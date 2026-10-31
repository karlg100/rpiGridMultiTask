"""AiDot floods: settings, the row renderer, what reaches Home Assistant, and the HTTP layer."""

import json
import random
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from haunt import floods
from haunt.floods import FloodAgent, HAError, HomeAssistant, Row, _InlineExecutor, light_state, parse_setting

ENTS = ["light.flood_%d" % i for i in range(1, 16)]


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


class FakeHA:
    def __init__(self, ents=ENTS, fail=None, features=0, unavailable=(), bad=()):
        self.ents = list(ents)
        self.calls = []
        self.fail = fail
        self.features = features
        self.unavailable = set(unavailable)
        self.bad = set(bad)              # a call that includes one of these fails
        self.light = {}

    def states(self):
        return {e: {"entity_id": e, "state": "unavailable" if e in self.unavailable else "on",
                    "attributes": {"supported_features": self.features}} for e in self.ents}

    def turn_on(self, entities, rgb, brightness, transition=None):
        if self.fail:
            raise self.fail
        if self.bad & set(entities):
            raise HAError("500 from the integration", 500)
        self.calls.append(("on", tuple(entities), tuple(rgb), brightness, transition))
        for e in entities:
            self.light[e] = (tuple(rgb), brightness)

    def turn_off(self, entities, transition=None):
        if self.fail:
            raise self.fail
        self.calls.append(("off", tuple(entities), None, None, transition))
        for e in entities:
            self.light[e] = None


def make(ha=None, rate=1000.0, workers=4, idle="off", **kw):
    clock = Clock()
    clock.t = 100.0
    ha = ha or FakeHA()
    bus = Bus()
    agent = FloodAgent({"floods": {"entities": list(ENTS), "topic": "haunt/floods/floods"}}, ha, bus,
                       clock=clock, rng=random.Random(4), rate=rate, workers=workers, fps=5,
                       idle=idle, executor=_InlineExecutor(), **kw)
    return agent, ha, bus, clock


def run(agent, clock, seconds, step=0.05):
    end = clock.t + seconds
    while clock.t < end:
        agent.tick()
        clock.t += step


def go(agent, setting):
    agent.handle("haunt/director/online", "1")
    agent.handle("haunt/director/state", json.dumps({"phase": "playing"}))
    agent.handle("haunt/floods/floods/set", json.dumps(parse_setting(setting)))


# --------------------------------------------------------------------------
# settings
# --------------------------------------------------------------------------

def test_parse_simple_forms():
    assert parse_setting("off") == {"on": False, "color": None}
    assert parse_setting(None)["on"] is False
    s = parse_setting("#FF6A00")
    assert s["colors"] == ["#ff6a00"] and s["animation"] == "solid" and s["bri"] == 255
    s = parse_setting({"colors": ["#ff0000", "#0000ff"], "pattern": "blocks", "animation": "chase",
                       "width": 4, "direction": "bounce", "period": 3, "low": 0.1})
    assert s["pattern"] == "blocks" and s["width"] == 4 and s["direction"] == "bounce"
    assert parse_setting(s) == s                       # already normalised: unchanged


@pytest.mark.parametrize("bad", [
    {"color": "#ff0000", "effect": "candle"},
    {"color": "#ff0000", "animation": "strobe"},
    {"color": "#ff0000", "pattern": "zigzag"},
    {"color": "#ff0000", "bri": 300},
    {"color": "#ff0000", "period": 0.1},
    {"color": "#ff0000", "direction": "up"},
])
def test_parse_rejects(bad):
    with pytest.raises(ValueError):
        parse_setting(bad)


def test_light_state():
    assert light_state(None, 255) is None
    assert light_state("#000000", 255) is None
    assert light_state("#ff6a00", 255) == ((255, 106, 0), 255)
    rgb, b = light_state("#800000", 255)
    assert rgb == (255, 0, 0) and 124 <= b <= 132     # a dark colour is a dimmer light
    assert light_state("#ffffff", 0.4) is None


# --------------------------------------------------------------------------
# the row
# --------------------------------------------------------------------------

def frame(setting, t=0.0, n=15):
    r = Row(n, random.Random(1))
    r.start(parse_setting(setting), 0.0)
    return r, r.frame(t)


def test_patterns():
    _, f = frame({"colors": ["#ff0000", "#00ff00"]})
    assert [c for c, _ in f[:4]] == ["#ff0000", "#00ff00", "#ff0000", "#00ff00"]
    _, f = frame({"colors": ["#ff0000", "#00ff00"], "pattern": "blocks"})
    cols = [c for c, _ in f]
    assert cols[:7] == ["#ff0000"] * 7 and cols[8:] == ["#00ff00"] * 7     # Window half / Wall half
    _, f = frame({"colors": ["#ff0000", "#0000ff"], "pattern": "gradient"})
    assert f[0][0] == "#ff0000" and f[-1][0] == "#0000ff" and f[7][0] not in ("#ff0000", "#0000ff")


def test_drift_moves_right():
    r, f0 = frame({"colors": ["#ff0000", "#00ff00", "#0000ff"], "animation": "drift", "period": 2})
    f1 = r.frame(2.1)
    assert [c for c, _ in f1][1:] == [c for c, _ in f0][:-1]


def test_chase_runs_along_the_row():
    r, _ = frame({"color": "#ff0000", "animation": "chase", "period": 3, "width": 2, "low": 0.0})
    heads = []
    for k in range(15):
        f = r.frame(k * 3 / 15 + 0.01)
        heads.append(max(range(15), key=lambda i: f[i][1]))
    assert heads == list(range(15))
    r, _ = frame({"color": "#ff0000", "animation": "chase", "period": 3, "direction": "left", "low": 0.0})
    f = r.frame(0.01)
    assert max(range(15), key=lambda i: f[i][1]) == 14


def test_chase_bounce_turns_round():
    r, _ = frame({"color": "#ff0000", "animation": "chase", "period": 2, "direction": "bounce", "low": 0.0})
    seq = []
    for k in range(29):
        f = r.frame(k * 2 / 28 + 0.001)
        seq.append(max(range(15), key=lambda i: f[i][1]))
    assert seq[0] == 0 and max(seq) == 14 and seq[-1] <= 1


def test_lightning_flashes_and_returns_dim():
    r, f = frame({"color": "#300050", "animation": "lightning", "period": 2, "bri": 200, "low": 0.1})
    seen_flash = False
    for k in range(200):
        f = r.frame(k * 0.05)
        if any(c == floods.DEFAULT_FLASH for c, _ in f):
            seen_flash = True
    assert seen_flash
    assert all(b <= 200 * 0.1 + 1e-6 or c == floods.DEFAULT_FLASH for c, b in r.frame(1000.0))


def test_off_frame():
    _, f = frame("off")
    assert all(c is None for c, _ in f)


# --------------------------------------------------------------------------
# the agent
# --------------------------------------------------------------------------

def test_solid_is_one_call_for_the_whole_row():
    agent, ha, bus, clock = make()
    go(agent, "#ff6a00")
    run(agent, clock, 1.0)
    on = [c for c in ha.calls if c[0] == "on"]
    assert len(on) == 1 and set(on[0][1]) == set(ENTS)
    run(agent, clock, 2.0)
    assert len([c for c in ha.calls if c[0] == "on"]) == 1     # nothing resent when nothing changes


def test_off_when_show_stops_and_when_director_goes():
    agent, ha, bus, clock = make()
    go(agent, "#ff6a00")
    run(agent, clock, 0.5)
    agent.handle("haunt/director/state", json.dumps({"phase": "stopped"}))
    run(agent, clock, 0.5)
    assert all(ha.light[e] is None for e in ENTS)
    agent.handle("haunt/director/state", json.dumps({"phase": "playing"}))
    run(agent, clock, 0.5)
    assert all(ha.light[e] is not None for e in ENTS)
    agent.handle("haunt/director/online", "0")
    run(agent, clock, 0.5)
    assert all(ha.light[e] is None for e in ENTS)


def test_idle_leave_does_not_touch_the_lights():
    agent, ha, bus, clock = make(idle="leave")
    agent.handle("haunt/director/online", "0")
    run(agent, clock, 3.0)
    assert ha.calls == []


def test_no_blink_while_waiting_for_retained_messages():
    agent, ha, bus, clock = make()
    run(agent, clock, 1.0)
    assert ha.calls == []          # does not switch everything off before hearing the director
    go(agent, "#00ff00")
    run(agent, clock, 0.5)
    assert ha.calls and ha.calls[0][0] == "on"


def test_chase_sends_only_changes():
    agent, ha, bus, clock = make()
    go(agent, {"color": "#ff0000", "animation": "chase", "period": 3, "width": 1, "low": 0.0})
    run(agent, clock, 0.3)
    n0 = len(ha.calls)
    run(agent, clock, 3.0)
    per_step = (len(ha.calls) - n0) / (3.0 * 5)
    assert per_step <= 3.0          # head on, previous off: about two calls a frame, not fifteen


def test_rate_limit_keeps_latest_and_is_fair():
    agent, ha, bus, clock = make(rate=5.0, workers=1)
    go(agent, {"color": "#ff0000", "animation": "flicker", "period": 0.5})
    run(agent, clock, 6.0)
    assert len(ha.calls) <= 5 * 6 + 5
    touched = set(e for c in ha.calls for e in c[1])
    assert touched == set(ENTS)     # every light gets its turn, none starved


def test_errors_back_off_and_recover():
    ha = FakeHA(fail=HAError("down"))
    agent, ha, bus, clock = make(ha=ha)
    go(agent, "#ff6a00")
    run(agent, clock, 1.0)
    assert agent.hold_until > clock.t - 1.0
    ha.fail = None
    run(agent, clock, 12.0)
    assert all(ha.light.get(e) == ((255, 106, 0), 255) for e in ENTS)


def test_transition_only_when_supported():
    agent, ha, bus, clock = make()
    go(agent, {"color": "#ff6a00", "transition": 2})
    run(agent, clock, 0.5)
    assert all(c[4] is None for c in ha.calls)
    agent2, ha2, _b, clock2 = make(ha=FakeHA(features=floods.TRANSITION_FEATURE))
    go(agent2, {"color": "#ff6a00", "transition": 2})
    run(agent2, clock2, 0.5)
    assert ha2.calls[0][4] == 2.0


def test_missing_light_is_skipped_and_reported():
    ents = [e for e in ENTS if e != "light.flood_13"]
    agent, ha, bus, clock = make(ha=FakeHA(ents=ents))
    go(agent, "#ff0000")
    run(agent, clock, 0.5)
    st = [p for t, p, r in bus.sent if t == "haunt/floods/floods/status"]
    assert st[-1] == "ok: 14 of 15 lights; not in HA: 13"
    sent_to = set(e for c in ha.calls for e in c[1])
    assert sent_to == set(ents)
    # it turns up later (re-paired): picked up at the next check and given the scene
    ha.ents = list(ENTS)
    run(agent, clock, 31.0)
    assert ha.light.get("light.flood_13") == ((255, 0, 0), 255)


def test_unavailable_light_is_skipped_until_it_returns():
    agent, ha, bus, clock = make(ha=FakeHA(unavailable={"light.flood_2"}))
    go(agent, "#00ff00")
    run(agent, clock, 0.5)
    assert "light.flood_2" not in ha.light
    ha.unavailable = set()
    run(agent, clock, 31.0)
    assert ha.light["light.flood_2"] == ((0, 255, 0), 255)


def test_one_bad_light_does_not_sink_the_rest():
    agent, ha, bus, clock = make(ha=FakeHA(bad={"light.flood_7"}))
    go(agent, "#ff6a00")
    run(agent, clock, 15.0)
    good = [e for e in ENTS if e != "light.flood_7"]
    assert all(ha.light.get(e) == ((255, 106, 0), 255) for e in good)


def test_max_bri_caps_everything():
    agent, ha, bus, clock = make(max_bri=128)
    go(agent, {"color": "#ffffff", "bri": 255})
    run(agent, clock, 0.5)
    assert all(b <= 128 for c in ha.calls if c[0] == "on" for b in [c[3]])


# --------------------------------------------------------------------------
# config and the show file
# --------------------------------------------------------------------------

def test_load_config(tmp_path):
    p = tmp_path / "floods.yaml"
    p.write_text("home_assistant: http://192.168.1.244:8123\nrows:\n  floods:\n    entities: [%s]\n"
                 % ", ".join(ENTS))
    cfg = floods.load_config(str(p), need_mqtt=False)
    assert cfg["rows"]["floods"]["entities"] == ENTS
    assert cfg["rows"]["floods"]["topic"] == "haunt/floods/floods"
    assert cfg["idle"] == "off"
    p.write_text("rows:\n  floods: [switch.nope]\n")
    with pytest.raises(Exception):
        floods.load_config(str(p), need_mqtt=False)


def test_show_file_accepts_floods(tmp_path):
    from haunt.config import load_show
    from haunt import lights
    p = tmp_path / "show.yaml"
    p.write_text("""
players: {1: {name: Window}}
lights:
  floods: {type: floods}
scenes:
  - name: A
    master: 1
    players: {1: {file: a.mp4}}
    lights:
      floods: {colors: ["#ff6a00", "#5a00a0"], pattern: blocks, animation: chase}
""")
    show = load_show(str(p))
    cfg = show.lights["floods"]
    assert cfg["topic"] == "haunt/floods/floods"
    setting = show.scenes[0].lights["floods"]
    msgs = lights.messages(cfg, setting)
    assert msgs[0][0] == "haunt/floods/floods/set" and json.loads(msgs[0][1])["animation"] == "chase"
    bus = Bus()
    lights.apply(bus, cfg, setting)
    assert bus.sent[0][2] is True                  # retained, so a restarted agent catches up


# --------------------------------------------------------------------------
# HTTP layer against a pretend Home Assistant
# --------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def _reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer tok":
            return self._reply(401, {"message": "no"})
        self._reply(200, [{"entity_id": "light.flood_1", "state": "off", "attributes": {}}])

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        _Handler.seen.append((self.path, json.loads(self.rfile.read(n))))
        self._reply(200, [])


def test_http_client():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        ha = HomeAssistant("http://127.0.0.1:%d" % srv.server_port, "tok")
        assert "light.flood_1" in ha.states()
        ha.turn_on(["light.flood_1", "light.flood_2"], (255, 0, 0), 128)
        ha.turn_off(["light.flood_1"], 0.5)
        assert _Handler.seen[0] == ("/api/services/light/turn_on",
                                    {"entity_id": ["light.flood_1", "light.flood_2"],
                                     "rgb_color": [255, 0, 0], "brightness": 128})
        assert _Handler.seen[1][1] == {"entity_id": ["light.flood_1"], "transition": 0.5}
        bad = HomeAssistant("http://127.0.0.1:%d" % srv.server_port, "wrong")
        with pytest.raises(HAError) as ei:
            bad.states()
        assert ei.value.status == 401
    finally:
        srv.shutdown()


def test_fast_chase_lights_every_light_in_order():
    agent, ha, bus, clock = make(rate=1000.0)
    go(agent, {"color": "#20ff20", "animation": "chase", "width": 1, "period": 2, "low": 0.05})
    run(agent, clock, 2.0, step=0.02)
    heads = [c[1][0] for c in ha.calls if c[0] == "on" and c[3] == 255 and len(c[1]) == 1]
    order = [int(e.rsplit("_", 1)[1]) for e in heads]
    assert order[:15] == list(range(1, 16))
