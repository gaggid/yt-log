"""How much a rain clip really moves. The rain is the only thing that should move, so a clip that is nearly a still picture
(a shimmer of brightness and a few thin streaks) is a failed clip, however good one frame looks.

Measured on real clips (832x480 / 1280x720, 49 to 81 frames): a good rain clip changes about 3 % of its pixels between
frames half a second apart (5 % at 832x480 and 1.7 % at 1280x720, where the streaks are finer, with dense rain in the picture and guidance 8; the picture itself looked right at both); the clip that "only flickered" changed 0.03 %. The numbers are kept on the clip's media row and
shown on the card, so a weak clip is seen before the long steps (audio, encode, upload) are spent on it."""
import glob
import shutil
import subprocess
import tempfile
from pathlib import Path

import config
from PIL import Image, ImageChops, ImageFilter, ImageStat

MAX_STREAK_SAME = 0.85       # share of the streak pattern that is still in the same place half a second later (see streak_same)
MIN_CHANGED_PCT = 1.0        # share of pixels that change (by more than 12 of 255) between two frames half a second apart


def _corr(a: list, b: list) -> float:
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = (sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)) ** 0.5
    return num / den if den else 1.0


def streak_same(frames: list, gap: int = 8) -> float:
    """How much of the rain-streak pattern is still where it was `gap` frames (half a second) earlier: the correlation of the fine detail
    (the picture minus its blur) in the upper half, where the rain is, averaged over the clip. Falling rain draws new streaks all the
    time, so this is low (0.3 to 0.6 in the best clips we made); streaks that only sit and shimmer stay at 0.9 and above. The pond and the
    stones shimmer in every clip, so the lower half is left out: counting them made a clip with fixed streaks look lively (3.8 % changed)."""
    w, h = frames[0].size
    box = (int(w * .12), int(h * .05), int(w * .88), int(h * .55))
    maps = []
    for f in frames:
        c = f.crop(box).resize(((box[2] - box[0]) // 3, (box[3] - box[1]) // 3))
        blur = c.filter(ImageFilter.GaussianBlur(2))
        maps.append([a - b for a, b in zip(c.getdata(), blur.getdata())])
    pairs = range(0, len(maps) - gap, max(1, (len(maps) - gap) // 6))
    return sum(_corr(maps[i], maps[i + gap]) for i in pairs) / len(pairs)


def measure(path: Path, width: int = 480) -> dict:
    """{frames, changed_pixels_pct, consecutive_avg, first_vs_last, brightness_drift}; {} when the file cannot be read."""
    tmp = Path(tempfile.mkdtemp(prefix="rlmotion_"))
    try:
        r = subprocess.run([config.FFMPEG, "-v", "error", "-y", "-i", str(path), "-vf", f"scale={width}:-1", str(tmp / "f_%03d.png")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        files = sorted(glob.glob(str(tmp / "f_*.png")))
        if r.returncode != 0 or len(files) < 10:
            return {}
        fr = [Image.open(f).convert("L") for f in files]

        def md(a, b):
            return ImageStat.Stat(ImageChops.difference(a, b)).mean[0]
        gap = 8                                                   # frames; half a second at 16 fps
        pcts = []
        for i in range(0, len(fr) - gap, max(1, (len(fr) - gap) // 6)):
            m = ImageChops.difference(fr[i], fr[i + gap]).point(lambda v: 255 if v > 12 else 0)
            pcts.append(100 * ImageStat.Stat(m).mean[0] / 255)
        means = [ImageStat.Stat(f).mean[0] for f in fr]
        return {"frames": len(fr),
                "changed_pixels_pct": round(sum(pcts) / len(pcts), 2),
                "consecutive_avg": round(sum(md(fr[i], fr[i + 1]) for i in range(len(fr) - 1)) / (len(fr) - 1), 2),
                "first_vs_last": round(md(fr[0], fr[-1]), 2),
                "brightness_drift": round(max(means) - min(means), 2),
                "streak_same": round(streak_same(fr), 2)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def weak(m: dict) -> bool:
    """A clip is weak when almost nothing changes, or when the streaks keep their places (rain that does not fall)."""
    return bool(m) and (m.get("changed_pixels_pct", 0) < MIN_CHANGED_PCT or m.get("streak_same", 0) > MAX_STREAK_SAME)
