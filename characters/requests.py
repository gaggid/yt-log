"""The one place that builds image requests for the studio (like shorts/pipelines.py for Wan): the prompt for each view, the gateway body, the reference pictures of an edit, and the hash of
the recipe. Prompt order follows the research notes (docs/PLAN_characters.md 13): the view and subject first, then the one fixed identity paragraph, then the render look, then what to
keep out. Qwen runs at cfg 1 on this gateway, so exclusions are plain sentences; FLUX honours a negative prompt and gets one."""
import hashlib
import json
import re
import zlib

from story2 import describe, providers
from story3 import store as media

from . import render, store

NO_TEXT = "No text, letters, numbers, logo, watermark or subtitles. A single picture, no collage, no split screen."
KEEP = "Keep exactly the same person: same face, same hair, same skin tone, same build and the same clothes. Keep the plain studio background and the framing."
NEGATIVE = "blurry, low quality, deformed, disfigured, extra fingers, poorly drawn hands, jpeg artifacts, text, watermark, logo, collage"

# view -> how it is made ("draw" from text, "edit" from the canon pictures), size, the frame text (draw) or the instruction (edit), and which canon views it is edited from
VIEWS: dict[str, dict] = {
    "portrait": {"how": "draw", "size": "1024x1024", "kind": "person", "label": "Portrait (head and shoulders)",
                 "frame": "Head and shoulders portrait, facing the camera, plain soft grey studio background."},
    "body": {"how": "draw", "size": "720x1280", "kind": "person", "label": "Full body, front",
             "frame": "Full body standing front view, whole figure visible from head to feet, relaxed natural pose, plain soft grey studio background."},
    "place": {"how": "draw", "size": "1280x720", "kind": "place", "label": "Establishing view",
              "frame": "An establishing view that shows the layout, materials, light and typical objects of the place clearly, empty of people."},
    "three_quarter": {"how": "edit", "size": "720x1280", "kind": "person", "label": "Three-quarter view", "refs": ("portrait", "body"),
                      "instruction": "Show the same person standing in a three-quarter view, turned about 45 degrees to the left, whole body visible from head to feet."},
    "side": {"how": "edit", "size": "720x1280", "kind": "person", "label": "Side view (profile)", "refs": ("portrait", "body"),
             "instruction": "Show the same person standing in a side view, in profile facing left, whole body visible from head to feet."},
    "back": {"how": "edit", "size": "720x1280", "kind": "person", "label": "Back view", "refs": ("portrait", "body"),
             "instruction": "Show the same person standing seen from behind, back to the camera, whole body visible from head to feet."},
}
EXPRESSIONS = {"smile": "a warm natural smile", "laugh": "a wide, genuine laugh", "angry": "an angry, tense expression", "worried": "a worried, anxious expression",
               "surprised": "a surprised expression with raised eyebrows", "sad": "a quiet, sad expression"}
for _k, _t in EXPRESSIONS.items():
    VIEWS["expr_" + _k] = {"how": "edit", "size": "1024x1024", "kind": "person", "label": "Expression: " + _k, "refs": ("portrait",),
                           "instruction": f"Change only the expression to {_t}. Same head and shoulders framing."}
SHEET_VIEWS = ("three_quarter", "side", "back", *("expr_" + k for k in EXPRESSIONS))


def seed_for(char_id: str, view: str, attempt: int) -> int:
    return (zlib.crc32(f"{char_id}:{view}".encode()) + 101 * (attempt - 1)) % (2 ** 32)


STEPS = {"qwen-image-2.1": 35}                   # owner decision 2026-10-30: character pictures run at 35 steps on Qwen (faces and eyes come out cleaner than at the gateway default)
HEAD_VIEWS = ("portrait",)                       # views whose frame ends at the shoulders: legs, feet, wrists and hands are not in it
_BELOW = re.compile(r"\b(wrists?|hands?|fingers?|bangles?|bracelets?|rings?|watch(?:es)?|belts?|anklets?|toe|shoes?|sandals?|heels?|waist)\b", re.I)
_LONG = re.compile(r"\b(?:waist|hip|knee|thigh|floor)[- ]length\b", re.I)


def visible_slots(slots: dict, view: str | None) -> tuple[dict, set[str]]:
    """What the picture for `view` can show. The image model draws every word it is given, so a head-and-shoulders portrait that is told about flats and trousers tries to fit them in and
    the face comes out morphed: trousers, footwear, jewellery of the wrists and hands and hair length beyond the shoulders are left out of those views (they stay in the full-body views)."""
    if view not in HEAD_VIEWS and not (view or "").startswith("expr_"):
        return slots, set()
    s = dict(slots)
    if s.get("accessories"):
        keep = [c for c in re.split(r",| and ", s["accessories"]) if c.strip() and not _BELOW.search(c)]
        s["accessories"] = ", ".join(x.strip() for x in keep)
    if s.get("hair"):
        s["hair"] = _LONG.sub("long", s["hair"])
    return s, set(describe.LOWER)


def identity_text(char: dict, view: str | None = None) -> str:
    """The one fixed paragraph about the subject, composed from the slots (for a head-and-shoulders view only the part the frame shows); an empty ethnicity slot of a person means Indian."""
    slots = dict(char["slots"])
    if char["kind"] == "person" and not slots.get("ethnicity"):
        slots["ethnicity"] = "Indian"
    slots, hide = visible_slots(slots, view) if char["kind"] == "person" else (slots, set())
    text = describe.describe(char["kind"], slots, hide)
    region = (char.get("declared") or {}).get("ethnicity")
    return f"A location in {region}. {text}" if char["kind"] == "place" and region else text


def draw_prompt(char: dict, view: str, listing: dict | None = None) -> str:
    r = char["render"]
    trig = render.trigger_words(r, listing)
    parts = [trig, VIEWS[view]["frame"], identity_text(char, view), render.look(r), NO_TEXT]
    if char.get("personality") and char["kind"] == "person":
        parts.insert(3, f"Mood: {char['personality'].rstrip('. ')}.")
    return " ".join(p for p in parts if p)[:3900]


def edit_prompt(char: dict, view: str, extra: str = "") -> str:
    """An instruction naming the reference pictures by position (the model card's pattern), with the keep list."""
    v = VIEWS[view]
    refs = v.get("refs", ())
    lead = (f"The first picture shows the person's face and the second picture the whole body. " if len(refs) == 2 else "")
    return " ".join(p for p in (lead + v["instruction"], KEEP, extra.strip(), NO_TEXT) if p)[:3900]


def _loras(r: dict):
    return [{"name": x["name"], "strength": x["strength"]} for x in r["loras"]] or None


def photo_prompt(char: dict) -> str:
    """First portrait of a character made from a picture of a person: redraw that person in the chosen render style."""
    return (f"Redraw the person in the picture as a head and shoulders portrait facing the camera on a plain soft grey studio background, in this style: {render.look(char['render'])} "
            "Keep exactly the same face, hair, skin tone and age. " + NO_TEXT)


def build(char: dict, view: str, attempt: int, listing: dict | None = None, seed: int | None = None, extra: str = "") -> dict:
    """{how, body, refs (pictures to send, in order), ref_ids, meta}. `refs` are paths of the canon (or the source photo); the request is refused when a canon picture is missing."""
    if view not in VIEWS:
        raise store.CharError(f"unknown view '{view}'")
    v = VIEWS[view]
    if v["kind"] != char["kind"]:
        raise store.CharError(f"the view '{view}' is for a {v['kind']}")
    r = char["render"]
    seed = seed if seed is not None else seed_for(char["id"], view, attempt)
    body = {"model": r["model"], "size": v["size"], "n": 1, "seed": seed, "response_format": "b64_json"}
    if STEPS.get(r["model"]):
        body["steps"] = STEPS[r["model"]]
    paths, ref_ids = [], []
    how = v["how"]
    photo = store.photo_path(char) if (view == "portrait" and char["kind"] == "person") else None
    if photo:
        how, body["prompt"], paths = "edit", photo_prompt(char) + (" " + extra.strip() if extra.strip() else ""), [photo]
        ref_ids = ["photo"]
    elif how == "draw":
        body["prompt"] = draw_prompt(char, view, listing) + (" " + extra.strip() if extra.strip() else "")
        lo = _loras(r)
        if lo:
            body["lora"] = lo
        if providers.PROVIDERS.get(r["model"], {}).get("negative_prompt"):
            body["negative_prompt"] = NEGATIVE
    else:
        canon = store.canon_items(char)
        for cv in v["refs"]:
            it = canon.get(cv)
            if not it:
                raise store.CharError(f"approve the {VIEWS[cv]['label'].lower()} first: this view is made from it")
            paths.append(media.path_of(it))
            ref_ids.append(it["id"])
        body["prompt"] = edit_prompt(char, view, extra)
    meta = {"view": view, "how": how, "model": r["model"], "seed": seed, "prompt": body["prompt"][:1500], "loras": r["loras"] if how == "draw" else [], "refs": ref_ids,
            "identity_hash": store.identity_hash(char), "version": char["version"], "style": r["style"], "steps": body.get("steps")}
    meta["input_hash"] = hashlib.sha1(json.dumps({k: v for k, v in {**meta, "seed": 0}.items() if k not in ("prompt",)} | {"prompt": body["prompt"]}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
    return {"how": how, "body": body, "refs": paths, "ref_ids": ref_ids, "meta": meta}
