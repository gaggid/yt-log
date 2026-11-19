"""Assemble the 3-hour relaxation video.

The upscaled rain clip is looped with ffmpeg stream_loop for the target duration,
the mixed audio is embedded, and the result is encoded to H.264/AAC at 1920x1080
(or 2560x1440 when upscaled) suitable for YouTube upload.

Output: data/media/{session_id}/final/final-a{n}.mp4
"""
import hashlib
import json
import subprocess
from pathlib import Path

import config
from story3 import store as media
from story3.voice import MediaError

from . import models as M, store

VERSION = "v1"      # bump when encoding settings change


def _ffmpeg(args: list[str], cwd: Path | None = None) -> None:
    r = subprocess.run(
        [config.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *args],
        capture_output=True, text=True, cwd=cwd, encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        last = (r.stderr or r.stdout).strip().splitlines()
        raise RuntimeError((last[-1] if last else str(r.returncode))[:240])


def _out_size(upscaled: bool) -> tuple[int, int]:
    return (2560, 1440) if upscaled else (M.OUT_W, M.OUT_H)


def _input_hash(rain_item: dict, audio_item: dict, total_s: float, upscaled: bool) -> str:
    return hashlib.sha1(
        json.dumps([VERSION, rain_item["id"], audio_item["id"],
                    round(total_s), upscaled], sort_keys=True).encode()
    ).hexdigest()[:12]


async def make(session_id: str, s: dict | None = None, key: str = "",
               progress=None, force: bool = False) -> dict:
    """Assemble the final 3-hour MP4. Returns a media row (rl_final)."""
    rain_item = store.chosen(session_id, M.KIND_RAIN)
    if not rain_item:
        raise MediaError("rain clip not ready")
    audio_item = store.chosen(session_id, M.KIND_AUDIO)
    if not audio_item:
        raise MediaError("audio mix not ready")

    session = store.get(session_id)
    settings = session.get("settings") or {}
    total_s = M.total_s(settings)

    # prefer the upscaled file if available
    upscaled_file = rain_item.get("meta", {}).get("upscaled_file")
    if upscaled_file:
        rain_path = media.media_dir(session_id) / upscaled_file
        if not rain_path.is_file():
            upscaled_file = None   # file somehow missing; fall back
    if not upscaled_file:
        rain_path = media.path_of(rain_item)
    upscaled = bool(upscaled_file)

    audio_path = media.path_of(audio_item)
    if not rain_path.is_file():
        raise MediaError("rain clip file missing")
    if not audio_path.is_file():
        raise MediaError("audio file missing")

    h = _input_hash(rain_item, audio_item, total_s, upscaled)
    if not force:
        for it in media.items(session_id, M.KIND_FINAL, "final"):
            if it["status"] == "done" and it["file"] and it["meta"].get("input_hash") == h:
                return it

    w, h_px = _out_size(upscaled)
    it = media.add(session_id, M.KIND_FINAL, "final", 0, "running", {"input_hash": h})
    out_dir = media.media_dir(session_id, "final")
    name = f"final-a{it['attempt']}.mp4"
    out_path = out_dir / name

    try:
        if progress:
            progress(0, 1, f"encoding {M.duration_label(settings)} loop ({w}x{h_px})")

        # scale/pad rain clip to exact output size, loop it, embed audio, normalise loudness
        # stream_loop -1 = infinite loop; -t trims to exact duration
        vf = (
            f"scale={w}:{h_px}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={w}:{h_px},setsar=1,format=yuv420p"
        )
        _ffmpeg([
            "-stream_loop", "-1", "-i", str(rain_path),
            "-i", str(audio_path),
            "-t", f"{total_s:.2f}",
            "-vf", vf,
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-pix_fmt", "yuv420p", "-r", str(M.OUT_FPS),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-shortest",
            "-movflags", "+faststart",
            str(out_path),
        ])

        size_mb = out_path.stat().st_size / (1024 * 1024)
        if progress:
            progress(1, 1, f"done — {size_mb:.0f} MB")

        return media.update(it["id"], status="done", file=f"final/{name}",
                            meta={"input_hash": h, "total_s": total_s,
                                  "size_mb": round(size_mb, 1), "w": w, "h": h_px,
                                  "upscaled": upscaled})
    except (RuntimeError, OSError) as e:
        media.update(it["id"], status="failed", meta={"error": str(e)[:300]})
        raise MediaError(f"video assembly failed: {e}") from e


def remux(session_id: str) -> dict:
    """Replace the sound of the finished video with the current audio mix, copying the picture as it is (no re-encode).
    Makes a new rl_final attempt; the earlier one stays on disk until the storage page clears it."""
    final = store.chosen(session_id, M.KIND_FINAL)
    audio_item = store.chosen(session_id, M.KIND_AUDIO)
    rain_item = store.chosen(session_id, M.KIND_RAIN)
    if not (final and audio_item and rain_item):
        raise MediaError("the video or its sound is not ready")
    src, snd = media.path_of(final), media.path_of(audio_item)
    if not src.is_file() or not snd.is_file():
        raise MediaError("the video or audio file is missing")
    meta = dict(final["meta"])
    it = media.add(session_id, M.KIND_FINAL, "final", 0, "running", {"remux_of": final["id"]})
    name = f"final-a{it['attempt']}.mp4"
    out = media.media_dir(session_id, "final") / name
    try:
        _ffmpeg(["-i", str(src), "-i", str(snd), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                 "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(out)])
        total_s = float(meta.get("total_s") or audio_item["meta"].get("total_s") or 0)
        h = _input_hash(rain_item, audio_item, total_s, bool(meta.get("upscaled")))
        return media.update(it["id"], status="done", file=f"final/{name}",
                            meta={**meta, "input_hash": h, "size_mb": round(out.stat().st_size / (1024 * 1024), 1), "remux_of": final["id"]})
    except (RuntimeError, OSError) as e:
        media.update(it["id"], status="failed", meta={"error": str(e)[:300]})
        raise MediaError(f"putting the new sound into the video failed: {e}") from e
