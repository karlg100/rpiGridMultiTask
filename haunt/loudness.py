"""Loudness measurement, so "volume" finally means something.

Every clip in the show was mastered at a different level, which is why the old
per-clip ``vol`` numbers ended up all over the place (-100 ... +30). Here each
file's integrated loudness (EBU R128, in LUFS) is measured once with ffmpeg
and cached on the player. At load time the player applies the difference to a
common target, so every clip plays equally loud at ``level: 100`` and the
level in the show file is purely "how loud do I want this one".
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import shutil
import subprocess
import threading

log = logging.getLogger("haunt.loudness")

_INTEGRATED = re.compile(r"\bI:\s*(-?\d+(?:\.\d+)?)\s*LUFS")
_DURATION = re.compile(r"Duration:\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)")

NO_AUDIO = "none"   # cached marker: measured, file has no (audible) audio


def have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def measure(path: str, timeout: float = 900):
    """Integrated loudness of a file in LUFS.

    Returns a float, NO_AUDIO for a silent / audio-less file, or None if the
    measurement could not be made (ffmpeg missing, unreadable file).
    """
    info = scan(path, timeout)
    return info["lufs"] if info else None


def scan(path: str, timeout: float = 900):
    """Measure a file: {"lufs": float | NO_AUDIO, "dur": seconds | None},
    or None if it could not be measured."""
    if not have_ffmpeg():
        return None
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-nostats", "-vn", "-sn", "-dn",
           "-i", path, "-af", "ebur128", "-f", "null", "-"]
    if shutil.which("nice"):
        cmd = ["nice", "-n", "19"] + cmd   # never steal CPU from playback
    try:
        proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.PIPE, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("loudness scan of %s failed: %s", path, exc)
        return None
    text = proc.stderr.decode("utf-8", "replace")
    d = _DURATION.search(text)
    dur = (int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3))) if d else None
    summary = text.rsplit("Summary:", 1)
    if len(summary) < 2:
        # No ebur128 summary: no audio stream, or the file is unreadable.
        if dur is None:
            return None
        return {"lufs": NO_AUDIO, "dur": dur}
    m = _INTEGRATED.search(summary[1])
    if not m:
        return None
    lufs = float(m.group(1))
    # -70 is ebur128's floor, i.e. silence
    return {"lufs": NO_AUDIO if lufs <= -69.0 else lufs, "dur": dur}


def gain_db(lufs, target: float, max_boost: float = 9.0, max_cut: float = 30.0) -> float:
    """dB to add so a file measured at ``lufs`` plays at ``target``."""
    if lufs is None or lufs == NO_AUDIO:
        return 0.0
    return max(-max_cut, min(max_boost, target - float(lufs)))


def db_to_factor(db: float) -> float:
    """dB -> multiplier for mpv's volume percent.

    mpv's software volume is cubic: gain = (volume/100)^3, so
    dB = 60*log10(volume/100).
    """
    return 10 ** (db / 60.0)


class LoudnessCache:
    """Disk cache of measurements plus a background scanner thread."""

    def __init__(self, cache_dir: str, scan_fn=scan):
        self.path = os.path.join(cache_dir, "loudness.json")
        self.scan_fn = scan_fn
        self.data = {}
        self._todo = queue.Queue()
        self._queued = set()
        self.done = queue.Queue()     # paths finished since last drained
        self._thread = None
        try:
            with open(self.path) as fh:
                self.data = json.load(fh)
        except (OSError, ValueError):
            self.data = {}

    @staticmethod
    def _stamp(path: str):
        st = os.stat(path)
        return [int(st.st_mtime), st.st_size]

    def info(self, path: str):
        """Cached {"lufs", "dur"} for a file, or None if not measured yet (or
        the file changed since)."""
        entry = self.data.get(path)
        if not entry:
            return None
        try:
            if entry.get("stamp") != self._stamp(path):
                return None
        except OSError:
            return None
        return entry

    def get(self, path: str):
        """Cached LUFS (float), NO_AUDIO, or None if not measured yet."""
        entry = self.info(path)
        return entry.get("lufs") if entry else None

    def pending(self) -> int:
        return len(self._queued)

    def request(self, path: str) -> None:
        """Queue a file for measurement in the background."""
        if path in self._queued:
            return
        self._queued.add(path)
        self._todo.put(path)
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._worker, name="loudness", daemon=True)
            self._thread.start()

    def _worker(self):
        while True:
            path = self._todo.get()
            try:
                stamp = self._stamp(path)
                info = self.scan_fn(path)
                if info is not None:
                    self.data[path] = dict(info, stamp=stamp)
                    self._save()
                    log.info("measured %s: %s LUFS, %s s", os.path.basename(path),
                             info.get("lufs"), info.get("dur"))
            except Exception:
                log.exception("loudness scan failed for %s", path)
            finally:
                self._queued.discard(path)
                self.done.put(path)

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(self.data, fh, indent=1, sort_keys=True)
        os.replace(tmp, self.path)
