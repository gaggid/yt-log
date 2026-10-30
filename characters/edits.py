"""Free edits of a character's pictures (C2): any picture of the character, an instruction (a preset with a value, or the person's own sentence, or a garment picture for a try-on), up to two
more reference pictures. Edits keep the look of their source picture, so no LoRA is sent (C0 finding). The request builder is here, next to requests.py, and is used by the studio, the
Shorts storyboard fix and the place-the-character step."""
import hashlib
import json

from PIL import Image

from story3 import store as media

from . import requests as R, store

KEEP_ID = "Keep exactly the same person: same face, same skin tone and same build."
# preset -> (instruction template with {v}, what must stay)
PRESETS: dict[str, tuple[str, str]] = {
    "outfit": ("Change only the clothes of the person to: {v}.", KEEP_ID + " Same hair. Keep the background and the pose."),
    "hair": ("Change only the hair to: {v}.", KEEP_ID + " Keep the clothes, the background and the pose."),
    "age": ("Make the same person look about {v} years old, aged naturally.", KEEP_ID + " Keep the background and the framing."),
    "expression": ("Change only the expression to {v}.", KEEP_ID + " Same hair. Keep the clothes, the background and the framing."),
    "pose": ("Change only the pose: {v}.", KEEP_ID + " Same hair. Keep the clothes and the background."),
    "lighting": ("Change only the lighting to {v}.", KEEP_ID + " Same hair. Keep the clothes, the pose and the background."),
    "time_of_day": ("Change only the time of day to {v}, with matching light and sky.", KEEP_ID + " Same hair. Keep the clothes and the pose."),
    "weather": ("Change only the weather to {v}.", KEEP_ID + " Same hair. Keep the clothes and the pose."),
    "background": ("Put the same person in this place: {v}.", KEEP_ID + " Same hair. Keep the same clothes and a natural pose."),
    "accessory": ("Add or change only this accessory: {v}.", KEEP_ID + " Same hair. Keep everything else."),
    "custom": ("{v}", KEEP_ID + " Same hair."),
}
GARMENT_SCOPES = {"outfit": "whole outfit", "top": "top (shirt, jacket, kurta)", "bottom": "trousers or lower garment", "footwear": "shoes", "headwear": "headwear", "accessory": "accessory"}
TRYON = ("Dress the person from the first picture in the {scope} shown in the second picture, exactly as it appears: same colours, fabric, pattern and cut. "
         "{replace} Do not copy the person who wears it in the second picture, only the clothing. " + KEEP_ID + " Same hair. Keep the background and the pose.")
WORN = ("The second picture shows a model wearing the clothing. Copy ONLY the clothing from it. Never copy the model's face, hair, skin tone, body, pose, hands, jewellery or the background; "
        "the person in the first picture keeps their own face, hair, body and pose. ")
FLATLAY = ("Show only the clothing worn by the person in this picture as a flat lay product photograph on a plain light grey surface: every garment laid flat and complete, exactly the same "
           "colours, fabric, pattern and cut. No person, no mannequin, no hands, no face, no skin, no background objects. No text, no logo.")
PLACE = ("The first picture shows the person's face and the second picture the whole body; the last picture is the place. Put the person into the place: {v}. "
         "Show the whole person naturally in the scene, with the light of the place on them. " + KEEP_ID + " Same hair. Keep the same clothes.")
MAX_EXTRA_REFS = 2


def snap(n: float) -> int:
    return max(256, int(round(n / 16)) * 16)


def size_of_picture(path) -> str:
    """The size an edit is asked for: the source picture's own, snapped to the model's multiple of 16 and kept inside about 1.5 megapixels."""
    with Image.open(path) as im:
        w, h = im.size
    f = min(1.0, (1_500_000 / (w * h)) ** 0.5)
    return f"{snap(w * f)}x{snap(h * f)}"


def edit_text(preset: str, value: str = "", garment_scope: str = "", has_garment: bool = False, worn: bool = False) -> str:
    if has_garment:
        scope = GARMENT_SCOPES.get(garment_scope or "outfit", GARMENT_SCOPES["outfit"])
        replace = "Replace the old clothes completely." if (garment_scope or "outfit") == "outfit" else "Keep the other clothes."
        text = TRYON.replace("{scope}", scope).replace("{replace}", replace)
        if worn:                                                           # the garment photo has a person in it: say again that only the clothing may move across
            text = text.replace("Do not copy the person who wears it in the second picture, only the clothing. ", WORN)
        return (text + (" " + value.strip() if value.strip() else "") + " " + R.NO_TEXT)[:3900]
    if preset not in PRESETS:
        raise store.CharError(f"unknown edit '{preset}' (one of: {', '.join(PRESETS)})")
    if not value.strip():
        raise store.CharError("say what the edit should do")
    template, keep = PRESETS[preset]
    return (template.replace("{v}", value.strip().rstrip(".")) + " " + keep + " " + R.NO_TEXT)[:3900]


def _meta(char: dict, body: dict, base: dict, ref_ids: list[str], op: str, preset: str, value: str, extra_meta: dict | None = None) -> dict:
    depth = int(base["meta"].get("depth", 0)) + 1 if base["kind"] == store.EDIT else 1
    meta = {"view": "edit", "how": "edit", "op": op, "preset": preset, "value": value, "parent": base["id"], "depth": depth, "refs": ref_ids, "model": body["model"], "seed": body["seed"],
            "prompt": body["prompt"][:1500], "loras": [], "identity_hash": store.identity_hash(char), "version": char["version"], "style": char["render"]["style"], "size": body["size"],
            **(extra_meta or {})}
    stable = {k: v for k, v in meta.items() if k not in ("seed", "prompt")}
    meta["input_hash"] = hashlib.sha1(json.dumps({**stable, "prompt": body["prompt"]}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
    return meta


def build(char: dict, base: dict, preset: str, value: str, attempt: int, extra: list[dict] | None = None, garment_path=None, garment_scope: str = "", seed: int | None = None,
          override: str = "", extra_meta: dict | None = None, garment_worn: bool = False) -> dict:
    """An edit of one picture (`base` is a finished media row). `extra` are more pictures of the character or the place (up to two); `garment_path` is a clothes picture for a try-on."""
    extra = (extra or [])[:MAX_EXTRA_REFS]
    refs = [media.path_of(base)] + [media.path_of(x) for x in extra]
    ref_ids = [base["id"]] + [x["id"] for x in extra]
    if garment_path:
        refs, ref_ids = [refs[0], garment_path], [ref_ids[0], "garment"]
    prompt = override.strip() or edit_text(preset, value, garment_scope, bool(garment_path), garment_worn)
    if extra and not garment_path and not override.strip():
        prompt = "The first picture is the one to edit; the other pictures are references for the same person or place. " + prompt
    seed = seed if seed is not None else R.seed_for(char["id"], "edit", attempt)
    body = {"model": char["render"]["model"], "size": size_of_picture(refs[0]), "n": 1, "seed": seed, "response_format": "b64_json", "prompt": prompt}
    meta = _meta(char, body, base, ref_ids, "tryon" if garment_path else "edit", preset, value, {"garment_scope": garment_scope, "garment_worn": garment_worn, **(extra_meta or {})} if garment_path else extra_meta)
    return {"how": "edit", "body": body, "refs": refs, "ref_ids": ref_ids, "meta": meta}


def build_place(char: dict, place: dict, action: str, attempt: int, base: dict | None = None, seed: int | None = None, override: str = "") -> dict:
    """The character in a place (C0: three references hold the face): references are the canon portrait, the canon body (or `base`, a look) and the place picture."""
    canon = store.canon_items(char)
    if "portrait" not in canon or "body" not in canon:
        raise store.CharError("approve a portrait and a full-body picture first")
    body_pic = base or canon["body"]
    refs = [media.path_of(canon["portrait"]), media.path_of(body_pic), media.path_of(place)]
    ref_ids = [canon["portrait"]["id"], body_pic["id"], place["id"]]
    prompt = override.strip() or (PLACE.replace("{v}", (action.strip().rstrip(".") or "standing naturally, looking at the camera")) + " " + R.NO_TEXT)
    seed = seed if seed is not None else R.seed_for(char["id"], "place", attempt)
    body = {"model": char["render"]["model"], "size": "720x1280", "n": 1, "seed": seed, "response_format": "b64_json", "prompt": prompt}
    meta = _meta(char, body, body_pic, ref_ids, "place", "place", action, {"place": place["plan_id"], "place_item": place["id"]})
    return {"how": "edit", "body": body, "refs": refs, "ref_ids": ref_ids, "meta": meta}
