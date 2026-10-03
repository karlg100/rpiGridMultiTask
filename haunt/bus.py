"""Message bus: a thin wrapper so the show logic never touches paho directly.

``MqttBus`` is the real thing. ``MemoryBus`` is an in-process stand-in with the
same behaviour (wildcards, retained messages) used by the tests and by
``haunt demo``.

Incoming messages land in a queue and are handed out by ``poll()``, so all
show logic runs on one thread and needs no locks.
"""

from __future__ import annotations

import json
import logging
import queue
import socket
import os
from typing import List, Optional, Tuple

log = logging.getLogger("haunt.bus")

Message = Tuple[str, str]


def topic_matches(pattern: str, topic: str) -> bool:
    """MQTT wildcard match (+ = one level, # = the rest)."""
    p = pattern.split("/")
    t = topic.split("/")
    for i, part in enumerate(p):
        if part == "#":
            return True
        if i >= len(t):
            return False
        if part != "+" and part != t[i]:
            return False
    return len(p) == len(t)


def encode(payload) -> str:
    if isinstance(payload, (dict, list)):
        return json.dumps(payload, separators=(",", ":"))
    if isinstance(payload, bytes):
        return payload.decode("utf-8", "replace")
    return str(payload)


class Bus:
    """Interface shared by MqttBus and MemoryBus."""

    connected = False

    def publish(self, topic: str, payload, retain: bool = False) -> None:
        raise NotImplementedError

    def subscribe(self, pattern: str) -> None:
        raise NotImplementedError

    def poll(self, timeout: float = 0.0) -> List[Message]:
        raise NotImplementedError

    def close(self) -> None:
        pass


# --------------------------------------------------------------------------
# In-memory bus
# --------------------------------------------------------------------------

class MemoryHub:
    """The 'broker' for MemoryBus clients."""

    def __init__(self):
        self.retained = {}
        self.clients = []
        self.history = []  # every (topic, payload) ever published, for tests

    def client(self, will: Optional[Tuple[str, str]] = None,
               birth: Optional[Tuple[str, str]] = None) -> "MemoryBus":
        bus = MemoryBus(self, will)
        bus.birth = birth
        self.clients.append(bus)
        if birth:
            bus.publish(birth[0], birth[1], retain=True)
        return bus

    def route(self, topic: str, payload: str, retain: bool) -> None:
        self.history.append((topic, payload))
        if retain:
            if payload == "":
                self.retained.pop(topic, None)
            else:
                self.retained[topic] = payload
        for c in list(self.clients):
            if any(topic_matches(p, topic) for p in c.patterns):
                c.inbox.put((topic, payload))


class MemoryBus(Bus):
    def __init__(self, hub: MemoryHub, will=None):
        self.hub = hub
        self.will = will
        self.patterns = []
        self.inbox = queue.Queue()
        self.connected = True

    def publish(self, topic, payload, retain=False):
        self.hub.route(topic, encode(payload), retain)

    def subscribe(self, pattern):
        self.patterns.append(pattern)
        for topic, payload in list(self.hub.retained.items()):
            if topic_matches(pattern, topic):
                self.inbox.put((topic, payload))

    def poll(self, timeout=0.0):
        out = []
        try:
            if timeout:
                out.append(self.inbox.get(timeout=timeout))
            while True:
                out.append(self.inbox.get_nowait())
        except queue.Empty:
            pass
        return out

    def close(self):
        """Clean disconnect: say goodbye, like MqttBus.close()."""
        was = self._detach()
        if was and getattr(self, "birth", None):
            self.hub.route(self.birth[0], "0", True)

    def _detach(self):
        was = self in self.hub.clients
        if was:
            self.hub.clients.remove(self)
        self.connected = False
        return was

    def drop(self):
        """Simulate a crash / network loss: the broker sends the last will."""
        if self._detach() and self.will:
            self.hub.route(self.will[0], self.will[1], True)


# --------------------------------------------------------------------------
# Real MQTT
# --------------------------------------------------------------------------

class MqttBus(Bus):
    """paho-mqtt client that survives the broker being down.

    * connects in the background and keeps retrying (the old scripts crashed
      at import time if the broker was unreachable)
    * re-subscribes and re-announces itself after every reconnect
    * registers a last-will so everyone else sees us go offline
    * works with paho-mqtt 1.x (Bookworm apt) and 2.x (Trixie apt / pip)
    """

    def __init__(self, mqtt_cfg: dict, role: str,
                 will: Optional[Tuple[str, str]] = None,
                 birth: Optional[Tuple[str, str]] = None):
        import paho.mqtt.client as mqtt

        self.inbox = queue.Queue()
        self.patterns = []
        self.birth = birth
        self.connected = False
        # A unique id: two clients sharing an id kick each other off the broker.
        client_id = "haunt-%s-%s-%d" % (role, socket.gethostname(), os.getpid())
        try:
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                      client_id=client_id)
        except AttributeError:  # paho 1.x
            self.client = mqtt.Client(client_id=client_id)

        user = mqtt_cfg.get("username")
        password = mqtt_cfg.get("password")
        if user:
            self.client.username_pw_set(user, password)
        if will:
            self.client.will_set(will[0], will[1], qos=1, retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=10)
        self.host = mqtt_cfg.get("host", "localhost")
        self.port = int(mqtt_cfg.get("port", 1883))
        self.client.connect_async(self.host, self.port, keepalive=15)
        self.client.loop_start()

    # paho 1.x and 2.x pass different argument lists; we need none of them.
    def _on_connect(self, client, userdata, *args):
        rc = args[1] if len(args) > 1 else 0
        failed = getattr(rc, "is_failure", None)
        if failed is None:
            failed = bool(rc)
        if failed:
            log.error("broker %s refused the connection: %s", self.host, rc)
            return
        log.info("connected to broker %s:%d", self.host, self.port)
        self.connected = True
        for p in self.patterns:
            client.subscribe(p, qos=0)
        if self.birth:
            client.publish(self.birth[0], self.birth[1], qos=1, retain=True)

    def _on_disconnect(self, client, userdata, *args):
        if self.connected:
            log.warning("lost connection to broker %s, retrying", self.host)
        self.connected = False

    def _on_message(self, client, userdata, msg):
        self.inbox.put((msg.topic, msg.payload.decode("utf-8", "replace")))

    def publish(self, topic, payload, retain=False):
        self.client.publish(topic, encode(payload), qos=0, retain=retain)

    def subscribe(self, pattern):
        self.patterns.append(pattern)
        if self.connected:
            self.client.subscribe(pattern, qos=0)

    def poll(self, timeout=0.0):
        out = []
        try:
            if timeout:
                out.append(self.inbox.get(timeout=timeout))
            while True:
                out.append(self.inbox.get_nowait())
        except queue.Empty:
            pass
        return out

    def close(self):
        """Clean shutdown: say goodbye ourselves, since a clean disconnect
        suppresses the last will."""
        try:
            if self.birth and self.connected:
                info = self.client.publish(self.birth[0], "0", qos=1, retain=True)
                info.wait_for_publish(timeout=2)
        except Exception:
            pass
        self.client.loop_stop()
        try:
            self.client.disconnect()
        except Exception:
            pass
        self.connected = False
