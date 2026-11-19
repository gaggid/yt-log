"""Generate the room scene image with Qwen Image 2.1.

One 1280x720 (16:9 landscape) image per session. Saved as a media row (kind rl_scene).
The image is the first frame passed to Wan for the rain animation."""
import base64

import httpx

from story import settings as settings_mod
from story3 import store as media
from story3.voice import MediaError

from . import models as M, store

TIMEOUT_S = 900          # 2048x1152 at 35 steps takes about 2.5 times as long as 1280x720
_NO_SEED = None     # None = omit seed from request (gateway picks randomly)


def _client(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout)


def _body(s: dict, scene: str, seed: int) -> dict:
    """The request for the scene picture. `s` is the session's settings: its `scene_prompt` (written for this video by relaxation/director.py from the light, lamp,
    season, air, camera and grade picked for it) wins over the theme's fixed prompt, so two videos of one theme never draw the same picture."""
    cfg = M.SCENES.get(scene) or M.SCENES[M.DEFAULT_SCENE]
    body: dict = {
        "model": s.get("image_model") or M.IMAGE_MODEL,
        "prompt": s.get("scene_prompt") or cfg["prompt"],
        "size": M.IMAGE_SIZE,
        "n": 1,
        "steps": M.IMAGE_STEPS,
        "response_format": "b64_json",
    }
    loras = [x for x in (s.get("image_loras") or M.IMAGE_LORAS) if x.get("name")]
    if loras:
        body["lora"] = {x["name"]: float(x.get("strength", 0.7)) for x in loras}
        trig = " ".join(dict.fromkeys(M.LORA_TRIGGERS[x["name"]] for x in loras if x["name"] in M.LORA_TRIGGERS))
        if trig:
            body["prompt"] = f"{trig}. {body['prompt']}"
    if seed:
        body["seed"] = seed
    return body


async def generate(session_id: str, s: dict | None = None, key: str = "", force: bool = False) -> dict:
    """Draw the room scene image. Returns the media row. Raises MediaError on failure."""
    s = s or settings_mod.get()
    api_key = key or settings_mod.api_key()
    base = s["base_url"].rstrip("/")

    session = store.get(session_id)
    settings = session.get("settings") or {}

    if not force:
        existing = store.chosen(session_id, M.KIND_SCENE)
        if existing:
            return existing

    seed = int(settings.get("seed") or 7)
    scene = settings.get("scene") or M.DEFAULT_SCENE
    body = _body(settings, scene, seed)

    it = media.add(session_id, M.KIND_SCENE, "scene", 0, "running", {"scene": scene, "seed": seed, "look": settings.get("look") or {}})
    try:
        async with _client(TIMEOUT_S) as c:
            r = await c.post(
                base + "/images/generations",
                json=body,
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if r.status_code != 200:
            raise MediaError(f"image gateway returned {r.status_code}: {r.text[:200]}")
        b64 = r.json()["data"][0]["b64_json"]
        img_bytes = base64.b64decode(b64)

        out_dir = media.media_dir(session_id, "scene")
        name = f"scene-a{it['attempt']}.jpg"
        (out_dir / name).write_bytes(img_bytes)

        return media.update(it["id"], status="done", file=f"scene/{name}",
                            meta={"scene": scene, "seed": seed, "size": M.IMAGE_SIZE})
    except (httpx.HTTPError, OSError, KeyError) as e:
        media.update(it["id"], status="failed", meta={"error": str(e)[:300]})
        raise MediaError(f"scene image failed: {e}") from e
