"""The consistency check (C3): is this picture still the same person as the canon? The chat model with vision compares feature by feature against the canon pictures and the written slots,
with scoring anchors, because a single "same person?" number was too lenient in C0 (it gave 10 to a picture with a leaner face and curlier hair). The overall score is the mean of the
features minus a penalty for each feature that is clearly off, so one wrong feature cannot hide behind nine right ones. Clothes and background are allowed to change; hair colour, hair length
and facial hair are not unless the edit asked for it."""
import base64

import httpx

from story import llm, settings as settings_mod
from story3 import store as media
from story3.voice import MediaError

from . import requests as R, store

FEATURES = ("face_shape", "eyes_and_brows", "nose_and_mouth", "facial_hair", "hair", "skin_tone", "build", "age")
PASS_AT = 7.0                                            # below this the picture counts as drifted
ANCHORS = ("10 = indistinguishable from the reference, 8 = same person with a small difference you would only notice side by side, 6 = a visible difference (another hair length, a leaner or "
           "rounder face, a different beard density), 3 = looks like a relative, 0 = a different person")


def _client(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout)


def _b64(path) -> str:
    return base64.b64encode(open(path, "rb").read()).decode()


def prompt(char: dict, allowed: str = "") -> str:
    keys = ", ".join(f'"{k}": 0-10' for k in FEATURES)
    return ("You are a strict continuity supervisor for a film. The first pictures are the REFERENCE of one character (a face portrait, then the whole body). The LAST picture is a new picture that should "
            f"show the SAME character. Written description of the character: {R.identity_text(char)}\n"
            "Compare ONLY the person: face shape, eyes and brows, nose and mouth, facial hair, hair (colour, length, style), skin tone, build, apparent age. Ignore clothes, background, pose, light and "
            f"picture style. {('This change was asked for and is allowed: ' + allowed + '. ') if allowed else ''}Score each feature from 0 to 10. {ANCHORS}. Be harsh and specific. "
            f'Reply with JSON only: {{{keys}, "differences": ["short, concrete"]}}')


def overall(scores: dict[str, float]) -> float:
    vals = [max(0.0, min(10.0, float(scores.get(k, 0)))) for k in FEATURES]
    off = sum(1 for v in vals if v < 6)
    return round(max(0.0, sum(vals) / len(vals) - 1.0 * off), 1)


async def look(char: dict, item: dict, s: dict | None = None, key: str = "", allowed: str = "") -> dict:
    """Score one picture against the canon. Raises MediaError when there is no canon or the model server refuses."""
    s = s or settings_mod.get()
    canon = store.canon_items(char)
    if not canon.get("portrait"):
        raise MediaError("approve a portrait first: the check compares with it")
    pics = [canon["portrait"]] + ([canon["body"]] if canon.get("body") else [])
    content = [{"type": "text", "text": prompt(char, allowed)}] + [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + _b64(media.path_of(p))}} for p in pics] \
        + [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + _b64(media.path_of(item))}}]
    async with _client(300) as c:
        r = await c.post(s["base_url"].rstrip("/") + "/chat/completions", headers={"Authorization": f"Bearer {key or settings_mod.api_key()}"},
                         json={**llm.model_field(s), "messages": [{"role": "user", "content": content}], "max_tokens": 1500, "temperature": 0})
    if r.status_code != 200:
        raise MediaError(f"the check was refused ({r.status_code}): {r.text[:160]}")
    j = llm.parse_json(r.json()["choices"][0]["message"].get("content") or "")
    scores = {k: max(0.0, min(10.0, float(j.get(k, 0)))) for k in FEATURES}
    score = overall(scores)
    return {"features": scores, "score": score, "ok": score >= PASS_AT, "differences": [str(x) for x in (j.get("differences") or []) if str(x).strip().lower() not in ("none", "n/a")][:5],
            "version": char["version"]}
