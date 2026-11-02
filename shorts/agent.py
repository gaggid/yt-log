"""Agentic auto-run for shorts: wraps the standard auto-run pipeline with three editorial
checkpoints (narration, stills, final) that use an LLM to score the output and, on failure,
write a targeted fix instruction and retry the step.

Iteration budget
  MAX_RETRIES_PER_CHECKPOINT = 2  (3 total attempts per checkpoint)
  MAX_TOTAL_RETRIES = 8           (across all checkpoints for the whole run)
  PASS_SCORE = 7                  (score >= this passes without retry)
  Hard stop: if score does not improve between attempt 1 and attempt 2, stop retrying
             that checkpoint — the problem is structural and needs human input.

Timeline decisions (stored in story.agent_store):
  Each checkpoint attempt records: problem / solution / outcome.
  Resolved decisions are later used as few-shot examples for future runs."""
import asyncio
import hashlib
import time

from story import settings as settings_mod
from story.agent_store import PASS_SCORE, for_plan, recent_examples, save_decision

from . import auto, checks, clips, planner, pipelines as P, store, stitch, upscale, voice as svoice
from . import evaluators

MAX_RETRIES_PER_CHECKPOINT = 2
MAX_TOTAL_RETRIES = 8


def _run_id(short_id: str) -> str:
    return hashlib.sha1(f"{short_id}{time.time()}".encode()).hexdigest()[:10]


def _story_type(short: dict) -> str:
    return (short.get("plan") or {}).get("format") or short.get("settings", {}).get("format", "auto")


def _sub(progress, label: str):
    return lambda d, t, l="": progress(d, t, f"{label}: {l}" if l else label)


def _record(decisions: list[dict], run_id: str, plan_id: str, story_type: str, checkpoint: str,
            attempt: int, eval_result, score_before: int, score_after: int | None,
            resolved: bool, action_taken: str) -> None:
    """Build the timeline entry and persist it."""
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
        "problem": eval_result.problem or (f"Score {score_before}/10 — checking quality" if eval_result.ok else f"Score {score_before}/10"),
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


async def run(short_id: str, backend, s: dict, progress, key: str = "") -> dict:
    """Run the full shorts pipeline with agentic checkpoints.
    Returns {"decisions": [...], "notes": [...], "stopped": str | None}."""
    s = s or settings_mod.get()
    decisions: list[dict] = []
    notes: list[str] = []
    run_id = _run_id(short_id)
    total_retries = 0

    short = store.get(short_id)
    story_type = _story_type(short)
    plan_id = short_id

    # ── PHASE 1: PLAN (write the narration) ──────────────────────────────────
    if not short["shots"]:
        progress(0, 5, "planning the short")
        await planner.make_plan(short_id, backend, s, _sub(progress, "plan"))
        short = store.get(short_id)

    # Narration checkpoint
    examples = recent_examples(story_type, "narration")
    score_prev = None
    for attempt in range(1, MAX_RETRIES_PER_CHECKPOINT + 2):     # 1, 2, 3
        result = await evaluators.narration(short, backend, s, examples)
        score_now = result.score
        if result.ok or attempt > MAX_RETRIES_PER_CHECKPOINT or total_retries >= MAX_TOTAL_RETRIES:
            resolved = result.ok
            _record(decisions, run_id, plan_id, story_type, "narration",
                    attempt, result, score_prev or score_now, score_now if attempt > 1 else None, resolved,
                    "No issues found." if result.ok else "Stopped — max retries or budget reached.")
            break
        # Hard stop: no improvement between attempt 1 and attempt 2
        if score_prev is not None and score_now <= score_prev:
            _record(decisions, run_id, plan_id, story_type, "narration",
                    attempt, result, score_prev, score_now, False,
                    "Stopped — score did not improve between retries.")
            notes.append("Narration: score did not improve after rewrite; review the brief and edit manually.")
            break
        # Rewrite with instruction
        _record(decisions, run_id, plan_id, story_type, "narration",
                attempt, result, score_now, None, False,
                f"Rewriting script: {result.instruction[:120]}")
        score_prev = score_now
        await planner.rewrite_script(short_id, result.instruction, backend, s, _sub(progress, "rewrite narration"))
        short = store.get(short_id)
        total_retries += 1

    # ── PHASE 2: VOICE + FIT ─────────────────────────────────────────────────
    progress(1, 5, "making the voice")
    short = store.get(short_id)
    if short.get("settings", {}).get("voice_mode") != "none" and svoice.missing(short):
        res = await svoice.make(short_id, progress=_sub(progress, "voice"), s=s, key=key)
        if res["failed"]:
            return {"decisions": decisions, "notes": notes, "stopped": f"Voice failed: {res['failed'][0]['error']}"}
        short = store.get(short_id)

    await planner.fit_shots(short_id, backend, s, _sub(progress, "fit shots"))
    short = planner.sync_timing(short_id)

    chk = checks.run(short)
    if not chk["ok"]:
        first = next(i for i in chk["issues"] if i["level"] == "block")
        return {"decisions": decisions, "notes": notes, "stopped": first["text"]}

    # ── PHASE 3: START PICTURES (keyframe pipeline only) ─────────────────────
    if P.keyframes_on(short):
        progress(2, 5, "making start pictures")
        if not all(clips.chosen_keyframe(short, sh) for sh in short["shots"]):
            res = await clips.make_keyframes(short_id, progress=_sub(progress, "keyframes"), s=s, key=key)
            if res["failed"]:
                return {"decisions": decisions, "notes": notes,
                        "stopped": f"Keyframe failed: {res['failed'][0]['error']}"}
            short = store.get(short_id)

        # Stills checkpoint
        examples = recent_examples(story_type, "stills")
        score_prev = None
        for attempt in range(1, MAX_RETRIES_PER_CHECKPOINT + 2):
            result = await evaluators.stills(short, backend, s, examples)
            score_now = result.score
            if result.ok or attempt > MAX_RETRIES_PER_CHECKPOINT or total_retries >= MAX_TOTAL_RETRIES:
                resolved = result.ok
                _record(decisions, run_id, plan_id, story_type, "stills",
                        attempt, result, score_prev or score_now, score_now if attempt > 1 else None, resolved,
                        "No issues found." if result.ok else "Stopped — max retries or budget reached.")
                break
            if score_prev is not None and score_now <= score_prev:
                _record(decisions, run_id, plan_id, story_type, "stills",
                        attempt, result, score_prev, score_now, False,
                        "Stopped — picture score did not improve between retries.")
                notes.append("Start pictures: score did not improve after rewrite; redo manually.")
                break
            # Rewrite weak still prompts then redraw those shots
            weak = result.weak_shots
            if not weak:
                # evaluator flagged issues but gave no specific shots — pass anyway
                _record(decisions, run_id, plan_id, story_type, "stills",
                        attempt, result, score_now, None, True, "Issues noted but no specific shots flagged.")
                break
            _record(decisions, run_id, plan_id, story_type, "stills",
                    attempt, result, score_now, None, False,
                    f"Rewriting still prompts for {', '.join(weak[:4])}.")
            score_prev = score_now
            for shot_id in weak:
                try:
                    sh = store.shot_by_id(short, shot_id)
                except store.ShortError:
                    continue
                beat = next(b for b in short["beats"] if b["id"] == sh["beat"])
                beat_shots = [x for sid in beat["shot_ids"] for x in short["shots"] if x["id"] == sid]
                from . import stillwriter, motionwriter
                written = await stillwriter.write_beat(short, beat, beat_shots, backend, s, only={shot_id}, note=result.instruction)
                if written:
                    await motionwriter.write_beat(short, beat, beat_shots, backend, s, only={shot_id})
            store.save(short)
            # Redraw the weak shots
            await clips.make_keyframes(short_id, shot_ids=weak, only_missing=False,
                                       progress=_sub(progress, "redrawing pictures"), s=s, key=key)
            short = store.get(short_id)
            total_retries += 1

        # Human review checkpoint — same as regular auto-run
        if short["settings"].get("review_keyframes", True) and not short.get("keyframes_confirmed"):
            return {"decisions": decisions, "notes": notes, "stopped": "review_keyframes",
                    "message": "Done so far. Look at the start pictures, redo or replace any you don't like, press 'Pictures are good', then press Agent Run again."}

    # ── PHASE 4: CLIPS + FINAL ───────────────────────────────────────────────
    progress(3, 5, "making clips")
    short = store.get(short_id)
    if not all(clips.chosen_clip(short, sh) for sh in short["shots"]):
        res = await clips.make_clips(short_id, progress=_sub(progress, "clips"), s=s, key=key)
        if res["failed"] or res["skipped"]:
            bad = (res["failed"] or res["skipped"])[0]
            return {"decisions": decisions, "notes": notes,
                    "stopped": f"Clip failed for shot {bad['shot']}: {bad['error']}"}

    if upscale.wanted(short) and upscale.missing(short):
        res = await upscale.make(short_id, progress=_sub(progress, "2K"), s=s, key=key)
        if res["failed"]:
            return {"decisions": decisions, "notes": notes,
                    "stopped": f"Upscale failed: {res['failed'][0]['error']}"}

    progress(4, 5, "putting the short together")
    await asyncio.to_thread(stitch.build, short_id, _sub(progress, "final"))

    # Final evaluation (report only — no retry)
    progress(5, 5, "final quality check")
    short = store.get(short_id)
    final_result = await evaluators.final(short, backend, s)
    decisions.append({
        "checkpoint": "final",
        "attempt": 1,
        "score_before": final_result.score,
        "score_after": None,
        "resolved": True,
        "problem": f"Predicted engagement score: {final_result.score}/10",
        "solution": "No automatic action — final report for human review.",
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
