"""Animate the room scene with rain using Wan I2V (wan-2.2-i2v-a14b).

The rain clip is generated from the Qwen room image: only the rain and light shimmer
move; the room stays still. Saved as a media row (kind rl_rain). The clip is then
upscaled and looped by video.py to form the 3-hour final video."""
import base64
import math

from story3 import store as media
from story3.voice import MediaError

import asyncio

from . import models as M, motion, store
from shorts import wan

# frames: I2V at 16 fps, CLIP_S seconds, rounded up to 4n+1 (3 s -> 49)
_FRAMES = 4 * math.ceil((math.ceil(M.CLIP_S * M.I2V_FPS) - 1) / 4) + 1
_FRAMES = min(_FRAMES, M.I2V_MAX_FRAMES)   # hard cap

UPSCALE_LIMIT_S = 1800
# The rain clip is a 14B image-to-video job at 720p: the estimate alone is about 33 minutes, so
# wait for twice the estimate (never less than the gateway's usual one hour).
RAIN_LIMIT_S = max(wan.JOB_LIMIT_S, 2 * M.estimate_rain_s(_FRAMES))
# A resumed job that is gone or failed on the gateway starts a new one; any other error is final.
_GONE = ("no longer has this job", "video job ")


async def _resume_previous(session_id: str, seed: int, base: str, api_key: str) -> tuple[dict, bytes, dict] | None:
    """The last rain attempt was sent to the gateway but never collected (the wait ran out or the app stopped):
    if the gateway still has that job for the same frames and seed, take its result instead of making a new one."""
    prev = media.items(session_id, M.KIND_RAIN, "rain")
    if not prev:
        return None
    it = prev[-1]
    meta = it["meta"]
    if it["status"] == "done" or not meta.get("job_id") or meta.get("frames") != _FRAMES or meta.get("seed") != seed:
        return None
    media.update(it["id"], status="running", meta={"error": "", "resumed": True})
    try:
        data, res = await wan.resume(meta["job_id"], base, api_key, limit_s=RAIN_LIMIT_S)
    except wan.WanError as e:
        if any(g in str(e) for g in _GONE):
            media.update(it["id"], status="failed", meta={"error": f"could not be picked up again: {e}"[:300]})
            return None
        media.update(it["id"], status="failed", meta={"error": str(e)[:300]})
        raise MediaError(f"rain clip failed: {e}") from e
    return it, data, res


def _rain_body(image_data: bytes, seed: int, scene: str = "", guidance: float = M.RAIN_GUIDANCE) -> dict:
    img_b64 = base64.b64encode(image_data).decode()
    return {
        "model": M.I2V_MODEL,
        "prompt": M.rain_motion(scene),
        "negative_prompt": M.RAIN_NEGATIVE,
        "image": f"data:image/jpeg;base64,{img_b64}",
        "end_image": f"data:image/jpeg;base64,{img_b64}",   # first = last frame: the clip loops without a jump
        "size": M.CLIP_SIZE,
        "num_frames": _FRAMES,
        "fps": M.I2V_FPS,
        "speed_lora": False,
        "steps": 10,
        "guidance": guidance,
        "guidance_low": guidance,
        "seed": seed,
        "response_format": "mp4",
    }


async def _clip(session_id: str, img_data: bytes, seed: int, scene: str, base: str, api_key: str, guidance: float, resume: bool) -> dict:
    """One rain clip (one gateway job); a job the gateway still has for the same frames and seed is picked up instead of repeated."""
    body = _rain_body(img_data, seed, scene, guidance)
    resumed = await _resume_previous(session_id, seed, base, api_key) if resume else None
    if resumed:
        it, clip_data, res = resumed
    else:
        it = media.add(session_id, M.KIND_RAIN, "rain", 0, "running", {"frames": _FRAMES, "seed": seed, "guidance": guidance})
    try:
        if not resumed:
            ans = await wan.submit(body, base, api_key, background=True)
            if ans.get("id") and ans.get("status") not in ("succeeded", "completed"):
                # store job id so a retry or a restart can resume
                media.update(it["id"], meta={"job_id": ans["id"], "frames": _FRAMES, "seed": seed})
                res = await wan.wait(ans["id"], base, api_key, limit_s=RAIN_LIMIT_S)
            else:
                res = wan._result(ans)
            clip_data = await wan.fetch(res, base, api_key)
        out_dir = media.media_dir(session_id, "rain")
        name = f"rain-a{it['attempt']}.mp4"
        (out_dir / name).write_bytes(clip_data)

        duration_s = _FRAMES / M.I2V_FPS
        row = media.update(it["id"], status="done", file=f"rain/{name}",
                           meta={"frames": _FRAMES, "fps": M.I2V_FPS, "seed": seed, "guidance": guidance, "duration_s": round(duration_s, 2)})
    except (wan.WanError, OSError) as e:
        media.update(it["id"], status="failed", meta={"error": str(e)[:300]})
        raise MediaError(f"rain clip failed: {e}") from e
    m = await asyncio.to_thread(motion.measure, media.path_of(row))      # how much of the picture really moves
    return media.update(row["id"], meta={"motion": m})


async def generate_code(session_id: str, s: dict | None = None, key: str = "", force: bool = False) -> dict:
    """The rain, drawn by code over the scene picture (relaxation/rainfx.py): the vision model finds the window and the surfaces
    (relaxation/zones.py), then a 5 second loop is drawn at 4K. About a minute, no GPU. Returns the media row (rl_rain, meta.engine = "code")."""
    from story import llm, settings as settings_mod
    from . import rainfx, zones
    s = s or settings_mod.get()
    api_key = key or settings_mod.api_key()
    if not force:
        existing = store.chosen(session_id, M.KIND_RAIN)
        if existing:
            return existing
    scene_item = store.chosen(session_id, M.KIND_SCENE)
    if not scene_item:
        raise MediaError("scene image not generated yet")
    pic = media.path_of(scene_item)
    if not pic.is_file():
        raise MediaError("scene image file missing")
    st = store.get(session_id).get("settings") or {}
    seed = int(st.get("seed") or 7)
    flame = bool(st["flame"]) if "flame" in st else bool((M.SCENES.get(st.get("scene") or "") or {}).get("flame"))     # the lamp of THIS picture (director.py) burns or does not
    w, h = M.OUT_4K
    it = media.add(session_id, M.KIND_RAIN, "rain", 0, "running", {"engine": "code", "seed": seed})
    try:
        z = await zones.find(pic, llm.ChatBackend(s, api_key), s)
        media.update(it["id"], meta={"zones": z})
        name = f"rain-a{it['attempt']}.mp4"
        out = media.media_dir(session_id, "rain") / name
        await asyncio.to_thread(rainfx.render, pic, z, out, (w, h), seed, rainfx.LOOP_S, flame)         # PIL work: off the event loop
        return media.update(it["id"], status="done", file=f"rain/{name}",
                            meta={"engine": "code", "seamless": True, "w": w, "h": h, "fps": rainfx.FPS, "loop_s": rainfx.LOOP_S, "seed": seed,
                                  "zones": z, "flame": flame, "duration_s": rainfx.LOOP_S})
    except (RuntimeError, OSError) as e:
        media.update(it["id"], status="failed", meta={"error": str(e)[:300]})
        raise MediaError(f"rain drawing failed: {e}") from e


def engine(session_id: str) -> str:
    """"code" (drawn over the picture) or "wan"; a session made before the code engine has no key and stays on Wan."""
    return (store.get(session_id).get("settings") or {}).get("rain_engine") or "wan"


async def generate(session_id: str, s: dict | None = None, key: str = "", force: bool = False) -> dict:
    """Make the rain for the scene picture: drawn by code (default for new sessions) or, for older sessions, a Wan clip.
    Wan: a clip that barely moves (relaxation/motion.py) is made once more with another seed and a higher guidance; the clip that moves more is kept."""
    if engine(session_id) == "code":
        return await generate_code(session_id, s, key, force)
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

    st = store.get(session_id).get("settings") or {}
    seed = int(st.get("seed") or 7)
    scene = st.get("scene") or ""
    row = await _clip(session_id, img_data, seed, scene, base, api_key, M.RAIN_GUIDANCE, resume=not force)
    if motion.weak(row["meta"].get("motion") or {}) and st.get("rain_retry", True):
        again = await _clip(session_id, img_data, seed + 1, scene, base, api_key, M.RAIN_GUIDANCE_RETRY, resume=False)
        pct = lambda r: (r["meta"].get("motion") or {}).get("changed_pixels_pct", 0)
        better, worse = (again, row) if pct(again) > pct(row) else (row, again)
        media.update(worse["id"], status="failed", meta={"error": "less rain movement than the other attempt"})
        row = media.get(better["id"])
    return row


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
