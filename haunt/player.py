"""Player agent: one per video Pi.

It owns a video backend (mpv) and does what the director tells it over MQTT.
Each command is ONE JSON message carrying everything it needs and a ``cue``
id; every state report echoes that cue. That replaces the old protocol of a
dozen separate topics followed by a "queue" command, which is where the
"omx got called before all params were set" race came from.

States:

    idle      nothing loaded, screen black
    loading   told to load, waiting for the first frame
    ready     paused on the (blacked-out) first frame, waiting for "play"
    playing
    paused
    stopping  fading out because the director said stop
    ended     the clip reached its own end and has gone to black
    error     see the "error" field
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

from . import __version__
from .backends import Backend, FakeBackend, MpvBackend
from .bus import Bus
from .loudness import LoudnessCache, db_to_factor, gain_db, have_ffmpeg
from .topics import Topics

log = logging.getLogger("haunt.player")

LOAD_TIMEOUT = 15.0      # seconds for mpv to produce a first frame
HEARTBEAT = 0.25         # seconds between state reports while nothing changes
LEVEL_RAMP = 0.3         # seconds to glide to a new level


class Ramp:
    """A value that glides linearly to a target."""

    def __init__(self, value: float = 0.0):
        self.a = self.b = float(value)
        self.t0 = 0.0
        self.dur = 0.0

    def to(self, target: float, dur: float, now: float) -> None:
        self.a = self.value(now)
        self.b = float(target)
        self.t0 = now
        self.dur = max(0.0, float(dur))

    def set(self, value: float) -> None:
        self.a = self.b = float(value)
        self.dur = 0.0

    def value(self, now: float) -> float:
        if self.dur <= 0 or now >= self.t0 + self.dur:
            return self.b
        return self.a + (self.b - self.a) * (now - self.t0) / self.dur

    def done(self, now: float) -> bool:
        return self.dur <= 0 or now >= self.t0 + self.dur


class PlayerAgent:
    def __init__(self, cfg: dict, bus: Bus, backend: Backend,
                 clock=time.monotonic, wallclock=time.time,
                 loudness: Optional[LoudnessCache] = None):
        self.cfg = cfg
        self.id = str(cfg["id"])
        self.bus = bus
        self.backend = backend
        self.clock = clock
        self.wallclock = wallclock
        self.loudness = loudness
        self.topics = Topics(cfg["mqtt"].get("prefix", "haunt"))

        self.state = "idle"
        self.cue = None
        self.clip = {}            # the last "load" command
        self.path = None
        self.error = None
        self.gain_db = 0.0
        self.lufs = None
        self.fade = Ramp(0.0)     # 0 = black + silent, 1 = full
        self.level = Ramp(100.0)  # what the director asked for, percent
        self.fading_out = False
        self.play_at = None       # wall-clock time to start, or None
        self.play_pending = False
        self.t_load = 0.0
        self.pos = 0.0
        self.dur = None
        self.volume = 0.0

        self._last_pub = None
        self._last_pub_t = -1e9
        self._restart_after = 0.0
        self._probe = None        # the last probe request, to re-answer as scans finish

        bus.subscribe(self.topics.player(self.id, "cmd"))

    # -- commands --------------------------------------------------------

    def handle(self, topic: str, payload: str) -> None:
        if topic != self.topics.player(self.id, "cmd"):
            return
        try:
            cmd = json.loads(payload)
            name = cmd["cmd"]
        except (ValueError, KeyError, TypeError):
            log.warning("ignoring malformed command: %r", payload[:200])
            return
        fn = getattr(self, "_cmd_" + str(name), None)
        if fn is None:
            log.warning("unknown command %r", name)
            return
        log.info("cmd %s", payload[:300])
        fn(cmd)
        self.publish_state(force=True)

    def resolve(self, file: str) -> str:
        return file if os.path.isabs(file) else os.path.join(self.cfg["media_root"], file)

    def _cmd_load(self, cmd):
        now = self.clock()
        self.cue = cmd.get("cue")
        self.clip = cmd
        self.error = None
        self.play_pending = False
        self.play_at = None
        self.fading_out = False
        self.pos, self.dur = 0.0, None
        file = str(cmd.get("file", ""))
        self.path = self.resolve(file)
        if self.backend.name != "fake" and not os.path.isfile(self.path):
            self._fail("file not found: %s" % self.path)
            return

        self.lufs = self.loudness.get(self.path) if self.loudness else None
        self.gain_db = 0.0
        if self.cfg.get("normalize", True) and cmd.get("target_lufs") is not None:
            self.gain_db = gain_db(self.lufs, float(cmd["target_lufs"]),
                                   max_boost=float(self.cfg.get("max_boost_db", 9.0)))
            if self.lufs is None and self.loudness:
                self.loudness.request(self.path)   # ready for next time round

        # Black and silent before the first frame is decoded, so nothing is
        # visible until we are told to play.
        self.fade.set(0.0)
        self.level.set(float(cmd.get("level", 100)))
        self._apply(now)
        self.backend.load(self.path, start=float(cmd.get("start") or 0), loop=bool(cmd.get("loop")))
        self.state = "loading"
        self.t_load = now

    def _cmd_play(self, cmd):
        if cmd.get("cue") != self.cue:
            log.warning("play for cue %r but I have %r; ignored", cmd.get("cue"), self.cue)
            return
        at = cmd.get("at")
        self.play_at = float(at) if at else None
        if self.state == "ready":
            self.play_pending = True
            self._maybe_start()
        elif self.state == "loading":
            self.play_pending = True
        elif self.state == "paused":
            self._cmd_resume(cmd)

    def _cmd_pause(self, cmd):
        if self.state == "playing":
            self.backend.pause()
            self.state = "paused"

    def _cmd_resume(self, cmd):
        if self.state == "paused":
            self.backend.play()
            self.state = "playing"

    def _cmd_stop(self, cmd):
        now = self.clock()
        fade = float(cmd.get("fade") or 0)
        self.play_pending = False
        if self.state == "playing" and fade > 0 and self.fade.value(now) > 0:
            self.fade.to(0.0, fade, now)
            self.fading_out = True
            self.state = "stopping"
        elif self.state == "stopping":
            pass                      # already on the way out
        else:
            self._go_idle()

    def _cmd_level(self, cmd):
        try:
            value = max(0.0, float(cmd["value"]))
        except (KeyError, TypeError, ValueError):
            return
        if cmd.get("cue") not in (None, self.cue):
            return
        self.level.to(value, float(cmd.get("ramp", LEVEL_RAMP)), self.clock())

    def _cmd_probe(self, cmd):
        self._probe = cmd
        self.publish_probe()

    # -- helpers ---------------------------------------------------------

    def _fail(self, message: str) -> None:
        log.error("%s", message)
        self.error = message
        self.state = "error"
        try:
            self.backend.stop()
        except Exception:
            pass

    def _go_idle(self) -> None:
        self.backend.stop()
        self.fade.set(0.0)
        self.fading_out = False
        self.state = "idle"
        self.pos = 0.0

    def _maybe_start(self) -> None:
        if not self.play_pending or self.state != "ready":
            return
        if self.play_at is not None:
            wait = self.play_at - self.wallclock()
            if 0 < wait < 5:
                return            # tick() calls us again
        now = self.clock()
        self.play_pending = False
        self.backend.play()
        self.fade.to(1.0, float(self.clip.get("fade_in") or 0), now)
        self.state = "playing"

    def _apply(self, now: float) -> None:
        """Push the current fade and level to the backend."""
        f = self.fade.value(now)
        trim = float(self.cfg.get("trim", 100)) / 100.0
        self.volume = self.level.value(now) * trim * db_to_factor(self.gain_db) * f
        self.backend.set_volume(self.volume)
        self.backend.set_fade(f if self.cfg.get("video_fade", True) else 1.0)

    # -- main loop -------------------------------------------------------

    def tick(self) -> None:
        now = self.clock()

        if not self.backend.alive():
            if self.state != "error" or "mpv" not in (self.error or ""):
                self._fail("mpv is not running; restarting it")
            if now >= self._restart_after:
                self._restart_after = now + 5
                try:
                    self.backend.close()
                    self.backend.start()
                    self.state, self.error = "idle", None
                    log.info("backend restarted")
                except Exception as exc:
                    self.error = "cannot start mpv: %s" % exc
                    log.error("%s", self.error)
            self.publish_state()
            return

        st = self.backend.status()
        if st.loaded:
            self.pos, self.dur = st.pos, st.dur

        if self.state == "loading":
            if st.error:
                self._fail(st.error)
            elif st.ready:
                self.state = "ready"
                self._maybe_start()
            elif now - self.t_load > LOAD_TIMEOUT:
                self._fail("timed out loading %s" % self.path)

        elif self.state == "ready":
            self._maybe_start()

        elif self.state == "playing":
            if st.error:
                self._fail(st.error)
            elif st.eof or not st.loaded:
                # Reached its own end: go to black and say so.
                self.backend.stop()
                self.fade.set(0.0)
                self.fading_out = False
                self.state = "ended"
            elif (not self.clip.get("loop") and not self.fading_out and st.dur):
                fade_out = float(self.clip.get("fade_out") or 0)
                left = st.dur - st.pos
                if fade_out > 0 and left <= fade_out:
                    self.fade.to(0.0, max(0.0, left - 0.05), now)
                    self.fading_out = True

        elif self.state == "stopping":
            if self.fade.done(now) or st.eof or not st.loaded:
                self._go_idle()

        self._apply(now)

        if self.loudness is not None:
            changed = False
            while not self.loudness.done.empty():
                self.loudness.done.get()
                changed = True
            if changed and self._probe:
                self.publish_probe()

        self.publish_state()

    # -- reports ---------------------------------------------------------

    def snapshot(self) -> dict:
        now = self.clock()
        return {
            "id": self.id,
            "state": self.state,
            "cue": self.cue,
            "file": self.clip.get("file") if self.state != "idle" else None,
            "loop": bool(self.clip.get("loop")) if self.state != "idle" else False,
            "pos": round(self.pos, 1),
            "dur": round(self.dur, 1) if self.dur else None,
            "level": round(self.level.b, 1),
            "volume": round(self.volume, 1),
            "gain_db": round(self.gain_db, 1),
            "fade": round(self.fade.value(now), 2),
            "error": self.error,
            "backend": self.backend.name,
            "ver": __version__,
        }

    def publish_state(self, force: bool = False) -> None:
        snap = self.snapshot()
        # Position and fade tick constantly; only the rest counts as "a change".
        key = dict(snap, pos=None, fade=None, volume=None)
        now = self.clock()
        if force or key != self._last_pub or now - self._last_pub_t >= HEARTBEAT:
            self._last_pub = key
            self._last_pub_t = now
            snap["ts"] = round(self.wallclock(), 2)
            self.bus.publish(self.topics.player(self.id, "state"), snap, retain=True)

    def publish_probe(self) -> None:
        req = self._probe or {}
        files = {}
        for f in req.get("files") or []:
            path = self.resolve(str(f))
            exists = self.backend.name == "fake" or os.path.isfile(path)
            lufs = dur = None
            if self.backend.name == "fake":
                dur = self.backend.duration_of(path)
            elif exists and self.loudness:
                info = self.loudness.info(path)
                if info:
                    lufs, dur = info.get("lufs"), info.get("dur")
                elif self.cfg.get("normalize", True):
                    self.loudness.request(path)
            files[str(f)] = {"exists": exists, "lufs": lufs, "dur": dur}
        self.bus.publish(self.topics.player(self.id, "probe"), {
            "files": files,
            "scanning": self.loudness.pending() if self.loudness else 0,
            "ffmpeg": have_ffmpeg(),
            "ts": round(self.wallclock(), 2),
        }, retain=True)

    def run(self) -> None:
        log.info("player %s up (backend %s, media %s)", self.id, self.backend.name,
                 self.cfg["media_root"])
        try:
            while True:
                for topic, payload in self.bus.poll(timeout=0.03):
                    self.handle(topic, payload)
                self.tick()
        except KeyboardInterrupt:
            pass
        finally:
            log.info("player %s shutting down", self.id)
            try:
                self.backend.close()
            finally:
                self.bus.close()


def build_backend(cfg: dict) -> Backend:
    if cfg["backend"] == "fake":
        return FakeBackend(default_duration=float(cfg.get("fake_duration", 30.0)))
    return MpvBackend(mpv_path=cfg["mpv_path"], rotate=int(cfg["rotate"]),
                      audio_device=str(cfg["audio_device"]), extra_args=cfg["mpv_args"])


def main(cfg: dict) -> None:
    from .bus import MqttBus
    topics = Topics(cfg["mqtt"].get("prefix", "haunt"))
    online = topics.player(cfg["id"], "online")
    backend = build_backend(cfg)
    backend.start()
    bus = MqttBus(cfg["mqtt"], "player%s" % cfg["id"], will=(online, "0"), birth=(online, "1"))
    loud = LoudnessCache(cfg["cache_dir"]) if cfg["backend"] != "fake" else None
    PlayerAgent(cfg, bus, backend, loudness=loud).run()
