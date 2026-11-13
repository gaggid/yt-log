"""The scene review (plan: docs/PLAN_scene_director.md, layer 2). It looks at the drawn start pictures and scores every scene. It changes nothing: it only reads the pictures and writes `short["review"]`.

The model is never shown what a picture was asked to show. It only DESCRIBES what it sees (place, background, people, objects, text, style), one call per sheet of six pictures, with a strict JSON schema so the
reply is always valid JSON (tried on the real gateway: a model that sees the prompt agrees with it and misses defects; a model that describes blind does not). Code then compares the description with the
prompt and decides what is a defect, and computes every score:

  defects    extra_object, wrong_place, wrong_count (a note when a crowd is in the picture), text_in_picture, style_break, blank_background, extra_person (people when the shot names none), object_face (a car or object with eyes)
  engagement 0 to 10 from up to five parts of 0 to 2: Read and Pull (the model's), Proof (the picture matches its prompt), Clean (no text, style break or blank background), Move (the motion line asks for a camera move)
  repeat     0 (new) to 10 (a copy of an earlier scene): the colour and layout match with every earlier picture, and the overlap of what the descriptions say is in them
  floors     the three low floors of the pass rule (hook, dead stretch, duplicate); only reported here

Switch: `settings.scene_review` (on for every new short; a short made before it existed has no such key)."""
import hashlib
import json
import re
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import config
from story import llm, settings as settings_mod
from story.schemas import Str
from story2.schemas import M
from story3 import store as media

from . import lint, looks, motionwriter, subjects as subj

SETTING = "scene_review"
SHEET = 6                                                    # pictures per sheet (one call each)
TILE = (360, 640)
HOOK_S = 3.0                                                 # the scenes that start in the first 3 seconds count double in the short's average
WEAK_ENGAGEMENT, WEAK_RUN = 5.0, 3                           # a stretch of three scenes under 5 is reported
FLOOR_HOOK, FLOOR_DEAD, DUPLICATE_MATCH = 4.0, 3.0, 0.85     # the three low floors (section 5.3 of the plan)
MONEY = re.compile(r"\b(rupees?|money|coins?|banknotes?|notes?|cash|currency)\b", re.I)
BREATHING = re.compile(r"\b(breath\w*|blinks?)\b", re.I)
BAD_STYLE = {"drawn": re.compile(r"isometric|\b3d\b|render|photo|diorama|cgi|vector|low[- ]poly", re.I),         # the short is a drawing: these are a different look
             "photo": re.compile(r"painted|paint|cartoon|anime|illustration|drawn|3d|isometric|diorama", re.I),   # the short is a photograph: these are not
             "3d": re.compile(r"photo|painted|paint|watercolou?r|anime|sketch|line art|vector|flat", re.I)}      # the short is a rendered or modelled look: "3d", "diorama", "cartoon" are right, a photograph or a flat drawing is not
BLANK = re.compile(r"\b(blank|empty|plain white|white background|nothing)\b", re.I)
CROWD_PLACES = {"market", "street"}
RULES = "4"        # bump when the defects or the questions to the model change: a review made under older rules is no longer current (and the director does not act on it)
TRAFFIC = {"car", "sedan", "suv", "bus", "truck", "taxi", "auto", "rickshaw", "bicycle", "bike", "scooter", "motorcycle", "van"}          # street scenery: a car passing in a street picture is not an extra prop
STREETY = re.compile(r"\b(street|road|city|skyline|market|lane|avenue|traffic|junction|highway)\b", re.I)
NO_FACE = re.compile(r"^\s*(none|no|n/?a|nothing|no objects?|-|)\s*\.?\s*$", re.I)
PROPS = {"object", "product", "other", ""}                   # a place that shows up is a wrong place (below), not an extra object


def enabled(short: dict) -> bool:
    return bool((short.get("settings") or {}).get(SETTING))


# ── the model's part: what is in each picture ──────────────────────────────────────

class Seen(M):
    id: Str
    place: Str = ""
    setting_type: Str = ""
    people_count: int = 0
    objects: list[str] = []
    readable_text: Str = ""
    style: Str = ""
    background: Str = ""
    shot_size: Str = ""
    arrangement: Str = ""
    face_visible: bool = False
    object_faces: Str = ""
    read: int = 0
    pull: int = 0


class SeenOut(M):
    shots: list[Seen]


_STR, _INT, _BOOL, _LIST = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}, {"type": "array", "items": {"type": "string"}}
SCHEMA = {"type": "object", "properties": {"shots": {"type": "array", "items": {"type": "object", "properties": {
    "id": _STR, "place": _STR, "setting_type": _STR, "people_count": _INT, "objects": _LIST, "readable_text": _STR, "style": _STR, "background": _STR,
    "shot_size": _STR, "arrangement": _STR, "face_visible": _BOOL, "object_faces": _STR, "read": _INT, "pull": _INT},
    "required": ["id", "place", "setting_type", "people_count", "objects", "readable_text", "style", "background", "shot_size", "arrangement", "face_visible", "object_faces", "read", "pull"],
    "additionalProperties": False}}}, "required": ["shots"], "additionalProperties": False}
RESPONSE_FORMAT = {"type": "json_schema", "json_schema": {"name": "picture_description", "strict": True, "schema": SCHEMA}}

SYSTEM = """[TASK:p4_review]
You describe pictures plainly, like a careful assistant writing alt text. The attached sheet shows up to six pictures, each labelled with its shot id in the top-left corner.
For every labelled picture return: id; place (where it is, for example living room, street market, office, kitchen, empty white background); setting_type (indoor, outdoor or none); people_count (people you can clearly see);
objects (every clearly visible object that is not a person or the building); readable_text (any text or numbers you can see, banknote numerals and screen text included, and whether they look like real words, or "none");
style (painted, photo, 3d, isometric diorama, other); background (one short phrase: what is behind the main subject, or "blank white" if it is empty); shot_size (close-up, medium or wide); arrangement (one short phrase of how
things are placed); face_visible (true when a face can be seen); object_faces (name every vehicle, machine, building or other object that has eyes, a mouth or a face on it, as if it were a character; "none" when no object does); read (2 if a phone viewer understands the one main subject at once, 1 after a moment, 0 if unclear); pull (2 if a face, emotion, surprise or strong contrast
would make a stranger keep watching, 1 if pleasant, 0 if dull).
Describe only what you see. Do not guess what the picture was meant to show. Return ONLY the JSON."""


def _font():
    try:
        return ImageFont.load_default(size=34)
    except TypeError:                                          # an older Pillow has no size
        return ImageFont.load_default()


def sheet_for(items: list[tuple[str, Path]], path: Path | None = None) -> str:
    """One contact sheet of up to six pictures, each labelled with its shot id, as a JPEG data URL (also saved to `path`: a file that can be made again)."""
    import base64
    import io
    w, h = TILE
    sheet = Image.new("RGB", (w * 3, h * 2), "white")
    d = ImageDraw.Draw(sheet)
    font = _font()
    for i, (sid, p) in enumerate(items):
        x, y = (i % 3) * w, (i // 3) * h
        sheet.paste(Image.open(p).convert("RGB").resize((w, h)), (x, y))
        d.rectangle((x, y, x + 20 + 22 * len(sid), y + 46), fill="black")
        d.text((x + 8, y + 4), sid, fill="white", font=font)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(path, quality=88)
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def pictures(short: dict) -> list[tuple[dict, dict, Path]]:
    """(shot, its chosen start picture's media row, the file) for every shot that has a picture."""
    from . import clips
    out = []
    for sh in short.get("shots", []):
        kf = clips.chosen_keyframe(short, sh)
        if kf and kf.get("file"):
            p = media.path_of(kf)
            if p.is_file():
                out.append((sh, kf, p))
    return out


async def describe(short: dict, items: list[tuple[dict, dict, Path]], backend, s: dict) -> dict[str, dict]:
    """The blind description of every picture: id -> what the model sees. One call per sheet; a sheet that fails is left out (the scenes on it are simply not reviewed)."""
    out: dict[str, dict] = {}
    folder = config.DATA_DIR / "media" / short["id"] / "review"
    for n in range(0, len(items), SHEET):
        chunk = items[n:n + SHEET]
        ids = [sh["id"] for sh, _k, _p in chunk]
        url = sheet_for([(sh["id"], p) for sh, _k, p in chunk], folder / f"sheet-{n // SHEET + 1}.jpg")
        user = "The labelled pictures on this sheet, left to right and top row first: " + ", ".join(ids) + "\nDescribe every one of them."

        def check(res: SeenOut, ids=ids) -> None:
            if sorted(x.id for x in res.shots) != sorted(ids):
                raise ValueError("describe exactly these pictures: " + ", ".join(ids))
        try:
            res = await llm.JsonCaller(backend, s).call(SYSTEM, user, SeenOut, validate=check, images=[url], response_format=RESPONSE_FORMAT)
        except llm.LLMError:
            continue
        for x in res.value.shots:
            out[x.id] = x.model_dump()
    await face_pass(short, items, out, backend, s)
    return out


class FaceLook(M):
    things: list[str] = []
    face_on_a_thing: bool = False
    where: Str = ""


FACE_SCHEMA = {"type": "object", "properties": {"things": _LIST, "face_on_a_thing": _BOOL, "where": _STR}, "required": ["things", "face_on_a_thing", "where"], "additionalProperties": False}
FACE_FORMAT = {"type": "json_schema", "json_schema": {"name": "face_check", "strict": True, "schema": FACE_SCHEMA}}
FACE_SYSTEM = """[TASK:p4_review_face]
You inspect one picture closely. List the vehicles and non-living objects in it. Then answer: is there a LITERAL drawn eye on any of them, that is an eyeball with an iris or a pupil, an eyelid or eyelashes,
or a drawn mouth with lips or teeth, as if the vehicle or object were a cartoon character? Normal headlights, grilles, windows, bumpers and lamps are NOT eyes or mouths, even when the front of a car looks a little
like a face. Answer true only for a literal eye or mouth, and say exactly where it is. Otherwise answer false and "none". Return ONLY the JSON."""
# Measured on the three s5 pictures of sh-2bf15321 (a1 a small eyeball in a headlight, a2 a normal car, a3 a large eye on the car): "any face or eye" flagged all three (a normal car front "looks like a face"),
# this wording flags only a3 and never a2, and looser "eye-like part" wording flagged all three again. A small eyeball in a headlight (a1) is still missed: precision first, because a flag costs a redraw.
FACE_WIDTH = 1280          # a small eye in a headlight is missed on a sheet tile or at 640 px wide, and seen at this width (tried on the Pixar short sh-2bf15321)
FACE_KINDS = PROPS         # a shot whose subjects include a thing (not only people and places) gets the close look


def _wide_url(path: Path) -> str:
    import base64
    import io
    im = Image.open(path).convert("RGB")
    im = im.resize((FACE_WIDTH, max(1, round(im.height * FACE_WIDTH / im.width))))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def wants_face_look(short: dict, shot: dict, seen: dict) -> bool:
    """A picture that shows a vehicle or a thing the shot lists: the sheet look is too small for an eye on a car, so each of these is looked at again, alone and large."""
    objects = {lint._stem(w) for o in seen.get("objects") or [] for w in lint._words(o)}
    return bool(objects & {lint._stem(t) for t in TRAFFIC}) or any((x.get("kind") or "") in FACE_KINDS for x in subj.in_shot(short, shot))


async def face_pass(short: dict, items: list[tuple[dict, dict, Path]], seen: dict[str, dict], backend, s: dict) -> None:
    """The second look for `object_face`: one picture at a time, large. A claim counts only when it says where the face is (the model sometimes answers true with "none"). A failed call leaves
    the sheet's answer as it is."""
    for sh, _kf, p in items:
        sd = seen.get(sh["id"])
        if not sd or not wants_face_look(short, sh, sd):
            continue
        try:
            res = await llm.JsonCaller(backend, s).call(FACE_SYSTEM, "Inspect this picture.", FaceLook, images=[_wide_url(p)], response_format=FACE_FORMAT)
        except llm.LLMError:
            continue
        where = (res.value.where or "").strip()
        if res.value.face_on_a_thing and not NO_FACE.match(where) and where.lower() not in ("none", "no", "n/a"):
            sd["object_faces"] = where if NO_FACE.match(sd.get("object_faces") or "") else f"{sd['object_faces']}; {where}"


# ── the code's part: defects ────────────────────────────────────────────────────────

def asked_text(shot: dict) -> str:
    return f"{shot.get('still') or shot.get('prompt') or ''} {' '.join(shot.get('must_show') or [])}".strip()


def asks_people(short: dict, shot: dict) -> bool:
    """Whether a shot asks for a person: its text names one, it follows the main character, or a person or group subject is in it."""
    if shot.get("character") or shot.get("avatar") or lint.PERSON.search(asked_text(shot)):
        return True
    return any((s.get("kind") or "") in ("person", "group") for s in subj.in_shot(short, shot))


def defects(short: dict, shot: dict, seen: dict) -> tuple[list[dict], list[str]]:
    """(defects, notes) for one picture: what the description says compared with what the shot asked for. A defect is objectively wrong; a note is something the person may want to know."""
    asked, found, notes = asked_text(shot), [], []
    objects = " ".join(seen.get("objects") or [])
    text = seen.get("readable_text") or ""
    if re.fullmatch(r"\s*s\d{1,3}\s*", text, re.I) or text.strip().lower() == str(shot.get("id") or "").lower():
        text = ""                                        # the shot label printed on the contact sheet, read as text (seen on a one-picture sheet), is not text in the picture
    if not MONEY.search(asked) and (MONEY.search(objects) or MONEY.search(text)):
        found.append({"kind": "extra_object", "text": "paper money or coins are in the picture but its text never asks for them"})
    for sub in subj.of(short):                           # any other prop the plan lists that the picture shows without being asked
        if (sub.get("kind") or "") in PROPS and subj.drawable(sub) and not lint.mentioned(short, sub, asked):
            tokens = lint.distinctive(short, sub)
            have = set(" ".join(lint._stem(w) for w in lint._words(objects)).split())
            hit = tokens & have
            if hit and hit <= {lint._stem(t) for t in TRAFFIC} and STREETY.search(f"{seen.get('place', '')} {seen.get('background', '')}"):
                continue                                 # a car or a bicycle in the traffic of a street picture
            if hit:
                found.append({"kind": "extra_object", "text": f"\"{sub['name']}\" is in the picture but its text never names it"})
    place = lint.place_of(f"{seen.get('place', '')} {seen.get('background', '')}")
    own = lint.scene_place(shot.get("still") or "") or lint.place_of(shot.get("setting") or "")                  # a place THE SHOT names
    plan_place = lint.place_of((short.get("plan") or {}).get("place") or "")                                    # the short's one backdrop: only a fallback
    asked_place = own or plan_place
    if place and asked_place and not lint.same_place(place[0], asked_place[0]):
        if own:
            found.append({"kind": "wrong_place", "text": f"it shows {place[1].strip()} but the shot is set in {asked_place[1].strip()}"})
        elif (shot.get("setting") or "").strip():       # the shot names a place this check cannot read ("a high-tech laboratory"): the short's backdrop says nothing about it
            pass
        elif asked_place[0] in lint.HOME_ROOMS and place[0] not in lint.HOME_ROOMS:
            found.append({"kind": "wrong_place", "text": f"it shows {place[1].strip()} but the short is set in {asked_place[1].strip()} and this shot names no other place"})
        else:                                           # a desk scene in a short whose backdrop is a living room: the shot never asked for the living room, so it is a note and nothing is redrawn
            notes.append(f"it shows {place[1].strip()}; the short's place is {asked_place[1].strip()}, but this shot names no place, so nothing is changed")
    counts = [{"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}.get(m.group(1).lower(), 0) or int(m.group(1)) for m in re.finditer(
        r"\b(one|two|three|four|five|\d+)\s+(?:[\w-]+\s+){0,2}?(?:people|persons?)\b", shot.get("still") or "", re.I)]
    asked_n = counts[0] if counts and len(counts) > 1 and sum(counts[1:]) == counts[0] else sum(counts)         # "five people. One person stands left, one ..." is five, not ten
    got = int(seen.get("people_count") or 0)
    if asked_n and got != asked_n:
        if (place and place[0] in CROWD_PLACES) or abs(got - asked_n) < 2:
            notes.append(f"{got} people are in the picture (its text asks for {asked_n}); a crowd or a near count")
        else:
            found.append({"kind": "wrong_count", "text": f"{got} people are in the picture; its text asks for {asked_n}"})
    want = re.search(r"close[- ]up|wide shot|medium", shot.get("still") or "", re.I)
    drawn = re.search(r"close|medium|wide", seen.get("shot_size") or "", re.I)
    if want and drawn:
        w, d = ("close" if want.group(0).lower().startswith("close") else want.group(0).lower().split()[0]), drawn.group(0).lower()
        if w in ("close", "wide") and d != w:
            notes.append(f"the text asks for a {w} shot and the picture is {d}; the image model often ignores a close-up, so nothing is changed")
    faces = (seen.get("object_faces") or "").strip()
    if faces and not NO_FACE.match(faces):
        found.append({"kind": "object_face", "text": f"an object has eyes or a face drawn on it: {faces[:60]}"})
    got_people = int(seen.get("people_count") or 0)
    if got_people >= 2 and not asks_people(short, shot) and not (place and place[0] in CROWD_PLACES):
        found.append({"kind": "extra_person", "text": f"{got_people} people are in the picture but the shot names none"})
    if text.strip().lower() not in ("", "none", "n/a"):
        found.append({"kind": "text_in_picture", "text": f"readable text or numbers are in the picture: {text.strip()[:60]}"})
    style = seen.get("style") or ""
    if style and BAD_STYLE[looks.family(short)].search(style):
        found.append({"kind": "style_break", "text": f"the picture looks {style.strip()}, not like the rest of the short ({looks.label(short)})"})
    if BLANK.search(seen.get("background") or "") or (seen.get("place") or "").strip().lower() == "none":
        found.append({"kind": "blank_background", "text": "the background is blank or empty"})
    return found, notes


# ── the code's part: scores ──────────────────────────────────────────────────────────

def move_part(shot: dict, prev_kind: str) -> tuple[int | None, str]:
    """0 to 2 for how much the motion line asks the camera and the subject to do, and its camera kind; None when the shot has no motion line."""
    m = (shot.get("move") or "").strip()
    if not m:
        return None, ""
    kind = motionwriter.camera_kind(m)
    score = 2 - (kind in ("static", "")) - bool(prev_kind and kind == prev_kind) - bool(motionwriter.WEAK.search(m)) - bool(BREATHING.search(m))
    return max(0, score), kind


def engagement(parts: dict) -> float | None:
    got = [v for v in parts.values() if v is not None]
    return round(10 * sum(got) / (2 * len(got)), 1) if got else None


def _hist(im: Image.Image) -> dict:
    raw = im.convert("RGB").resize((72, 128)).tobytes()
    h: dict = {}
    for i in range(0, len(raw), 3):
        k = (raw[i] // 64, raw[i + 1] // 64, raw[i + 2] // 64)
        h[k] = h.get(k, 0) + 1
    n = sum(h.values())
    return {k: v / n for k, v in h.items()}


def _gray(im: Image.Image) -> list[int]:
    return list(im.convert("L").resize((16, 28)).tobytes())


def _corr(a: list[int], b: list[int]) -> float:
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    da, db = sum((x - ma) ** 2 for x in a) ** 0.5, sum((y - mb) ** 2 for y in b) ** 0.5
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (da * db) if da and db else 0.0


def measured(a: dict, b: dict) -> float:
    """0 to 1: how much two pictures look alike in colour and in where the light and dark areas sit."""
    colour = sum(min(a["hist"].get(k, 0), b["hist"].get(k, 0)) for k in set(a["hist"]) | set(b["hist"]))
    return 0.5 * colour + 0.5 * max(0.0, _corr(a["gray"], b["gray"]))


def tags_of(seen: dict) -> dict:
    place = lint.place_of(f"{seen.get('place', '')} {seen.get('background', '')}")
    size = re.search(r"close|medium|wide", seen.get("shot_size") or "", re.I)
    objs = {lint._stem(w) for o in seen.get("objects") or [] for w in lint._words(o) if len(w) > 2}
    return {"place": place[0] if place else "", "size": size.group(0).lower() if size else "", "things": objs | ({place[0]} if place else set())}


def tag_match(a: dict, b: dict) -> float:
    union = a["things"] | b["things"]
    return 0.7 * (len(a["things"] & b["things"]) / len(union) if union else 0.0) + 0.3 * (1.0 if a["size"] and a["size"] == b["size"] else 0.0)


def repeat_score(combined: float) -> int:
    return max(0, min(10, round((combined - 0.25) / 0.55 * 10)))


def start_times(short: dict) -> dict[str, float]:
    t, out = 0.0, {}
    for sh in short.get("shots", []):
        out[sh["id"]] = t
        t += float(sh.get("seconds") or 0)
    return out


def floors(scenes: dict, order: list[str]) -> list[dict]:
    """The three low floors of the pass rule. Reported only; nothing stops for them yet."""
    out = []
    first = [scenes[i]["engagement"] for i in order[:2] if i in scenes and scenes[i]["engagement"] is not None]
    if any(v < FLOOR_HOOK for v in first):
        out.append({"floor": "hook", "text": f"one of the first two scenes has an engagement score under {FLOOR_HOOK:g}", "shots": order[:2]})
    low = [i for i in order if i in scenes and scenes[i]["engagement"] is not None and scenes[i]["engagement"] <= FLOOR_DEAD]
    run, run_ids = 0, []
    for i in order:
        if i in low:
            run += 1
            run_ids.append(i)
            if run >= 3:
                out.append({"floor": "dead_stretch", "text": f"three scenes in a row score {FLOOR_DEAD:g} or less", "shots": run_ids[-3:]})
                break
        else:
            run, run_ids = 0, []
    dups = [i for i in order if i in scenes and scenes[i]["repeat"]["duplicate"]]
    if dups:
        out.append({"floor": "duplicate", "text": "a scene is a near-duplicate of an earlier one", "shots": dups})
    return out


def summary(short: dict, scenes: dict, order: list[str]) -> dict:
    times = start_times(short)
    weights = {i: (2.0 if times.get(i, 99) < HOOK_S else 1.0) for i in order if i in scenes and scenes[i]["engagement"] is not None}
    avg = round(sum(scenes[i]["engagement"] * w for i, w in weights.items()) / sum(weights.values()), 1) if weights else None
    reps = [scenes[i]["repeat"]["score"] for i in order[1:] if i in scenes]
    half = len(reps) // 2
    weakest = None
    ids = [i for i in order if i in scenes and scenes[i]["engagement"] is not None]
    for k in range(len(ids) - WEAK_RUN + 1):
        win = ids[k:k + WEAK_RUN]
        mean = sum(scenes[i]["engagement"] for i in win) / WEAK_RUN
        if mean < WEAK_ENGAGEMENT and (weakest is None or mean < weakest["mean"]):
            weakest = {"shots": win, "mean": round(mean, 1)}
    return {"engagement": avg, "repeat": round(sum(reps) / len(reps), 1) if reps else None,
            "repeat_first_half": round(sum(reps[:half]) / half, 1) if half else None, "repeat_second_half": round(sum(reps[half:]) / max(1, len(reps) - half), 1) if reps else None,
            "defects": sum(len(v["defects"]) for v in scenes.values()), "weakest_stretch": weakest, "reviewed": len(scenes), "shots": len(order)}


def review_scenes(short: dict, items: list[tuple[dict, dict, Path]], seen: dict[str, dict]) -> dict:
    """Everything the code decides from the descriptions and the pictures: defects, the five engagement parts, the repeat score, the floors and the summary. Pure: no model call."""
    order = [sh["id"] for sh in short.get("shots", [])]
    shots = {sh["id"]: sh for sh in short.get("shots", [])}
    pics = {sh["id"]: p for sh, _k, p in items}
    prints = {}
    for sid, p in pics.items():
        if sid in seen:
            with Image.open(p) as im:
                prints[sid] = {"hist": _hist(im), "gray": _gray(im)}
    reads = [seen[i].get("read") for i in seen]
    flat = len(reads) >= 5 and len({seen[i].get("read") for i in seen}) == 1 and len({seen[i].get("pull") for i in seen}) == 1    # the model gave every picture the same soft score: it says nothing
    tags = {i: tags_of(seen[i]) for i in seen}
    scenes: dict[str, dict] = {}
    prev_kind = ""
    for sid in order:
        sh = shots[sid]
        move, kind = move_part(sh, prev_kind)
        prev_kind = kind or prev_kind
        if sid not in seen:
            continue
        found, notes = defects(short, sh, seen[sid])
        kinds = [d["kind"] for d in found]
        parts = {"read": None if flat else max(0, min(2, int(seen[sid].get("read") or 0))), "pull": None if flat else max(0, min(2, int(seen[sid].get("pull") or 0))),
                 "proof": max(0, 2 - sum(k in ("extra_object", "wrong_place", "wrong_count", "extra_person") for k in kinds)), "clean": max(0, 2 - sum(k in ("text_in_picture", "style_break", "blank_background", "object_face") for k in kinds)),
                 "move": move}
        closest, best, best_m, best_t = "", -1.0, 0.0, 0.0
        for earlier in order[:order.index(sid)]:
            if earlier not in prints:
                continue
            m, t = measured(prints[sid], prints[earlier]), tag_match(tags[sid], tags[earlier])
            c = 0.6 * m + 0.4 * t
            if c > best:
                closest, best, best_m, best_t = earlier, c, m, t
        dup = bool(closest) and best_m >= DUPLICATE_MATCH and bool(tags[sid]["place"]) and tags[sid]["place"] == tags[closest]["place"] and best_t >= 0.6
        scenes[sid] = {"seen": seen[sid], "defects": found, "notes": notes, "parts": parts, "engagement": engagement(parts),
                       "repeat": {"score": repeat_score(best) if closest else 0, "closest": closest, "measured": round(best_m, 2), "tags": round(best_t, 2), "duplicate": dup}}
    fl = floors(scenes, order)
    return {"scenes": scenes, "order": order, "summary": summary(short, scenes, order), "floors": fl, "needs_look": bool(fl), "soft_scores_flat": flat}


# ── the run ──────────────────────────────────────────────────────────────────────────

def stamp(short: dict) -> str:
    """A fingerprint of what the review looked at: the chosen picture of every shot and what it was asked to show."""
    rows = [[sh["id"], kf["id"], asked_text(sh), sh.get("setting"), sh.get("move")] for sh, kf, _p in pictures(short)]
    return hashlib.sha1(json.dumps([RULES, looks.style_id(short), rows, (short.get("plan") or {}).get("place")], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def current(short: dict) -> bool:
    return bool((short.get("review") or {}).get("stamp") == stamp(short))


def ready(short: dict) -> bool:
    """Whether every shot has its picture (the review reads the whole short, because repeats are compared across it)."""
    return bool(short.get("shots")) and len(pictures(short)) == len(short["shots"])


async def run_on(short: dict, backend, s: dict | None = None) -> dict:
    """Review a short in place (the caller saves it). Returns the report. A short with no pictures yet has nothing to review."""
    s = s or settings_mod.get()
    items = pictures(short)
    if not items:
        raise ValueError("draw the start pictures first")
    seen = await describe(short, items, backend, s)
    if not seen:
        raise ValueError("the model could not describe the pictures")
    res = review_scenes(short, items, seen)
    short["review"] = {"at": time.time(), "stamp": stamp(short), **res}
    return report(short)


async def run(short_id: str, backend, s: dict | None = None) -> dict:
    from . import store
    short = store.get(short_id)
    rep = await run_on(short, backend, s)
    store.save(short)
    return rep


def report(short: dict) -> dict:
    """What the screen shows."""
    last = short.get("review") or {}
    on = enabled(short)
    return {"enabled": on, "ready": ready(short) if on else False, "current": current(short) if on and last else False, "at": last.get("at"), "summary": last.get("summary"), "scenes": last.get("scenes", {}),
            "order": last.get("order", []), "floors": last.get("floors", []), "needs_look": last.get("needs_look", False), "soft_scores_flat": last.get("soft_scores_flat", False)}
