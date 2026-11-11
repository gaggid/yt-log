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
MAX_STATIC = 2                          # at most this many shots of a short may hold the camera still
STILL = re.compile(r"\b(?:stands?|sits?|remains?|stays?|holds?|waits?|is)\s+(?:still|steady|motionless|frozen|fixed|in place)\b", re.I)         # a subject that "stands still" is not an action
LOOK_SIZE = "360x640"                    # the start pictures the writer looks at are shown small
LOOKS = re.compile(r"\b(wearing|dressed in|dressed|looks like|appearance|features|complexion|hairstyle|outfit|photograph|illustration|painting|style|aesthetic|noir|cinematic|dramatic)\b", re.I)
WEAK = re.compile(r"\b(slightly|subtly|barely|a little|a bit)\b", re.I)
AMBIENT = re.compile(r"\b(dust|particles?|motes?|breeze|wind|pollen)\b", re.I)
KINDS = (("static", r"\bstatic\b|\blocked\b|(?:remains|stays|holds|held|is|kept)\s+(?:a\s+)?(?:still|steady|fixed|firm)\b|steady position|does not move"), ("push", r"\bpush|zoom(s)? in|dolly in|moves? in|closer"), ("pull", r"\bpull|zoom(s)? out|dolly out|back(s)? away|retreat"),
         ("pan", r"\bpan"), ("tilt", r"\btilt|\brises\b|\bdescends\b|\bcrane"), ("orbit", r"\borbit|\barcs?\b|sweeps around|circles"), ("track", r"\btrack|\bfollows?\b"), ("handheld", r"handheld|\bsway"))
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

HOW TO WRITE A "move" (15 to 45 words, plain present-tense sentences, English):
1. THE SUBJECT'S ACTION first: one clear verb with the part of the body or object that moves and where it goes ("the man slowly lifts the phone toward his face", "both hands tighten on the steering wheel", "the right jet banks away to the left"). One action, or two steps in order ("first ... then ..."), never more.
2. THE CAMERA, in plain words, with a direction and how far it goes, so the model really moves it: "the camera pushes in until the man's face fills the frame", "the camera pans left across the whole group", "the camera rises from the boots up to the face", "the camera sweeps around the jet to its other side", "slow handheld sway". Pick a move that differs from the shot before it and the shot after it (never the same move twice in a row). A static camera is for at most one shot in five, and only when the subject's own movement is the whole shot. Use the planner's camera as a hint, not a rule.
3. A MOTION IN THE SURROUNDINGS only when the picture description names something that can move there (smoke, flags, rain, water, snow, cloth, leaves, lights, a screen). Never add dust, particles, motes, a breeze or wind unless the picture description names them.
4. SPEED AND SIZE fit the seconds: the shot lasts only the given seconds. Under 2 seconds: two or three short sentences, the subject's action, the camera, and (when the picture names something that can move in the surroundings, such as water, clouds, cloth, leaves, a screen) one motion of it. 2 to 3 seconds: up to three sentences. Never more than three, and never one that needs more time than the shot has. KEEP IT CALM AND CLEAR: one main action, one camera move, at most one motion of the surroundings; never add actions to fill the time, and never make two people do different things at once unless the picture's story is exactly that. Use "slowly", "steadily" or "quickly". Never an action that needs more time than the shot has (no walking across a room in 2 seconds).
4b. MAKE THE MOVEMENT BIG ENOUGH TO SEE: say how far and what moves ("turns his whole head to the left", "steps forward two paces", "the hand closes into a fist"). Never use "slightly", "subtly", "barely" or "a little": the model then hardly moves anything.
5. TIME IT TO THE NARRATION: the viewer hears the beat's line while the shot plays. The key movement is what the line is about (a start at "the phone pings", a turn at "the door"). If the shot's job is only a pause, the subject holds still with one tiny movement (breathing, a blink, a finger tightening) and the camera carries the shot.
6. Keep what is in the picture: no new person, object or place appears, nothing leaves the frame unless the picture shows how (a door that is in frame can swing open). No cuts, no scene change, no text.
7. ONLY POSITIVE WORDS: never no, not, without, never, nothing. Say what moves, not what stays.
8. NEVER describe looks: no clothes, hair, colours of things, faces, materials, light mood, mood words, style words. Expressions are allowed only as a movement ("his brow tightens", "her eyes widen").
9. Exact counts where more than one thing moves ("both hands", "the two jets", "the three men"). Say which one moves when there are two ("the woman on the right reaches out, the man on the left stays still").

10. If a line "MOTION FEEL" is given, shape every move to that rhythm and kind of movement, in plain movement words. Never name the style or the medium itself.

If PICTURES are attached, they are the real start pictures of the shots, in the order given. LOOK at each one: write the motion for what is really in it (who and what is there, where they are, which way they face, what is in reach), and when the picture differs from the text description, trust the picture. Move only things you can see.

Test every move before you answer: could Wan draw a different clip from these words (which subject? how far? how fast? what does the camera do)? Then fix it. Does the motion fit the seconds?"""


def camera_kind(text: str) -> str:
    """The kind of camera move a motion line asks for (static, push, pull, pan, tilt, orbit, track, handheld), '' when it names none. The sentence about the camera is looked at first."""
    sents = [x for x in re.split(r"(?<=[.!?])\s+", text) if re.search(r"\bcamera\b|\bhandheld\b", x, re.I)] or [text]
    for sentence in sents:
        for name, rx in KINDS:
            if re.search(rx, sentence, re.I):
                return name
    return ""


def sentences(text: str) -> int:
    return len([x for x in re.split(r"(?<=[.!?])\s+", text.strip()) if x])


def problems(item: MoveOut, seconds: float | None = None, picture: str = "", before_kind: str = "", static_budget_left: bool = True) -> list[str]:
    """What is wrong with one motion line. `seconds` (the shot's length), `picture` (the picture description), `before_kind` (the camera move of the shot before) and `static_budget_left` switch on the
    checks that need them."""
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
    m = WEAK.search(item.move)
    if m:
        out.append(f"{item.id}: \"{m.group(0)}\" makes the model barely move; say how far and what moves")
    body = [x for x in re.split(r"[.!?;,]\s+|\s+(?:while|as|and)\s+", item.move.strip()) if x.strip(" .") and not re.search(r"\bcamera\b|\bhandheld\b", x, re.I)]        # clauses that are not about the camera
    if CAMERA.search(item.move) and not body:
        out.append(f"{item.id}: only the camera moves; say what the subject or the surroundings do too (one clear movement, not a busy one)")
    elif body and all(STILL.search(x) for x in body):
        out.append(f"{item.id}: \"stands still\" is not a movement; say what the subject does (one clear movement, for example a turn of the head or a step forward)")
    if seconds is not None:
        n = sentences(item.move)
        if n > 3:
            out.append(f"{item.id}: at most three sentences, not {n}")
    for m in AMBIENT.finditer(item.move):
        if picture and not re.search(rf"\b{re.escape(m.group(0))}", picture, re.I):
            out.append(f"{item.id}: \"{m.group(0)}\" is not in the picture description; move only things it names (or leave the surroundings still)")
            break
    kind = camera_kind(item.move)
    if kind and before_kind and kind == before_kind:
        out.append(f"{item.id}: the camera move ({kind}) repeats the shot before; choose a different one")
    elif kind == "static" and not static_budget_left:
        out.append(f"{item.id}: too many static cameras in this short; give this shot a camera move with a direction")
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


def picture_of(short: dict, shot: dict) -> tuple[dict, str] | None:
    """(the chosen start picture's media row, a small data URL of it) for a shot that has one, else None."""
    from . import clips, frames, wan                                  # imported here: clips imports the planner, which imports this module
    from story3 import store as media
    kf = clips.chosen_keyframe(short, shot)
    if not kf:
        return None
    try:
        return kf, wan.data_url(frames.crop_916(media.path_of(kf).read_bytes(), LOOK_SIZE, 82), "image/jpeg")
    except Exception:  # noqa: BLE001 - a picture that cannot be read is simply not shown to the writer
        return None


def unseen(short: dict) -> list[dict]:
    """The shots whose start picture exists but whose motion was not written while looking at it (the picture is new or was redone). A shot whose look failed once for this picture is left alone."""
    from . import clips
    out = []
    for sh in short["shots"]:
        if not eligible(sh):
            continue
        kf = clips.chosen_keyframe(short, sh)
        if kf and kf["id"] not in (sh.get("move_pic"), sh.get("move_pic_fail")) and not clips.chosen_clip(short, sh):      # a clip already made stays valid: its motion is not rewritten under it
            out.append(sh)
    return out


async def write_beat(short: dict, beat: dict, shots: list[dict], backend, s: dict | None = None, only: set[str] | None = None, note: str = "", look: bool = True) -> int:
    """Write `move` for the shots of one beat in place (all, or the ids in `only`). A shot that already has its start picture is written while LOOKING at it (the picture is sent with the question) and
    remembers which picture it was written for (`move_pic`); `look=False` writes from the text only. Returns how many were written; 0 when the call failed (the shots keep what they had)."""
    s = s or settings_mod.get()
    todo = [sh for sh in shots if eligible(sh) and (only is None or sh["id"] in only)]
    if not todo:
        return 0
    seen = {sh["id"]: p for sh in todo if (p := picture_of(short, sh))} if look else {}
    caller = llm.JsonCaller(backend, s)
    ids = [sh["id"] for sh in todo]

    by_id = {sh["id"]: sh for sh in shots}
    placed = [camera_kind(sh.get("move", "")) for sh in short["shots"] if sh["id"] not in ids and sh.get("move")]
    i = next((k for k, b in enumerate(short["beats"]) if b["id"] == beat["id"]), 0)
    prev = [sh for b in short["beats"][max(0, i - 1):i] for sid in b["shot_ids"] for sh in short["shots"] if sh["id"] == sid]
    kind_before = camera_kind(prev[-1].get("move", "")) if prev and prev[-1].get("move") else ""

    def check(out: MovesOut) -> None:
        if caller.last_attempt:
            return
        if [x.id for x in out.shots] != ids:
            raise ValueError("write exactly these shots, in this order: " + ", ".join(ids))
        bad, last, statics, total = [], kind_before, sum(k == "static" for k in placed), len(placed)
        for x in out.shots:
            sh = by_id.get(x.id) or {}
            k = camera_kind(x.move)
            total += 1
            budget = (statics + (k == "static")) <= min(MAX_STATIC, max(1, round(0.2 * total)))
            bad += problems(x, float(sh.get("seconds") or 2), f"{sh.get('still', '')} {sh.get('prompt', '')}", last, budget)
            statics += k == "static"
            last = k or last
        if bad:
            raise ValueError("; ".join(bad[:5]))

    user = _context(short, beat, shots, only) + (f"\n\nTHE PRODUCER'S INSTRUCTION (follow it; it wins over the planner's idea): {note.strip()}" if note.strip() else "")
    shown = [i for i in ids if i in seen]
    if shown:
        user += f"\n\nPICTURES attached, in this order: {', '.join(shown)}. Look at them before you write." + ("" if len(shown) == len(ids) else f" The other shots have no picture yet: {', '.join(i for i in ids if i not in seen)}.")
    user += f"\n\nWrite the motion of: {', '.join(ids)}."
    try:
        res = await caller.call(SYSTEM, user, MovesOut, validate=check, images=[seen[i][1] for i in shown] or None)
    except llm.LLMError:
        for i in shown:
            by_id[i]["move_pic_fail"] = seen[i][0]["id"]                   # the picture could not be looked at: the written motion stands and the step does not ask again
        return 0
    by = {x.id: x for x in res.value.shots}
    n = 0
    for sh in todo:
        x = by.get(sh["id"])
        if x and x.move.strip():
            sh["move"] = re.sub(r"\s+", " ", x.move).strip()
            sh["move_by"] = "writer"
            if sh["id"] in seen:
                sh["move_pic"] = seen[sh["id"]][0]["id"]
                sh.pop("move_pic_fail", None)
            n += 1
    return n


async def write_seen(short: dict, backend, s: dict | None = None, progress=None, only: set[str] | None = None) -> int:
    """Write the motion again for every shot whose start picture has not been looked at yet (the auto-run step after the start pictures, and the Make clips button). Beat by beat, so each call has the neighbours' moves.
    `only` limits it to those shots."""
    todo = {sh["id"] for sh in unseen(short) if only is None or sh["id"] in only}
    total = 0
    for i, b in enumerate(short["beats"]):
        shots = [sh for sid in b["shot_ids"] for sh in short["shots"] if sh["id"] == sid]
        ids = {sh["id"] for sh in shots} & todo
        if not ids:
            continue
        if progress:
            progress(i, len(short["beats"]), f"looking at the pictures of beat {i + 1} of {len(short['beats'])}")
        total += await write_beat(short, b, shots, backend, s, only=ids)
    return total


async def write_all(short: dict, backend, s: dict | None = None, progress=None, note: str = "") -> int:
    total = 0
    for i, b in enumerate(short["beats"]):
        if progress:
            progress(i, len(short["beats"]), f"writing the motion of beat {i + 1} of {len(short['beats'])}")
        shots = [sh for sid in b["shot_ids"] for sh in short["shots"] if sh["id"] == sid]
        total += await write_beat(short, b, shots, backend, s, note=note)
    return total


async def look_first(short_id: str, backend, s: dict | None = None, progress=None, only: set[str] | None = None) -> str:
    """Before clips are made (the Make clips button; auto-run has its own step): write the motion of every shot that has a start picture but was not written while looking at it. Returns a plain sentence
    for the screen, or "" when there was nothing to do. A failure never stops the clips, but it is always said: the clips then use the motion written before, from the text."""
    from . import pipelines as P, store
    short = store.get(short_id)
    if not P.keyframes_on(short):
        return ""
    todo = [sh["id"] for sh in unseen(short) if only is None or sh["id"] in only]
    if not todo:
        return ""
    try:
        n = await write_seen(short, backend, s, progress, only=set(todo))
        store.save(short)
    except Exception as e:  # noqa: BLE001
        return f"The motion was NOT written from the pictures ({str(e)[:100]}); these clips use the motion written before."
    if n == len(todo):
        return f"Motion written while looking at {n} start picture(s)."
    return f"Motion written from the pictures for {n} of {len(todo)} shots; the other {len(todo) - n} could not be looked at and keep the motion written before."

