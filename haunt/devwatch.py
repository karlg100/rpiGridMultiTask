"""Online/offline for devices that do not announce themselves over MQTT.

The graveyard Photon connects to the small broker on home-pi's
192.168.1.243 (deploy/legacy-mqtt-243/) but never publishes an online
message or a last will. That broker does log every connect and disconnect,
so this follows its log (from the systemd journal) and publishes, retained,

    <prefix>/light/<name>/online    1 / 0

for each watched MQTT client id, which the console and the phone page show.

    python3 -m haunt devwatch show.yaml --client halloweentree=graveyard

The Photon keeps its connection alive every 15 s, so a dead one shows as
offline about 20 s later.
"""

from __future__ import annotations

import logging
import re
import subprocess
from typing import Dict, Iterable, Optional

log = logging.getLogger("haunt.devwatch")

CONNECT = re.compile(r"New client connected from \S+ as (\S+) \(")
GONE = [
    re.compile(r"Client (\S+) (?:closed its connection|disconnected)"),
    re.compile(r"Client (\S+) has exceeded timeout"),
    re.compile(r"Socket error on client (\S+),"),
    re.compile(r"Client (\S+) already connected, closing old connection"),
]
BROKER_DOWN = re.compile(r"mosquitto version \S+ (?:terminating|starting)")


class Watcher:
    """Turns broker log lines into online states for the watched client ids."""

    def __init__(self, clients: Dict[str, str]):
        self.clients = clients                  # MQTT client id (or prefix with *) -> show name
        self.online: Dict[str, bool] = {}

    def _name(self, client_id: str) -> Optional[str]:
        client_id = client_id.rstrip(".,")
        for cid, name in self.clients.items():
            if cid.endswith("*") and client_id.startswith(cid[:-1]) or client_id == cid:
                return name
        return None

    def line(self, text: str) -> Dict[str, bool]:
        """Feed one log line; returns the states that changed."""
        changed = {}
        if BROKER_DOWN.search(text):
            for name in set(self.clients.values()):
                if self.online.get(name) is not False:
                    changed[name] = False
        else:
            m = CONNECT.search(text)
            if m:
                name = self._name(m.group(1))
                if name and self.online.get(name) is not True:
                    changed[name] = True
            else:
                for pat in GONE:
                    m = pat.search(text)
                    if m:
                        name = self._name(m.group(1))
                        if name and self.online.get(name) is not False:
                            changed[name] = False
                        break
        self.online.update(changed)
        return changed


def journal(unit: str = "mosquitto", backlog: int = 500) -> Iterable[str]:
    """The unit's log lines: the last ``backlog`` (to learn the current state), then new ones."""
    proc = subprocess.Popen(["journalctl", "-u", unit, "-f", "-n", str(backlog), "-o", "cat",
                             "--no-pager"], stdout=subprocess.PIPE, text=True, bufsize=1)
    try:
        for text in proc.stdout:
            yield text.rstrip("\n")
    finally:
        proc.terminate()


def parse_clients(specs) -> Dict[str, str]:
    out = {}
    for spec in specs or ["halloweentree=graveyard"]:
        cid, _, name = spec.partition("=")
        if not cid or not name:
            raise ValueError("--client wants CLIENT_ID=light_name, e.g. halloweentree=graveyard")
        out[cid] = name
    return out


def main(mqtt: dict, clients: Dict[str, str], unit: str = "mosquitto") -> None:
    import threading
    import time
    from .bus import MqttBus
    prefix = mqtt.get("prefix", "haunt")
    topics = {name: "%s/light/%s/online" % (prefix, name) for name in set(clients.values())}
    bus = MqttBus(mqtt, "devwatch")
    w = Watcher(clients)
    lock = threading.Lock()

    def publish_all():
        for name, on in w.online.items():
            bus.publish(topics[name], "1" if on else "0", retain=True)

    def keep_publishing():
        # retained, but sent again now and then in case the broker lost it
        was = False
        while True:
            time.sleep(5)
            now = bool(getattr(bus, "connected", False))
            if now and not was or now and int(time.time()) % 300 < 5:
                with lock:
                    publish_all()
            was = now

    threading.Thread(target=keep_publishing, daemon=True).start()
    log.info("watching %s for %s", unit, ", ".join("%s -> %s" % kv for kv in clients.items()))
    try:
        for text in journal(unit):
            with lock:
                changed = w.line(text)
                for name, on in changed.items():
                    log.info("%s is %s", name, "online" if on else "OFFLINE")
                    bus.publish(topics[name], "1" if on else "0", retain=True)
    finally:
        bus.close()
