"""Agentic auto-run for long-form plans: wraps the standard auto-run pipeline with three
editorial checkpoints (narration, storyboard, final) that use an LLM to score the output
and, on failure, write a targeted fix instruction and retry the step.

Iteration budget
  MAX_RETRIES_PER_CHECKPOINT = 2  (3 total attempts per checkpoint)
  MAX_TOTAL_RETRIES = 8           (across all checkpoints for the whole run)
  PASS_SCORE = 7                  (score >= this passes without retry)
  Hard stop: no improvement between attempt 1 and 2 → stop retrying that checkpoint."""
import hashlib
import time

from story import settings as settings_mod
from story.agent_store import PASS_SCORE, for_plan, recent_examples, save_decision
from story2 import planner, storyboard as sb

from . import auto
from .auto import AutoStop
from . import evaluators

MAX_RETRIES_PER_CHECKPOINT = 2
MAX_TOTAL_RETRIES = 8


def _run_id(plan_id: str) -> str:
    return hashlib.sha1(f"{plan_id}{time.time()}".encode()).hexdigest()[:10]


def _story_type(plan: dict) -> str:
    return plan.get("settings", {}).get("story_type", "")


def _sub(progress, label: str):
    return lambda d, t, l="": progress(d, t, f"{label}: {l}" if l else label)


def _record(decisions: list[dict], run_id: str, plan_id: str, story_type: str, checkpoint: str,
            attempt: int, eval_result, score_before: int, score_after: int | None,
            resolved: bool, action_taken: str) -> None:
    if eval_result.ok or score_after is None:
        outcome = f"Score {score_before}/10. {'Passed.' if resolved else 'Unresolved — please edit manually.'}"
    else:
        direction = "improved" if (score_after or 0) > score_before else "unchanged"
        outcome = f"Score {score_before} → {score_after}/10 ({direction}). {'Passed.' if resolved else 'Stopped after max retries.'}"

    entry = {
        "checkpoint": checkpoint,
        "attempt": attempt,
        "score_before": score_before,
        "score_after": score_after,
        "resolved": resolved,
        "problem": eval_result.problem or (f"Score {score_before}/10" if not eval_result.ok else f"Score {score_before}/10 — passed"),
        "solution": action_taken or ("No action needed." if eval_result.ok else eval_result.solution_desc or "Rewrote with targeted instruction."),
        "outcome": outcome,
    }
    decisions.append(entry)
    save_decision(
        plan_id=plan_id,
        run_id=run_id,
        story_type=story_type,
        checkpoint=checkpoint,
        attempt=attempt,
        score_before=score_before,
        score_after=score_after,
        resolved=resolved,
        problem=entry["problem"],
        solution=entry["solution"],
        outcome=outcome,
        instruction_used=getattr(eval_result, "instruction", "") or "",
    )


async def run(plan_id: str, progress, s: dict | None = None, api_key: str = "") -> dict:
    """Run the full long-form pipeline with agentic checkpoints.
    Returns {"decisions": [...], "notes": [...], "stopped": str | None}."""
    s = s or settings_mod.get()
    api_key = api_key or settings_mod.api_key()
    from story import llm as llm_mod
    be = llm_mod.ChatBackend(s, api_key)

    decisions: list[dict] = []
    notes: list[str] = []
    run_id = _run_id(plan_id)
    total_retries = 0

    plan = planner.get_plan(plan_id)
    story_type = _story_type(plan)

    # ── PHASE 1: up to and including narration ────────────────────────────────
    narration_stages = [k for k, _ in auto.STAGES if k in ("material", "blueprint", "narration", "events")]
    for key in narration_stages:
        if not auto.done(plan_id, key):
            progress(0, 4, f"running: {key}")
            try:
                await auto.run_stage(plan_id, key, be, s, api_key, progress, notes)
            except AutoStop as e:
                return {"decisions": decisions, "notes": notes, "stopped": str(e)}

    # Narration checkpoint
    plan = planner.get_plan(plan_id)
    examples = recent_examples(story_type, "narration")
    score_prev = None
    for attempt in range(1, MAX_RETRIES_PER_CHECKPOINT + 2):
        result = await evaluators.narration(plan, be, s, examples)
        score_now = result.score
        if result.ok or attempt > MAX_RETRIES_PER_CHECKPOINT or total_retries >= MAX_TOTAL_RETRIES:
            resolved = result.ok
            _record(decisions, run_id, plan_id, story_type, "narration",
                    attempt, result, score_prev or score_now, score_now if attempt > 1 else None, resolved,
                    "No issues found." if result.ok else "Stopped — max retries or budget reached.")
            break
        if score_prev is not None and score_now <= score_prev:
            _record(decisions, run_id, plan_id, story_type, "narration",
                    attempt, result, score_prev, score_now, False,
                    "Stopped — score did not improve between retries.")
            notes.append("Narration: score stuck after rewrite; review and edit manually.")
            break
        _record(decisions, run_id, plan_id, story_type, "narration",
                attempt, result, score_now, None, False,
                f"Rewriting narration: {result.instruction}")
        score_prev = score_now
        # Rewrite all narration beats with the instruction
        await planner.make_narration(plan_id, be, s, None, _sub(progress, "rewriting narration"),
                                     only_missing=False)
        plan = planner.get_plan(plan_id)
        total_retries += 1

    # ── PHASE 2: characters + storyboard ─────────────────────────────────────
    sb_stages = [k for k, _ in auto.STAGES if k in ("characters", "storyboard", "voicetags", "prompts", "repeats")]
    for key in sb_stages:
        if not auto.done(plan_id, key):
            progress(1, 4, f"running: {key}")
            try:
                await auto.run_stage(plan_id, key, be, s, api_key, progress, notes)
            except AutoStop as e:
                return {"decisions": decisions, "notes": notes, "stopped": str(e)}

    # Storyboard checkpoint
    plan = planner.get_plan(plan_id)
    examples = recent_examples(story_type, "storyboard")
    score_prev = None
    for attempt in range(1, MAX_RETRIES_PER_CHECKPOINT + 2):
        result = await evaluators.storyboard(plan, be, s, examples)
        score_now = result.score
        if result.ok or attempt > MAX_RETRIES_PER_CHECKPOINT or total_retries >= MAX_TOTAL_RETRIES:
            resolved = result.ok
            _record(decisions, run_id, plan_id, story_type, "storyboard",
                    attempt, result, score_prev or score_now, score_now if attempt > 1 else None, resolved,
                    "No issues found." if result.ok else "Stopped — max retries or budget reached.")
            break
        if score_prev is not None and score_now <= score_prev:
            _record(decisions, run_id, plan_id, story_type, "storyboard",
                    attempt, result, score_prev, score_now, False,
                    "Stopped — storyboard score did not improve.")
            notes.append("Storyboard: score stuck; review scenes manually.")
            break
        weak = result.weak_scenes
        if not weak:
            _record(decisions, run_id, plan_id, story_type, "storyboard",
                    attempt, result, score_now, None, True, "Issues noted but no specific scenes flagged.")
            break
        _record(decisions, run_id, plan_id, story_type, "storyboard",
                attempt, result, score_now, None, False,
                f"Regenerating scenes: {', '.join(weak[:4])}.")
        score_prev = score_now
        for scene_id in weak:
            try:
                await sb.regenerate_scene(scene_id, be, s, note=result.instruction)
            except Exception:
                pass
        from story2 import imgplan
        import asyncio
        await asyncio.to_thread(imgplan.compile_plan, plan_id)
        plan = planner.get_plan(plan_id)
        total_retries += 1

    # ── PHASE 3: approve + export + voice + pictures + rest ──────────────────
    remaining = [k for k, _ in auto.STAGES if k not in narration_stages + sb_stages]
    for key in remaining:
        if not auto.done(plan_id, key):
            progress(2, 4, f"running: {key}")
            try:
                await auto.run_stage(plan_id, key, be, s, api_key, progress, notes)
            except AutoStop as e:
                return {"decisions": decisions, "notes": notes, "stopped": str(e)}

    # Final evaluation (report only)
    progress(4, 4, "final quality check")
    plan = planner.get_plan(plan_id)
    final_result = await evaluators.final(plan, be, s)
    decisions.append({
        "checkpoint": "final",
        "attempt": 1,
        "score_before": final_result.score,
        "score_after": None,
        "resolved": True,
        "problem": f"Predicted engagement score: {final_result.score}/10",
        "solution": "Final report only — no automatic action.",
        "outcome": f"{final_result.engagement_notes or ''} Weakest: {final_result.weakest_moment or 'n/a'}. Strongest: {final_result.strongest_moment or 'n/a'}",
    })
    save_decision(
        plan_id=plan_id, run_id=run_id, story_type=story_type, checkpoint="final",
        attempt=1, score_before=final_result.score, score_after=None, resolved=True,
        problem=f"Predicted engagement score: {final_result.score}/10",
        solution="Final report only.",
        outcome=decisions[-1]["outcome"],
    )

    return {"decisions": decisions, "notes": notes, "stopped": None}
