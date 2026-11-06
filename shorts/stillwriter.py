"""The picture writer: Gemma writes the start-picture prompt of every shot for the image model (Qwen Image) instead of the shot planner adding it on the side of a dozen other fields.
Qwen draws exactly the words it is given, puts things where the words are loosely placed, ignores "no x" (and so draws x), and fills every vague count with a crowd. So each prompt is written by a call
that does only this: it sees the narration the picture must prove, the subjects, the neighbouring pictures and the rules below, tests every prompt as the image model would read it, and also lists
the 2 to 4 facts the picture must satisfy (`must_show`, kept on the shot for the person who looks at the picture). Code then adds the fixed looks once (shorts/stills.py).
A failed call never stops a plan: the shot keeps the `still` the shot planner wrote."""
import re

from story import llm, settings as settings_mod
from story.schemas import Str, StrList
from story2.schemas import M

from . import cast, subjects as subj

MIN_WORDS, MAX_WORDS = 15, 70
VAGUE = re.compile(r"\b(many|several|multiple|numerous|dozens?|hundreds?|thousands?|crowds?|crowded|group of|groups of|swarm|army of|lots of|a number of|some|few|bunch(?:es)? of|handful)\b", re.I)
NEGATION = re.compile(r"\b(no|not|without|never|instead of|rather than|nothing|none|isn't|aren't|doesn't|don't|empty of)\b", re.I)
BIG_COUNT = re.compile(r"\b(?:six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|hundred|[6-9]|[1-9]\d+)\s+(?!o'clock|am\b|pm\b|years?|months?|days?|hours?|minutes?|seconds?|percent|%)[a-z]", re.I)
FILLER = re.compile(r"\b(sleek|beautiful|stunning|ethereal|haunting|ominous|menacing|majestic|epic|cinematic|dramatic|moody|gritty|gleaming|shimmering|mysterious|powerful|imposing|grey metal|metallic)\b", re.I)


class StillOut(M):
    id: Str
    still: Str
    must_show: StrList = []


class StillsOut(M):
    shots: list[StillOut]


SYSTEM = """[TASK:p4_still]
You write the PICTURE PROMPT of each shot of a vertical video short, for Qwen Image, an image model with these habits:
- It draws EXACTLY what the words say, and puts a thing wherever the words leave it open. "A fighter jet with missiles" gets missiles on top of the wing; "a car" gets its exhaust wherever. So you say where every important part is.
- It cannot read a negative. "No missiles on top" draws missiles on top. Say only what is there, and where.
- A vague amount ("many jets", "a crowd", "several") becomes a dozen or a crowd. So you give an exact number for everything countable: "three fighter jets", "one man", "two missiles".
- It does not know the story. Everything the viewer must understand has to be visible in the picture.

Return ONLY a JSON object: {"shots": [{"id": "s1", "still": "...", "must_show": ["...", "..."]}]}  (one entry for each shot to write, same ids, same order)

HOW TO WRITE A "still" (25 to 55 words, plain present-tense sentences, English):
1. START with the shot size and angle, then the subject: "Low-angle wide shot of three fighter jets ...", "Close-up of one man's face ...". The first words matter most.
2. THE PICTURE PROVES THE LINE. Read the narration of the beat and the shot idea: show the claim itself (the proof, the object, the moment), not a topic or a mood. If the narration says the missiles hang under the wings, the picture is the missiles under the wings.
3. EXACT COUNTS in every sentence: "one", "two", "three" ... Never many, several, some, a group, a crowd, a swarm, dozens, formation without a number. Choose the smallest number that tells the story (usually one to three; at most five).
4. SAY WHERE PARTS ARE, in words an artist could follow: under, above, behind, in front of, at the rear of, at the front of, left of, right of, in the foreground, on the roof of, beneath each wing. For a machine or vehicle name the part and its place ("the exhaust pipe at the rear bumper, the headlights at the front", "one missile on a pylon beneath each wing, the top of the wings bare"). For two people or things say who stands on which side and which way they face.
5. SAY WHAT IT IS, NOT WHAT IT IS MADE OF. No filler like "grey metal", "sleek", "beautiful", "ethereal", "haunting", "dramatic", "cinematic", "moody", "powerful". Use a colour or material only when it tells things apart or is needed to recognise them (a red and yellow star roundel, a yellow helmet).
6. ONE MOMENT: one action, one expression, at most three subjects in frame, the background in five words or fewer. No second scene, no split screen, no collage.
7. ONLY POSITIVE WORDS: never no, not, without, never, instead of, nothing. State what is there instead ("the top of the wings bare" not "no missiles on top").
8. DO NOT REPEAT what code adds: the looks of the people and the named subjects (their faces, hair, clothes, markings), the place's colours, the style, the lighting mood and the "no text" rule. A CAST member is drawn from reference pictures: call them by their cast name and say only what they do, where they stand and which way they face; never describe their face, hair, skin or clothes, and with two cast members say who is on the left and who on the right. Refer to a subject by its short name ("the man", "the Ghostly Woman", "the J-20") and say only what it DOES and WHERE. A person who is not a listed subject is described by role and age only.
9. NO text, signs, screens with words or numbers to read; show a screen only as a glow or a shape.
10. Each shot differs from the shots next to it in subject, place or framing.
11. LIGHT BY DEFAULT: set every shot in bright daylight or a bright, well-lit room with a real, recognisable background. Go dark (night, dim room, deep shadow) only when the beat's feeling is fear, dread, threat or grief, or its narration says night or darkness. Never a black void, empty dark space or cosmic background.

TEST every prompt before you answer: read it as the image model would, one word at a time. Could a different picture also fit the words (a count left open, a part with no place, a left-right left open)? Then fix the prompt. Also check it against the narration: does a viewer hearing the line see its proof?
"must_show": 2 to 4 short facts the finished picture must satisfy, each checkable at a glance ("exactly 3 jets", "missiles under the wings", "exhaust at the back of the car"). Written positively."""


def problems(item: StillOut) -> list[str]:
    out: list[str] = []
    t = item.still
    n = len(t.split())
    if n < MIN_WORDS or n > MAX_WORDS:
        out.append(f"{item.id}: {n} words; write {MIN_WORDS} to {MAX_WORDS}")
    for rx, what in ((VAGUE, "a vague amount (give an exact number)"), (NEGATION, "a negative (say what IS there and where)"), (FILLER, "filler or style words (say what it is, not what it is made of)")):
        m = rx.search(t)
        if m:
            out.append(f"{item.id}: \"{m.group(0)}\" is {what}")
    big = BIG_COUNT.search(t)
    if big:
        out.append(f"{item.id}: \"{big.group(0)}\" is too many to draw (the image model cannot count above five): show at most five and let the picture suggest the rest")
    if re.search(r"\bsplit screen|collage|diptych|side by side\b", t, re.I):
        out.append(f"{item.id}: one picture only, no split screen or collage")
    return out


def _context(short: dict, beat: dict, shots: list[dict], only: set[str] | None) -> str:
    plan = short["plan"]
    beats = short["beats"]
    i = next((k for k, b in enumerate(beats) if b["id"] == beat["id"]), 0)
    lines = [f"WHOLE SHORT: {plan.get('title', '')} - {plan.get('logline', '')}", f"MAIN PLACE (its look is added by code): {plan.get('place', '') or 'none'}"]
    if plan.get("character"):
        lines.append(f"MAIN CHARACTER (look added by code; write \"the man\" / \"the woman\" etc.): {plan['character']}")
    members = [m for m in cast.members(short) if m["char"]]
    if members:
        lines.append("CAST (drawn from library pictures; their looks are fixed by those pictures): " + "; ".join(f"{m['char']['name']} ({m['char'].get('kind', 'person')})" for m in members))
    if subj.of(short):
        lines.append("SUBJECTS (their looks are added by code, so you do not repeat them; they tell you what each one is and has):\n" + "\n".join(f"- {x['name']} ({x['kind'] or 'subject'}): {subj.plain_visual(x['visual'])}" for x in subj.of(short) if subj.drawable(x)))
    if i:
        lines.append("THE BEAT BEFORE: " + " ".join(x["text"] for x in beats[i - 1]["sentences"]))
    lines.append(f"FEELING OF THIS BEAT: {beat.get('feeling') or 'neutral'}")
    lines.append(f"THIS BEAT (the picture proves it; the viewer hears it while the shots play): " + " ".join(x["text"] for x in beat["sentences"]))
    if i + 1 < len(beats):
        lines.append("THE BEAT AFTER: " + " ".join(x["text"] for x in beats[i + 1]["sentences"]))
    ideas = beat.get("ideas") or []
    rows = []
    for k, sh in enumerate(shots):
        row = f"- {sh['id']}" + ("" if only is None or sh["id"] in only else " (KEEP, already written; do not return it)") + f": idea: {ideas[k]['idea'] if len(ideas) == len(shots) else sh['prompt']}"
        cn = [m["char"]["name"] for m in members if m["char"]["id"] in (sh.get("cast") or [])]
        row += f" | subjects: {', '.join(sh['subjects']) or 'none'} | main character: {'yes' if sh.get('character') else 'no'}" + (f" | cast in the shot: {', '.join(cn)}" if cn else "") + f" | camera: {sh.get('camera', 'static')}"
        if sh.get("still") and only is not None and sh["id"] not in only:
            row += f" | written: {sh['still']}"
        rows.append(row)
    lines.append("THE SHOTS OF THIS BEAT, in order:\n" + "\n".join(rows))
    near = [sh for b in beats[max(0, i - 1):i] for sid in b["shot_ids"] for sh in short["shots"] if sh["id"] == sid][-2:]
    if near:
        lines.append("THE LAST PICTURES BEFORE (do not repeat them):\n" + "\n".join(f"- {sh['id']}: {sh.get('still', '')}" for sh in near))
    return "\n\n".join(lines)


async def write_beat(short: dict, beat: dict, shots: list[dict], backend, s: dict | None = None, only: set[str] | None = None, note: str = "") -> int:
    """Write the `still` and `must_show` of the shots of one beat in place (all of them, or only the ids in `only`). Returns how many were written; 0 when the call failed (the shots keep what they had)."""
    s = s or settings_mod.get()
    todo = [sh for sh in shots if only is None or sh["id"] in only]
    if not todo:
        return 0
    caller = llm.JsonCaller(backend, s)
    ids = [sh["id"] for sh in todo]

    def check(out: StillsOut) -> None:
        if caller.last_attempt:
            return
        if [x.id for x in out.shots] != ids:
            raise ValueError("write exactly these shots, in this order: " + ", ".join(ids))
        bad = [p for x in out.shots for p in problems(x)]
        if bad:
            raise ValueError("; ".join(bad[:5]))

    user = _context(short, beat, shots, only) + (f"\n\nTHE PRODUCER'S INSTRUCTION (follow it; it wins over the idea when they disagree): {note.strip()}" if note.strip() else "") + f"\n\nWrite the pictures of: {', '.join(ids)}."
    try:
        res = await caller.call(SYSTEM, user, StillsOut, validate=check)
    except llm.LLMError:
        return 0
    by = {x.id: x for x in res.value.shots}
    n = 0
    for sh in todo:
        x = by.get(sh["id"])
        if x and x.still.strip():
            sh["still"] = re.sub(r"\s+", " ", x.still).strip()
            sh["must_show"] = [m.strip() for m in x.must_show if m.strip()][:4]
            sh["still_by"] = "writer"
            n += 1
    return n


async def write_all(short: dict, backend, s: dict | None = None, progress=None, note: str = "") -> int:
    """The pictures of every beat again (after the shots exist). Returns how many were written."""
    total = 0
    for i, b in enumerate(short["beats"]):
        if progress:
            progress(i, len(short["beats"]), f"writing the picture prompts of beat {i + 1} of {len(short['beats'])}")
        shots = [sh for sid in b["shot_ids"] for sh in short["shots"] if sh["id"] == sid]
        total += await write_beat(short, b, shots, backend, s, note=note)
    return total
