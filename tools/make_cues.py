"""Generate per-scene lighting timelines (show-cues.yaml) from video analysis.

The analysis (tools/analyze_video.py, run on a player Pi, which has the files)
gives, per scene: keyframe times with their dominant colours, and the
soundtrack's loudness every 0.5 s. From that:

  * sections: hard cuts (a big colour change between keyframes); videos with
    no cuts are split into timed sections
  * colours: each section's two strongest colours, at full brightness and
    strong saturation; dark sections use the scene's theme colours
  * energy: loudness against the scene's own median, and the scene's cut rate
    and tempo, pick the animation and its speed
  * each light system changes only as often as it can: eaves (WLED) every cut
    down to 2.5 s apart, graveyard 4 s, Hue rooms 6 s, floods 20 s (the AiDot
    hub and the solar batteries), floods only with slow drifts

usage: python3 tools/make_cues.py ANALYSIS_DIR show.yaml > show-cues.yaml
"""
import colorsys, glob, json, os, statistics, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from haunt.config import load_show
import yaml

MIN_GAP = {"front_lights": 2.5, "graveyard": 4.0, "hue": 6.0, "floods": 20.0}
HUE_ROOMS = ("living_room", "front_bedroom", "porch", "lamp_post")


def rgb(h):
    return [int(h[i:i + 2], 16) for i in (1, 3, 5)]


def hexc(c):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(x)))) for x in c)


def vivid(h, sat_min=0.8):
    r, g, b = [x / 255 for x in rgb(h)]
    hh, s, v = colorsys.rgb_to_hsv(r, g, b)
    if s >= 0.25:
        s = max(s, sat_min)
    else:
        s = 0.0                           # whites stay white
    return hexc([x * 255 for x in colorsys.hsv_to_rgb(hh, s, 1.0)])


def hue_of(h):
    r, g, b = [x / 255 for x in rgb(h)]
    return colorsys.rgb_to_hsv(r, g, b)


def distinct(cols, n=2):
    out = []
    for c in cols:
        hh, s, _ = hue_of(c)
        if all(min(abs(hh - hue_of(o)[0]), 1 - abs(hh - hue_of(o)[0])) > 0.08 or (s < 0.2) != (hue_of(o)[1] < 0.2)
               for o in out):
            out.append(c)
        if len(out) == n:
            break
    return out


def theme(scene):
    """The scene's own colours from show.yaml (front_lights, else living room)."""
    for n in ("front_lights", "living_room", "floods"):
        v = scene.lights.get(n) or {}
        cols = [c for c in (v.get("colors") or [v.get("color")]) if c and c != "#000000"]
        if len(cols) >= 2:
            return [vivid(c) for c in cols[:2]]
    return ["#ff6a00", "#8000ff"]


def sections(keys, dur, static_len):
    """Section start times: cuts, or a timed grid when the video has none."""
    cuts = [keys[0]["t"]]
    for p, q in zip(keys, keys[1:]):
        if sum(abs(x - y) for x, y in zip(rgb(p["mean"]), rgb(q["mean"]))) > 60:
            cuts.append(q["t"])
    t0 = keys[0]["t"]
    grid = [t0 + k * static_len for k in range(int(dur // static_len) + 1)]
    # keep the cuts, and fill any long stretch without one from a timed grid
    near = 2.0 if len(cuts) * 60.0 / max(1.0, dur) < 4 else 0.75 * static_len
    cuts = sorted(set(cuts) | {g for g in grid if all(abs(g - c) >= near for c in cuts)})
    return cuts


def section_colours(keys, t0, t1, fallback):
    ks = [k for k in keys if t0 - 0.01 <= k["t"] < t1] or [min(keys, key=lambda k: abs(k["t"] - t0))]
    score = {}
    for k in ks:
        for c in k["top"]:
            if c["share"] < 0.02:
                continue
            v = vivid(c["rgb"])
            score[v] = score.get(v, 0) + c["share"]
    cols = distinct([c for c, _ in sorted(score.items(), key=lambda kv: -kv[1])])
    bright = statistics.mean(k["bright"] for k in ks)
    if len(cols) < 2:
        cols = (cols + [c for c in fallback if c not in cols])[:2]
    return cols, bright


def energy_at(rms, t, start, span=4.0):
    i0 = max(0, int((t - start) * 2)); i1 = max(i0 + 1, int((t + span - start) * 2))
    seg = [x for x in rms[i0:i1] if x > -90]
    return statistics.mean(seg) if seg else -60.0


def wled(cols, level, k, tempo):
    a, b = cols
    if k % 2:
        a, b = b, a                       # contrast: swap on alternate cuts
    if level == "peak":
        opts = [{"effect": "Running", "colors": [a, b], "speed": 210, "intensity": 90},
                {"effect": "Colorwaves", "palette": "Color Gradient", "colors": [a, b, a], "speed": 220, "intensity": 160},
                {"effect": "Popcorn", "colors": [a, b], "speed": 160, "intensity": 220},
                {"effect": "Meteor", "colors": [a], "speed": 220, "intensity": 160, "o3": True}]
    elif level == "mid":
        opts = [{"effect": "Colorwaves", "palette": "Color Gradient", "colors": [a, b, a], "speed": 140, "intensity": 128},
                {"effect": "Fairytwinkle", "colors": [a, b], "speed": 120, "intensity": 128},
                {"effect": "Running", "colors": [a, b], "speed": 120, "intensity": 70}]
    else:
        opts = [{"effect": "Colorwaves", "palette": "Color Gradient", "colors": [a, b, a], "speed": 60, "intensity": 128},
                {"effect": "Candle Multi", "colors": [a, b], "speed": 80, "intensity": 200}]
    s = dict(opts[k % len(opts)])
    s["transition"] = 0.3 if level == "peak" else 1
    return s


def hue_room(cols, level, k, room, tempo):
    a, b = cols
    if room in ("front_bedroom", "porch"):
        a, b = b, a
    beat = max(2.0, round(2 * 60.0 / tempo, 2)) if tempo else 2.0     # a pulse lasts two beats
    if room == "lamp_post":
        return {"color": a, "animation": "flicker", "period": 0.8 if level == "peak" else 1.2, "low": 0.6}
    if level == "peak":
        return ({"colors": [a, b], "animation": "pulse", "period": beat, "low": 0.6} if k % 2 == 0
                else {"colors": [a, b], "animation": "drift", "period": 1.0})
    if level == "mid":
        return {"colors": [a, b], "animation": "drift", "period": 3.0}
    return {"colors": [a, b], "animation": "drift", "period": 6.0}


def floods(cols, level):
    a, b = cols
    return {"colors": [a, b], "animation": "drift", "period": 8 if level == "peak" else (10 if level == "mid" else 14)}


def build(scene, an, length):
    keys = an["keys"]; start = an["start"]
    rms = an["audio"]["rms_db_per_0.5s"]
    loud = [x for x in rms if x > -90]
    med = statistics.median(loud); p75 = sorted(loud)[int(len(loud) * 0.75)]
    tempos = [t for t in an["audio"]["tempo_per_20s"] if t]
    tempo = statistics.median(tempos) if tempos else 110
    if tempo < 80:
        tempo *= 2                        # autocorrelation found the half beat
    end = start + length
    cuts_per_min = sum(1 for p, q in zip(keys, keys[1:])
                       if sum(abs(x - y) for x, y in zip(rgb(p["mean"]), rgb(q["mean"]))) > 60) * 60 / max(1, length)
    hot = cuts_per_min >= 6 or med >= -15
    static_len = 6.0 if hot else 8.0
    secs = [t for t in sections(keys, length, static_len) if start + 1.0 <= t < end - 2.0]
    fallback = theme(scene)
    # hand-written cues in show.yaml win: their lights are left alone for 30 s
    held = [(c.at, set(c.lights)) for c in scene.cues if c.lights]
    last = {}
    cues = {}
    for k, t in enumerate(secs):
        t1 = secs[k + 1] if k + 1 < len(secs) else end
        cols, bright = section_colours(keys, t, t1, fallback)
        if bright < 0.06:                 # nearly black on screen: use the scene's colours
            cols = fallback if k % 2 == 0 else fallback[::-1]
        e = energy_at(rms, t, start)
        level = "peak" if (e >= p75 and hot) or (hot and e >= med) else ("mid" if e >= med or hot else "calm")
        add = {}
        if t - last.get("front_lights", -99) >= MIN_GAP["front_lights"]:
            add["front_lights"] = wled(cols, level, k, tempo); last["front_lights"] = t
        if t - last.get("graveyard", -99) >= MIN_GAP["graveyard"]:
            add["graveyard"] = cols[k % 2]; last["graveyard"] = t
        if t - last.get("hue", -99) >= MIN_GAP["hue"]:
            for r in HUE_ROOMS:
                add[r] = hue_room(cols, level, k, r, tempo)
            last["hue"] = t
        if t - last.get("floods", -99) >= MIN_GAP["floods"]:
            add["floods"] = floods(cols, level); last["floods"] = t
        for at, names in held:
            if at <= t < at + 30:
                add = {n: v for n, v in add.items() if n not in names}
        if add:
            cues.setdefault(round(t, 1), {}).update(add)
    return [{"at": t, "lights": v} for t, v in sorted(cues.items())], {"tempo": tempo, "hot": hot,
                                                                         "cuts_per_min": round(cuts_per_min, 1)}


def main():
    adir, show_path = sys.argv[1], sys.argv[2]
    lens = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
    show = load_show(show_path)
    out = {}
    for f in sorted(glob.glob(os.path.join(adir, "scene_*.json"))):
        an = json.load(open(f))
        scene = next(s for s in show.scenes if s.name == an["scene"])
        length = float(lens.get(scene.name) or (an["keys"][-1]["t"] - an["start"] + 1))
        cues, info = build(scene, an, length)
        out[scene.name] = cues
        sys.stderr.write("%-24s %3d cues  tempo %d  %s  %.1f cuts/min\n" % (scene.name, len(cues), info["tempo"],
                                                                        "HIGH" if info["hot"] else "calm", info["cuts_per_min"]))
    sys.stdout.write("# Generated by tools/make_cues.py from the videos: colours at each cut, animation\n"
                     "# from the soundtrack's loudness and tempo. Regenerate rather than edit by hand.\n")
    sys.stdout.write(yaml.safe_dump(out, sort_keys=False, default_flow_style=None, width=200))


if __name__ == "__main__":
    main()
