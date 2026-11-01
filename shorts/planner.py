"""The two model steps of a short: the plan (title, narration in beats, the look) and the shots of each beat. The model writes; code decides the counts and the timing
(shorts/timeline.py), checks the words (banned phrases, script, length) and puts the character and place into every shot (shorts/pipelines.py), so the model never has to repeat them."""
import re

from story import llm, settings as settings_mod
from story.schemas import Str
from story2 import intake, leak, lexicon, maya, safety, svara, voices
from story2.schemas import M

from . import voice as svoice
from . import cast, formats, languages, looks, models, shotlist, tones, prompts as P, store, subjects as subj, timeline

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
    format: Str = ""
    subjects: list[subj.SubjectOut] = []
    character: Str = ""
    place: Str = ""
    look: Str = ""
    beats: list[SBeat]


class ShotOut(M):
    prompt: Str
    still: Str = ""
    cast: list[Str] = []
    subjects: list[Str] = []
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


def chosen_format(short: dict, said: str = "") -> str:
    """The producer's choice when there is one, else what the model decided, else explainer (it invents no person)."""
    pick = (short.get("settings", {}).get("format") or formats.AUTO).strip().lower()
    if formats.valid(pick):
        return pick
    said = (said or "").strip().lower()
    return said if formats.valid(said) else "explainer"


def target_s(short: dict) -> float:
    return float(short.get("settings", {}).get("target_s") or models.TARGET_S)


def word_limits(t_s: float, speed: float = 1.0) -> tuple[int, int, int, int]:
    """Scaled by the narration speed: a slower voice says fewer words in the same seconds."""
    lo, hi, a, b = _word_limits(t_s)
    return round(lo * speed), round(hi * speed), round(a * speed), round(b * speed)


def _word_limits(t_s: float) -> tuple[int, int, int, int]:
    """(accepted low, accepted high, asked low, asked high) spoken words for a short of `t_s` seconds. Scaled from the 30-second figures; a shorter short is also capped by what the voice can say
    (the fastest the timeline lets it speak), so words that pass here can fit."""
    if t_s >= models.TARGET_S:
        return WORDS_LO, WORDS_HI, REC_LO, REC_HI
    hi = min(round(WORDS_HI * t_s / models.TARGET_S), int((t_s - 0.9) * timeline.TEMPO_MAX * timeline.PACE_WPS))
    lo = max(6, round(WORDS_LO * t_s / models.TARGET_S))
    return lo, hi, max(lo, round(REC_LO * t_s / models.TARGET_S)), max(lo, min(round(REC_HI * t_s / models.TARGET_S), hi - 1))


def min_sentences(t_s: float) -> int:
    """Fewest sentences the plan prompt accepts: about one per four seconds."""
    return max(3, round(t_s / 4.3))


def beat_range(t_s: float) -> tuple[int, int]:
    """How many beats a short of `t_s` seconds has: 4 to 6 at 30 seconds, fewer when shorter."""
    lo = max(2, round(t_s / 7.5))
    return lo, max(lo + 1, round(t_s / 5))


def narration_problems(beats: list[dict], profile=None, t_s: float = models.TARGET_S, language: str = languages.DEFAULT, speed: float = 1.0) -> list[str]:
    """What is wrong with the words, in plain terms. Used while the model writes (it is sent back) and by the checks."""
    out: list[str] = []
    sentences = [s["text"] for b in beats for s in b["sentences"]]
    n = sum(len(t.split()) for t in sentences)
    if not sentences:
        return ["there is no narration"]
    lo, hi = word_limits(t_s, speed)[:2]
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
    for t in sentences if language in ("hinglish", "hi") else []:
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
        tag = maya.NEUTRAL if engine == "maya-tts" else ""                 # neutral for every beat: the person changes a tag on the screen when a beat needs one
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
    extra += tones.prompt_text(short["settings"])
    if short["settings"].get("tone"):
        extra += f"\nTone: {short['settings']['tone']}"

    t_s = target_s(short)
    b_lo, b_hi = beat_range(t_s)
    _, _, ask_lo, ask_hi = word_limits(t_s, svoice.speed(short))

    def check(out: PlanOut) -> None:
        if len(out.beats) < min(3, b_lo):
            raise ValueError(f"write at least {min(3, b_lo)} beats")
        if len(out.beats) > b_hi and not caller.last_attempt:
            raise ValueError(f"write at most {b_hi} beats for a {t_s:g}-second short; you wrote {len(out.beats)}")
        if caller.last_attempt:
            return                                                    # style rules never stop a run; the checks screen lists what is left
        n_sent = sum(len([t for t in b.narration if t.strip()]) for b in out.beats)
        if n_sent < min_sentences(t_s):
            raise ValueError(f"write at least {min_sentences(t_s)} sentences in all (one fact per sentence); you wrote {n_sent}")
        probs = narration_problems(_beats_from(out, cur["engine"]), prof, t_s, languages.of(short["settings"]), svoice.speed(short))
        if probs:
            raise ValueError("; ".join(probs[:4]))

    res = await caller.call(P.plan_system(cur["engine"], t_s, f"{b_lo} to {b_hi}", ask_lo, ask_hi, short["settings"].get("format") or formats.AUTO, languages.rule(short["settings"])), f"{source_text(short)}{extra}\n{note}\nWrite the short now.", PlanOut, validate=check)
    return res.value


def _shot(o: ShotOut) -> dict:
    return {"id": "", "beat": "", "prompt": o.prompt.strip(), "still": o.still.strip(), "cast": [x.strip() for x in o.cast if x.strip()], "subjects": [x.strip() for x in o.subjects if x.strip()], "camera": (o.camera or "static").strip(), "character": bool(o.character), "continues": bool(o.continues),
            "setting": o.setting.strip(), "seconds": 0.0, "frames": 0}


async def _shots_call(short: dict, beat: dict, count: int, backend, s: dict, before: dict | None) -> list[dict]:
    plan = short["plan"]
    caller = llm.JsonCaller(backend, s)
    ctx = [f"WHOLE SHORT: {plan.get('title', '')} - {plan.get('logline', '')}", f"FORMAT: {plan.get('format') or 'story'}",
           f"MAIN PLACE: {plan.get('place', '')}", f"MAIN CHARACTER (added to character shots for you): {plan.get('character', '') or 'none'}", f"LOOK: {plan.get('look', '')}",
           "THE WHOLE NARRATION:\n" + "\n".join(f"- ({b['name']}) " + " ".join(x["text"] for x in b["sentences"]) for b in short["beats"]),
           f"THIS BEAT ({beat['name']}, feeling: {beat['feeling'] or 'neutral'}): " + " ".join(x["text"] for x in beat["sentences"])]
    if subj.of(short):
        ctx.append("THE SUBJECTS (name them exactly in the shots they appear in):\n" + "\n".join(f"- {x['name']} ({x['kind'] or 'subject'}): {x['visual']}" for x in subj.of(short)))
    if before:
        ctx.append(f"THE SHOT BEFORE THIS BEAT: {before['prompt']} (camera: {before['camera']})")
    ideas = beat.get("ideas") or []
    if len(ideas) == count:
        ctx.append("SHOT IDEAS for this beat (the director's pictures, one per shot, in order):\n" + "\n".join(f"{i}. {x['idea']}" + (f" [subjects: {', '.join(x['subjects'])}]" if x["subjects"] else "") for i, x in enumerate(ideas, 1)))
    seen = shotlist.drawn(short, beat["id"])
    if seen:
        ctx.append("ALREADY DRAWN in other beats (do not repeat these pictures):\n" + "\n".join(seen))

    def check(out: ShotsOut) -> None:
        if len(out.shots) != count and not caller.last_attempt:
            raise ValueError(f"write exactly {count} shots, not {len(out.shots)}")
        if not out.shots:
            raise ValueError("write the shots")

    cast_names = [m["char"]["name"] for m in cast.members(short) if m["char"]]
    res = await caller.call(P.shots_system(count, MAX_CHARACTER_SHOTS, cast_names, target_s(short), plan.get("format") or "story", bool(subj.of(short))),"\n".join(ctx) + f"\n\nWrite exactly {count} shots now.", ShotsOut, validate=check)
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


async def direct(short: dict, counts: list[int], backend, s: dict, progress=None) -> None:
    """The director's pass: plan every picture of the short before any shot is written (shorts/shotlist.py). A failure here never stops the plan; the beats then get their shots without a list."""
    if progress:
        progress(1, len(short["beats"]) + 2, "planning the pictures of the whole short")
    try:
        shotlist.apply(short, await shotlist.make(short, counts, backend, s, target_s(short)))
    except Exception:
        for b in short["beats"]:
            b.pop("ideas", None)


async def make_plan(short_id: str, backend, s: dict | None = None, progress=None) -> dict:
    """Plan the whole short: narration and look first, then the shots of each beat. Replaces an earlier plan (voice and clips made from it stop counting by their hashes)."""
    s = s or settings_mod.get()
    short = store.get(short_id)
    if progress:
        progress(0, 1, "writing the story and the narration")
    out = await _plan_call(short, backend, s)
    fmt = chosen_format(short, out.format)
    fixed = bool(short["settings"].get("character_text") or cast.entries(short))          # a person the producer fixed is kept in any format
    plan = {"title": out.title.strip()[:90], "logline": out.logline.strip(), "format": fmt, "subjects": subj.clean([x.model_dump() for x in out.subjects]),
            "character": short["settings"].get("character_text") or (out.character.strip() if formats.allows_character(fmt) else ""),
            "place": out.place.strip(), "look": out.look.strip()}
    if cast.entries(short):                                                  # the library decides who and where, not the model
        plan["character"] = cast.block(short).replace("\n", " ") or plan["character"]
        plan["look"] = cast.look_text(short) or plan["look"]
    plan["look"] = looks.of(short, plan["look"])
    if cast.place_text(short):
        plan["place"] = cast.place_text(short)
    beats = _beats_from(out, voices.current({"tts": short["settings"].get("voice")})["engine"])
    short.update(plan=plan, beats=beats, shots=[], title=plan["title"] or short["title"])
    counts = timeline.plan_counts(beats, target_s(short), timeline.silent(short))
    all_shots: list[dict] = []
    short["shots"] = all_shots                                               # the shots written so far, so a beat sees what the earlier beats drew
    before = None
    await direct(short, counts, backend, s, progress)
    for i, (b, n) in enumerate(zip(beats, counts)):
        if progress:
            progress(i + 2, len(beats) + 2, f"planning the shots of beat {i + 1} of {len(beats)}")
        shots = await _shots_call(short, b, n, backend, s, before)
        before = shots[-1]
        for sh in shots:
            sh["id"] = f"s{len(all_shots) + 1}"
            sh["beat"] = b["id"]
            all_shots.append(sh)
        b["shot_ids"] = [sh["id"] for sh in shots]
    if not formats.allows_character(fmt) and not fixed:                      # no invented main person in a documentary, an explainer or a comparison
        for sh in all_shots:
            sh["character"], sh["cast"] = False, []
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


async def reshoot_all(short_id: str, backend, s: dict | None = None, progress=None) -> str:
    """Think the pictures of the whole short again (director's list, then the shots of every beat) without touching the narration, the voice or the timing. New shot ids make older pictures and clips old."""
    s = s or settings_mod.get()
    short = store.get(short_id)
    counts = [max(1, len(b["shot_ids"])) for b in short["beats"]]
    await direct(short, counts, backend, s, progress)
    store.save(short)
    for i, (b, n) in enumerate(zip(short["beats"], counts)):
        if progress:
            progress(i + 2, len(short["beats"]) + 2, f"writing the shots of beat {i + 1} of {len(short['beats'])}")
        await reshoot_beat(short_id, b["id"], n, backend, s)
    return "the pictures of every beat were planned again"


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
