"""Small picture and video helpers for Shorts: the last frame of a clip, a picture cropped to 9:16, a clip cut to a window. ffmpeg comes from story3/video.py (the known install,
then the PATH)."""
import io
import re
import subprocess
from pathlib import Path

from PIL import Image

from story3 import video
from story3.voice import MediaError

from . import models


def run(args: list[str], cwd: Path | None = None) -> str:
    return video._run([video.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *args], cwd=cwd)


def info(path: Path) -> dict:
    return video.media_info(path)


def last_frame(mp4: Path, out: Path) -> Path:
    """The final picture of a clip, as a JPEG. Seeking from the end avoids counting frames."""
    out.parent.mkdir(parents=True, exist_ok=True)
    run(["-sseof", "-0.15", "-i", str(mp4), "-frames:v", "1", "-update", "1", "-q:v", "2", str(out)])
    if not out.is_file() or out.stat().st_size == 0:
        run(["-i", str(mp4), "-vf", "reverse", "-frames:v", "1", "-q:v", "2", str(out)])            # a very short clip: the first frame of the reversed clip
    if not out.is_file() or out.stat().st_size == 0:
        raise MediaError(f"could not read the last frame of {mp4.name}")
    return out


def crop_916(data: bytes, size: str = models.SIZE_PORTRAIT, quality: int = 92) -> bytes:
    """A picture cut to the shape of `size` (centre crop, no stretching) and scaled to it; JPEG bytes. Pictures the gateway takes are PNG, JPEG or WebP up to 12 MB."""
    w, h = models.size_of(size)
    try:
        im = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as e:  # noqa: BLE001
        raise MediaError(f"the picture cannot be read ({type(e).__name__})") from e
    want = w / h
    iw, ih = im.size
    if iw / ih > want:                                    # too wide: cut the sides
        nw = round(ih * want)
        im = im.crop(((iw - nw) // 2, 0, (iw - nw) // 2 + nw, ih))
    else:                                                 # too tall: cut top and bottom, a little more from the bottom
        nh = round(iw / want)
        top = (ih - nh) // 3
        im = im.crop((0, top, iw, top + nh))
    im = im.resize((w, h), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def scene_cuts(path: Path, threshold: float = 0.3, limit_s: float | None = None) -> list[float]:
    """Seconds at which the picture changes sharply (a cut), from ffmpeg's scene score; reads only the first `limit_s` seconds when given."""
    cut = ["-t", f"{limit_s:.0f}"] if limit_s else []
    r = subprocess.run([video.FFMPEG, "-hide_banner", *cut, "-i", str(path), "-vf", f"select='gt(scene,{threshold})',showinfo", "-an", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return [round(float(m.group(1)), 2) for m in re.finditer(r"pts_time:([\d.]+)", r.stderr)]


def long_stretches(cuts: list[float], length: float, limit: float = models.MAX_SHOT_S) -> list[tuple[float, float]]:
    """The stretches of a window of `length` seconds in which no cut falls for longer than `limit`: (start, end) pairs."""
    marks = [0.0, *sorted(c for c in cuts if 0 < c < length), length]
    return [(round(a, 2), round(b, 2)) for a, b in zip(marks, marks[1:]) if b - a > limit]
