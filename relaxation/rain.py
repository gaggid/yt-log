"""Animate the room scene with rain using Wan I2V (wan-2.2-i2v-a14b).

The rain clip is generated from the Qwen room image: only the rain and light shimmer
move; the room stays still. Saved as a media row (kind rl_rain). The clip is then
upscaled and looped by video.py to form the 3-hour final video."""
import base64
import math

from story3 import store as media
from story3.voice import MediaError

from . import models as M, store
from shorts import wan

# frames: I2V at 16fps, target ~9s → need ceil(9*16)=144, nearest 4n+1 = 145
_FRAMES = 4 * math.ceil((math.ceil(M.CLIP_S * M.I2V_FPS) - 1) / 4) + 1
_FRAMES = min(_FRAMES, M.I2V_MAX_FRAMES)   # hard cap

UPSCALE_LIMIT_S = 1800


def _rain_body(image_data: bytes, seed: int) -> dict:
    img_b64 = base64.b64encode(image_data).decode()
    return {
        "model": M.I2V_MODEL,
        "prompt": M.RAIN_MOTION,
        "negative_prompt": M.RAIN_NEGATIVE,
        "image": f"data:image/jpeg;base64,{img_b64}",
        "size": M.CLIP_SIZE,
        "num_frames": _FRAMES,
        "fps": M.I2V_FPS,
        "speed_lora": False,
        "steps": 10,
        "seed": seed,
        "response_format": "mp4",
    }


async def generate(session_id: str, s: dict | None = None, key: str = "", force: bool = False) -> dict:
    """Animate rain on the scene image. Requires the scene image to exist. Returns media row."""
    from story import settings as settings_mod
    s = s or settings_mod.get()
    api_key = key or settings_mod.api_key()
    base = s["base_url"].rstrip("/")

    if not force:
        existing = store.chosen(session_id, M.KIND_RAIN)
        if existing:
            return existing

    scene_item = store.chosen(session_id, M.KIND_SCENE)
    if not scene_item:
        raise MediaError("scene image not generated yet")

    img_path = media.path_of(scene_item)
    if not img_path.is_file():
        raise MediaError("scene image file missing")
    img_data = img_path.read_bytes()

    session = store.get(session_id)
    seed = int((session.get("settings") or {}).get("seed") or 7)
    body = _rain_body(img_data, seed)

    it = media.add(session_id, M.KIND_RAIN, "rain", 0, "running", {"frames": _FRAMES, "seed": seed})
    try:
        ans = await wan.submit(body, base, api_key, background=True)
        if ans.get("id") and ans.get("status") not in ("succeeded", "completed"):
            # store job id so a restart can resume
            media.update(it["id"], meta={"job_id": ans["id"], "frames": _FRAMES, "seed": seed})
            res = await wan.wait(ans["id"], base, api_key, limit_s=UPSCALE_LIMIT_S)
        else:
            res = wan._result(ans)

        clip_data = await wan.fetch(res, base, api_key)
        out_dir = media.media_dir(session_id, "rain")
        name = f"rain-a{it['attempt']}.mp4"
        (out_dir / name).write_bytes(clip_data)

        duration_s = _FRAMES / M.I2V_FPS
        return media.update(it["id"], status="done", file=f"rain/{name}",
                            meta={"frames": _FRAMES, "fps": M.I2V_FPS, "seed": seed,
                                  "duration_s": round(duration_s, 2)})
    except (wan.WanError, OSError) as e:
        media.update(it["id"], status="failed", meta={"error": str(e)[:300]})
        raise MediaError(f"rain clip failed: {e}") from e


async def upscale(session_id: str, s: dict | None = None, key: str = "", force: bool = False) -> dict:
    """Upscale the rain clip to 2K via the gateway's video-upscale endpoint.
    Returns the same media row updated with an `upscaled_file` meta key."""
    from story import settings as settings_mod
    s = s or settings_mod.get()
    api_key = key or settings_mod.api_key()
    base = s["base_url"].rstrip("/")

    rain_item = store.chosen(session_id, M.KIND_RAIN)
    if not rain_item:
        raise MediaError("rain clip not generated yet")

    # already upscaled?
    if not force and rain_item.get("meta", {}).get("upscaled_file"):
        return rain_item

    session = store.get(session_id)
    if (session.get("settings") or {}).get("upscale") != "2k":
        return rain_item   # upscale not requested

    clip_path = media.path_of(rain_item)
    if not clip_path.is_file():
        raise MediaError("rain clip file missing")

    body = {
        "model": "video-upscale",
        "video": wan.data_url(clip_path.read_bytes(), "video/mp4"),
        "resolution": "2k",
        "response_format": "mp4",
        "crf": 16,
    }
    try:
        clip_data, res = await wan.run(body, base, api_key, limit_s=UPSCALE_LIMIT_S, path="/video/upscale")
    except wan.WanError as e:
        raise MediaError(f"upscale failed: {e}") from e

    out_dir = media.media_dir(session_id, "rain")
    name = f"rain-a{rain_item['attempt']}-2k.mp4"
    (out_dir / name).write_bytes(clip_data)

    return media.update(rain_item["id"], meta={**rain_item["meta"], "upscaled_file": f"rain/{name}",
                                               "upscale_w": res.get("output_width"),
                                               "upscale_h": res.get("output_height")})
