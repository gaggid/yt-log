"""Start pictures drawn by the image model (Qwen Image by default, any image model the gateway lists). Every shot has a `still`: the first frame of the shot written as a still picture by
the planner (the person can edit it). It is drawn 9:16, looked at by a person, and only then animated by Wan, so a wrong idea dies before the long wait. The character, the place and the
look the plan fixed are added by code, like in the Wan prompts."""
import base64

import httpx

from story2 import providers
from story3 import scenes
from story3.voice import MediaError

from . import cast, pipelines as P

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
    model = model_of(short)
    body = {"model": model, "prompt": prompt(short, shot), "size": SIZE, "n": 1, "seed": P.seed_for(short, shot, attempt), "response_format": "b64_json"}
    if providers.PROVIDERS.get(model, {}).get("negative_prompt"):          # FLUX runs with guidance and honours one; Qwen (cfg 1) ignores it, so only the sentence in the prompt counts
        body["negative_prompt"] = P.NEGATIVE
    return body


def _client(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout)


async def draw(body: dict, base: str, key: str) -> bytes:
    """One picture from the gateway's image endpoint (with the retries the scene pictures use). Returns the image bytes."""
    async with _client(float(providers.PROVIDERS.get(body["model"], {}).get("timeout_s", 300))) as client:
        img = await scenes._post(client, base.rstrip("/") + "/images/generations", key, json=body)
    if not img.get("b64_json"):
        raise MediaError("the image model sent no picture")
    return base64.b64decode(img["b64_json"])


def edit_prompt(short: dict, shot: dict, refs: dict) -> str:
    """The start picture of a shot with a cast: the pictures are named by position, the still describes the new frame, and the people keep their own faces, hair and clothes."""
    names = [f"Picture {i} shows {w[0]} ({w[1]})." for i, w in enumerate(refs["who"], 1)]
    if refs["place"]:
        names.append(f"Picture {len(refs['who']) + 1} shows the place.")
    plan = short["plan"]
    parts = [" ".join(names), "Create a new photograph:", (shot.get("still") or shot["prompt"]).strip()]
    if shot.get("setting"):
        parts.append(f"Setting: {shot['setting'].rstrip('. ')}.")
    elif not refs["place"] and plan.get("place"):
        parts.append(f"Setting: {plan['place'].rstrip('. ')}.")
    if shot.get("camera"):
        parts.append(f"Camera: {shot['camera'].rstrip('. ')}.")
    look = cast.look_text(short) or plan.get("look")
    if look:
        parts.append(look.rstrip(". ") + ".")
    parts.append("Every person keeps exactly the face, hair, skin tone, build and clothes of their own picture; if a place picture is given the scene happens there.")
    parts.append(KEEP_OUT)
    return " ".join(parts)[:3900]


def build(short: dict, shot: dict, attempt: int) -> dict:
    """{how, body, refs (paths), ref_ids, versions}: an edit from the cast's pictures when the shot has a cast member, else the plain text request."""
    refs = cast.refs_for(short, shot)
    if not refs:
        return {"how": "draw", "body": request(short, shot, attempt), "refs": [], "ref_ids": [], "versions": {}}
    body = {"model": model_of(short), "prompt": edit_prompt(short, shot, refs), "size": SIZE, "n": 1, "seed": P.seed_for(short, shot, attempt), "response_format": "b64_json"}
    return {"how": "edit", "body": body, "refs": refs["paths"], "ref_ids": refs["ids"], "versions": refs["versions"]}


def hash_of(req: dict) -> str:
    """What a start picture was made from: the request without the seed, the reference pictures and the characters' versions (a new canon makes the picture old)."""
    return P.req_hash({**req["body"], "refs": req["ref_ids"], "versions": req["versions"]})


async def send(req: dict, base: str, key: str) -> bytes:
    if req["how"] == "draw":
        return await draw(req["body"], base, key)
    async with _client(float(providers.PROVIDERS.get(req["body"]["model"], {}).get("timeout_s", 600))) as client:
        data, files = scenes._form(req["body"]["model"], req["body"]["prompt"], req["body"]["size"], req["body"]["seed"], req["refs"])
        img = await scenes._post(client, base.rstrip("/") + "/images/edits", key, data=data, files=files)
    if not img.get("b64_json"):
        raise MediaError("the image model sent no picture")
    return base64.b64decode(img["b64_json"])
