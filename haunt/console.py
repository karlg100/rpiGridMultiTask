"""The console: a terminal UI for the show.

It is only an MQTT client. It holds no show state of its own, so you can run
it on home-pi over SSH, on a laptop, or both at once, and quitting it never
touches the show.

``render()`` is a pure function from the model to styled text lines; curses
is only used to paint those lines and read keys. That keeps the layout
testable without a terminal.
"""

from __future__ import annotations

import json
import os
import time
from typing import List, Optional, Tuple

from .bus import Bus
from .lights import effect_label
from .topics import Topics

Seg = Tuple[str, object]      # (text, style)
Line = List[Seg]

UNICODE = {"bar_on": "█", "bar_off": "░", "dot": "●", "swatch": "■",
           "rule": "─", "play": "▶", "pause": "‖", "stop": "■",
           "ell": "…", "arrow": "→", "cur": "▸"}
ASCII = {"bar_on": "#", "bar_off": "-", "dot": "*", "swatch": "#",
         "rule": "-", "play": ">", "pause": "=", "stop": "x",
         "ell": "~", "arrow": ">", "cur": ">"}

HELP = [
    "space pause/resume   n next   p previous   r restart scene   enter go to selected",
    "s stop/start show   x skip scene on/off   +/- master   tab player   [ ] level   m mute",
    "u undo level changes   R reload show file   h Hue rooms: show / house   up/down select",
    "f fog   w mister: each press steps auto > forced on > forced off > auto (fog on = one burst)",
    "q quit (the show keeps running)",
]


OUTPUT_KEYS = {"fog": "f", "mister": "w"}     # console keys for the outputs, by label


def output_key(label: str) -> Optional[str]:
    return OUTPUT_KEYS.get((label or "").lower())


def mmss(seconds) -> str:
    if seconds is None:
        return "--:--"
    seconds = max(0, int(seconds))
    return "%d:%02d" % (seconds // 60, seconds % 60)


def clip_text(text: str, width: int, ell: str = "~") -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    return text[:max(0, width - 1)] + ell


def pad(text: str, width: int, ell: str = "~") -> str:
    return clip_text(text, width, ell).ljust(width)


class Model:
    """Everything the console knows, assembled from retained MQTT messages."""

    def __init__(self, topics: Topics, clock=time.monotonic):
        self.topics = topics
        self.clock = clock
        self.director_online = False
        self.state = {}
        self.state_seen = -1e9
        self.playlist = {}
        self.players = {}      # pid -> {"online": bool, "state": dict, "seen": t}
        self.hue_online = None  # the `haunt hue` agent, None = never heard
        self.floods_online = None  # the `haunt floods` agent
        self.light_online = {}     # light name -> bool, for controllers watched by `haunt devwatch`

    def _player(self, pid):
        return self.players.setdefault(pid, {"online": False, "state": {}, "seen": -1e9})

    def handle(self, topic: str, payload: str) -> None:
        t = self.topics
        try:
            if topic == t.director_online:
                self.director_online = payload == "1"
            elif topic == t.director_state:
                self.state = json.loads(payload)
                self.state_seen = self.clock()
            elif topic == t.director_playlist:
                self.playlist = json.loads(payload)
            elif topic == t.hue_online:
                self.hue_online = payload == "1"
            elif topic == t.floods_online:
                self.floods_online = payload == "1"
            elif t.parse_light_online(topic):
                name = t.parse_light_online(topic)
                if payload.strip():
                    self.light_online[name] = payload.strip() == "1"
                else:
                    self.light_online.pop(name, None)
            else:
                parsed = t.parse_player(topic)
                if not parsed:
                    return
                pid, leaf = parsed
                p = self._player(pid)
                if leaf == "online":
                    p["online"] = payload == "1"
                elif leaf == "state":
                    p["state"] = json.loads(payload)
                    p["seen"] = self.clock()
        except ValueError:
            pass

    def player_ids(self) -> List[str]:
        ids = set(self.players) | set((self.playlist.get("players") or {}))
        return sorted(ids, key=lambda x: (len(x), x))

    def pos(self, pid: str) -> float:
        """Position, carried forward between reports for a smooth bar."""
        p = self._player(pid)
        st = p["state"]
        pos = float(st.get("pos") or 0)
        if st.get("state") == "playing" and p["online"]:
            pos += max(0.0, min(1.0, self.clock() - p["seen"]))
            if st.get("dur") and not st.get("loop"):
                pos = min(pos, float(st["dur"]))
        return pos

    def scenes(self) -> list:
        return self.playlist.get("scenes") or []


STATE_STYLE = {"playing": "ok", "ready": "warn", "loading": "warn", "paused": "info",
               "stopping": "warn", "ended": "dim", "idle": "dim", "error": "err"}

PHASE_STYLE = {"running": "ok", "preparing": "warn", "ending": "warn", "gap": "warn",
               "stopped": "err", "waiting": "err"}


def rule(title: str, width: int, ch: str) -> Line:
    head = ch * 2 + " " + title + " "
    return [(head, "title"), (ch * max(0, width - len(head)), "dim")]


def clip_flags(c: dict, sym: dict) -> str:
    flags = []
    if c.get("loop"):
        flags.append("loop")
    if c.get("start"):
        flags.append("@%s" % mmss(c["start"]))
    if c.get("start_after"):
        flags.append("+%ds" % c["start_after"])
    if c.get("end_at") is not None:
        flags.append("%s%s" % (sym["arrow"], mmss(c["end_at"])))
    return " ".join(flags)


def level_text(c: dict) -> str:
    lvl = c.get("level", 100)
    text = "mute" if not lvl else "%d%%" % round(lvl)
    return text + ("*" if c.get("overridden") else "")


def scene_length(scene: dict):
    if scene.get("end_at") is not None:
        return scene["end_at"]
    m = (scene.get("players") or {}).get(str(scene.get("master")), {})
    if m.get("dur"):
        return max(0.0, float(m["dur"]) - float(m.get("start") or 0))
    return None


def render(model: Model, width: int, height: int, sel: int = 0, focus: Optional[str] = None,
           unicode: bool = True, broker: str = "", connected: bool = True,
           wallclock=time.time, show_help: bool = False) -> List[Line]:
    sym = UNICODE if unicode else ASCII
    ell = sym["ell"]
    w = max(40, width)
    st = model.state
    pids = model.player_ids()
    names = model.playlist.get("players") or {}
    scenes = model.scenes()
    lines: List[Line] = []

    # ---- header --------------------------------------------------------
    clock_txt = time.strftime("%H:%M:%S", time.localtime(wallclock()))
    left = " HAUNT  %s" % (st.get("show") or model.playlist.get("name") or "")
    right = "%s %s  %s " % (broker, sym["dot"], clock_txt)
    gap = max(1, w - len(left) - len(right))
    lines.append([(left, "bold"), (" " * gap, ""), (broker + " ", "dim"),
                  (sym["dot"], "ok" if connected else "err"), ("  %s " % clock_txt, "")])

    if not connected:
        lines.append([(" NOT CONNECTED to the MQTT broker %s; retrying" % broker, "err")])
    elif not model.director_online:
        lines.append([(" DIRECTOR OFFLINE", "err"),
                      ("  the show brain is not running (haunt director show.yaml)", "dim")])
    else:
        phase = st.get("phase", "?")
        if st.get("paused"):
            icon, label, style = sym["pause"], "PAUSED", "info"
        else:
            icon = sym["play"] if phase == "running" else (sym["stop"] if phase in ("stopped", "waiting") else sym["dot"])
            label, style = phase.upper(), PHASE_STYLE.get(phase, "")
        seg: Line = [(" %s %-9s" % (icon, label), style)]
        seg.append((" scene %s/%s  " % (st.get("index", 0) + 1, st.get("count", "?")), ""))
        tail = "  master %d%% " % round(st.get("master_level", 100))
        if st.get("next") is not None and phase in ("ending", "gap"):
            tail = "  %s scene %d" % (sym["arrow"], st["next"] + 1) + tail
        room = w - sum(len(t) for t, _ in seg) - len(tail)
        seg.append((pad(st.get("scene", ""), room, ell), "bold"))
        seg.append((tail, ""))
        lines.append(seg)

    # ---- players -------------------------------------------------------
    lines.append(rule("PLAYERS", w, sym["rule"]))
    roles = st.get("players") or {}
    master_pos = float(st.get("pos") or 0)
    for pid in pids:
        p = model.players.get(pid, {"online": False, "state": {}})
        ps = p["state"]
        role = (roles.get(pid) or {}).get("role", "")
        name = (names.get(pid) or {}).get("name", "")
        state = ps.get("state", "?") if p["online"] else "OFFLINE"
        style = STATE_STYLE.get(state, "err") if p["online"] else "err"
        mark = sym["cur"] if pid == focus else " "
        head: Line = [(mark, "bold"), ("P%s " % pid, "bold"), (pad(name, 10, ell), "bold"),
                      (" %-9s" % {"master": "MASTER", "follower": "follower"}.get(role, ""),
                       "info" if role == "master" else "dim"),
                      (sym["dot"] + " ", style), ("%-9s" % state, style)]
        used = sum(len(t) for t, _ in head)
        file = os.path.basename(ps.get("file") or "") if p["online"] else ""
        if state == "error":
            head.append((clip_text(str(ps.get("error") or ""), w - used, ell), "err"))
        else:
            head.append((clip_text(file, w - used, ell), ""))
        lines.append(head)

        detail: Line = [(" " * 16, "")]
        dur = ps.get("dur")
        active = p["online"] and state in ("playing", "paused", "stopping")
        info = (roles.get(pid) or {})
        if active:
            pos = model.pos(pid)
            bar_w = max(10, min(40, w - 62))
            if dur:
                filled = int(round(bar_w * min(1.0, pos / float(dur))))
                detail.append((sym["bar_on"] * filled, "ok" if state == "playing" else "info"))
                detail.append((sym["bar_off"] * (bar_w - filled), "dim"))
            else:
                detail.append((sym["bar_off"] * bar_w, "dim"))
            detail.append(("  %s / %s" % (mmss(pos), mmss(dur)), ""))
            if ps.get("loop"):
                detail.append((" loop", "dim"))
        elif p["online"] and state in ("ready", "loading") and role == "follower":
            wait = float(info.get("start_after") or 0) - master_pos
            txt = "starts in %s" % mmss(wait) if wait > 0.5 else "cued"
            detail.append((txt, "warn"))
        elif p["online"] and state == "idle" and role == "follower" and st.get("phase") == "running":
            wait = float(info.get("start_after") or 0) - master_pos
            if wait > 0:
                detail.append(("starts in %s" % mmss(wait), "dim"))
        if p["online"] and state not in ("idle", "OFFLINE", "?"):
            used = sum(len(t) for t, _ in detail)
            # The scene's level as the playlist shows it (before the master fader).
            cur_scene = scenes[st["index"]] if 0 <= st.get("index", -1) < len(scenes) else {}
            c = (cur_scene.get("players") or {}).get(pid)
            vol = "level " + (level_text(c) if c and model.director_online
                              else "%d%%" % round(ps.get("level") or 0))
            if ps.get("gain_db"):
                vol += "  (%+.1f dB normalise)" % ps["gain_db"]
            detail.append((" " * max(2, 48 + max(0, w - 110) - used) + vol, ""))
        lines.append(detail)

    # ---- lights --------------------------------------------------------
    lines.append(rule("LIGHTS & EFFECTS", w, sym["rule"]))
    light_types = model.playlist.get("lights") or {}
    hue_house = st.get("hue") == "released"
    if any((v or {}).get("type") == "hue" for v in light_types.values()):
        hseg: Line = [(" Hue rooms  ", "bold")]
        if hue_house:
            hseg += [(sym["dot"] + " HOUSE", "warn"),
                     ("  left alone for the Hue app and switches   h: give them to the show", "dim")]
        else:
            hseg += [(sym["dot"] + " SHOW", "ok"),
                     ("  follow the scenes (off when stopped)   h: hand them to the house", "dim")]
        if model.hue_online is False:
            hseg.append(("   hue agent OFFLINE", "err"))
        lines.append(hseg)
    if model.floods_online is False and any((v or {}).get("type") == "floods"
                                            for v in light_types.values()):
        lines.append([(" Floods  ", "bold"), ("floods agent OFFLINE", "err")])
    lseg: Line = [(" ", "")]
    for name in light_types:
        cur = (st.get("lights") or {}).get(name)
        lseg.append((name + " ", ""))
        if model.light_online.get(name) is False:
            lseg.append(("OFFLINE ", "err"))
        elif model.light_online.get(name):
            lseg.append((sym["dot"] + " ", "ok"))
        if hue_house and (light_types.get(name) or {}).get("type") == "hue":
            lseg.append(("house", "dim"))
        elif cur is None:
            lseg.append(("?", "dim"))
        elif not cur.get("on", True):
            lseg.append(("off", "dim"))
        else:
            color = cur.get("color")
            for c in (cur.get("colors") or [color])[:3]:
                lseg.append((sym["swatch"] * 2, ("rgb", c) if c else "dim"))
            label = effect_label(cur)
            lseg.append((" " + (label or color or "on"), ""))
            if cur.get("preset") is not None:
                lseg.append((" preset %s" % cur["preset"], "dim"))
        lseg.append(("    ", ""))
    lines.append(lseg)
    outs = st.get("outputs") or {}
    if outs:
        oseg: Line = [(" ", "")]
        for name, o in outs.items():
            on = o.get("on")
            label = o.get("label", name)
            key = output_key(label)
            oseg.append((label + (" (%s) " % key if key else " "), "bold"))
            txt = "ON" if on else "off"
            if on and o.get("burst") is not None:
                txt = "ON %ds" % max(0, round(o["burst"]))
            elif not on and o.get("next") is not None and o.get("override") != "off":
                txt = "off, next in %ds" % max(0, round(o["next"]))
            oseg.append((sym["dot"] + " " + txt, "warn" if on else "dim"))
            ov = o.get("override")
            if ov == "off":
                oseg.append(("  FORCED OFF", "err"))
            elif ov == "on":
                oseg.append(("  FORCED ON", "warn"))
            else:
                oseg.append(("  auto", "dim"))
            oseg.append(("     ", ""))
        oseg.append(("keys: auto > on > off", "dim"))
        lines.append(oseg)

    # ---- how much room is left -----------------------------------------
    help_lines = HELP if show_help else [" ? keys   space pause   n next   p prev   r restart   "
                                         "enter go to   s stop/start   +/- master   [ ] level   h hue   q quit"]
    logbuf = st.get("log") or []
    fixed = len(lines) + 2 + 1 + len(help_lines)   # playlist rule+header, log rule, help
    spare = max(0, height - fixed)
    detail_rows = 4 if spare >= 16 else 0
    log_rows = max(2, min(8, (spare - detail_rows) // 3)) if spare >= 5 else max(0, spare - 3)
    list_rows = max(1, spare - detail_rows - log_rows - (1 if detail_rows else 0))

    # ---- playlist ------------------------------------------------------
    lines.append(rule("PLAYLIST", w, sym["rule"]))
    n = len(pids) or 1
    name_w = max(14, min(34, (w - 16) // (n + 1)))
    cell_w = max(16, (w - 15 - name_w - 2 - 3 * len(model.playlist.get("lights") or {})) // n)
    flag_w = 11 if cell_w >= 34 else (9 if cell_w >= 26 else 4)
    file_w = max(6, cell_w - 10 - flag_w)
    hdr: Line = [("   # ", "dim"), (pad("scene", name_w), "dim"), ("    len ", "dim")]
    for pid in pids:
        hdr.append((pad("P%s %s" % (pid, (names.get(pid) or {}).get("name", "")), cell_w), "dim"))
    hdr.append(("lights", "dim"))
    lines.append(hdr)

    cur_idx = st.get("index", -1) if model.director_online else -1
    top = max(0, min(sel - list_rows // 2, len(scenes) - list_rows))
    for sc in scenes[top:top + list_rows]:
        i = sc["index"]
        is_cur = i == cur_idx
        is_sel = i == sel
        base = "sel" if is_sel else ("dim" if not sc.get("enabled", True) else "")
        row: Line = []
        marker = sym["play"] if is_cur else " "
        row.append((" %s" % marker, "ok" if is_cur and not is_sel else base))
        row.append(("%2d " % (i + 1), base))
        label = sc["name"] if sc.get("enabled", True) else sc["name"] + " (skip)"
        row.append((pad(label, name_w, ell), "bold" if is_cur and not is_sel else base))
        row.append((" %6s " % mmss(scene_length(sc)), base))
        for pid in pids:
            c = (sc.get("players") or {}).get(pid)
            if not c:
                row.append((pad("  -", cell_w), base))
                continue
            is_master = str(sc.get("master")) == pid
            cell = "%s%s" % ("M " if is_master else "  ", pad(os.path.basename(c["file"]), file_w, ell))
            flags = clip_flags(c, sym)
            rest = " %-5s %s" % (level_text(c), clip_text(flags, flag_w, ell))
            if c.get("missing"):
                row.append((pad(cell + " MISSING", cell_w - 1, ell) + " ", "sel" if is_sel else "err"))
            else:
                row.append((pad(cell + rest, cell_w - 1, ell) + " ", base))
        for lname in (model.playlist.get("lights") or {}):
            setting = (sc.get("lights") or {}).get(lname)
            if setting and setting.get("on", True) and setting.get("color"):
                row.append((sym["swatch"] * 2, ("rgb", setting["color"])))
            else:
                row.append(("  ", base))
            row.append((" ", base))
        # one letter per output this scene uses (M = mister, F = fog ...)
        used = dict(sc.get("outputs") or {})
        for cue in sc.get("cues") or []:
            used.update({k: v for k, v in (cue.get("outputs") or {}).items() if v})
        marks = "".join(model.playlist.get("outputs", {}).get(k, {}).get("label", k)[:1].upper()
                        for k, v in used.items() if v)
        if marks:
            row.append((marks, "warn" if not is_sel else base))
        lines.append(row)
    for _ in range(list_rows - len(scenes[top:top + list_rows])):
        lines.append([])

    # ---- selected scene, in full ---------------------------------------
    if detail_rows and scenes:
        sc = scenes[max(0, min(sel, len(scenes) - 1))]
        lines.append(rule("SCENE %d  %s" % (sc["index"] + 1, sc["name"]), w, sym["rule"]))
        rows = []
        for pid in pids:
            c = (sc.get("players") or {}).get(pid)
            if not c:
                continue
            bits = ["P%s%s" % (pid, " master" if str(sc.get("master")) == pid else ""),
                    c["file"], "level " + level_text(c)]
            if c.get("overridden"):
                bits.append("(show file: %d%%)" % round(c.get("level_file", 0)))
            flags = clip_flags(c, sym)
            if flags:
                bits.append(flags)
            bits.append("fade %.4g/%.4gs" % (c.get("fade_in", 0), c.get("fade_out", 0)))
            if isinstance(c.get("lufs"), (int, float)):
                bits.append("%.1f LUFS" % c["lufs"])
            elif c.get("lufs") == "none":
                bits.append("no audio")
            if c.get("missing"):
                bits.append("FILE MISSING ON PLAYER")
            rows.append([(" " + clip_text("  ".join(bits), w - 2, ell), "err" if c.get("missing") else "")])
        extra = []
        if sc.get("end_at") is not None:
            extra.append("scene ends at %s" % mmss(sc["end_at"]))
        for lname, setting in (sc.get("lights") or {}).items():
            desc = effect_label(setting) or setting.get("color") if setting.get("on", True) else "off"
            extra.append("%s %s" % (lname, desc))
        out_labels = {k: v.get("label", k) for k, v in (model.playlist.get("outputs") or {}).items()}
        for oname, val in (sc.get("outputs") or {}).items():
            if val is True:
                extra.append("%s on" % out_labels.get(oname, oname))
            elif isinstance(val, dict):
                extra.append("%s %gs every %gs" % (out_labels.get(oname, oname), val["burst"], val["every"]))
            elif val:
                extra.append("%s %gs burst" % (out_labels.get(oname, oname), val))
        for cue in sc.get("cues") or []:
            what = []
            if cue.get("mqtt"):
                what.append("%s=%s" % (cue["mqtt"]["topic"], cue["mqtt"].get("payload", "")))
            for lname, setting in (cue.get("lights") or {}).items():
                what.append("%s %s" % (lname, effect_label(setting) or setting.get("color") or "off"))
            for oname, val in (cue.get("outputs") or {}).items():
                what.append("%s %s" % (oname, "on" if val is True else ("off" if not val else (
                    "%gs every %gs" % (val["burst"], val["every"]) if isinstance(val, dict) else "%gs" % val))))
            extra.append("cue @%s %s" % (mmss(cue["at"]), ", ".join(what)))
        rows.append([(" " + clip_text("   ".join(extra), w - 2, ell), "dim")])
        rows = rows[:detail_rows]
        lines.extend(rows)
        for _ in range(detail_rows - len(rows)):
            lines.append([])

    # ---- log -----------------------------------------------------------
    if log_rows:
        lines.append(rule("LOG", w, sym["rule"]))
        tail = logbuf[-log_rows:]
        for ts, level, text in tail:
            stamp = time.strftime("%H:%M:%S", time.localtime(ts))
            lines.append([(" " + stamp + " ", "dim"),
                          (clip_text(text, w - 11, ell),
                           {"warning": "warn", "error": "err"}.get(level, ""))])
        for _ in range(log_rows - len(tail)):
            lines.append([])

    for h in help_lines:
        lines.append([(clip_text(h if h.startswith(" ") else " " + h, w, ell), "dim")])
    lines = lines[:height] if height else lines
    return [_fit(line, w) for line in lines]


def _fit(line: Line, width: int) -> Line:
    """Cut a line of segments to at most ``width`` characters."""
    out, room = [], width
    for text, style in line:
        if room <= 0:
            break
        out.append((text[:room], style))
        room -= len(text[:room])
    return out


def to_text(lines: List[Line]) -> str:
    return "\n".join("".join(t for t, _ in line).rstrip() for line in lines)


# --------------------------------------------------------------------------
# Controller: keys -> director commands
# --------------------------------------------------------------------------

class Controller:
    def __init__(self, model: Model, bus: Bus):
        self.model = model
        self.bus = bus
        self.sel = 0
        self.focus = None
        self.follow = True       # selection follows the playing scene until you move it
        self.show_help = False
        self.quit = False
        self._last_index = None

    def send(self, _cmd: str, **kw) -> None:
        self.bus.publish(self.model.topics.director_cmd, dict(kw, cmd=_cmd))

    def sync(self) -> None:
        """Keep selection/focus valid as state arrives."""
        pids = self.model.player_ids()
        if self.focus not in pids:
            self.focus = pids[0] if pids else None
        idx = self.model.state.get("index")
        if idx is not None and idx != self._last_index:
            self._last_index = idx
            if self.follow:
                self.sel = idx
        n = len(self.model.scenes())
        if n:
            self.sel = max(0, min(self.sel, n - 1))

    def key(self, k: str) -> None:
        """k is a single character or one of UP DOWN HOME END ENTER TAB."""
        n = len(self.model.scenes())
        cur = self.model.state.get("index", 0)
        if k in ("q", "Q"):
            self.quit = True
        elif k == "?":
            self.show_help = not self.show_help
        elif k == " ":
            self.send("toggle")
        elif k == "n":
            self.follow = True
            self.send("next")
        elif k == "p":
            self.follow = True
            self.send("prev")
        elif k == "r":
            self.send("restart")
        elif k == "s":
            self.send("start" if self.model.state.get("phase") in ("stopped", "waiting") else "stop")
        elif k in ("UP", "k") and n:
            self.sel = (self.sel - 1) % n
            self.follow = self.sel == cur
        elif k in ("DOWN", "j") and n:
            self.sel = (self.sel + 1) % n
            self.follow = self.sel == cur
        elif k == "HOME":
            self.sel, self.follow = 0, False
        elif k == "END" and n:
            self.sel, self.follow = n - 1, False
        elif k == "ENTER" and n:
            self.follow = True
            self.send("goto", index=self.sel)
        elif k == "x" and n:
            self.send("enable", index=self.sel)
        elif k in ("+", "="):
            self.send("master", delta=5)
        elif k in ("-", "_"):
            self.send("master", delta=-5)
        elif k == "TAB":
            pids = self.model.player_ids()
            if pids:
                self.focus = pids[(pids.index(self.focus) + 1) % len(pids)] if self.focus in pids else pids[0]
        elif k == "]" and self.focus:
            self.send("level", player=self.focus, delta=5)
        elif k == "[" and self.focus:
            self.send("level", player=self.focus, delta=-5)
        elif k == "m" and self.focus:
            self.send("mute", player=self.focus)
        elif k == "u":
            self.send("reset_levels")
        elif k == "R":
            self.send("reload")
        elif k == "h":
            self.send("hue")
        else:
            outs = self.model.playlist.get("outputs") or {}
            for name, o in outs.items():
                if output_key(o.get("label", name)) == k:
                    self.send("output", name=name)
                    break


# --------------------------------------------------------------------------
# curses front end
# --------------------------------------------------------------------------

def _rgb_to_256(color: str) -> int:
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    if r == g == b:
        if r < 8:
            return 16
        if r > 248:
            return 231
        return 232 + int(round((r - 8) / 247 * 23))
    q = lambda v: int(round(v / 255 * 5))
    return 16 + 36 * q(r) + 6 * q(g) + q(b)


def _rgb_to_8(color: str) -> int:
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    top = max(r, g, b)
    if top < 40:
        return 0
    return (1 if r > top * 0.55 else 0) | (2 if g > top * 0.55 else 0) | (4 if b > top * 0.55 else 0)


def run_curses(model: Model, bus: Bus, broker: str = "", unicode: bool = True) -> None:
    import curses
    import locale

    locale.setlocale(locale.LC_ALL, "")
    ctl = Controller(model, bus)

    def main(stdscr):
        curses.curs_set(0)
        stdscr.timeout(100)
        colors = curses.has_colors()
        styles = {"": 0, "bold": curses.A_BOLD, "dim": curses.A_DIM,
                  "sel": curses.A_REVERSE, "title": curses.A_BOLD}
        pairs = {}
        if colors:
            curses.start_color()
            curses.use_default_colors()
            for i, (name, fg) in enumerate((("ok", curses.COLOR_GREEN), ("warn", curses.COLOR_YELLOW),
                                            ("err", curses.COLOR_RED), ("info", curses.COLOR_CYAN),
                                            ("title", curses.COLOR_MAGENTA)), 1):
                curses.init_pair(i, fg, -1)
                styles[name] = curses.color_pair(i) | (curses.A_BOLD if name in ("err", "title") else 0)
        else:
            styles.update(ok=curses.A_BOLD, warn=0, err=curses.A_BOLD, info=0)

        def attr(style):
            if isinstance(style, tuple):          # ("rgb", "#rrggbb")
                if not colors:
                    return 0
                code = _rgb_to_256(style[1]) if curses.COLORS >= 256 else _rgb_to_8(style[1])
                if code not in pairs:
                    num = 10 + len(pairs)
                    if num >= curses.COLOR_PAIRS:
                        return 0
                    curses.init_pair(num, code, -1)
                    pairs[code] = curses.color_pair(num)
                return pairs[code]
            return styles.get(style, 0)

        keymap = {curses.KEY_UP: "UP", curses.KEY_DOWN: "DOWN", curses.KEY_HOME: "HOME",
                  curses.KEY_END: "END", curses.KEY_ENTER: "ENTER", 10: "ENTER", 13: "ENTER",
                  9: "TAB"}
        while not ctl.quit:
            for topic, payload in bus.poll():
                model.handle(topic, payload)
            ctl.sync()
            h, w = stdscr.getmaxyx()
            lines = render(model, w, h, sel=ctl.sel, focus=ctl.focus, unicode=unicode,
                           broker=broker, connected=bus.connected, show_help=ctl.show_help)
            stdscr.erase()
            for y, line in enumerate(lines[:h]):
                x = 0
                for text, style in line:
                    if x >= w - 1:
                        break
                    text = text[:w - 1 - x]
                    try:
                        stdscr.addstr(y, x, text, attr(style))
                    except curses.error:
                        pass
                    x += len(text)
            stdscr.refresh()
            ch = stdscr.getch()
            if ch == -1 or ch == curses.KEY_RESIZE:
                continue
            if ch == 12:                      # Ctrl-L: repaint from scratch
                stdscr.clearok(True)
                continue
            ctl.key(keymap.get(ch) or (chr(ch) if 0 < ch < 256 else ""))

    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
    finally:
        bus.close()
