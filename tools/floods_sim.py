"""Simulate every scene's floods setting against a model of the AiDot hub
(one light command at a time, 0.2 s each) and report the load and lag.

    python3 tools/floods_sim.py [show.yaml] [--seconds 60]
"""
import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from haunt.config import load_show            # noqa: E402
from haunt.floods import FloodAgent           # noqa: E402

N = 14
ENTS = ["light.f%02d" % i for i in range(N)]


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


class Hub:
    """Light commands are acknowledged one after another, `each` seconds apart."""

    def __init__(self, clock, each=0.2):
        self.clock, self.each, self.free = clock, each, 0.0
        self.n = 0

    def states(self):
        return {e: {"state": "off", "attributes": {}} for e in ENTS}

    def turn_on(self, ents, rgb, bri, transition=None):
        self.n += len(ents)

    def turn_off(self, ents, transition=None):
        self.n += len(ents)


class SimExecutor:
    def __init__(self, hub):
        self.hub = hub

    def submit(self, fn, *a):
        hub, clock = self.hub, self.hub.clock
        cost = len(a[0]) if a and isinstance(a[0], list) else 0
        start = max(clock(), hub.free)
        hub.free = start + hub.each * cost
        done_at = hub.free
        value = fn(*a)

        class F:
            def done(self):
                return clock() >= done_at

            def result(self):
                return value
        return F()

    def shutdown(self, wait=True):
        pass


class Bus:
    connected = False

    def subscribe(self, p):
        pass

    def publish(self, *a, **k):
        pass


def run(setting, seconds, rate=5.0, workers=3):
    clock = Clock()
    hub = Hub(clock)
    a = FloodAgent({"floods": {"entities": ENTS, "topic": "t"}}, hub, Bus(), clock=clock,
                   rng=random.Random(1), rate=rate, workers=workers, fps=5, executor=SimExecutor(hub))
    a.handle("haunt/director/online", "1")
    a.handle("haunt/director/state", json.dumps({"phase": "playing"}))
    a.handle("t/set", json.dumps(setting))
    lags = []
    while clock.t < seconds:
        a.tick()
        if clock.t > 4.0:                                   # after the opening sweep
            lags.append(clock.t - min(a.since.values()) if a.since else 0.0)
        clock.t += 0.02
    lags.sort()
    return hub.n / seconds, lags[len(lags) // 2], lags[int(len(lags) * 0.95)], lags[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("show", nargs="?", default="show.yaml")
    ap.add_argument("--seconds", type=float, default=60)
    args = ap.parse_args()
    show = load_show(args.show)
    print("%-24s %8s %8s %8s %8s" % ("scene", "cmds/s", "lag p50", "lag p95", "lag max"))
    for sc in show.scenes:
        st = sc.lights.get("floods")
        if st is None:
            continue
        rate, p50, p95, mx = run(st, args.seconds)
        flag = "  <-- lags" if p95 > 1.0 else ""
        print("%-24s %8.1f %7.2fs %7.2fs %7.2fs%s" % (sc.name[:24], rate, p50, p95, mx, flag))


if __name__ == "__main__":
    main()
