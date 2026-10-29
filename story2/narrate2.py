"""Narration v2 (docs/AUDIT_2026-10-29.md sections 3.3 and 14.2; tasks 2.4 to 2.7): each beat is written in three passes from the story's Material Pack.

  1. DRAFT    a storyteller writes the part as free Hinglish prose from the details it must tell (warm sampling, no JSON, no tags);
  2. EDIT     an editor cuts what adds nothing, replaces what the checks flagged and adds what the beat left out (cool sampling);
  3. TAG      the sentences are split in code (the words are never changed) and a small JSON step marks emotion, pauses and pronunciation.

The checks live in code, not in the prompt: the banned phrases (story2/lexicon.py) are named to the editor only when found, the question budget, the details of the beat
that must be told, attributed accusations, script rules, repeats and length. A failed check sends the EDIT pass back with the reason; the last round is accepted and its
findings are stored on the segment as issues. Used when the plan has a Material Pack and a blueprint that names details for its beats (`applies`)."""
import re
from types import SimpleNamespace

from story import llm
from story.schemas import Str, StrList

from . import audit, hindigate, lexicon, material, planner, prompts as P, safety, svara
from .schemas import M, NarrationOut, Pronounce, SegmentOut, Sentence

FIRST_SENTENCE_MAX_WORDS = 12
MAX_QUESTIONS_IN_VIDEO = 4
EDIT_ROUNDS = 3
COVER_SHARE = 0.7                       # at least this share of a beat's details must be told
_SENT_SPLIT = re.compile(r"(?<=[।.?!])\s+")
_STOP = set("the a an of and or to in on at with for from by is are was were be as it its this that his her their over under into out up down he she they him them who whom what which "
            "had has have not but then than so if when after before while about also very just".split())


_NUMWORDS = "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty"
ID_IN_TEXT = re.compile(r"(?<![A-Za-z])[Mm]\s?(?:\d{1,2}|(?:" + _NUMWORDS + r"))(?![A-Za-z\d])")             # "m13" or "M thirteen": a label of the Material Pack spoken aloud (seen on the real model)
YES_NO = re.compile(r"^\s*(?:क्या\s+(?:आप|तुम|यह|ये|वह|वो|हम|कभी|कोई)|(?:is|are|do|does|did|would|can|could|will|have|has)\s)", re.I)
PAUSE_AND_GUESS_HOLD_S = 3.0            # the picture holds this long after the question that stops the viewer to guess (task 2.17)


def applies(plan: dict) -> bool:
    """Narration v2 runs for a plan that has a Material Pack and a blueprint that names details for its beats."""
    return material.has(plan) and any(b.get("use") for b in (plan.get("blueprint") or {}).get("beats", []))


def split_sentences(text: str) -> list[str]:
    """The prose as sentences, in code: split after । . ? ! ; a fragment of one word is joined to the sentence before it; a sentence without an ending gets one."""
    parts = [p.strip() for p in _SENT_SPLIT.split(re.sub(r"\s+", " ", text or "").strip()) if p.strip()]
    out: list[str] = []
    for p in parts:
        if out and len(p.split()) < 2:
            out[-1] = out[-1].rstrip() + " " + p
        else:
            out.append(p)
    return [s if re.search(r"[।.?!…]$", s) else s + ("।" if re.search(r"[ऀ-ॿ]$", s) else ".") for s in out]


def covered(item: dict, text: str) -> bool:
    """Is this detail told in the text? A keyword of the item (`say`), or two content words of its detail, in Latin or Devanagari letters."""
    low = (text or "").lower()
    if any(k.strip() and k.strip().lower() in low for k in item.get("say", [])):
        return True
    words = {w for w in re.findall(r"[a-z]{4,}", (item.get("detail", "") + " " + item.get("who", "")).lower()) if w not in _STOP}
    return len([w for w in words if w in low]) >= 2


def coverage(items: list[dict], text: str) -> tuple[float, list[dict]]:
    if not items:
        return 1.0, []
    missing = [it for it in items if not covered(it, text)]
    return 1 - len(missing) / len(items), missing


class TagRow(M):
    n: int = 0
    emotion: Str = "neutral"
    pause_after_s: float = 0.0


class TagOut(M):
    sentences: list[TagRow] = []
    pronounce: list[Pronounce] = []
    emphasis: StrList = []


NEW_WORD_FLOOR = 0.40              # a part after the first must bring at least this share of words the video has not used yet (audit 14.1: density fell from 97% to 30%)
DEAD_RUN = 7                       # sentences in a row (about 25 seconds) that tell none of the part's details


def new_word_share(sentences: list[str], spoken: list[str]) -> float:
    seen = {w for t in spoken for w in audit._tokens(t)}
    toks = [w for s in sentences for w in audit._tokens(s)]
    return sum(1 for w in toks if w not in seen) / len(toks) if toks else 1.0


def dead_stretch(sentences: list[str], items: list[dict]) -> tuple[int, int] | None:
    """The first run of more than DEAD_RUN sentences in which no new detail of the part is told, as 1-based sentence numbers, or None."""
    told: set[str] = set()
    last = 0                                                                  # the sentence (0-based, -1 before the start) where a new detail last appeared
    start = -1
    for i, s in enumerate(sentences):
        new = [it["id"] for it in items if it["id"] not in told and covered(it, s)]
        if new:
            told.update(new)
            start = i
        elif i - start > DEAD_RUN and len(told) < len(items):
            return start + 2, i + 1
    return None


def problems(sentences: list[str], ctx: SimpleNamespace) -> tuple[list[str], list[dict]]:
    """Every defect of a beat's prose that the checks can see, as sentences for the editor, and the details of the beat that are missing."""
    text = " ".join(sentences)
    out: list[str] = []
    words = len(text.split())
    if ctx.first and sentences and len(sentences[0].split()) > FIRST_SENTENCE_MAX_WORDS:
        out.append(f"The first sentence has {len(sentences[0].split())} words; it must have {FIRST_SENTENCE_MAX_WORDS} or fewer: one striking concrete moment, details after it.")
    if words > ctx.per_beat * 1.5:
        out.append(f"The part has {words} words and has room for about {ctx.per_beat}: keep the most striking details and cut the rest.")
    elif words < ctx.per_beat * 0.6:
        out.append(f"The part has {words} words and needs about {ctx.per_beat}: tell the details fully, one clear sentence each.")
    ids = [m.group() for s in sentences for m in ID_IN_TEXT.finditer(s)]
    if ids:
        out.append("The text contains the labels of the details (" + ", ".join(dict.fromkeys(ids)) + "): those are notes for you, never words to speak. Say the detail itself.")
    said = {h for s in sentences for h in lexicon.hits(s, ctx.avoid)}
    if said:
        out.append("These phrases are worn out in this video; say the thing itself instead, specific to this moment: " + " | ".join(sorted(said)[:8]))
    q = sum(1 for s in sentences if "?" in s)
    room = max(1, len(sentences) // 8) + (1 if ctx.last else 0)
    if q > room or ctx.questions + q > MAX_QUESTIONS_IN_VIDEO + (1 if ctx.last else 0):
        out.append(f"There are {q} question(s) in this part and the video has used {ctx.questions} already: allow at most {room} here. Turn the others into statements that tell the answer or the fact.")
    acc = safety.accusations(sentences)
    if acc:
        out.append("A crime is stated as plain fact; say what police or a complainant say or allege (पुलिस के मुताबिक, आरोप है कि): " + " | ".join(a[:80] for a in acc[:3]))
    bad = svara.foreign_chars(text)
    if bad:
        out.append("It contains characters that cannot be spoken: " + " ".join(bad) + ". Use Devanagari for Hindi and Latin letters for English words only; numbers as words, never digits.")
    roman = [s for s in sentences if svara.romanised_hindi(s)]
    if roman:
        out.append(f"Hindi is written in Latin letters ({roman[0][:60]}): Hindi words must be in Devanagari.")
    mixed = svara.mixed_words(text)
    if mixed:
        out.append("English and Hindi letters are glued in one word: " + " ".join(mixed) + ". Write the English word alone, then a space, then the Hindi particle.")
    again = planner.repeated_sentences(ctx.spoken, sentences)
    if again:
        out.append("These sentences repeat something already said in the video: " + " | ".join(again[:3]))
    samey = planner.overused_openers(ctx.spoken, sentences)
    if samey:
        out.append("Too many sentences begin like earlier ones (" + " | ".join(samey[:4]) + "): start them with something specific to this moment.")
    out += lexicon.profile_problems(sentences, ctx.profile, ctx.spoken)
    if not ctx.first and ctx.spoken:
        share = new_word_share(sentences, ctx.spoken)
        if share < NEW_WORD_FLOOR:
            out.append(f"Only {round(100 * share)}% of the words are new to the video (the least allowed is {round(100 * NEW_WORD_FLOOR)}%): this part repeats what was said; tell new things.")
    stretch = dead_stretch(sentences, ctx.items)
    if stretch:
        out.append(f"Sentences {stretch[0]} to {stretch[1]} tell none of the details of this part: replace them with the details that are still missing, or cut them.")
    payoff = getattr(ctx, "payoff", "")
    if payoff and getattr(ctx, "is_payoff", False) and not covered({"detail": payoff, "say": []}, text):
        out.append(f"This part must tell the answer to the film's central question in plain words: {payoff}")
    if ctx.last and sentences and sentences[-1].rstrip().endswith("?") and YES_NO.match(sentences[-1]):
        out.append("The closing question can be answered with yes or no; ask an open one (कौन, क्यों, कैसे, क्या-क्या, किसने) that makes the viewer give their own view in the comments.")
    ratio, missing = coverage(ctx.items, text)
    if ratio < COVER_SHARE:
        out.append(f"Only {round(100 * ratio)}% of the details this part must tell are in it; tell the missing ones.")
    else:
        missing = [it for it in missing if it.get("weight", 0) >= 3]                       # enough is told: only an important detail still has to be added
    return out, missing


def item_lines(items: list[dict], show: set[str]) -> str:
    rows = []
    for it in items:
        bits = "; ".join(x for x in (it.get("when"), it.get("where"), it.get("who")) if x)
        rows.append(f"{it['id']} [{it['kind']}{', ALLEGED' if it.get('alleged') else ''}] {it['detail']}" + (f" ({bits})" if bits else "") + ("  [SHOWN ON SCREEN]" if it["id"] in show else ""))
    return "\n".join(rows)


def experience_lines(bp: dict, beat_id: str) -> str:
    """What the film's experience design asks of this beat: the stake in the opening, the clock, the clue shown before its answer, the set piece, the pause-and-guess, the closing question."""
    ex = bp.get("experience") or {}
    if not ex:
        return ""
    out = []
    if ex.get("stake_to_viewer") and beat_id == (bp.get("beats") or [{}])[0].get("id"):
        out.append(f"make the viewer feel the stake early: {ex['stake_to_viewer']}")
    if ex.get("clock_device") and str(ex["clock_device"]).lower() not in ("none", ""):
        out.append(f"keep the film's clock in the telling: {ex['clock_device']}")
    if ex.get("clue_device"):
        out.append(f"the clue shown before it is explained: {ex['clue_device']}")
    sp = ex.get("set_piece") if isinstance(ex.get("set_piece"), dict) else {}
    if sp.get("beat") == beat_id:
        out.append(f"THIS PART IS THE SET PIECE: tell it slowly, shot by shot, with every detail: {sp.get('idea', '')}")
    part = ex.get("participation") if isinstance(ex.get("participation"), dict) else {}
    if part.get("pause_and_guess_beat") == beat_id:
        out.append("end this part with one short sentence that stops and asks the viewer what they think happens next (the answer comes right after, in the next part)")
    return ("\n" + "\n".join("- " + x for x in out) + "\n") if out else ""


def draft_user(ctx: SimpleNamespace) -> str:
    bp, b = ctx.bp, ctx.beat
    told = "\n".join(f"- {x}" for x in ctx.told[-8:]) or "- nothing: this is the opening of the video"
    closing = planner.closing(bp, ctx.last).strip() if ctx.last else (f"End this part on: {b['ends_on']} (as a statement or one image, not a recap)." if b.get("ends_on") else "")
    opening = (f"This is the opening of the video: the first sentence has at most {FIRST_SENTENCE_MAX_WORDS} words and puts the viewer inside one concrete moment; the central question is raised within the first fifteen seconds, "
               "and what answers it is held back.") if ctx.first else ""
    return (f"THE FILM\npromise: {bp.get('viewer_promise', '')}\ncentral question: {bp.get('central_question', '')}\nwhat is at stake: {bp.get('stakes', '')}\n\n"
            f"THIS PART ({b.get('name', '')}, part {ctx.pos} of {ctx.total})\npurpose: {b.get('purpose', '')}\nthe viewer should understand or feel: {b.get('takeaway', '')}\n"
            f"the turn of this part: {b.get('turn', '') or '(none given)'}\nthe new thing the viewer gets: {b.get('reward', '') or '(none given)'}\nthe question it opens: {b.get('question', '') or '(none)'}\n{experience_lines(bp, b.get('id', ''))}\n"
            f"DETAILS TO TELL, IN THIS ORDER:\n{item_lines(ctx.items, set(b.get('show', [])))}\n\n"
            f"NAMES (use exactly these spellings): {', '.join(n['name'] for n in ctx.names) or '(as in the details)'}\n\n"
            f"ALREADY TOLD (never tell these again):\n{told}\n\n{opening}\n{closing}\n\nWrite about {ctx.per_beat} words now.")


def edit_user(text: str, found: list[str], missing: list[dict], ctx: SimpleNamespace) -> str:
    probs = "\n".join(f"- {p}" for p in found) or "- none: only tighten it (cut what adds nothing, merge fragments)"
    miss = item_lines(missing, set()) or "none"
    return f"PART PROSE:\n{text}\n\nPROBLEMS FOUND:\n{probs}\n\nMISSING DETAILS (add each, in one or two natural sentences):\n{miss}\n\nTARGET LENGTH: about {ctx.per_beat} words."


async def tag(sentences: list[str], backend, s: dict) -> TagOut:
    """Emotion, pauses and pronunciation for a part whose words are final. Any failure leaves every sentence neutral: the voice-direction step adds the real tags later."""
    lines = "\n".join(f"{i}. {t}" for i, t in enumerate(sentences, 1))
    try:
        return (await llm.JsonCaller(backend, s).call(P.NARRATE_TAG, f"THE PART, {len(sentences)} sentence(s):\n{lines}\n\nMark it up now.", TagOut)).value
    except llm.LLMError:
        return TagOut()


def _emotion(row: TagRow | None) -> tuple[str, float]:
    if not row:
        return "neutral", 0.0
    return svara.norm_emotion(row.emotion), max(0.0, min(svara.MAX_PAUSE_S, float(row.pause_after_s or 0)))


async def _candidate(ctx: SimpleNamespace, backend, s: dict, system: str, edit_system: str, warm: float | None = None) -> tuple[str, list[str], int]:
    """One finished version of the part: a draft, then editor rounds until the checks pass (or the rounds are used). `warm` raises the draft's temperature for a second version."""
    tokens = 0
    drafter = llm.TextCaller(backend, s)
    if warm:
        drafter.override = {"temperature": warm}
    res = await drafter.call(system, draft_user(ctx))
    tokens += res.tokens_out
    text = res.value if isinstance(res.value, str) else str(res.value)
    found: list[str] = []
    for _round in range(EDIT_ROUNDS):
        found, missing = problems(split_sentences(text), ctx)
        res = await llm.TextCaller(backend, s).call(edit_system, edit_user(text, found, missing, ctx))
        tokens += res.tokens_out
        text = str(res.value)
        found, missing = problems(split_sentences(text), ctx)
        if not found:
            break
    if any(svara.romanised_hindi(s) for s in split_sentences(text)):                    # the editor could not get the script right: a plain transliteration task, then the checks again
        res = await llm.TextCaller(backend, s).call(P.DEVANAGARI, text)
        tokens += res.tokens_out
        text = str(res.value)
        found, _ = problems(split_sentences(text), ctx)
    return text, found, tokens


class Verdict(M):
    winner: Str = "A"
    reason: Str = ""


async def pick(a: str, b: str, ctx: SimpleNamespace, backend, s: dict) -> str:
    """Which of two versions reads better: asked twice with the order swapped; the version that wins both times is kept, a split decision keeps the first (task 2.8)."""
    role = "an OPENING part" if ctx.first else "the CLOSING part"
    async def ask(x: str, y: str) -> str:
        try:
            v = (await llm.JsonCaller(backend, s).call(P.JUDGE_NARRATION, f"This is {role} of the film. Central question: {ctx.bp.get('central_question', '')}\n\nVERSION A:\n{x}\n\nVERSION B:\n{y}", Verdict)).value
        except llm.LLMError:
            return ""
        return "A" if v.winner.strip().upper().startswith("A") else "B"
    first, second = await ask(a, b), await ask(b, a)
    if first == "A" and second == "B":
        return a
    if first == "B" and second == "A":
        return b
    return a


async def write_beat(ctx: SimpleNamespace, backend, s: dict) -> tuple[NarrationOut, list[dict], int]:
    """The part's narration as a one-segment NarrationOut, the findings the last round could not fix (stored on the segment), and the tokens written. The losing version of
    an opening or closing part is left on `ctx.alt`."""
    system = (P.NARRATE_DRAFT.replace("{words}", str(ctx.per_beat)) + ("\n\n" + ctx.rules if ctx.rules else "") + "\n\n" + lexicon.profile_note(ctx.profile) + "\n\n" + safety.ATTRIBUTION_RULE + getattr(ctx, "tell_note", ""))
    edit_system = P.NARRATE_EDIT + getattr(ctx, "polish_note", "") + ("\n\n" + ctx.rules if ctx.rules else "") + "\n\n" + lexicon.profile_note(ctx.profile)
    text, found, tokens = await _candidate(ctx, backend, s, system, edit_system)
    ctx.alt = ""
    if (ctx.first or ctx.last) and getattr(ctx, "best_of_two", False):
        other, found2, tok2 = await _candidate(ctx, backend, s, system, edit_system, warm=0.9)
        tokens += tok2
        winner = await pick(text, other, ctx, backend, s)
        if winner is other:
            text, found, ctx.alt = other, found2, text
        else:
            ctx.alt = other
    text, renamed = material.canonical(text, ctx.names)
    gate = None
    if getattr(ctx, "hindi_gate", False):
        gate = await hindigate.check(split_sentences(text), ctx.items, ctx.profile, backend, s)
        if not gate["ok"]:                                                                 # one more editor round with what the gate found, then the result stands
            res = await llm.TextCaller(backend, s).call(edit_system, edit_user(text, gate["issues"], [it for it in ctx.items if it["id"] in gate["missing"]], ctx))
            tokens += res.tokens_out
            text = material.canonical(str(res.value), ctx.names)[0]
            gate = await hindigate.check(split_sentences(text), ctx.items, ctx.profile, backend, s)
    sentences = split_sentences(text)
    marks = await tag(sentences, backend, s)
    by_n = {r.n: r for r in marks.sentences}
    guess = ((ctx.bp.get("experience") or {}).get("participation") or {}).get("pause_and_guess_beat") == ctx.beat.get("id")
    sents = []
    for i, t in enumerate(sentences, 1):
        emo, pause = _emotion(by_n.get(i))
        if guess and i == len(sentences):
            pause = max(pause, PAUSE_AND_GUESS_HOLD_S)                                      # the picture holds while the viewer thinks (the planned pause survives the dead-air trim)
        sents.append(Sentence(text=t, emotion=emo, pause_after_s=pause))
    seg = SegmentOut(beat=ctx.beat["id"], sentences=sents, emphasis=marks.emphasis[:6], pronounce=marks.pronounce, facts_used=list(ctx.beat.get("use", [])))
    issues = [{"where": "", "kind": "narration_check", "level": "warn", "text": f, "detail": "the last editing round could not fix this"} for f in found]
    if gate:
        issues += hindigate.as_issues(gate)
    return NarrationOut(segments=[seg]), issues, tokens
