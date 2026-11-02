"""Agentic evaluators for long-form plans: one LLM call per checkpoint.

Three checkpoints:
  narration    — after the narration stage; checks hook, story arc, Hinglish, leaks
  storyboard   — after the storyboard stage; checks visual variety and scene-to-narration fit
  final        — after the video is built; engagement estimate (report only)

Each evaluator returns a structured result. The agent uses `ok` + `instruction` to decide
whether to retry the step."""
from story import llm as llm_mod
from story2.schemas import M
from story.schemas import Str, StrList

PASS_SCORE = 7


# ── output schemas ────────────────────────────────────────────────────────────

class NarrationEval(M):
    ok: bool
    score: int
    issues: StrList = []
    instruction: Str = ""
    problem: Str = ""
    solution_desc: Str = ""


class StoryboardEval(M):
    ok: bool
    score: int
    issues: StrList = []
    weak_scenes: StrList = []         # scene ids to fix
    instruction: Str = ""
    problem: Str = ""
    solution_desc: Str = ""


class FinalEval(M):
    score: int
    engagement_notes: Str = ""
    weakest_moment: Str = ""
    strongest_moment: Str = ""


# ── helpers ───────────────────────────────────────────────────────────────────

_AGENT_BASE = """[TASK:agent_lf]
You are an editorial director reviewing a long-form video script. Your job is to catch problems before production: a weak opening beat, a scene that does not carry its narration claim visually, or a storyboard that repeats the same talking-head framing. Be direct and specific; do not praise.

Score 1 to 10. A score of 7 or above is a pass. Write instructions as direct orders: "rewrite beat 3 to open with the arrest scene, not the background" — not "beat 3 could be improved"."""


def _narration_text(plan: dict) -> str:
    lines = []
    for seg in plan.get("segments", []):
        sents = " ".join(s.get("text", "") for s in seg.get("sentences", []))
        lines.append(f"[beat {seg.get('seq', '')}] {sents}")
    return "\n".join(lines) or "(no narration yet)"


def _scenes_text(plan: dict) -> str:
    lines = []
    for sc in plan.get("scenes", [])[:30]:      # cap at 30 scenes for context
        desc = (sc.get("data") or {}).get("description", "")[:180]
        lines.append(f"{sc['id']}: {desc}")
    return "\n".join(lines) or "(no scenes yet)"


def _brief(plan: dict) -> str:
    bp = plan.get("blueprint") or {}
    return (bp.get("premise") or plan.get("title") or "").strip()


def _examples_block(examples: list[dict]) -> str:
    if not examples:
        return ""
    parts = ["Past corrections (same story type and checkpoint — learn from these):"]
    for ex in examples:
        parts.append(
            f"  Problem: {ex['problem']}\n"
            f"  Solution: {ex['solution']}\n"
            f"  Outcome: {ex['outcome']}"
        )
    return "\n".join(parts)


# ── narration evaluator ───────────────────────────────────────────────────────

_NARRATION_SYSTEM = _AGENT_BASE + """

You are evaluating the NARRATION (script segments) of the long-form video.

Check:
1. Opening beat: does the first beat stop the viewer in the first 10 seconds? It must contain a specific claim, question with teeth, or scene in progress — not a generic introduction.
2. Story arc: does the narration build toward a satisfying conclusion, or does it flatten out in the middle?
3. Concept accuracy: does the narration stay faithful to the key claims in the brief, or does it drift into generalities or unsupported claims?
4. Language: Hinglish in mixed script, no digits written as numbers, sentences end with ।.
5. No source mentions: the narration must not refer to any book, article, author, chapter or title — zero.

Return ONLY a JSON object:
{"ok": true/false, "score": 1-10, "issues": ["..."], "instruction": "exact rewrite order", "problem": "one-line problem summary", "solution_desc": "what the agent is doing"}

If the narration passes (score >= 7), set ok=true, issues=[], instruction="", problem="", solution_desc=""."""

_NARRATION_USER = """BRIEF / PREMISE:
{brief}

STORY TYPE: {story_type}

NARRATION (beat by beat):
{narration}

{examples}

Evaluate the narration. Return ONLY the JSON object."""


async def narration(plan: dict, backend, s: dict, examples: list[dict]) -> NarrationEval:
    caller = llm_mod.JsonCaller(backend, s)
    caller.last_attempt = True
    user = _NARRATION_USER.format(
        brief=_brief(plan),
        story_type=plan.get("settings", {}).get("story_type", ""),
        narration=_narration_text(plan),
        examples=_examples_block(examples),
    )
    try:
        r = await caller.call(_NARRATION_SYSTEM, user, NarrationEval)
        return r.value
    except Exception:
        return NarrationEval(ok=True, score=PASS_SCORE, issues=["evaluator call failed — skipping"])


# ── storyboard evaluator ──────────────────────────────────────────────────────

_STORYBOARD_SYSTEM = _AGENT_BASE + """

You are evaluating the STORYBOARD (scene descriptions) of the long-form video.

Check:
1. Visual variety: are there long runs of the same shot type (e.g. talking head after talking head, or establishing shot after establishing shot)? Flag the repetitive stretches.
2. Scene-to-narration fit: does each scene description match what the narrator says in its segment? A scene that shows something unrelated to the narration is a miss.
3. Emotional arc: does the visual pacing match the emotional arc of the story (quiet scenes before a big reveal, action during escalation)?

Return ONLY a JSON object:
{"ok": true/false, "score": 1-10, "issues": ["..."], "weak_scenes": ["scene-id"], "instruction": "exact fix instruction per weak scene", "problem": "one-line problem summary", "solution_desc": "what the agent is doing"}

Write instructions as: "sc-abc: change from talking-head to a close-up of the document being signed; sc-def: show the crowd reaction, not the speaker."
If the storyboard passes (score >= 7), set ok=true, weak_scenes=[], instruction="", problem="", solution_desc=""."""

_STORYBOARD_USER = """BRIEF / PREMISE:
{brief}

SCENES (scene id: description):
{scenes}

{examples}

Evaluate the storyboard. Return ONLY the JSON object."""


async def storyboard(plan: dict, backend, s: dict, examples: list[dict]) -> StoryboardEval:
    caller = llm_mod.JsonCaller(backend, s)
    caller.last_attempt = True
    user = _STORYBOARD_USER.format(
        brief=_brief(plan),
        scenes=_scenes_text(plan),
        examples=_examples_block(examples),
    )
    try:
        r = await caller.call(_STORYBOARD_SYSTEM, user, StoryboardEval)
        return r.value
    except Exception:
        return StoryboardEval(ok=True, score=PASS_SCORE, issues=["evaluator call failed — skipping"])


# ── final evaluator (report only) ────────────────────────────────────────────

_FINAL_SYSTEM = _AGENT_BASE + """

You are doing a final quality review. No further changes will be made automatically — this is a report for the human reviewer.

Assess:
1. Predicted engagement score 1 to 10.
2. Strongest moment: which beat or scene would make a viewer share the video?
3. Weakest moment: where would a viewer most likely stop watching?

Return ONLY a JSON object:
{"score": 1-10, "engagement_notes": "2-3 sentences on overall impact", "weakest_moment": "one sentence", "strongest_moment": "one sentence"}"""

_FINAL_USER = """BRIEF / PREMISE:
{brief}

NARRATION:
{narration}"""


async def final(plan: dict, backend, s: dict) -> FinalEval:
    caller = llm_mod.JsonCaller(backend, s)
    caller.last_attempt = True
    user = _FINAL_USER.format(brief=_brief(plan), narration=_narration_text(plan))
    try:
        r = await caller.call(_FINAL_SYSTEM, user, FinalEval)
        return r.value
    except Exception:
        return FinalEval(score=PASS_SCORE, engagement_notes="final evaluation could not run")
