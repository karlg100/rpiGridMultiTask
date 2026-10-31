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
    "target_lufs": -14.0,   # loudness every clip is normalised to
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
        {color: "#ff8800", bri: 128, preset: 3, api: "FX=12"}
        {effect: "Fire 2012", palette: "Fire", speed: 120, intensity: 200,
         colors: ["#ff6a00", "#300060"], bri: 200, transition: 1.0}
    Effects and palettes can be WLED names or numbers (see haunt/lights.py).
    """
    from . import lights as _lights
    if value is False or (isinstance(value, str) and value.strip().lower() == "off"):
        return {"on": False, "color": None}
    if isinstance(value, dict) and not ({"r", "g", "b"} <= set(value)):
        known = {"on", "color", "colors", "bri", "preset", "api", "transition",
                 "effect", "fx", "speed", "sx", "intensity", "ix", "palette", "pal",
                 "c1", "c2", "c3", "o1", "o2", "o3", "grouping", "grp", "mirror", "mi"}
        unknown = sorted(set(value) - known)
        if unknown:
            raise ValueError("unknown setting(s) %s" % ", ".join(map(repr, unknown)))
        out = {"on": bool(value.get("on", True)), "color": parse_color(value.get("color"))}
        if value.get("colors") is not None:
            cols = value["colors"]
            if not isinstance(cols, list) or not 1 <= len(cols) <= 3:
                raise ValueError("colors must be a list of 1 to 3 colours")
            out["colors"] = [parse_color(c) for c in cols]
            out["color"] = out["colors"][0]
        fx = value.get("effect", value.get("fx"))
        if fx is not None:
            out["fx"] = _lights.effect_id(fx)
        pal = value.get("palette", value.get("pal"))
        if pal is not None:
            out["pal"] = _lights.palette_id(pal)
        for key, alias in (("sx", "speed"), ("ix", "intensity"), ("bri", "bri")):
            v = value.get(alias, value.get(key))
            if v is not None:
                v = int(v)
                if not 0 <= v <= 255:
                    raise ValueError("%s %r is out of range 0-255" % (alias, v))
                out[key] = v
        for k, top in (("c1", 255), ("c2", 255), ("c3", 31)):
            if value.get(k) is not None:
                v = int(value[k])
                if not 0 <= v <= top:
                    raise ValueError("%s %r is out of range 0-%d" % (k, v, top))
                out[k] = v
        for k in ("o1", "o2", "o3"):
            if value.get(k) is not None:
                out[k] = bool(value[k])
        grp = value.get("grouping", value.get("grp"))
        if grp is not None:
            grp = int(grp)
            if not 1 <= grp <= 255:
                raise ValueError("grouping %r is out of range 1-255" % grp)
            out["grp"] = grp
        mi = value.get("mirror", value.get("mi"))
        if mi is not None:
            out["mi"] = bool(mi)
        if value.get("transition") is not None:
            out["transition"] = float(value["transition"])
        for k in ("preset", "api"):
            if value.get(k) is not None:
                out[k] = value[k]
        return out
    return {"on": True, "color": parse_color(value)}


def parse_output_value(value):
    """An output setting: True (on for the scene), False (off), a number of
    seconds (one burst), or {burst: N, every: M, first: K} (a burst of N
    seconds every M seconds through the scene, the first K seconds in)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        unknown = sorted(set(value) - {"burst", "every", "first"})
        if unknown:
            raise ValueError("unknown setting(s) %s (burst, every, first)" % ", ".join(map(repr, unknown)))
        try:
            burst, every = float(value["burst"]), float(value["every"])
            first = float(value.get("first", 0))
        except KeyError as exc:
            raise ValueError("repeating bursts need %s" % exc)
        except (TypeError, ValueError):
            raise ValueError("burst, every and first are seconds")
        if burst <= 0 or every < burst + 5 or first < 0:
            raise ValueError("bursts: burst > 0, every at least burst + 5 s, first >= 0")
        return {"burst": burst, "every": every, "first": first}
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("on", "true", "yes"):
            return True
        if v in ("off", "false", "no"):
            return False
        raise ValueError("%r is not on, off or a number of seconds" % value)
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    raise ValueError("%r is not on, off or a number of seconds" % (value,))


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
    outputs: Dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"at": self.at, "lights": self.lights, "mqtt": self.mqtt, "outputs": self.outputs}


@dataclass
class Scene:
    name: str
    master: str
    clips: Dict[str, Clip]
    lights: Dict[str, dict] = field(default_factory=dict)
    cues: List[Cue] = field(default_factory=list)
    end_at: Optional[float] = None
    enabled: bool = True
    outputs: Dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "master": self.master,
            "end_at": self.end_at,
            "enabled": self.enabled,
            "players": {pid: c.as_dict() for pid, c in self.clips.items()},
            "lights": self.lights,
            "cues": [c.as_dict() for c in self.cues],
            "outputs": self.outputs,
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
    outputs: Dict[str, dict] = field(default_factory=dict)   # name -> {"topic", "max_on"}

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
_SCENE_KEYS = {"name", "master", "players", "lights", "cues", "end_at", "enabled", "outputs"}


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
        if l["type"] == "hue":
            # a Hue room: the director publishes the setting, `haunt hue` drives the bridge
            l.setdefault("topic", "%s/hue/%s" % ((data.get("mqtt") or {}).get("prefix", "haunt"), name))
        if l["type"] == "floods":
            # a row of lights in Home Assistant: the director publishes the setting, `haunt floods` drives HA
            l.setdefault("topic", "%s/floods/%s" % ((data.get("mqtt") or {}).get("prefix", "haunt"), name))
        l.setdefault("topic", name)
        if l["type"] not in ("wled", "particle", "hue", "floods"):
            problems.append("lights.%s: type %r is not 'wled', 'particle', 'hue' or 'floods'" % (name, l["type"]))
        lights[str(name)] = l

    outputs = {}
    for name, o in (data.get("outputs") or {}).items():
        o = dict(o or {})
        prefix = (data.get("mqtt") or {}).get("prefix", "haunt")
        o.setdefault("topic", "%s/output/%s" % (prefix, name))
        try:
            o["max_on"] = float(o.get("max_on") or 0)
        except (TypeError, ValueError):
            problems.append("outputs.%s: max_on must be a number of seconds" % name)
            o["max_on"] = 0.0
        o.setdefault("label", str(name).replace("_", " "))
        for k in o:
            if k not in ("topic", "max_on", "label"):
                problems.append("outputs.%s: unknown setting %r" % (name, k))
        outputs[str(name)] = o

    def parse_outputs(raw, where):
        out = {}
        for oname, val in (raw or {}).items():
            if str(oname) not in outputs:
                problems.append("%s: output %r is not defined under 'outputs'" % (where, oname))
                continue
            try:
                out[str(oname)] = parse_output_value(val)
            except ValueError as exc:
                problems.append("%s: output %s: %s" % (where, oname, exc))
        return out

    def parse_lights(raw, where):
        out = {}
        for lname, val in (raw or {}).items():
            if str(lname) not in lights:
                problems.append("%s: light %r is not defined under 'lights'" % (where, lname))
                continue
            try:
                if lights[str(lname)]["type"] == "hue":
                    from . import hue as _hue
                    out[str(lname)] = _hue.parse_setting(val)
                elif lights[str(lname)]["type"] == "floods":
                    from . import floods as _floods
                    out[str(lname)] = _floods.parse_setting(val)
                else:
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
            for k in cue:
                if k not in ("at", "lights", "mqtt", "outputs"):
                    problems.append("%s: unknown setting %r" % (cw, k))
            cues.append(Cue(at=at, lights=parse_lights(cue.get("lights"), cw), mqtt=m,
                            outputs=parse_outputs(cue.get("outputs"), cw)))
        cues.sort(key=lambda c: c.at)

        scenes.append(Scene(
            name=name, master=master, clips=clips,
            lights=parse_lights(raw.get("lights"), where),
            cues=cues, end_at=end_at, enabled=bool(raw.get("enabled", True)),
            outputs=parse_outputs(raw.get("outputs"), where),
        ))

    if not scenes:
        problems.append("scenes: the show has no scenes")
    if problems:
        raise ConfigError(problems)

    return Show(
        name=str(data.get("name", "Halloween")),
        mqtt=resolve_mqtt(data.get("mqtt")),
        players=players, lights=lights, defaults=defaults, scenes=scenes, path=path,
        outputs=outputs,
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
    "max_boost_db": 18.0,      # never amplify a quiet file by more than this (a limiter catches the peaks)
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
