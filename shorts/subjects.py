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

- At most 10, the most important first. Do not stop at machines: when the facts allow, also list the people who use them (pilots, crew, soldiers, engineers, leaders), the places, a period of history, and an object that proves a point. Use the exact names the facts use (and the common short form, for example "Chinese J-20 stealth fighter").
- "visual" is English, 20 to 45 words, one concrete description an image model can draw WITHOUT knowing the story: shape, size, colours, markings, insignia, clothing, materials, the setting it is usually seen in.
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
    subs = of(short)
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
    return "Subjects in this shot: " + " ".join(f"{s['name']}: {s['visual'].rstrip('. ')}." for s in subs)


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
