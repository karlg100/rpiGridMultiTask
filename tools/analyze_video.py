"""Per-video analysis for lighting cues: keyframe cuts + colours, audio energy + tempo, contact sheet.
usage: analyze.py OUTDIR scenes.json INDEX..."""
import colorsys, json, math, os, re, subprocess, sys, array
ROOT = os.path.expanduser("~/videos")
W, H = 32, 18

def keyframes(path, start, end):
    cmd = ["ffmpeg", "-v", "info", "-nostats", "-skip_frame", "nokey"]
    if start: cmd += ["-ss", str(start)]
    cmd += ["-i", path, "-an", "-sn"]
    if end: cmd += ["-t", str(end - start)]
    cmd += ["-vf", "scale=%d:%d,showinfo" % (W, H), "-vsync", "vfr", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    p = subprocess.run(cmd, capture_output=True)
    times = [float(x) for x in re.findall(rb"pts_time:([0-9.]+)", p.stderr)]
    n = W * H * 3
    frames = [p.stdout[i:i + n] for i in range(0, len(p.stdout) - n + 1, n)]
    return [(start + t, f) for t, f in zip(times, frames)]

def colours(f):
    bins = {}
    tot = [0, 0, 0]; vs = 0.0
    for i in range(0, len(f), 3):
        r, g, b = f[i] / 255, f[i + 1] / 255, f[i + 2] / 255
        tot[0] += f[i]; tot[1] += f[i + 1]; tot[2] += f[i + 2]
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        vs += v
        if v < 0.2 or s < 0.25:
            continue
        k = int(h * 12) % 12
        w = s * v
        e = bins.setdefault(k, [0.0, 0.0, 0.0, 0.0])
        e[0] += w; e[1] += r * w; e[2] += g * w; e[3] += b * w
    n = len(f) // 3
    top = sorted(bins.items(), key=lambda kv: -kv[1][0])[:3]
    out = []
    for k, (w, r, g, b) in top:
        out.append({"rgb": "#%02x%02x%02x" % (int(255 * r / w), int(255 * g / w), int(255 * b / w)),
                    "share": round(w / n, 3)})
    mean = [round(c / n) for c in tot]
    return {"mean": "#%02x%02x%02x" % tuple(mean), "bright": round(vs / n, 3), "top": out}

def audio(path, start, end, rate=4000):
    cmd = ["ffmpeg", "-v", "error", "-nostats"]
    if start: cmd += ["-ss", str(start)]
    cmd += ["-i", path, "-vn"]
    if end: cmd += ["-t", str(end - start)]
    cmd += ["-ac", "1", "-ar", str(rate), "-f", "s16le", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    a = array.array("h"); a.frombytes(raw[: len(raw) // 2 * 2])
    hop = rate // 50                      # 20 ms
    env = []
    for i in range(0, len(a) - hop, hop):
        seg = a[i:i + hop]
        env.append(math.sqrt(sum(x * x for x in seg) / hop) / 32768)
    # loudness per 0.5 s
    rms = [round(20 * math.log10(max(1e-5, sum(env[i:i + 25]) / max(1, len(env[i:i + 25])))), 1)
           for i in range(0, len(env), 25)]
    # onset envelope and tempo by autocorrelation (60-180 bpm)
    on = [max(0.0, env[i] - env[i - 1]) for i in range(1, len(env))]
    def tempo(seg):
        if len(seg) < 200: return None
        m = sum(seg) / len(seg); seg = [x - m for x in seg]
        best, bl = 0, None
        for lag in range(17, 51):     # 50 fps: 17 = 176 bpm .. 50 = 60 bpm
            c = sum(seg[i] * seg[i + lag] for i in range(len(seg) - lag))
            if c > best: best, bl = c, lag
        return round(60 * 50 / bl) if bl else None
    tempos = [tempo(on[i:i + 50 * 20]) for i in range(0, len(on), 50 * 20)]   # per 20 s
    # onset density per 2 s (beats/hits)
    thr = sorted(on)[int(len(on) * 0.9)] if on else 0
    dens = [sum(1 for x in on[i:i + 100] if x > thr) for i in range(0, len(on), 100)]
    return {"rms_db_per_0.5s": rms, "tempo_per_20s": tempos, "onsets_per_2s": dens}

def sheet(path, start, end, n_key, out):
    step = max(1, math.ceil(n_key / 48))
    cmd = ["ffmpeg", "-v", "error", "-y", "-skip_frame", "nokey"]
    if start: cmd += ["-ss", str(start)]
    cmd += ["-i", path, "-an"]
    if end: cmd += ["-t", str(end - start)]
    cmd += ["-vf", "select='not(mod(n\\,%d))',scale=200:112,drawtext=text='%%{pts\\:hms}':x=4:y=4:fontsize=14:fontcolor=white:box=1:boxcolor=black@0.6,tile=6x8" % step,
            "-vsync", "vfr", "-frames:v", "1", "-q:v", "4", out]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode:   # no drawtext: plain
        cmd = [c.replace(",drawtext=text='%{pts\\:hms}':x=4:y=4:fontsize=14:fontcolor=white:box=1:boxcolor=black@0.6", "") for c in cmd]
        subprocess.run(cmd, capture_output=True)
    return step

outdir = sys.argv[1]; scenes = json.load(open(sys.argv[2]))
os.makedirs(outdir, exist_ok=True)
for idx in sys.argv[3:]:
    sc = [s for s in scenes if s["i"] == int(idx)][0]
    path = os.path.join(ROOT, sc["file"])
    end = sc.get("len_end")
    kf = keyframes(path, sc["start"], end)
    res = {"scene": sc["name"], "file": sc["file"], "start": sc["start"],
           "keys": [{"t": round(t, 2), **colours(f)} for t, f in kf]}
    res["audio"] = audio(path, sc["start"], end)
    res["sheet_step"] = sheet(path, sc["start"], end, len(kf), os.path.join(outdir, "sheet_%02d.jpg" % sc["i"]))
    json.dump(res, open(os.path.join(outdir, "scene_%02d.json" % sc["i"]), "w"))
    print(idx, sc["name"], len(kf), "keyframes", flush=True)
print("ALL DONE", flush=True)
