"""DMX output: lets the show drive DMX fixtures (the fog machine) through a
USB-to-DMX dongle (FTDI FT232R, the "Open DMX USB" kind).

It listens on the same topics as any other switched output:

    <prefix>/output/<name>/set     "ON" / "OFF" (retained, from the director)
    <prefix>/director/online       "0" = director gone: everything off

and turns ON into a DMX level on a channel. DMX has to be sent continuously
(about 30 frames a second); a fixture that stops receiving frames usually
holds its last value, so this program always keeps sending, and sends zeros
whenever it is unsure:

  * OFF, or the director's last will ("0")
  * the MQTT connection drops (until the broker is back and says otherwise)
  * an output stays on longer than its own ``max_on`` (default 15 s); it then
    stays off until the director sends OFF and ON again
  * the program stops (a few blackout frames are sent on the way out)

Config: /etc/haunt/dmx.yaml (see deploy/dmx.example.yaml).
Bench test without MQTT:  python3 -m haunt dmx --test 3
"""

from __future__ import annotations

import glob
import logging
import socket
import threading
import time
from typing import Callable, Dict, Optional

log = logging.getLogger("haunt.dmx")

DEFAULT_MAX_ON = 15.0


# --------------------------------------------------------------------------
# The wire
# --------------------------------------------------------------------------

def find_device() -> str:
    """The first FTDI serial adapter, by its stable /dev/serial/by-id name."""
    for pattern in ("/dev/serial/by-id/*FTDI*", "/dev/serial/by-id/*FT232*",
                    "/dev/serial/by-id/*", "/dev/ttyUSB*"):
        found = sorted(glob.glob(pattern))
        if found:
            return found[0]
    raise OSError("no USB-to-DMX adapter found (nothing in /dev/serial/by-id or /dev/ttyUSB*)")


class SerialPort:
    """DMX512 on an FTDI USB-RS485 adapter: 250 kbaud, 8N2, then per frame a
    break (>= 88 us), mark-after-break (>= 8 us), start code 0 and the slots."""

    def __init__(self, device: str):
        import serial
        self.device = find_device() if device in (None, "", "auto") else device
        self.ser = serial.Serial(self.device, baudrate=250000, bytesize=8,
                                 parity="N", stopbits=2, timeout=0, write_timeout=1)
        log.info("opened %s", self.device)

    def send(self, frame: bytes) -> None:
        self.ser.break_condition = True
        time.sleep(0.0002)            # sleep is coarse; a longer break is fine
        self.ser.break_condition = False
        time.sleep(0.00002)
        self.ser.write(frame)
        self.ser.flush()              # wait until it is on the wire

    def close(self) -> None:
        try:
            self.ser.close()
        except Exception:
            pass


class FakePort:
    """Stand-in for tests and dry runs: remembers what it was sent."""

    def __init__(self, device: str = "fake"):
        self.device = device
        self.frames = []
        self.closed = False

    def send(self, frame: bytes) -> None:
        self.frames.append(bytes(frame))
        if len(self.frames) > 1000:
            del self.frames[:500]

    def close(self) -> None:
        self.closed = True


# --------------------------------------------------------------------------
# What to send
# --------------------------------------------------------------------------

def parse_outputs(raw: dict, prefix: str) -> Dict[str, dict]:
    out = {}
    problems = []
    for name, d in (raw or {}).items():
        d = dict(d or {})
        ch = d.get("channel")
        if not isinstance(ch, int) or not 1 <= ch <= 512:
            problems.append("dmx output %s: channel must be 1..512" % name)
            continue
        level = d.get("level", 255)
        if not isinstance(level, int) or not 0 <= level <= 255:
            problems.append("dmx output %s: level must be 0..255" % name)
            continue
        extra = d.get("extra") or {}          # other channels to hold while on
        for k, v in extra.items():
            if not (isinstance(k, int) and 1 <= k <= 512 and isinstance(v, int) and 0 <= v <= 255):
                problems.append("dmx output %s: extra must map channel 1..512 to 0..255" % name)
        out[name] = {
            "channel": ch,
            "level": level,
            "extra": dict(extra),
            "max_on": float(d.get("max_on", DEFAULT_MAX_ON) or 0),
            "topic": d.get("topic") or "%s/output/%s" % (prefix, name),
        }
    if problems:
        from .config import ConfigError
        raise ConfigError(problems)
    return out


class DmxAgent:
    """MQTT side. All logic runs on one thread (handle/tick); the sender
    thread only reads ``self.frame``, which is replaced, never mutated."""

    def __init__(self, outputs: Dict[str, dict], bus, prefix: str = "haunt",
                 slots: int = 512, clock: Callable[[], float] = time.monotonic):
        self.outputs = outputs
        self.bus = bus
        self.prefix = prefix
        used = [o["channel"] for o in outputs.values()] + [c for o in outputs.values() for c in o["extra"]]
        self.slots = max([24, min(512, int(slots))] + used)
        self.clock = clock
        self.wanted: Dict[str, bool] = {n: False for n in outputs}   # what MQTT says
        self.on_since: Dict[str, Optional[float]] = {n: None for n in outputs}
        self.tripped = set()            # cut by max_on; needs OFF before it can fire again
        self.director_online: Optional[bool] = None
        self.was_connected = False
        self.reported: Dict[str, Optional[bool]] = {n: None for n in outputs}
        self.by_topic = {o["topic"] + "/set": n for n, o in outputs.items()}
        self.frame = self._build({})
        for t in self.by_topic:
            bus.subscribe(t)
        bus.subscribe("%s/director/online" % prefix)

    # -- inputs ----------------------------------------------------------

    def handle(self, topic: str, payload: str) -> None:
        if topic == "%s/director/online" % self.prefix:
            self.director_online = payload.strip() != "0"
            if not self.director_online:
                log.info("director offline: everything off")
            return
        name = self.by_topic.get(topic)
        if name is None:
            return
        on = payload.strip().upper() in ("ON", "1", "TRUE")
        if not on:
            self.tripped.discard(name)
        self.wanted[name] = on

    def all_off(self) -> None:
        for n in self.outputs:
            self.wanted[n] = False
        self.tick()

    # -- the decision ----------------------------------------------------

    def active(self, name: str) -> bool:
        return (self.wanted[name] and name not in self.tripped
                and self.director_online is not False and bool(self.bus.connected))

    def tick(self) -> None:
        now = self.clock()
        connected = bool(self.bus.connected)
        if self.was_connected and not connected:
            log.warning("lost the broker: everything off until it is back")
            for n in self.outputs:
                self.wanted[n] = False      # retained messages restore it on reconnect
        self.was_connected = connected

        levels = {}
        for name, o in self.outputs.items():
            on = self.active(name)
            if on:
                since = self.on_since[name]
                if since is None:
                    self.on_since[name] = since = now
                if o["max_on"] and now - since >= o["max_on"]:
                    log.warning("%s on for %gs: switched off (max_on)", name, o["max_on"])
                    self.tripped.add(name)
                    on = False
            if not on:
                self.on_since[name] = None
            if on:
                levels[o["channel"]] = o["level"]
                levels.update(o["extra"])
            self._report(name, on)
        self.frame = self._build(levels)

    def _build(self, levels: Dict[int, int]) -> bytes:
        frame = bytearray(1 + self.slots)          # start code 0, then the slots
        for ch, v in levels.items():
            frame[ch] = max(frame[ch], v)
        return bytes(frame)

    def _report(self, name: str, on: bool) -> None:
        if self.reported[name] == on:
            return
        self.reported[name] = on
        log.info("%s %s", name, "ON" if on else "off")
        if self.bus.connected:
            self.bus.publish(self.outputs[name]["topic"] + "/dmx", "ON" if on else "OFF", retain=True)


class Sender(threading.Thread):
    """Keeps frames going out; reopens the adapter if it is unplugged."""

    def __init__(self, get_frame: Callable[[], bytes], open_port: Callable[[], object],
                 fps: float = 30.0):
        super().__init__(daemon=True, name="dmx-sender")
        self.get_frame = get_frame
        self.open_port = open_port
        self.period = 1.0 / max(1.0, fps)
        self.stop = threading.Event()
        self.port = None
        self.frames_sent = 0

    def run(self) -> None:
        complained = False
        while not self.stop.is_set():
            if self.port is None:
                try:
                    self.port = self.open_port()
                    complained = False
                except Exception as exc:
                    if not complained:
                        log.error("DMX adapter: %s (retrying every 5 s)", exc)
                        complained = True
                    self.stop.wait(5)
                    continue
            t0 = time.monotonic()
            try:
                self.port.send(self.get_frame())
                self.frames_sent += 1
            except Exception as exc:
                log.error("DMX adapter: %s; reopening", exc)
                self._close()
                continue
            self.stop.wait(max(0.0, self.period - (time.monotonic() - t0)))

    def blackout_and_close(self, frame: bytes) -> None:
        self.stop.set()
        self.join(timeout=2)
        if self.port is not None:
            for _ in range(5):
                try:
                    self.port.send(frame)
                except Exception:
                    break
                time.sleep(self.period)
        self._close()

    def _close(self) -> None:
        if self.port is not None:
            self.port.close()
            self.port = None


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

DMX_DEFAULTS = {
    "device": "auto",        # or /dev/serial/by-id/usb-FTDI_..., or "fake"
    "fps": 30,
    "slots": 512,            # channels per frame; some fixtures want all 512
    "outputs": {"fog_machine": {"channel": 1, "level": 255, "max_on": DEFAULT_MAX_ON}},
}


def load_config(path: Optional[str], device: Optional[str] = None,
                broker: Optional[str] = None) -> dict:
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
    unknown = set(data) - set(DMX_DEFAULTS) - {"mqtt"}
    if unknown:
        raise ConfigError(["dmx config: unknown setting %r" % k for k in sorted(unknown)])
    cfg = dict(DMX_DEFAULTS)
    cfg.update({k: v for k, v in data.items() if k != "mqtt"})
    mqtt = dict(data.get("mqtt") or {})
    if broker:
        mqtt["host"] = broker
    cfg["mqtt"] = resolve_mqtt(mqtt)
    if device:
        cfg["device"] = device
    cfg["fps"] = float(cfg["fps"])
    cfg["slots"] = int(cfg["slots"])
    cfg["outputs"] = parse_outputs(cfg["outputs"], cfg["mqtt"].get("prefix", "haunt"))
    if not cfg["outputs"]:
        raise ConfigError("dmx config: no outputs")
    return cfg


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------

def _port_opener(device: str):
    if device == "fake":
        return lambda: FakePort()
    return lambda: SerialPort(device)


def main(cfg: dict) -> None:
    from .bus import MqttBus
    prefix = cfg["mqtt"].get("prefix", "haunt")
    online = "%s/dmx/%s/online" % (prefix, socket.gethostname())
    bus = MqttBus(cfg["mqtt"], "dmx", will=(online, "0"), birth=(online, "1"))
    agent = DmxAgent(cfg["outputs"], bus, prefix=prefix, slots=cfg["slots"])
    sender = Sender(lambda: agent.frame, _port_opener(cfg["device"]), cfg["fps"])
    sender.start()
    log.info("DMX outputs: %s", ", ".join("%s -> ch %d @ %d" % (n, o["channel"], o["level"])
                                          for n, o in agent.outputs.items()))
    try:
        while True:
            for topic, payload in bus.poll(timeout=0.05):
                agent.handle(topic, payload)
            agent.tick()
    finally:
        agent.all_off()
        sender.blackout_and_close(agent.frame)
        bus.close()


def bench_test(cfg: dict, seconds: float, name: Optional[str] = None) -> None:
    """Fire one output for N seconds with no MQTT at all, then zeros."""
    outputs = cfg["outputs"]
    name = name or next(iter(outputs))
    o = outputs[name]
    slots = max(24, cfg["slots"], o["channel"])
    off = bytes(1 + slots)
    on = bytearray(off)
    on[o["channel"]] = o["level"]
    for ch, v in o["extra"].items():
        on[ch] = v
    port = _port_opener(cfg["device"])()
    print("adapter: %s" % getattr(port, "device", "?"))
    print("%s: channel %d = %d for %gs" % (name, o["channel"], o["level"], seconds))
    period = 1.0 / cfg["fps"]
    try:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            port.send(bytes(on))
            time.sleep(period)
    finally:
        for _ in range(int(cfg["fps"])):        # a second of zeros
            port.send(off)
            time.sleep(period)
        port.close()
    print("off")
