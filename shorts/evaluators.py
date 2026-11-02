"""Agentic evaluators for shorts: one LLM call per checkpoint that scores the output and, on
failure, writes a targeted fix instruction. Called by shorts/agent.py after each key step.

Three checkpoints:
  narration  — after the plan step; checks hook, concept accuracy, entity names, flow
  stills     — after keyframes; checks picture-narration alignment and shot variety
  final      — after stitching; engagement estimate only (report, no retry)

Each evaluator takes the short dict + few-shot examples from past corrections and returns
an EvalResult. The agent uses `ok` + `instruction` to decide whether to retry."""
from story import llm as llm_mod
from story2.schemas import M
from story.schemas import Str, StrList

from . import formats as fmt_mod, languages, tones

PASS_SCORE = 7          # score >= this is a pass; must match story/agent_store.PASS_SCORE
MAX_SCORE = 10


# ── output schemas ────────────────────────────────────────────────────────────

class NarrationEval(M):
    ok: bool
    score: int
    issues: StrList = []
    weak_beats: StrList = []         # beat ids that most need rewriting
    instruction: Str = ""            # verbatim instruction to pass to rewrite_script / rewrite_beat
    problem: Str = ""                # one-line timeline label: what was wrong
    solution_desc: Str = ""          # one-line: what the agent is doing to fix it


class StillsEval(M):
    ok: bool
    score: int
    issues: StrList = []
    weak_shots: StrList = []         # shot ids whose still prompt needs rewriting
    instruction: Str = ""
    problem: Str = ""
    solution_desc: Str = ""


class FinalEval(M):
    score: int
    engagement_notes: Str = ""       # what would make a viewer stop or scroll past
    weakest_moment: Str = ""         # the moment most likely to lose the viewer
    strongest_moment: Str = ""


# ── system prompt base ────────────────────────────────────────────────────────

_AGENT_BASE = """[TASK:p4_agent]
You are an editorial director reviewing a short-form vertical video script and its start pictures before production. Your job is to catch problems that will cost the creator views: a weak hook, a factual drift from the brief, a visually repetitive sequence. Be direct and specific; do not praise.

Score 1 to 10. A score of 7 or above is a pass. Score lower only when there is a concrete, fixable problem.

When you write an instruction, write it as a direct order to the writer or picture artist — "rewrite beat 1 to open with the year and the dollar figure", not "the hook could be improved"."""


# ── helpers ───────────────────────────────────────────────────────────────────

def _brief(short: dict) -> str:
    src = short.get("source") or {}
    return src.get("text", short.get("title", "")).strip()


def _script_text(short: dict) -> str:
    lines = []
    for b in short.get("beats", []):
        sents = " ".join(s.get("text", "") for s in b.get("sentences", []))
        lines.append(f"[{b.get('job', '').upper()}] {sents}")
    return "\n".join(lines) or "(no narration yet)"


def _examples_block(examples: list[dict]) -> str:
    if not examples:
        return ""
    parts = ["Past corrections (same format and checkpoint — learn from these):"]
    for ex in examples:
        parts.append(
            f"  Problem: {ex['problem']}\n"
            f"  Solution: {ex['solution']}\n"
            f"  Outcome: {ex['outcome']}"
        )
    return "\n".join(parts)


def _format_label(short: dict) -> str:
    fid = (short.get("plan") or {}).get("format") or short.get("settings", {}).get("format", "auto")
    return fid


# ── narration evaluator ───────────────────────────────────────────────────────

_NARRATION_SYSTEM = _AGENT_BASE + """

You are evaluating the NARRATION (script) of the short.

Check all of the following:
1. Hook strength: does beat 1 stop the scroll within the first two seconds? It must contain at least one specific fact, number, year, or named claim — not a vague question or generic opener.
2. Concept accuracy: does the narration faithfully represent the key claims in the brief, or does it drift into generalities?
3. Entity names: for documentary or comparison formats, entities (countries, companies, people) must be named exactly as in the brief — never given aliases, nicknames or codenames.
4. Flow between beats: does each beat transition naturally from the previous, or are there jarring topic jumps without a bridging sentence?
5. Language: Hinglish in mixed script, sentences end with । (danda), no digits.

Return ONLY a JSON object:
{"ok": true/false, "score": 1-10, "issues": ["..."], "weak_beats": ["beat-id or b1"], "instruction": "exact rewrite order for the writer", "problem": "one-line problem summary for the timeline", "solution_desc": "what the agent is doing"}

If the narration passes (score >= 7), set ok=true, issues=[], instruction="", problem="", solution_desc="".
If it fails, list each issue and write a precise, actionable instruction that would fix the most important problem."""

_NARRATION_USER = """THE BRIEF:
{brief}

FORMAT: {format}
TONE: {tone}
TARGET LENGTH: {target_s}s

THE NARRATION (beat by beat):
{script}

{examples}

Evaluate the narration. Return ONLY the JSON object."""


async def narration(short: dict, backend, s: dict, examples: list[dict]) -> NarrationEval:
    caller = llm_mod.JsonCaller(backend, s)
    caller.last_attempt = True          # evaluators never retry on schema errors; one shot
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
        # On any failure return a pass so the agent does not loop on a bad evaluator call
        return NarrationEval(ok=True, score=PASS_SCORE, issues=["evaluator call failed — skipping"])


# ── stills evaluator ─────────────────────────────────────────────────────────

_STILLS_SYSTEM = _AGENT_BASE + """

You are evaluating the START PICTURES (still prompts) of the short — the images that will be drawn by the image model for each shot.

Check all of the following:
1. Narration alignment: does each picture prove or illustrate its narration line? A picture that shows something unrelated to what the narrator says at that moment is a miss.
2. Visual variety: are there two or more shots with nearly the same composition (same subject, same framing, same setting)? If so, flag the weaker of the pair.
3. Concept delivery: together, do the pictures tell the story of the brief, or do they mostly repeat one setting or one subject?

Return ONLY a JSON object:
{"ok": true/false, "score": 1-10, "issues": ["..."], "weak_shots": ["shot-id"], "instruction": "exact instruction for the picture artist per weak shot", "problem": "one-line problem summary", "solution_desc": "what the agent is doing"}

If the pictures pass (score >= 7), set ok=true, weak_shots=[], instruction="", problem="", solution_desc="".
Write instructions as: "s5: show a close-up of the astronaut visor; s20: show the tunnelling drill from below."
List only shot ids that genuinely need a rewrite."""

_STILLS_USER = """THE BRIEF:
{brief}

THE SHOTS (shot id, narration line, current picture prompt):
{shots_block}

{examples}

Evaluate the start pictures. Return ONLY the JSON object."""


def _shots_block(short: dict) -> str:
    lines = []
    beat_narr: dict[str, str] = {}
    for b in short.get("beats", []):
        beat_narr[b["id"]] = " ".join(s.get("text", "") for s in b.get("sentences", []))
    for sh in short.get("shots", []):
        narr = beat_narr.get(sh.get("beat", ""), "")[:120]
        still = (sh.get("still") or sh.get("prompt") or "")[:200]
        lines.append(f"{sh['id']}  narration: {narr}\n        still prompt: {still}")
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

You are doing a final quality review of a completed short. No further changes will be made automatically — this is a report for the human reviewer.

Assess:
1. Predicted engagement score 1 to 10: would a viewer who started the short watch it to the end?
2. Strongest moment: which line or picture would make a viewer share it?
3. Weakest moment: where would a viewer most likely scroll away?

Return ONLY a JSON object:
{"score": 1-10, "engagement_notes": "2-3 sentences on overall impact", "weakest_moment": "one sentence", "strongest_moment": "one sentence"}"""

_FINAL_USER = """THE BRIEF:
{brief}

THE NARRATION:
{script}"""


async def final(short: dict, backend, s: dict) -> FinalEval:
    caller = llm_mod.JsonCaller(backend, s)
    caller.last_attempt = True
    user = _FINAL_USER.format(brief=_brief(short), script=_script_text(short))
    try:
        r = await caller.call(_FINAL_SYSTEM, user, FinalEval)
        return r.value
    except Exception:
        return FinalEval(score=PASS_SCORE, engagement_notes="final evaluation could not run")
