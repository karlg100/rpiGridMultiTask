"""DMX output: what goes on the wire for each MQTT situation."""

import pytest

from haunt.dmx import DmxAgent, FakePort, Sender, parse_outputs, load_config


class Bus:
    def __init__(self):
        self.connected = True
        self.subs = []
        self.sent = []

    def subscribe(self, p):
        self.subs.append(p)

    def publish(self, topic, payload, retain=False):
        self.sent.append((topic, payload))


class Clock:
    t = 100.0

    def __call__(self):
        return self.t


def make(**fog):
    fog.setdefault("channel", 1)
    bus, clock = Bus(), Clock()
    a = DmxAgent(parse_outputs({"fog_machine": fog}, "haunt"), bus, clock=clock)
    return a, bus, clock


SET = "haunt/output/fog_machine/set"
ONLINE = "haunt/director/online"


def test_frame_layout_and_on_off():
    a, bus, _ = make(level=200)
    assert SET in bus.subs and ONLINE in bus.subs
    a.tick()
    assert len(a.frame) == 513 and a.frame[0] == 0 and not any(a.frame)
    a.handle(SET, "ON"); a.tick()
    assert a.frame[1] == 200 and sum(a.frame) == 200
    assert ("haunt/output/fog_machine/dmx", "ON") in bus.sent
    a.handle(SET, "OFF"); a.tick()
    assert not any(a.frame)


def test_director_gone_means_off_and_blocks_retained_on():
    a, _, _ = make()
    a.handle(ONLINE, "0")
    a.handle(SET, "ON"); a.tick()          # retained ON arriving after the will
    assert a.frame[1] == 0
    a.handle(ONLINE, "1"); a.tick()
    assert a.frame[1] == 255


def test_broker_loss_means_off_until_told_again():
    a, bus, _ = make()
    a.handle(SET, "ON"); a.tick()
    bus.connected = False; a.tick()
    assert a.frame[1] == 0
    bus.connected = True; a.tick()
    assert a.frame[1] == 0                  # stays off until the retained message comes back
    a.handle(SET, "ON"); a.tick()
    assert a.frame[1] == 255


def test_local_max_on_trips_and_needs_off_to_rearm():
    a, _, clock = make(max_on=15)
    a.handle(SET, "ON"); a.tick()
    clock.t += 14.9; a.tick()
    assert a.frame[1] == 255
    clock.t += 0.2; a.tick()
    assert a.frame[1] == 0
    a.handle(SET, "ON"); a.tick()           # repeated ON without an OFF: still off
    assert a.frame[1] == 0
    a.handle(SET, "OFF"); a.handle(SET, "ON"); a.tick()
    assert a.frame[1] == 255


def test_extra_channels_and_short_frames():
    a, _, _ = make(channel=3, extra={4: 128})
    a2 = DmxAgent(a.outputs, Bus(), slots=24)
    a2.handle(SET, "ON"); a2.tick()
    assert len(a2.frame) == 25 and a2.frame[3] == 255 and a2.frame[4] == 128


def test_bad_config_reported():
    from haunt.config import ConfigError
    with pytest.raises(ConfigError):
        parse_outputs({"fog_machine": {"channel": 0}}, "haunt")
    with pytest.raises(ConfigError):
        parse_outputs({"fog_machine": {"channel": 1, "level": 300}}, "haunt")


def test_load_config_defaults(tmp_path):
    p = tmp_path / "dmx.yaml"
    p.write_text("mqtt: {host: 192.168.1.244}\noutputs:\n  fog_machine: {channel: 2, level: 180}\n")
    cfg = load_config(str(p), device="fake")
    assert cfg["device"] == "fake" and cfg["mqtt"]["host"] == "192.168.1.244"
    assert cfg["outputs"]["fog_machine"]["channel"] == 2
    assert cfg["outputs"]["fog_machine"]["max_on"] == 15


def test_sender_keeps_sending_and_blacks_out():
    port = FakePort()
    frames = [bytes([0, 255] + [0] * 23)]
    s = Sender(lambda: frames[0], lambda: port, fps=200)
    s.start()
    import time
    time.sleep(0.1)
    s.blackout_and_close(bytes(25))
    assert len(port.frames) > 5 and port.frames[0][1] == 255
    assert port.frames[-1] == bytes(25) and port.closed


def test_sender_reopens_after_unplug():
    import time
    opened = []

    class Flaky(FakePort):
        def send(self, frame):
            if len(opened) == 1:
                raise OSError("unplugged")
            super().send(frame)

    def opener():
        p = Flaky(); opened.append(p); return p

    s = Sender(lambda: bytes(25), opener, fps=200)
    s.stop.wait = lambda t: time.sleep(min(t, 0.01))   # skip the 5 s retry pause
    s.start(); time.sleep(0.1)
    s.blackout_and_close(bytes(25))
    assert len(opened) == 2 and opened[1].frames
