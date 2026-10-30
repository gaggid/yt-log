"""Start pictures drawn by the image model (Qwen Image by default, any image model the gateway lists). Every shot has a `still`: the first frame of the shot written as a still picture by
the planner (the person can edit it). It is drawn 9:16, looked at by a person, and only then animated by Wan, so a wrong idea dies before the long wait. The character, the place and the
look the plan fixed are added by code, like in the Wan prompts."""
import base64

import httpx

from story2 import providers
from story3 import scenes
from story3.voice import MediaError

from . import pipelines as P

SIZE = "720x1280"                         # 9:16, multiples of 16, well inside the image model's pixel budget; cropped to the video size when it is animated
DEFAULT_MODEL = providers.DEFAULT_MODEL
KEEP_OUT = "A single still photograph in a vertical 9:16 frame. No text, no letters, no numbers, no logo, no watermark, no subtitles, no collage, no split screen."


def model_of(short: dict) -> str:
    return short["settings"].get("image_model") or DEFAULT_MODEL


def prompt(short: dict, shot: dict) -> str:
    """The picture prompt: the person (when the shot shows them), the still, the place, the camera and the look, then what to keep out (this model has no negative prompt)."""
    plan = short["plan"]
    parts = []
    if shot.get("character") and plan.get("character"):
        parts.append(plan["character"].rstrip(". ") + ".")
    parts.append((shot.get("still") or shot["prompt"]).strip())
    setting = shot.get("setting") or plan.get("place")
    if setting:
        parts.append(f"Setting: {setting.rstrip('. ')}.")
    if shot.get("camera"):
        parts.append(f"Camera: {shot['camera'].rstrip('. ')}.")
    if plan.get("look"):
        parts.append(plan["look"].rstrip(". ") + ".")
    parts.append(KEEP_OUT)
    return " ".join(parts)[:3900]


def request(short: dict, shot: dict, attempt: int) -> dict:
    return {"model": model_of(short), "prompt": prompt(short, shot), "size": SIZE, "n": 1, "seed": P.seed_for(short, shot, attempt), "response_format": "b64_json"}


def _client(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout)


async def draw(body: dict, base: str, key: str) -> bytes:
    """One picture from the gateway's image endpoint (with the retries the scene pictures use). Returns the image bytes."""
    async with _client(float(providers.PROVIDERS.get(body["model"], {}).get("timeout_s", 300))) as client:
        img = await scenes._post(client, base.rstrip("/") + "/images/generations", key, json=body)
    if not img.get("b64_json"):
        raise MediaError("the image model sent no picture")
    return base64.b64decode(img["b64_json"])
