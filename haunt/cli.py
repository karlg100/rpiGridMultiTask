"""Command line: haunt director | player | dmx | hue | floods | console | demo | check | send"""

from __future__ import annotations

import argparse
import json
import locale
import logging
import os
import sys
import threading
import time

from . import __version__
from .config import ConfigError, load_player_config, load_show, resolve_mqtt
from .topics import Topics

DEFAULT_SHOW = os.environ.get("HAUNT_SHOW", "show.yaml")


def _sigterm_is_ctrl_c() -> None:
    """systemd stops services with SIGTERM; treat it like Ctrl-C so the
    normal shutdown path runs (black out players, quit mpv, say goodbye)."""
    import signal

    def handler(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, handler)


def _logging(verbose: bool) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")


def _mqtt_for_client(args) -> dict:
    """MQTT settings for console/send: from the show file if there is one,
    otherwise from --broker / environment."""
    cfg = {}
    if os.path.exists(args.show):
        cfg = dict(load_show(args.show).mqtt)
    else:
        cfg = resolve_mqtt({})
    if args.broker:
        cfg["host"] = args.broker
    return cfg


def cmd_director(args) -> None:
    from . import director
    _logging(args.verbose)
    _sigterm_is_ctrl_c()
    start = args.start - 1 if args.start else None
    director.main(args.show, start_index=start, autostart=not args.stopped)


def cmd_player(args) -> None:
    from . import player
    _logging(args.verbose)
    _sigterm_is_ctrl_c()
    cfg = load_player_config(args.config, {
        "id": args.id, "backend": args.backend, "media_root": args.media,
        "mqtt_host": args.broker,
    })
    player.main(cfg)


def cmd_dmx(args) -> None:
    from . import dmx
    _logging(args.verbose)
    _sigterm_is_ctrl_c()
    cfg = dmx.load_config(args.config, device=args.device, broker=args.broker)
    if args.test is not None:
        dmx.bench_test(cfg, args.test, args.output)
    else:
        dmx.main(cfg)


def cmd_hue(args) -> None:
    from . import hue
    _logging(args.verbose)
    _sigterm_is_ctrl_c()
    cfg = hue.load_config(args.config, bridge=args.bridge, broker=args.broker,
                          need_mqtt=not (args.pair or args.list or args.discover or args.test))
    if args.discover:
        found = hue.discover()
        print("\n".join(found) if found else "no Hue bridge found")
    elif args.pair:
        hue.cmd_pair(cfg)
    elif args.list:
        hue.cmd_list(cfg)
    elif args.test:
        room, setting = args.test
        hue.bench_test(cfg, room, setting, args.seconds)
    else:
        hue.main(cfg)


def cmd_floods(args) -> None:
    from . import floods
    _logging(args.verbose)
    _sigterm_is_ctrl_c()
    cfg = floods.load_config(args.config, broker=args.broker,
                             need_mqtt=not (args.list is not None or args.walk or args.test))
    if args.list is not None:
        floods.cmd_list(cfg, args.list)
    elif args.walk:
        floods.cmd_walk(cfg, args.row, args.hold)
    elif args.test:
        row, setting = args.test
        floods.bench_test(cfg, row, setting, args.seconds)
    else:
        floods.main(cfg)


def _utf8() -> bool:
    locale.setlocale(locale.LC_ALL, "")
    return "utf" in (locale.getpreferredencoding(False) or "").lower()


def cmd_console(args) -> None:
    from .bus import MqttBus
    from .console import Model, run_curses
    mqtt = _mqtt_for_client(args)
    topics = Topics(mqtt.get("prefix", "haunt"))
    bus = MqttBus(mqtt, "console")
    bus.subscribe(topics.everything)
    run_curses(Model(topics), bus, broker=mqtt["host"], unicode=_utf8() and not args.ascii)


def cmd_demo(args) -> None:
    """The whole system in one process with pretend players: no broker, no
    Pis, no video. For trying the console and rehearsing a show file."""
    from .backends import FakeBackend
    from .bus import MemoryHub
    from .config import PLAYER_DEFAULTS
    from .console import Model, run_curses
    from .director import Director
    from .player import PlayerAgent

    logging.basicConfig(level=logging.CRITICAL)
    show = load_show(args.show)
    topics = Topics(show.prefix)
    hub = MemoryHub()
    stop = threading.Event()

    def loop(component, period):
        while not stop.is_set():
            for topic, payload in component.bus.poll(timeout=period):
                component.handle(topic, payload)
            component.tick()

    for pid in show.players:
        cfg = dict(PLAYER_DEFAULTS, id=pid, backend="fake", mqtt=dict(show.mqtt))
        online = topics.player(pid, "online")
        agent = PlayerAgent(cfg, hub.client(will=(online, "0"), birth=(online, "1")),
                            FakeBackend(default_duration=args.clip_seconds))
        threading.Thread(target=loop, args=(agent, 0.03), daemon=True).start()
    d = Director(show, hub.client(will=(topics.director_online, "0"),
                                  birth=(topics.director_online, "1")))
    d.probe()
    threading.Thread(target=loop, args=(d, 0.05), daemon=True).start()

    bus = hub.client()
    bus.subscribe(topics.everything)
    try:
        run_curses(Model(topics), bus, broker="demo (no broker)", unicode=_utf8() and not args.ascii)
    finally:
        stop.set()


def cmd_check(args) -> None:
    show = load_show(args.show)
    print("%s: OK" % args.show)
    print("  %d scenes, %d players, %d lights" % (len(show.scenes), len(show.players), len(show.lights)))
    for i, s in enumerate(show.scenes, 1):
        parts = []
        for pid, c in s.clips.items():
            tag = "P%s%s %s" % (pid, "*" if pid == s.master else "", os.path.basename(c.file))
            parts.append(tag)
        print("  %2d. %-34s %s" % (i, s.name[:34], " | ".join(parts)))
    if args.media:
        missing = sorted({c.file for s in show.scenes for c in s.clips.values()
                          if not os.path.isfile(c.file if os.path.isabs(c.file)
                                                else os.path.join(args.media, c.file))})
        for f in missing:
            print("  MISSING under %s: %s" % (args.media, f))
        if missing:
            sys.exit(1)
        print("  all files found under %s" % args.media)


def cmd_send(args) -> None:
    """One-shot command to the director, for scripts and cron."""
    from .bus import MqttBus
    mqtt = _mqtt_for_client(args)
    topics = Topics(mqtt.get("prefix", "haunt"))
    payload = {"cmd": args.command}
    for item in args.params:
        k, _, v = item.partition("=")
        try:
            payload[k] = json.loads(v)
        except ValueError:
            payload[k] = v
    bus = MqttBus(mqtt, "send")
    deadline = time.monotonic() + 5
    while not bus.connected and time.monotonic() < deadline:
        time.sleep(0.05)
    if not bus.connected:
        sys.exit("could not reach the MQTT broker at %s" % mqtt["host"])
    info = bus.client.publish(topics.director_cmd, json.dumps(payload), qos=1)
    info.wait_for_publish(timeout=3)
    bus.close()
    print("sent %s" % json.dumps(payload))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="haunt", description=__doc__)
    ap.add_argument("--version", action="version", version="haunt " + __version__)
    sub = ap.add_subparsers(dest="what", required=True)

    def show_arg(p):
        p.add_argument("show", nargs="?", default=DEFAULT_SHOW, help="show file (default: show.yaml)")

    p = sub.add_parser("director", help="run the show (headless; on home-pi)")
    show_arg(p)
    p.add_argument("--start", type=int, metavar="N", help="start at scene N instead of where it left off")
    p.add_argument("--stopped", action="store_true", help="come up stopped; start from the console")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(fn=cmd_director)

    p = sub.add_parser("player", help="run a video player agent (on each player Pi)")
    p.add_argument("-c", "--config", help="player.yaml")
    p.add_argument("--id", help="player id (overrides the config file)")
    p.add_argument("--broker", help="MQTT broker host")
    p.add_argument("--media", help="directory the show's file names are relative to")
    p.add_argument("--backend", choices=("mpv", "fake"))
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(fn=cmd_player)

    p = sub.add_parser("dmx", help="drive DMX fixtures (the fog machine) from the show's outputs")
    p.add_argument("-c", "--config", help="dmx.yaml (default settings: fog_machine on channel 1)")
    p.add_argument("--device", help="serial device, 'auto' (default) or 'fake'")
    p.add_argument("--broker", help="MQTT broker host")
    p.add_argument("--test", type=float, metavar="SECONDS",
                   help="no MQTT: fire one output for SECONDS, then off (bench test)")
    p.add_argument("--output", help="with --test: which output (default: the first)")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(fn=cmd_dmx)

    p = sub.add_parser("hue", help="drive the Philips Hue rooms (living room, front bedroom) from the show")
    p.add_argument("-c", "--config", help="hue.yaml (default: bridge auto, key in /etc/haunt/hue.key)")
    p.add_argument("--bridge", help="bridge IP address (overrides the config)")
    p.add_argument("--broker", help="MQTT broker host")
    p.add_argument("--discover", action="store_true", help="find bridges on the network")
    p.add_argument("--pair", action="store_true", help="get a key: press the bridge button, then run this")
    p.add_argument("--list", action="store_true", help="show the bridge's rooms, zones and bulbs")
    p.add_argument("--test", nargs=2, metavar=("ROOM", "SETTING"),
                   help="no MQTT: run SETTING (e.g. '{\"color\":\"#ff6a00\",\"effect\":\"candle\"}') "
                        "on ROOM, then off")
    p.add_argument("--seconds", type=float, default=15, help="with --test: how long (default 15)")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(fn=cmd_hue)

    p = sub.add_parser("floods", help="drive the AiDot flood lights (through Home Assistant) from the show")
    p.add_argument("-c", "--config", help="floods.yaml (Home Assistant address, token file, the row's entities)")
    p.add_argument("--broker", help="MQTT broker host")
    p.add_argument("--list", nargs="?", const="", metavar="MATCH",
                   help="list Home Assistant's lights (optionally only those matching MATCH)")
    p.add_argument("--walk", action="store_true",
                   help="light each light in turn, 1 to the end, to check the order")
    p.add_argument("--row", help="with --walk: which row (default: the first)")
    p.add_argument("--hold", type=float, default=1.5, help="with --walk: seconds per light")
    p.add_argument("--test", nargs=2, metavar=("ROW", "SETTING"),
                   help="no MQTT: run SETTING (e.g. '{\"color\":\"#ff6a00\",\"animation\":\"chase\"}') "
                        "on ROW, then off")
    p.add_argument("--seconds", type=float, default=15, help="with --test: how long (default 15)")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(fn=cmd_floods)

    p = sub.add_parser("console", help="the terminal UI")
    show_arg(p)
    p.add_argument("--broker", help="MQTT broker host (default: from the show file)")
    p.add_argument("--ascii", action="store_true", help="plain ASCII, no box-drawing characters")
    p.set_defaults(fn=cmd_console)

    p = sub.add_parser("demo", help="director + pretend players + console in one process")
    show_arg(p)
    p.add_argument("--clip-seconds", type=float, default=30, help="pretend every clip is this long")
    p.add_argument("--ascii", action="store_true")
    p.set_defaults(fn=cmd_demo)

    p = sub.add_parser("check", help="validate a show file")
    show_arg(p)
    p.add_argument("--media", help="also check every file exists under this directory")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("send", help="send one command to the director (next, prev, pause, ...)")
    p.add_argument("command")
    p.add_argument("params", nargs="*", metavar="key=value")
    p.add_argument("--show", default=DEFAULT_SHOW)
    p.add_argument("--broker")
    p.set_defaults(fn=cmd_send)

    args = ap.parse_args(argv)
    try:
        args.fn(args)
    except ConfigError as exc:
        sys.exit("configuration problem:\n%s" % exc)
    except KeyboardInterrupt:
        pass
