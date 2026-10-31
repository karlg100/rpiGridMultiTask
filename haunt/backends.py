"""Video backends for the player agent.

``MpvBackend`` starts ONE mpv when the agent starts and keeps it for the whole
night. Clips are loaded into that same instance over mpv's JSON IPC socket.
That is the fix for the flicker: omxplayer was a new process per clip, so the
display layer was torn down and rebuilt at every clip boundary (and the text
console showed through in between). Here the output is opened once and simply
shows black whenever nothing is loaded.

``FakeBackend`` pretends to play, on a clock. It lets you rehearse the whole
show on a laptop and drives the tests.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("haunt.backend")


def _die_with_parent():
    """Runs in the mpv child before exec: have the kernel kill mpv if the
    agent dies for any reason, so an orphan never keeps hold of the display."""
    try:
        import ctypes
        import signal
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, int(signal.SIGTERM), 0, 0, 0)  # PR_SET_PDEATHSIG
    except Exception:
        pass


@dataclass
class Status:
    loaded: bool = False        # a file is loaded (as opposed to idle/black)
    ready: bool = False         # first frame decoded, paused, waiting for "play"
    paused: bool = True
    pos: float = 0.0
    dur: Optional[float] = None
    eof: bool = False
    error: Optional[str] = None


class Backend:
    name = "?"

    def start(self) -> None:
        pass

    def close(self) -> None:
        pass

    def alive(self) -> bool:
        return True

    def load(self, path: str, start: float = 0.0, loop: bool = False) -> None:
        """Load a file paused on its first frame."""
        raise NotImplementedError

    def play(self) -> None:
        raise NotImplementedError

    def pause(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        """Unload; the screen goes (stays) black."""
        raise NotImplementedError

    def set_volume(self, percent: float) -> None:
        """Output volume 0-100. Used for fades only."""
        raise NotImplementedError

    def set_gain(self, db: float) -> None:
        """Gain in dB applied before a peak limiter: loudness normalisation
        plus the clip's level. Can be positive without clipping."""
        raise NotImplementedError

    def set_fade(self, amount: float) -> None:
        """Picture fade: 0.0 = black, 1.0 = normal."""
        raise NotImplementedError

    def set_mono(self, mono: bool) -> None:
        """Mix to mono, the same on both output channels."""
        self.mono = bool(mono)

    def status(self) -> Status:
        raise NotImplementedError


# --------------------------------------------------------------------------
# Fake
# --------------------------------------------------------------------------

class FakeBackend(Backend):
    name = "fake"

    def __init__(self, clock=time.monotonic, default_duration: float = 30.0,
                 durations: Optional[dict] = None, load_time: float = 0.2):
        self.clock = clock
        self.default_duration = default_duration
        self.durations = durations or {}   # basename -> seconds
        self.load_time = load_time
        self.volume = 0.0
        self.gain = 0.0
        self.fade = 1.0
        self.mono = False
        self._path = None
        self._loop = False
        self._dur = None
        self._pos = 0.0
        self._paused = True
        self._t_loaded = 0.0
        self._t_last = 0.0
        self.fail_next_load = None   # tests: set to an error string

    def _advance(self):
        now = self.clock()
        if self._path and not self._paused:
            self._pos += now - self._t_last
            if self._loop and self._dur:
                self._pos %= self._dur
        self._t_last = now

    def duration_of(self, path: str) -> float:
        return float(self.durations.get(os.path.basename(path), self.default_duration))

    def load(self, path, start=0.0, loop=False):
        self._path = path
        self._loop = loop
        self._dur = self.duration_of(path)
        if start >= self._dur:          # pretend clip is shorter than the seek: extend it
            self._dur += float(start)
        self._pos = float(start)
        self._paused = True
        self._t_loaded = self._t_last = self.clock()

    def play(self):
        self._advance()
        self._paused = False

    def pause(self):
        self._advance()
        self._paused = True

    def stop(self):
        self._path = None
        self._paused = True
        self._pos = 0.0

    def set_volume(self, percent):
        self.volume = percent

    def set_gain(self, db):
        self.gain = db

    def set_fade(self, amount):
        self.fade = amount

    def status(self):
        if not self._path:
            return Status()
        self._advance()
        if self.fail_next_load:
            err, self.fail_next_load = self.fail_next_load, None
            self._path = None
            return Status(error=err)
        ready = self.clock() - self._t_loaded >= self.load_time
        eof = bool(self._dur and not self._loop and self._pos >= self._dur)
        return Status(loaded=True, ready=ready, paused=self._paused,
                      pos=min(self._pos, self._dur or self._pos), dur=self._dur, eof=eof)


# --------------------------------------------------------------------------
# mpv
# --------------------------------------------------------------------------

class MpvBackend(Backend):
    name = "mpv"

    BASE_ARGS = [
        "--idle=yes",                 # stay running with nothing loaded
        "--force-window=immediate",   # own the screen (black) from the start
        "--keep-open=yes",            # at end of file hold, don't close the output
        "--fullscreen",
        "--no-osc", "--no-osd-bar", "--osd-level=0",
        "--no-input-default-bindings", "--no-input-terminal",
        "--cursor-autohide=always",
        "--volume-max=100",           # volume is only used for fades; gain is in AUDIO_FILTER
        "--volume=0",
        "--hr-seek=yes",
        "--msg-level=all=warn",
    ]

    # Gain first, then a peak limiter at -1 dBFS, so quiet clips can be
    # brought up to the loudness target without clipping on their peaks.
    # The label lets the gain be changed later with af-command.
    AUDIO_FILTER = ("@haunt:lavfi=[volume=%.2fdB,"
                    "alimiter=limit=0.891:level=0:attack=5:release=100]")
    # Mono for a one-speaker PA: any layout to stereo (5.1 gets a proper
    # downmix), then both channels become (L+R)/2, so whichever pin of the
    # jack the PA is wired to it gets the whole mix at the same level.
    MONO_FILTER = ("@mono:lavfi=[aformat=channel_layouts=stereo,"
                   "pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1]")

    def __init__(self, mpv_path: str = "mpv", rotate: int = 0,
                 audio_device: str = "auto", extra_args=None,
                 socket_path: Optional[str] = None):
        self.mpv_path = mpv_path
        self.rotate = rotate
        self.audio_device = audio_device
        self.extra_args = list(extra_args or [])
        self.socket_path = socket_path or os.path.join(
            tempfile.gettempdir(), "haunt-mpv-%d.sock" % os.getpid())
        self.proc = None
        self.sock = None
        self._reader = None
        self._lock = threading.Lock()      # guards the state below
        self._wlock = threading.Lock()     # guards socket writes
        self._props = {}
        self._ready = False
        self._error = None
        self._awaiting_start = False       # set by load(), cleared by start-file
        self._entry_id = None
        self._req = 0
        self._sent = {}                    # request_id -> command, for error logs
        self._last_volume = None
        self._last_brightness = None
        self._gain = 0.0
        self._gain_sent = None
        self.mono = False

    # -- process ---------------------------------------------------------

    def start(self):
        try:
            os.unlink(self.socket_path)
        except OSError:
            pass
        args = [self.mpv_path] + self.BASE_ARGS + [
            "--input-ipc-server=" + self.socket_path,
        ]
        if self.rotate:
            args.append("--video-rotate=%d" % self.rotate)
        if self.audio_device and self.audio_device != "auto":
            args.append("--audio-device=" + self.audio_device)
        args += self.extra_args
        log.info("starting: %s", " ".join(args))
        self.proc = subprocess.Popen(args, stdin=subprocess.DEVNULL,
                                     preexec_fn=_die_with_parent)

        deadline = time.monotonic() + 10
        while True:
            if self.proc.poll() is not None:
                raise RuntimeError("mpv exited at startup (code %s); run it by hand "
                                   "to see why: %s" % (self.proc.returncode, " ".join(args)))
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(self.socket_path)
                self.sock = s
                break
            except OSError:
                s.close()
                if time.monotonic() > deadline:
                    self.close()
                    raise RuntimeError("mpv did not open its IPC socket")
                time.sleep(0.05)

        # mpv opens its IPC socket before the video output. If there is no
        # display it exits a moment later, so make sure it stays up.
        settle = time.monotonic() + 1.5
        while time.monotonic() < settle:
            if self.proc.poll() is not None:
                code = self.proc.returncode
                self.close()
                raise RuntimeError("mpv exited at startup (code %s), usually because no "
                                   "display is connected" % code)
            time.sleep(0.05)

        self._props = {}
        self._ready = False
        self._error = None
        self._last_volume = self._last_brightness = None
        self._reader = threading.Thread(target=self._read_loop, name="mpv-ipc", daemon=True)
        self._reader.start()
        for i, prop in enumerate(("time-pos", "duration", "pause", "eof-reached", "idle-active"), 1):
            self._command("observe_property", i, prop)

    def close(self):
        if self.proc and self.proc.poll() is None:
            try:
                self._command("quit")
                self.proc.wait(timeout=2)
            except Exception:
                self.proc.kill()
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None
        try:
            os.unlink(self.socket_path)
        except OSError:
            pass

    def alive(self):
        return bool(self.proc and self.proc.poll() is None
                    and self._reader and self._reader.is_alive())

    # -- IPC -------------------------------------------------------------

    def _command(self, *cmd):
        if self.sock is None:          # mpv not running; the agent is restarting it
            return
        with self._wlock:
            self._req += 1
            rid = self._req
            self._sent[rid] = cmd
            if len(self._sent) > 200:
                for k in sorted(self._sent)[:100]:
                    self._sent.pop(k, None)
            data = json.dumps({"command": list(cmd), "request_id": rid}) + "\n"
            try:
                self.sock.sendall(data.encode())
            except (OSError, AttributeError) as exc:
                log.error("mpv IPC write failed: %s", exc)

    def _read_loop(self):
        buf = b""
        sock = self.sock
        while True:
            try:
                chunk = sock.recv(65536)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    self._on_message(json.loads(line))
                except Exception:
                    log.exception("bad message from mpv: %r", line[:200])
        log.warning("mpv IPC connection closed")

    def _on_message(self, msg):
        event = msg.get("event")
        if event is None:
            rid = msg.get("request_id")
            cmd = self._sent.pop(rid, None)
            if msg.get("error") not in (None, "success"):
                log.warning("mpv rejected %s: %s", cmd, msg.get("error"))
            return
        with self._lock:
            if event == "property-change":
                self._props[msg.get("name")] = msg.get("data")
            elif event == "start-file":
                # Everything before this belonged to the previous file.
                self._awaiting_start = False
                self._entry_id = msg.get("playlist_entry_id")
                self._ready = False
                self._props["eof-reached"] = False
                self._props["time-pos"] = None
                self._props["duration"] = None
            elif event == "playback-restart":
                if not self._awaiting_start:
                    self._ready = True
            elif event == "end-file":
                if (msg.get("reason") == "error" and not self._awaiting_start
                        and msg.get("playlist_entry_id") in (None, self._entry_id)):
                    self._error = "mpv could not play the file (%s)" % msg.get("file_error", "error")
                    self._ready = False

    # -- Backend API -----------------------------------------------------

    def load(self, path, start=0.0, loop=False):
        with self._lock:
            self._awaiting_start = True
            self._ready = False
            self._error = None
        # Options are set first rather than passed to loadfile, whose
        # argument order changed in mpv 0.38.
        self._command("set", "pause", "yes")
        self._command("set", "start", "%.3f" % start if start else "none")
        self._command("set", "loop-file", "inf" if loop else "no")
        # The filter chain is rebuilt for each file; start it at the right gain.
        self._command("set", "af", self._af())
        self._gain_sent = self._gain
        self._command("loadfile", path, "replace")

    def _af(self) -> str:
        chain = self.AUDIO_FILTER % self._gain
        return (self.MONO_FILTER + "," + chain) if self.mono else chain

    def set_mono(self, mono):
        mono = bool(mono)
        if mono == self.mono:
            return
        self.mono = mono
        with self._lock:
            playing = not self._awaiting_start and not self._props.get("idle-active", True)
        if playing:   # rebuild the chain now (a short blip); otherwise load() does it
            self._command("set", "af", self._af())
            self._gain_sent = self._gain

    def play(self):
        self._command("set", "pause", "no")

    def pause(self):
        self._command("set", "pause", "yes")

    def stop(self):
        with self._lock:
            self._ready = False
            self._awaiting_start = False
        self._command("stop")

    def set_gain(self, db):
        self._gain = max(-60.0, min(30.0, float(db)))
        if self._gain_sent is not None and abs(self._gain - self._gain_sent) < 0.05:
            return
        with self._lock:
            playing = not self._awaiting_start and not self._props.get("idle-active", True)
        if playing:   # with nothing loaded there is no filter to talk to; load() applies it
            self._gain_sent = self._gain
            self._command("af-command", "haunt", "volume", "%.2fdB" % self._gain, "volume")

    def set_volume(self, percent):
        v = round(max(0.0, min(100.0, percent)), 1)
        if v != self._last_volume:
            self._last_volume = v
            self._command("set_property", "volume", v)

    def set_fade(self, amount):
        # mpv's brightness is applied in the GPU shader: -100 is fully black.
        b = int(round(-100 + 100 * max(0.0, min(1.0, amount))))
        if b != self._last_brightness:
            self._last_brightness = b
            self._command("set_property", "brightness", b)

    def status(self):
        with self._lock:
            p = self._props
            if self._error:
                return Status(error=self._error)
            idle = bool(p.get("idle-active", True))
            if self._awaiting_start:
                return Status(loaded=True)
            if idle:
                return Status()
            return Status(
                loaded=True,
                ready=self._ready,
                paused=bool(p.get("pause", True)),
                pos=float(p.get("time-pos") or 0.0),
                dur=p.get("duration"),
                eof=bool(self._ready and p.get("eof-reached")),
            )
