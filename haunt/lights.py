"""Light drivers. A light is driven by plain MQTT publishes, so the wire
format stays exactly what the WLED strip and the Particle graveyard already
understand.

    wled      WLED's built-in MQTT:  <topic>      ON / OFF / 0-255 brightness
                                     <topic>/col  #rrggbb
                                     <topic>/api  raw HTTP-API string (PL=3 ...)
    particle  the Particle firmware in Particle/: <topic>/color/r|g|b, then
                                     <topic>/command go   (on / off)
"""

from __future__ import annotations


def messages(light_cfg: dict, setting: dict):
    """Return the [(topic, payload), ...] that put a light into ``setting``."""
    topic = light_cfg["topic"]
    kind = light_cfg.get("type", "wled")
    out = []
    if kind == "wled":
        if not setting.get("on", True):
            return [(topic, "OFF")]
        if setting.get("bri") is not None:
            out.append((topic, str(int(setting["bri"]))))   # a number also switches on
        else:
            out.append((topic, "ON"))
        if setting.get("preset") is not None:
            out.append((topic + "/api", "PL=%d" % int(setting["preset"])))
        if setting.get("color"):
            out.append((topic + "/col", setting["color"].upper()))
        if setting.get("api"):
            out.append((topic + "/api", str(setting["api"])))
    elif kind == "particle":
        if not setting.get("on", True):
            return [(topic + "/command", "off")]
        out.append((topic + "/command", "on"))
        color = setting.get("color")
        if color:
            r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
            out += [(topic + "/color/r", str(r)), (topic + "/color/g", str(g)),
                    (topic + "/color/b", str(b)), (topic + "/command", "go")]
    return out


def apply(bus, light_cfg: dict, setting: dict) -> None:
    for topic, payload in messages(light_cfg, setting):
        bus.publish(topic, payload)
