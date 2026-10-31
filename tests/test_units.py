"""Config, bus, lights, loudness maths, player agent details, console rendering."""

import copy
import json

import pytest

from haunt import lights, loudness
from haunt.backends import FakeBackend
from haunt.bus import MemoryHub, topic_matches
from haunt.config import (PLAYER_DEFAULTS, ConfigError, load_show, parse_color,
                          parse_light, parse_show, resolve_mqtt)
from haunt.console import Controller, Model, render, to_text
from haunt.player import PlayerAgent, Ramp
from haunt.topics import Topics
from sim import SHOW, Sim


# -- config ------------------------------------------------------------------

def test_colours_are_zero_padded():
    assert parse_color([0, 0, 190]) == "#0000be"       # old code produced "#00be"
    assert parse_color({"r": 255, "g": 165, "b": 0}) == "#ffa500"
    assert parse_color("FFA500") == "#ffa500"
    with pytest.raises(ValueError):
        parse_color([0, 0, 300])
    with pytest.raises(ValueError):
        parse_color("orange")


def test_light_forms():
    assert parse_light("off") == {"on": False, "color": None}
    assert parse_light({"color": "#102030", "bri": 128, "preset": 3}) == {
        "on": True, "color": "#102030", "bri": 128, "preset": 3}


def test_show_problems_are_all_reported_with_their_scene():
    bad = copy.deepcopy(SHOW)
    bad["scenes"][0]["players"][2]["volume"] = 5          # unknown key
    bad["scenes"][1]["master"] = 3                         # no such clip
    bad["scenes"][2]["lights"] = {"porch": "#ffffff"}      # undefined light
    bad["scenes"].append({"name": "Loop forever", "master": 1,
                          "players": {1: {"file": "x.mp4", "loop": True}}})
    with pytest.raises(ConfigError) as err:
        parse_show(bad)
    text = str(err.value)
    assert "scene 1 (A) player 2: unknown setting 'volume'" in text
    assert "scene 2 (B): master 3 has no clip" in text
    assert "light 'porch' is not defined" in text
    assert "master loops" in text


def test_master_end_at_on_clip_becomes_scene_end():
    show = copy.deepcopy(SHOW)
    show["scenes"][2]["players"][1]["end_at"] = 4
    assert parse_show(show).scenes[2].end_at == 4


def test_password_comes_from_environment(monkeypatch):
    monkeypatch.setenv("HAUNT_MQTT_PASSWORD", "from-env")
    assert resolve_mqtt({"host": "h", "password": "in-file"})["password"] == "from-env"


def test_password_is_read_from_the_systemd_env_file(tmp_path):
    from haunt.config import _password_from_env_file
    f = tmp_path / "env"
    f.write_text("# comment\nHAUNT_MQTT_PASSWORD='hunter2'\n")
    assert _password_from_env_file(str(f)) == "hunter2"
    f.write_text("HAUNT_MQTT_PASSWORD=\n")
    assert _password_from_env_file(str(f)) is None
    assert _password_from_env_file(str(tmp_path / "absent")) is None


def test_the_real_show_file_loads():
    import os
    show = load_show(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "show.yaml"))
    assert len(show.scenes) >= 14
    assert all(s.lights["front_lights"].get("fx") is not None for s in show.scenes)   # every scene has an effect
    thriller = [s for s in show.scenes if s.name == "Thriller"][0]
    assert thriller.clips["1"].start == 244
    assert thriller.clips["2"].start_after == 420 and thriller.clips["2"].level == 0
    assert "password" not in show.mqtt or show.mqtt.get("password") is None
    for s in show.scenes:
        for c in s.clips.values():
            assert "\\" not in c.file and not c.file.startswith("/")


# -- bus / lights ---------------------------------------------------------------

def test_topic_wildcards():
    assert topic_matches("haunt/#", "haunt/player/1/state")
    assert topic_matches("haunt/player/+/state", "haunt/player/2/state")
    assert not topic_matches("haunt/player/+/state", "haunt/player/2/cmd")
    assert not topic_matches("haunt/player/+", "haunt/player/2/cmd")


def test_memory_bus_retained_and_last_will():
    hub = MemoryHub()
    a = hub.client(will=("x/online", "0"), birth=("x/online", "1"))
    b = hub.client()
    b.subscribe("x/#")
    assert b.poll() == [("x/online", "1")]          # retained, delivered on subscribe
    a.drop()
    assert b.poll() == [("x/online", "0")]


def test_wled_and_particle_messages():
    wled = {"type": "wled", "topic": "front_lights"}
    assert lights.messages(wled, {"on": True, "color": "#0000be"}) == [
        ("front_lights", "ON"), ("front_lights/col", "#0000BE")]
    assert lights.messages(wled, {"on": False}) == [("front_lights", "OFF")]
    assert lights.messages(wled, {"on": True, "color": None, "bri": 80, "preset": 2}) == [
        ("front_lights/api", "PL=2"), ("front_lights", "80")]
    part = {"type": "particle", "topic": "graveyard"}
    assert lights.messages(part, {"on": True, "color": "#310059"}) == [
        ("graveyard/command", "on"), ("graveyard/color/r", "49"),
        ("graveyard/color/g", "0"), ("graveyard/color/b", "89"), ("graveyard/command", "go")]


def test_wled_effect_is_one_json_api_message():
    wled = {"type": "wled", "topic": "front_lights"}
    setting = parse_light({"effect": "Fire 2012", "palette": "Fire", "speed": 120,
                           "intensity": 200, "colors": ["#ff6a00", [48, 0, 96]],
                           "bri": 200, "transition": 1.5})
    msgs = lights.messages(wled, setting)
    assert len(msgs) == 1 and msgs[0][0] == "front_lights/api"
    assert json.loads(msgs[0][1]) == {
        "on": True, "bri": 200, "transition": 15,
        "seg": [{"fx": 66, "sx": 120, "ix": 200, "pal": 35, "grp": 1, "mi": False,
                 "col": [[255, 106, 0], [48, 0, 96], [0, 0, 0]]}]}
    assert lights.effect_label(setting) == "Fire 2012 / Fire"
    # The Particle graveyard just takes the first colour.
    assert lights.messages({"type": "particle", "topic": "g"}, setting)[1] == ("g/color/r", "255")


def test_wled_effect_names_are_checked():
    with pytest.raises(ValueError) as err:
        parse_light({"effect": "Fire 2013"})
    assert "fire 2012" in str(err.value)
    with pytest.raises(ValueError):
        parse_light({"effect": "Candle", "speed": 300})
    with pytest.raises(ValueError):
        parse_light({"effect": "Candle", "colour": "#ffffff"})
    assert parse_light({"fx": 74, "pal": 2})["fx"] == 74     # numbers work too
    # WLED 16: Meteor Smooth is Meteor with option 3 ("Smooth") on
    seg = lights.wled_json(parse_light({"effect": "Meteor", "o3": True}))["seg"][0]
    assert seg["fx"] == 76 and seg["o3"] is True
    with pytest.raises(ValueError):
        parse_light({"effect": "Meteor", "c3": 40})          # c3 is 0-31
    # an effect without a palette resets the palette to the effect's default
    assert lights.wled_json(parse_light({"effect": "Juggle"}))["seg"][0]["pal"] == 0


# -- loudness ---------------------------------------------------------------------

def test_gain_is_clamped_and_silent_files_get_none():
    assert loudness.gain_db(-14.0, -18.0) == -4.0
    assert loudness.gain_db(-40.0, -18.0, max_boost=9.0) == 9.0
    assert loudness.gain_db(None, -18.0) == 0.0
    assert loudness.gain_db(loudness.NO_AUDIO, -18.0) == 0.0


def test_percent_and_db():
    assert loudness.percent_to_db(100) == 0
    assert loudness.percent_to_db(50) == pytest.approx(-18.06, abs=0.01)
    assert loudness.percent_to_db(0) == -60.0


def test_db_maps_onto_mpvs_cubic_volume():
    # mpv: gain = (volume/100)^3. -6 dB should halve the amplitude.
    factor = loudness.db_to_factor(-6.0206)
    assert factor ** 3 == pytest.approx(0.5, rel=1e-3)


# -- player agent -------------------------------------------------------------------

class Rig:
    def __init__(self, **cfg):
        self.t = 0.0
        self.hub = MemoryHub()
        self.backend = FakeBackend(clock=lambda: self.t, durations={"ten.mp4": 10})
        conf = dict(PLAYER_DEFAULTS, id="1", backend="fake", mqtt=resolve_mqtt({}), **cfg)
        self.agent = PlayerAgent(conf, self.hub.client(), self.backend,
                                 clock=lambda: self.t, wallclock=lambda: self.t)
        self.ctl = self.hub.client()

    def cmd(self, **kw):
        self.ctl.publish("haunt/player/1/cmd", kw)
        self.run(0.05)

    def run(self, seconds, dt=0.05):
        for _ in range(int(round(seconds / dt))):
            self.t += dt
            for topic, payload in self.agent.bus.poll():
                self.agent.handle(topic, payload)
            self.agent.tick()

    def state(self):
        return json.loads(self.hub.retained["haunt/player/1/state"])


def test_ramp():
    r = Ramp(0)
    r.to(10, 2, now=100)
    assert r.value(101) == 5 and r.value(103) == 10 and r.done(102)


def test_clip_is_black_and_silent_until_play_then_fades_in():
    rig = Rig()
    rig.cmd(cmd="load", cue="c1", file="ten.mp4", level=80, fade_in=2.0, fade_out=2.0)
    rig.run(1)
    assert rig.agent.state == "ready"
    assert rig.backend.fade == 0 and rig.backend.volume == 0      # loaded but invisible
    rig.cmd(cmd="play", cue="c1")
    rig.run(1.0)
    assert 0.4 < rig.backend.fade < 0.6                           # half way up
    assert 40 < rig.backend.volume < 60                           # the fade rides mpv's volume
    rig.run(1.5)
    assert rig.backend.fade == 1 and rig.backend.volume == 100
    assert rig.backend.gain == pytest.approx(loudness.percent_to_db(80))   # the level is gain


def test_fades_out_by_itself_before_the_end_and_reports_ended():
    rig = Rig()
    rig.cmd(cmd="load", cue="c1", file="ten.mp4", fade_in=0, fade_out=2.0)
    rig.run(0.5)
    rig.cmd(cmd="play", cue="c1")
    rig.run(8.9)
    assert rig.agent.state == "playing" and 0.2 < rig.backend.fade < 0.8
    rig.run(1.5)
    assert rig.agent.state == "ended" and rig.backend.fade == 0
    assert rig.state()["state"] == "ended" and rig.state()["cue"] == "c1"


def test_stop_with_fade_then_idle():
    rig = Rig()
    rig.cmd(cmd="load", cue="c1", file="ten.mp4", fade_in=0)
    rig.run(0.5)
    rig.cmd(cmd="play", cue="c1")
    rig.run(2)
    rig.cmd(cmd="stop", fade=1.0)
    assert rig.agent.state == "stopping"
    rig.run(0.5)
    assert 0.3 < rig.backend.fade < 0.7
    rig.run(1)
    assert rig.agent.state == "idle" and rig.backend.status().loaded is False


def test_play_for_a_different_cue_is_ignored():
    rig = Rig()
    rig.cmd(cmd="load", cue="new", file="ten.mp4")
    rig.run(0.5)
    rig.cmd(cmd="play", cue="stale")
    rig.run(1)
    assert rig.agent.state == "ready"


def test_play_arriving_while_still_loading_is_remembered():
    rig = Rig()
    rig.backend.load_time = 1.0
    rig.cmd(cmd="load", cue="c", file="ten.mp4")
    rig.cmd(cmd="play", cue="c")
    assert rig.agent.state == "loading"
    rig.run(1.5)
    assert rig.agent.state == "playing"


def test_trim_and_normalisation_gain_scale_the_volume():
    rig = Rig(trim=50)
    rig.cmd(cmd="load", cue="c", file="ten.mp4", level=100, fade_in=0)
    rig.agent.gain_db = -6.0
    rig.run(0.5)
    rig.cmd(cmd="play", cue="c")
    rig.run(0.5)
    # level 100 x trim 50% = -18 dB, plus the -6 dB loudness correction, all
    # in the gain stage ahead of the limiter; mpv's volume stays at 100.
    assert rig.backend.gain == pytest.approx(-6.0 + loudness.percent_to_db(50), abs=0.01)
    assert rig.backend.volume == 100
    assert rig.agent.volume == pytest.approx(100 * 0.5 * loudness.db_to_factor(-6.0), rel=1e-3)


def test_quiet_clip_is_boosted_up_to_the_limit_and_muted_clip_is_silent():
    rig = Rig()
    rig.cmd(cmd="load", cue="c", file="ten.mp4", level=100, fade_in=0, target_lufs=-14)
    rig.agent.gain_db = loudness.gain_db(-40.0, -14.0, max_boost=18.0)
    rig.run(0.5)
    rig.cmd(cmd="play", cue="c")
    rig.run(0.5)
    assert rig.backend.gain == 18.0
    rig.cmd(cmd="level", value=0, ramp=0)
    rig.run(0.2)
    assert rig.backend.volume == 0 and rig.backend.gain == -60.0


def test_video_fade_can_be_switched_off():
    rig = Rig(video_fade=False)
    rig.cmd(cmd="load", cue="c", file="ten.mp4", fade_in=2)
    rig.run(0.5)
    assert rig.backend.fade == 1.0 and rig.backend.volume == 0      # sound still fades


def test_malformed_commands_do_not_crash_the_agent():
    rig = Rig()
    for junk in ("", "not json", "[]", '{"cmd": "launch_missiles"}', '{"cmd": "level"}'):
        rig.ctl.publish("haunt/player/1/cmd", junk)
    rig.run(0.5)
    assert rig.agent.state == "idle"


# -- console ----------------------------------------------------------------------------

def console(sim, width=120, height=40):
    bus = sim.hub.client()
    bus.subscribe("haunt/#")
    model = Model(Topics("haunt"), clock=sim.clock)
    ctl = Controller(model, bus)
    for topic, payload in bus.poll():
        model.handle(topic, payload)
    ctl.sync()
    text = to_text(render(model, width, height, sel=ctl.sel, focus=ctl.focus,
                          broker="test", wallclock=sim.clock))
    return model, ctl, text


def test_console_shows_the_show():
    sim = Sim()
    sim.run_until(lambda: sim.agents["2"].state == "playing")
    model, ctl, text = console(sim)
    assert "RUNNING" in text and "scene 1/3" in text
    assert "MASTER" in text and "a1.mp4" in text and "follower" in text
    assert "front_lights" in text and "#0000be" in text
    assert "+8s" in text and "loop" in text and "60%" in text       # settings in the playlist
    assert "scene 1: A" in text                                     # log


@pytest.mark.parametrize("size", [(80, 24), (100, 30), (200, 60), (40, 10)])
def test_console_fits_any_terminal(size):
    sim = Sim()
    sim.run_until(lambda: sim.agents["2"].state == "playing")
    w, h = size
    bus = sim.hub.client()
    bus.subscribe("haunt/#")
    model = Model(Topics("haunt"), clock=sim.clock)
    for topic, payload in bus.poll():
        model.handle(topic, payload)
    lines = render(model, w, h, wallclock=sim.clock)
    assert len(lines) <= h
    assert all(sum(len(t) for t, _ in line) <= max(w, 40) for line in lines)


def test_console_keys_drive_the_director():
    sim = Sim()
    sim.run_until(lambda: sim.director.phase == "running" and sim.director.started)
    model, ctl, _ = console(sim)
    ctl.key("n")
    sim.run_until(lambda: sim.director.scene.name == "B" and sim.director.phase == "running")
    ctl.key(" ")
    sim.run(1)
    assert sim.director.paused
    ctl.key(" ")
    ctl.key("TAB")                       # focus player 2
    assert ctl.focus == "2"
    ctl.key("[")
    ctl.key("-")
    sim.run(1)
    assert sim.director.master_level == 95
    assert sim.director.levels["B"]["2"] == 95
    ctl.key("DOWN")
    ctl.key("x")                         # skip the selected scene
    sim.run(0.5)
    assert not sim.director.enabled(ctl.sel)
    ctl.key("q")
    assert ctl.quit and sim.director.phase == "running"   # quitting the console stops nothing


def test_console_says_when_the_director_is_down():
    sim = Sim()
    sim.run(2)
    sim.director.bus.drop()
    _, _, text = console(sim)
    assert "DIRECTOR OFFLINE" in text


def test_console_hue_key_hands_the_rooms_to_the_house():
    import copy
    from sim import SHOW
    show = copy.deepcopy(SHOW)
    show["lights"]["living_room"] = {"type": "hue"}
    show["scenes"][0]["lights"]["living_room"] = "#ff6a00"
    sim = Sim(show)
    sim.run_until(lambda: sim.director.phase == "running")
    model, ctl, text = console(sim)
    assert "Hue rooms" in text and "SHOW" in text
    ctl.key("h")
    sim.run(0.5)
    assert sim.director.hue is False
    assert sim.hub.retained["haunt/hue/control"] == "released"
    _, _, text = console(sim)
    assert "HOUSE" in text and "living_room house" in text
    ctl.key("h")
    sim.run(0.5)
    assert sim.hub.retained["haunt/hue/control"] == "show"


def test_console_without_hue_lights_has_no_hue_line():
    sim = Sim()
    sim.run(1)
    _, _, text = console(sim)
    assert "Hue rooms" not in text


def test_wled_grouping_and_mirror_stretch_an_effect_and_reset_after():
    wled = {"type": "wled", "topic": "front_lights"}
    seg = json.loads(lights.messages(wled, parse_light(
        {"effect": "Fire 2012", "palette": "Fire", "grouping": 4, "mirror": True}))[0][1])["seg"][0]
    assert seg["grp"] == 4 and seg["mi"] is True
    seg = json.loads(lights.messages(wled, parse_light({"effect": "Juggle"}))[0][1])["seg"][0]
    assert seg["grp"] == 1 and seg["mi"] is False            # the next scene gets the whole strip back
    with pytest.raises(ValueError):
        parse_light({"effect": "Fire 2012", "grouping": 0})


# -- output overrides ----------------------------------------------------------

def test_output_overrides_force_on_off_and_auto(tmp_path):
    import copy
    from sim import SHOW
    show = copy.deepcopy(SHOW)
    show["outputs"] = {"pond_mister": {"label": "mister"}, "fog_machine": {"label": "fog", "max_on": 10}}
    show["scenes"][0]["outputs"] = {"pond_mister": True}
    path = str(tmp_path / "show.state.json")
    sim = Sim(show, state_path=path)
    sim.run_until(lambda: sim.director.phase == "running")
    sent = lambda: sim.hub.retained.get("haunt/output/pond_mister/set")
    fog = lambda: sim.hub.retained.get("haunt/output/fog_machine/set")
    assert sent() == "ON"
    sim.cmd("output", name="pond_mister", value="off")
    sim.run(0.2)
    assert sent() == "OFF" and sim.director.snapshot()["outputs"]["pond_mister"]["override"] == "off"
    sim.cmd("output", name="fog_machine")              # steps auto -> on: one burst of max_on
    sim.run(0.2)
    assert fog() == "ON"
    sim.run(11)
    assert fog() == "OFF" and sim.director.outputs.override.get("fog_machine") is None
    sim.director._save_state()
    again = Sim(show, state_path=path)                  # forced off survives a restart
    again.run_until(lambda: again.director.phase == "running")
    assert again.hub.retained.get("haunt/output/pond_mister/set") == "OFF"
    again.cmd("output", name="pond_mister", value="auto")
    again.run(0.2)
    assert again.hub.retained.get("haunt/output/pond_mister/set") == "ON"
    again.cmd("output", name="pond_mister", value="on")
    again.cmd("stop")
    again.run_until(lambda: again.director.phase == "stopped")
    again.run(1)
    assert again.hub.retained.get("haunt/output/pond_mister/set") == "OFF"    # stop drops forced on
    again.cmd("output", name="pond_mister", value="on")                       # but can try it while stopped
    again.run(0.2)
    assert again.hub.retained.get("haunt/output/pond_mister/set") == "ON"


def test_console_output_keys_and_light_online():
    import copy
    from sim import SHOW
    show = copy.deepcopy(SHOW)
    show["outputs"] = {"pond_mister": {"label": "mister"}, "fog_machine": {"label": "fog", "max_on": 10}}
    sim = Sim(show)
    sim.run_until(lambda: sim.director.phase == "running")
    sim.hub.client().publish("haunt/light/graveyard/online", "0", retain=True)
    model, ctl, text = console(sim)
    assert "graveyard OFFLINE" in text and "mister (w)" in text and "fog (f)" in text and "auto" in text
    ctl.key("w")
    sim.run(0.3)
    assert sim.director.outputs.override.get("pond_mister") == "on"
    ctl.key("w")
    sim.run(0.3)
    sim.hub.client().publish("haunt/light/graveyard/online", "1", retain=True)
    _, _, text = console(sim)
    assert "FORCED OFF" in text and "graveyard OFFLINE" not in text and "graveyard ●" in text


def test_devwatch_follows_the_broker_log():
    from haunt.devwatch import Watcher
    w = Watcher({"halloweentree": "graveyard", "fridgemon_*": "freezer"})
    assert w.line("1: New client connected from 192.168.3.1:64419 as halloweentree (p1, c1, k15).") == {"graveyard": True}
    assert w.line("1: New client connected from 192.168.3.1:64420 as halloweentree (p1, c1, k15).") == {}
    assert w.line("1: Client halloweentree closed its connection.") == {"graveyard": False}
    assert w.line("1: New client connected from 192.168.2.225:4 as fridgemon_6644 (p2, c1, k15, u'home-pi').") == {"freezer": True}
    assert w.line("1: Client halloweentree has exceeded timeout, disconnecting.") == {}
    w.line("1: New client connected from 192.168.3.1:1 as halloweentree (p1, c1, k15).")
    assert w.line("1: mosquitto version 2.0.11 terminating") == {"graveyard": False, "freezer": False}
    assert w.line("1: New client connected from 192.168.1.45:1 as auto-ABC (p2, c1, k60).") == {}


def test_repeating_fog_bursts_through_a_scene():
    from haunt.config import parse_output_value
    from haunt.outputs import Outputs

    class Bus:
        def __init__(self): self.sent = []
        def publish(self, t, p, retain=False): self.sent.append((round(clock.t, 1), p))

    class Clock:
        t = 0.0
        def __call__(self): return self.t
    clock, bus = Clock(), Bus()
    o = Outputs({"fog_machine": {"label": "fog", "max_on": 10, "topic": "f"}}, bus, clock, lambda *a: None)

    def run(secs):
        end = clock.t + secs
        while clock.t < end - 1e-9:
            clock.t = round(clock.t + 0.1, 1)
            o.tick()
    o.scene({"fog_machine": parse_output_value({"burst": 4, "every": 30, "first": 5})})
    run(70)
    ons = [t for t, p in bus.sent if p == "ON"]
    offs = [t for t, p in bus.sent if p == "OFF"]
    assert ons == [5.0, 35.0, 65.0] and offs[:2] == [9.0, 39.0]
    o.apply({"fog_machine": 8})                         # a one-off cue burst keeps the repeats going
    run(30)
    assert [t for t, p in bus.sent if p == "ON"][-1] == 95.0
    o.suspend()                                         # pause: off, and the clock to the next burst stops
    run(60)
    assert bus.sent[-1][1] == "OFF"
    o.resume()
    run(30)
    assert [t for t, p in bus.sent if p == "ON"][-1] == 185.0
    o.scene({})                                         # next scene without fog: no more bursts
    run(60)
    assert bus.sent[-1][1] == "OFF" and not o.repeat
    with pytest.raises(ValueError):
        parse_output_value({"burst": 5, "every": 6})    # no time to recover
    with pytest.raises(ValueError):
        parse_output_value({"burst": 5, "often": 30})


# -- mono (one-speaker PA) -------------------------------------------------------

def test_player_is_mono_by_default_and_remembers_a_toggle(tmp_path):
    state = str(tmp_path / "player-state.json")
    rig = Rig(state_file=state)
    rig.run(0.2)
    assert rig.backend.mono is True and rig.state()["mono"] is True
    rig.cmd(cmd="mono")                                # toggle
    assert rig.backend.mono is False and rig.state()["mono"] is False
    again = Rig(state_file=state)                      # a restart keeps the console's choice
    assert again.backend.mono is False
    again.cmd(cmd="mono", value=True)
    assert again.backend.mono is True and json.load(open(state)) == {"mono": True}
    assert Rig(mono=False).backend.mono is False       # player.yaml can default to stereo


def test_mpv_filter_chain_with_and_without_mono():
    from haunt.backends import MpvBackend
    b = MpvBackend()
    b._gain = 3.0
    assert b._af().startswith("@haunt:lavfi=[volume=3.00dB")
    b.mono = True
    af = b._af()
    assert af.startswith("@mono:lavfi=[aformat=channel_layouts=stereo,pan=stereo|c0=0.5*c0+0.5*c1|c1=")
    assert af.endswith("alimiter=limit=0.891:level=0:attack=5:release=100]")


def test_mono_from_the_console_reaches_the_player():
    sim = Sim()
    sim.run_until(lambda: sim.director.phase == "running")
    model, ctl, text = console(sim)
    assert "mono" in text
    ctl.key("TAB")                                     # focus player 2
    ctl.key("c")
    sim.run(0.5)
    assert sim.agents["2"].mono is False and sim.agents["1"].mono is True
    _, _, text = console(sim)
    assert "STEREO" in text
    sim.cmd("mono", player="2", value=True)
    sim.run(0.5)
    assert sim.agents["2"].mono is True
