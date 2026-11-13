"""The subjects of a short: the specific people, machines, organisations, places, products or programs the story is about, each with the exact name and a concrete look. The image and video
models draw every word literally and know nothing about the story, so a shot that says "a fighter jet" gets a generic jet. The plan keeps the subjects once (plan["subjects"]); a shot names
the ones it shows (shot["subjects"]), and code adds their looks to the start-picture and clip prompts, the same way it adds the main character and the place."""
import re

from story import llm, settings as settings_mod
from story.schemas import Str
from story2.schemas import M

MAX_SUBJECTS = 10


class SubjectOut(M):
    name: Str
    kind: Str = ""
    visual: Str


class SubjectsOut(M):
    subjects: list[SubjectOut]


SYSTEM = """[TASK:p4_subjects]
You list the SUBJECTS of a short video: the specific things the facts are about, so that pictures can show them exactly. A subject is a named or distinct person, group or force, machine or vehicle,
organisation, place, product, animal or software. Keep every side of a story: a story about two countries has subjects for BOTH, and each looks different from the other.

Return ONLY a JSON object: {"subjects": [{"name": "...", "kind": "person | group | machine | organisation | place | product | software | other", "visual": "..."}]}

- At most 10, the most important first. Do not stop at machines: when the facts allow, also list the people who use them (pilots, crew, soldiers, engineers, leaders), the places, a place, an object or a person from the period of history the facts mention, and an object that proves a point. A period, an era, an idea or a feeling is never a subject: it cannot be drawn. Use the exact names the facts use (and the common short form, for example "Chinese J-20 stealth fighter").
- "visual" is English, 20 to 45 words, one concrete description an image model can draw WITHOUT knowing the story: shape, size, colours, markings, insignia, clothing, materials, the setting it is usually seen in. Show it in bright daylight against a light, real background; never a dark void, black space or cosmic background unless the story is set there.
  EVERY machine, vehicle, person or group MUST say whose it is by what can be seen: the national roundel or flag colours on aircraft and vehicles (for example a red and yellow star on Chinese aircraft, an orange, white and green roundel on Indian aircraft), the uniform, the logo shown only as a shape (no readable text), a software window by its layout and theme.
  Never write the subject's name inside the visual as text to be printed; describe how it looks.
- Real machines and people are drawn as they really look: if you know the real appearance, describe it (for example a twin-engine stealth fighter with canards and a dark grey finish with a red and yellow star roundel); if you do not know it, say what the facts say and stay plain.
- When the facts name only a class (for example "Chinese stealth fighters" or "Indian fighters"), name the best-known real example in the subject for the picture, such as "Chinese stealth fighter (J-20)" or "Indian Su-30MKI fighter", and describe that real machine. This is for the pictures only; the narration says only what the facts say.
- Describe what makes it RECOGNISABLE and where its parts are (for example: twin tail fins, a long nose, wing pylons beneath the wings, the exhaust pipe at the rear), never filler like "grey metal", "sleek", "powerful" or "beautiful".
- Prefer what can be SEEN: a force or an organisation is shown by its machines, people or uniforms, so list those instead of the bare organisation. Do not list the same thing twice.
- Nothing graphic: no gore, no weapons aimed at anyone. No text, numbers or logos to be read in the picture.
"""


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


NOT_DRAWABLE = re.compile(r"\b(period|era|epoch|age of|history|historical|idea|concept|theme|feeling|mood|emotion|time)\b", re.I)
CAMERA_WORDS = re.compile(r",?\s*(?:seen |viewed |shown |photographed )?(?:from|in|with) an? (?:macro|close-up|wide|low-angle|high-angle|aerial|top-down|bird's-eye|ground-level)[a-z' -]{0,20}(?:perspective|view|angle|lens|shot)\b", re.I)


def drawable(sub: dict) -> bool:
    """A subject the picture can show: not a period, an idea or a feeling (a model sometimes lists \"The Construction Era\", and a shot then names it as if it were a place)."""
    return not (NOT_DRAWABLE.search(sub.get("kind", "")) or NOT_DRAWABLE.search(sub.get("name", "")))


def plain_visual(text: str) -> str:
    """A subject's look without camera words ("seen from a macro perspective"): the shot chooses the camera, and a macro or photographic phrase in a look pulls the whole picture toward a real photograph, whatever the style."""
    return CAMERA_WORDS.sub("", text or "").strip(" ,")


# A subject's look often carries its own scene: "standing on a podium", "parked on a clean paved driveway", "leaning against a brick wall", "sitting on a large wooden table in the center of a bright room".
# In a shot that shows only part of it the shot says where it is, so these clauses would draw a podium, a driveway or a wall that the shot never asked for.
POSE_CLAUSE = re.compile(r",?\s*\b(?:standing|sitting|sits|stands|parked|leaning|lying|resting|placed|kept|hanging|walking|running|positioned|set)\b[^.;]*?\b(?:on|in|at|against|beside|near|inside|outside|under|over|before|by|across|along)\b[^.;]*", re.I)


def appearance(text: str) -> str:
    """A subject's look without camera words and without where it stands or what it does ("standing on a podium", "parked on a driveway"): what it IS and looks like. Never empty: when every
    clause is a pose the plain look is kept."""
    t = plain_visual(text)
    cut = re.sub(r"\s{2,}", " ", POSE_CLAUSE.sub("", t)).strip(" ,;")
    return cut if len(cut.split()) >= 3 else t


def of(short: dict) -> list[dict]:
    return [x for x in (short.get("plan") or {}).get("subjects") or [] if x.get("name") and x.get("visual")]


def clean(items: list[dict]) -> list[dict]:
    out, seen = [], set()
    for x in items:
        name = re.sub(r"\s+", " ", str(x.get("name", ""))).strip()[:80]
        vis = re.sub(r"\s+", " ", str(x.get("visual", ""))).strip()[:500]
        if name and vis and _norm(name) not in seen:
            seen.add(_norm(name))
            out.append({"name": name, "kind": str(x.get("kind", "")).strip()[:20], "visual": vis})
    return out[:MAX_SUBJECTS]


def in_shot(short: dict, shot: dict) -> list[dict]:
    """The subjects a shot shows: the ones the planner listed for it, plus any whose name its own words mention (the model sometimes forgets to list one)."""
    subs = [x for x in of(short) if drawable(x)]
    if not subs:
        return []
    wanted = {_norm(n) for n in shot.get("subjects") or []}
    text = " " + _norm(f"{shot.get('prompt', '')} {shot.get('still', '')}") + " "
    out = []
    for s in subs:
        n = _norm(s["name"])
        if n in wanted or (n and f" {n} " in text):
            out.append(s)
    return out


def block(short: dict, shot: dict) -> str:
    """The sentence added to a shot's prompts. Empty when the shot shows no subject."""
    subs = in_shot(short, shot)
    if not subs:
        return ""
    return "Subjects in this shot: " + " ".join(f"{s['name']}: {plain_visual(s['visual']).rstrip('. ')}." for s in subs)


def parse_lines(text: str) -> list[dict]:
    """The editor's box: one subject per line, `Name: how it looks` (the dash also works)."""
    out = []
    for line in (text or "").splitlines():
        m = re.match(r"\s*(.+?)\s*(?::|\s[-–—]\s)\s*(.+)$", line)
        if m:
            out.append({"name": m.group(1), "kind": "", "visual": m.group(2)})
    return clean(out)


def to_lines(items: list[dict]) -> str:
    return "\n".join(f"{x['name']}: {x['visual']}" for x in items)


async def extract(short: dict, backend, s: dict | None = None) -> list[dict]:
    """Ask the chat model for the subjects of a short from its source and, when there is one, its narration."""
    from . import planner
    s = s or settings_mod.get()
    story = " ".join(x["text"] for b in short.get("beats", []) for x in b["sentences"])
    text = planner.source_text(short) + (f"\n\nTHE NARRATION SO FAR (the subjects it talks about must be listed):\n{story}" if story else "")

    def check(out: SubjectsOut) -> None:
        if not out.subjects:
            raise ValueError("list at least one subject")

    res = await llm.JsonCaller(backend, s).call(SYSTEM, text + "\n\nList the subjects now.", SubjectsOut, validate=check)
    return clean([x.model_dump() for x in res.value.subjects])
