"""The writers' room of a short: four model steps that write the narration before any picture is planned, so it plays like a story and not like a summary.
1. bible    the story's engine: premise, what the hero wants and fears, the secret, the wow moments, the closing question (kept on the short, so a rewrite starts from it)
2. map      the retention map: every beat gets a job (hook, escalate, reveal, re-hook ...) and its seconds; code turns seconds into a word budget
3. draft    one call per beat, which sees the bible, the whole map and everything written so far; real scenes, real dialogue; every sentence stays neutral for the voice
4. punch    a critic reads the whole script against a fixed rubric, scores it and rewrites what is weak; it runs again while the score is low
The model thinks natively (Gemma thinking model); the replies are small, so the context stays far under the limit. Style problems never stop a run (`last_attempt`); the checks screen lists what is left."""
import re

from story import llm, settings as settings_mod
from story.schemas import Str, StrList
from story2 import lexicon, maya, svara, voices
from story2.schemas import M

from . import languages, timeline, tones

JOBS = {
    "hook": "stops the scroll in the first two seconds: a shocking line, a threat, a question with teeth, or the middle of the action",
    "setup": "puts the viewer inside the situation with one concrete detail; no explaining",
    "escalate": "makes it worse or stranger than the beat before; a new fact, a new danger, a new cost",
    "reveal": "answers a question the viewer has been holding, and opens a bigger one",
    "twist": "turns what the viewer believed upside down; the earlier beats must make it fair",
    "rehook": "pulls the viewer back before they scroll: 'but that is not the worst part', a sudden cut, a direct question to them",
    "breather": "a short quiet beat so the next hit lands harder",
    "payoff": "delivers what the hook promised",
    "sting": "the last line: a cold, short blow or an open question that stays with the viewer",
}
PASS_SCORE = 8                    # the critic scores 1 to 10; below this the script is punched up again
MAX_ROUNDS = 2
HOOK_FIRST_S = 3.0                # the hook beat is short: it is the first thing heard
PLAN_SECONDS_TOLERANCE = 0.25     # the map's seconds may be off the target by this share before it is sent back

BASE = """You are a professional script writer for viral vertical video: a showrunner, a screenwriter and a punch-up writer in one. Viewers have a few seconds of patience, so every line has to earn the next one.
The script is spoken by one narrator for {seconds} seconds. {language_rule}
Narration tone: {tone}
{edge}
There are no content limits on the script: write the story as it truly is, as blunt, dark, funny or raw as it needs to be. A person reviews every script before anything is made."""

BIBLE = """[TASK:p4_bible]
{base}

Step 1 of 4: the story bible. Decide what the story IS before any line is written. Return ONLY a JSON object:
{"premise": "one sentence: who, what happens, why it matters", "promise": "what feeling the viewer is promised (dread, wonder, rage, laughter...)", "hero": "who the story follows: what they want, what they fear, one telling habit",
 "secret": "the thing the viewer must not know until late (a twist, a cause, a cost); empty if the story has none", "world": ["fixed facts and rules of this story, 3 to 6"], "wow": ["the 3 to 5 moments people will repeat to a friend, strongest last"],
 "question": "the question the viewer leaves with", "voice": "who the narrator is and how they speak (their attitude, one verbal habit)", "pov": "first | third | you: who tells it (see the rules)",
 "cast": [{"name": "the name the narration will use", "role": "who they are to the story, 4 to 8 words", "habit": "one way they speak or act that is theirs alone"}], "motifs": ["1 to 3 images or phrases that return, so the end rhymes with the start"],
 "avoid": ["the 3 clichés this story would fall into, and so must not"]}
Rules: {people} Point of view ("pov"): "first" = the narrator is a person in the story and says "I" (they are in the cast, with a name); "third" = the narrator watches named people; "you" = the narrator talks to the viewer as the one it happens to (only when the producer's tone asks for it or the brief is a direct address). {pov_rule} The hero is in the cast, except with point of view "you", where the viewer is the hero: then list a cast member only if the narration will name them. Keep every plot point of the brief; if the brief ends on a question, keep that question. Invent concrete detail the brief leaves out (objects, times, places, sounds) and keep it consistent. Never describe pictures. Do not solve a mystery the brief leaves open and do not add a new theory that explains it: add atmosphere, objects, names and habits, not lore."""

MAP = """[TASK:p4_map]
{base}

Step 2 of 4: the retention map. Split the story into beats. A beat is one stretch of narration in one steady emotion. Every beat has a job:
{jobs}
Return ONLY a JSON object: {"beats": [{"name": "short title", "job": "one of the jobs above", "feeling": "one word: the emotion of the voice", "seconds": 6, "carries": "what this beat must tell or make the viewer feel, 1 or 2 sentences, concrete, in plain English (notes for the writer, never narration)", "cliff": "OPTIONAL: a hanging question or threat that makes the viewer stay for the next beat; leave it empty unless the beat truly needs one"}]}
Rules:
- {beats} beats; the seconds add up to {seconds} (the first beat is 3 to 5 seconds).
- The first beat's job is hook, the last beat's job is sting (or payoff when a sting does not fit).
- One open loop runs through the script (the bible's question); do not close a beat on a fresh question each time. Most beats hand over with a statement, a fact or a turn; give a cliff to at most one beat in three, never to two beats in a row. Something changes in every beat: a new fact, a worse danger, a turned belief.
- {pace}
- Put the bible's wow moments where they hit hardest, and make the twist land on a beat of its own, after it has been set up.
- Never two beats in a row with the same job and feeling."""

DRAFT = """[TASK:p4_draft]
{base}

Step 3 of 4: write the narration of ONE beat. Return ONLY a JSON object: {"sentences": [{"text": "..."}, {"text": "..."}]}
Each {"text": "..."} object holds exactly one spoken sentence ending in । or ? or !. Never put two sentences inside one "text" value.
Craft:
- People: follow the bible's point of view and cast. Say a person's name the first time they appear and keep calling them by it; never "a man", "a woman", "someone" for a cast member. Every quoted line says who speaks it (a name, "I", or a clear "she said"). Whose phone, whose room, whose body: name the owner once. The narration never switches point of view. Show a cast member's habit as an action in a scene, once at most; never copy the cast notes into a line.
- Show, do not report. Never write "he discovers", "she reveals", "a voice warns me". Write the discovery: the object, the sound, the exact words said, in the line itself. Put people's words in direct speech.
- The viewer lives it: sensory detail (one sound, one smell, one texture), the narrator's body and thoughts, a number or a name instead of "a lot" or "someone".
- Rhythm: vary the length. A long line that rolls, then a blunt short one. A fragment is fine. A line of two words can be a whole beat. Never three sentences of the same length in a row.
- Flow: this beat continues the line before it. Pick up its thought, keep the same voice and the same way of addressing the viewer, never restart or re-introduce. End on a statement or a turn; end on a question only when the map gives this beat a cliff, and then one real question the viewer would ask, never a cut-in question after every beat. At most one question in a beat.
- Speak to the ear: no brackets, no stage directions, no digits (write numbers as words). Do not start with the same word as the line before.
- {tags}
- {words}
- Write ONLY this beat. Stay inside the story bible; do not repeat anything already written; do not jump to the next beat's events."""

PUNCH = """[TASK:p4_punch]
{base}

Step 4 of 4: the punch-up. You get the whole script, beat by beat. Judge it as a skeptical viewer who scrolls at the first dull line, then rewrite what is weak.
Score the INPUT script from 1 to 10 against: (1) the first line stops the scroll in two seconds, (2) a new hook or open loop at least every ten seconds, (3) no line that only reports what the pictures will show, (4) real lines of dialogue or concrete detail, not summary verbs, (5) the twist is set up before it fires, (6) varied rhythm with blunt lines, (7) the last line lands and the bible's question stays open, (8) the people are named and distinct, the point of view never switches, and it is always clear who speaks and whose things they are, (9) each beat continues the one before it, in one steady voice and one form of address, and (10) no more than one beat in three ends on a question, never two in a row.
Return ONLY a JSON object: {"score": 6, "problems": ["the 3 worst problems, each naming the beat"], "beats": [{"id": "b1", "sentences": [{"text": "..."}, {"text": "..."}]}]}
Each {"text": "..."} object holds exactly one spoken sentence ending in । or ? or !. Never put two sentences inside one "text" value.
Rules for "beats": return EVERY beat with its id, in order. Rewrite the weak lines, keep the strong ones word for word. Keep each beat's job, order of events and facts. Keep the whole script between {lo} and {hi} words, and each beat within 20% of its words now. {tags}"""

TAGS = "Write no tags, brackets or stage directions: the voice is neutral and the producer directs its emotion later. The words, the rhythm and the punctuation ('...' before a reveal, a comma for a breath, '?' for a real question) carry the feeling."


class CastOut(M):
    name: Str
    role: Str = ""
    habit: Str = ""


class BibleOut(M):
    premise: Str
    promise: Str = ""
    hero: Str = ""
    secret: Str = ""
    world: StrList = []
    wow: StrList = []
    question: Str = ""
    voice: Str = ""
    pov: Str = ""
    cast: list[CastOut] = []
    motifs: StrList = []
    avoid: StrList = []


class MapBeat(M):
    name: Str = ""
    job: Str = "escalate"
    feeling: Str = ""
    seconds: float = 0
    carries: Str = ""
    cliff: Str = ""


class MapOut(M):
    beats: list[MapBeat]


class SentOut(M):
    text: Str
    tag: Str = ""


class DraftOut(M):
    sentences: list[SentOut]


class PunchBeat(M):
    id: Str
    sentences: list[SentOut]


class PunchOut(M):
    score: float = 0
    problems: StrList = []
    beats: list[PunchBeat] = []


def _base(short: dict, t_s: float) -> str:
    settings = short["settings"]
    tone = tones.TONES[tones.of(settings)]
    tone_text = f"{tone['label'].split(' (')[0]} (energy {tone['energy']} of 5; sounds {tone['sound'].lower()}). Writing rules: {tone['writing']}"
    if tone.get("pov"):
        tone_text += f" Point of view: {tone['pov']}."
    return (BASE.replace("{seconds}", f"{t_s:g}").replace("{language_rule}", languages.rule(settings)).replace("{tone}", tone_text)
            .replace("{edge}", "Language edge: " + tones.EDGES[tones.edge_of(settings)]["rule"]))


def _people_rules(short: dict) -> tuple[str, str]:
    """(who may be named, point-of-view rule). A story made from facts has real people: their names are used exactly as given and none is invented. A brief is free to name its unnamed people."""
    if short["source"].get("kind") == "story":
        return ("The facts are real: put every person the facts name in the cast with exactly that name and role, and never invent a person, a name or a nickname.",
                "Default to third. A real person is never made to say words the facts do not give; quote only what the facts quote.")
    fmt = (short.get("plan") or {}).get("format") or short["settings"].get("format", "auto")
    if fmt in ("documentary", "comparison"):
        return ("The subjects are real entities (countries, armies, organisations, people). The cast name of each entity must be exactly the name stated in the brief — never give a real country, army, organisation or person a dramatic nickname, codename or alias.",
                "Default to third. The narrator observes and compares; never put words in a real entity's mouth.")
    return ("Give every person the story needs a name that fits the place and time; if the brief already names someone, or the brief is about real, known people, use exactly those names and invent nobody real.",
            "Default to third or first, whichever the brief reads best in; use you only when asked.")


def _source(short: dict) -> str:
    from . import cast, planner
    out = planner.source_text(short)
    if short["settings"].get("character_text"):
        out += f"\nThe main character is chosen by the producer: {short['settings']['character_text']}"
    if cast.entries(short):
        out += "\nThe cast is fixed by the producer; write for exactly these people:\n" + cast.block(short)
    if short["settings"].get("tone"):
        out += f"\nProducer's note on tone: {short['settings']['tone']}"
    try:
        from feedback import playbook
        lb = playbook.learnings_block("script")
        if lb:
            out += "\n\n" + lb
    except Exception as e:  # noqa: BLE001 - the script must never fail because of the feedback loop
        print(f"[feedback] script learnings failed: {e}", flush=True)
    return out


def seconds_to_words(seconds: float, t_s: float, speed: float = 1.0) -> int:
    """Words for `seconds` of speech: the share of the whole short's asked words that these seconds are."""
    from . import planner
    b = planner.word_limits(t_s, speed)[3]
    return max(3, round(seconds * b / max(1.0, t_s)))                        # aim at the asked top: drama needs the room, and the accepted top is left for a beat that runs over


def beat_count(t_s: float) -> tuple[int, int]:
    from . import planner
    return planner.beat_range(t_s)


def _pace_rule(t_s: float) -> str:
    if t_s <= 20:
        return "Short video: one hook and one blow; no breather."
    if t_s <= 60:
        return "Hook in the first beat, a new turn every beat, the twist in the second half, the sting last."
    return "Long video: a cold open, then three or four escalating loops. A re-hook beat at least every 20 seconds. A mid-point reversal that changes what the viewer thinks is going on. A breather before the biggest hit. The last beat rhymes with the first."


def _bible_text(b: BibleOut) -> str:
    lines = [f"PREMISE: {b.premise}", f"PROMISE: {b.promise}", f"HERO: {b.hero}", f"SECRET (hold it back): {b.secret}" if b.secret else "", "WORLD: " + "; ".join(b.world),
             "WOW MOMENTS: " + "; ".join(b.wow), f"CLOSING QUESTION: {b.question}", f"NARRATOR: {b.voice}", f"POINT OF VIEW: {b.pov}" if b.pov else "", "CAST (use exactly these names): " + "; ".join(f"{c.name} ({c.role}; {c.habit})" if c.habit else f"{c.name} ({c.role})" for c in b.cast) if b.cast else "", "MOTIFS: " + "; ".join(b.motifs), "AVOID: " + "; ".join(b.avoid)]
    return "\n".join(x for x in lines if x.strip() and not x.endswith(": "))


def clean_job(j: str) -> str:
    j = re.sub(r"[^a-z]", "", (j or "").lower())
    return j if j in JOBS else next((k for k in JOBS if j.startswith(k) or k.startswith(j)), "escalate") if j else "escalate"


def fit_map(beats: list[MapBeat], t_s: float) -> list[dict]:
    """The map as plain dicts with seconds scaled to add up to the target (the model's arithmetic is not trusted) and the first beat short."""
    items = [{"name": b.name.strip() or f"Beat {i + 1}", "job": clean_job(b.job), "feeling": b.feeling.strip(), "carries": b.carries.strip(), "cliff": b.cliff.strip(), "seconds": max(1.5, float(b.seconds or 0) or t_s / len(beats))} for i, b in enumerate(beats)]
    if len(items) > 1:
        items[0]["seconds"] = min(items[0]["seconds"], max(HOOK_FIRST_S, t_s * 0.12))
    total = sum(x["seconds"] for x in items)
    for x in items:
        x["seconds"] = round(x["seconds"] * t_s / total, 2)
    gap = 3
    for x in items[:-1]:                              # a cliff only now and then: a question at the end of every beat reads as forced
        gap += 1
        if x["cliff"] and gap >= 3:
            gap = 0
        else:
            x["cliff"] = ""
    items[-1]["cliff"] = ""
    return items


def clean_sentences(sents: list[SentOut], engine: str) -> list[dict]:
    out = []
    tag = maya.NEUTRAL if engine == "maya-tts" else ""
    for s in sents:
        text = re.sub(r"\[[a-z ]+\]", "", re.sub(r"\s+", " ", s.text)).strip()
        if not text:
            continue
        # Split packed sentences the model put in one text field (e.g. "A। B। C?")
        parts = [p.strip() for p in re.split(r"(?<=[।?!])\s+", text) if p.strip()]
        for p in parts:
            out.append({"text": p, "tag": tag})      # every sentence starts neutral; the producer (or the voice-direction step) changes it
    return out


def words_of(sents: list[dict]) -> int:
    return sum(len(s["text"].split()) for s in sents)


def draft_problems(sents: list[dict], lo: int, hi: int, language: str, prev_last: str = "", address: str = "aap") -> list[str]:
    from . import planner
    out: list[str] = []
    n = words_of(sents)
    if not sents:
        return ["write the beat"]
    if n < lo or n > hi:
        out.append(f"the beat is {n} words; write between {lo} and {hi}")
    texts = [s["text"] for s in sents]
    if any(re.search(r"\d", t) for t in texts):
        out.append("digits found: write numbers as words")
    if language in ("hinglish", "hi") and any(svara.romanised_hindi(t) for t in texts):
        out.append("Hindi written in Latin letters: Hindi words must be in Devanagari, only English words in Latin letters")
    if language in languages.HINDI_LIKE and address == "aap":
        tu = [h for t in texts for h in languages.address_hits(t)]
        if tu:
            out.append("familiar address found (" + ", ".join(dict.fromkeys(tu)) + "): speak to the viewer as aap, never tu or tum")
    if sum(t.rstrip().endswith("?") for t in texts) > 1:
        out.append("more than one question in this beat; keep one at most")
    if prev_last.rstrip().endswith("?") and texts[-1].rstrip().endswith("?"):
        out.append("the beat before ended on a question; end this one on a statement")
    stock = [h for t in texts for h in lexicon.hits(t)]
    if stock:
        out.append("stock phrases: " + ", ".join(dict.fromkeys(stock)) + " (say it another way)")
    if prev_last and texts[0].split()[:1] == prev_last.split()[:1]:
        out.append("do not start with the same word as the line before")
    if len(sents) >= 3 and len({len(t.split()) // 3 for t in texts}) == 1:
        out.append("every line has the same length; vary the rhythm with a long line and a blunt short one")
    if any(len(t.split()) > planner.MAX_SENTENCE_WORDS + 8 for t in texts):
        out.append(f"a line is longer than {planner.MAX_SENTENCE_WORDS + 8} words; split it")
    return out


def cast_problems(bible: BibleOut, sents: list[dict]) -> list[str]:
    """By the end of the second beat the narration has said a cast member's name (a first-person narrator may be the only one, and says theirs once)."""
    names = [c.name.strip() for c in bible.cast if c.name.strip()]
    text = " ".join(s["text"] for s in sents).lower()
    if names and not any(n.lower() in text or n.lower().split()[0] in text for n in names):
        return ["no cast member is named yet: say the name of " + " or ".join(names[:3]) + " in this beat"]
    return []


async def write_bible(short: dict, t_s: float, backend, s: dict) -> BibleOut:
    caller = llm.JsonCaller(backend, s)
    people, pov = _people_rules(short)
    res = await caller.call(BIBLE.replace("{base}", _base(short, t_s)).replace("{people}", people).replace("{pov_rule}", pov), _source(short) + "\n\nWrite the story bible now.", BibleOut)
    return res.value


async def write_map(short: dict, bible: BibleOut, t_s: float, backend, s: dict) -> list[dict]:
    lo, hi = beat_count(t_s)
    caller = llm.JsonCaller(backend, s)

    def check(out: MapOut) -> None:
        if caller.last_attempt:
            return
        if not lo <= len(out.beats) <= hi:
            raise ValueError(f"write {lo} to {hi} beats, not {len(out.beats)}")
        total = sum(b.seconds for b in out.beats)
        if abs(total - t_s) > PLAN_SECONDS_TOLERANCE * t_s:
            raise ValueError(f"the seconds add up to {total:g}; they must add up to {t_s:g}")
        if clean_job(out.beats[0].job) != "hook":
            raise ValueError("the first beat's job must be hook")

    system = MAP.replace("{base}", _base(short, t_s)).replace("{jobs}", "\n".join(f"- {k}: {v}" for k, v in JOBS.items())).replace("{beats}", f"{lo} to {hi}").replace("{seconds}", f"{t_s:g}").replace("{pace}", _pace_rule(t_s))
    res = await caller.call(system, f"THE BRIEF:\n{_source(short)}\n\nTHE STORY BIBLE:\n{_bible_text(bible)}\n\nWrite the retention map now.", MapOut, validate=check)
    return fit_map(res.value.beats[:hi + 2], t_s)


async def draft_beat(short: dict, bible: BibleOut, plan: list[dict], done: list[dict], i: int, t_s: float, engine: str, speed: float, backend, s: dict,
                     budget: tuple[int, int] | None = None, note: str = "", current: list[dict] | None = None, after: list[dict] | None = None) -> list[dict]:
    """Write beat `i`. A rewrite also gets `budget` (its words), the producer's `note`, the beat's `current` text and the beats that come `after` it."""
    b = plan[i]
    words = seconds_to_words(b["seconds"], t_s, speed)
    lo, hi = budget or (max(3, round(words * 0.8)), max(5, round(words * 1.2)))
    language = languages.of(short["settings"])
    prev_last = done[-1]["sentences"][-1]["text"] if done and done[-1]["sentences"] else ""
    caller = llm.JsonCaller(backend, s)

    def check(out: DraftOut) -> None:
        if caller.last_attempt:
            return
        sents = clean_sentences(out.sentences, engine)
        probs = draft_problems(sents, lo, hi, language, prev_last, languages.address(short["settings"]))
        if i == 1:
            probs += cast_problems(bible, [x for b in done for x in b["sentences"]] + sents)
        if probs:
            raise ValueError("; ".join(probs[:3]))

    system = (DRAFT.replace("{base}", _base(short, t_s)).replace("{tags}", TAGS).replace("{words}", f"This beat is about {b['seconds']:g} seconds of speech: between {lo} and {hi} words in total (count them)."))
    lines = [f"THE STORY BIBLE:\n{_bible_text(bible)}", "THE MAP (every beat, in order):\n" + "\n".join(
        f"{'>> ' if k == i else '   '}{k + 1}. [{x['job']}, {x['feeling'] or 'neutral'}, {x['seconds']:g}s] {x['name']}: {x['carries']}" + (f" | cliff: {x['cliff']}" if x['cliff'] else "") for k, x in enumerate(plan))]
    if done:
        lines.append("WRITTEN SO FAR (do not repeat; continue from the last line):\n" + "\n".join(f"({x['name']}) " + " ".join(f"{('[' + y['tag'] + '] ') if y['tag'] not in ('', maya.NEUTRAL) else ''}{y['text']}" for y in x["sentences"]) for x in done))
    if after:
        lines.append("COMES AFTER THIS BEAT (do not spoil it and do not repeat it):\n" + "\n".join(f"({x['name']}) " + " ".join(y["text"] for y in x["sentences"]) for x in after))
    if current:
        lines.append("THE CURRENT TEXT OF THIS BEAT (the producer wants it written again):\n" + " ".join(y["text"] for y in current))
    if note:
        lines.append(f"THE PRODUCER'S INSTRUCTION (follow it exactly; it wins over the map when they disagree): {note}")
    lines.append(f"NOW WRITE BEAT {i + 1} of {len(plan)}: {b['name']}\nJob: {b['job']} - {JOBS[b['job']]}\nFeeling: {b['feeling'] or 'neutral'}\nIt must carry: {b['carries']}\n" + (f"It may end on this open question or threat if it fits (otherwise end on a statement): {b['cliff']}" if b["cliff"] else ("It is the last beat: end on the sting." if i == len(plan) - 1 else "End on a statement or a turn that leads into the next beat, not on a question.")))
    res = await caller.call(system, "\n\n".join(lines), DraftOut, validate=check)
    return clean_sentences(res.value.sentences, engine)


def stored_bible(short: dict) -> BibleOut:
    """The short's story bible; a short written by the one-call plan gets a small one made from its plan."""
    saved = (short.get("script") or {}).get("bible")
    if saved:
        return BibleOut.model_validate(saved)
    plan = short.get("plan") or {}
    return BibleOut(premise=plan.get("logline") or plan.get("title") or "the story of this short", hero=plan.get("character", ""), question="")


def stored_plan(short: dict) -> tuple[list[dict], bool]:
    """The retention map aligned with the beats, and whether it is the real one. A short without a map (or whose beats changed) gets one made from its beats: each keeps its name, job and feeling and
    carries 'the same events as the current text'."""
    beats = short["beats"]
    saved = (short.get("script") or {}).get("map") or []
    if len(saved) == len(beats):
        return [dict(x) for x in saved], True
    return [{"name": b["name"], "job": clean_job(b.get("job", "")), "feeling": b.get("feeling", ""), "carries": "the same events as the current text, told better", "cliff": "",
             "seconds": round(max(1.5, words_of(b["sentences"]) / timeline.PACE_WPS), 2)} for b in beats], False


def _script_text(beats: list[dict]) -> str:
    return "\n".join(f"{b['id']} ({b['name']}; {b['job']}; {b['feeling'] or 'neutral'}): " + " ".join(f"{('[' + s['tag'] + '] ') if s['tag'] not in ('', maya.NEUTRAL) else ''}{s['text']}" for s in b["sentences"]) for b in beats)


def _floor(lo: int, hi: int, before: dict) -> int:
    """The fewest words a punched-up script may have: a rewrite sharpens, it does not cut (but it may always get under the top)."""
    return min(max(lo, round(0.92 * sum(before.values()))), hi)


async def punch_up(short: dict, bible: BibleOut, beats: list[dict], t_s: float, engine: str, speed: float, backend, s: dict) -> tuple[list[dict], dict]:
    """Up to MAX_ROUNDS critic passes. Returns the best script and a report {"score", "problems", "rounds"}. A reply that breaks the beat ids or the word budget is ignored."""
    from . import planner
    lo, hi = planner.word_limits(t_s, speed)[:2]
    report = {"score": 0.0, "problems": [], "rounds": 0}
    ids = [b["id"] for b in beats]
    for _ in range(MAX_ROUNDS):
        caller = llm.JsonCaller(backend, s)
        before = {b["id"]: words_of(b["sentences"]) for b in beats}

        def check(out: PunchOut) -> None:
            if caller.last_attempt:
                return
            if [b.id for b in out.beats] != ids:
                raise ValueError("return every beat, in order, with the same ids: " + ", ".join(ids))
            sent = {b.id: clean_sentences(b.sentences, engine) for b in out.beats}
            total = sum(words_of(v) for v in sent.values())
            floor = _floor(lo, hi, before)
            if not floor <= total <= hi:
                raise ValueError(f"the script is {total} words; it must be between {floor} and {hi} (do not cut it shorter; sharpen the lines)")
            tu = [h for v in sent.values() for x in v for h in languages.address_hits(x["text"])] if languages.of(short["settings"]) in languages.HINDI_LIKE and languages.address(short["settings"]) == "aap" else []
            if tu:
                raise ValueError("familiar address found (" + ", ".join(dict.fromkeys(tu)) + "): speak to the viewer as aap, never tu or tum")
            for k, v in sent.items():
                if not v:
                    raise ValueError(f"beat {k} has no sentences")
                if not 0.65 * before[k] <= words_of(v) <= 1.35 * before[k] + 2:
                    raise ValueError(f"beat {k} was {before[k]} words and is now {words_of(v)}; keep each beat within 35% of its words")

        system = PUNCH.replace("{base}", _base(short, t_s)).replace("{lo}", str(lo)).replace("{hi}", str(hi)).replace("{tags}", TAGS)
        user = f"THE STORY BIBLE:\n{_bible_text(bible)}\n\nTHE SCRIPT ({t_s:g} seconds):\n{_script_text(beats)}\n\nJudge and rewrite it now."
        try:
            out = (await caller.call(system, user, PunchOut, validate=check)).value
        except llm.LLMError:
            break
        report["rounds"] += 1
        report["score"], report["problems"] = out.score, out.problems[:4]
        if [b.id for b in out.beats] == ids:
            new = {b.id: clean_sentences(b.sentences, engine) for b in out.beats}
            total = sum(words_of(v) for v in new.values())
            if all(new.values()) and _floor(lo, hi, before) <= total <= hi:
                for b in beats:
                    b["sentences"] = new[b["id"]]
        if out.score >= PASS_SCORE:
            break
    return beats, report


def hard_problems(short: dict, sents: list[dict]) -> list[str]:
    """What must never reach the voice, whatever the last attempt of a model call accepted: Hindi in Latin letters and the familiar 'tu' address."""
    language = languages.of(short["settings"])
    if language not in languages.HINDI_LIKE:
        return []
    out: list[str] = []
    texts = [x["text"] for x in sents]
    if any(svara.romanised_hindi(t) for t in texts):
        out.append("Hindi written in Latin letters: Hindi words must be in Devanagari, only English words in Latin letters")
    if languages.address(short["settings"]) == "aap":
        tu = [h for t in texts for h in languages.address_hits(t)]
        if tu:
            out.append("familiar address found (" + ", ".join(dict.fromkeys(tu)) + "): speak to the viewer as aap, never tu or tum")
    return out


async def repair(short: dict, bible: BibleOut, plan: list[dict], beats: list[dict], t_s: float, engine: str, speed: float, backend, s: dict) -> list[str]:
    """After the punch-up: every beat that still breaks a hard rule is written again once with the problem named. A rewrite is kept only when it has fewer problems.
    Returns the problems that are left (for the checks screen)."""
    left: list[str] = []
    for i, b in enumerate(beats):
        probs = hard_problems(short, b["sentences"])
        if not probs:
            continue
        w = words_of(b["sentences"])
        try:
            new = await draft_beat(short, bible, plan, beats[:i], i, t_s, engine, speed, backend, s, budget=(max(3, round(0.8 * w)), round(1.25 * w) + 2),
                                   note="Same events, same facts, same order, written again. Fix this: " + "; ".join(probs), current=b["sentences"], after=beats[i + 1:])
        except llm.LLMError:
            new = []
        if new and len(hard_problems(short, new)) < len(probs):
            b["sentences"] = new
            probs = hard_problems(short, new)
        left += [f"{b['id']}: {p}" for p in probs]
    return left


async def write_beat_for_gap(short: dict, after_beat_id: str, topic: str, backend, s: dict) -> list[dict]:
    """Write sentences for a brand-new beat to insert after `after_beat_id`.

    The model sees the beat before, the beat after, and the full brief so the new beat
    flows naturally between its neighbours. Returns a list of sentence dicts ready to
    drop into short["beats"]. Returns [] on any failure so the caller can decide."""
    beats = short["beats"]
    pos = next((i for i, b in enumerate(beats) if b["id"] == after_beat_id), len(beats) - 1)
    before_beat = beats[pos]
    after_beat_obj = beats[pos + 1] if pos + 1 < len(beats) else None

    t_s = float(short.get("settings", {}).get("target_s") or 30)
    # New beat gets a proportional share — roughly one beat's worth of seconds
    avg_s = t_s / max(1, len(beats) + 1)
    lo = max(3, round(seconds_to_words(avg_s, t_s) * 0.75))
    hi = max(lo + 2, round(seconds_to_words(avg_s, t_s) * 1.25))

    engine = voices.current({"tts": short.get("settings", {}).get("voice", {})}).get("engine", "maya-tts")
    bible = stored_bible(short)
    language = languages.of(short.get("settings", {}))
    prev_last = before_beat["sentences"][-1]["text"] if before_beat.get("sentences") else ""

    caller = llm.JsonCaller(backend, s)

    def check(out: DraftOut) -> None:
        if caller.last_attempt:
            return
        sents = clean_sentences(out.sentences, engine)
        probs = draft_problems(sents, lo, hi, language, prev_last, languages.address(short.get("settings", {})))
        if probs:
            raise ValueError("; ".join(probs[:3]))

    before_text = " ".join(s["text"] for s in before_beat.get("sentences", []))
    after_text = (" ".join(s["text"] for s in after_beat_obj.get("sentences", [])) if after_beat_obj else "")

    system = (DRAFT
              .replace("{base}", _base(short, t_s))
              .replace("{tags}", TAGS)
              .replace("{words}", f"This beat is about {avg_s:.1f} seconds of speech: between {lo} and {hi} words."))

    lines = [
        f"THE STORY BIBLE:\n{_bible_text(bible)}",
        f"THE BEAT BEFORE THIS NEW BEAT:\n{before_text}",
        f"THE NEW BEAT TO WRITE:\nJob: escalate — makes it stranger or more concrete than the beat before\nFeeling: curious\nIt must carry: {topic}",
    ]
    if after_text:
        lines.append(f"THE BEAT AFTER THIS NEW BEAT (do not spoil or repeat it):\n{after_text}")
    lines.append(f"THE PRODUCER'S INSTRUCTION: {topic.strip()}")
    lines.append(f"Write exactly one beat ({lo} to {hi} words). Return ONLY the JSON object.")

    try:
        res = await caller.call(system, "\n\n".join(lines), DraftOut, validate=check)
        return clean_sentences(res.value.sentences, engine)
    except llm.LLMError:
        return []


async def write(short: dict, backend, s: dict | None = None, progress=None) -> dict:
    """Run the four steps. Returns {"bible", "map", "beats": [plan-style beats], "report"}; the beats are the narration and need nothing else."""
    from . import planner
    from story2 import voices
    s = s or settings_mod.get()
    t_s = planner.target_s(short)
    engine = voices.current({"tts": short["settings"].get("voice")})["engine"]
    speed = float(short["settings"].get("voice_speed") or 1.0)
    steps = 3
    if progress:
        progress(0, steps, "story bible")
    bible = await write_bible(short, t_s, backend, s)
    if progress:
        progress(0, steps, "retention map")
    plan = await write_map(short, bible, t_s, backend, s)
    beats: list[dict] = []
    for i in range(len(plan)):
        if progress:
            progress(0, steps, f"writing beat {i + 1} of {len(plan)}")
        sents = await draft_beat(short, bible, plan, beats, i, t_s, engine, speed, backend, s)
        beats.append({"id": f"b{i + 1}", "name": plan[i]["name"], "job": plan[i]["job"], "feeling": plan[i]["feeling"], "tag": maya.NEUTRAL if engine == "maya-tts" else "", "sentences": sents, "shot_ids": []})
    if progress:
        progress(0, steps, "punch-up")
    beats, report = await punch_up(short, bible, beats, t_s, engine, speed, backend, s)
    report["left"] = await repair(short, bible, plan, beats, t_s, engine, speed, backend, s)
    report["words"] = sum(words_of(b["sentences"]) for b in beats)
    return {"bible": bible.model_dump(), "map": plan, "beats": beats, "report": report}


DEFAULT_NOTE = "Write a stronger version: a sharper first line, more concrete detail, real speech instead of summary, a blunter ending."


async def rewrite_beat(short: dict, beat_id: str, instruction: str, backend, s: dict | None = None) -> list[dict]:
    """New sentences for one beat, following the producer's instruction, inside the beat's neighbours. The beat may get longer only while the whole script stays under its word limit."""
    from . import planner
    from story2 import voices
    s = s or settings_mod.get()
    beats = short["beats"]
    i = next((k for k, b in enumerate(beats) if b["id"] == beat_id), -1)
    if i < 0:
        raise ValueError(f"no such beat: {beat_id}")
    t_s = planner.target_s(short)
    speed = float(short["settings"].get("voice_speed") or 1.0)
    engine = voices.current({"tts": short["settings"].get("voice")})["engine"]
    plan, _ = stored_plan(short)
    w, total, hi = words_of(beats[i]["sentences"]), sum(words_of(b["sentences"]) for b in beats), planner.word_limits(t_s, speed)[1]
    budget = (max(3, round(0.6 * w)), max(w + 2, min(round(1.6 * w), w + max(0, hi - total))))
    return await draft_beat(short, stored_bible(short), plan, beats[:i], i, t_s, engine, speed, backend, s, budget=budget, note=instruction.strip() or DEFAULT_NOTE, current=beats[i]["sentences"], after=beats[i + 1:])


async def rewrite_all(short: dict, instruction: str, backend, s: dict | None = None, progress=None) -> dict:
    """Write every beat again (same beats, same order, same jobs: shots and ids stay), then punch up. Returns {"beats": {beat id: sentences}, "report"}."""
    from . import planner
    from story2 import voices
    s = s or settings_mod.get()
    t_s = planner.target_s(short)
    speed = float(short["settings"].get("voice_speed") or 1.0)
    engine = voices.current({"tts": short["settings"].get("voice")})["engine"]
    plan, real = stored_plan(short)
    bible = stored_bible(short)
    new: list[dict] = []
    for i, b in enumerate(short["beats"]):
        if progress:
            progress(i, len(short["beats"]) + 1, f"writing beat {i + 1} of {len(short['beats'])} again")
        w = words_of(b["sentences"])
        budget = None if real else (max(3, round(0.8 * w)), round(1.25 * w) + 1)
        sents = await draft_beat(short, bible, plan, new, i, t_s, engine, speed, backend, s, budget=budget, note=instruction.strip() or DEFAULT_NOTE, current=b["sentences"])
        new.append({"id": b["id"], "name": b["name"], "job": plan[i]["job"], "feeling": plan[i]["feeling"], "sentences": sents})
    if progress:
        progress(len(short["beats"]), len(short["beats"]) + 1, "punch-up")
    new, report = await punch_up(short, bible, new, t_s, engine, speed, backend, s)
    report["left"] = await repair(short, bible, plan, new, t_s, engine, speed, backend, s)
    report["words"] = sum(words_of(b["sentences"]) for b in new)
    return {"beats": {b["id"]: b["sentences"] for b in new}, "report": report}
