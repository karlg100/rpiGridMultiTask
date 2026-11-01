"""The director: runs the show.

A scene has one *master* clip, which decides how long the scene lasts, and
any number of *followers* (the other screen), plus colours for the lights.
The director walks through the scenes as an explicit state machine:

    preparing  load the scene's clips, paused and blacked out, on every player
    running    master playing; followers start at their offsets; cues fire
    ending     everything fades to black
    gap        a moment of black, then the next scene
    stopped    show halted from the console (screens black)
    waiting    no scene can run right now (players offline); retrying

It is headless. The console (and anything else that can publish MQTT, e.g.
Home Assistant) controls it through <prefix>/director/cmd and watches
<prefix>/director/state.
"""

from __future__ import annotations

import collections
import json
import logging
import os
import random
import time
from typing import Optional

from . import __version__, lights
from .outputs import Outputs
from .bus import Bus
from .config import ConfigError, Show, load_show
from .topics import Topics

log = logging.getLogger("haunt.director")

MASTER_OFFLINE_GRACE = 3.0   # s to wait for an offline master before skipping
STALE_AFTER = 6.0            # s without a report from the master = it is gone
RESEND_AFTER = 2.5           # s before repeating a load/play nobody acted on
LIGHTS_ONLY_GUESS = 180.0    # s a lights-only scene lasts if its video's length was never learned
RETRY_WAIT = 5.0             # s to sit in "waiting" before trying again
PUBLISH_EVERY = 0.5
SAVE_DELAY = 2.0


class PlayerView:
    """What the director knows about one player."""

    def __init__(self):
        self.online = False
        self.state = {}
        self.seen = -1e9
        self.probe = {}

    def at(self, cue) -> Optional[str]:
        """The player's state name if it is talking about ``cue``, else None."""
        if not self.online or self.state.get("cue") != cue:
            return None
        return self.state.get("state")

    def pos(self, now: float) -> float:
        """Playback position, carried forward from the last report so the
        director is not limited to the report interval."""
        p = float(self.state.get("pos") or 0)
        if self.state.get("state") == "playing":
            p += max(0.0, min(1.0, now - self.seen))
            if self.state.get("dur") and not self.state.get("loop"):
                p = min(p, float(self.state["dur"]))
        return p


class Director:
    def __init__(self, show: Show, bus: Bus, clock=time.monotonic,
                 wallclock=time.time, state_path: Optional[str] = None,
                 start_index: Optional[int] = None, autostart: bool = True):
        self.show = show
        self.bus = bus
        self.clock = clock
        self.wallclock = wallclock
        self.topics = Topics(show.prefix)
        self.state_path = state_path
        self.boot = "%04x" % random.randrange(0x10000)
        self.seq = 0
        self.cue = None

        self.players = {pid: PlayerView() for pid in show.players}
        self.phase = "stopped"
        self.paused = False
        self.index = 0
        self.next = None          # (scene index, search direction) after "ending"
        self.ending_fade = 0.0
        self.t_phase = clock()
        self.skips = 0
        self.want_loaded = {}     # pid -> time the load was (last) sent
        self.want_playing = {}    # pid -> time the play was (last) sent, or None
        self.stopped_early = set()  # followers already told to stop (their end_at)
        self.started = False      # master has been seen playing
        self.tail = False         # followers already fading out with the master
        self.cue_idx = 0
        self.pos = 0.0
        self.current_lights = {}
        self.logbuf = collections.deque(maxlen=30)

        # Things changed from the console; kept across restarts.
        self.master_level = 100.0
        self.levels = {}          # scene name -> {pid: level}
        self.disabled = set()     # scene names
        self.hue = True           # the show drives the Hue rooms (False: left to the house)
        self.floods_level = 100.0  # master brightness for the floods, percent (console , and .)
        self.floods_on = True      # False: the floods stay off during the show (console o)
        self.video = True          # False: lights only, no projection; scenes run on the director's clock (console V)
        self.durations = {}        # player id -> {file: seconds}, from the players' probes; kept for lights-only
        self._lo_last = None       # lights-only: last tick time while running
        self.forced_off = set()   # outputs forced off from the console (kept across restarts)
        self.test = None          # test mode: {"scene": i, "light": name|"all", "pattern": ...}
        self.test_pending = False # enter test mode once the show has stopped
        self.light_status = {}    # WLED lights: "online" / "offline" from <topic>/status
        self.unmute = {}          # (scene, pid) -> level to return to
        self._dirty_at = None
        self._load_state()

        self._last_pub = None
        self._last_pub_t = -1e9
        self._playlist_dirty = True
        self._broker_down = not bus.connected

        bus.subscribe(self.topics.all_players)
        bus.subscribe(self.topics.director_cmd)
        self._wled_status = {}
        self._subscribe_light_status()

        self.outputs = Outputs(show.outputs, bus, clock, self.note)
        self._restore_overrides()
        self.outputs.all_off(force=True)
        self._publish_hue()
        self._publish_floods_level()
        self._publish_floods_on()

        if start_index is not None:
            self.index = max(0, min(len(show.scenes) - 1, start_index))
        self.note("director up: %s, %d scenes" % (show.name, len(show.scenes)))
        if autostart:
            self.start_scene(self.index)

    # -- small helpers ---------------------------------------------------

    def note(self, text: str, level: str = "info") -> None:
        self.logbuf.append([round(self.wallclock(), 1), level, text])
        getattr(log, level if level in ("info", "warning", "error") else "info")(text)

    def send(self, pid: str, cmd: dict) -> None:
        self.bus.publish(self.topics.player(pid, "cmd"), cmd)

    @property
    def scene(self):
        return self.show.scenes[self.index]

    def enabled(self, i: int) -> bool:
        s = self.show.scenes[i]
        return s.enabled and s.name not in self.disabled

    def find_enabled(self, start: int, step: int = 1) -> Optional[int]:
        n = len(self.show.scenes)
        for k in range(n):
            i = (start + step * k) % n
            if self.enabled(i):
                return i
        return None

    def clip_level(self, scene, pid: str) -> float:
        """Level sent to a player: the clip's level (or console override)
        scaled by the master fader."""
        base = self.levels.get(scene.name, {}).get(pid, scene.clips[pid].level)
        return round(base * self.master_level / 100.0, 1)

    # -- persistence -----------------------------------------------------

    def _load_state(self) -> None:
        if not self.state_path:
            return
        try:
            with open(self.state_path) as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return
        self.master_level = float(data.get("master", 100))
        self.levels = {k: {str(p): float(v) for p, v in d.items()}
                       for k, d in (data.get("levels") or {}).items()}
        self.disabled = set(data.get("disabled") or [])
        self.hue = bool(data.get("hue", True))
        self.forced_off = set(data.get("outputs_off") or [])
        self.floods_level = max(0.0, min(100.0, float(data.get("floods_level", 100))))
        self.floods_on = bool(data.get("floods_on", True))
        self.video = bool(data.get("video", True))
        self.durations = {str(p): {str(f): float(d) for f, d in (v or {}).items()}
                          for p, v in (data.get("durations") or {}).items()}
        names = [s.name for s in self.show.scenes]
        if data.get("scene") in names:
            self.index = names.index(data["scene"])

    def _save_state(self) -> None:
        self._dirty_at = None
        if not self.state_path:
            return
        data = {"master": self.master_level, "levels": self.levels,
                "disabled": sorted(self.disabled), "scene": self.scene.name,
                "hue": self.hue, "outputs_off": sorted(self.forced_off),
                "floods_level": self.floods_level, "floods_on": self.floods_on,
                "video": self.video, "durations": self.durations}
        try:
            tmp = self.state_path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(data, fh, indent=1, sort_keys=True)
            os.replace(tmp, self.state_path)
        except OSError as exc:
            log.warning("cannot save %s: %s", self.state_path, exc)

    def _touch(self) -> None:
        self._playlist_dirty = True
        if self._dirty_at is None:
            self._dirty_at = self.clock()

    # -- scene lifecycle -------------------------------------------------

    def _load_cmd(self, scene, pid: str) -> dict:
        clip = scene.clips[pid]
        return {
            "cmd": "load", "cue": self.cue, "file": clip.file,
            "start": clip.start, "loop": clip.loop,
            "level": self.clip_level(scene, pid),
            "fade_in": clip.fade_in, "fade_out": clip.fade_out,
            "target_lufs": self.show.defaults["target_lufs"],
        }

    def _load(self, pid: str) -> None:
        self.send(pid, self._load_cmd(self.scene, pid))
        self.want_loaded[pid] = self.clock()

    def _play(self, pid: str) -> None:
        cmd = {"cmd": "play", "cue": self.cue}
        lead = float(self.show.defaults.get("sync_lead") or 0)
        if lead > 0:
            cmd["at"] = round(self.wallclock() + lead, 3)
        self.send(pid, cmd)
        self.want_playing[pid] = self.clock()

    def start_scene(self, index: int, step: int = 1) -> None:
        """Start the scene at ``index``, or the next enabled one in direction
        ``step``. step=0 means exactly this scene, even if it is set to skip."""
        i = index % len(self.show.scenes) if step == 0 else self.find_enabled(index, step)
        if i is None:
            self.note("every scene is disabled; show stopped", "warning")
            self.phase = "stopped"
            return
        now = self.clock()
        self.index = i
        scene = self.scene
        self.seq += 1
        self.cue = "%s-%d" % (self.boot, self.seq)
        self.phase = "preparing"
        self.t_phase = now
        self.paused = False
        self.next = None
        self.want_loaded, self.want_playing = {}, {}
        self.stopped_early = set()
        self.started = False
        self.tail = False
        self.cue_idx = 0
        self.pos = 0.0
        preroll = float(self.show.defaults["follower_preroll"])
        for pid in self.show.players:
            clip = scene.clips.get(pid)
            if clip is None or not self.video:
                self.send(pid, {"cmd": "stop", "fade": 0})
            elif pid == scene.master or clip.start_after <= preroll:
                self._load(pid)
            # else: loaded later, shortly before its start_after
        self.note("scene %d: %s" % (i + 1, scene.name))
        self._touch()

    def _begin(self) -> None:
        scene = self.scene
        self.phase = "running"
        self.t_phase = self.clock()
        self.skips = 0
        if not self.video:
            self.started = True
            self.pos = scene.clips[scene.master].start      # cue times are the master file's time
            self._lo_last = self.t_phase
            self.set_lights(scene.lights)
            self.outputs.scene(scene.outputs)
            return
        self._play(scene.master)
        for pid in self.want_loaded:
            # Followers with no offset start in the same breath as the master.
            if pid != scene.master and scene.clips[pid].start_after <= 0:
                self.want_playing[pid] = None
                if self.players[pid].at(self.cue) == "ready":
                    self._play(pid)
        self.set_lights(scene.lights)
        self.outputs.scene(scene.outputs)

    def end_scene(self, target, fade: float, why: str = "") -> None:
        """Fade everything out, then go to ``target``: a scene index, an
        (index, direction) pair, or None to stop the show."""
        if why:
            self.note(why)
        if isinstance(target, int):
            target = (target, 1)
        self.phase = "ending"
        self.t_phase = self.clock()
        self.ending_fade = fade
        self.next = target
        self.paused = False
        if target is None:
            self.outputs.all_off()
        else:
            self.outputs.resume()   # if we were paused, the next scene decides
        for pid in self.show.players:
            self.send(pid, {"cmd": "stop", "fade": fade})

    def _skip(self, why: str) -> None:
        self.note("skipping scene %d: %s" % (self.index + 1, why), "warning")
        self.skips += 1
        for pid in self.want_loaded:
            self.send(pid, {"cmd": "stop", "fade": 0})
        if self.skips >= sum(1 for i in range(len(self.show.scenes)) if self.enabled(i)):
            self.note("no scene can run right now; retrying in %ds" % RETRY_WAIT, "warning")
            self.outputs.all_off()
            self.phase = "waiting"
            self.t_phase = self.clock()
        else:
            self.start_scene(self.index + 1)

    def set_lights(self, settings: dict) -> None:
        for name, setting in settings.items():
            cfg = self.show.lights.get(name)
            if cfg:
                lights.apply(self.bus, cfg, setting)
                self.current_lights[name] = setting

    # -- tick ------------------------------------------------------------

    def tick(self) -> None:
        now = self.clock()
        if not self.bus.connected:
            # Blind and mute without the broker: hold still rather than
            # "skipping" every scene because no player can be heard.
            if not self._broker_down:
                self._broker_down = True
                self.note("lost the MQTT broker; holding until it is back", "warning")
            return
        if self._broker_down:
            # Back (or connected for the first time). Do not restart anything:
            # the players' retained state arrives with the re-subscription, so
            # give them a fresh grace period and carry on from what they say.
            self._broker_down = False
            self.note("connected to the MQTT broker")
            self._playlist_dirty = True
            self.probe()
            self.skips = 0
            for v in self.players.values():
                v.seen = now
            if self.phase in ("preparing", "waiting"):
                self.t_phase = now
            self.want_loaded = {pid: now - RESEND_AFTER for pid in self.want_loaded}
            self.outputs.republish()
            self._publish_hue()
            self._publish_floods_level()
            self._publish_floods_on()
        self.outputs.tick()
        handler = getattr(self, "_tick_" + self.phase)
        handler(now)
        if self._dirty_at is not None and now - self._dirty_at >= SAVE_DELAY:
            self._save_state()
        self.publish()

    def _tick_stopped(self, now):
        if self.test_pending:
            self.test_pending = False
            self._enter_test()

    def _tick_test(self, now):
        pass

    def _tick_waiting(self, now):
        if now - self.t_phase >= RETRY_WAIT:
            self.skips = 0
            self.start_scene(self.index + 1)

    def _resend_loads(self, now):
        """Repeat a load to a player that is online but has not picked it up
        (it was offline, restarted, or the message was lost)."""
        for pid, sent in list(self.want_loaded.items()):
            v = self.players[pid]
            if v.online and v.state.get("cue") != self.cue and now - sent > RESEND_AFTER:
                self._load(pid)

    def _tick_preparing(self, now):
        if not self.video:
            return self._begin()
        scene = self.scene
        waited = now - self.t_phase
        timeout = float(self.show.defaults["ready_timeout"])
        self._resend_loads(now)

        m = self.players[scene.master]
        m_state = m.at(self.cue)
        if m_state == "error":
            return self._skip("%s: %s" % (self.pname(scene.master), m.state.get("error")))
        if not m.online and waited > MASTER_OFFLINE_GRACE:
            return self._skip("%s (master) is offline" % self.pname(scene.master))
        if m_state != "ready":
            if waited > timeout:
                return self._skip("%s (master) did not get ready" % self.pname(scene.master))
            return

        for pid in self.want_loaded:
            if pid == scene.master:
                continue
            v = self.players[pid]
            if v.online and v.at(self.cue) not in ("ready", "error") and waited <= timeout:
                return      # give it a little longer
        for pid in self.want_loaded:
            v = self.players[pid]
            if pid != scene.master and v.at(self.cue) != "ready":
                why = v.state.get("error") if v.at(self.cue) == "error" else "not ready"
                self.note("%s: %s; running the scene without it"
                          % (self.pname(pid), why if v.online else "offline"), "warning")
        self._begin()

    def lights_only_end(self, scene=None) -> Optional[float]:
        """Lights only: where the scene ends, in the master file's time."""
        scene = scene or self.scene
        if scene.end_at is not None:
            return float(scene.end_at)
        clip = scene.clips[scene.master]
        d = self.durations.get(scene.master, {}).get(clip.file)
        if d is None:
            return clip.start + LIGHTS_ONLY_GUESS
        return float(d)

    def _tick_lights_only(self, now):
        scene = self.scene
        if not self.paused and self._lo_last is not None:
            self.pos += max(0.0, now - self._lo_last)
        self._lo_last = now
        end = self.lights_only_end()
        if self.pos >= end:
            return self.end_scene(self.index + 1, 0.0)
        self._run_cues(scene)

    def _run_cues(self, scene):
        while self.cue_idx < len(scene.cues) and self.pos >= scene.cues[self.cue_idx].at:
            cue = scene.cues[self.cue_idx]
            self.cue_idx += 1
            self.set_lights(cue.lights)
            self.outputs.apply(cue.outputs)
            if cue.mqtt:
                self.bus.publish(cue.mqtt["topic"], cue.mqtt.get("payload", ""))
            self.note("cue at %ds" % cue.at)

    def _tick_running(self, now):
        if not self.video:
            return self._tick_lights_only(now)
        scene = self.scene
        m = self.players[scene.master]
        m_state = m.at(self.cue)
        if m_state in ("playing", "paused"):
            self.started = True
            self.pos = m.pos(now)

        nxt = self.index + 1
        fade_out = float(self.show.defaults["fade_out"])
        if not m.online:
            return self.end_scene(nxt, fade_out, "%s (master) went offline" % self.pname(scene.master))
        if m_state in ("ended", "idle"):
            return self.end_scene(nxt, fade_out)
        if m_state == "error":
            return self.end_scene(nxt, fade_out, "%s: %s" % (self.pname(scene.master), m.state.get("error")))
        if m_state is None and self.started:
            return self.end_scene(nxt, fade_out, "%s (master) restarted" % self.pname(scene.master))
        if not self.paused and now - m.seen > STALE_AFTER:
            return self.end_scene(nxt, fade_out, "%s (master) stopped reporting" % self.pname(scene.master))
        if scene.end_at is not None and self.pos >= scene.end_at:
            return self.end_scene(nxt, fade_out)
        if self.paused:
            return

        self._resend_loads(now)
        preroll = float(self.show.defaults["follower_preroll"])
        for pid, clip in scene.clips.items():
            if pid == scene.master:
                continue
            v = self.players[pid]
            if pid not in self.want_loaded:
                if self.pos >= clip.start_after - preroll:
                    self._load(pid)
                continue
            if (pid not in self.want_playing and pid not in self.stopped_early
                    and self.started and self.pos >= clip.start_after):
                self.want_playing[pid] = None
            if (clip.end_at is not None and pid not in self.stopped_early
                    and v.at(self.cue) == "playing"
                    and v.pos(now) >= clip.end_at):
                self.send(pid, {"cmd": "stop", "fade": clip.fade_out})
                self.stopped_early.add(pid)

        # As the master nears its own end (where it fades itself out), fade
        # the followers with it so both screens reach black together.
        mclip = scene.clips[scene.master]
        dur = m.state.get("dur")
        if (not self.tail and self.started and dur and not mclip.loop
                and mclip.fade_out > 0 and self.pos >= float(dur) - mclip.fade_out):
            self.tail = True
            left = max(0.1, float(dur) - self.pos)
            for pid in self.want_loaded:
                if pid != scene.master:
                    self.send(pid, {"cmd": "stop", "fade": round(left, 2)})
                    self.stopped_early.add(pid)
                    self.want_playing.pop(pid, None)

        # (Re)send "play" to anything that should be playing but is still
        # sitting ready. Covers followers reaching their cue and lost messages.
        for pid, sent in list(self.want_playing.items()):
            if self.players[pid].at(self.cue) == "ready" and (sent is None or now - sent > RESEND_AFTER):
                self._play(pid)

        self._run_cues(scene)

    def _tick_ending(self, now):
        waited = now - self.t_phase
        busy = [pid for pid, v in self.players.items()
                if v.online and v.state.get("state") not in ("idle", None)]
        if not busy or waited > self.ending_fade + 2.0:
            self.phase = "gap"
            self.t_phase = now

    def _tick_gap(self, now):
        if now - self.t_phase < float(self.show.defaults["gap"]):
            return
        if self.next is None:
            self.phase = "stopped"
            self.outputs.all_off()
            self.note("show stopped")
        else:
            self.start_scene(self.next[0] % len(self.show.scenes), self.next[1])

    def pname(self, pid: str) -> str:
        return "%s (P%s)" % (self.show.players[pid]["name"], pid)

    # -- incoming --------------------------------------------------------

    def _subscribe_light_status(self) -> None:
        """WLED controllers report online/offline on <topic>/status (their last will)."""
        for name, cfg in self.show.lights.items():
            if cfg.get("type", "wled") == "wled":
                topic = cfg["topic"] + "/status"
                if topic not in self._wled_status:
                    self.bus.subscribe(topic)
                self._wled_status[topic] = name

    def handle(self, topic: str, payload: str) -> None:
        if topic == self.topics.director_cmd:
            return self.command(payload)
        if topic in self._wled_status:
            state = payload.strip().lower()
            if self.light_status.get(self._wled_status[topic]) != state:
                self.light_status[self._wled_status[topic]] = state
                self._playlist_dirty = True
            return
        parsed = self.topics.parse_player(topic)
        if not parsed:
            return
        pid, leaf = parsed
        v = self.players.get(pid)
        if v is None:
            return
        if leaf == "online":
            online = payload == "1"
            if online != v.online:
                v.online = online
                self.note("%s is %s" % (self.pname(pid), "online" if online else "OFFLINE"),
                          "info" if online else "warning")
                if online:
                    v.seen = self.clock()
                    self.probe(pid)
        elif leaf == "state":
            try:
                v.state = json.loads(payload)
                v.seen = self.clock()
            except ValueError:
                pass
        elif leaf == "probe":
            try:
                v.probe = json.loads(payload)
                self._playlist_dirty = True
            except ValueError:
                return
            got = {f: float(i["dur"]) for f, i in (v.probe.get("files") or {}).items()
                   if isinstance(i, dict) and i.get("dur")}
            if got and any(self.durations.get(pid, {}).get(f) != d for f, d in got.items()):
                self.durations.setdefault(pid, {}).update(got)
                self._touch()

    def probe(self, pid: Optional[str] = None) -> None:
        """Ask players which of their show files exist (and how loud they are)."""
        for p in ([pid] if pid else list(self.show.players)):
            files = sorted({s.clips[p].file for s in self.show.scenes if p in s.clips})
            self.send(p, {"cmd": "probe", "files": files})

    def go(self, target: int, step: int = 1) -> None:
        """Jump to a scene, fading out whatever is on."""
        target %= len(self.show.scenes)
        if self.phase == "running":
            self.end_scene((target, step), float(self.show.defaults["skip_fade"]))
        elif self.phase == "preparing":
            self.end_scene((target, step), 0.0)
        elif self.phase in ("ending", "gap"):
            self.next = (target, step)
        else:
            self.skips = 0
            self.start_scene(target, step)

    def command(self, payload: str) -> None:
        try:
            cmd = json.loads(payload)
            if isinstance(cmd, str):
                cmd = {"cmd": cmd}
            name = str(cmd["cmd"])
        except (ValueError, KeyError, TypeError):
            # Allow a bare word, handy from mosquitto_pub / Home Assistant.
            name, cmd = payload.strip(), {}
        fn = getattr(self, "_cmd_" + name, None)
        if fn is None:
            self.note("unknown command %r" % name, "warning")
            return
        if self.phase == "test" and name == "stop":
            self._leave_test()
            self.publish(force=True)
            return
        if self.phase == "test" and name in ("start", "goto", "next", "prev", "restart",
                                             "toggle", "resume"):
            self._leave_test(lights_off=False)     # the show takes over from test mode
        try:
            fn(cmd)
        except (KeyError, TypeError, ValueError) as exc:
            self.note("bad %s command: %s" % (name, exc), "warning")
        self.publish(force=True)

    def _cmd_next(self, cmd):
        self.note("next")
        self.go(self.index + 1)

    def _cmd_prev(self, cmd):
        self.note("previous")
        self.go(self.index - 1, step=-1)

    def _cmd_restart(self, cmd):
        self.note("restart scene")
        self.go(self.index)

    def _cmd_goto(self, cmd):
        i = int(cmd["index"])
        if not 0 <= i < len(self.show.scenes):
            raise ValueError("no scene %d" % (i + 1))
        self.note("go to scene %d" % (i + 1))
        self.go(i, step=0)     # asked for by name: play it even if it is set to skip

    def _cmd_pause(self, cmd):
        if self.phase != "running" or self.paused:
            return
        self.paused = True
        for pid in self.show.players:
            self.send(pid, {"cmd": "pause"})
        self.outputs.suspend()
        self.note("paused")

    def _cmd_resume(self, cmd):
        if self.phase == "stopped":
            return self._cmd_start(cmd)
        if not self.paused:
            return
        self.paused = False
        self.players[self.scene.master].seen = self.clock()
        for pid in self.show.players:
            self.send(pid, {"cmd": "resume"})
        self.outputs.resume()
        self.note("resumed")

    def _cmd_toggle(self, cmd):
        if self.paused or self.phase == "stopped":
            self._cmd_resume(cmd)
        else:
            self._cmd_pause(cmd)

    def _cmd_stop(self, cmd):
        if self.phase in ("stopped",):
            return
        self.note("stop")
        if self.phase in ("running", "preparing"):
            self.end_scene(None, float(self.show.defaults["skip_fade"]))
        else:
            self.next = None
            if self.phase == "waiting":
                self.phase = "stopped"
                self.outputs.all_off()

    def _cmd_start(self, cmd):
        if self.phase in ("stopped", "waiting"):
            self.note("start")
            self.skips = 0
            self.start_scene(self.index)
        elif self.phase in ("ending", "gap") and self.next is None:
            self.next = (self.index, 1)

    def _value(self, cmd, current: float, top: float) -> float:
        if "value" in cmd:
            v = float(cmd["value"])
        else:
            v = current + float(cmd["delta"])
        return max(0.0, min(top, v))

    def _push_levels(self) -> None:
        if self.phase in ("preparing", "running"):
            for pid in self.want_loaded:
                self.send(pid, {"cmd": "level", "cue": self.cue,
                                "value": self.clip_level(self.scene, pid)})

    def _cmd_master(self, cmd):
        self.master_level = self._value(cmd, self.master_level, 150.0)
        self._push_levels()
        self._touch()

    def _cmd_level(self, cmd):
        pid = str(cmd["player"])
        scene = self.show.scenes[int(cmd.get("scene", self.index))]
        if pid not in scene.clips:
            return
        current = self.levels.get(scene.name, {}).get(pid, scene.clips[pid].level)
        self.levels.setdefault(scene.name, {})[pid] = self._value(cmd, current, 150.0)
        if scene is self.scene:
            self._push_levels()
        self._touch()

    def _cmd_mute(self, cmd):
        pid = str(cmd["player"])
        scene = self.show.scenes[int(cmd.get("scene", self.index))]
        if pid not in scene.clips:
            return
        current = self.levels.get(scene.name, {}).get(pid, scene.clips[pid].level)
        key = (scene.name, pid)
        if current > 0:
            self.unmute[key] = current
            new = 0.0
        else:
            new = self.unmute.pop(key, None) or scene.clips[pid].level or 100.0
        self._cmd_level({"player": pid, "scene": self.show.scenes.index(scene), "value": new})

    def _cmd_reset_levels(self, cmd):
        scene = self.show.scenes[int(cmd.get("scene", self.index))]
        if self.levels.pop(scene.name, None) is not None:
            self.note("levels for scene %d back to the show file" % (self.show.scenes.index(scene) + 1))
            if scene is self.scene:
                self._push_levels()
            self._touch()

    def _cmd_enable(self, cmd):
        i = int(cmd["index"])
        scene = self.show.scenes[i]
        on = bool(cmd["value"]) if "value" in cmd else scene.name in self.disabled
        if on:
            self.disabled.discard(scene.name)
        else:
            self.disabled.add(scene.name)
        self.note("scene %d %s" % (i + 1, "enabled" if on else "disabled"))
        self._touch()

    def _cmd_mirror(self, cmd):
        """{"cmd":"mirror","player":"1","value":true}; no value toggles. Kept by the player."""
        pid = str(cmd["player"])
        if pid not in self.show.players:
            raise ValueError("no player %r" % pid)
        out = {"cmd": "mirror"}
        if "value" in cmd:
            out["value"] = bool(cmd["value"])
            now = out["value"]
        else:
            now = not bool(self.players[pid].state.get("mirror", False))
        self.note("%s: picture %s" % (self.pname(pid), "MIRRORED (rear projection)" if now else "normal"))
        self.send(pid, out)

    def _cmd_mono(self, cmd):
        """{"cmd":"mono","player":"2","value":true}; no value toggles. Kept by the player."""
        pid = str(cmd["player"])
        if pid not in self.show.players:
            raise ValueError("no player %r" % pid)
        out = {"cmd": "mono"}
        if "value" in cmd:
            out["value"] = bool(cmd["value"])
            self.note("%s: %s" % (self.pname(pid), "mono" if out["value"] else "stereo"))
        else:
            now = not bool(self.players[pid].state.get("mono", True))
            self.note("%s: %s" % (self.pname(pid), "mono" if now else "stereo"))
        self.send(pid, out)

    # -- test mode -------------------------------------------------------

    TEST_COLORS = {"white": "#ffffff", "red": "#ff0000", "green": "#00ff00", "blue": "#0000ff"}
    TEST_PATTERNS = ("scene", "white", "red", "green", "blue", "off")

    def _test_setting(self, name: str, pattern: str):
        """What light ``name`` shows for a test pattern (parsed for its type)."""
        from . import floods as _floods
        from . import hue as _hue
        from .config import parse_light
        kind = self.show.lights[name].get("type", "wled")
        if pattern == "scene":
            scene = self.show.scenes[self.test["scene"]]
            return scene.lights.get(name, {"on": False, "color": None})
        if pattern == "off":
            return {"on": False, "color": None}
        color = self.TEST_COLORS[pattern]
        if kind == "hue":
            return _hue.parse_setting(color)
        if kind == "floods":
            return _floods.parse_setting(color)
        if kind == "wled":
            return parse_light({"effect": "Solid", "color": color, "bri": 255})
        return parse_light(color)

    def _enter_test(self) -> None:
        self.phase = "test"
        self.t_phase = self.clock()
        self.paused = False
        self.outputs.all_off()
        self.test = {"scene": self.index, "light": "all", "pattern": "scene"}
        self.note("TEST MODE: lights show scene %d; the videos stay off" % (self.index + 1))
        self._test_apply("all", "scene")

    def _leave_test(self, lights_off: bool = True) -> None:
        if self.phase != "test":
            return
        if lights_off:
            self.set_lights({n: {"on": False, "color": None} for n in self.show.lights})
        self.outputs.all_off()
        self.test = None
        self.phase = "stopped"
        self.t_phase = self.clock()
        self.note("test mode off")

    def _test_apply(self, light: str, pattern: str) -> None:
        names = list(self.show.lights) if light == "all" else [light]
        self.set_lights({n: self._test_setting(n, pattern) for n in names})
        self.test.update(light=light, pattern=pattern)

    def _cmd_test(self, cmd):
        """Test mode on/off ({"value": bool}; no value toggles). Turning it on
        stops the show first if it is running."""
        on = bool(cmd["value"]) if "value" in cmd else self.phase != "test" and not self.test_pending
        if not on:
            self.test_pending = False
            self._leave_test()
            return
        if self.phase == "test":
            return
        if self.phase in ("stopped", "waiting"):
            self.phase = "stopped"
            self._enter_test()
        else:
            self.note("stopping the show for test mode")
            self.test_pending = True
            self._cmd_stop({})

    def _cmd_test_scene(self, cmd):
        """Show a scene's lights in test mode: {"index": i} or {"delta": +1/-1}."""
        if self.phase != "test":
            raise ValueError("not in test mode")
        n = len(self.show.scenes)
        i = int(cmd["index"]) if "index" in cmd else self.test["scene"] + int(cmd.get("delta", 1))
        self.test["scene"] = i % n
        self.index = self.test["scene"]           # "start" from here plays this scene
        scene = self.show.scenes[self.index]
        self.note("test: scene %d %s" % (self.index + 1, scene.name))
        self._test_apply("all", "scene")
        self._touch()

    def _cmd_test_light(self, cmd):
        """{"name": light or "all", "pattern": scene|white|red|green|blue|off}"""
        if self.phase != "test":
            raise ValueError("not in test mode")
        name = str(cmd.get("name", "all"))
        pattern = str(cmd.get("pattern", "scene")).lower()
        if name != "all" and name not in self.show.lights:
            raise ValueError("no light called %r" % name)
        if pattern not in self.TEST_PATTERNS:
            raise ValueError("pattern must be one of %s" % ", ".join(self.TEST_PATTERNS))
        self._test_apply(name, pattern)
        self.note("test: %s %s" % ("all lights" if name == "all" else name, pattern))

    def _restore_overrides(self) -> None:
        for name in sorted(self.forced_off):
            if name in self.outputs.defs:
                self.outputs.set_override(name, "off")

    def _cmd_output(self, cmd):
        """{"cmd":"output","name":"fog_machine","value":"on"|"off"|"auto"}; without
        a value it steps auto -> on -> off -> auto."""
        name = str(cmd["name"])
        if name not in self.outputs.defs:
            raise ValueError("no output called %r" % name)
        mode = cmd.get("value")
        if mode is True:
            mode = "on"
        elif mode is False:
            mode = "off"
        elif mode is None:
            mode = {None: "on", "on": "off", "off": "auto"}[self.outputs.override.get(name)]
        mode = str(mode).lower()
        self.outputs.set_override(name, mode)
        label = self.outputs.defs[name]["label"]
        max_on = float(self.outputs.defs[name].get("max_on") or 0)
        if mode == "on":
            self.note("%s forced ON%s" % (label, " for %gs" % max_on if max_on else ""))
        elif mode == "off":
            self.note("%s forced OFF until set back to auto" % label)
        else:
            self.note("%s back to following the show" % label)
        before = set(self.forced_off)
        if mode == "off":
            self.forced_off.add(name)
        else:
            self.forced_off.discard(name)
        if before != self.forced_off:
            self._touch()

    def _publish_floods_level(self) -> None:
        self.bus.publish("%s/floods/level" % self.topics.prefix, "%g" % self.floods_level, retain=True)

    def _cmd_floods_level(self, cmd):
        """Master brightness for the floods, percent: {"value": 40} or {"delta": -10}."""
        v = self._value(cmd, self.floods_level, 100.0)
        if v != self.floods_level:
            self.floods_level = v
            self.note("floods brightness %d%%" % round(v))
            self._touch()
        self._publish_floods_level()

    def _cmd_video(self, cmd):
        """Projection on/off: {"value": false} = lights only (no video), or no value to toggle.
        A running scene starts again from the top in the new mode."""
        on = bool(cmd["value"]) if "value" in cmd else not self.video
        if on == self.video:
            return
        self.video = on
        self.note("projection %s" % ("ON" if on else "OFF: lights only"))
        self._touch()
        if self.phase in ("preparing", "running"):
            self.go(self.index, step=0)
        elif not on:
            for pid in self.show.players:
                self.send(pid, {"cmd": "stop", "fade": 0})

    def _publish_floods_on(self) -> None:
        self.bus.publish("%s/floods/enabled" % self.topics.prefix, "1" if self.floods_on else "0", retain=True)

    def _cmd_floods_on(self, cmd):
        """Floods on or off during the show: {"value": false}, or no value to toggle.
        Off holds them dark while the show runs; a stopped show leaves them to
        their own motion sensors either way."""
        on = bool(cmd["value"]) if "value" in cmd else not self.floods_on
        if on != self.floods_on:
            self.floods_on = on
            self.note("floods %s during the show" % ("ON" if on else "OFF"))
            self._touch()
        self._publish_floods_on()

    def _publish_hue(self) -> None:
        self.bus.publish(self.topics.hue_control, "show" if self.hue else "released", retain=True)

    def _cmd_hue(self, cmd):
        """Hand the Hue rooms to the house (released) or back to the show."""
        on = bool(cmd["value"]) if "value" in cmd else not self.hue
        if on != self.hue:
            self.hue = on
            self.note("Hue lights: " + ("the show has them" if on
                                        else "left to the house (Hue app and switches)"))
            self._touch()
        self._publish_hue()

    def _cmd_reload(self, cmd):
        if not self.show.path:
            return
        try:
            new = load_show(self.show.path)
        except ConfigError as exc:
            self.note("reload failed, keeping the running show:", "error")
            for p in exc.problems[:6]:
                self.note("  " + p, "error")
            return
        if set(new.players) != set(self.show.players) or new.prefix != self.show.prefix:
            self.note("players or MQTT settings changed: restart the director to apply", "warning")
            return
        current = self.scene.name
        if new.outputs != self.show.outputs:
            # Switch the old ones off before forgetting them.
            self.outputs.all_off()
            self.outputs = Outputs(new.outputs, self.bus, self.clock, self.note)
            self._restore_overrides()
            self.outputs.all_off(force=True)
        self.show = new
        self._subscribe_light_status()
        if self.test:
            self.test["scene"] = min(self.test["scene"], len(new.scenes) - 1)
        names = [s.name for s in new.scenes]
        if current in names:
            self.index = names.index(current)
            self.note("show reloaded (%d scenes); changes apply from the next scene" % len(names))
        else:
            self.index = min(self.index, len(names) - 1)
            self.note("show reloaded (%d scenes)" % len(names))
            if self.phase in ("running", "preparing"):
                self.end_scene(self.index, float(new.defaults["skip_fade"]))
        self.probe()
        self._touch()

    # -- reports ---------------------------------------------------------

    def playlist(self) -> dict:
        scenes = []
        for i, s in enumerate(self.show.scenes):
            d = s.as_dict()
            d["index"] = i
            d["enabled"] = self.enabled(i)
            for pid, c in d["players"].items():
                over = self.levels.get(s.name, {})
                c["level_file"] = c["level"]
                c["level"] = over.get(pid, c["level"])
                c["overridden"] = pid in over and over[pid] != c["level_file"]
                info = (self.players[pid].probe.get("files") or {}).get(c["file"]) if pid in self.players else None
                c["missing"] = bool(info is not None and not info.get("exists"))
                c["lufs"] = info.get("lufs") if info else None
                c["dur"] = info.get("dur") if info else None
            scenes.append(d)
        return {
            "name": self.show.name,
            "players": self.show.players,
            "lights": {k: {"type": v["type"]} for k, v in self.show.lights.items()},
            "outputs": {k: {"label": v["label"], "max_on": v["max_on"]} for k, v in self.show.outputs.items()},
            "defaults": self.show.defaults,
            "scenes": scenes,
        }

    def snapshot(self) -> dict:
        scene = self.scene
        m = self.players[scene.master]
        active = self.phase in ("preparing", "running", "ending")
        players = {}
        for pid in self.show.players:
            clip = scene.clips.get(pid)
            players[pid] = {
                "role": ("master" if pid == scene.master else "follower") if clip else "unused",
                "start_after": clip.start_after if clip else None,
                "level": self.clip_level(scene, pid) if clip else None,
                "online": self.players[pid].online,
            }
        return {
            "show": self.show.name,
            "phase": self.phase,
            "paused": self.paused,
            "index": self.index,
            "count": len(self.show.scenes),
            "scene": scene.name,
            "cue": self.cue if active else None,
            "master": scene.master,
            "pos": round(self.pos, 1) if self.phase == "running" else 0.0,
            "dur": (m.state.get("dur") if m.at(self.cue) else None) if self.video
                   else (self.lights_only_end() if active else None),
            "video": self.video,
            "end_at": scene.end_at,
            "next": self.next[0] % len(self.show.scenes) if self.next else None,
            "master_level": round(self.master_level, 1),
            "players": players,
            "lights": self.current_lights,
            "outputs": self.outputs.snapshot(),
            "hue": "show" if self.hue else "released",
            "floods_level": round(self.floods_level),
            "floods_on": self.floods_on,
            "test": dict(self.test, scene_name=self.show.scenes[self.test["scene"]].name)
            if self.test and self.phase == "test" else None,
            "test_pending": self.test_pending,
            "light_status": self.light_status,
            "log": list(self.logbuf),
            "ver": __version__,
        }

    def publish(self, force: bool = False) -> None:
        now = self.clock()
        if self._playlist_dirty:
            self._playlist_dirty = False
            self.bus.publish(self.topics.director_playlist, self.playlist(), retain=True)
        snap = self.snapshot()
        key = dict(snap, pos=None)
        if force or key != self._last_pub or now - self._last_pub_t >= PUBLISH_EVERY:
            self._last_pub = key
            self._last_pub_t = now
            snap["ts"] = round(self.wallclock(), 2)
            self.bus.publish(self.topics.director_state, snap, retain=True)

    def run(self) -> None:
        try:
            while True:
                for topic, payload in self.bus.poll(timeout=0.05):
                    self.handle(topic, payload)
                self.tick()
        except KeyboardInterrupt:
            pass
        finally:
            log.info("director shutting down; blacking out the players")
            for pid in self.show.players:
                self.send(pid, {"cmd": "stop", "fade": float(self.show.defaults["skip_fade"])})
            self.outputs.all_off()
            self._save_state()
            time.sleep(0.3)
            self.bus.close()


def main(show_path: str, start_index: Optional[int] = None, autostart: bool = True) -> None:
    from .bus import MqttBus
    show = load_show(show_path)
    topics = Topics(show.prefix)
    bus = MqttBus(show.mqtt, "director", will=(topics.director_online, "0"),
                  birth=(topics.director_online, "1"))
    state_path = os.path.splitext(show_path)[0] + ".state.json"
    Director(show, bus, state_path=state_path, start_index=start_index,
             autostart=autostart).run()
