"""/api/feedback: how the channel's results steer the idea factory. Reading and regrading are instant; the model steps run as the one background ideas job (the gateway serves one request at a time)."""
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from story import llm, settings as settings_mod

from . import generate, insights, outcomes, playbook, store

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


def _pb_view(pb: dict) -> dict:
    return {"id": pb["id"], "version": pb["version"], "status": pb["status"], "created_at": pb["created_at"], "decided_at": pb["decided_at"], "data": pb["data"]}


def _state() -> dict:
    from shorts import ideas as ideas_mod
    cfg = ideas_mod.get_config()
    pbs = store.playbooks()
    approved = next((p for p in pbs if p["status"] == "approved"), None)
    return {"use_playbook": cfg["use_playbook"], "explore": cfg["explore"], "auto_feedback": cfg["auto_feedback"], "playbook_min_new": cfg["playbook_min_new"], "tone_arms": cfg["tone_arms"],
            "active_version": approved["version"] if approved and cfg["use_playbook"] else 0, "min_graded": playbook.MIN_GRADED, "last_cycle": store.kv("last_cycle", None),
            "approve_min": cfg["approve_min"], "min_score": cfg["min_score"]}


@router.get("/overview")
async def overview():
    o = insights.overview()
    base = outcomes.baseline()
    return {**o, "baseline": base, "state": _state(), "playbooks": [_pb_view(p) for p in store.playbooks()], "pins": store.pins(),
            "ideas_by_origin": _origins()}


def _origins() -> dict:
    from shorts import ideas as ideas_mod
    out: dict[str, int] = {}
    for i in ideas_mod.listing():
        k = (i.get("origin") or "generated").split(":")[0]
        out[k] = out.get(k, 0) + 1
    return out


class LearnFrom(BaseModel):
    date: str   # YYYY-MM-DD, India time


@router.post("/learn-from")
async def set_learn_from(body: LearnFrom):
    """Change the first day the loop learns from (default 1 Nov 2026). Videos published before it are ignored everywhere."""
    try:
        d = datetime.strptime(body.date.strip(), "%Y-%m-%d").replace(tzinfo=outcomes.IST)
    except ValueError:
        raise HTTPException(400, "date must look like 2026-11-01")
    store.set_kv("learn_from", d.timestamp())
    return {"result": outcomes.refresh(), **await overview()}


@router.post("/refresh")
async def refresh():
    """Regrade every video from the numbers already pulled. No model call."""
    return {"result": outcomes.refresh(), **await overview()}


def _job(kind: str, make):
    from shorts import api as shorts_api
    s, key = settings_mod.get(), settings_mod.api_key()

    async def work(progress):
        return await make(llm.ChatBackend(s, key), s, key, progress)

    return shorts_api._start_idea_job(kind, work)


@router.post("/tag")
async def tag():
    async def make(backend, s, key, progress):
        progress(0, 1, "tagging subjects")
        r = await generate.tag_missing(backend, s)
        outcomes.refresh()
        return f"tagged {r['ideas']} ideas, {r['videos']} videos"
    return _job("tag", make)


@router.post("/playbook/draft")
async def playbook_draft():
    if len(outcomes.graded_rows()) < playbook.MIN_GRADED:
        raise HTTPException(400, f"only {len(outcomes.graded_rows())} graded videos so far; a Playbook needs at least {playbook.MIN_GRADED}")

    async def make(backend, s, key, progress):
        progress(0, 1, "writing the Playbook")
        pb = await playbook.draft(backend, s)
        return f"Playbook v{pb['version']} drafted: review it on the YouTube page"
    return _job("playbook", make)


async def _dedup_rate(ids, s, key, progress) -> str:
    from shorts import ideas as ideas_mod
    if not ids:
        return "no new ideas"
    progress(0, 1, f"checking {len(ids)} new ideas")
    rejected = set(await ideas_mod.dedup(ids, s, key))
    kept = [i for i in ids if i not in rejected]
    if kept:
        await ideas_mod.rate(kept, s, key)
    return f"{len(ids)} new ideas, {len(kept)} kept"


@router.post("/sequels")
async def sequels():
    async def make(backend, s, key, progress):
        progress(0, 1, "writing sequels of winners")
        return await _dedup_rate(await generate.sequels(backend, s), s, key, progress)
    return _job("sequels", make)


@router.post("/comments/ideas")
async def comment_ideas():
    async def make(backend, s, key, progress):
        progress(0, 1, "reading comments")
        return await _dedup_rate(await generate.comment_ideas(backend, s), s, key, progress)
    return _job("comments", make)


@router.post("/cycle")
async def cycle():
    from shorts import ideas as ideas_mod

    async def make(backend, s, key, progress):
        return await generate.run_cycle(s, key, progress, ideas_mod.get_config())
    return _job("feedback", make)


@router.post("/playbooks/{pid}/approve")
async def approve(pid: int):
    pb = store.playbook(pid)
    if not pb:
        raise HTTPException(404, "no such Playbook")
    if pb["status"] == "approved":
        return _pb_view(pb)
    return _pb_view(store.set_playbook_status(pid, "approved"))


@router.post("/playbooks/{pid}/reject")
async def reject(pid: int):
    pb = store.playbook(pid)
    if not pb:
        raise HTTPException(404, "no such Playbook")
    return _pb_view(store.set_playbook_status(pid, "rejected"))


class _Key(BaseModel):
    key: str


@router.post("/playbooks/{pid}/toggle")
async def toggle(pid: int, body: _Key):
    try:
        return _pb_view(playbook.toggle_item(pid, body.key))
    except ValueError as e:
        raise HTTPException(404, str(e))


class _Pin(BaseModel):
    text: str


@router.post("/pins")
async def add_pin(body: _Pin):
    if not body.text.strip():
        raise HTTPException(400, "write the principle")
    store.add_pin(body.text)
    return {"pins": store.pins()}


@router.delete("/pins/{pin_id}")
async def del_pin(pin_id: int):
    store.remove_pin(pin_id)
    return {"pins": store.pins()}


class _Apply(BaseModel):
    threshold: float


@router.post("/calibration/apply")
async def apply_threshold(body: _Apply):
    """Set the approve and make thresholds to the advised score line (the owner pressed the button)."""
    from shorts import ideas as ideas_mod
    t = max(0.0, min(10.0, body.threshold))
    ideas_mod.save_config({"approve_min": t, "min_score": t})
    return _state()
