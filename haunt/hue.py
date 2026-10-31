"""Philips Hue rooms in the show (the living room and front bedroom).

The director does not talk to Hue itself. For a light of ``type: hue`` it
publishes the scene's setting as JSON, retained, on

    <prefix>/hue/<name>/set

and this program (``python3 -m haunt hue``, usually on home-pi next to the
director) turns that into calls to the Hue bridge's CLIP v2 API and runs the
animation. It also listens to

    <prefix>/director/online   "0" = director gone
    <prefix>/director/state    retained JSON; "phase": "stopped" = show over

and switches its rooms OFF whenever the show is not running: director offline,
show stopped, or this program stopping. Losing the broker leaves the rooms as
they are (they are room lights, not a fog machine).

A setting (in show.yaml, per scene or cue):

    living_room: "#ff6a00"                         solid colour
    living_room: off
    living_room:
      colors: ["#ff6a00", "#5a00a0"]               spread across the bulbs
      bri: 200                                     0-255 (colour brightness scales it too)
      animation: drift                             solid | drift | flicker | pulse | lightning
      effect: candle                               Hue's own effect, on bulbs that have it:
                                                   candle fire sparkle prism opal glisten
                                                   underwater cosmos sunbeam enchant
      period: 4                                    seconds per step of the animation
      low: 0.2                                     dimmest point, as a fraction of bri
      flash: "#d8e4ff"                             lightning flash colour
      transition: 1.0                              fade into this setting, seconds

    solid      every bulb fixed (several colours: bulb 1 gets colour 1 ...)
    drift      the colours slowly rotate round the bulbs, crossfading
    flicker    each bulb flickers on its own, like flame or a bad bulb
    pulse      the whole room breathes between bri and low (colours advance each breath)
    lightning  room held dim, with random white double-flashes

A bulb that lacks the requested Hue effect gets flicker (candle, fire) or
drift (the rest) instead. White-only bulbs follow the brightness only.

A show light is a Hue room or zone, or a list of bulbs by name (``lights:``
in hue.yaml), handy when outdoor lights share one Hue room. ``floor: 30``
(percent) keeps a light from going dimmer than that while the show runs
(through pulses and lightning); it does not stop the light switching off
when the show is over. Nothing uses it by default.

Hue asks for no more than about 10 light commands a second and 1 room
command a second; commands are queued and the newest command for a bulb
replaces an older one still waiting, so nothing backs up.

Config: /etc/haunt/hue.yaml (deploy/hue.example.yaml). Bridge key from
``python3 -m haunt hue --pair`` (press the bridge's button first).
"""

from __future__ import annotations

import http.client
import json
import logging
import os
import random
import socket
import ssl
import subprocess
import time
from collections import OrderedDict
from typing import Callable, Dict, List, Optional

log = logging.getLogger("haunt.hue")

ANIMATIONS = ("solid", "drift", "flicker", "pulse", "lightning")
EFFECTS = ("candle", "fire", "sparkle", "prism", "opal", "glisten",
           "underwater", "cosmos", "sunbeam", "enchant")
DEFAULT_PERIOD = {"solid": 0.0, "drift": 4.0, "flicker": 0.6, "pulse": 3.0, "lightning": 8.0}
DEFAULT_LOW = {"flicker": 0.35, "pulse": 0.15, "lightning": 0.12}
DEFAULT_FLASH = "#d8e4ff"
MIN_PERIOD = {"pulse": 2.0, "lightning": 1.5}   # room commands are limited to ~1/s


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

def _color(value) -> str:
    from .config import parse_color
    c = parse_color(value)
    if c is None:
        raise ValueError("missing colour")
    return c.lower()


def parse_setting(value) -> dict:
    """Normalise a show.yaml (or already normalised) Hue setting.
    Raises ValueError with a readable message."""
    if value is None or value is False or (isinstance(value, str) and value.strip().lower() == "off"):
        return {"on": False, "color": None}
    if not isinstance(value, dict) or {"r", "g", "b"} <= set(value):
        return parse_setting({"color": value})
    known = {"on", "color", "colors", "bri", "animation", "effect", "period", "low",
             "flash", "transition"}
    unknown = sorted(set(value) - known)
    if unknown:
        raise ValueError("unknown Hue setting(s) %s (Hue lights take: %s)"
                         % (", ".join(map(repr, unknown)), ", ".join(sorted(known))))
    if value.get("on") is False:
        return {"on": False, "color": None}
    cols = value.get("colors")
    if cols is not None:
        if not isinstance(cols, list) or not 1 <= len(cols) <= 8:
            raise ValueError("colors must be a list of 1 to 8 colours")
        colors = [_color(c) for c in cols]
    elif value.get("color") is not None:
        colors = [_color(value["color"])]
    else:
        colors = ["#ffffff"]
    anim = str(value.get("animation") or "solid").strip().lower()
    if anim not in ANIMATIONS:
        raise ValueError("animation %r is not one of %s" % (value.get("animation"), ", ".join(ANIMATIONS)))
    effect = value.get("effect")
    if effect is not None:
        effect = str(effect).strip().lower().replace(" ", "_")
        if effect in ("none", "no_effect", "off"):
            effect = None
        elif effect not in EFFECTS:
            raise ValueError("effect %r is not one of %s" % (value.get("effect"), ", ".join(EFFECTS)))
    bri = value.get("bri", 255)
    if isinstance(bri, bool) or not isinstance(bri, (int, float)) or not 0 <= bri <= 255:
        raise ValueError("bri %r is out of range 0-255" % (bri,))
    out = {"on": True, "color": colors[0], "colors": colors, "bri": int(bri), "animation": anim}
    if effect:
        out["effect"] = effect
    for key, lo, hi in (("period", 0.1, 600.0), ("low", 0.0, 1.0), ("transition", 0.0, 60.0)):
        v = value.get(key)
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
            raise ValueError("%s %r must be a number from %g to %g" % (key, v, lo, hi))
        out[key] = float(v)
    if anim in MIN_PERIOD and out.get("period") is not None and out["period"] < MIN_PERIOD[anim]:
        raise ValueError("period for %s must be at least %gs (Hue allows ~1 room command a second)"
                         % (anim, MIN_PERIOD[anim]))
    if value.get("flash") is not None:
        out["flash"] = _color(value["flash"])
    return out


def label(setting: dict) -> Optional[str]:
    """Short description for the console, e.g. 'Candle' or 'Drift 4s'."""
    if not setting or not setting.get("on", True):
        return None
    if setting.get("effect"):
        return setting["effect"].title()
    anim = setting.get("animation")
    if anim and anim != "solid":
        return anim.title()
    return None


def rgb_to_xy(color: str):
    """#rrggbb -> (x, y, level). level 0..1 is how bright the colour is meant to
    be (its largest channel), applied on top of bri."""
    r, g, b = (int(color[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
    level = max(r, g, b)

    def lin(c):
        return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92
    r, g, b = lin(r), lin(g), lin(b)
    # Wide-gamut RGB D65 conversion from Philips' developer notes.
    X = r * 0.664511 + g * 0.154324 + b * 0.162028
    Y = r * 0.283881 + g * 0.668433 + b * 0.047685
    Z = r * 0.000088 + g * 0.072310 + b * 0.986039
    s = X + Y + Z
    if s <= 0:
        return 0.3127, 0.3290, 0.0
    return round(X / s, 4), round(Y / s, 4), level


# --------------------------------------------------------------------------
# The bridge
# --------------------------------------------------------------------------

class HueError(Exception):
    def __init__(self, msg: str, status: int = 0):
        super().__init__(msg)
        self.status = status


class Bridge:
    """Minimal CLIP v2 client: one kept-alive HTTPS connection (a fresh TLS
    handshake per call is slow on a Pi 3). The bridge's certificate is
    self-signed, so it is not verified; this is the house LAN."""

    def __init__(self, host: str, key: str, timeout: float = 2.0, port: int = 443):
        self.host = host
        self.port = port
        self.key = key
        self.timeout = timeout
        self.conn = None
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE

    def _request(self, method: str, path: str, body=None):
        data = json.dumps(body, separators=(",", ":")).encode() if body is not None else None
        headers = {"hue-application-key": self.key, "Content-Type": "application/json"}
        last = None
        for attempt in (1, 2):              # a kept-alive connection may have been dropped
            try:
                if self.conn is None:
                    self.conn = http.client.HTTPSConnection(self.host, self.port, timeout=self.timeout,
                                                            context=self.ctx)
                self.conn.request(method, "/clip/v2" + path, body=data, headers=headers)
                resp = self.conn.getresponse()
                raw = resp.read()
                break
            except (OSError, http.client.HTTPException) as exc:
                last = exc
                self.close()
        else:
            raise HueError("bridge %s: %s" % (self.host, last))
        try:
            doc = json.loads(raw.decode() or "{}")
        except ValueError:
            doc = {}
        if resp.status >= 400:
            errs = "; ".join(e.get("description", "") for e in doc.get("errors") or []) or resp.reason
            raise HueError("bridge %s %s %s: %d %s" % (self.host, method, path, resp.status, errs),
                           resp.status)
        return doc.get("data", [])

    def get(self, path: str):
        return self._request("GET", path)

    def put(self, path: str, body: dict):
        return self._request("PUT", path, body)

    def close(self) -> None:
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

    def inventory(self) -> dict:
        """Rooms and zones: {name: {"kind", "group", "lights": [Bulb]}}."""
        lights = {l["id"]: l for l in self.get("/resource/light")}
        devices = {d["id"]: d for d in self.get("/resource/device")}
        out = {}
        for kind in ("room", "zone"):
            for g in self.get("/resource/" + kind):
                ids = []
                for child in g.get("children") or []:
                    if child.get("rtype") == "light":
                        ids.append(child["rid"])
                    elif child.get("rtype") == "device":
                        for svc in (devices.get(child["rid"]) or {}).get("services") or []:
                            if svc.get("rtype") == "light":
                                ids.append(svc["rid"])
                group = next((s["rid"] for s in g.get("services") or []
                              if s.get("rtype") == "grouped_light"), None)
                bulbs = [Bulb.from_resource(lights[i]) for i in ids if i in lights]
                name = (g.get("metadata") or {}).get("name") or g["id"]
                out[name] = {"kind": kind, "group": group, "lights": bulbs}
        return out


class Bulb:
    def __init__(self, id: str, name: str = "", color: bool = True, effects=()):
        self.id = id
        self.name = name or id
        self.color = color
        self.effects = set(effects)

    @classmethod
    def from_resource(cls, r: dict) -> "Bulb":
        eff = (r.get("effects") or {}).get("effect_values") or []
        eff2 = [e for e in ((r.get("effects_v2") or {}).get("action") or {}).get("effect_values") or []]
        return cls(r["id"], (r.get("metadata") or {}).get("name", ""), "color" in r,
                   [e for e in eff + eff2 if e != "no_effect"])

    def __repr__(self):
        return "Bulb(%r%s%s)" % (self.name, "" if self.color else ", white",
                                  (", " + "/".join(sorted(self.effects))) if self.effects else "")


def norm(name: str) -> str:
    return " ".join(str(name).lower().replace("_", " ").replace("-", " ").replace("'", "").split())


def pair(host: str, wait: float = 30.0, devicetype: Optional[str] = None, port: int = 443) -> str:
    """Ask the bridge for an application key. Press its round button first;
    this keeps asking for ``wait`` seconds."""
    devicetype = devicetype or "haunt#%s" % socket.gethostname()[:19]
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    end = time.monotonic() + wait
    while True:
        conn = http.client.HTTPSConnection(host, port, timeout=5, context=ctx)
        conn.request("POST", "/api", body=json.dumps({"devicetype": devicetype, "generateclientkey": True}),
                     headers={"Content-Type": "application/json"})
        doc = json.loads(conn.getresponse().read().decode() or "[]")
        conn.close()
        item = (doc or [{}])[0]
        if "success" in item:
            return item["success"]["username"]
        err = (item.get("error") or {})
        if err.get("type") != 101 or time.monotonic() > end:
            raise HueError("pairing failed: %s" % (err.get("description") or doc))
        time.sleep(2)


def discover() -> List[str]:
    """Bridge IPs: mDNS first (avahi), then Philips' discovery service."""
    found = []
    try:
        out = subprocess.run(["avahi-browse", "-rpt", "_hue._tcp"], capture_output=True,
                             text=True, timeout=8).stdout
        for line in out.splitlines():
            f = line.split(";")
            if f[0] == "=" and len(f) > 7 and f[2] == "IPv4" and f[7] not in found:
                found.append(f[7])
    except (OSError, subprocess.SubprocessError):
        pass
    if not found:
        try:
            import urllib.request
            with urllib.request.urlopen("https://discovery.meethue.com/", timeout=8) as r:
                for b in json.loads(r.read().decode()):
                    if b.get("internalipaddress") not in found:
                        found.append(b["internalipaddress"])
        except Exception as exc:
            log.debug("cloud discovery: %s", exc)
    return found


# --------------------------------------------------------------------------
# One room: what to send and when
# --------------------------------------------------------------------------

def _cmd(color: Optional[str], bri: float, bulb_color: bool = True, ms: Optional[int] = None,
         effect: Optional[str] = None) -> dict:
    """A light/grouped_light state body. bri is 0-255 before the colour's own level."""
    x = y = None
    level = 1.0
    if color:
        x, y, level = rgb_to_xy(color)
    pct = round(max(0.0, min(255.0, bri)) / 255.0 * 100.0 * level, 1)
    if pct < 0.5:
        body = {"on": {"on": False}}
    else:
        body = {"on": {"on": True}, "dimming": {"brightness": pct}}
        if bulb_color and x is not None:
            body["color"] = {"xy": {"x": x, "y": y}}
    if ms is not None:
        body["dynamics"] = {"duration": int(max(0, ms))}
    if effect is not None:
        body["effects"] = {"effect": effect}
    return body


def restore_body(r: dict) -> dict:
    """The command that puts a bulb back the way the bridge reported it
    (``r`` is a CLIP v2 light resource)."""
    eff_values = set((r.get("effects") or {}).get("effect_values") or [])
    status = (r.get("effects") or {}).get("status")
    body = {"dynamics": {"duration": 1000}}
    if not (r.get("on") or {}).get("on"):
        body["on"] = {"on": False}
    else:
        body["on"] = {"on": True}
        bri = (r.get("dimming") or {}).get("brightness")
        if bri is not None:
            body["dimming"] = {"brightness": bri}
        ct = r.get("color_temperature") or {}
        xy = (r.get("color") or {}).get("xy")
        if ct.get("mirek_valid") and ct.get("mirek"):
            body["color_temperature"] = {"mirek": ct["mirek"]}
        elif xy:
            body["color"] = {"xy": {"x": xy["x"], "y": xy["y"]}}
    if eff_values:
        body["effects"] = {"effect": status if status in eff_values and body["on"]["on"]
                           else "no_effect"}
    return body


class Room:
    def __init__(self, name: str, group: Optional[str], bulbs: List[Bulb], rng=None,
                 floor: float = 0.0):
        self.floor = float(floor or 0.0)     # minimum brightness %, while on
        self.name = name
        self.group = group
        self.bulbs = bulbs
        self.rng = rng or random.Random()
        self.s: Optional[dict] = None
        self.native: List[Bulb] = []     # bulbs running a Hue effect now
        self.anim_bulbs: List[Bulb] = []
        self.anim = "solid"
        self.events: List[tuple] = []    # (time, kind) for room-level steps
        self.next_bulb: Dict[str, float] = {}
        self.step = 0

    def _floored(self, body: dict) -> dict:
        """While the setting is on, never below the floor (dark colours and
        the dim phases of pulse/lightning included)."""
        if not self.floor or not self.s or not self.s.get("on", True):
            return body
        if body.get("on") == {"on": False}:
            body = dict(body, on={"on": True}, dimming={"brightness": self.floor})
        elif "dimming" in body and body["dimming"]["brightness"] < self.floor:
            body = dict(body, dimming={"brightness": self.floor})
        return body

    # (key, path, body) triples
    def _light(self, b: Bulb, body: dict):
        body = self._floored(body)
        if not b.color:
            body = {k: v for k, v in body.items() if k != "color"}
        return (("light", b.id), "/resource/light/" + b.id, body)

    def _light_raw(self, b: Bulb, body: dict):
        return (("light", b.id), "/resource/light/" + b.id, body)

    def _group(self, body: dict):
        body = self._floored(body)
        return (("group", self.group), "/resource/grouped_light/" + self.group, body)

    def _all(self, body: dict, bulbs: Optional[List[Bulb]] = None):
        bulbs = self.bulbs if bulbs is None else bulbs
        if self.group and len(bulbs) == len(self.bulbs) and len(bulbs) > 1:
            return [self._group(body)]
        return [self._light(b, dict(body)) for b in bulbs]

    def _par(self, key: str, default: float) -> float:
        v = (self.s or {}).get(key)
        return default if v is None else v

    def start(self, s: dict, now: float) -> list:
        """Switch to setting ``s``. Returns the commands to send now."""
        prev_native = set(b.id for b in self.native)
        self.s = s
        self.events = []
        self.next_bulb = {}
        self.step = 0
        if not s.get("on", True):
            self.native, self.anim_bulbs, self.anim = [], [], "solid"
            if prev_native:
                return [self._light(b, {"on": {"on": False}, "effects": {"effect": "no_effect"}})
                        for b in self.bulbs if b.id in prev_native] + \
                       [self._light(b, {"on": {"on": False}}) for b in self.bulbs if b.id not in prev_native]
            return self._all({"on": {"on": False}, "dynamics": {"duration": 400}})

        eff = s.get("effect")
        self.native = [b for b in self.bulbs if eff and eff in b.effects]
        self.anim_bulbs = [b for b in self.bulbs if b not in self.native]
        anim = s.get("animation", "solid")
        if eff and anim == "solid" and self.anim_bulbs:
            anim = "flicker" if eff in ("candle", "fire") else "drift"   # stand-in for missing effect
        self.anim = anim
        ms = int(self._par("transition", 1.0) * 1000)
        colors, bri = s["colors"], s["bri"]
        cmds = []
        for i, b in enumerate(self.native):
            cmds.append(self._light(b, _cmd(colors[i % len(colors)], bri, b.color, ms, eff)))
        low = self._par("low", DEFAULT_LOW.get(anim, 0.2))
        start_bri = bri * low if anim == "lightning" else bri
        bodies = [_cmd(colors[i % len(colors)], start_bri, True, ms,
                       "no_effect" if b.id in prev_native else None)
                  for i, b in enumerate(self.anim_bulbs)]
        if bodies and all(bd == bodies[0] for bd in bodies):
            cmds += self._all(bodies[0], self.anim_bulbs)
        else:
            cmds += [self._light(b, bd) for b, bd in zip(self.anim_bulbs, bodies)]
        # the first animation step comes after the fade in
        t0 = now + ms / 1000.0
        period = self._par("period", DEFAULT_PERIOD.get(anim, 4.0))
        if anim == "drift" and (len(colors) > 1):
            self.events = [(t0 + period, "drift")]
        elif anim == "pulse":
            self.events = [(t0, "pulse")]
        elif anim == "lightning":
            self.events = [(t0 + self.rng.uniform(0.3, 1.0) * period, "flash")]
        elif anim == "flicker":
            for b in self.anim_bulbs:
                self.next_bulb[b.id] = t0 + self.rng.uniform(0, period)
        return cmds

    def tick(self, now: float) -> list:
        if not self.s or not self.s.get("on", True):
            return []
        s = self.s
        colors, bri, anim = s["colors"], s["bri"], self.anim
        period = self._par("period", DEFAULT_PERIOD.get(anim, 4.0))
        low = self._par("low", DEFAULT_LOW.get(anim, 0.2))
        cmds = []
        for b in self.anim_bulbs:                          # flicker: each bulb on its own clock
            t = self.next_bulb.get(b.id)
            if t is not None and now >= t:
                gap = period * self.rng.uniform(0.35, 1.0)
                level = self.rng.uniform(low, 1.0)
                if self.rng.random() < 0.12:
                    level = low * self.rng.uniform(0.3, 1.0)  # an occasional deep dip
                i = self.anim_bulbs.index(b)
                cmds.append(self._light(b, _cmd(colors[(i + self.rng.randrange(len(colors))) % len(colors)]
                                                if len(colors) > 1 and self.rng.random() < 0.25
                                                else colors[i % len(colors)],
                                                bri * level, True, int(gap * 700))))
                self.next_bulb[b.id] = now + gap
        due = [e for e in self.events if now >= e[0]]
        self.events = [e for e in self.events if now < e[0]]
        for _t, kind in due:
            if kind == "drift":
                self.step += 1
                for i, b in enumerate(self.anim_bulbs):
                    cmds.append(self._light(b, _cmd(colors[(i + self.step) % len(colors)], bri, True,
                                                    int(period * 1000))))
                self.events.append((now + period, "drift"))
            elif kind == "pulse":
                half = period / 2.0
                high = self.step % 2 == 0
                c = colors[(self.step // 2) % len(colors)]
                self.step += 1
                cmds += self._all(_cmd(c, bri if high else bri * low, True, int(half * 1000)),
                                  self.anim_bulbs)
                self.events.append((now + half, "pulse"))
            elif kind == "flash":
                flash = s.get("flash", DEFAULT_FLASH)
                cmds += self._all(_cmd(flash, 255, True, 0), self.anim_bulbs)
                self.events.append((now + self.rng.uniform(0.08, 0.16), "dark"))
                if self.rng.random() < 0.5:
                    self.events.append((now + self.rng.uniform(0.3, 0.45), "flash2"))
                self.events.append((now + period * self.rng.uniform(0.5, 1.5) + 0.5, "flash"))
            elif kind == "flash2":
                # second strike: per bulb, so it does not hit the room-command limit
                flash = s.get("flash", DEFAULT_FLASH)
                cmds += [self._light(b, _cmd(flash, 200, True, 0)) for b in self.anim_bulbs]
                self.events.append((now + self.rng.uniform(0.06, 0.12), "dark"))
            elif kind == "dark":
                cmds += [self._light(b, _cmd(colors[i % len(colors)], bri * low, True,
                                             int(self.rng.uniform(300, 900))))
                         for i, b in enumerate(self.anim_bulbs)]
        return cmds


# --------------------------------------------------------------------------
# The agent: MQTT in, bridge out
# --------------------------------------------------------------------------

class Bucket:
    def __init__(self, rate: float, burst: float, clock):
        self.rate, self.burst, self.clock = rate, burst, clock
        self.tokens = burst
        self.t = clock()

    def take(self) -> bool:
        now = self.clock()
        self.tokens = min(self.burst, self.tokens + (now - self.t) * self.rate)
        self.t = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


class HueAgent:
    def __init__(self, rooms_cfg: Dict[str, dict], bridge, bus, prefix: str = "haunt",
                 clock: Callable[[], float] = time.monotonic, rng=None,
                 rate: float = 10.0, group_rate: float = 1.0, resolve_every: float = 30.0):
        self.cfg = rooms_cfg                 # show light name -> {"room": Hue name, "topic": ...}
        self.bridge = bridge
        self.bus = bus
        self.prefix = prefix
        self.clock = clock
        self.rng = rng or random.Random()
        self.rooms: Dict[str, Room] = {}
        self.wanted: Dict[str, Optional[dict]] = {n: None for n in rooms_cfg}
        self.applied: Dict[str, Optional[dict]] = {n: None for n in rooms_cfg}
        self.director_online: Optional[bool] = None
        self.phase: Optional[str] = None
        self.queue: "OrderedDict[tuple, tuple]" = OrderedDict()
        self.lights_bucket = Bucket(rate, max(rate, 1.0), clock)
        self.group_bucket = Bucket(group_rate, 2.0, clock)
        self.resolve_every = resolve_every
        self.next_resolve = 0.0
        self.hold_until = 0.0                # back off after a bridge error
        self.status: Dict[str, str] = {}
        # haunt/hue/control: True = the show drives the rooms, False = left
        # to the house (released), None = not heard yet (retained, so it
        # normally arrives at once; give it a moment before taking over).
        self.control: Optional[bool] = None
        self.control_wait_until = clock() + 3.0
        self.saved: Dict[str, list] = {}     # name -> commands that put the room back
        self.ok_text: Dict[str, str] = {}
        self.by_topic = {c["topic"] + "/set": n for n, c in rooms_cfg.items()}
        for t in self.by_topic:
            bus.subscribe(t)
        bus.subscribe("%s/director/online" % prefix)
        bus.subscribe("%s/director/state" % prefix)
        bus.subscribe("%s/hue/control" % prefix)

    # -- inputs ----------------------------------------------------------

    def handle(self, topic: str, payload: str) -> None:
        if topic == "%s/hue/control" % self.prefix:
            word = payload.strip().lower()
            control = word not in ("released", "release", "off", "0", "house")
            if control != self.control:
                log.info("Hue rooms: %s", "the show drives them" if control else "released to the house")
            self.control = control
            return
        if topic == "%s/director/online" % self.prefix:
            self.director_online = payload.strip() != "0"
            return
        if topic == "%s/director/state" % self.prefix:
            try:
                self.phase = json.loads(payload).get("phase")
            except (ValueError, AttributeError):
                pass
            return
        name = self.by_topic.get(topic)
        if name is None:
            return
        if not payload.strip():
            self.wanted[name] = None
            return
        try:
            self.wanted[name] = parse_setting(json.loads(payload) if payload.strip()[:1] in "{[\"" else payload)
        except (ValueError, TypeError) as exc:
            log.error("%s: bad setting %r: %s", name, payload[:200], exc)

    def in_control(self) -> bool:
        if self.control is None:
            return self.clock() >= self.control_wait_until
        return self.control

    def show_running(self) -> bool:
        return self.director_online is True and self.phase not in (None, "stopped")

    def target(self, name: str) -> dict:
        w = self.wanted.get(name)
        if w is None or not self.show_running():
            return {"on": False, "color": None}
        return w

    # -- the bridge ------------------------------------------------------

    def resolve(self) -> None:
        inv = self.bridge.inventory()
        by_norm = {norm(k): (k, v) for k, v in inv.items()}
        bulbs_by_name = {}
        for info in inv.values():
            for b in info["lights"]:
                bulbs_by_name.setdefault(norm(b.name), b)
        for name, c in self.cfg.items():
            if c.get("lights"):
                found = [bulbs_by_name.get(norm(n)) for n in c["lights"]]
                missing = [n for n, b in zip(c["lights"], found) if b is None]
                if missing:
                    self._status(name, "error: no Hue bulb called %s (have: %s)"
                                 % (", ".join(map(repr, missing)),
                                    ", ".join(sorted(b.name for b in bulbs_by_name.values()))))
                    continue
                real, info = " + ".join(b.name for b in found), {"kind": "bulbs", "group": None,
                                                                   "lights": found}
            else:
                hit = by_norm.get(norm(c.get("room") or name))
                if not hit:
                    self._status(name, "error: no Hue room or zone %r (have: %s)"
                                 % (c.get("room") or name, ", ".join(sorted(inv))))
                    continue
                real, info = hit
            if not info["lights"]:
                self._status(name, "error: %r has no lights" % real)
                continue
            old = self.rooms.get(name)
            if old and [b.id for b in old.bulbs] == [b.id for b in info["lights"]]:
                continue
            self.rooms[name] = Room(real, info["group"], info["lights"], self.rng,
                                    floor=c.get("floor") or 0.0)
            if self.applied[name] != "released":
                self.applied[name] = None      # (re)apply what it should be showing
            log.info("%s -> Hue %s %r: %s", name, info["kind"], real, info["lights"])
            self.ok_text[name] = "ok: %s, %d bulb(s)" % (real, len(info["lights"]))
            if self.applied.get(name) != "released":
                self._status(name, self.ok_text[name])

    def _status(self, name: str, text: str) -> None:
        if self.status.get(name) == text:
            return
        self.status[name] = text
        (log.error if text.startswith("error") else log.info)("%s: %s", name, text)
        if getattr(self.bus, "connected", False):
            self.bus.publish("%s/hue/%s/status" % (self.prefix, name), text, retain=True)

    def enqueue(self, cmds) -> None:
        for key, path, body in cmds:
            if key[0] == "group":                 # supersedes anything waiting for its bulbs
                room = next((r for r in self.rooms.values() if r.group == key[1]), None)
                for b in (room.bulbs if room else []):
                    self.queue.pop(("light", b.id), None)
            self.queue.pop(key, None)
            self.queue[key] = (path, body)

    def drain(self) -> None:
        now = self.clock()
        while self.queue and now >= self.hold_until:
            key, (path, body) = next(iter(self.queue.items()))
            bucket = self.group_bucket if key[0] == "group" else self.lights_bucket
            if not bucket.take():
                return
            self.queue.pop(key)
            try:
                self.bridge.put(path, body)
            except HueError as exc:
                if exc.status == 429:
                    self.hold_until = now + 1.0
                    self.queue[key] = (path, body)
                    self.queue.move_to_end(key, last=False)
                    return
                log.error("%s", exc)
                if exc.status in (0, 503):          # bridge unreachable: retry and re-apply later
                    self.hold_until = now + 5.0
                    self.queue.clear()
                    for n in self.applied:
                        self.applied[n] = None
                    return

    # -- the loop --------------------------------------------------------

    def tick(self) -> None:
        now = self.clock()
        if now >= self.next_resolve and now >= self.hold_until and len(self.rooms) < len(self.cfg):
            self.next_resolve = now + self.resolve_every
            try:
                self.resolve()
            except HueError as exc:
                log.error("cannot read rooms from the bridge: %s", exc)
                self.hold_until = now + 5.0
        if not self.in_control():
            if self.control is False:
                self.release()
            self.drain()
            return
        self.take_over()
        for name, room in self.rooms.items():
            if name not in self.saved:
                continue
            t = self.target(name)
            if t != self.applied[name]:
                self.applied[name] = t
                log.info("%s: %s", name, json.dumps(t))
                self.enqueue(room.start(t, now))
            else:
                self.enqueue(room.tick(now))
        self.drain()

    def take_over(self) -> None:
        """Remember how each room looks before the show first changes it, so
        releasing it can put it back."""
        need = [n for n in self.rooms if n not in self.saved]
        if not need or self.clock() < self.hold_until:
            return
        try:
            res = {r["id"]: r for r in self.bridge.get("/resource/light")}
        except HueError as exc:
            # Do not touch a room before knowing how to put it back.
            log.warning("cannot read the lights to remember them: %s", exc)
            self.hold_until = self.clock() + (1.0 if exc.status == 429 else 5.0)
            return
        for name in need:
            room = self.rooms[name]
            self.saved[name] = [room._light_raw(b, restore_body(res[b.id]))
                                for b in room.bulbs if b.id in res]
            if self.applied[name] == "released":
                self.applied[name] = None
                self._status(name, self.ok_text.get(name, "ok"))

    def release(self) -> None:
        """Stop driving the rooms and put them back as they were."""
        for name, room in self.rooms.items():
            if self.applied[name] == "released":
                continue
            ids = set(b.id for b in room.bulbs)
            for key in list(self.queue):
                if key == ("group", room.group) or (key[0] == "light" and key[1] in ids):
                    self.queue.pop(key)
            self.enqueue(self.saved.pop(name, []))
            room.s, room.events, room.next_bulb, room.native = None, [], {}, []
            self.applied[name] = "released"
            self._status(name, "released to the house")

    def all_off(self, wait: float = 2.0) -> None:
        """Off now, sent directly (used on the way out). Released rooms
        are left alone."""
        if not self.in_control():
            return
        self.director_online = False
        now = self.clock()
        self.hold_until = 0.0
        for name, room in self.rooms.items():
            self.applied[name] = off = {"on": False, "color": None}
            self.enqueue(room.start(off, now))
        end = time.monotonic() + wait
        while self.queue and time.monotonic() < end:
            self.drain()
            time.sleep(0.05)


# --------------------------------------------------------------------------
# Config and entry points
# --------------------------------------------------------------------------

HUE_DEFAULTS = {
    "bridge": "auto",                  # IP address, or "auto" (mDNS / Philips discovery)
    "key": None,                       # normally in key_file instead
    "key_file": "/etc/haunt/hue.key",
    "rate": 10.0,                      # light commands a second
    "rooms": {"living_room": "Living room", "front_bedroom": "Front bedroom",
              "porch": "Porch", "lamp_post": "Lamp post"},
}


def load_config(path: Optional[str], bridge: Optional[str] = None,
                broker: Optional[str] = None, need_mqtt: bool = True) -> dict:
    import yaml
    from .config import ConfigError, resolve_mqtt
    data = {}
    if path:
        try:
            with open(path) as fh:
                data = yaml.safe_load(fh) or {}
        except OSError as exc:
            raise ConfigError("cannot read %s: %s" % (path, exc))
        except yaml.YAMLError as exc:
            raise ConfigError("%s is not valid YAML: %s" % (path, exc))
    unknown = set(data) - set(HUE_DEFAULTS) - {"mqtt"}
    if unknown:
        raise ConfigError(["hue config: unknown setting %r" % k for k in sorted(unknown)])
    cfg = dict(HUE_DEFAULTS)
    cfg.update({k: v for k, v in data.items() if k != "mqtt"})
    if bridge:
        cfg["bridge"] = bridge
    mqtt = dict(data.get("mqtt") or {})
    if broker:
        mqtt["host"] = broker
    cfg["mqtt"] = resolve_mqtt(mqtt) if need_mqtt else mqtt
    prefix = cfg["mqtt"].get("prefix", "haunt")
    rooms = {}
    for name, room in (cfg["rooms"] or {}).items():
        if isinstance(room, dict):
            r = dict(room)
        else:
            r = {"room": str(room)}
        unknown = set(r) - {"room", "lights", "floor", "topic"}
        if unknown:
            raise ConfigError(["hue config: rooms.%s: unknown setting %r (room, lights, floor)" % (name, k)
                               for k in sorted(unknown)])
        if r.get("lights") is not None:
            if isinstance(r["lights"], str):
                r["lights"] = [r["lights"]]
            if not isinstance(r["lights"], list) or not r["lights"]:
                raise ConfigError("hue config: rooms.%s: lights must be a list of bulb names" % name)
            r["lights"] = [str(x) for x in r["lights"]]
        else:
            r.setdefault("room", str(name))
        fl = r.get("floor", 0) or 0
        if isinstance(fl, bool) or not isinstance(fl, (int, float)) or not 0 <= fl <= 100:
            raise ConfigError("hue config: rooms.%s: floor must be 0-100 (percent)" % name)
        r["floor"] = float(fl)
        r.setdefault("topic", "%s/hue/%s" % (prefix, name))
        rooms[str(name)] = r
    if not rooms:
        raise ConfigError("hue config: no rooms")
    cfg["rooms"] = rooms
    cfg["rate"] = float(cfg["rate"])
    return cfg


def read_key(cfg: dict) -> str:
    from .config import ConfigError
    key = os.environ.get("HAUNT_HUE_KEY") or cfg.get("key")
    if not key and cfg.get("key_file"):
        try:
            with open(os.path.expanduser(cfg["key_file"])) as fh:
                key = fh.read().strip()
        except OSError:
            pass
    if not key:
        raise ConfigError("no Hue key: press the bridge button, then run  python3 -m haunt hue --pair")
    return key


def bridge_host(cfg: dict) -> str:
    from .config import ConfigError
    host = cfg.get("bridge") or "auto"
    if host != "auto":
        return host
    found = discover()
    if not found:
        raise ConfigError("no Hue bridge found on the network; set bridge: <ip> in hue.yaml")
    if len(found) > 1:
        log.warning("several Hue bridges (%s); using %s", ", ".join(found), found[0])
    return found[0]


def main(cfg: dict) -> None:
    from .bus import MqttBus
    prefix = cfg["mqtt"].get("prefix", "haunt")
    online = "%s/hue/online" % prefix
    bridge = Bridge(bridge_host(cfg), read_key(cfg))
    bus = MqttBus(cfg["mqtt"], "hue", will=(online, "0"), birth=(online, "1"))
    agent = HueAgent(cfg["rooms"], bridge, bus, prefix=prefix, rate=cfg["rate"])
    log.info("Hue bridge %s; lights: %s", bridge.host,
             ", ".join("%s = %r" % (n, c.get("room") or c.get("lights")) for n, c in cfg["rooms"].items()))
    try:
        while True:
            for topic, payload in bus.poll(timeout=0.02):
                agent.handle(topic, payload)
            agent.tick()
    finally:
        agent.all_off()
        bridge.close()
        bus.close()


def cmd_pair(cfg: dict) -> None:
    host = bridge_host(cfg)
    print("bridge %s: press its round link button now (waiting 30 s)..." % host)
    key = pair(host)
    path = cfg.get("key_file") or "/etc/haunt/hue.key"
    try:
        fd = os.open(os.path.expanduser(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(key + "\n")
        print("paired; key saved in %s" % path)
    except OSError as exc:
        print("paired, but could not write %s (%s). The key is:\n%s" % (path, exc, key))
    if cfg.get("bridge") in (None, "auto"):
        print("tip: put  bridge: %s  in hue.yaml so it never has to search" % host)


def cmd_list(cfg: dict) -> None:
    bridge = Bridge(bridge_host(cfg), read_key(cfg))
    inv = bridge.inventory()
    wanted = {norm(c["room"]): n for n, c in cfg["rooms"].items() if c.get("room")}
    wanted_bulbs = {norm(b): n for n, c in cfg["rooms"].items() for b in c.get("lights") or []}
    print("bridge %s" % bridge.host)
    for name, info in sorted(inv.items()):
        tag = ("   <- %s" % wanted[norm(name)]) if norm(name) in wanted else ""
        print("%s %r%s" % (info["kind"], name, tag))
        for b in info["lights"]:
            caps = "colour" if b.color else "white only"
            if b.effects:
                caps += "; effects: " + ", ".join(sorted(b.effects))
            tag = ("   <- %s" % wanted_bulbs[norm(b.name)]) if norm(b.name) in wanted_bulbs else ""
            print("    %-28s %s%s" % (b.name, caps, tag))
    missing = [n for k, n in wanted.items() if k not in {norm(x) for x in inv}]
    for n in missing:
        print("!! %s: no room or zone called %r" % (n, cfg["rooms"][n]["room"]))
    names = {norm(b.name) for info in inv.values() for b in info["lights"]}
    for k, n in wanted_bulbs.items():
        if k not in names:
            print("!! %s: no bulb called %r" % (n, k))
    bridge.close()


class _NullBus:
    connected = False

    def subscribe(self, p):
        pass

    def publish(self, *a, **k):
        pass


def bench_test(cfg: dict, room: str, setting, seconds: float) -> None:
    """Run one setting on one room with no MQTT, then switch it off."""
    if room not in cfg["rooms"]:
        raise SystemExit("unknown room %r (have: %s)" % (room, ", ".join(cfg["rooms"])))
    if isinstance(setting, str):
        try:
            setting = json.loads(setting)
        except ValueError:
            pass
    s = parse_setting(setting)
    bridge = Bridge(bridge_host(cfg), read_key(cfg))
    agent = HueAgent({room: cfg["rooms"][room]}, bridge, _NullBus(), rate=cfg["rate"])
    agent.director_online, agent.phase = True, "running"
    agent.wanted[room] = s
    print("%s: %s for %gs" % (room, json.dumps(s), seconds))
    end = time.monotonic() + seconds
    try:
        while time.monotonic() < end:
            agent.tick()
            time.sleep(0.02)
    finally:
        agent.all_off()
        bridge.close()
    print("off")
