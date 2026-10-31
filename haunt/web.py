"""The console for a phone: a small web server (normally on home-pi).

    python3 -m haunt web show.yaml            # http://home-pi.local:8080

It listens to the same retained MQTT messages as the terminal console and
passes taps on to the director as the same commands, so the two can be used
at once. The page (haunt/web.html) gets the show's state pushed to it as
Server-Sent Events, with a plain poll as the fallback.

    GET  /               the page
    GET  /api/state      everything the page shows, as JSON
    GET  /api/events     the same, pushed whenever it changes (text/event-stream)
    POST /api/cmd        {"cmd": "next"} etc., passed on to <prefix>/director/cmd

No password: it is meant for the home network only.
"""

from __future__ import annotations

import json
import logging
import os
import struct
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from .console import Model, light_health, scene_length
from .lights import effect_label
from .topics import Topics

log = logging.getLogger("haunt.web")

# Director commands the page may send, and the fields each may carry.
COMMANDS = {
    "next": (), "prev": (), "restart": (), "toggle": (), "pause": (), "resume": (),
    "stop": (), "start": (), "reload": (), "hue": ("value",),
    "goto": ("index",), "enable": ("index", "value"),
    "master": ("delta", "value"), "level": ("player", "delta", "value"),
    "mute": ("player",), "reset_levels": (), "output": ("name", "value"),
    "mono": ("player", "value"), "floods_level": ("value", "delta"), "floods_on": ("value",),
    "test": ("value",), "test_scene": ("index", "delta"), "test_light": ("name", "pattern"),
}

PUSH_EVERY = 0.25        # at most this often, while things change
KEEPALIVE = 15.0         # comment line on a quiet event stream


class WebApp:
    """The MQTT side: a console Model kept current, and commands out."""

    def __init__(self, bus, topics: Topics, clock=time.monotonic, wallclock=time.time):
        self.bus = bus
        self.topics = topics
        self.clock = clock
        self.wallclock = wallclock
        self.model = Model(topics, clock=clock)
        self.lock = threading.Lock()
        self.changed = threading.Condition(self.lock)
        self.version = 0
        self._stop = threading.Event()

    # -- MQTT in ---------------------------------------------------------

    def pump(self, timeout: float = 0.2) -> int:
        msgs = self.bus.poll(timeout=timeout)
        if msgs:
            with self.lock:
                for topic, payload in msgs:
                    self.model.handle(topic, payload)
                self.version += 1
                self.changed.notify_all()
        return len(msgs)

    def run_pump(self) -> None:
        was = None
        while not self._stop.is_set():
            self.pump(0.2)
            now = getattr(self.bus, "connected", True)
            if now != was:
                was = now
                with self.lock:
                    self.version += 1
                    self.changed.notify_all()

    def stop(self) -> None:
        self._stop.set()
        with self.lock:
            self.changed.notify_all()

    # -- commands out ----------------------------------------------------

    def command(self, body: dict) -> Optional[str]:
        """Pass a command on to the director. Returns an error, or None."""
        if not isinstance(body, dict) or not isinstance(body.get("cmd"), str):
            return "expected {\"cmd\": ...}"
        name = body["cmd"]
        if name not in COMMANDS:
            return "unknown command %r" % name
        cmd = {"cmd": name}
        for k in COMMANDS[name]:
            if k in body:
                v = body[k]
                if k == "player":
                    v = str(v)
                elif k == "name" and isinstance(v, str):
                    pass
                elif k == "value" and isinstance(v, bool):
                    pass
                elif k == "value" and name == "output" and v in ("on", "off", "auto"):
                    pass
                elif k == "pattern" and v in ("scene", "white", "red", "green", "blue", "off"):
                    pass
                elif isinstance(v, bool) or not isinstance(v, (int, float)):
                    return "%s: %s must be a number" % (name, k)
                cmd[k] = v
        if not getattr(self.bus, "connected", True):
            return "not connected to the MQTT broker"
        self.bus.publish(self.topics.director_cmd, cmd)
        return None

    # -- what the page shows ---------------------------------------------

    def snapshot(self) -> dict:
        with self.lock:
            return self._snapshot()

    def _snapshot(self) -> dict:
        m = self.model
        st = m.state or {}
        names = m.playlist.get("players") or {}
        light_types = m.playlist.get("lights") or {}
        scenes = []
        for sc in m.scenes():
            clips = {}
            for pid, c in (sc.get("players") or {}).items():
                clips[pid] = {
                    "file": os.path.basename(c.get("file") or ""),
                    "level": c.get("level"), "overridden": bool(c.get("overridden")),
                    "missing": bool(c.get("missing")), "loop": bool(c.get("loop")),
                    "start_after": c.get("start_after") or 0,
                }
            scenes.append({"index": sc.get("index"), "name": sc.get("name"),
                           "enabled": sc.get("enabled", True), "master": str(sc.get("master")),
                           "len": scene_length(sc), "players": clips})
        players = []
        roles = st.get("players") or {}
        for pid in m.player_ids():
            p = m.players.get(pid) or {"online": False, "state": {}}
            ps = p["state"] or {}
            r = roles.get(pid) or {}
            playing = p["online"] and ps.get("state") == "playing"
            players.append({
                "id": pid, "name": (names.get(pid) or {}).get("name", "P" + pid),
                "online": p["online"], "state": ps.get("state") if p["online"] else "offline",
                "file": os.path.basename(ps.get("file") or "") if p["online"] else "",
                "pos": round(m.pos(pid), 1), "dur": ps.get("dur"), "loop": bool(ps.get("loop")),
                "playing": bool(playing), "error": ps.get("error"),
                "role": r.get("role", ""), "level": r.get("level"),
                "start_after": r.get("start_after") or 0,
                "gain_db": ps.get("gain_db"),
                "mono": ps.get("mono") if p["online"] else None,
                "host": ps.get("host"), "ip": ps.get("ip"),
                # seconds since the player's last report (its own timestamp; it reports
                # several times a second while up)
                "age": max(0, round(self.wallclock() - float(ps["ts"]))) if ps.get("ts") else None,
            })
        lights = []
        for name, info in light_types.items():
            cur = (st.get("lights") or {}).get(name)
            kind = (info or {}).get("type", "")
            item = {"name": name, "type": kind}
            if kind == "hue" and st.get("hue") == "released":
                item["text"], item["on"] = "house", None
            elif cur is None:
                item["text"], item["on"] = "?", None
            elif not cur.get("on", True):
                item["text"], item["on"] = "off", False
            else:
                item["on"] = True
                item["colors"] = [c for c in (cur.get("colors") or [cur.get("color")]) if c][:3]
                item["text"] = effect_label(cur) or cur.get("color") or "on"
            if name in m.light_online:
                item["online"] = m.light_online[name]
            item["health"] = list(light_health(m, name, kind or "wled"))
            lights.append(item)
        out_defs = m.playlist.get("outputs") or {}
        outputs = [{"name": k, "label": o.get("label", k), "on": bool(o.get("on")),
                    "burst": o.get("burst"), "override": o.get("override"), "next": o.get("next"),
                    "max_on": (out_defs.get(k) or {}).get("max_on")}
                   for k, o in (st.get("outputs") or {}).items()]
        has_hue = any((v or {}).get("type") == "hue" for v in light_types.values())
        return {
            "connected": bool(getattr(self.bus, "connected", True)),
            "director": bool(m.director_online),
            "show": st.get("show") or m.playlist.get("name") or "",
            "phase": st.get("phase"), "paused": bool(st.get("paused")),
            "index": st.get("index"), "count": st.get("count"), "scene": st.get("scene"),
            "next": st.get("next"), "pos": st.get("pos"), "dur": st.get("dur"),
            "master": str(st.get("master")) if st.get("master") is not None else None,
            "master_level": st.get("master_level"),
            "hue": st.get("hue") if has_hue else None, "hue_online": m.hue_online,
            "floods_level": st.get("floods_level") if any((v or {}).get("type") == "floods"
                                                           for v in light_types.values()) else None,
            "floods_on": st.get("floods_on", True) is not False,
            "players": players, "scenes": scenes, "lights": lights, "outputs": outputs,
            "test": st.get("test"), "test_pending": bool(st.get("test_pending")),
            "log": (st.get("log") or [])[-12:],
            "version": self.version,
        }


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def _png(size: int = 180) -> bytes:
    """The home-screen icon: an orange jack-o'-lantern-ish disc on black."""
    rows = []
    c, r = size / 2.0, size * 0.40
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            dx, dy = (x - c) / r, (y - c * 1.06) / (r * 0.86)
            inside = dx * dx + dy * dy <= 1.0
            eye = (abs(abs(x - c) - size * 0.15) < size * 0.07 and abs(y - size * 0.45) < size * 0.06)
            mouth = abs(y - size * 0.66) < size * 0.045 and abs(x - c) < size * 0.22
            stem = abs(x - c) < size * 0.05 and size * 0.10 < y < size * 0.22
            if stem:
                row += bytes((70, 140, 40))
            elif inside and not (eye or mouth):
                row += bytes((255, 120, 0))
            elif inside:
                row += bytes((255, 220, 90))
            else:
                row += bytes((12, 10, 16))
        rows.append(bytes(row))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


MANIFEST = {
    "name": "Haunt", "short_name": "Haunt", "start_url": "/", "display": "standalone",
    "background_color": "#0c0a10", "theme_color": "#0c0a10",
    "icons": [{"src": "/icon.png", "sizes": "180x180", "type": "image/png"}],
}


def make_handler(app: WebApp, page: bytes, icon: bytes):
    class Handler(BaseHTTPRequestHandler):
        server_version = "haunt-web"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            log.debug("%s %s", self.address_string(), fmt % args)

        def _send(self, code: int, body: bytes, ctype: str, extra=()):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in extra:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj) -> None:
            self._send(code, json.dumps(obj, separators=(",", ":")).encode(), "application/json")

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                self._send(200, page, "text/html; charset=utf-8")
            elif path == "/api/state":
                self._json(200, app.snapshot())
            elif path == "/api/events":
                self._events()
            elif path in ("/icon.png", "/apple-touch-icon.png", "/apple-touch-icon-precomposed.png"):
                self._send(200, icon, "image/png", [("Cache-Control", "max-age=86400")])
            elif path == "/manifest.json":
                self._send(200, json.dumps(MANIFEST).encode(), "application/manifest+json")
            elif path == "/favicon.ico":
                self._send(200, icon, "image/png")
            else:
                self._send(404, b"not found\n", "text/plain")

        def do_POST(self):
            if self.path.split("?", 1)[0] != "/api/cmd":
                return self._send(404, b"not found\n", "text/plain")
            try:
                n = min(int(self.headers.get("Content-Length") or 0), 4096)
                body = json.loads(self.rfile.read(n).decode() or "{}")
            except (ValueError, UnicodeDecodeError):
                return self._json(400, {"ok": False, "error": "bad JSON"})
            err = app.command(body)
            if err:
                return self._json(400, {"ok": False, "error": err})
            self._json(200, {"ok": True})

        def _events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self.close_connection = True
            seen = -1
            last_write = time.monotonic()
            try:
                while not app._stop.is_set():
                    with app.lock:
                        if app.version == seen:
                            app.changed.wait(timeout=KEEPALIVE)
                        ver = app.version
                    if ver != seen:
                        seen = ver
                        data = json.dumps(app.snapshot(), separators=(",", ":"))
                        self.wfile.write(("data: %s\n\n" % data).encode())
                        self.wfile.flush()
                        last_write = time.monotonic()
                        time.sleep(PUSH_EVERY)
                    elif time.monotonic() - last_write >= KEEPALIVE - 0.5:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                        last_write = time.monotonic()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

    return Handler


def load_page() -> bytes:
    with open(os.path.join(os.path.dirname(__file__), "web.html"), "rb") as fh:
        return fh.read()


def serve(app: WebApp, host: str = "0.0.0.0", port: int = 8080) -> ThreadingHTTPServer:
    """Start the HTTP server and the MQTT pump in background threads."""
    httpd = ThreadingHTTPServer((host, port), make_handler(app, load_page(), _png()))
    httpd.daemon_threads = True
    threading.Thread(target=app.run_pump, daemon=True, name="mqtt-pump").start()
    threading.Thread(target=httpd.serve_forever, daemon=True, name="http").start()
    return httpd


def main(mqtt: dict, host: str = "0.0.0.0", port: int = 8080) -> None:
    from .bus import MqttBus
    topics = Topics(mqtt.get("prefix", "haunt"))
    bus = MqttBus(mqtt, "web")
    bus.subscribe(topics.everything)
    app = WebApp(bus, topics)
    httpd = serve(app, host, port)
    log.info("phone console on http://%s:%d/", host if host != "0.0.0.0" else "<this host>", port)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()
        httpd.shutdown()
        bus.close()
