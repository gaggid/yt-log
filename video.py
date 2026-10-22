"""Shot-based video assembly: per-shot camera move (zoompan) + xfade transitions, all native FFmpeg."""
import random
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageStat

import config

# Only slow, professional camera moves. Each move is (z, x, y) zoompan expressions.
# N = frames-1, `on` = output frame index. Source is upscaled to 3840x2160 first so slow motion stays smooth.
_AMT = 0.08                       # total zoom travel over a shot (8%)
_PAN = 1.08                       # fixed zoom while panning/tilting (8% travel)
_CX = "iw/2-(iw/zoom/2)"
_CY = "ih/2-(ih/zoom/2)"
MOVES = {
    "zoom_in":   (f"1+{_AMT}*on/N", _CX, _CY),
    "zoom_out":  (f"1+{_AMT}-{_AMT}*on/N", _CX, _CY),
    "pan_left":  (str(_PAN), "(iw-iw/zoom)*(1-on/N)", _CY),
    "pan_right": (str(_PAN), "(iw-iw/zoom)*on/N", _CY),
    "tilt_up":   (str(_PAN), _CX, "(ih-ih/zoom)*(1-on/N)"),
    "tilt_down": (str(_PAN), _CX, "(ih-ih/zoom)*on/N"),
}
# Slow push-in dominates (classic documentary look); the rest add gentle variety.
_WEIGHTS = {"zoom_in": 5, "zoom_out": 2, "pan_left": 1, "pan_right": 1, "tilt_up": 1, "tilt_down": 1}
TRANSITIONS = ["fade"]            # clean crossfade only


def pick_moves(n: int, camera: str, rng: random.Random) -> list[str]:
    if camera in MOVES:
        return [camera] * n
    out: list[str] = []
    names = list(_WEIGHTS)
    for _ in range(n):
        pool = [m for m in names if not out or m != out[-1]]
        out.append(rng.choices(pool, [_WEIGHTS[m] for m in pool])[0])
    return out


def _run(cmd: list) -> None:
    r = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({r.returncode}): {r.stderr[-1500:]}")


def _uniform(strip: Image.Image):
    """'white' / 'black' when a 1px strip is a flat frame colour, else None."""
    st = ImageStat.Stat(strip.convert("L"))
    if st.stddev[0] >= 12:
        return None
    return "white" if st.mean[0] > 228 else "black" if st.mean[0] < 22 else None


def trim_frame(src: Path, dst: Path, safe: float = 0.015) -> Path:
    """Crop off white/black comic frames and margins baked into a generated image, then re-crop to 16:9 plus a small
    safe margin, so zoom-out and pans never reveal a blank canvas."""
    im = Image.open(src).convert("RGB")
    W, H = im.size
    box = [0, 0, W, H]                                   # left, top, right, bottom
    for side in range(4):
        horiz = side in (0, 2)
        dim = W if horiz else H
        black = 0
        while (box[2] - box[0]) > W * 0.5 and (box[3] - box[1]) > H * 0.5:
            if side == 0:
                strip = im.crop((box[0], box[1], box[0] + 1, box[3]))
            elif side == 2:
                strip = im.crop((box[2] - 1, box[1], box[2], box[3]))
            elif side == 1:
                strip = im.crop((box[0], box[1], box[2], box[1] + 1))
            else:
                strip = im.crop((box[0], box[3] - 1, box[2], box[3]))
            kind = _uniform(strip)
            taken = (box[side] if side < 2 else dim - box[side])
            if kind == "white" and taken < dim * 0.30:
                pass
            elif kind == "black" and black < dim * 0.025:
                black += 1
            else:
                break
            box[side] += 1 if side < 2 else -1
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    x0, x1, y0, y1 = x0 + w * safe, x1 - w * safe, y0 + h * safe, y1 - h * safe
    w, h = x1 - x0, y1 - y0
    ratio = W / H
    if w / h > ratio:                                    # keep 16:9: shrink the longer side around the centre
        nw = h * ratio
        x0, x1 = x0 + (w - nw) / 2, x1 - (w - nw) / 2
    else:
        nh = w / ratio
        y0, y1 = y0 + (h - nh) / 2, y1 - (h - nh) / 2
    im.crop((round(x0), round(y0), round(x1), round(y1))).resize((W, H), Image.LANCZOS).save(dst)
    return dst


def _render_clip(img: Path, length: float, move: str, out: Path) -> None:
    img = trim_frame(img, out.with_suffix(".png"))
    frames = max(2, round(length * config.VIDEO_FPS))
    z, x, y = (e.replace("N", str(frames - 1)) for e in MOVES[move])
    vf = (f"scale=3840:2160:flags=lanczos,setsar=1,"
          f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={config.VIDEO_W}x{config.VIDEO_H}"
          f":fps={config.VIDEO_FPS},format=yuv420p")
    _run([config.FFMPEG, "-y", "-i", str(img), "-vf", vf, "-frames:v", str(frames),
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", str(out)])


def assemble(job_dir: Path, audio_paths: list, shots: list[dict], output: Path,
             camera: str = "auto", seed: str = "") -> dict:
    """shots: [{"image": Path, "dur": float}] in playback order; their durations must sum to the audio length."""
    rng = random.Random(seed)
    T = config.XFADE
    full_audio = job_dir / "audio.mp3"
    ac = job_dir / "audio_list.txt"
    ac.write_text("\n".join(f"file '{p.resolve().as_posix()}'" for p in audio_paths), encoding="utf-8")
    _run([config.FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(ac), "-c", "copy", str(full_audio)])

    n = len(shots)
    moves = pick_moves(n, camera, rng)
    clips_dir = job_dir / "clips"
    clips_dir.mkdir(exist_ok=True)
    clips = [clips_dir / f"clip_{i:03d}.mp4" for i in range(n)]
    # Every clip but the last carries T extra seconds that the next transition overlaps.
    lengths = [s["dur"] + (T if i < n - 1 else 0) for i, s in enumerate(shots)]
    with ThreadPoolExecutor(max_workers=3) as ex:
        list(ex.map(lambda i: _render_clip(shots[i]["image"], lengths[i], moves[i], clips[i]), range(n)))

    total = sum(s["dur"] for s in shots)
    trans = [rng.choice(TRANSITIONS) for _ in range(max(0, n - 1))]
    if n == 1:
        graph, last = "[0:v]null[vout]", "vout"
    else:
        parts, prev, offset = [], "0:v", 0.0
        for k in range(1, n):
            offset += shots[k - 1]["dur"]
            lab = "vout" if k == n - 1 else f"x{k}"
            parts.append(f"[{prev}][{k}:v]xfade=transition={trans[k-1]}:duration={T}:offset={offset:.3f}[{lab}]")
            prev = lab
        graph = ";".join(parts)
    gfile = job_dir / "filter.txt"
    gfile.write_text(graph, encoding="utf-8")

    cmd = [config.FFMPEG, "-y"]
    for c in clips:
        cmd += ["-i", str(c)]
    cmd += ["-i", str(full_audio), "-filter_complex_script", str(gfile),
            "-map", "[vout]", "-map", f"{n}:a",
            "-c:v", "libx264", "-preset", "medium", "-crf", "22", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-r", str(config.VIDEO_FPS), "-t", f"{total:.3f}", "-movflags", "+faststart", str(output)]
    _run(cmd)
    return {"shots": n, "moves": moves, "transitions": trans, "seconds": round(total, 1)}
