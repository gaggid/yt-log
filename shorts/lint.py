"""The storyboard check (plan: docs/PLAN_scene_director.md, layer 1). Plain code, no model call except one rewrite request to the picture writer for the two problems only the writer can fix.
It runs on the picture prompts of a short before any picture is drawn, and only acts on CONTRADICTIONS (something in the prompt that the picture text does not ask for, or says twice in two ways):

  stray_subject    a prop or a place the plan lists is added to a shot whose own picture text never names it
  setting_conflict the shot's "Setting:" names a different place from the one its picture text names
  angle_wording    "low-angle" in two words, which the image model ignores, instead of a sentence it can follow
  text_in_picture  a picture asked to show text, numbers, labels or a number on a screen (the video model handles text badly)
  group_count      a group ("a family") with no exact head count (the image model fills a vague count with a crowd)

Everything about taste (the same place in many shots, the same composition, how many shots show a person) is only a NOTE, shown to the person; nothing is changed for it.

Switch: `settings.storyboard_lint` (on for every new short; a short made before it existed has no such key and keeps its old behaviour, so its drawn pictures are never marked old)."""
import hashlib
import json
import re
import time

from . import subjects as subj

SETTING = "storyboard_lint"

# ── words ────────────────────────────────────────────────────────────────────

NATIONALITY = {"indian", "chinese", "american", "russian", "pakistani", "british", "japanese", "korean", "european", "african", "asian", "french", "german", "israeli", "iranian", "turkish",
               "bangladeshi", "nepali", "global", "local", "national", "modern", "young", "old", "small", "large", "big", "new", "the", "a", "an", "of", "and", "or", "with"}
PROP_KINDS = {"object", "product", "place", "other", ""}          # kinds that can be added to a picture by mistake; people, groups and machines are kept as the planner listed them

PLACES = [
    ("living room", r"living[- ]room|drawing[- ]room|\blounge\b|sitting room"),
    ("bedroom", r"bedroom"),
    ("kitchen", r"kitchen"),
    ("office", r"\boffice\b(?!\s+(?:worker|workers|staff|employee|employees|job|clerk|boy|chair|desk))"),
    ("classroom", r"classroom|\bschool\b|\bcollege\b|lecture hall"),
    ("hospital", r"hospital|clinic"),
    ("temple", r"\btemple\b|mosque|church|shrine"),
    ("palace", r"palace|opulent hall|grand hall|\bhall\b"),
    ("market", r"market|bazaar"),
    ("street", r"\b(?:street|road|lane|alley|highway)\b"),
    ("shop", r"\b(?:shop|store|showroom|mall)\b"),
    ("cottage", r"cottage|\bhut\b|shack|village house"),
    ("village", r"village|\bfarm\b|\bfield\b"),
    ("garden", r"garden|\bpark\b"),
    ("beach", r"beach|seaside|\bshore\b"),
    ("mountain", r"mountain|himalaya|snowy slope|snow slope"),
    ("forest", r"forest|jungle|\bwoods\b"),
    ("desert", r"desert|\bdunes?\b"),
    ("factory", r"factory|warehouse|workshop"),
    ("station", r"railway station|train station|airport|runway|harbou?r|\bdock\b"),
    ("studio", r"\bstudio\b|\bstage\b"),
    ("space", r"outer space|in space|\borbit\b"),
]
SAME_PLACE = [{"market", "street", "shop"}, {"cottage", "village"}]
HOME_ROOMS = {"living room", "bedroom", "kitchen", "office", "classroom"}          # rooms a short can move between without leaving its one indoor backdrop
ARTICLE_AN = {"office", "empty"}

NO_TEXT = re.compile(r"\b(text|letters?|words?|numbers?|numerals?|digits?|labels?|logos?|captions?|headlines?|price tags?|writing|written|printed|inscri\w+|slogans?|barcodes?|qr codes?)\b"
                     r"|\b(?:screen|display|sign|board|poster|banner)s?\s+(?:displays?|shows?|reads?|says?)\s+(?:a |an |the |one )?(?:large |big |small )?(?:number|text|word|message|figure|graph|chart|price|balance)", re.I)
NUM = r"(?:one|two|three|four|five|\d+)"
GROUP_WORDS = "family|families|group|team|crowd|friends|colleagues|villagers|students|workers|passengers|soldiers|crew|audience|class|household"
GROUP_NOUN = re.compile(rf"(?<![\w-])(?:{GROUP_WORDS})(?![\w-])", re.I)                    # not the "class" of "middle-class"
COUNT_OK = re.compile(rf"\b{NUM}\s+(?:[\w-]+\s+){{0,2}}(?:people|persons?|men|women|members|children|kids|friends|adults|soldiers|workers|students|passengers|colleagues|villagers)\b"
                      rf"|(?<![\w-])(?:{GROUP_WORDS})\s+of\s+{NUM}\b", re.I)                # "three people", "a family of three"
ANGLE_LOW = re.compile(r"\blow[- ]angle\b", re.I)
ANGLE_HIGH = re.compile(r"\b(?:high[- ]angle|bird'?s[- ]eye(?: view)?|overhead|top[- ]down)\b", re.I)
ANGLE_DONE = re.compile(r"camera is placed (?:low|high)|looks? (?:up|down) at|from below|from above", re.I)
LOW_SENTENCE = "The camera is placed low and looks up at the subject from below."
HIGH_SENTENCE = "The camera is placed high and looks down at the subject from above."
PERSON = re.compile(r"\b(man|men|woman|women|person|people|family|worker|soldier|soldiers|boy|girl|child|children|couple|face|villager|student|driver|pilot|friends)\b", re.I)
SIZE = re.compile(r"\b(close[- ]up|medium shot|wide shot|macro|extreme close[- ]up|medium close[- ]up)\b", re.I)
CURRENCY = re.compile(r"\b(rupees?|banknotes?|bank notes?|currency|cash|dollars?|money)\b", re.I)
PAPER = "The notes are plain coloured paper with soft, blurred print."


def enabled(short: dict) -> bool:
    return bool((short.get("settings") or {}).get(SETTING))


# ── small helpers ─────────────────────────────────────────────────────────────

def _stem(w: str) -> str:
    w = w.lower()
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        return w[:-1]
    return w


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _strip_kind(name: str) -> str:
    """A shot lists its subjects as "Middle-class Indian family (group)": the bracket is the kind, not part of the name."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", name or "").strip()


def _text_of(shot: dict) -> str:
    return (shot.get("still") or shot.get("prompt") or "").strip()


def _plan_subject(short: dict, name: str) -> dict | None:
    key = subj._norm(_strip_kind(name))
    return next((x for x in subj.of(short) if subj._norm(x["name"]) == key), None)


def distinctive(short: dict, sub: dict) -> set[str]:
    """The words of a subject's name that only this subject has (and that are not a nationality or a plain adjective): "Indian Rupees" is told by "rupee", never by "Indian"."""
    others = [{_stem(w) for w in _words(x["name"]) if w not in NATIONALITY} for x in subj.of(short) if x["name"] != sub["name"]]
    mine = {_stem(w) for w in _words(sub["name"]) if w not in NATIONALITY}
    return {w for w in mine if not any(w in o for o in others)}


def mentioned(short: dict, sub: dict, text: str) -> bool:
    """Whether a picture text names a subject: its whole name, or a word only that subject has (with a plural)."""
    t = " " + " ".join(_stem(w) for w in _words(text)) + " "
    full = " " + " ".join(_stem(w) for w in _words(sub["name"])) + " "
    if full in t:
        return True
    return any(f" {w} " in t for w in distinctive(short, sub))


def place_of(text: str) -> tuple[str, str] | None:
    """(place key, the words that named it) for the first place a text names, else None."""
    best = None
    for key, rx in PLACES:
        m = re.search(rx, text or "", re.I)
        if m and (best is None or m.start() < best[2]):
            best = (key, m.group(0), m.start())
    return (best[0], best[1]) if best else None


SCREEN = re.compile(r"\b(screen|display|wallpaper|monitor|photograph|painting|poster|television|tv|map)\b", re.I)


def scene_place(text: str) -> tuple[str, str] | None:
    """The place a picture text puts its scene in: the sentences about what a screen, a painting or a map SHOWS are left out ("the screen shows a forest" is not a forest)."""
    sents = [x for x in re.split(r"(?<=[.!?])\s+", text or "") if x and not SCREEN.search(x)]
    return place_of(" ".join(sents)) if sents else None


def same_place(a: str, b: str) -> bool:
    return a == b or any(a in g and b in g for g in SAME_PLACE)


def phrase_for(key: str) -> str:
    return ("an " if key[0] in "aeiou" else "a ") + key


# ── fixes that only need code ──────────────────────────────────────────────────

def normalise_still(text: str) -> str:
    """"Low-angle close-up of ..." becomes "Close-up of ... The camera is placed low and looks up at the subject from below." (the image model ignores a two-word angle and follows a sentence)."""
    t = (text or "").strip()
    if not t or ANGLE_DONE.search(t):
        return t
    sentence = LOW_SENTENCE if ANGLE_LOW.search(t) else (HIGH_SENTENCE if ANGLE_HIGH.search(t) else "")
    if not sentence:
        return t
    t = ANGLE_HIGH.sub("", ANGLE_LOW.sub("", t, count=1), count=1)
    t = re.sub(r"\s{2,}", " ", t).strip(" ,")
    t = t[:1].upper() + t[1:]
    parts = re.split(r"(?<=[.!?])\s+", t, maxsplit=1)
    return " ".join([parts[0], sentence] + parts[1:])


def clean_visual(text: str) -> str:
    """A subject's look with the numbers taken out ("500 and 2000 Rupee notes" would be printed on the notes) and, for money, plain paper said in positive words."""
    t = text or ""
    had = bool(re.search(r"\d", t))
    t = re.sub(r"\b\d[\d,.]*\b", "", t)
    t = re.sub(r"\b(of|with|and|or)\s+(?:and|or)\s+", r"\1 ", t)
    t = re.sub(r"\s{2,}", " ", t).replace(" ,", ",").strip()
    if (had or CURRENCY.search(t)) and CURRENCY.search(t) and PAPER not in t:
        t = t.rstrip(". ") + ". " + PAPER
    return t


def tidy_shot(short: dict, shot: dict) -> list[str]:
    """Apply the fixes that need only code to one shot, in place. Returns what changed, in plain words."""
    changed: list[str] = []
    text = _text_of(shot)
    listed = [n for n in shot.get("subjects") or []]
    keep = []
    for name in listed:
        sub = _plan_subject(short, name)
        if sub is not None and (sub.get("kind") or "") in PROP_KINDS and text and not mentioned(short, sub, text):
            changed.append(f"took \"{sub['name']}\" out of the shot (its picture text never names it)")
        else:
            keep.append(name)
    if keep != listed:
        shot["subjects"] = keep
    place = scene_place(shot.get("still") or "")
    setting = (shot.get("setting") or "").strip()
    if place and setting:
        sp = place_of(setting)
        if sp and not same_place(place[0], sp[0]):
            shot["setting"] = phrase_for(place[0]).capitalize() + "."
            changed.append(f"changed the setting from \"{setting.rstrip('. ')}\" to {phrase_for(place[0])} (the picture text says {place[1].strip()})")
    still = shot.get("still") or ""
    fixed = normalise_still(still)
    if fixed != still:
        shot["still"] = fixed
        changed.append("wrote the camera angle as a sentence")
    must = shot.get("must_show") or []
    kept = [m for m in must if not NO_TEXT.search(m)]
    if kept != must:
        shot["must_show"] = kept
        changed.append("took a fact about text out of what the picture must show")
    return changed


# ── findings (pure) ─────────────────────────────────────────────────────────────

def _finding(rule: str, shot: str | None, text: str, fix: str | None) -> dict:
    return {"rule": rule, "shot": shot, "text": text, "fix": fix}


def findings(short: dict, shot_ids: set[str] | None = None) -> list[dict]:
    """Every contradiction still left in the picture prompts. `fix` says who can fix it: `code` (tidy_shot) or `writer` (the picture writer is asked again)."""
    out = []
    for sh in short.get("shots", []):
        if shot_ids is not None and sh["id"] not in shot_ids:
            continue
        sid, text = sh["id"], _text_of(sh)
        for name in sh.get("subjects") or []:
            sub = _plan_subject(short, name)
            if sub is not None and (sub.get("kind") or "") in PROP_KINDS and text and not mentioned(short, sub, text):
                out.append(_finding("stray_subject", sid, f"shot {sid}: \"{sub['name']}\" is added to the picture but its text never names it", "code"))
        place, setting = scene_place(sh.get("still") or ""), (sh.get("setting") or "").strip()
        sp = place_of(setting) if setting else None
        if place and sp and not same_place(place[0], sp[0]):
            out.append(_finding("setting_conflict", sid, f"shot {sid}: the picture text says {place[1].strip()} but the setting says {sp[1].strip()}", "code"))
        still = sh.get("still") or ""
        if (ANGLE_LOW.search(still) or ANGLE_HIGH.search(still)) and not ANGLE_DONE.search(still):
            out.append(_finding("angle_wording", sid, f"shot {sid}: the camera angle is two words the image model ignores", "code"))
        m = NO_TEXT.search(still) or next((x for x in (NO_TEXT.search(f) for f in sh.get("must_show") or []) if x), None)
        if m:
            out.append(_finding("text_in_picture", sid, f"shot {sid}: the picture is asked to show text or a number (\"{m.group(0)}\"); the video model handles text badly", "writer" if NO_TEXT.search(still) else "code"))
        g = GROUP_NOUN.search(still)
        if g and not COUNT_OK.search(still):
            out.append(_finding("group_count", sid, f"shot {sid}: \"{g.group(0)}\" has no exact head count (the image model draws a crowd for a vague count)", "writer"))
    return out


def notes(short: dict) -> list[dict]:
    """What the person may want to know, never acted on: the same place, the same composition, or few people across the shots."""
    shots = short.get("shots", [])
    out = []
    places: dict[str, list[str]] = {}
    sigs: dict[tuple, list[str]] = {}
    people = 0
    for sh in shots:
        still = sh.get("still") or ""
        p = scene_place(still)
        if p:
            places.setdefault(p[0], []).append(sh["id"])
        size = SIZE.search(still)
        sigs.setdefault(((size.group(0).lower() if size else "?"), p[0] if p else "?", bool(PERSON.search(still))), []).append(sh["id"])
        people += bool(PERSON.search(still))
    for key, ids in places.items():
        if len(ids) >= 3:
            out.append({"rule": "place_repeat", "text": f"{len(ids)} shots are set in the same place ({key}): {', '.join(ids)}", "shots": ids})
    for (size, place, person), ids in sigs.items():
        if len(ids) >= 3 and size != "?":
            out.append({"rule": "composition_repeat", "text": f"{len(ids)} shots use the same size and place ({size}, {place}, {'with a person' if person else 'no person'}): {', '.join(ids)}", "shots": ids})
    if shots and people * 3 < len(shots):
        out.append({"rule": "few_people", "text": f"only {people} of {len(shots)} shots show a person", "shots": []})
    return out


# ── the run ──────────────────────────────────────────────────────────────────────

def stamp(short: dict) -> str:
    """A fingerprint of everything the check looks at, so the Next bar knows whether it has been run on the current prompts."""
    rows = [[sh["id"], sh.get("still"), sh.get("subjects"), sh.get("setting"), sh.get("must_show")] for sh in short.get("shots", [])]
    return hashlib.sha1(json.dumps([rows, [x.get("visual") for x in subj.of(short)]], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def current(short: dict) -> bool:
    return bool((short.get("lint") or {}).get("stamp") == stamp(short))


def drawn(short: dict, shot: dict) -> bool:
    """Whether a shot already has its start picture (a change to its prompt would make that picture old)."""
    from . import clips
    return bool(clips.chosen_keyframe(short, shot))


def tidy(short: dict, protect: bool = True) -> dict:
    """Tidy the plan's subjects and every shot. With `protect`, a shot whose picture is already drawn is left as it is (and listed as skipped), so nothing already made turns old."""
    changed: dict[str, list[str]] = {}
    skipped: dict[str, list[str]] = {}
    shots = short.get("shots", [])
    any_drawn = protect and any(drawn(short, sh) for sh in shots)
    for sub in subj.of(short):                                    # the subjects' looks are shared by every shot that shows them
        clean = clean_visual(sub["visual"])
        if clean != sub["visual"]:
            if any_drawn:
                skipped.setdefault("plan", []).append(f"numbers in the look of \"{sub['name']}\" (pictures are already drawn)")
            else:
                sub["visual"] = clean
                changed.setdefault("plan", []).append(f"took the numbers out of the look of \"{sub['name']}\"")
    for sh in shots:
        probe = json.loads(json.dumps(sh))
        what = tidy_shot(short, probe)
        if not what:
            continue
        if protect and drawn(short, sh):
            skipped[sh["id"]] = what
        else:
            tidy_shot(short, sh)
            changed[sh["id"]] = what
    return {"changed": changed, "skipped": skipped}


async def write_fix(short: dict, backend, s: dict, protect: bool) -> list[str]:
    """Ask the picture writer again, once, for the shots whose prompts still ask for text or have a vague group (only the writer can fix those). Returns the shot ids written."""
    from . import stillwriter
    bad: dict[str, list[str]] = {}
    for f in findings(short):
        if f["fix"] == "writer":
            sh = next(x for x in short["shots"] if x["id"] == f["shot"])
            if protect and drawn(short, sh):
                continue
            bad.setdefault(sh["beat"], []).append(f)
    written: list[str] = []
    for beat_id, items in bad.items():
        beat = next(b for b in short["beats"] if b["id"] == beat_id)
        shots = [sh for sid in beat["shot_ids"] for sh in short["shots"] if sh["id"] == sid]
        ids = {f["shot"] for f in items}
        note = ("Rewrite these pictures. " + " ".join(f["text"] + "." for f in items) + " Show a screen only as a soft glow, a banknote as plain coloured paper, a sign as a blank board, and "
                "say exactly how many people a group has (for example \"a family of three people: a man on the left, a woman in the middle, a child on the right\").")
        if await stillwriter.write_beat(short, beat, shots, backend, s, only=ids, note=note):
            written.extend(sorted(ids))
    return written


async def apply_to(short: dict, backend=None, s: dict | None = None, protect: bool = True) -> dict:
    """Run the check on a short in place (the caller saves it): the code fixes, then one rewrite for what only the writer can fix, then the notes. Returns the report, also kept in short["lint"]."""
    if not enabled(short):
        return report(short)
    first = tidy(short, protect)
    written: list[str] = []
    if backend is not None:
        try:
            written = await write_fix(short, backend, s, protect)
        except Exception as e:  # noqa: BLE001 - the check never stops a short
            print(f"[lint] rewrite failed: {e}", flush=True)
    second = tidy(short, protect)
    changed = first["changed"]
    for k, v in second["changed"].items():
        changed.setdefault(k, []).extend(v)
    skipped = {**first["skipped"], **second["skipped"]}
    left = findings(short)
    short["lint"] = {"at": time.time(), "stamp": "", "changed": changed, "skipped": skipped, "rewritten": written, "unresolved": left, "notes": notes(short)}
    short["lint"]["stamp"] = stamp(short)
    return report(short)


async def apply(short_id: str, backend=None, s: dict | None = None, protect: bool = True) -> dict:
    from . import store
    short = store.get(short_id)
    rep = await apply_to(short, backend, s, protect)
    store.save(short)
    return rep


def report(short: dict) -> dict:
    """What the screen shows: whether the check is on, whether it has run on the current prompts, what it changed, what it left alone and what it still finds."""
    last = short.get("lint") or {}
    on = enabled(short)
    return {"enabled": on, "current": current(short) if on else True, "at": last.get("at"), "changed": last.get("changed", {}), "skipped": last.get("skipped", {}), "rewritten": last.get("rewritten", []),
            "unresolved": findings(short) if on else [], "notes": notes(short) if on else []}
