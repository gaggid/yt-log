"""The motion writer: Gemma writes what MOVES in each shot, for Wan 2.2 picture-to-video. Wan already has the start picture, so it must not be told what the picture shows (it takes the words as a
request and may redraw the face or shift the light). It needs only the movement: what the subject does, what the camera does, what moves in the surroundings, at what speed, in the few seconds the
shot is on screen. The call sees the narration the shot plays under, the shot's seconds, the final start-picture prompt (so it knows what exists in the frame) and the neighbouring shots' moves.
A failed call never stops a plan: the shot keeps the planner's prompt and camera (see pipelines.compose)."""
import re

from story import llm, settings as settings_mod
from story.schemas import Str
from story2.schemas import M

from . import looks
from .stillwriter import NEGATION

MIN_WORDS, MAX_WORDS = 12, 60
LOOKS = re.compile(r"\b(wearing|dressed in|dressed|looks like|appearance|features|complexion|hairstyle|outfit|photograph|illustration|painting|style|aesthetic|noir|cinematic|dramatic)\b", re.I)
CAMERA = re.compile(r"\b(camera|static|locked|pan|pans|panning|tilt|tilts|push|pushes|pull|pulls|dolly|orbit|orbits|arc|arcs|track|tracks|tracking|handheld|zoom|zooms|rack focus|crane|rises|descends)\b", re.I)


class MoveOut(M):
    id: Str
    move: Str


class MovesOut(M):
    shots: list[MoveOut]


SYSTEM = """[TASK:p4_move]
You write the MOTION PROMPT of each shot of a vertical video short. Wan 2.2 turns the shot's START PICTURE into a moving clip of a few seconds. The picture already shows everything: who and what is there, how they look, the place, the light, the style. Wan treats every word as an instruction, so words about looks make it redraw the picture.
So you write ONLY WHAT MOVES, and you refer to the things that move by their short name ("the man", "the phone", "the door", "the left jet") without describing them.

Return ONLY a JSON object: {"shots": [{"id": "s1", "move": "..."}]}  (one entry for each shot, same ids, same order)

HOW TO WRITE A "move" (20 to 45 words, plain present-tense sentences, English):
1. THE SUBJECT'S ACTION first: one clear verb with the part of the body or object that moves and where it goes ("the man slowly lifts the phone toward his face", "both hands tighten on the steering wheel", "the right jet banks away to the left"). One action, or two steps in order ("first ... then ..."), never more.
2. THE CAMERA, in plain words, with direction and speed: "the camera slowly pushes in toward the man's face", "the camera pans left to follow the jets", "static camera", "slow handheld sway", "the camera tilts down from the door to the floor". Pick a move that fits the shot and differs from the shots next to it; use the planner's camera as a hint, not a rule.
3. ONE small motion in the surroundings if it fits what is in the picture: dust drifting, a light flickering, rain falling, cloth moving, smoke curling, a screen glowing brighter. Only things the picture has.
4. SPEED AND SIZE fit the seconds: the shot lasts only the given seconds. Under 2 seconds: one small movement. 2 to 3 seconds: one clear movement. Use "slowly", "steadily" or "quickly". Never an action that needs more time than the shot has (no walking across a room in 2 seconds).
5. TIME IT TO THE NARRATION: the viewer hears the beat's line while the shot plays. The key movement is what the line is about (a start at "the phone pings", a turn at "the door"). If the shot's job is only a pause, the subject holds still with one tiny movement (breathing, a blink, a finger tightening) and the camera carries the shot.
6. Keep what is in the picture: no new person, object or place appears, nothing leaves the frame unless the picture shows how (a door that is in frame can swing open). No cuts, no scene change, no text.
7. ONLY POSITIVE WORDS: never no, not, without, never, nothing. Say what moves, not what stays.
8. NEVER describe looks: no clothes, hair, colours of things, faces, materials, light mood, mood words, style words. Expressions are allowed only as a movement ("his brow tightens", "her eyes widen").
9. Exact counts where more than one thing moves ("both hands", "the two jets", "the three men"). Say which one moves when there are two ("the woman on the right reaches out, the man on the left stays still").

10. If a line "MOTION FEEL" is given, shape every move to that rhythm and kind of movement, in plain movement words. Never name the style or the medium itself.

Test every move before you answer: could Wan draw a different clip from these words (which subject? how far? how fast? what does the camera do)? Then fix it. Does the motion fit the seconds?"""


def problems(item: MoveOut) -> list[str]:
    out: list[str] = []
    n = len(item.move.split())
    if n < MIN_WORDS or n > MAX_WORDS:
        out.append(f"{item.id}: {n} words; write {MIN_WORDS} to {MAX_WORDS}")
    for rx, what in ((NEGATION, "a negative (say what moves instead)"), (LOOKS, "a word about looks or style (the picture has it; say only what moves)")):
        m = rx.search(item.move)
        if m:
            out.append(f"{item.id}: \"{m.group(0)}\" is {what}")
    if not CAMERA.search(item.move):
        out.append(f"{item.id}: say what the camera does (for example \"the camera slowly pushes in\" or \"static camera\")")
    return out


def eligible(shot: dict) -> bool:
    """A talking avatar and a shot driven by a reference video are moved by their own models, not by words."""
    from . import avatar, motion as shotmotion                      # imported here: these modules import the planner
    return not avatar.is_avatar(shot) and not shotmotion.of(shot)


def _context(short: dict, beat: dict, shots: list[dict], only: set[str] | None) -> str:
    plan = short["plan"]
    beats = short["beats"]
    i = next((k for k, b in enumerate(beats) if b["id"] == beat["id"]), 0)
    lines = [f"WHOLE SHORT: {plan.get('title', '')} - {plan.get('logline', '')}"]
    lines.append("THE LINE THE VIEWER HEARS WHILE THESE SHOTS PLAY: " + (" ".join(x["text"] for x in beat["sentences"]) or "(no voice; the pictures tell it)"))
    if i + 1 < len(beats):
        lines.append("THE LINE AFTER: " + " ".join(x["text"] for x in beats[i + 1]["sentences"]))
    if looks.motion_hint(short):
        lines.append("MOTION FEEL (how things move in this short): " + looks.motion_hint(short))
    rows = []
    for sh in shots:
        row = f"- {sh['id']} ({sh.get('seconds') or '2'} s, planner's camera: {sh.get('camera', 'static')})"
        if only is not None and sh["id"] not in only:
            row += f" KEEP, already written, do not return it: {sh.get('move', '')}"
        else:
            row += f": what the picture shows: {sh.get('still') or sh['prompt']} | what the planner meant: {sh['prompt']}"
        rows.append(row)
    lines.append("THE SHOTS OF THIS BEAT, in order:\n" + "\n".join(rows))
    near = [sh for b in beats[max(0, i - 1):i] for sid in b["shot_ids"] for sh in short["shots"] if sh["id"] == sid][-2:]
    if near:
        lines.append("THE LAST MOVES BEFORE (vary the camera):\n" + "\n".join(f"- {sh['id']}: {sh.get('move', '')}" for sh in near if sh.get("move")))
    return "\n\n".join(lines)


async def write_beat(short: dict, beat: dict, shots: list[dict], backend, s: dict | None = None, only: set[str] | None = None, note: str = "") -> int:
    """Write `move` for the shots of one beat in place (all, or the ids in `only`). Returns how many were written; 0 when the call failed (the shots keep what they had)."""
    s = s or settings_mod.get()
    todo = [sh for sh in shots if eligible(sh) and (only is None or sh["id"] in only)]
    if not todo:
        return 0
    caller = llm.JsonCaller(backend, s)
    ids = [sh["id"] for sh in todo]

    def check(out: MovesOut) -> None:
        if caller.last_attempt:
            return
        if [x.id for x in out.shots] != ids:
            raise ValueError("write exactly these shots, in this order: " + ", ".join(ids))
        bad = [p for x in out.shots for p in problems(x)]
        if bad:
            raise ValueError("; ".join(bad[:5]))

    user = _context(short, beat, shots, only) + (f"\n\nTHE PRODUCER'S INSTRUCTION (follow it; it wins over the planner's idea): {note.strip()}" if note.strip() else "") + f"\n\nWrite the motion of: {', '.join(ids)}."
    try:
        res = await caller.call(SYSTEM, user, MovesOut, validate=check)
    except llm.LLMError:
        return 0
    by = {x.id: x for x in res.value.shots}
    n = 0
    for sh in todo:
        x = by.get(sh["id"])
        if x and x.move.strip():
            sh["move"] = re.sub(r"\s+", " ", x.move).strip()
            sh["move_by"] = "writer"
            n += 1
    return n


async def write_all(short: dict, backend, s: dict | None = None, progress=None, note: str = "") -> int:
    total = 0
    for i, b in enumerate(short["beats"]):
        if progress:
            progress(i, len(short["beats"]), f"writing the motion of beat {i + 1} of {len(short['beats'])}")
        shots = [sh for sid in b["shot_ids"] for sh in short["shots"] if sh["id"] == sid]
        total += await write_beat(short, b, shots, backend, s, note=note)
    return total
