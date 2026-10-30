"""Light drivers. A light is driven by plain MQTT publishes, so the wire
format stays exactly what the WLED strip and the Particle graveyard already
understand.

    wled      WLED's built-in MQTT:  <topic>      ON / OFF / 0-255 brightness
                                     <topic>/col  #rrggbb
                                     <topic>/api  HTTP-API string ("PL=3") or a
                                                  JSON-API object ("{...}")
    particle  the Particle firmware in Particle/: <topic>/color/r|g|b, then
                                     <topic>/command go   (on / off)

A WLED setting that names an effect, palette, speed, intensity or more than
one colour is sent as one JSON-API message, so the strip changes in a single
step: {"on":true,"bri":..,"transition":..,"seg":[{"fx":..,"sx":..,"ix":..,
"pal":..,"col":[[r,g,b],...]}]}. The effect only applies to segment 0, i.e.
the whole strip unless it has been split into segments in WLED. With an effect
and no palette, palette 0 ("Default", the effect's own) is sent; colour slots
that are not given are sent black, so nothing carries over from the scene
before.

Effect and palette numbers are WLED's built-in ones (kno.wled.ge/features/effects,
kno.wled.ge/interfaces/json-api). They have been stable since WLED 0.14 for
everything below; names can be used in show.yaml instead of numbers.
"""

from __future__ import annotations

import json
from typing import Optional

# WLED effect IDs (1-D effects; the 2-D and audio-reactive ones are left out).
EFFECTS = {
    "solid": 0, "blink": 1, "breathe": 2, "wipe": 3, "wipe random": 4,
    "random colors": 5, "sweep": 6, "dynamic": 7, "colorloop": 8, "rainbow": 9,
    "scan": 10, "scan dual": 11, "fade": 12, "theater": 13, "theater rainbow": 14,
    "running": 15, "saw": 16, "twinkle": 17, "dissolve": 18, "dissolve rnd": 19,
    "sparkle": 20, "sparkle dark": 21, "sparkle+": 22, "strobe": 23,
    "strobe rainbow": 24, "strobe mega": 25, "blink rainbow": 26, "android": 27,
    "chase": 28, "chase random": 29, "chase rainbow": 30, "chase flash": 31,
    "chase flash rnd": 32, "rainbow runner": 33, "colorful": 34,
    "traffic light": 35, "sweep random": 36, "chase 2": 37, "aurora": 38,
    "stream": 39, "scanner": 40, "lighthouse": 41, "fireworks": 42, "rain": 43,
    "tetrix": 44, "fire flicker": 45, "gradient": 46, "loading": 47,
    "fairy": 49, "two dots": 50, "fairytwinkle": 51, "running dual": 52,
    "chase 3": 54, "tri wipe": 55, "tri fade": 56, "lightning": 57, "icu": 58,
    "multi comet": 59, "scanner dual": 60, "stream 2": 61, "oscillate": 62,
    "pride 2015": 63, "juggle": 64, "palette": 65, "fire 2012": 66,
    "colorwaves": 67, "bpm": 68, "fill noise": 69, "noise 1": 70, "noise 2": 71,
    "noise 3": 72, "noise 4": 73, "colortwinkles": 74, "lake": 75, "meteor": 76,
    "meteor smooth": 77, "railway": 78, "ripple": 79, "twinklefox": 80,
    "twinklecat": 81, "halloween eyes": 82, "solid pattern": 83,
    "solid pattern tri": 84, "spots": 85, "spots fade": 86, "glitter": 87,
    "candle": 88, "fireworks starburst": 89, "fireworks 1d": 90,
    "bouncing balls": 91, "sinelon": 92, "sinelon dual": 93,
    "sinelon rainbow": 94, "popcorn": 95, "drip": 96, "plasma": 97,
    "percent": 98, "ripple rainbow": 99, "heartbeat": 100, "pacifica": 101,
    "candle multi": 102, "solid glitter": 103, "sunrise": 104, "phased": 105,
    "twinkleup": 106, "noise pal": 107, "sine": 108, "phased noise": 109,
    "flow": 110, "chunchun": 111, "dancing shadows": 112,
    "washing machine": 113, "blends": 115, "tv simulator": 116,
    "dynamic smooth": 117,
}

PALETTES = {
    "default": 0, "random cycle": 1, "primary color": 2, "based on primary": 3,
    "set colors": 4, "based on set": 5, "party": 6, "cloud": 7, "lava": 8,
    "ocean": 9, "forest": 10, "rainbow": 11, "rainbow bands": 12, "sunset": 13,
    "rivendell": 14, "breeze": 15, "red & blue": 16, "yellowout": 17,
    "analogous": 18, "splash": 19, "pastel": 20, "sunset 2": 21, "beech": 22,
    "vintage": 23, "departure": 24, "landscape": 25, "beach": 26, "sherbet": 27,
    "hult": 28, "hult 64": 29, "drywet": 30, "jul": 31, "grintage": 32,
    "rewhi": 33, "tertiary": 34, "fire": 35, "icefire": 36, "cyane": 37,
    "light pink": 38, "autumn": 39, "magenta": 40, "magred": 41, "yelmag": 42,
    "yelblu": 43, "orange & teal": 44, "tiamat": 45, "april night": 46,
}

EFFECT_NAMES = {v: k for k, v in EFFECTS.items()}
PALETTE_NAMES = {v: k for k, v in PALETTES.items()}


def _lookup(table: dict, value, what: str) -> int:
    if isinstance(value, bool):
        raise ValueError("%s %r is not a name or number" % (what, value))
    if isinstance(value, (int, float)):
        n = int(value)
        if not 0 <= n <= 255:
            raise ValueError("%s %r is out of range 0-255" % (what, value))
        return n
    key = str(value).strip().lower()
    if key in table:
        return table[key]
    import difflib
    near = [k for k in table if key in k][:3] or difflib.get_close_matches(key, list(table), n=3, cutoff=0.6)
    hint = (" (did you mean: %s?)" % ", ".join(near)) if near else ""
    raise ValueError("unknown WLED %s %r%s" % (what, value, hint))


def effect_id(value) -> int:
    return _lookup(EFFECTS, value, "effect")


def palette_id(value) -> int:
    return _lookup(PALETTES, value, "palette")


def effect_label(setting: dict) -> Optional[str]:
    """Short human description, e.g. 'Fire 2012 / Fire'."""
    if setting.get("fx") is None:
        return None
    name = EFFECT_NAMES.get(setting["fx"], "fx %d" % setting["fx"]).title()
    if setting.get("pal") is not None:
        name += " / " + PALETTE_NAMES.get(setting["pal"], "pal %d" % setting["pal"]).title()
    return name


def _rgb(color: str):
    return [int(color[i:i + 2], 16) for i in (1, 3, 5)]


def wled_json(setting: dict) -> dict:
    """The WLED JSON-API state object for a setting with an effect."""
    state = {"on": True}
    if setting.get("bri") is not None:
        state["bri"] = int(setting["bri"])
    if setting.get("transition") is not None:
        state["transition"] = int(round(float(setting["transition"]) * 10))   # 100 ms units
    seg = {}
    for key in ("fx", "sx", "ix", "pal"):
        if setting.get(key) is not None:
            seg[key] = int(setting[key])
    if "fx" in seg and "pal" not in seg:
        seg["pal"] = 0        # the effect's own default, not whatever the last scene left
    colors = setting.get("colors") or ([setting["color"]] if setting.get("color") else [])
    if colors:
        # Unused colour slots go black so nothing from the last scene leaks in.
        seg["col"] = [_rgb(c) for c in colors] + [[0, 0, 0]] * (3 - len(colors))
    state["seg"] = [seg]
    return state


def messages(light_cfg: dict, setting: dict):
    """Return the [(topic, payload), ...] that put a light into ``setting``."""
    topic = light_cfg["topic"]
    kind = light_cfg.get("type", "wled")
    out = []
    if kind == "wled":
        if not setting.get("on", True):
            return [(topic, "OFF")]
        if setting.get("preset") is not None:
            out.append((topic + "/api", "PL=%d" % int(setting["preset"])))
            if setting.get("bri") is not None:
                out.append((topic, str(int(setting["bri"]))))
        elif any(setting.get(k) is not None for k in ("fx", "sx", "ix", "pal", "colors", "transition")):
            out.append((topic + "/api", json.dumps(wled_json(setting), separators=(",", ":"))))
        else:
            if setting.get("bri") is not None:
                out.append((topic, str(int(setting["bri"]))))   # a number also switches on
            else:
                out.append((topic, "ON"))
            if setting.get("color"):
                out.append((topic + "/col", setting["color"].upper()))
        if setting.get("api"):
            out.append((topic + "/api", str(setting["api"])))
    elif kind == "particle":
        if not setting.get("on", True):
            return [(topic + "/command", "off")]
        out.append((topic + "/command", "on"))
        color = setting.get("color") or (setting.get("colors") or [None])[0]
        if color:
            r, g, b = _rgb(color)
            out += [(topic + "/color/r", str(r)), (topic + "/color/g", str(g)),
                    (topic + "/color/b", str(b)), (topic + "/command", "go")]
    return out


def apply(bus, light_cfg: dict, setting: dict) -> None:
    for topic, payload in messages(light_cfg, setting):
        bus.publish(topic, payload)
