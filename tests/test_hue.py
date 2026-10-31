"""Hue rooms: settings, what gets sent to the bridge and when, and the HTTP layer."""

import json
import random
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from haunt import hue
from haunt.hue import Bridge, Bulb, HueAgent, HueError, Room, parse_setting


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

class Bus:
    def __init__(self):
        self.connected = True
        self.subs = []
        self.sent = []

    def subscribe(self, p):
        self.subs.append(p)

    def publish(self, topic, payload, retain=False):
        self.sent.append((topic, payload, retain))


class Clock:
    t = 100.0

    def __call__(self):
        return self.t


class FakeBridge:
    def __init__(self, rooms=None, fail=None):
        self.rooms = rooms or {
            "Living Room": {"kind": "room", "group": "g-lr",
                            "lights": [Bulb("l1", "Lamp", True, {"candle", "fire"}),
                                       Bulb("l2", "Ceiling", True),
                                       Bulb("l3", "Old bulb", False)]},
            "Front bedroom": {"kind": "room", "group": "g-fb",
                              "lights": [Bulb("f1", "Bedside", True)]},
        }
        self.puts = []
        self.gets = 0
        self.fail = fail            # for puts
        self.get_fail = None
        # what the house had on before the show (CLIP v2 light resources)
        self.state = {}
        for info in self.rooms.values():
            for b in info["lights"]:
                r = {"id": b.id, "on": {"on": True}, "dimming": {"brightness": 40.0}}
                if b.color:
                    r["color"] = {"xy": {"x": 0.45, "y": 0.41}}
                    r["color_temperature"] = {"mirek": 370, "mirek_valid": True}
                if b.effects:
                    r["effects"] = {"status": "no_effect",
                                    "effect_values": ["no_effect"] + sorted(b.effects)}
                self.state[b.id] = r

    def inventory(self):
        return self.rooms

    def get(self, path):
        assert path == "/resource/light"
        if self.get_fail:
            raise self.get_fail
        self.gets += 1
        return list(self.state.values())

    def put(self, path, body):
        if self.fail:
            raise self.fail
        self.puts.append((path, body))
        return []


CFG = {"living_room": {"room": "Living room", "topic": "haunt/hue/living_room"},
       "front_bedroom": {"room": "Front bedroom", "topic": "haunt/hue/front_bedroom"}}


def make(bridge=None, running=True, rate=100.0):
    bus, clock, bridge = Bus(), Clock(), bridge or FakeBridge()
    a = HueAgent(CFG, bridge, bus, clock=clock, rng=random.Random(1), rate=rate, group_rate=100.0)
    a.handle("haunt/hue/control", "show")
    if running:
        a.handle("haunt/director/online", "1")
        a.handle("haunt/director/state", json.dumps({"phase": "running"}))
    return a, bus, clock, bridge


def setting(a, name, s):
    a.handle("haunt/hue/%s/set" % name, json.dumps(parse_setting(s)))


def run(a, clock, seconds, step=0.05):
    end = clock.t + seconds
    while clock.t < end:
        clock.t += step
        a.tick()


# --------------------------------------------------------------------------
# settings
# --------------------------------------------------------------------------

def test_parse_forms():
    assert parse_setting("off") == {"on": False, "color": None}
    assert parse_setting(False)["on"] is False
    s = parse_setting("#FF8800")
    assert s["colors"] == ["#ff8800"] and s["animation"] == "solid" and s["bri"] == 255
    s = parse_setting([255, 0, 0])
    assert s["color"] == "#ff0000"
    s = parse_setting({"colors": ["#ff0000", "#00ff00"], "animation": "Drift", "period": 5, "bri": 128})
    assert s["animation"] == "drift" and s["period"] == 5.0 and s["bri"] == 128
    s = parse_setting({"color": "#ff6a00", "effect": "Candle"})
    assert s["effect"] == "candle"
    assert parse_setting(parse_setting({"color": "#123456", "animation": "pulse"})) == \
        parse_setting({"color": "#123456", "animation": "pulse"})        # idempotent


@pytest.mark.parametrize("bad, msg", [
    ({"color": "#ff0000", "speed": 3}, "unknown Hue setting"),
    ({"animation": "strobe"}, "animation"),
    ({"effect": "disco"}, "effect"),
    ({"bri": 300}, "bri"),
    ({"animation": "pulse", "period": 1}, "at least"),
    ({"colors": []}, "colors"),
    ({"low": 2}, "low"),
])
def test_parse_rejects(bad, msg):
    with pytest.raises(ValueError, match=msg):
        parse_setting(bad)


def test_xy():
    x, y, lvl = hue.rgb_to_xy("#ff0000")
    assert x > 0.65 and lvl == 1.0
    assert hue.rgb_to_xy("#000000")[2] == 0.0
    assert hue.rgb_to_xy("#800000")[2] == pytest.approx(128 / 255)


# --------------------------------------------------------------------------
# show running or not
# --------------------------------------------------------------------------

def test_nothing_until_rooms_known_then_room_matching_is_forgiving():
    a, bus, clock, br = make()
    a.tick()
    assert set(a.rooms) == {"living_room", "front_bedroom"}
    assert a.rooms["living_room"].name == "Living Room"
    statuses = {t: p for t, p, r in bus.sent if t.endswith("/status")}
    assert statuses["haunt/hue/living_room/status"].startswith("ok")


def test_missing_room_reports_error():
    rooms = {"Kitchen": {"kind": "room", "group": "g", "lights": [Bulb("k")]}}
    a, bus, clock, br = make(FakeBridge(rooms))
    a.tick()
    assert a.rooms == {}
    statuses = {t: p for t, p, r in bus.sent}
    assert "Kitchen" in statuses["haunt/hue/living_room/status"]


def test_solid_colour_uses_one_room_command():
    a, bus, clock, br = make()
    setting(a, "living_room", "#ff0000")
    a.tick()
    lr = [(p, b) for p, b in br.puts if "g-lr" in p]
    assert len(lr) == 1
    body = lr[0][1]
    assert body["on"] == {"on": True} and body["dimming"]["brightness"] == 100.0
    assert body["color"]["xy"]["x"] > 0.65
    assert not any("/light/l" in p for p, b in br.puts)


def test_off_when_show_stops_and_when_director_goes():
    a, bus, clock, br = make()
    setting(a, "front_bedroom", "#00ff00")
    a.tick()
    assert br.puts[-1][1]["on"] == {"on": True}
    a.handle("haunt/director/state", json.dumps({"phase": "stopped"}))
    a.tick()
    assert br.puts[-1] == ("/resource/light/f1", {"on": {"on": False}, "dynamics": {"duration": 400}})
    a.handle("haunt/director/state", json.dumps({"phase": "running"}))
    a.tick()
    assert br.puts[-1][1]["on"] == {"on": True}            # retained setting comes back
    a.handle("haunt/director/online", "0")
    a.tick()
    assert br.puts[-1][1]["on"] == {"on": False}


def test_dark_until_director_has_said_anything():
    a, bus, clock, br = make(running=False)
    setting(a, "living_room", "#ff0000")
    a.tick()
    assert all(b["on"] == {"on": False} for p, b in br.puts)


def test_white_only_bulb_gets_no_colour():
    a, bus, clock, br = make()
    setting(a, "living_room", {"colors": ["#ff0000", "#0000ff"]})
    a.tick()
    by = {p: b for p, b in br.puts}
    assert "color" in by["/resource/light/l1"] and "color" not in by["/resource/light/l3"]
    assert by["/resource/light/l2"]["color"] != by["/resource/light/l1"]["color"]   # spread


# --------------------------------------------------------------------------
# animations
# --------------------------------------------------------------------------

def test_native_effect_where_supported_flicker_elsewhere_and_cleared_after():
    a, bus, clock, br = make()
    setting(a, "living_room", {"color": "#ff6a00", "effect": "candle"})
    a.tick()
    by = {p: b for p, b in br.puts}
    assert by["/resource/light/l1"]["effects"] == {"effect": "candle"}
    assert "effects" not in by.get("/resource/light/l2", {})
    assert a.rooms["living_room"].anim == "flicker"
    br.puts.clear()
    run(a, clock, 3)
    flick = [p for p, b in br.puts]
    assert "/resource/light/l2" in flick and "/resource/light/l3" in flick
    assert "/resource/light/l1" not in flick                 # the bulb does its own candle
    br.puts.clear()
    setting(a, "living_room", "#0000ff")
    a.tick()
    by = {p: b for p, b in br.puts}
    assert by["/resource/light/l1"]["effects"] == {"effect": "no_effect"}


def test_drift_rotates_colours():
    a, bus, clock, br = make()
    setting(a, "front_bedroom", {"colors": ["#ff0000", "#00ff00", "#0000ff"], "animation": "drift",
                                 "period": 2, "transition": 0})
    a.tick()
    first = br.puts[-1][1]["color"]
    br.puts.clear()
    run(a, clock, 2.1)
    assert len(br.puts) == 1 and br.puts[0][1]["color"] != first
    assert br.puts[0][1]["dynamics"]["duration"] == 2000
    run(a, clock, 4)
    assert len(br.puts) == 3


def test_pulse_alternates_on_the_room_group():
    a, bus, clock, br = make()
    setting(a, "living_room", {"color": "#800080", "animation": "pulse", "period": 2,
                               "transition": 0})
    a.tick()
    br.puts.clear()
    run(a, clock, 4.05)
    assert all("grouped_light/g-lr" in p for p, b in br.puts)
    levels = [b["dimming"]["brightness"] for p, b in br.puts]
    assert len(levels) >= 4 and levels[0] > levels[1] < levels[2]


def test_lightning_flashes_then_goes_dark():
    a, bus, clock, br = make()
    setting(a, "living_room", {"color": "#202060", "animation": "lightning", "period": 2,
                               "transition": 0})
    a.tick()
    base = [b for p, b in br.puts if "g-lr" in p][-1]["dimming"]["brightness"]
    br.puts.clear()
    run(a, clock, 6)
    bright = [b for p, b in br.puts if b.get("dimming", {}).get("brightness", 0) > 60]
    dark = [b for p, b in br.puts if 0 < b.get("dimming", {}).get("brightness", 0) <= base + 0.1]
    assert bright and dark
    assert bright[0]["dynamics"]["duration"] == 0


def test_flicker_rate_is_limited_and_queue_coalesces():
    a, bus, clock, br = make(rate=2.0)
    setting(a, "living_room", {"color": "#ff4400", "animation": "flicker", "period": 0.2,
                               "transition": 0})
    run(a, clock, 10, step=0.02)
    assert len(br.puts) <= 2 * 10 + 3
    assert len(a.queue) <= 3                       # one entry per bulb at most


# --------------------------------------------------------------------------
# bridge trouble
# --------------------------------------------------------------------------

def test_unreachable_bridge_backs_off_then_reapplies():
    a, bus, clock, br = make()
    setting(a, "front_bedroom", "#ff0000")
    a.tick()
    br.fail = HueError("down", 0)
    setting(a, "front_bedroom", "#00ff00")
    a.tick()
    assert a.hold_until > clock.t
    br.fail = None
    n = len(br.puts)
    run(a, clock, 6)
    assert len(br.puts) > n and br.puts[-1][1]["color"]["xy"]["y"] > 0.6     # green arrived


def test_429_retries_same_command():
    a, bus, clock, br = make()
    setting(a, "front_bedroom", "#ff0000")
    br.fail = HueError("slow down", 429)
    a.tick()
    assert len(a.queue) == 2 and a.hold_until > clock.t      # nothing dropped, waiting 1 s
    br.fail = None
    run(a, clock, 1.2)
    assert {p for p, b in br.puts} == {"/resource/grouped_light/g-lr", "/resource/light/f1"}
    assert not a.queue


# --------------------------------------------------------------------------
# the real HTTP layer, against a local HTTPS stand-in for the bridge
# --------------------------------------------------------------------------

V2 = {
    "/clip/v2/resource/light": [
        {"id": "L1", "metadata": {"name": "Lamp"}, "color": {}, "effects": {"effect_values": ["no_effect", "candle"]}},
        {"id": "L2", "metadata": {"name": "Plain"}},
    ],
    "/clip/v2/resource/device": [{"id": "D1", "services": [{"rid": "L1", "rtype": "light"}]}],
    "/clip/v2/resource/room": [{"id": "R1", "metadata": {"name": "Living room"},
                                "children": [{"rid": "D1", "rtype": "device"}],
                                "services": [{"rid": "G1", "rtype": "grouped_light"}]}],
    "/clip/v2/resource/zone": [{"id": "Z1", "metadata": {"name": "Porch"},
                                "children": [{"rid": "L2", "rtype": "light"}], "services": []}],
}


@pytest.fixture(scope="module")
def fake_bridge(tmp_path_factory):
    d = tmp_path_factory.mktemp("cert")
    try:
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                        "-subj", "/CN=bridge", "-keyout", str(d / "k.pem"), "-out", str(d / "c.pem")],
                       check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("openssl not available")
    seen = []
    state = {"button": False}

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, code, doc):
            raw = json.dumps(doc).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.headers.get("hue-application-key") != "KEY":
                return self._send(403, {"errors": [{"description": "unauthorized user"}]})
            self._send(200, {"data": V2.get(self.path, []), "errors": []})

        def do_PUT(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, body))
            if "bad" in self.path:
                return self._send(404, {"errors": [{"description": "not found"}]})
            self._send(200, {"data": [{"rid": "x"}], "errors": []})

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            if state["button"]:
                return self._send(200, [{"success": {"username": "NEWKEY", "clientkey": "C"}}])
            state["button"] = True          # "pressed" for the next try
            self._send(200, [{"error": {"type": 101, "description": "link button not pressed"}}])

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(d / "c.pem"), str(d / "k.pem"))
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv, seen
    srv.shutdown()


def _bridge(srv, key="KEY"):
    return Bridge("127.0.0.1", key, port=srv.server_address[1])


def test_http_inventory_put_and_errors(fake_bridge):
    srv, seen = fake_bridge
    b = _bridge(srv)
    inv = b.inventory()
    assert set(inv) == {"Living room", "Porch"}
    lr = inv["Living room"]
    assert lr["group"] == "G1" and [x.id for x in lr["lights"]] == ["L1"]
    assert lr["lights"][0].effects == {"candle"} and lr["lights"][0].color
    assert inv["Porch"]["lights"][0].color is False
    b.put("/resource/light/L1", {"on": {"on": True}})
    conn = b.conn
    b.put("/resource/light/L1", {"on": {"on": False}})
    assert b.conn is conn                                    # kept alive
    assert seen[-2:] == [("/clip/v2/resource/light/L1", {"on": {"on": True}}),
                         ("/clip/v2/resource/light/L1", {"on": {"on": False}})]
    with pytest.raises(HueError) as e:
        b.put("/resource/light/bad", {})
    assert e.value.status == 404 and "not found" in str(e.value)
    with pytest.raises(HueError, match="unauthorized"):
        _bridge(srv, key="WRONG").get("/resource/light")


def test_http_unreachable_is_status_0():
    b = Bridge("127.0.0.1", "KEY", timeout=0.5, port=9)
    with pytest.raises(HueError) as e:
        b.get("/resource/light")
    assert e.value.status == 0


def test_pairing_waits_for_the_button(fake_bridge, monkeypatch):
    srv, seen = fake_bridge
    monkeypatch.setattr(hue.time, "sleep", lambda s: None)
    assert hue.pair("127.0.0.1", wait=5, port=srv.server_address[1]) == "NEWKEY"


def test_agent_end_to_end_over_https(fake_bridge):
    srv, seen = fake_bridge
    b = _bridge(srv)
    seen.clear()
    bus, clock = Bus(), Clock()
    a = HueAgent({"living_room": {"room": "living_room", "topic": "haunt/hue/living_room"}},
                 b, bus, clock=clock)
    a.handle("haunt/hue/control", "show")
    a.handle("haunt/director/online", "1")
    a.handle("haunt/director/state", '{"phase": "running"}')
    a.handle("haunt/hue/living_room/set", json.dumps({"color": "#ff6a00", "effect": "candle"}))
    a.tick()
    assert seen == [("/clip/v2/resource/light/L1",
                     {"on": {"on": True}, "dimming": {"brightness": 100.0},
                      "color": {"xy": {"x": seen[0][1]["color"]["xy"]["x"],
                                       "y": seen[0][1]["color"]["xy"]["y"]}},
                      "dynamics": {"duration": 1000}, "effects": {"effect": "candle"}})]
    a.all_off(wait=1)
    assert seen[-1][1]["on"] == {"on": False} and seen[-1][1]["effects"] == {"effect": "no_effect"}


# --------------------------------------------------------------------------
# director -> bus -> haunt hue, on the simulated show
# --------------------------------------------------------------------------

def test_director_drives_hue_rooms_through_the_show():
    import copy
    from sim import SHOW, Sim
    show = copy.deepcopy(SHOW)
    show["lights"]["living_room"] = {"type": "hue"}
    show["scenes"][0]["lights"]["living_room"] = {"color": "#ff6a00", "effect": "candle"}
    show["scenes"][1]["lights"]["living_room"] = "#00ff00"
    sim = Sim(show)
    br = FakeBridge()
    bus = sim.hub.client()
    agent = HueAgent({"living_room": {"room": "Living room", "topic": "haunt/hue/living_room"}},
                     br, bus, clock=sim.clock, rng=random.Random(2), rate=100, group_rate=100)
    sim.agents["hue"] = agent            # stepped along with the players

    def lr_state():
        return agent.applied.get("living_room") or {}

    sim.run_until(lambda: lr_state().get("effect") == "candle")
    assert any(b.get("effects") == {"effect": "candle"} for p, b in br.puts)
    sim.run_until(lambda: lr_state().get("color") == "#00ff00", limit=60)
    assert sim.hub.retained["haunt/hue/living_room/set"]          # retained for restarts
    sim.cmd("stop")
    sim.run_until(lambda: sim.director.phase == "stopped")
    sim.run(0.5)
    assert lr_state()["on"] is False and br.puts[-1][1]["on"] == {"on": False}
    sim.cmd("start")
    sim.run_until(lambda: lr_state().get("on"), limit=30)


# --------------------------------------------------------------------------
# accents: floor and bulbs by name
# --------------------------------------------------------------------------

OUTDOOR = {
    "Outside": {"kind": "room", "group": "g-out",
                "lights": [Bulb("p1", "Porch left"), Bulb("p2", "Porch right"),
                           Bulb("lp", "Lamp post", False)]},
}


def test_bulbs_by_name_and_floor():
    br = FakeBridge(OUTDOOR)
    cfg = {"porch": {"lights": ["porch left", "Porch_Right"], "floor": 30.0, "topic": "haunt/hue/porch"},
           "lamp_post": {"lights": ["Lamp post"], "floor": 25.0, "topic": "haunt/hue/lamp_post"}}
    bus, clock = Bus(), Clock()
    a = HueAgent(cfg, br, bus, clock=clock, rng=random.Random(3), rate=100, group_rate=100)
    a.handle("haunt/hue/control", "show")
    a.handle("haunt/director/online", "1")
    a.handle("haunt/director/state", '{"phase": "running"}')
    a.handle("haunt/hue/porch/set", json.dumps({"color": "#0a2a10", "animation": "lightning", "period": 2,
                                                "low": 0.1, "transition": 0}))
    a.handle("haunt/hue/lamp_post/set", json.dumps({"color": "#000000"}))
    a.tick()
    assert [b.id for b in a.rooms["porch"].bulbs] == ["p1", "p2"]
    assert a.rooms["porch"].group is None                    # never the whole Outside room
    run(a, clock, 8)
    porch = [b for p, b in br.puts if p.endswith(("/p1", "/p2"))]
    assert porch and all(b["on"] == {"on": True} and b["dimming"]["brightness"] >= 30 for b in porch)
    assert any(b["dimming"]["brightness"] > 60 for b in porch)          # flashes still flash
    lamp = [b for p, b in br.puts if p.endswith("/lp")]
    assert lamp[0] == {"on": {"on": True}, "dimming": {"brightness": 25.0}, "dynamics": {"duration": 1000}}
    assert not any("grouped_light/g-out" in p for p, b in br.puts)
    a.handle("haunt/director/state", '{"phase": "stopped"}')            # floor never keeps it on
    a.tick()
    assert all(b["on"] == {"on": False} for p, b in br.puts[-3:])


def test_unknown_bulb_name_is_reported():
    br = FakeBridge(OUTDOOR)
    bus = Bus()
    a = HueAgent({"porch": {"lights": ["Porch lft"], "topic": "haunt/hue/porch"}}, br, bus, clock=Clock())
    a.handle("haunt/hue/control", "show")
    a.handle("haunt/director/online", "1")
    a.tick()
    status = [p for t, p, r in bus.sent if t == "haunt/hue/porch/status"][-1]
    assert "Porch lft" in status and "Porch left" in status


def test_hue_config_rooms(tmp_path):
    f = tmp_path / "hue.yaml"
    f.write_text("rooms:\n  porch: {lights: Porch left, floor: 30}\n  lr: Living room\n")
    cfg = hue.load_config(str(f), need_mqtt=False)
    assert cfg["rooms"]["porch"]["lights"] == ["Porch left"] and cfg["rooms"]["porch"]["floor"] == 30.0
    assert cfg["rooms"]["lr"]["room"] == "Living room" and cfg["rooms"]["lr"]["topic"] == "haunt/hue/lr"
    f.write_text("rooms:\n  porch: {lights: [x], floor: 150}\n")
    with pytest.raises(Exception, match="floor"):
        hue.load_config(str(f), need_mqtt=False)
    f.write_text("rooms:\n  porch: {bulbs: [x]}\n")
    with pytest.raises(Exception, match="unknown"):
        hue.load_config(str(f), need_mqtt=False)


# --------------------------------------------------------------------------
# released to the house (console "h")
# --------------------------------------------------------------------------

def test_release_puts_rooms_back_and_stops_driving_them():
    a, bus, clock, br = make()
    setting(a, "living_room", {"colors": ["#ff0000", "#00ff00"], "animation": "drift", "period": 2})
    setting(a, "front_bedroom", {"color": "#ff6a00", "effect": "candle"})
    a.tick()
    assert br.gets == 1                                  # remembered before the first change
    run(a, clock, 5)
    br.puts.clear()
    a.handle("haunt/hue/control", "released")
    run(a, clock, 1)
    back = dict(br.puts)
    assert set(back) == {"/resource/light/l1", "/resource/light/l2", "/resource/light/l3",
                         "/resource/light/f1"}
    assert back["/resource/light/l1"] == {"on": {"on": True}, "dimming": {"brightness": 40.0},
                                          "color_temperature": {"mirek": 370},
                                          "effects": {"effect": "no_effect"},
                                          "dynamics": {"duration": 1000}}
    assert back["/resource/light/l3"] == {"on": {"on": True}, "dimming": {"brightness": 40.0},
                                          "dynamics": {"duration": 1000}}
    br.puts.clear()
    setting(a, "living_room", "#0000ff")                 # the show carries on without them
    a.handle("haunt/director/state", json.dumps({"phase": "stopped"}))
    run(a, clock, 5)
    a.all_off(wait=0.1)
    assert br.puts == []
    assert [p for t, p, r in bus.sent if t == "haunt/hue/living_room/status"][-1] == "released to the house"


def test_taken_back_remembers_again_and_resumes():
    a, bus, clock, br = make()
    setting(a, "living_room", "#ff0000")
    run(a, clock, 1)
    a.handle("haunt/hue/control", "released")
    run(a, clock, 1)
    br.state["l1"]["dimming"]["brightness"] = 77.0      # someone used the lights meanwhile
    br.puts.clear()
    a.handle("haunt/hue/control", "show")
    run(a, clock, 1)
    assert br.gets == 2
    assert ("/resource/grouped_light/g-lr", br.puts[0][1]) == br.puts[0] and \
        br.puts[0][1]["color"]                           # the show's red again
    a.handle("haunt/hue/control", "released")
    br.puts.clear()
    run(a, clock, 1)
    assert dict(br.puts)["/resource/light/l1"]["dimming"] == {"brightness": 77.0}


def test_restart_while_released_never_touches_the_rooms():
    bus, clock, br = Bus(), Clock(), FakeBridge()
    a = HueAgent(CFG, br, bus, clock=clock, rate=100, group_rate=100)
    a.handle("haunt/director/online", "1")
    a.handle("haunt/director/state", json.dumps({"phase": "stopped"}))
    run(a, clock, 2)                                     # control not heard yet: waits
    assert br.puts == [] and br.gets == 0
    a.handle("haunt/hue/control", "released")            # the retained message
    run(a, clock, 5)
    a.all_off(wait=0.1)
    assert br.puts == [] and br.gets == 0


def test_no_control_message_at_all_takes_over_after_a_moment():
    bus, clock, br = Bus(), Clock(), FakeBridge()
    a = HueAgent(CFG, br, bus, clock=clock, rate=100, group_rate=100)
    run(a, clock, 2)
    assert br.puts == []
    run(a, clock, 2)
    assert br.puts and all(b["on"] == {"on": False} for p, b in br.puts)   # no show: dark


def test_unreadable_lights_hold_off_rather_than_lose_the_house_state():
    a, bus, clock, br = make()
    br.get_fail = HueError("bridge 1.2.3.4: timed out", 0)
    setting(a, "living_room", "#ff0000")
    run(a, clock, 1)
    assert br.puts == []
    br.get_fail = None
    run(a, clock, 6)
    assert br.puts and br.gets == 1


def test_restore_body_forms():
    rb = hue.restore_body
    assert rb({"id": "x", "on": {"on": False}}) == {"on": {"on": False}, "dynamics": {"duration": 1000}}
    assert rb({"id": "x", "on": {"on": True}, "dimming": {"brightness": 12.5},
               "color": {"xy": {"x": 0.3, "y": 0.2}},
               "color_temperature": {"mirek": None, "mirek_valid": False},
               "effects": {"status": "candle", "effect_values": ["no_effect", "candle"]}}) == \
        {"on": {"on": True}, "dimming": {"brightness": 12.5}, "color": {"xy": {"x": 0.3, "y": 0.2}},
         "effects": {"effect": "candle"}, "dynamics": {"duration": 1000}}


def test_director_hue_command_is_retained_persisted_and_toggles(tmp_path):
    from sim import Sim
    path = str(tmp_path / "show.state.json")
    sim = Sim(state_path=path)
    assert sim.hub.retained["haunt/hue/control"] == "show"
    sim.cmd("hue")
    sim.run(0.2)
    assert sim.hub.retained["haunt/hue/control"] == "released"
    assert sim.director.snapshot()["hue"] == "released"
    sim.director._save_state()
    again = Sim(state_path=path)
    assert again.director.hue is False and again.hub.retained["haunt/hue/control"] == "released"
    again.cmd("hue", value=True)
    again.run(0.2)
    assert again.hub.retained["haunt/hue/control"] == "show"


# --------------------------------------------------------------------------
# full: true (indoor rooms at full brightness)
# --------------------------------------------------------------------------

def test_full_colour_keeps_hue_drops_darkness():
    assert hue.full_color("#600000") == "#ff0000"
    assert hue.full_color("#000000") == "#ffffff"
    assert hue.full_color("#20ff40") == "#20ff40"
    for c in ("#0a1a40", "#5a00a0", "#a00060"):
        x1, y1, _ = hue.rgb_to_xy(c)
        x2, y2, lvl = hue.rgb_to_xy(hue.full_color(c))
        assert abs(x1 - x2) < 0.001 and abs(y1 - y2) < 0.001 and lvl == 1.0


def test_full_room_ignores_bri_and_dark_colours_but_still_pulses():
    cfg = {"living_room": dict(CFG["living_room"], full=True), "front_bedroom": CFG["front_bedroom"]}
    bus, clock, br = Bus(), Clock(), FakeBridge()
    a = HueAgent(cfg, br, bus, clock=clock, rng=random.Random(1), rate=100, group_rate=100)
    for t, p in (("haunt/hue/control", "show"), ("haunt/director/online", "1"),
                 ("haunt/director/state", '{"phase": "running"}')):
        a.handle(t, p)
    setting(a, "living_room", {"color": "#600000", "bri": 110})
    setting(a, "front_bedroom", {"color": "#600000", "bri": 110})
    a.tick()
    by = dict(br.puts)
    assert by["/resource/grouped_light/g-lr"]["dimming"] == {"brightness": 100.0}
    assert by["/resource/light/f1"]["dimming"]["brightness"] < 20            # not full: as the show says
    br.puts.clear()
    setting(a, "living_room", {"color": "#5a00a0", "animation": "pulse", "period": 2, "low": 0.25})
    run(a, clock, 4)
    levels = {b["dimming"]["brightness"] for p, b in br.puts if p.endswith("g-lr") and "dimming" in b}
    assert levels == {100.0, 25.0}


def test_hue_config_full(tmp_path):
    f = tmp_path / "hue.yaml"
    f.write_text("rooms:\n  lr: {room: Living room, full: true}\n  p: Porch\n")
    cfg = hue.load_config(str(f), need_mqtt=False)
    assert cfg["rooms"]["lr"]["full"] is True and cfg["rooms"]["p"]["full"] is False
    f.write_text("rooms:\n  lr: {room: Living room, full: 1}\n")
    with pytest.raises(Exception, match="full"):
        hue.load_config(str(f), need_mqtt=False)
