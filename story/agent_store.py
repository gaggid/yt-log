"""Persistent log of agentic auto-run decisions.

Each entry is one checkpoint attempt (narration, stills, storyboard, final).
The three fields shown in the UI timeline are: problem, solution, outcome.
`instruction_used` and scores are stored for learning but not displayed.
`story_type` + `checkpoint` index supports retrieving few-shot examples."""
import hashlib
import time

from . import db

MAX_EXAMPLES = 3        # examples fed back into evaluator prompts
PASS_SCORE = 7          # score >= this is a pass


def save_decision(
    plan_id: str,
    run_id: str,
    story_type: str,
    checkpoint: str,
    attempt: int,
    score_before: int,
    score_after: int | None,
    resolved: bool,
    problem: str,
    solution: str,
    outcome: str,
    instruction_used: str = "",
) -> str:
    did = hashlib.sha1(f"{plan_id}{run_id}{checkpoint}{attempt}{time.time()}".encode()).hexdigest()[:12]
    db.ex(
        "INSERT OR REPLACE INTO agent_decisions"
        "(id,plan_id,run_id,story_type,checkpoint,attempt,score_before,score_after,"
        "resolved,problem,solution,outcome,instruction_used,created_at)"
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (did, plan_id, run_id, story_type or "", checkpoint, attempt,
         score_before, score_after, int(resolved),
         problem, solution, outcome, instruction_used, db.now()),
    )
    return did


def recent_examples(story_type: str, checkpoint: str) -> list[dict]:
    """Past resolved decisions for the same story_type + checkpoint, newest first, capped at MAX_EXAMPLES.
    Used as few-shot examples in evaluator prompts so the agent learns from past corrections."""
    rows = db.q(
        "SELECT problem, solution, outcome, instruction_used, score_before, score_after "
        "FROM agent_decisions "
        "WHERE story_type=? AND checkpoint=? AND resolved=1 "
        "ORDER BY created_at DESC LIMIT ?",
        (story_type or "", checkpoint, MAX_EXAMPLES),
    )
    return rows


def for_plan(plan_id: str) -> list[dict]:
    """All decisions for one plan, oldest first — for the UI timeline."""
    return db.q(
        "SELECT run_id, checkpoint, attempt, score_before, score_after, resolved, "
        "problem, solution, outcome, created_at "
        "FROM agent_decisions WHERE plan_id=? ORDER BY created_at ASC",
        (plan_id,),
    )


def runs_for_plan(plan_id: str) -> list[str]:
    """Distinct run_ids for a plan, newest first."""
    rows = db.q(
        "SELECT DISTINCT run_id FROM agent_decisions WHERE plan_id=? ORDER BY created_at DESC",
        (plan_id,),
    )
    return [r["run_id"] for r in rows]
