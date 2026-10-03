"""The real thing, minus the screens: a real mosquitto broker, real mpv
processes (video and audio output set to null) and generated clips.

Skipped automatically where mosquitto, mpv or ffmpeg is not installed.
Takes about 25 seconds because it plays the clips in real time.
"""

import json
import shutil
import socket
import subprocess
import threading
import time

import pytest

from haunt.backends import MpvBackend
from haunt.bus import MqttBus
from haunt.config import PLAYER_DEFAULTS, parse_show
from haunt.director import Director
from haunt.loudness import LoudnessCache
from haunt.player import PlayerAgent
from haunt.topics import Topics

MOSQUITTO = shutil.which("mosquitto") or shutil.which("mosquitto", path="/usr/sbin:/usr/local/sbin")
needs_tools = pytest.mark.skipif(
    not (MOSQUITTO and shutil.which("mpv") and shutil.which("ffmpeg")),
    reason="needs mosquitto, mpv and ffmpeg")


def make_clip(path, seconds, tone=440, gain=1.0):
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=size=320x180:rate=25",
         "-f", "lavfi", "-i", "sine=frequency=%d,volume=%s" % (tone, gain),
         "-t", str(seconds), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-shortest", str(path)], check=True)


@pytest.fixture
def broker(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    conf = tmp_path / "mosquitto.conf"
    conf.write_text("listener %d 127.0.0.1\nallow_anonymous true\n" % port)
    proc = subprocess.Popen([MOSQUITTO, "-c", str(conf)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.05)
    yield {"host": "127.0.0.1", "port": port, "prefix": "haunt"}
    proc.terminate()
    proc.wait(timeout=5)


@needs_tools
def test_mpv_backend_load_play_eof_loop_and_errors(tmp_path):
    make_clip(tmp_path / "three.mp4", 3)
    (tmp_path / "junk.mp4").write_text("not a video")
    b = MpvBackend(extra_args=["--vo=null", "--ao=null"])
    b.start()
    try:
        def wait(cond, limit=5):
            end = time.time() + limit
            while time.time() < end:
                st = b.status()
                if cond(st):
                    return st
                time.sleep(0.02)
            raise AssertionError("mpv never got there: %s" % (b.status(),))

        assert b.status().loaded is False
        b.load(str(tmp_path / "three.mp4"))
        st = wait(lambda s: s.ready)
        assert st.paused and st.pos == 0 and 2.9 < st.dur < 3.2
        time.sleep(0.5)
        assert b.status().pos == 0                       # really paused
        b.play()
        wait(lambda s: s.pos > 0.5)
        st = wait(lambda s: s.eof)                       # holds on the last frame
        assert st.loaded
        b.stop()
        wait(lambda s: not s.loaded)

        b.load(str(tmp_path / "three.mp4"), start=2.0, loop=True)
        st = wait(lambda s: s.ready)
        assert 1.9 < st.pos < 2.2                        # start offset honoured
        b.play()
        wait(lambda s: s.pos < 1.0, limit=4)             # wrapped round: it loops
        assert not b.status().eof

        b.load(str(tmp_path / "junk.mp4"))
        assert "could not play" in wait(lambda s: s.error).error
        b.load(str(tmp_path / "three.mp4"))              # and it recovers
        wait(lambda s: s.ready)
    finally:
        b.close()
    assert not b.alive()


@needs_tools
def test_two_scenes_over_real_mqtt_with_real_mpv(tmp_path, broker):
    media = tmp_path / "media"
    media.mkdir()
    make_clip(media / "lead.mp4", 8, gain=2.0)           # loud
    make_clip(media / "bg loop.mp4", 2, tone=300, gain=0.2)   # quiet, space in the name
    make_clip(media / "second.mp4", 6)

    show = parse_show({
        "name": "Real", "mqtt": dict(broker),
        "players": {1: {"name": "Window"}, 2: {"name": "Wall"}},
        "lights": {"front_lights": {"type": "wled"}, "graveyard": {"type": "particle"}},
        "defaults": {"gap": 0.2, "fade_in": 0.5, "fade_out": 1.0},
        "scenes": [
            {"name": "One", "master": 1,
             "players": {1: {"file": "lead.mp4"},
                         2: {"file": "bg loop.mp4", "loop": True, "start_after": 3, "level": 50}},
             "lights": {"front_lights": [0, 0, 190], "graveyard": "#310059"},
             "cues": [{"at": 5, "mqtt": {"topic": "ghosts/command", "payload": "startle"}}]},
            {"name": "Two", "master": 2, "end_at": 3,
             "players": {2: {"file": "second.mp4"}},
             "lights": {"front_lights": "off"}},
        ],
    })
    topics = Topics("haunt")

    seen = []          # (seconds since start, topic, payload)
    t0 = time.time()
    watcher = MqttBus(broker, "watcher")
    for pattern in ("haunt/#", "front_lights/#", "graveyard/#", "ghosts/#"):
        watcher.subscribe(pattern)

    stop = threading.Event()
    threads, things = [], []

    def loop(component):
        while not stop.is_set():
            for topic, payload in component.bus.poll(timeout=0.03):
                component.handle(topic, payload)
            component.tick()

    backends = []
    try:
        for pid in ("1", "2"):
            cfg = dict(PLAYER_DEFAULTS, id=pid, mqtt=dict(broker), media_root=str(media),
                       cache_dir=str(tmp_path / ("cache" + pid)))
            backend = MpvBackend(extra_args=["--vo=null", "--ao=null"])
            backend.start()
            backends.append(backend)
            online = topics.player(pid, "online")
            bus = MqttBus(broker, "player" + pid, will=(online, "0"), birth=(online, "1"))
            things.append(PlayerAgent(cfg, bus, backend, loudness=LoudnessCache(cfg["cache_dir"])))
        # First pass measures loudness in the background; let it finish so the
        # scene below runs with normalisation applied.
        for agent, files in zip(things, (["lead.mp4"], ["bg loop.mp4", "second.mp4"])):
            for f in files:
                agent.loudness.request(agent.resolve(f))
        deadline = time.time() + 20
        while any(a.loudness.pending() for a in things) and time.time() < deadline:
            time.sleep(0.1)

        director = Director(show, MqttBus(broker, "director",
                                          will=(topics.director_online, "0"),
                                          birth=(topics.director_online, "1")))
        things.append(director)
        for thing in things:
            th = threading.Thread(target=loop, args=(thing,), daemon=True)
            th.start()
            threads.append(th)

        deadline = time.time() + 40
        loops = 0
        while time.time() < deadline:
            for topic, payload in watcher.poll(timeout=0.1):
                seen.append((time.time() - t0, topic, payload))
            starts = [p for _, t, p in seen if t == "front_lights" and p == "ON"]
            loops = len(starts)
            if loops >= 2:               # scene One has come round a second time
                break
        assert loops >= 2, "show never wrapped round"
    finally:
        stop.set()
        for th in threads:
            th.join(timeout=2)
        for thing in things:
            thing.bus.close()
        watcher.close()
        for backend in backends:
            backend.close()

    def payloads(topic):
        return [p for _, t, p in seen if t == topic]

    def states(pid):
        return [json.loads(p) for p in payloads("haunt/player/%s/state" % pid)]

    # lights: zero-padded colour, particle sequence, and "off" for scene Two
    assert "#0000BE" in payloads("front_lights/col")
    assert "OFF" in payloads("front_lights")
    assert payloads("graveyard/color/r")[0] == "49" and "go" in payloads("graveyard/command")
    assert "startle" in payloads("ghosts/command")

    # player 1 went through the full life of a clip
    order = []
    for s in states("1"):
        if not order or order[-1] != s["state"]:
            order.append(s["state"])
    for wanted in ("loading", "ready", "playing", "ended", "idle"):
        assert wanted in order, order

    # the follower started when the master reached 3s, not before
    one_cue = next(s["cue"] for s in states("1") if s["state"] == "playing")
    first_p2 = next(t for t, topic, p in seen if topic == "haunt/player/2/state"
                    and json.loads(p)["state"] == "playing" and json.loads(p)["cue"] == one_cue)
    first_p1 = next(t for t, topic, p in seen if topic == "haunt/player/1/state"
                    and json.loads(p)["state"] == "playing" and json.loads(p)["cue"] == one_cue)
    assert 2.7 < first_p2 - first_p1 < 4.0, first_p2 - first_p1

    # loudness normalisation was applied: the loud clip turned down, the quiet one up
    lead = next(s for s in states("1") if s["state"] == "playing")
    bg = next(s for s in states("2") if s["state"] == "playing" and s["file"] == "bg loop.mp4")
    assert lead["gain_db"] < 0 < bg["gain_db"]

    # scene Two was cut at end_at=3 although the clip is 6s long
    two = [s for s in states("2") if s["file"] == "second.mp4" and s["state"] in ("playing", "stopping")]
    assert two and max(s["pos"] for s in two) < 4.8

    # the director's log is clean
    final = json.loads(payloads("haunt/director/state")[-1])
    assert not [line for line in final["log"] if line[1] != "info"], final["log"]
