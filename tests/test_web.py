"""The phone console: state out, commands in, over real HTTP."""

import json
import threading
import time
import urllib.request

import pytest

from haunt.topics import Topics
from haunt.web import WebApp, make_handler, _png, load_page
from sim import Sim

from http.server import ThreadingHTTPServer


@pytest.fixture
def web():
    sim = Sim()
    bus = sim.hub.client()
    bus.subscribe("haunt/#")
    app = WebApp(bus, Topics("haunt"), clock=sim.clock)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app, load_page(), _png(32)))
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % httpd.server_address[1]
    yield sim, app, base
    app.stop()
    httpd.shutdown()


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.headers.get("Content-Type"), r.read()


def post(url, body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_state_shows_the_show(web):
    sim, app, base = web
    sim.run_until(lambda: sim.agents["2"].state == "playing")
    app.pump(0)
    code, ctype, body = get(base + "/api/state")
    s = json.loads(body)
    assert code == 200 and ctype == "application/json"
    assert s["director"] and s["phase"] == "running" and s["scene"] == "A" and s["count"] == 3
    assert [p["id"] for p in s["players"]] == ["1", "2"]
    assert s["players"][0]["role"] == "master" and s["players"][1]["playing"]
    assert [sc["name"] for sc in s["scenes"]] == ["A", "B", "C"]
    assert s["scenes"][0]["players"]["1"]["file"] == "a1.mp4"
    assert any(l["name"] == "front_lights" and l["colors"] == ["#0000be"] for l in s["lights"])
    assert s["hue"] is None                      # no Hue lights in this show


def test_commands_reach_the_director(web):
    sim, app, base = web
    sim.run_until(lambda: sim.director.phase == "running" and sim.director.started)
    assert post(base + "/api/cmd", {"cmd": "next"}) == (200, {"ok": True})
    sim.run_until(lambda: sim.director.scene.name == "B" and sim.director.phase == "running")
    post(base + "/api/cmd", {"cmd": "master", "delta": -5})
    post(base + "/api/cmd", {"cmd": "enable", "index": 2})
    post(base + "/api/cmd", {"cmd": "level", "player": 2, "delta": 5})
    sim.run(1)
    assert sim.director.master_level == 95 and not sim.director.enabled(2)
    assert sim.director.levels["B"]["2"] == sim.show.scenes[1].clips["2"].level + 5
    post(base + "/api/cmd", {"cmd": "hue", "value": False})
    sim.run(0.5)
    assert sim.director.hue is False


def test_bad_commands_are_refused(web):
    sim, app, base = web
    assert post(base + "/api/cmd", {"cmd": "launch"})[0] == 400
    assert post(base + "/api/cmd", {"nope": 1})[0] == 400
    assert post(base + "/api/cmd", {"cmd": "master", "delta": "lots"})[0] == 400
    code, body = post(base + "/api/cmd", {"cmd": "goto", "index": 1, "extra": "dropped"})
    assert code == 200
    sent = [p for t, p in sim.hub.history if t == "haunt/director/cmd"]
    assert json.loads(sent[-1]) == {"cmd": "goto", "index": 1}


def test_page_icon_manifest(web):
    sim, app, base = web
    code, ctype, body = get(base + "/")
    assert code == 200 and ctype.startswith("text/html") and b"apple-mobile-web-app-capable" in body
    code, ctype, body = get(base + "/apple-touch-icon.png")
    assert ctype == "image/png" and body[:8] == b"\x89PNG\r\n\x1a\n"
    assert json.loads(get(base + "/manifest.json")[2])["display"] == "standalone"


def test_events_stream_pushes_changes(web):
    sim, app, base = web
    sim.run(1)
    app.pump(0)
    r = urllib.request.urlopen(base + "/api/events", timeout=5)
    assert r.headers.get("Content-Type") == "text/event-stream"
    first = r.readline()
    assert first.startswith(b"data: ") and json.loads(first[6:])["show"] == "Test show"
    r.readline()                                       # blank line ends the event
    sim.cmd("next")
    sim.run(1)
    app.pump(0)
    nxt = r.readline()
    assert nxt.startswith(b"data: ")
    r.close()


def test_hue_shown_when_the_show_has_hue_lights():
    import copy
    from sim import SHOW
    show = copy.deepcopy(SHOW)
    show["lights"]["living_room"] = {"type": "hue"}
    show["scenes"][0]["lights"]["living_room"] = "#ff6a00"
    sim = Sim(show)
    sim.run(1)
    bus = sim.hub.client()
    bus.subscribe("haunt/#")
    app = WebApp(bus, Topics("haunt"), clock=sim.clock)
    app.pump(0)
    s = app.snapshot()
    assert s["hue"] == "show"
    sim.cmd("hue")
    sim.run(0.5)
    app.pump(0)
    s = app.snapshot()
    assert s["hue"] == "released"
    assert next(l for l in s["lights"] if l["name"] == "living_room")["text"] == "house"
