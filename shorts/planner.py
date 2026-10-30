"""The two model steps of a short: the plan (title, narration in beats, the look) and the shots of each beat. The model writes; code decides the counts and the timing
(shorts/timeline.py), checks the words (banned phrases, script, length) and puts the character and place into every shot (shorts/pipelines.py), so the model never has to repeat them."""
import re

from story import llm, settings as settings_mod
from story.schemas import Str
from story2 import intake, leak, lexicon, maya, safety, svara, voices
from story2.schemas import M

from . import cast, models, prompts as P, store, timeline

WORDS_LO, WORDS_HI = 52, 86              # spoken words in the whole short (the prompt asks for 62 to 74; this is what is accepted)
REC_LO, REC_HI = 62, 74                  # what the prompt asks for at the full 30 seconds
MAX_SENTENCE_WORDS = 16
MAX_HOOK_WORDS = 9
MAX_CHARACTER_SHOTS = 4


class SBeat(M):
    name: Str = ""
    feeling: Str = ""
    tag: Str = ""
    narration: list[Str]


class PlanOut(M):
    title: Str
    logline: Str = ""
    character: Str = ""
    place: Str = ""
    look: Str = ""
    beats: list[SBeat]


class ShotOut(M):
    prompt: Str
    still: Str = ""
    cast: list[Str] = []
    camera: Str = "static"
    character: bool = False
    continues: bool = False
    setting: Str = ""


class ShotsOut(M):
    shots: list[ShotOut]


def source_text(short: dict) -> str:
    src = short["source"]
    if src.get("kind") == "story":
        return "FACTS (tell only these; do not invent any):\n" + src.get("facts", "")
    return "THE IDEA (the brief for the short):\n" + src.get("text", "")


def _profile(short: dict):
    """The source profile the leak gate needs, for a short made from a story; None for an idea."""
    src = short["source"]
    if src.get("kind") != "story":
        return None
    try:
        ev = intake.load(src["candidate_id"])["evidence"]
        return leak.profile(ev["project_id"], ev["passages"])
    except intake.IntakeError:
        return None


def target_s(short: dict) -> float:
    return float(short.get("settings", {}).get("target_s") or models.TARGET_S)


def word_limits(t_s: float) -> tuple[int, int, int, int]:
    """(accepted low, accepted high, asked low, asked high) spoken words for a short of `t_s` seconds. Scaled from the 30-second figures; a shorter short is also capped by what the voice can say
    (the fastest the timeline lets it speak), so words that pass here can fit."""
    if t_s >= models.TARGET_S:
        return WORDS_LO, WORDS_HI, REC_LO, REC_HI
    hi = min(round(WORDS_HI * t_s / models.TARGET_S), int((t_s - 0.9) * timeline.TEMPO_MAX * timeline.PACE_WPS))
    lo = max(6, round(WORDS_LO * t_s / models.TARGET_S))
    return lo, hi, max(lo, round(REC_LO * t_s / models.TARGET_S)), max(lo, min(round(REC_HI * t_s / models.TARGET_S), hi - 1))


def beat_range(t_s: float) -> tuple[int, int]:
    """How many beats a short of `t_s` seconds has: 4 to 6 at 30 seconds, fewer when shorter."""
    lo = max(2, round(t_s / 7.5))
    return lo, max(lo + 1, round(t_s / 5))


def narration_problems(beats: list[dict], profile=None, t_s: float = models.TARGET_S) -> list[str]:
    """What is wrong with the words, in plain terms. Used while the model writes (it is sent back) and by the checks."""
    out: list[str] = []
    sentences = [s["text"] for b in beats for s in b["sentences"]]
    n = sum(len(t.split()) for t in sentences)
    if not sentences:
        return ["there is no narration"]
    lo, hi = word_limits(t_s)[:2]
    if n < lo or n > hi:
        out.append(f"the narration is {n} words; it must be between {lo} and {hi} so that it fills about {t_s:g} seconds")
    if len(sentences[0].split()) > MAX_HOOK_WORDS:
        out.append(f"the first sentence is {len(sentences[0].split())} words; the hook must be at most {MAX_HOOK_WORDS}")
    for t in sentences:
        if len(t.split()) > MAX_SENTENCE_WORDS:
            out.append(f"a sentence is {len(t.split())} words (limit {MAX_SENTENCE_WORDS}): \"{t[:50]}\"")
            break
    for t in sentences:
        if re.search(r"\d", t):
            out.append(f"digits in \"{t[:50]}\": write numbers as words")
            break
    for t in sentences:
        if svara.romanised_hindi(t):
            out.append(f"Hindi written in Latin letters: \"{t[:50]}\". Hindi words must be in Devanagari; only English words use Latin letters")
            break
    stock = [h for t in sentences for h in lexicon.hits(t)]
    if stock:
        out.append("stock phrases: " + ", ".join(dict.fromkeys(stock)) + " (say it another way)")
    if profile is not None:
        found = leak.check_many([("narration", " ".join(sentences))], profile)
        if found:
            out.append("the narration points back to the source: " + "; ".join(f["text"] for f in found[:3]))
    return out


def _beats_from(out: PlanOut, engine: str) -> list[dict]:
    beats = []
    for i, b in enumerate(out.beats, 1):
        tag = maya.norm_tag(b.tag) if engine == "maya-tts" else ""
        sents = [{"text": re.sub(r"\s+", " ", t).strip(), "tag": ""} for t in b.narration if t.strip()]
        if sents and tag:
            sents[0]["tag"] = tag
        beats.append({"id": f"b{i}", "name": b.name or f"Beat {i}", "feeling": b.feeling, "tag": tag, "sentences": sents, "shot_ids": []})
    beats = [b for b in beats if b["sentences"]]
    for b in beats:
        safety.guard_tags(b["sentences"])
    return beats


async def _plan_call(short: dict, backend, s: dict, note: str = "") -> PlanOut:
    cur = voices.current({"tts": short["settings"].get("voice")})
    caller = llm.JsonCaller(backend, s)
    prof = _profile(short)
    extra = ""
    if short["settings"].get("character_text"):
        extra += f"\nThe main character is already chosen by the producer; use exactly this description: {short['settings']['character_text']}"
    if cast.entries(short):
        extra += ("\nThe cast is fixed by the producer (their faces and clothes are drawn from library pictures); write the story for exactly these people and invent no other main character:\n"
                  + cast.block(short))
    if cast.place_text(short):
        extra += f"\nThe main place is fixed by the producer: {cast.place_text(short)}"
    if short["settings"].get("tone"):
        extra += f"\nTone: {short['settings']['tone']}"

    t_s = target_s(short)
    b_lo, b_hi = beat_range(t_s)
    _, _, ask_lo, ask_hi = word_limits(t_s)

    def check(out: PlanOut) -> None:
        if len(out.beats) < min(3, b_lo):
            raise ValueError(f"write at least {min(3, b_lo)} beats")
        if caller.last_attempt:
            return                                                    # style rules never stop a run; the checks screen lists what is left
        probs = narration_problems(_beats_from(out, cur["engine"]), prof, t_s)
        if probs:
            raise ValueError("; ".join(probs[:4]))

    res = await caller.call(P.plan_system(cur["engine"], t_s, f"{b_lo} to {b_hi}", ask_lo, ask_hi), f"{source_text(short)}{extra}\n{note}\nWrite the short now.", PlanOut, validate=check)
    return res.value


def _shot(o: ShotOut) -> dict:
    return {"id": "", "beat": "", "prompt": o.prompt.strip(), "still": o.still.strip(), "cast": [x.strip() for x in o.cast if x.strip()], "camera": (o.camera or "static").strip(), "character": bool(o.character), "continues": bool(o.continues),
            "setting": o.setting.strip(), "seconds": 0.0, "frames": 0}


async def _shots_call(short: dict, beat: dict, count: int, backend, s: dict, before: dict | None) -> list[dict]:
    plan = short["plan"]
    caller = llm.JsonCaller(backend, s)
    ctx = [f"WHOLE SHORT: {plan.get('title', '')} - {plan.get('logline', '')}",
           f"MAIN PLACE: {plan.get('place', '')}", f"MAIN CHARACTER (added to character shots for you): {plan.get('character', '') or 'none'}", f"LOOK: {plan.get('look', '')}",
           "THE WHOLE NARRATION:\n" + "\n".join(f"- ({b['name']}) " + " ".join(x["text"] for x in b["sentences"]) for b in short["beats"]),
           f"THIS BEAT ({beat['name']}, feeling: {beat['feeling'] or 'neutral'}): " + " ".join(x["text"] for x in beat["sentences"])]
    if before:
        ctx.append(f"THE SHOT BEFORE THIS BEAT: {before['prompt']} (camera: {before['camera']})")

    def check(out: ShotsOut) -> None:
        if len(out.shots) != count and not caller.last_attempt:
            raise ValueError(f"write exactly {count} shots, not {len(out.shots)}")
        if not out.shots:
            raise ValueError("write the shots")

    cast_names = [m["char"]["name"] for m in cast.members(short) if m["char"]]
    res = await caller.call(P.shots_system(count, MAX_CHARACTER_SHOTS, cast_names, target_s(short)),"\n".join(ctx) + f"\n\nWrite exactly {count} shots now.", ShotsOut, validate=check)
    shots = [_shot(o) for o in res.value.shots]
    ids = cast.names(short)
    for sh in shots:                                                         # names the model wrote become library ids; a character shot with no names shows the whole cast
        found = [ids[n.lower()] for n in sh["cast"] if n.lower() in ids]
        sh["cast"] = found or (list(ids.values())[:cast.MAX_PEOPLE] if (sh["character"] and ids) else [])
        sh["character"] = bool(sh["character"] or sh["cast"])
    while len(shots) > count:                                         # the last attempt may be off by some: trim, or repeat the last shot closer
        shots.pop()
    while len(shots) < count:
        last = dict(shots[-1])
        last["prompt"] = last["prompt"] + " A closer detail of the same moment."
        last["still"] = ""
        last["camera"] = "close-up"
        last["continues"] = True
        shots.append(last)
    return shots


def _limit_character_shots(shots: list[dict]) -> None:
    seen = 0
    for sh in shots:
        if sh["character"]:
            seen += 1
            if seen > MAX_CHARACTER_SHOTS:
                sh["character"] = False
                sh["cast"] = []


async def make_plan(short_id: str, backend, s: dict | None = None, progress=None) -> dict:
    """Plan the whole short: narration and look first, then the shots of each beat. Replaces an earlier plan (voice and clips made from it stop counting by their hashes)."""
    s = s or settings_mod.get()
    short = store.get(short_id)
    if progress:
        progress(0, 1, "writing the story and the narration")
    out = await _plan_call(short, backend, s)
    plan = {"title": out.title.strip()[:90], "logline": out.logline.strip(), "character": short["settings"].get("character_text") or out.character.strip(),
            "place": out.place.strip(), "look": out.look.strip()}
    if cast.entries(short):                                                  # the library decides who and where, not the model
        plan["character"] = cast.block(short).replace("\n", " ") or plan["character"]
        plan["look"] = cast.look_text(short) or plan["look"]
    if cast.place_text(short):
        plan["place"] = cast.place_text(short)
    beats = _beats_from(out, voices.current({"tts": short["settings"].get("voice")})["engine"])
    short.update(plan=plan, beats=beats, shots=[], title=plan["title"] or short["title"])
    counts = timeline.plan_counts(beats, target_s(short))
    all_shots: list[dict] = []
    before = None
    for i, (b, n) in enumerate(zip(beats, counts)):
        if progress:
            progress(i + 1, len(beats) + 1, f"planning the shots of beat {i + 1} of {len(beats)}")
        shots = await _shots_call(short, b, n, backend, s, before)
        before = shots[-1]
        for sh in shots:
            sh["id"] = f"s{len(all_shots) + 1}"
            sh["beat"] = b["id"]
            all_shots.append(sh)
        b["shot_ids"] = [sh["id"] for sh in shots]
    _limit_character_shots(all_shots)
    if short.get("settings", {}).get("voice_mode") == "none":               # silent video: narration was only needed for shot context; discard it
        for b in beats:
            b["sentences"] = []
    short["shots"] = all_shots
    short["status"] = "planned"
    short["keyframes_confirmed"] = False
    refit(short)
    return store.save(short)


async def reshoot_beat(short_id: str, beat_id: str, count: int, backend, s: dict | None = None) -> dict:
    """Write the shots of one beat again, with `count` shots (when the voice turned out longer or shorter than the estimate). Other beats are not touched."""
    s = s or settings_mod.get()
    short = store.get(short_id)
    beat = next((b for b in short["beats"] if b["id"] == beat_id), None)
    if not beat:
        raise store.ShortError(f"no such beat: {beat_id}")
    idx = short["beats"].index(beat)
    prev = None
    if idx > 0 and short["beats"][idx - 1]["shot_ids"]:
        prev = store.shot_by_id(short, short["beats"][idx - 1]["shot_ids"][-1])
    shots = await _shots_call(short, beat, max(1, count), backend, s, prev)
    old = set(beat["shot_ids"])
    keep = [sh for sh in short["shots"] if sh["id"] not in old]
    top = max([int(sh["id"][1:]) for sh in short["shots"]] + [0])
    for k, sh in enumerate(shots, 1):
        sh["id"] = f"s{top + k}"                                       # new ids: clips made for the old shots are not mistaken for these
        sh["beat"] = beat_id
    beat["shot_ids"] = [sh["id"] for sh in shots]
    order = {sid: n for n, sid in enumerate(sid for b in short["beats"] for sid in b["shot_ids"])}
    short["shots"] = sorted(keep + shots, key=lambda sh: order[sh["id"]])
    refit(short)
    return store.save(short)


def refit(short: dict, voice: dict[str, float] | None = None) -> dict:
    """Write each shot's seconds and output frames from the timeline (the real voice when `voice` is given, else the estimate). Returns the timeline."""
    tl = timeline.build(short, voice)
    by = {t["id"]: t for t in tl["shots"]}
    for sh in short["shots"]:
        t = by.get(sh["id"])
        if t:
            sh["seconds"], sh["frames"], sh["start"] = t["seconds"], t["frames"], t["start"]
    return tl


def sync_timing(short_id: str) -> dict:
    """Shot lengths from the real voice where a beat has a valid take, the estimate elsewhere; saved. Call after the voice is made and before clips are planned."""
    from . import voice as svoice
    short = store.get(short_id)
    refit(short, svoice.real_seconds(short))
    return store.save(short)


async def fit_shots(short_id: str, backend, s: dict | None = None, progress=None) -> str:
    """After the voice exists: any beat whose shots would be on screen longer than the limit gets its shots written again with enough of them. Returns a sentence about what was done."""
    from . import voice as svoice
    done = []
    for _ in range(3):
        short = sync_timing(short_id)
        tl = timeline.build(short, svoice.real_seconds(short))
        need = next((p["beats"] for p in tl["problems"] if p["code"] == "shot_too_long"), {})
        if not need:
            break
        for n, (bid, count) in enumerate(need.items()):
            if progress:
                progress(n, len(need), f"writing {count} shots for {bid}")
            await reshoot_beat(short_id, bid, count, backend, s)
            done.append(bid)
    return ("shots rewritten for " + ", ".join(dict.fromkeys(done))) if done else "every shot already fits"
