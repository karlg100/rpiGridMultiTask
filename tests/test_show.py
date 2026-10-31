"""Director + players, end to end on the simulated clock."""

import copy
import json

import pytest

from haunt.config import ConfigError, parse_show

from sim import SHOW, Sim


def running(sim, name):
    d = sim.director
    return lambda: d.phase == "running" and d.started and d.scene.name == name


def test_scene_plays_through_and_advances():
    sim = Sim()
    sim.run_until(running(sim, "A"))
    a1 = sim.agents["1"]
    assert a1.state == "playing"
    # the follower is not loaded until shortly before its cue, and not started early
    sim.run(2)
    assert sim.agents["2"].state == "idle"
    sim.run_until(lambda: sim.agents["2"].state == "playing")
    assert 8.0 <= a1.pos <= 8.2, a1.pos
    # master runs to its own end, then the next scene starts
    sim.run_until(running(sim, "B"))
    assert sim.director.index == 1
    # the looping follower from A was stopped, and player 1 now loops b1 silently
    assert sim.pstate("1")["file"] == "b1.mp4"


def test_show_wraps_around():
    sim = Sim()
    for name in ("A", "B", "C", "A"):
        sim.run_until(running(sim, name))
        sim.run(1)


def test_scene_end_at_cuts_master_short():
    sim = Sim()
    sim.run_until(running(sim, "B"))
    sim.run_until(lambda: sim.director.phase != "running")
    assert 12.0 <= sim.director.pos <= 12.2     # b2 is 30s long but end_at is 12
    sim.run_until(running(sim, "C"))


def test_lights_are_zero_padded_and_follow_the_scene():
    sim = Sim()
    sim.run_until(running(sim, "A"))
    # The old manager sent "#00be" for (0, 0, 190).
    assert sim.sent("front_lights/col") == ["#0000BE"]
    assert sim.sent("front_lights") == ["ON"]
    assert sim.sent("graveyard/color/r")[-1] == "49"
    assert sim.sent("graveyard/color/b")[-1] == "89"
    assert sim.sent("graveyard/command") == ["on", "go"]
    sim.run_until(running(sim, "B"))
    assert sim.sent("front_lights/col")[-1] == "#FFA500"
    assert sim.state()["lights"]["front_lights"]["color"] == "#ffa500"


def test_cue_fires_at_master_position():
    sim = Sim()
    sim.cmd("goto", index=2)
    sim.run_until(running(sim, "C"))
    sim.run(4)
    assert sim.sent("ghosts/command") == []
    sim.run(2)
    assert sim.sent("ghosts/command") == ["startle"]
    assert sim.sent("graveyard/color/r")[-1] == "255"


def test_next_prev_restart_goto():
    sim = Sim()
    sim.run_until(running(sim, "A"))
    sim.cmd("next")
    sim.run_until(running(sim, "B"))
    sim.cmd("prev")
    sim.run_until(running(sim, "A"))
    sim.run(5)
    sim.cmd("restart")
    sim.run_until(lambda: sim.director.phase == "preparing")
    sim.run_until(running(sim, "A"))
    assert sim.agents["1"].pos < 2
    sim.cmd("goto", index=2)
    sim.run_until(running(sim, "C"))


def test_prev_from_first_scene_wraps_to_last():
    sim = Sim()
    sim.run_until(running(sim, "A"))
    sim.cmd("prev")
    sim.run_until(running(sim, "C"))


def test_disabled_scenes_are_skipped_in_both_directions():
    sim = Sim()
    sim.run_until(running(sim, "A"))
    sim.cmd("enable", index=1, value=False)
    assert sim.playlist()["scenes"][1]["enabled"] is False
    sim.cmd("next")
    sim.run_until(running(sim, "C"))
    sim.cmd("prev")
    sim.run_until(running(sim, "A"))
    sim.cmd("goto", index=1)          # asked for by name: plays even though set to skip
    sim.run_until(running(sim, "B"))
    sim.run_until(running(sim, "C"))  # ...and auto-advance still skips over it afterwards
    sim.run_until(running(sim, "A"))


def test_pause_and_resume_freeze_everything():
    sim = Sim()
    sim.run_until(lambda: sim.agents["2"].state == "playing")
    sim.cmd("pause")
    sim.run(0.5)
    p1, p2 = sim.agents["1"].pos, sim.agents["2"].pos
    sim.run(20)                         # longer than the stale-master timeout
    assert sim.director.phase == "running" and sim.state()["paused"]
    assert sim.agents["1"].state == "paused" and sim.agents["2"].state == "paused"
    assert abs(sim.agents["1"].pos - p1) < 0.2 and abs(sim.agents["2"].pos - p2) < 0.2
    sim.cmd("toggle")
    sim.run(2)
    assert sim.agents["1"].state == "playing" and sim.agents["1"].pos > p1 + 1
    assert sim.director.scene.name == "A"


def test_stop_blacks_out_and_start_resumes():
    sim = Sim()
    sim.run_until(running(sim, "A"))
    sim.cmd("stop")
    sim.run_until(lambda: sim.director.phase == "stopped")
    assert all(a.state == "idle" for a in sim.agents.values())
    sim.run(30)
    assert sim.director.phase == "stopped"
    sim.cmd("start")
    sim.run_until(running(sim, "A"))


def test_master_offline_skips_to_a_scene_that_can_run():
    sim = Sim(online=("2",))            # player 1 never shows up
    sim.run_until(running(sim, "B"))    # A needs player 1 as master: skipped
    assert any("skipping scene 1" in line[2] for line in sim.state()["log"])


def test_follower_offline_scene_still_runs():
    sim = Sim(online=("1",))
    sim.run_until(running(sim, "A"))
    sim.run_until(lambda: sim.director.phase == "ending")
    assert sim.director.pos > 18        # played to the end regardless


def test_nobody_online_waits_then_recovers():
    sim = Sim(online=())
    sim.run_until(lambda: sim.director.phase == "waiting")
    sim.run(30)
    assert sim.director.phase in ("waiting", "preparing")
    sim.add_player(1)
    sim.add_player(2)
    sim.run_until(lambda: sim.director.phase == "running", limit=60)


def test_master_dies_mid_scene_show_moves_on():
    sim = Sim()
    sim.run_until(running(sim, "A"))
    sim.run(3)
    sim.kill_player(1)
    sim.run_until(running(sim, "B"))
    assert any("went offline" in line[2] for line in sim.state()["log"])


def test_master_agent_restart_mid_scene_moves_on():
    sim = Sim()
    sim.run_until(running(sim, "A"))
    sim.run(3)
    sim.kill_player(1)
    sim.add_player(1)                   # back before the director notices the will
    sim.run_until(lambda: sim.director.scene.name != "A" and sim.director.phase == "running")


def test_load_error_on_master_skips_scene():
    sim = Sim()
    sim.agents["1"].backend.fail_next_load = "mpv could not play the file"
    sim.run_until(running(sim, "B"))
    assert any("could not play" in line[2] for line in sim.state()["log"])


def test_follower_restart_mid_scene_is_reloaded():
    sim = Sim()
    sim.cmd("goto", index=1)
    sim.run_until(running(sim, "B"))
    sim.run(2)
    sim.kill_player(1)
    sim.add_player(1)
    sim.run_until(lambda: sim.agents["1"].state == "playing", limit=10)
    assert sim.director.scene.name == "B"


def test_levels_master_and_mute():
    sim = Sim()
    sim.run_until(lambda: sim.agents["2"].state == "playing")
    sim.run(2)
    assert sim.agents["2"].level.b == 60
    assert sim.agents["1"].volume == pytest.approx(100, abs=0.5)

    sim.cmd("level", player="2", delta=10)
    sim.run(1)
    assert sim.agents["2"].volume == pytest.approx(70, abs=0.5)

    sim.cmd("master", value=50)
    sim.run(1)
    assert sim.agents["1"].volume == pytest.approx(50, abs=0.5)
    assert sim.agents["2"].volume == pytest.approx(35, abs=0.5)

    sim.cmd("mute", player="1")
    sim.run(1)
    assert sim.agents["1"].volume == 0
    sim.cmd("mute", player="1")
    sim.run(1)
    assert sim.agents["1"].volume == pytest.approx(50, abs=0.5)

    scene = sim.playlist()["scenes"][0]
    assert scene["players"]["2"]["level"] == 70 and scene["players"]["2"]["overridden"]
    assert scene["players"]["2"]["level_file"] == 60

    sim.cmd("reset_levels")
    sim.run(1)
    assert sim.agents["2"].volume == pytest.approx(30, abs=0.5)


def test_console_changes_survive_a_director_restart(tmp_path):
    path = str(tmp_path / "show.state.json")
    sim = Sim(state_path=path)
    sim.run_until(running(sim, "A"))
    sim.cmd("master", value=80)
    sim.cmd("level", player="2", value=45)
    sim.cmd("enable", index=2, value=False)
    sim.cmd("next")
    sim.run_until(running(sim, "B"))
    sim.run(3)                           # past the save delay
    saved = json.load(open(path))
    assert saved["master"] == 80 and saved["levels"]["A"]["2"] == 45
    assert saved["disabled"] == ["C"] and saved["scene"] == "B"

    again = Sim(state_path=path)
    assert again.director.master_level == 80
    assert again.director.scene.name == "B"      # picks up where it left off
    assert not again.director.enabled(2)
    again.run_until(running(again, "B"))


def test_follower_end_at_stops_just_that_player():
    show = copy.deepcopy(SHOW)
    show["scenes"][0]["players"][2] = {"file": "b2.mp4", "end_at": 5}
    sim = Sim(show)
    sim.run_until(lambda: sim.agents["2"].state == "playing")
    sim.run_until(lambda: sim.agents["2"].state == "idle")
    assert 5.0 <= sim.agents["1"].pos <= 8.5
    assert sim.agents["1"].state == "playing" and sim.director.phase == "running"


def test_bare_word_command_and_unknown_command():
    sim = Sim()
    sim.run_until(running(sim, "A"))
    sim.observer.publish(sim.topics.director_cmd, "next")
    sim.run_until(running(sim, "B"))
    sim.observer.publish(sim.topics.director_cmd, "explode")
    sim.run(1)
    assert sim.director.phase == "running"


def test_probe_reports_missing_files_into_the_playlist(tmp_path):
    sim = Sim()
    agent = sim.agents["1"]
    agent.backend.name = "mpv"          # make it check the disk for real
    agent.cfg["media_root"] = str(tmp_path)
    (tmp_path / "a1.mp4").write_bytes(b"x")
    sim.director.probe("1")
    sim.run(1)
    scenes = sim.playlist()["scenes"]
    assert scenes[0]["players"]["1"]["missing"] is False
    assert scenes[1]["players"]["1"]["missing"] is True


def test_lost_play_message_is_resent():
    sim = Sim()
    sim.run_until(lambda: sim.director.phase == "running")
    # Pretend the play never arrived: put the master back to "ready".
    a = sim.agents["1"]
    a.backend.pause()
    a.state = "ready"
    a.play_pending = False
    sim.run(4)
    assert a.state == "playing"


def test_followers_fade_out_together_with_the_master():
    sim = Sim()
    sim.run_until(lambda: sim.agents["2"].state == "playing")
    sim.run_until(lambda: sim.agents["1"].state == "ended")
    # by the time the master is black, the looping follower is too
    assert sim.agents["2"].state in ("idle", "stopping")
    assert sim.agents["2"].backend.fade <= 0.1


# -- fog machine, mister and other switched outputs -------------------------

def effects_show():
    show = copy.deepcopy(SHOW)
    show["outputs"] = {"pond_mister": {}, "fog_machine": {"max_on": 8}}
    show["scenes"][0]["outputs"] = {"pond_mister": "on", "fog_machine": 3}
    show["scenes"][0]["cues"] = [{"at": 10, "outputs": {"fog_machine": 30}}]   # clamped to 8
    show["scenes"][1]["outputs"] = {"fog_machine": "on"}                       # cut off by max_on
    return show


def out(sim, name):
    sent = sim.sent("haunt/output/%s/set" % name)
    return sent[-1] if sent else None


def test_outputs_start_off_and_follow_the_scenes():
    sim = Sim(effects_show())
    assert out(sim, "pond_mister") == "OFF" and out(sim, "fog_machine") == "OFF"
    sim.run_until(running(sim, "A"))
    assert out(sim, "pond_mister") == "ON" and out(sim, "fog_machine") == "ON"
    sim.run(3.2)
    assert out(sim, "fog_machine") == "OFF" and out(sim, "pond_mister") == "ON"   # 3 s burst over
    sim.run_until(lambda: sim.director.pos >= 10.2)
    assert out(sim, "fog_machine") == "ON"                                      # cue burst
    sim.run(8.2)
    assert out(sim, "fog_machine") == "OFF"                                     # max_on 8 s, not 30
    assert out(sim, "pond_mister") == "ON"
    sim.run_until(running(sim, "B"))
    assert out(sim, "pond_mister") == "OFF"                                     # B does not use it
    assert out(sim, "fog_machine") == "ON"
    sim.run(8.5)
    assert out(sim, "fog_machine") == "OFF"                                     # "on" still limited
    assert any("fog machine switched off after its 8s limit" in l[2] for l in sim.state()["log"])
    assert sim.state()["outputs"]["fog_machine"]["on"] is False


def test_outputs_off_when_paused_or_stopped():
    sim = Sim(effects_show())
    sim.run_until(running(sim, "A"))
    sim.cmd("pause")
    assert out(sim, "pond_mister") == "OFF" and out(sim, "fog_machine") == "OFF"
    sim.cmd("resume")
    assert out(sim, "pond_mister") == "ON"
    assert out(sim, "fog_machine") == "OFF"          # a burst is not replayed
    sim.cmd("stop")
    sim.run_until(lambda: sim.director.phase == "stopped")
    assert out(sim, "pond_mister") == "OFF"


def test_outputs_are_retained_so_a_late_listener_sees_the_state():
    sim = Sim(effects_show())
    sim.run_until(running(sim, "A"))
    assert sim.hub.retained["haunt/output/pond_mister/set"] == "ON"


def test_bad_output_settings_are_reported():
    show = effects_show()
    show["scenes"][2]["outputs"] = {"smoke_machine": "on", "pond_mister": "maybe"}
    with pytest.raises(ConfigError) as err:
        parse_show(show)
    assert "output 'smoke_machine' is not defined" in str(err.value)
    assert "pond_mister: 'maybe' is not on, off or a number" in str(err.value)


def test_cues_from_a_cues_file(tmp_path):
    import copy
    import yaml
    from haunt.config import ConfigError, load_show
    from sim import SHOW
    show = copy.deepcopy(SHOW)
    show["cues_file"] = "extra.yaml"
    (tmp_path / "extra.yaml").write_text(yaml.safe_dump({"A": [{"at": 3, "lights": {"front_lights": "#ff0000"}},
                                                               {"at": 1, "lights": {"graveyard": "#00ff00"}}]}))
    (tmp_path / "show.yaml").write_text(yaml.safe_dump(show))
    s = load_show(str(tmp_path / "show.yaml"))
    a = s.scenes[0]
    assert [c.at for c in a.cues][:2] == [1.0, 3.0] and a.cues[1].lights["front_lights"]["color"] == "#ff0000"
    (tmp_path / "extra.yaml").write_text(yaml.safe_dump({"No such scene": []}))
    with pytest.raises(ConfigError, match="No such scene"):
        load_show(str(tmp_path / "show.yaml"))
