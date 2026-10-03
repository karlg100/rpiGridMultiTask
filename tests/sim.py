"""A whole show in one process on a fake clock: director + fake players on an
in-memory bus. Deterministic, and a simulated hour takes well under a second."""

import json

from haunt.backends import FakeBackend
from haunt.bus import MemoryHub
from haunt.config import PLAYER_DEFAULTS, parse_show, resolve_mqtt
from haunt.director import Director
from haunt.player import PlayerAgent
from haunt.topics import Topics

SHOW = {
    "name": "Test show",
    "players": {1: {"name": "Window"}, 2: {"name": "Wall"}},
    "lights": {
        "front_lights": {"type": "wled", "topic": "front_lights"},
        "graveyard": {"type": "particle", "topic": "graveyard"},
    },
    "defaults": {"gap": 0.5, "fade_in": 1.0, "fade_out": 1.5},
    "scenes": [
        {"name": "A", "master": 1,
         "players": {1: {"file": "a1.mp4"},
                     2: {"file": "a2.mp4", "loop": True, "start_after": 8, "level": 60}},
         "lights": {"front_lights": [0, 0, 190], "graveyard": "#310059"}},
        {"name": "B", "master": 2, "end_at": 12,
         "players": {1: {"file": "b1.mp4", "loop": True, "level": 0},
                     2: {"file": "b2.mp4"}},
         "lights": {"front_lights": "#ffa500", "graveyard": [255, 165, 0]}},
        {"name": "C", "master": 1,
         "players": {1: {"file": "c1.mp4"}},
         "cues": [{"at": 5, "mqtt": {"topic": "ghosts/command", "payload": "startle"},
                   "lights": {"graveyard": "#ff0000"}}]},
    ],
}

DURATIONS = {"a1.mp4": 20, "a2.mp4": 6, "b1.mp4": 7, "b2.mp4": 30, "c1.mp4": 10}


class Sim:
    def __init__(self, show=None, durations=None, state_path=None, online=("1", "2"),
                 autostart=True):
        self.t = 1000.0
        self.hub = MemoryHub()
        self.show = parse_show(show or SHOW)
        self.topics = Topics(self.show.prefix)
        self.durations = dict(DURATIONS, **(durations or {}))
        self.agents = {}
        self.observer = self.hub.client()
        for pid in online:
            self.add_player(pid)
        self.director = Director(
            self.show, self.hub.client(will=(self.topics.director_online, "0"),
                                       birth=(self.topics.director_online, "1")),
            clock=self.clock, wallclock=self.clock, state_path=state_path,
            autostart=autostart)

    def clock(self):
        return self.t

    def add_player(self, pid):
        pid = str(pid)
        cfg = dict(PLAYER_DEFAULTS, id=pid, backend="fake", mqtt=resolve_mqtt({}))
        online = self.topics.player(pid, "online")
        bus = self.hub.client(will=(online, "0"), birth=(online, "1"))
        backend = FakeBackend(clock=self.clock, durations=self.durations)
        self.agents[pid] = PlayerAgent(cfg, bus, backend, clock=self.clock, wallclock=self.clock)
        return self.agents[pid]

    def kill_player(self, pid):
        self.agents.pop(str(pid)).bus.drop()

    def step(self, dt=0.05):
        self.t += dt
        for comp in list(self.agents.values()) + [self.director]:
            for topic, payload in comp.bus.poll():
                comp.handle(topic, payload)
            comp.tick()

    def run(self, seconds, dt=0.05):
        for _ in range(int(round(seconds / dt))):
            self.step(dt)

    def run_until(self, cond, limit=120, dt=0.05):
        for _ in range(int(limit / dt)):
            if cond():
                return True
            self.step(dt)
        raise AssertionError("condition not reached within %ss (phase=%s scene=%s)"
                             % (limit, self.director.phase, self.director.scene.name))

    def cmd(self, name, **kw):
        self.observer.publish(self.topics.director_cmd, dict(kw, cmd=name))
        self.step()

    def sent(self, topic):
        """Every payload ever published on a topic."""
        return [p for t, p in self.hub.history if t == topic]

    def state(self):
        return json.loads(self.hub.retained[self.topics.director_state])

    def playlist(self):
        return json.loads(self.hub.retained[self.topics.director_playlist])

    def pstate(self, pid):
        return json.loads(self.hub.retained[self.topics.player(pid, "state")])
