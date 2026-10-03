"""Show file (show.yaml) and player file (player.yaml) loading + validation.

The show file is the single place the playlist lives. It is checked hard at
load time so a typo is reported with the scene it is in, instead of showing up
as a black screen on Halloween night.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import yaml


class ConfigError(Exception):
    """One or more problems in a config file. str() lists them all."""

    def __init__(self, problems):
        if isinstance(problems, str):
            problems = [problems]
        self.problems = list(problems)
        super().__init__("\n".join("  - " + p for p in self.problems))


DEFAULTS = {
    "fade_in": 1.0,         # seconds, picture + sound, at the start of a clip
    "fade_out": 1.5,        # seconds, at the natural end of a clip
    "skip_fade": 0.6,       # seconds, when you press next/prev/stop
    "gap": 0.5,             # seconds of black between scenes
    "level": 100,           # per-clip loudness, percent
    "ready_timeout": 10.0,  # seconds to wait for players to load a scene
    "target_lufs": -18.0,   # loudness every clip is normalised to
    "sync_lead": 0.0,       # >0: start clips at a shared wall-clock time (needs NTP)
    "follower_preroll": 5.0,  # load late-starting followers this long before their cue
}

_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


def parse_color(value) -> Optional[str]:
    """Accept '#rrggbb', 'rrggbb', [r, g, b] or {r:, g:, b:}. Returns '#rrggbb'."""
    if value is None:
        return None
    if isinstance(value, str):
        m = _HEX.match(value.strip())
        if not m:
            raise ValueError("colour %r is not #rrggbb" % value)
        return "#" + m.group(1).lower()
    if isinstance(value, dict) and {"r", "g", "b"} <= set(value):
        value = [value["r"], value["g"], value["b"]]
    if isinstance(value, (list, tuple)) and len(value) == 3:
        rgb = [int(v) for v in value]
        if not all(0 <= v <= 255 for v in rgb):
            raise ValueError("colour %r has a channel outside 0-255" % (value,))
        # Zero padded. The old manager used "#%x%x%x", which turned
        # (0, 0, 190) into "#00be".
        return "#%02x%02x%02x" % tuple(rgb)
    raise ValueError("colour %r is not #rrggbb or [r, g, b]" % (value,))


def parse_light(value) -> dict:
    """Normalise one light setting to {'on': bool, 'color': '#rrggbb'|None, ...}.

    Accepted forms:
        "#ff8800"            colour, on
        [255, 136, 0]        colour, on
        off / false          switch it off
        {color: "#ff8800", bri: 128, preset: 3, api: "FX=12"}   WLED extras
    """
    if value is False or (isinstance(value, str) and value.strip().lower() == "off"):
        return {"on": False, "color": None}
    if isinstance(value, dict) and not ({"r", "g", "b"} <= set(value)):
        out = {"on": bool(value.get("on", True)), "color": parse_color(value.get("color"))}
        for k in ("bri", "preset", "api"):
            if value.get(k) is not None:
                out[k] = value[k]
        return out
    return {"on": True, "color": parse_color(value)}


@dataclass
class Clip:
    file: str
    level: float = 100.0
    loop: bool = False
    start: float = 0.0            # seek into the file before playing
    start_after: float = 0.0      # follower: start when the master reaches this
    end_at: Optional[float] = None  # stop this clip at this position
    fade_in: float = 1.0
    fade_out: float = 1.5

    def as_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class Cue:
    at: float
    lights: Dict[str, dict] = field(default_factory=dict)
    mqtt: Optional[dict] = None

    def as_dict(self) -> dict:
        return {"at": self.at, "lights": self.lights, "mqtt": self.mqtt}


@dataclass
class Scene:
    name: str
    master: str
    clips: Dict[str, Clip]
    lights: Dict[str, dict] = field(default_factory=dict)
    cues: List[Cue] = field(default_factory=list)
    end_at: Optional[float] = None
    enabled: bool = True

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "master": self.master,
            "end_at": self.end_at,
            "enabled": self.enabled,
            "players": {pid: c.as_dict() for pid, c in self.clips.items()},
            "lights": self.lights,
            "cues": [c.as_dict() for c in self.cues],
        }


@dataclass
class Show:
    name: str
    mqtt: dict
    players: Dict[str, dict]     # id -> {"name": ...}
    lights: Dict[str, dict]      # name -> {"type": ..., "topic": ...}
    defaults: dict
    scenes: List[Scene]
    path: Optional[str] = None

    @property
    def prefix(self) -> str:
        return self.mqtt.get("prefix", "haunt")


ENV_FILE = "/etc/haunt/env"


def _password_from_env_file(path: Optional[str] = None) -> Optional[str]:
    """The services get the password from systemd's EnvironmentFile. Read the
    same file directly so that `haunt console` typed at a shell on the Pi finds
    it too."""
    try:
        with open(path or ENV_FILE) as fh:
            for line in fh:
                key, sep, value = line.strip().partition("=")
                if sep and key.strip() == "HAUNT_MQTT_PASSWORD":
                    return value.strip().strip("'\"") or None
    except OSError:
        pass
    return None


def resolve_mqtt(cfg: Optional[dict]) -> dict:
    """Fill in MQTT settings. The password comes from $HAUNT_MQTT_PASSWORD,
    /etc/haunt/env or a password_file first, so it never has to be committed."""
    out = {"host": "localhost", "port": 1883, "prefix": "haunt"}
    out.update(cfg or {})
    env = os.environ.get("HAUNT_MQTT_PASSWORD") or _password_from_env_file()
    if env:
        out["password"] = env
    elif out.get("password_file"):
        try:
            with open(os.path.expanduser(out["password_file"])) as fh:
                out["password"] = fh.read().strip()
        except OSError as exc:
            raise ConfigError("mqtt.password_file: %s" % exc)
    if os.environ.get("HAUNT_MQTT_HOST"):
        out["host"] = os.environ["HAUNT_MQTT_HOST"]
    return out


def _num(value, what, problems, minimum=None):
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        problems.append("%s: %r is not a number" % (what, value))
        return None
    if minimum is not None and v < minimum:
        problems.append("%s: %r must be at least %s" % (what, value, minimum))
    return v


_CLIP_KEYS = {"file", "level", "loop", "start", "start_after", "end_at",
              "fade_in", "fade_out", "mute"}
_SCENE_KEYS = {"name", "master", "players", "lights", "cues", "end_at", "enabled"}


def parse_show(data: dict, path: Optional[str] = None) -> Show:
    problems = []
    if not isinstance(data, dict):
        raise ConfigError("show file must be a YAML mapping")

    defaults = dict(DEFAULTS)
    for k, v in (data.get("defaults") or {}).items():
        if k not in DEFAULTS:
            problems.append("defaults: unknown setting %r" % k)
        else:
            defaults[k] = v

    players = {}
    for pid, p in (data.get("players") or {}).items():
        p = p or {}
        players[str(pid)] = {"name": str(p.get("name", "Player %s" % pid))}
    if not players:
        problems.append("players: define at least one player")

    lights = {}
    for name, l in (data.get("lights") or {}).items():
        l = dict(l or {})
        l.setdefault("type", "wled")
        l.setdefault("topic", name)
        if l["type"] not in ("wled", "particle"):
            problems.append("lights.%s: type %r is not 'wled' or 'particle'" % (name, l["type"]))
        lights[str(name)] = l

    def parse_lights(raw, where):
        out = {}
        for lname, val in (raw or {}).items():
            if str(lname) not in lights:
                problems.append("%s: light %r is not defined under 'lights'" % (where, lname))
                continue
            try:
                out[str(lname)] = parse_light(val)
            except ValueError as exc:
                problems.append("%s: light %s: %s" % (where, lname, exc))
        return out

    scenes = []
    seen = set()
    for i, raw in enumerate(data.get("scenes") or []):
        raw = raw or {}
        name = str(raw.get("name") or "Scene %d" % (i + 1))
        where = "scene %d (%s)" % (i + 1, name)
        if name in seen:
            problems.append("%s: duplicate scene name" % where)
        seen.add(name)
        for k in raw:
            if k not in _SCENE_KEYS:
                problems.append("%s: unknown setting %r" % (where, k))

        clips = {}
        for pid, c in (raw.get("players") or {}).items():
            pid = str(pid)
            c = c or {}
            cw = "%s player %s" % (where, pid)
            if pid not in players:
                problems.append("%s: not defined under 'players'" % cw)
            for k in c:
                if k not in _CLIP_KEYS:
                    problems.append("%s: unknown setting %r" % (cw, k))
            if not c.get("file"):
                problems.append("%s: missing 'file'" % cw)
                continue
            level = _num(c.get("level", defaults["level"]), cw + " level", problems, 0)
            if c.get("mute"):
                level = 0.0
            clips[pid] = Clip(
                file=str(c["file"]),
                level=level if level is not None else 100.0,
                loop=bool(c.get("loop", False)),
                start=_num(c.get("start", 0), cw + " start", problems, 0) or 0.0,
                start_after=_num(c.get("start_after", 0), cw + " start_after", problems, 0) or 0.0,
                end_at=_num(c.get("end_at"), cw + " end_at", problems, 0),
                fade_in=_num(c.get("fade_in", defaults["fade_in"]), cw + " fade_in", problems, 0) or 0.0,
                fade_out=_num(c.get("fade_out", defaults["fade_out"]), cw + " fade_out", problems, 0) or 0.0,
            )

        master = str(raw.get("master", "")) if raw.get("master") is not None else ""
        if not clips:
            problems.append("%s: no players" % where)
        elif not master:
            master = sorted(clips)[0] if len(clips) == 1 else ""
            if not master:
                problems.append("%s: missing 'master' (which player's clip decides when the scene ends)" % where)
        elif master not in clips:
            problems.append("%s: master %s has no clip in this scene" % (where, master))

        end_at = _num(raw.get("end_at"), where + " end_at", problems, 0)
        if master in clips:
            m = clips[master]
            if m.start_after:
                problems.append("%s: the master cannot have start_after" % where)
            if m.end_at is not None and end_at is None:
                end_at = m.end_at   # end_at on the master's clip means the scene
            if m.loop and end_at is None:
                problems.append("%s: master loops, so the scene needs 'end_at' or it never ends" % where)

        cues = []
        for j, cue in enumerate(raw.get("cues") or []):
            cue = cue or {}
            cw = "%s cue %d" % (where, j + 1)
            at = _num(cue.get("at"), cw + " at", problems, 0)
            if at is None:
                problems.append("%s: missing 'at'" % cw)
                continue
            m = cue.get("mqtt")
            if m is not None and not (isinstance(m, dict) and m.get("topic")):
                problems.append("%s: mqtt needs a 'topic'" % cw)
                m = None
            cues.append(Cue(at=at, lights=parse_lights(cue.get("lights"), cw), mqtt=m))
        cues.sort(key=lambda c: c.at)

        scenes.append(Scene(
            name=name, master=master, clips=clips,
            lights=parse_lights(raw.get("lights"), where),
            cues=cues, end_at=end_at, enabled=bool(raw.get("enabled", True)),
        ))

    if not scenes:
        problems.append("scenes: the show has no scenes")
    if problems:
        raise ConfigError(problems)

    return Show(
        name=str(data.get("name", "Halloween")),
        mqtt=resolve_mqtt(data.get("mqtt")),
        players=players, lights=lights, defaults=defaults, scenes=scenes, path=path,
    )


def load_show(path: str) -> Show:
    try:
        with open(path) as fh:
            data = yaml.safe_load(fh)
    except OSError as exc:
        raise ConfigError("cannot read %s: %s" % (path, exc))
    except yaml.YAMLError as exc:
        raise ConfigError("%s is not valid YAML: %s" % (path, exc))
    return parse_show(data, path=os.path.abspath(path))


# --------------------------------------------------------------------------
# Player config
# --------------------------------------------------------------------------

PLAYER_DEFAULTS = {
    "id": None,
    "media_root": "/home/pi/videos",
    "backend": "mpv",          # or "fake" (no video, just pretends; for rehearsing)
    "rotate": 0,               # 0 / 90 / 180 / 270, for an upside-down projector
    "audio_device": "auto",    # run `mpv --audio-device=help` on the Pi to list them
    "trim": 100,               # percent; evens out two players with different amps
    "video_fade": True,        # fade the picture to/from black (needs --vo=gpu)
    "normalize": True,         # measure each file's loudness once and even them out
    "max_boost_db": 9.0,       # never amplify a quiet file by more than this
    "mpv_path": "mpv",
    "mpv_args": [],            # extra mpv options, e.g. ["--hwdec=v4l2m2m-copy"]
    "cache_dir": "~/.cache/haunt",
    "fake_duration": 30.0,     # fake backend: pretend every clip is this long
}


def load_player_config(path: Optional[str], overrides: Optional[dict] = None) -> dict:
    cfg = dict(PLAYER_DEFAULTS)
    data = {}
    if path:
        try:
            with open(path) as fh:
                data = yaml.safe_load(fh) or {}
        except OSError as exc:
            raise ConfigError("cannot read %s: %s" % (path, exc))
        except yaml.YAMLError as exc:
            raise ConfigError("%s is not valid YAML: %s" % (path, exc))
    problems = []
    for k, v in data.items():
        if k == "mqtt":
            continue
        if k not in PLAYER_DEFAULTS:
            problems.append("player config: unknown setting %r" % k)
        else:
            cfg[k] = v
    overrides = dict(overrides or {})
    mqtt = dict(data.get("mqtt") or {})
    if overrides.get("mqtt_host"):
        mqtt["host"] = overrides["mqtt_host"]
    overrides.pop("mqtt_host", None)
    for k, v in overrides.items():
        if v is not None:
            cfg[k] = v
    cfg["mqtt"] = resolve_mqtt(mqtt)
    if cfg["id"] is None:
        problems.append("player config: 'id' is required (or pass --id)")
    else:
        cfg["id"] = str(cfg["id"])
    if cfg["rotate"] not in (0, 90, 180, 270):
        problems.append("player config: rotate must be 0, 90, 180 or 270")
    if cfg["backend"] not in ("mpv", "fake"):
        problems.append("player config: backend must be 'mpv' or 'fake'")
    if problems:
        raise ConfigError(problems)
    cfg["cache_dir"] = os.path.expanduser(str(cfg["cache_dir"]))
    return cfg
