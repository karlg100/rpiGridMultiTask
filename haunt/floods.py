"""The AiDot solar flood lights: a row of lights across the front of the
house (1 by the Window projector ... 15 by the Wall projector), driven through
Home Assistant.

The director does not talk to Home Assistant itself. For a light of
``type: floods`` it publishes the scene's setting as JSON, retained, on

    <prefix>/floods/<name>/set

and this program (``python3 -m haunt floods``, on home-pi next to the
director) works out what every light in the row should show, a few times a
second, and sends only the lights that changed to Home Assistant's REST API
(``light.turn_on`` / ``light.turn_off``). Lights that need the same thing at
the same moment share one call. It also listens to

    <prefix>/director/online   "0" = director gone
    <prefix>/director/state    retained JSON; "phase": "stopped" = show over

and puts the row in its idle setting (off, by default) whenever the show is
not running: director offline, show stopped, or this program stopping.

A setting (in show.yaml, per scene or cue):

    floods: "#ff6a00"                            every light that colour
    floods: off
    floods:
      colors: ["#ff6a00", "#5a00a0"]             laid along the row (see pattern)
      pattern: alternate                         alternate | blocks | gradient
      bri: 200                                   0-255 (a dark colour is dimmer too)
      animation: chase                           solid | drift | flicker | pulse |
                                                 lightning | chase | wave | sparkle
      period: 4                                  seconds (see below)
      low: 0.1                                   dimmest point, as a fraction of bri
      direction: right                           right (1 -> 15) | left | bounce
      width: 3                                   chase: lights in the moving group
      flash: "#d8e4ff"                           lightning / sparkle flash colour
      transition: 0.5                            fade in, seconds (if the lights can)

    pattern    alternate  1 gets colour 1, 2 gets colour 2, ... and round again
               blocks     the row split into one block per colour (two colours:
                          Window half and Wall half)
               gradient   colours blended along the row

    solid      fixed
    drift      the pattern crawls along the row one light every period
    flicker    each light flickers on its own (flame, failing bulb); period = how often
    pulse      the whole row breathes between bri and low; period = one breath;
               with several colours, the colours swap each breath
    lightning  held dim, random white strikes across part or all of the row;
               period = average gap between strikes
    chase      a group of `width` lights runs along the row with a fading tail;
               period = one pass of the row
    wave       brightness rolls along the row like a swell; period = one wave
    sparkle    held dim, random lights flare up; period = average gap per light

Config: /etc/haunt/floods.yaml (deploy/floods.example.yaml). Token: a Home
Assistant long-lived access token in /etc/haunt/ha.token.
"""

from __future__ import annotations

import http.client
import json
import logging
import math
import os
import random
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional, Tuple

log = logging.getLogger("haunt.floods")

ANIMATIONS = ("solid", "drift", "flicker", "pulse", "lightning", "chase", "wave", "sparkle")
PATTERNS = ("alternate", "blocks", "gradient")
DIRECTIONS = ("right", "left", "bounce")
DEFAULT_PERIOD = {"solid": 0.0, "drift": 2.0, "flicker": 0.8, "pulse": 3.0, "lightning": 6.0,
                  "chase": 4.0, "wave": 4.0, "sparkle": 3.0}
DEFAULT_LOW = {"flicker": 0.3, "pulse": 0.1, "lightning": 0.08, "chase": 0.05, "wave": 0.08,
               "sparkle": 0.25}
DEFAULT_FLASH = "#d8e4ff"
TRANSITION_FEATURE = 32       # LightEntityFeature.TRANSITION

OFF = None                    # a light's state: None = off, else ((r, g, b), brightness 1-255)


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

def _color(value) -> str:
    from .config import parse_color
    c = parse_color(value)
    if c is None:
        raise ValueError("missing colour")
    return c.lower()


def _num(value, key, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi:
        raise ValueError("%s %r must be a number from %g to %g" % (key, value, lo, hi))
    return float(value)


def parse_setting(value) -> dict:
    """Normalise a show.yaml (or already normalised) floods setting.
    Raises ValueError with a readable message."""
    if value is None or value is False or (isinstance(value, str) and value.strip().lower() == "off"):
        return {"on": False, "color": None}
    if not isinstance(value, dict) or {"r", "g", "b"} <= set(value):
        return parse_setting({"color": value})
    known = {"on", "color", "colors", "bri", "animation", "pattern", "period", "low",
             "direction", "width", "flash", "transition"}
    unknown = sorted(set(value) - known)
    if unknown:
        raise ValueError("unknown floods setting(s) %s (floods take: %s)"
                         % (", ".join(map(repr, unknown)), ", ".join(sorted(known))))
    if value.get("on") is False:
        return {"on": False, "color": None}
    cols = value.get("colors")
    if cols is not None:
        if not isinstance(cols, list) or not 1 <= len(cols) <= 15:
            raise ValueError("colors must be a list of 1 to 15 colours")
        colors = [_color(c) for c in cols]
    elif value.get("color") is not None:
        colors = [_color(value["color"])]
    else:
        colors = ["#ffffff"]
    anim = str(value.get("animation") or "solid").strip().lower()
    if anim not in ANIMATIONS:
        raise ValueError("animation %r is not one of %s" % (value.get("animation"), ", ".join(ANIMATIONS)))
    pattern = str(value.get("pattern") or "alternate").strip().lower()
    if pattern not in PATTERNS:
        raise ValueError("pattern %r is not one of %s" % (value.get("pattern"), ", ".join(PATTERNS)))
    direction = str(value.get("direction") or "right").strip().lower()
    if direction not in DIRECTIONS:
        raise ValueError("direction %r is not one of %s" % (value.get("direction"), ", ".join(DIRECTIONS)))
    bri = value.get("bri", 255)
    if isinstance(bri, bool) or not isinstance(bri, (int, float)) or not 0 <= bri <= 255:
        raise ValueError("bri %r is out of range 0-255" % (bri,))
    out = {"on": True, "color": colors[0], "colors": colors, "bri": int(bri), "animation": anim}
    if pattern != "alternate":
        out["pattern"] = pattern
    if direction != "right":
        out["direction"] = direction
    for key, lo, hi in (("period", 0.5, 600.0), ("low", 0.0, 1.0), ("transition", 0.0, 60.0),
                        ("width", 1, 15)):
        if value.get(key) is not None:
            out[key] = _num(value[key], key, lo, hi)
    if "width" in out:
        out["width"] = int(out["width"])
    if value.get("flash") is not None:
        out["flash"] = _color(value["flash"])
    return out


# --------------------------------------------------------------------------
# Colour helpers
# --------------------------------------------------------------------------

def _rgb(color: str) -> Tuple[int, int, int]:
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def _mix(a: str, b: str, f: float) -> str:
    ra, rb = _rgb(a), _rgb(b)
    return _hex([x + (y - x) * f for x, y in zip(ra, rb)])


def light_state(color: Optional[str], bri: float, step: int = 4):
    """(colour, brightness 0-255 before the colour's own level) -> what to
    send: None (off) or ((r, g, b) at full level, brightness 1-255).
    Brightness is rounded to `step` so tiny changes are not sent."""
    if not color:
        return OFF
    r, g, b = _rgb(color)
    level = max(r, g, b) / 255.0
    value = max(0.0, min(255.0, bri)) * level
    if value < 1.0:
        return OFF
    if step > 1:
        value = max(1, int(round(value / step)) * step)
    full = tuple(int(round(c / level)) for c in (r, g, b)) if level > 0 else (255, 255, 255)
    return (full, int(min(255, max(1, round(value)))))


# --------------------------------------------------------------------------
# One row: what each light shows at a given moment
# --------------------------------------------------------------------------

class Row:
    def __init__(self, n: int, rng=None):
        self.n = n
        self.rng = rng or random.Random()
        self.s: Optional[dict] = None
        self.t0 = 0.0
        self.next_change: List[float] = [0.0] * n     # flicker / sparkle clocks
        self.level: List[float] = [1.0] * n
        self.flare_until: List[float] = [0.0] * n
        self.strikes: List[tuple] = []                # lightning: (start, end, lo, hi, colour)
        self.next_strike = 0.0

    def _par(self, key: str, default: float) -> float:
        v = (self.s or {}).get(key)
        return default if v is None else v

    def start(self, s: dict, now: float) -> None:
        self.s = s
        self.t0 = now
        self.strikes = []
        anim = s.get("animation", "solid")
        period = self._par("period", DEFAULT_PERIOD.get(anim, 4.0))
        self.level = [1.0] * self.n
        self.flare_until = [0.0] * self.n
        self.next_change = [now + self.rng.uniform(0, max(period, 0.1)) for _ in range(self.n)]
        self.next_strike = now + self.rng.uniform(0.3, 1.0) * period

    def base(self, i: int, shift: int = 0) -> str:
        """The pattern colour for light i (0-based), shifted along the row."""
        s = self.s
        cols = s["colors"]
        k = len(cols)
        p = (i - shift) % self.n
        pattern = s.get("pattern", "alternate")
        if k == 1:
            return cols[0]
        if pattern == "blocks":
            return cols[min(k - 1, p * k // self.n)]
        if pattern == "gradient":
            x = p / max(1, self.n - 1) * (k - 1)
            j = min(k - 2, int(x))
            return _mix(cols[j], cols[j + 1], x - j)
        return cols[p % k]

    def _dir(self) -> int:
        return -1 if (self.s or {}).get("direction") == "left" else 1

    def frame(self, now: float) -> List[Tuple[Optional[str], float]]:
        """[(colour or None, brightness 0-255), ...] for lights 1..n."""
        s = self.s
        n = self.n
        if not s or not s.get("on", True):
            return [(None, 0.0)] * n
        bri = float(s["bri"])
        anim = s.get("animation", "solid")
        period = self._par("period", DEFAULT_PERIOD.get(anim, 4.0)) or 1.0
        low = self._par("low", DEFAULT_LOW.get(anim, 0.2))
        t = now - self.t0
        out = []
        if anim == "solid":
            return [(self.base(i), bri) for i in range(n)]
        if anim == "drift":
            shift = int(t / period) * self._dir()
            return [(self.base(i, shift), bri) for i in range(n)]
        if anim == "flicker":
            for i in range(n):
                if now >= self.next_change[i]:
                    lv = self.rng.uniform(low, 1.0)
                    if self.rng.random() < 0.12:
                        lv = low * self.rng.uniform(0.3, 1.0)       # an occasional deep dip
                    self.level[i] = lv
                    self.next_change[i] = now + period * self.rng.uniform(0.35, 1.0)
                out.append((self.base(i), bri * self.level[i]))
            return out
        if anim == "pulse":
            phase = t / period
            lv = low + (1.0 - low) * (0.5 + 0.5 * math.cos(2 * math.pi * phase))
            lv = round(lv * 10) / 10.0
            shift = int(phase + 0.5)                                 # swap colours at the dim point
            return [(self.base(i, shift), bri * lv) for i in range(n)]
        if anim == "wave":
            for i in range(n):
                x = t / period - self._dir() * i / n
                lv = low + (1.0 - low) * (0.5 + 0.5 * math.cos(2 * math.pi * x))
                out.append((self.base(i), bri * round(lv * 6) / 6.0))
            return out
        if anim == "chase":
            width = int(s.get("width") or 3)
            if s.get("direction") == "bounce":
                span = max(1, 2 * (n - 1))
                pos = (t / period * span) % span
                head = pos if pos <= n - 1 else span - pos
                moving_right = pos <= n - 1
                for i in range(n):
                    behind = (head - i) if moving_right else (i - head)
                    out.append((self.base(i), bri * self._tail(behind, width, low)))
                return out
            head = (t / period * n) % n
            if self._dir() < 0:
                head = n - 1 - head
            for i in range(n):
                behind = ((head - i) % n) if self._dir() > 0 else ((i - head) % n)
                out.append((self.base(i), bri * self._tail(behind, width, low)))
            return out
        if anim == "sparkle":
            flash = s.get("flash")
            for i in range(n):
                if now >= self.next_change[i]:
                    self.flare_until[i] = now + self.rng.uniform(0.25, 0.6)
                    self.next_change[i] = now + self.rng.expovariate(1.0 / period) + 0.6
                if now < self.flare_until[i]:
                    out.append((flash or self.base(i), bri))
                else:
                    out.append((self.base(i), bri * low))
            return out
        if anim == "lightning":
            if now >= self.next_strike:
                flash = s.get("flash", DEFAULT_FLASH)
                w = self.rng.randint(max(3, n // 3), n)
                lo = self.rng.randint(0, n - w)
                end = now + self.rng.uniform(0.12, 0.22)
                self.strikes.append((now, end, lo, lo + w, flash))
                if self.rng.random() < 0.5:                         # a second strike
                    t2 = end + self.rng.uniform(0.15, 0.35)
                    self.strikes.append((t2, t2 + self.rng.uniform(0.08, 0.16), lo, lo + w, flash))
                self.next_strike = now + period * self.rng.uniform(0.5, 1.5) + 0.8
            self.strikes = [st for st in self.strikes if st[1] > now]
            lit = [st for st in self.strikes if st[0] <= now]
            for i in range(n):
                hit = next((st for st in lit if st[2] <= i < st[3]), None)
                out.append((hit[4], 255.0) if hit else (self.base(i), bri * low))
            return out
        return [(self.base(i), bri) for i in range(n)]

    @staticmethod
    def _tail(behind: float, width: int, low: float) -> float:
        """Chase brightness for a light `behind` lights behind the head."""
        if behind < -0.5 or behind >= width + 0.5:
            return low
        if behind < 1.0:
            return 1.0
        return max(low, 1.0 - (behind / (width + 0.5)) * (1.0 - low))


# --------------------------------------------------------------------------
# Home Assistant
# --------------------------------------------------------------------------

class HAError(Exception):
    def __init__(self, msg: str, status: int = 0):
        super().__init__(msg)
        self.status = status


class HomeAssistant:
    """Tiny REST client. One keep-alive connection per thread."""

    def __init__(self, url: str, token: str, timeout: float = 8.0):
        u = urllib.parse.urlparse(url if "://" in url else "http://" + url)
        self.url = "%s://%s" % (u.scheme, u.netloc)
        self.https = u.scheme == "https"
        self.host = u.hostname
        self.port = u.port or (443 if self.https else 8123)
        self.token = token
        self.timeout = timeout
        self._local = threading.local()

    def _conn(self):
        c = getattr(self._local, "conn", None)
        if c is None:
            cls = http.client.HTTPSConnection if self.https else http.client.HTTPConnection
            c = cls(self.host, self.port, timeout=self.timeout)
            self._local.conn = c
        return c

    def _drop(self):
        c = getattr(self._local, "conn", None)
        if c is not None:
            try:
                c.close()
            except Exception:
                pass
        self._local.conn = None

    def request(self, method: str, path: str, body=None):
        data = None if body is None else json.dumps(body).encode()
        headers = {"Authorization": "Bearer " + self.token, "Content-Type": "application/json"}
        for attempt in (0, 1):                  # once more on a stale keep-alive connection
            try:
                c = self._conn()
                c.request(method, "/api" + path, body=data, headers=headers)
                r = c.getresponse()
                raw = r.read()
            except (OSError, http.client.HTTPException) as exc:
                self._drop()
                if attempt == 0:
                    continue
                raise HAError("Home Assistant %s unreachable: %s" % (self.url, exc))
            if r.status >= 400:
                text = raw.decode("utf-8", "replace").strip()[:200]
                if r.status == 401:
                    text = "token refused (401): check /etc/haunt/ha.token"
                raise HAError("Home Assistant %s %s: %s %s" % (method, path, r.status, text), r.status)
            try:
                return json.loads(raw) if raw else None
            except ValueError:
                return raw.decode("utf-8", "replace")
        return None

    def states(self) -> Dict[str, dict]:
        return {s["entity_id"]: s for s in self.request("GET", "/states") or []}

    def turn_on(self, entities: List[str], rgb, brightness: int, transition: Optional[float] = None):
        body = {"entity_id": entities, "rgb_color": list(rgb), "brightness": int(brightness)}
        if transition is not None:
            body["transition"] = round(float(transition), 2)
        return self.request("POST", "/services/light/turn_on", body)

    def turn_off(self, entities: List[str], transition: Optional[float] = None):
        body = {"entity_id": entities}
        if transition is not None:
            body["transition"] = round(float(transition), 2)
        return self.request("POST", "/services/light/turn_off", body)

    def close(self):
        self._drop()


# --------------------------------------------------------------------------
# The agent: MQTT in, Home Assistant out
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


class _InlineExecutor:
    """Runs calls at once, in the caller's thread (tests, bench)."""

    def submit(self, fn, *a):
        class Done:
            def __init__(self):
                try:
                    self.value, self.exc = fn(*a), None
                except Exception as exc:          # noqa: BLE001 - reported by the agent
                    self.value, self.exc = None, exc

            def done(self):
                return True

            def result(self):
                if self.exc:
                    raise self.exc
                return self.value
        return Done()

    def shutdown(self, wait=True):
        pass


class FloodAgent:
    def __init__(self, rows_cfg: Dict[str, dict], ha, bus, prefix: str = "haunt",
                 clock: Callable[[], float] = time.monotonic, rng=None,
                 rate: float = 10.0, workers: int = 4, fps: float = 5.0, idle="off",
                 executor=None, resolve_every: float = 30.0, max_bri: int = 255):
        self.cfg = rows_cfg              # show light name -> {"entities": [...], "topic": ...}
        self.ha = ha
        self.bus = bus
        self.prefix = prefix
        self.clock = clock
        self.rng = rng or random.Random()
        self.rows = {n: Row(len(c["entities"]), self.rng) for n, c in rows_cfg.items()}
        self.wanted: Dict[str, Optional[dict]] = {n: None for n in rows_cfg}
        self.applied: Dict[str, Optional[dict]] = {n: None for n in rows_cfg}
        self.idle = idle                 # "off", "leave", or a parsed setting
        self.director_online: Optional[bool] = None
        self.phase: Optional[str] = None
        self.bucket = Bucket(rate, max(rate, 1.0), clock)
        self.workers = max(1, int(workers))
        self.frame_every = 1.0 / max(0.5, float(fps))
        self.next_frame = 0.0
        self.executor = executor or ThreadPoolExecutor(max_workers=self.workers,
                                                       thread_name_prefix="floods")
        # per entity
        self.entity_row: Dict[str, str] = {}
        for n, c in rows_cfg.items():
            for e in c["entities"]:
                self.entity_row[e] = n
        self.desired: Dict[str, object] = {}
        self.sent: Dict[str, object] = {}
        self.since: Dict[str, float] = {}
        self.fade: Dict[str, Optional[float]] = {}   # transition for the next send (scene start)
        self.busy: Dict[str, object] = {}            # entity -> future
        self.calls: List[tuple] = []                 # (future, entities, state)
        self.can_fade: Dict[str, bool] = {}
        self.skip: set = set()                       # not in HA, or unavailable: not sent to
        self.solo_until: Dict[str, float] = {}       # after a failed group call: one at a time
        self.retry_at: Dict[str, float] = {}         # a light that failed on its own: wait
        self.fails: Dict[str, int] = {}
        self.max_bri = max(1, min(255, int(max_bri)))
        self.hold_until = 0.0
        self.resolve_every = resolve_every
        self.next_resolve = 0.0
        self.status: Dict[str, str] = {}
        self.errors = 0
        self.last_error_log = -1e9
        self.n_calls = 0
        # retained director messages normally arrive at once; wait a moment
        # before deciding the show is not running (no blink on a restart)
        self.start_wait_until = clock() + 2.0
        self.by_topic = {c["topic"] + "/set": n for n, c in rows_cfg.items()}
        for t in self.by_topic:
            bus.subscribe(t)
        bus.subscribe("%s/director/online" % prefix)
        bus.subscribe("%s/director/state" % prefix)

    # -- inputs ----------------------------------------------------------

    def handle(self, topic: str, payload: str) -> None:
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

    def show_running(self) -> bool:
        return self.director_online is True and self.phase not in (None, "stopped")

    def target(self, name: str):
        """The setting a row should show now, or "leave"."""
        if not self.show_running():
            return self.idle if self.idle != "off" else {"on": False, "color": None}
        w = self.wanted.get(name)
        return w if w is not None else {"on": False, "color": None}

    # -- Home Assistant --------------------------------------------------

    def resolve(self) -> None:
        """Read Home Assistant: which lights exist and are available (the
        others are skipped, and picked up again when they come back)."""
        states = self.ha.states()
        skip = set()
        for name, c in self.cfg.items():
            ents = c["entities"]
            missing = [e for e in ents if e not in states]
            gone = [e for e in ents if e in states and states[e].get("state") == "unavailable"]
            skip.update(missing + gone)
            for e in ents:
                feats = int((states.get(e) or {}).get("attributes", {}).get("supported_features") or 0)
                self.can_fade[e] = bool(feats & TRANSITION_FEATURE)
            if len(missing) + len(gone) == len(ents):
                text = "error: none of the %d lights is in Home Assistant" % len(ents)
            else:
                text = "ok: %d of %d lights" % (len(ents) - len(missing) - len(gone), len(ents))
                if missing:
                    text += "; not in HA: %s" % ", ".join(str(ents.index(e) + 1) for e in missing)
                if gone:
                    text += "; unavailable: %s" % ", ".join(str(ents.index(e) + 1) for e in gone)
            self._status(name, text)
        for e in skip - self.skip:
            self.since.pop(e, None)
        for e in self.skip - skip:                   # back: send it what it should show
            self.sent.pop(e, None)
            if self.desired.get(e, "unset") != "unset":
                self.since[e] = self.clock()
        self.skip = skip

    def _status(self, name: str, text: str) -> None:
        if self.status.get(name) == text:
            return
        self.status[name] = text
        (log.error if text.startswith("error") else log.info)("%s: %s", name, text)
        if getattr(self.bus, "connected", False):
            self.bus.publish("%s/floods/%s/status" % (self.prefix, name), text, retain=True)

    def _want(self, entity: str, state, now: float, fade: Optional[float] = None) -> None:
        if self.desired.get(entity, "unset") == state:
            return
        self.desired[entity] = state
        if entity in self.skip:
            return
        if self.sent.get(entity, "unset") != state:
            self.since.setdefault(entity, now)
            if fade is not None:
                self.fade[entity] = fade
        else:
            self.since.pop(entity, None)

    def _collect(self, now: float) -> None:
        keep = []
        for fut, ents, state in self.calls:
            if not fut.done():
                keep.append((fut, ents, state))
                continue
            for e in ents:
                self.busy.pop(e, None)
            try:
                fut.result()
            except Exception as exc:              # noqa: BLE001 - HAError, or anything from the pool
                err = exc if isinstance(exc, HAError) else HAError(str(exc))
                for e in ents:
                    self.sent[e] = "unknown"
                    self.since[e] = now               # to the back of the queue
                    if len(ents) > 1:
                        # one bad light can fail a shared call: retry them one by one for a while
                        self.solo_until[e] = now + 30.0
                if len(ents) == 1 and err.status >= 500:
                    # HA answered; this one light is the trouble: back off just this light
                    e = ents[0]
                    self.fails[e] = self.fails.get(e, 0) + 1
                    self.retry_at[e] = now + min(30.0, 2.0 ** self.fails[e])
                    if self.fails[e] in (1, 5) or self.fails[e] % 20 == 0:
                        log.error("%s (failed %d times)", err, self.fails[e])
                else:
                    self._fail(err, now)
                continue
            self.errors = 0
            for e in ents:
                self.fails.pop(e, None)
                self.retry_at.pop(e, None)
                self.sent[e] = state
                if self.desired.get(e, "unset") == state:
                    self.since.pop(e, None)
                else:
                    self.since.setdefault(e, now)
        self.calls = keep

    def _fail(self, exc: HAError, now: float) -> None:
        self.errors += 1
        if now - self.last_error_log > 10.0:
            self.last_error_log = now
            log.error("%s", exc)
        self.hold_until = now + min(10.0, 0.5 * self.errors)

    def dispatch(self) -> None:
        now = self.clock()
        self._collect(now)
        if now < self.hold_until:
            return
        for e in [e for e in self.since if self.sent.get(e, "unset") == self.desired.get(e, "unset")]:
            self.since.pop(e, None)
        while len(self.calls) < self.workers:
            pending = sorted((t, e) for e, t in self.since.items()
                             if e not in self.busy and e not in self.skip
                             and self.retry_at.get(e, 0.0) <= now
                             and self.desired.get(e, "unset") != "unset"
                             and self.sent.get(e, "unset") != self.desired[e])
            if not pending:
                return
            if not self.bucket.take():
                return
            first = pending[0][1]
            state = self.desired[first]
            fade = self.fade.get(first)
            if self.solo_until.get(first, 0.0) > now:
                group = [first]
            else:
                group = [e for _t, e in pending if self.desired[e] == state and self.fade.get(e) == fade
                         and self.solo_until.get(e, 0.0) <= now]
            for e in group:
                self.fade.pop(e, None)
            if fade is not None and not all(self.can_fade.get(e) for e in group):
                fade = None
            if state is OFF:
                fut = self.executor.submit(self.ha.turn_off, group, fade)
            else:
                rgb, b = state
                fut = self.executor.submit(self.ha.turn_on, group, rgb, b, fade)
            self.n_calls += 1
            for e in group:
                self.busy[e] = fut
            self.calls.append((fut, group, state))
            self._collect(now)

    # -- the loop --------------------------------------------------------

    def tick(self) -> None:
        now = self.clock()
        if now >= self.next_resolve:
            self.next_resolve = now + self.resolve_every
            try:
                self.resolve()
            except HAError as exc:
                log.error("cannot read Home Assistant: %s", exc)
                self.next_resolve = now + 10.0
        if self.director_online is None and now < self.start_wait_until:
            return
        if now >= self.next_frame:
            self.next_frame = now + self.frame_every
            for name, row in self.rows.items():
                ents = self.cfg[name]["entities"]
                t = self.target(name)
                if t == "leave":
                    if self.applied[name] != "leave":
                        self.applied[name] = "leave"
                        for e in ents:
                            self.desired.pop(e, None)
                            self.since.pop(e, None)
                            self.sent.pop(e, None)
                    continue
                fade = None
                if t != self.applied[name]:
                    self.applied[name] = t
                    log.info("%s: %s", name, json.dumps(t))
                    row.start(t, now)
                    fade = float(t.get("transition", 0.5)) if t.get("on", True) else 0.5
                scale = self.max_bri / 255.0
                for e, (color, bri) in zip(ents, row.frame(now)):
                    self._want(e, light_state(color, bri * scale), now, fade)
        self.dispatch()

    def all_off(self, wait: float = 3.0) -> None:
        """On the way out: idle setting (normally off), sent directly."""
        self.director_online = False
        if self.idle == "leave":
            return
        self.hold_until = 0.0
        self.next_frame = 0.0
        end = time.monotonic() + wait
        self.tick()
        while (self.since or self.calls) and time.monotonic() < end:
            self.dispatch()
            time.sleep(0.05)


# --------------------------------------------------------------------------
# Config and entry points
# --------------------------------------------------------------------------

FLOODS_DEFAULTS = {
    "home_assistant": "http://homeassistant.local:8123",
    "token": None,                       # normally in token_file instead
    "token_file": "/etc/haunt/ha.token",
    "rate": 10.0,                        # calls a second to Home Assistant
    "workers": 4,                        # calls in flight at once
    "fps": 5.0,                          # animation frames a second
    "idle": "off",                       # when the show is not running: off | leave | a setting
    "max_bri": 255,                      # cap on every light's brightness (0-255), e.g. to spare batteries
    "rows": {},
}


def load_config(path: Optional[str], broker: Optional[str] = None, need_mqtt: bool = True) -> dict:
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
    unknown = set(data) - set(FLOODS_DEFAULTS) - {"mqtt"}
    if unknown:
        raise ConfigError(["floods config: unknown setting %r" % k for k in sorted(unknown)])
    cfg = dict(FLOODS_DEFAULTS)
    cfg.update({k: v for k, v in data.items() if k != "mqtt"})
    mqtt = dict(data.get("mqtt") or {})
    if broker:
        mqtt["host"] = broker
    cfg["mqtt"] = resolve_mqtt(mqtt) if need_mqtt else mqtt
    prefix = cfg["mqtt"].get("prefix", "haunt")
    rows = {}
    for name, row in (cfg["rows"] or {}).items():
        r = dict(row) if isinstance(row, dict) else {"entities": row}
        unknown = set(r) - {"entities", "topic"}
        if unknown:
            raise ConfigError(["floods config: rows.%s: unknown setting %r (entities)" % (name, k)
                               for k in sorted(unknown)])
        ents = r.get("entities")
        if not isinstance(ents, list) or not ents or not all(isinstance(e, str) and e.startswith("light.")
                                                             for e in ents):
            raise ConfigError("floods config: rows.%s: entities must be a list of light.* entity ids, "
                              "first = the Window end of the row" % name)
        if len(set(ents)) != len(ents):
            raise ConfigError("floods config: rows.%s: an entity is listed twice" % name)
        r["entities"] = list(ents)
        r.setdefault("topic", "%s/floods/%s" % (prefix, name))
        rows[str(name)] = r
    cfg["rows"] = rows
    idle = cfg["idle"]
    if idle is False or idle is None or (isinstance(idle, str) and idle.strip().lower() == "off"):
        cfg["idle"] = "off"
    elif isinstance(idle, str) and idle.strip().lower() == "leave":
        cfg["idle"] = "leave"
    else:
        try:
            cfg["idle"] = parse_setting(idle)
        except ValueError as exc:
            raise ConfigError("floods config: idle: %s" % exc)
    mb = cfg["max_bri"]
    if isinstance(mb, bool) or not isinstance(mb, (int, float)) or not 1 <= mb <= 255:
        raise ConfigError("floods config: max_bri must be 1-255")
    cfg["max_bri"] = int(mb)
    for key in ("rate", "fps"):
        cfg[key] = float(cfg[key])
    cfg["workers"] = int(cfg["workers"])
    return cfg


def read_token(cfg: dict) -> str:
    from .config import ConfigError
    token = os.environ.get("HAUNT_HA_TOKEN") or cfg.get("token")
    if not token and cfg.get("token_file"):
        try:
            with open(os.path.expanduser(cfg["token_file"])) as fh:
                token = fh.read().strip()
        except OSError:
            pass
    if not token:
        raise ConfigError("no Home Assistant token: make a long-lived access token (HA profile > "
                          "Security) and put it in %s" % cfg.get("token_file"))
    return token


def connect(cfg: dict) -> HomeAssistant:
    return HomeAssistant(cfg["home_assistant"], read_token(cfg))


class DryRun:
    """Reads Home Assistant for real, but only logs the light commands."""

    def __init__(self, ha: HomeAssistant, label: Optional[Dict[str, str]] = None):
        self.ha = ha
        self.url = ha.url
        self.label = label or {}
        self.n = 0

    def states(self):
        return self.ha.states()

    def _names(self, entities):
        return " ".join(self.label.get(e, e) for e in entities)

    def turn_on(self, entities, rgb, brightness, transition=None):
        self.n += 1
        log.info("DRY on  %-24s %s bri %d", self._names(entities), _hex(rgb), brightness)

    def turn_off(self, entities, transition=None):
        self.n += 1
        log.info("DRY off %s", self._names(entities))

    def close(self):
        self.ha.close()


def _labels(cfg: dict) -> Dict[str, str]:
    return {e: "%s#%d" % (n if len(cfg["rows"]) > 1 else "", i + 1)
            for n, c in cfg["rows"].items() for i, e in enumerate(c["entities"])}


def main(cfg: dict, dry_run: bool = False) -> None:
    from .bus import MqttBus
    from .config import ConfigError
    if not cfg["rows"]:
        raise ConfigError("floods config: no rows (run with --list to find the entity ids)")
    prefix = cfg["mqtt"].get("prefix", "haunt")
    online = "%s/floods/online" % prefix
    ha = connect(cfg)
    if dry_run:
        ha = DryRun(ha, _labels(cfg))
        log.info("DRY RUN: reading Home Assistant and MQTT, sending nothing to the lights")
        # no birth/will and no status messages, so the real agent's are left alone
        bus = MqttBus(cfg["mqtt"], "floods-dry")
    else:
        bus = MqttBus(cfg["mqtt"], "floods", will=(online, "0"), birth=(online, "1"))
    agent = FloodAgent(cfg["rows"], ha, bus, prefix=prefix, rate=cfg["rate"],
                       workers=cfg["workers"], fps=cfg["fps"], idle=cfg["idle"],
                       max_bri=cfg["max_bri"])
    if dry_run:
        agent._status = lambda name, text: log.info("%s: %s", name, text)
    log.info("Home Assistant %s; rows: %s", ha.url,
             ", ".join("%s = %d lights" % (n, len(c["entities"])) for n, c in cfg["rows"].items()))
    try:
        while True:
            for topic, payload in bus.poll(timeout=0.02):
                agent.handle(topic, payload)
            agent.tick()
    finally:
        agent.all_off()
        agent.executor.shutdown(wait=False)
        bus.close()


def cmd_list(cfg: dict, match: str = "") -> None:
    ha = connect(cfg)
    states = ha.states()
    used = {e: (n, i + 1) for n, c in cfg["rows"].items() for i, e in enumerate(c["entities"])}
    lights = sorted((e, s) for e, s in states.items() if e.startswith("light."))
    print("Home Assistant %s: %d lights" % (ha.url, len(lights)))
    for e, s in lights:
        name = (s.get("attributes") or {}).get("friendly_name", "")
        if match and match.lower() not in (e + " " + name).lower():
            continue
        tag = ("   <- %s #%d" % used[e]) if e in used else ""
        modes = ",".join((s.get("attributes") or {}).get("supported_color_modes") or [])
        print("  %-40s %-28s %-12s %s%s" % (e, name[:28], s.get("state"), modes, tag))
    for e in used:
        if e not in states:
            print("!! %s (%s #%d) is not in Home Assistant" % ((e,) + used[e]))


def cmd_walk(cfg: dict, row: Optional[str] = None, hold: float = 1.5) -> None:
    """Light one light at a time, 1 to n, so the order on the house can be checked."""
    name = row or next(iter(cfg["rows"]), None)
    if name not in cfg["rows"]:
        raise SystemExit("unknown row %r (have: %s)" % (name, ", ".join(cfg["rows"]) or "none"))
    ha = connect(cfg)
    ents = cfg["rows"][name]["entities"]
    ha.turn_off(ents)
    try:
        for i, e in enumerate(ents):
            print("%2d  %s" % (i + 1, e), flush=True)
            ha.turn_on([e], (255, 40, 0), 255)
            time.sleep(hold)
            ha.turn_off([e])
    finally:
        ha.turn_off(ents)


class _NullBus:
    connected = False

    def subscribe(self, p):
        pass

    def publish(self, *a, **k):
        pass


def bench_test(cfg: dict, row: str, setting, seconds: float) -> None:
    """Run one setting on one row with no MQTT, then switch it off."""
    if row not in cfg["rows"]:
        raise SystemExit("unknown row %r (have: %s)" % (row, ", ".join(cfg["rows"]) or "none"))
    if isinstance(setting, str):
        try:
            setting = json.loads(setting)
        except ValueError:
            pass
    s = parse_setting(setting)
    ha = connect(cfg)
    agent = FloodAgent({row: cfg["rows"][row]}, ha, _NullBus(), rate=cfg["rate"],
                       workers=cfg["workers"], fps=cfg["fps"], max_bri=cfg["max_bri"])
    agent.director_online, agent.phase = True, "running"
    agent.wanted[row] = s
    print("%s: %s for %gs" % (row, json.dumps(s), seconds))
    end = time.monotonic() + seconds
    try:
        while time.monotonic() < end:
            agent.tick()
            time.sleep(0.02)
    finally:
        agent.idle = "off"
        agent.all_off()
        agent.executor.shutdown(wait=True)
    print("off (%d calls to Home Assistant, %.1f a second)" % (agent.n_calls, agent.n_calls / max(seconds, 0.1)))
