"""Start pictures drawn by the image model (Qwen Image by default, any image model the gateway lists). Every shot has a `still`: the first frame of the shot written as a still picture by
the planner (the person can edit it). It is drawn 9:16, looked at by a person, and only then animated by Wan, so a wrong idea dies before the long wait. The character, the place and the
look the plan fixed are added by code, like in the Wan prompts."""
import base64
import re

import httpx

from story2 import providers
from story3 import scenes
from story3.voice import MediaError

from . import cast, looks, pipelines as P, subjects

SIZE = "720x1280"                         # 9:16, multiples of 16, well inside the image model's pixel budget; cropped to the video size when it is animated
DEFAULT_MODEL = providers.DEFAULT_MODEL
KEEP_OUT = "A single still photograph in a vertical 9:16 frame. No text, no letters, no numbers, no logo, no watermark, no subtitles, no collage, no split screen."


def keep_out(short: dict) -> str:
    """KEEP_OUT, saying 'still image' instead of 'photograph' when the chosen style is a drawing."""
    return KEEP_OUT.replace("still photograph", "still illustration") if looks.painted(short) else KEEP_OUT


def avoid_items(shot: dict) -> list[str]:
    """What the person wants kept out of this shot's start picture (the optional negative prompt box), as short items."""
    return [x.strip(" .") for x in re.split(r"[,;\n]+", str(shot.get("avoid") or "")) if x.strip(" .")][:12]


def avoid_line(shot: dict) -> str:
    """The negative prompt as the image model reads it: Qwen ignores a negative field, so it is said in the prompt in the same "No x, no y." form as KEEP_OUT."""
    items = avoid_items(shot)
    return ("No " + ", no ".join(items) + ".") if items else ""


def model_of(short: dict) -> str:
    return short["settings"].get("image_model") or DEFAULT_MODEL


_TIGHT = re.compile(r"close[- ]?up|medium shot|medium close|waist|chest|bust|portrait|head and shoulders|over[- ]the[- ]shoulder|selfie|talking head", re.I)
_FULL = re.compile(r"full[- ]body|full[- ]length|wide shot|wide angle|establishing|head to (?:toe|foot|feet)|walking|running|feet|shoes", re.I)
_LEGS = re.compile(r"\b(shoes?|footwear|sandals?|sneakers?|flats|heels?|boots?|loafers?|chappals?|juttis?|slippers?|barefoot|trousers|pants|jeans|leggings|skirt|dhoti|lungi|socks?|ankles?|legs?)\b", re.I)


def framed_character(text: str, shot: dict) -> str:
    """The character paragraph without the parts of the body the shot's framing cannot show: the image model draws every word, so shoes and trousers in a close-up are forced into the
    frame and the face comes out morphed. Full-body and wide shots keep everything."""
    frame = f"{shot.get('camera', '')} {shot.get('still', '')}"
    if not _TIGHT.search(frame) or _FULL.search(frame):
        return text
    keep = [c for c in re.split(r"(?<=[.;])\s+|,\s+| and ", text) if c.strip() and not _LEGS.search(c)]
    return ", ".join(x.strip(" .") for x in keep) or text


AVATAR_FRAMING = ("The person faces the camera straight on, waist-up, looking into the lens, mouth relaxed and just slightly open as if about to speak, both hands visible and relaxed in front "
                  "of the body, a steady uncluttered background.")


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 3 and w not in {"with", "wearing", "that", "from", "over", "this", "their", "have"}}


def _same(a: str, b: str) -> bool:
    """Whether two descriptions say mostly the same words (the main character is also listed as a subject)."""
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) >= 5 and len(ta & tb) / min(len(ta), len(tb)) >= 0.6              # a few shared words (brown, white, beard) are not the same person


def looks_line(short: dict, shot: dict, character: str) -> tuple[str, str]:
    """(who and what looks like, the place) for a shot, each said once. The main character is not repeated as a subject, and the place is the shot's own place, else a place subject it shows,
    else the plan's main place."""
    subs = subjects.in_shot(short, shot)
    shown = [f"{s['name']}: {s['visual'].rstrip('. ')}." for s in subs if s.get("kind") != "place" and not (character and _same(character, s["visual"]))]
    places = [s for s in subs if s.get("kind") == "place"]
    setting = (shot.get("setting") or "").strip() or (places[0]["visual"].strip() if places else "") or (short["plan"].get("place") or "").strip()
    return " ".join(([character.rstrip(". ") + "."] if character else []) + shown), setting


def prompt(short: dict, shot: dict) -> str:
    """The picture prompt: the still first (the image model weighs the first words most), then how the people and things in it look, the place once, the style and what to keep out. The camera
    move is not said (it means nothing for a still picture), and nothing is said twice (this model has no negative prompt and draws every word)."""
    plan = short["plan"]
    character = framed_character(plan["character"], shot) if shot.get("character") and plan.get("character") else ""
    who, setting = looks_line(short, shot, character)
    parts = [(shot.get("still") or shot["prompt"]).strip()]
    if who:
        parts.append("How they look: " + who)
    if setting:
        parts.append(f"Setting: {setting.rstrip('. ')}.")
    look = looks.of(short, plan.get("look", ""))
    if look:
        parts.append(look.rstrip(". ") + ".")
    if shot.get("avatar"):
        parts.append(AVATAR_FRAMING)
    if avoid_line(shot):
        parts.append(avoid_line(shot))
    parts.append(keep_out(short))
    return " ".join(parts)[:3900]


def request(short: dict, shot: dict, attempt: int) -> dict:
    model = model_of(short)
    body = {"model": model, "prompt": prompt(short, shot), "size": SIZE, "n": 1, "seed": P.seed_for(short, shot, attempt), "response_format": "b64_json"}
    if providers.PROVIDERS.get(model, {}).get("negative_prompt"):          # FLUX runs with guidance and honours one; Qwen (cfg 1) ignores it, so only the sentence in the prompt counts
        body["negative_prompt"] = ", ".join([looks.negative(short, P.NEGATIVE), *avoid_items(shot)])
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


_MAIN = {"the man", "the woman", "man", "woman", "protagonist", "hero", "heroine", "main character", "the protagonist", "narrator"}


def _is_cast(sub: dict, cast_names: set[str], character: str, shot: dict) -> bool:
    """Whether a person subject is one of the people drawn from the reference pictures (they must not be described again: the words would fight the pictures): named like a cast member,
    described like the main character, or called "the man" in a shot that shows the main character."""
    if sub.get("kind") != "person":
        return False
    name = subjects._norm(sub["name"])
    return name in cast_names or bool(character and _same(character, sub["visual"])) or bool(shot.get("character") and name in _MAIN)


def edit_prompt(short: dict, shot: dict, refs: dict) -> str:
    """The start picture of a shot with a cast: the pictures are named by position, the still says what happens and where they stand, and the pictures alone give the people their faces, hair and
    clothes. So the prompt never describes a cast member again, adds the look of anything else once, and names the place only when no place picture is given."""
    who = refs["who"]
    plan = short["plan"]
    noun = "illustration" if looks.painted(short) else "photograph"
    names = [f"Picture {i} shows {w[0]} ({w[1]})." for i, w in enumerate(who, 1)]
    if refs["place"]:
        names.append(f"Picture {len(who) + 1} shows the place.")
    cast_names = {subjects._norm(w[0]) for w in who}
    subs = subjects.in_shot(short, shot)
    others = [s for s in subs if s.get("kind") != "place" and not _is_cast(s, cast_names, plan.get("character", ""), shot)]
    parts = [" ".join(names), f"Create a new {noun}:", (shot.get("still") or shot["prompt"]).strip()]
    if others:
        parts.append("How they look: " + " ".join(f"{s['name']}: {s['visual'].rstrip('. ')}." for s in others))
    if not refs["place"]:
        places = [s for s in subs if s.get("kind") == "place"]
        setting = (shot.get("setting") or "").strip() or (places[0]["visual"].strip() if places else "") or (plan.get("place") or "").strip()
        if setting:
            parts.append(f"Setting: {setting.rstrip('. ')}.")
    look = looks.of(short, cast.look_text(short) or plan.get("look"))
    if look:
        parts.append(look.rstrip(". ") + ".")
    if who:
        parts.append("Each person keeps exactly the face, hair, skin tone, build and clothes of their own picture; any wording about their looks or clothes above is ignored."
                     + (" The scene happens in the place of the place picture." if refs["place"] else ""))
    elif refs["place"]:
        parts.append("The scene happens in the place of the place picture.")
    if shot.get("avatar"):
        parts.append(AVATAR_FRAMING)
    if avoid_line(shot):
        parts.append(avoid_line(shot))
    parts.append(keep_out(short))
    return " ".join(parts)[:3900]


def build(short: dict, shot: dict, attempt: int) -> dict:
    """{how, body, refs (paths), ref_ids, versions}: an edit from the cast's pictures when the shot has a cast member, else the plain text request."""
    from . import store as sstore
    refs = cast.refs_for(short, shot)
    if not refs and shot.get("character"):
        # No cast configured but shot is tagged as showing a character: use the uploaded anchor image
        # (if any) so the person's face and outfit come from the user's own photo rather than from
        # the text description (which may name a different outfit like the Character Studio canon).
        anchor = sstore.image_path(short, short["images"].get("anchor", ""))
        if anchor:
            pl = cast.place(short)
            place_item = pl["item"] if (pl and pl.get("item") and not shot.get("setting")) else None
            from story3 import store as media
            place_paths = [media.path_of(place_item)] if place_item else []
            place_ids = [place_item["id"]] if place_item else []
            refs = {"paths": [anchor] + place_paths, "ids": [str(anchor)] + place_ids,
                    "who": [("the character", "face and clothes")], "place": bool(place_item), "versions": {}}
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
