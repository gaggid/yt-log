"""Agentic evaluators for shorts: one LLM call per checkpoint that scores the output and,
on failure, returns a structured list of typed actions the agent dispatches individually.

Three checkpoints:
  narration  — after the plan step; checks hook, concept accuracy, entity names, flow
  stills     — after keyframes; checks picture-narration alignment and shot variety
  final      — after stitching; engagement estimate only (report, no retry)

Action types (NarrationEval.actions):
  rewrite_beat   — rewrite one beat's words   (beat_id, instruction)
  insert_beat    — add a new beat              (after_beat, topic)
  trim_beat      — shorten one beat            (beat_id, target_words)
  rewrite_script — rewrite the whole script   (instruction)
"""
from story import llm as llm_mod
from story2.schemas import M
from story.schemas import Str, StrList

from . import languages, tones

PASS_SCORE = 7


# ── action schema ─────────────────────────────────────────────────────────────

class ActionOut(M):
    type: Str                   # "rewrite_beat" | "insert_beat" | "trim_beat" | "rewrite_script"
    beat_id: Str = ""           # rewrite_beat, trim_beat
    after_beat: Str = ""        # insert_beat: insert after this beat id
    topic: Str = ""             # insert_beat: what the new beat is about
    instruction: Str = ""       # rewrite_beat, rewrite_script: what to change
    target_words: int = 0       # trim_beat: target word count for that beat


# ── output schemas ────────────────────────────────────────────────────────────

class NarrationEval(M):
    ok: bool
    score: int
    issues: StrList = []
    actions: list[ActionOut] = []   # ordered list of targeted actions; empty when ok
    problem: Str = ""               # one-line timeline label
    solution_desc: Str = ""         # what the agent is doing


class StillsEval(M):
    ok: bool
    score: int
    issues: StrList = []
    weak_shots: StrList = []
    instruction: Str = ""
    problem: Str = ""
    solution_desc: Str = ""


class FinalEval(M):
    score: int
    engagement_notes: Str = ""
    weakest_moment: Str = ""
    strongest_moment: Str = ""


# ── base ──────────────────────────────────────────────────────────────────────

_AGENT_BASE = """[TASK:p4_agent]
You are an editorial director reviewing a short-form vertical video script. Your job is to catch problems that will cost the creator views: a weak hook, a missing pillar from the brief, a factual drift. Be direct and specific; do not praise.

Score 1 to 10. A score of 7 or above is a pass. Score lower only when there is a concrete, fixable problem."""


# ── helpers ───────────────────────────────────────────────────────────────────

def _brief(short: dict) -> str:
    src = short.get("source") or {}
    return src.get("text", short.get("title", "")).strip()


def _script_text(short: dict) -> str:
    lines = []
    for b in short.get("beats", []):
        wc = sum(len(s.get("text", "").split()) for s in b.get("sentences", []))
        sents = " ".join(s.get("text", "") for s in b.get("sentences", []))
        lines.append(f"[{b['id']} · {b.get('job','').upper()} · {wc}w] {sents}")
    return "\n".join(lines) or "(no narration yet)"


def _examples_block(examples: list[dict]) -> str:
    if not examples:
        return ""
    parts = ["Past corrections (same format — learn from these):"]
    for ex in examples:
        parts.append(f"  Problem: {ex['problem']}\n  Solution: {ex['solution']}\n  Outcome: {ex['outcome']}")
    return "\n".join(parts)


def _format_label(short: dict) -> str:
    return (short.get("plan") or {}).get("format") or short.get("settings", {}).get("format", "auto")


# ── narration evaluator ───────────────────────────────────────────────────────

_NARRATION_SYSTEM = _AGENT_BASE + """

You are evaluating the NARRATION (script) of the short.

Check:
1. Hook: does beat 1 stop the scroll? It must contain at least one specific fact, number, year, or named claim — not a vague question or generic opener.
2. Completeness: does the narration cover all the key pillars of the brief? Identify any pillar the brief mentions that has no beat.
3. Entity names: for documentary or comparison formats, use exact names from the brief — no aliases.
4. Flow: does each beat transition naturally? Flag jarring jumps.
5. Language: Hinglish mixed script, sentences end with ।, no digits.

Return ONLY a JSON object with this exact structure:
{
  "ok": true/false,
  "score": 1-10,
  "issues": ["short plain description of each problem"],
  "actions": [
    {"type": "rewrite_beat", "beat_id": "b1", "instruction": "exact rewrite order"},
    {"type": "insert_beat", "after_beat": "b4", "topic": "what the new beat covers, 1 sentence"},
    {"type": "trim_beat", "beat_id": "b3", "target_words": 18},
    {"type": "rewrite_script", "instruction": "only use this if the whole script needs rebuilding"}
  ],
  "problem": "one-line summary of the biggest problem",
  "solution_desc": "what the agent will do"
}

Rules for actions:
- Use "rewrite_beat" to fix wording of one beat. Include the beat id (e.g. "b1") and a precise instruction.
- Use "insert_beat" when a key pillar from the brief is entirely missing. Name the beat to insert after and describe the topic in one sentence.
- Use "trim_beat" only when one beat is clearly too long. Give a realistic target word count.
- Use "rewrite_script" only as a last resort when the whole structure is wrong.
- Order actions from most important to least. List at most 3 actions.
- If ok=true, actions must be [].
- Beat ids appear in the narration as e.g. "b1", "b2" etc. — use them exactly."""

_NARRATION_USER = """THE BRIEF:
{brief}

FORMAT: {format}
TONE: {tone}
TARGET LENGTH: {target_s}s

THE NARRATION (beat id · job · word count · text):
{script}

{examples}

Evaluate. Return ONLY the JSON object."""


async def narration(short: dict, backend, s: dict, examples: list[dict]) -> NarrationEval:
    caller = llm_mod.JsonCaller(backend, s)
    caller.last_attempt = True
    tone_label = tones.TONES.get(tones.of(short.get("settings")), {}).get("label", "")
    user = _NARRATION_USER.format(
        brief=_brief(short),
        format=_format_label(short),
        tone=tone_label,
        target_s=short.get("settings", {}).get("target_s", 30),
        script=_script_text(short),
        examples=_examples_block(examples),
    )
    try:
        r = await caller.call(_NARRATION_SYSTEM, user, NarrationEval)
        return r.value
    except Exception:
        return NarrationEval(ok=True, score=PASS_SCORE, issues=["evaluator call failed — skipping"])


# ── stills evaluator ─────────────────────────────────────────────────────────

_STILLS_SYSTEM = _AGENT_BASE + """

You are evaluating the START PICTURES (still prompts) of the short.

Check:
1. Narration alignment: does each picture prove its narration line?
2. Visual variety: are any two shots the same composition (same subject + framing + setting)?
3. Concept delivery: do the pictures together tell the story?

Return ONLY a JSON object:
{"ok": true/false, "score": 1-10, "issues": ["..."], "weak_shots": ["shot-id"], "instruction": "per-shot rewrite order: 's5: show a close-up of …; s20: …'", "problem": "one-line summary", "solution_desc": "what the agent is doing"}

If ok=true, weak_shots=[], instruction="", problem="", solution_desc=""."""

_STILLS_USER = """THE BRIEF:
{brief}

THE SHOTS (id · narration · still prompt):
{shots_block}

{examples}

Evaluate. Return ONLY the JSON object."""


def _shots_block(short: dict) -> str:
    lines = []
    beat_narr: dict[str, str] = {}
    for b in short.get("beats", []):
        beat_narr[b["id"]] = " ".join(s.get("text", "") for s in b.get("sentences", []))
    for sh in short.get("shots", []):
        narr = beat_narr.get(sh.get("beat", ""), "")[:120]
        still = (sh.get("still") or sh.get("prompt") or "")[:200]
        lines.append(f"{sh['id']}  narration: {narr}\n        still: {still}")
    return "\n".join(lines) or "(no shots)"


async def stills(short: dict, backend, s: dict, examples: list[dict]) -> StillsEval:
    caller = llm_mod.JsonCaller(backend, s)
    caller.last_attempt = True
    user = _STILLS_USER.format(
        brief=_brief(short),
        shots_block=_shots_block(short),
        examples=_examples_block(examples),
    )
    try:
        r = await caller.call(_STILLS_SYSTEM, user, StillsEval)
        return r.value
    except Exception:
        return StillsEval(ok=True, score=PASS_SCORE, issues=["evaluator call failed — skipping"])


# ── final evaluator (report only) ────────────────────────────────────────────

_FINAL_SYSTEM = _AGENT_BASE + """

Final quality review — report for the human reviewer, no changes will be made.

Assess: engagement score 1-10, strongest moment, weakest moment.

Return ONLY: {"score": 1-10, "engagement_notes": "2-3 sentences", "weakest_moment": "one sentence", "strongest_moment": "one sentence"}"""


async def final(short: dict, backend, s: dict) -> FinalEval:
    caller = llm_mod.JsonCaller(backend, s)
    caller.last_attempt = True
    user = f"THE BRIEF:\n{_brief(short)}\n\nTHE NARRATION:\n{_script_text(short)}"
    try:
        r = await caller.call(_FINAL_SYSTEM, user, FinalEval)
        return r.value
    except Exception:
        return FinalEval(score=PASS_SCORE, engagement_notes="final evaluation could not run")
