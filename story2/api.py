"""HTTP API for Phase 2 (mounted under /api/plans). Same login as the rest of the app.
Model steps run as background jobs (start, then poll /api/plans/{id}/job); everything else is immediate."""
import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from story import db, llm, settings as settings_mod
from story.pipeline import manager
from . import intake, jobs, planner, storyboard

router = APIRouter(prefix="/api/plans")


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except (planner.PlanError, intake.IntakeError) as e:
        raise HTTPException(400, str(e))


def _start(plan_id: str, kind: str, step):
    """step(backend, settings, progress) -> awaitable."""
    _guard(planner.get_plan, plan_id)
    if manager.busy():
        raise HTTPException(409, "story processing is running; wait for it to finish (the model serves one request at a time)")

    async def work(progress):
        s = settings_mod.get()
        await step(llm.ChatBackend(s, settings_mod.api_key()), s, progress)

    try:
        return jobs.start(plan_id, kind, work)
    except jobs.JobBusy as e:
        raise HTTPException(409, str(e))


class NewPlan(BaseModel):
    candidate_id: str
    narrator_name: str = ""
    minutes: float = planner.DEFAULT_MINUTES
    allow_unapproved: bool = False


@router.get("")
async def plans(candidate_id: str = "", project_id: str = ""):
    return planner.list_plans(candidate_id, project_id)


@router.post("")
async def new_plan(body: NewPlan):
    return _guard(planner.create_plan, body.candidate_id, body.narrator_name, body.minutes, body.allow_unapproved)


@router.get("/{plan_id}")
async def plan(plan_id: str):
    p = _guard(planner.get_plan, plan_id)
    p["job"] = jobs.status(plan_id)
    return p


@router.delete("/{plan_id}")
async def delete_plan(plan_id: str):
    _guard(planner.get_plan, plan_id)
    if jobs.busy():
        raise HTTPException(409, "a planning job is running")
    for t in ("scenes", "segments", "assets", "plan_revisions"):
        db.ex(f"DELETE FROM {t} WHERE plan_id=?", (plan_id,))
    db.ex("DELETE FROM plans WHERE id=?", (plan_id,))
    return {"ok": True}


@router.get("/{plan_id}/job")
async def job(plan_id: str):
    return jobs.status(plan_id)


@router.post("/{plan_id}/cancel")
async def cancel(plan_id: str):
    return {"ok": jobs.cancel(plan_id)}


class Narrator(BaseModel):
    name: str | None = None
    voice: str | None = None
    gender: str | None = None


class Settings(BaseModel):
    minutes: float | None = None


@router.patch("/{plan_id}/narrator")
async def narrator(plan_id: str, body: Narrator):
    return _guard(planner.set_narrator, plan_id, body.name, **{k: v for k, v in body.model_dump().items() if k != "name" and v})


@router.patch("/{plan_id}/settings")
async def plan_settings(plan_id: str, body: Settings):
    p = _guard(planner.get_plan, plan_id)
    st = {**p["settings"], **({"minutes": body.minutes} if body.minutes else {})}
    db.ex("UPDATE plans SET settings=?, updated_at=? WHERE id=?", (db.jdump(st), db.now(), plan_id))
    return _guard(planner.get_plan, plan_id)


@router.post("/{plan_id}/blueprint")
async def blueprint(plan_id: str):
    async def step(be, s, progress):
        progress(0, 1, "planning the story")
        await planner.make_blueprint(plan_id, be, s)
        progress(1, 1, "done")
    return _start(plan_id, "blueprint", step)


class NarrationReq(BaseModel):
    beat_ids: list[str] | None = None
    only_missing: bool = False


@router.post("/{plan_id}/narration")
async def narration(plan_id: str, body: NarrationReq | None = None):
    body = body or NarrationReq()
    p = _guard(planner.get_plan, plan_id)
    if not p["blueprint"]:
        raise HTTPException(400, "make the blueprint first")

    async def step(be, s, progress):
        await planner.make_narration(plan_id, be, s, body.beat_ids, progress, body.only_missing)
    return _start(plan_id, "narration", step)


@router.post("/{plan_id}/fix-repeats")
async def fix_repeats(plan_id: str):
    async def step(be, s, progress):
        await storyboard.fix_repeats(plan_id, be, s, progress)
    return _start(plan_id, "fix repeats", step)


@router.post("/{plan_id}/registry")
async def registry(plan_id: str):
    async def step(be, s, progress):
        progress(0, 1, "listing recurring people, places and style")
        await storyboard.make_registry(plan_id, be, s)
        progress(1, 1, "done")
    return _start(plan_id, "registry", step)


class StoryboardReq(BaseModel):
    segment_ids: list[str] | None = None


@router.post("/{plan_id}/storyboard")
async def make_storyboard(plan_id: str, body: StoryboardReq | None = None):
    p = _guard(planner.get_plan, plan_id)
    if not p["segments"]:
        raise HTTPException(400, "write the narration first")

    async def step(be, s, progress):
        await storyboard.make_storyboard(plan_id, be, s, body.segment_ids if body else None, progress)
    return _start(plan_id, "storyboard", step)


class SegmentPatch(BaseModel):
    text: str | None = None
    sentences: list[dict] | None = None
    status: str | None = None
    locked: bool | None = None
    emphasis: list[str] | None = None
    pronounce: list[dict] | None = None


@router.patch("/segments/{seg_id}")
async def patch_segment(seg_id: str, body: SegmentPatch):
    f = {k: v for k, v in body.model_dump().items() if k not in ("text", "sentences") and v is not None}
    return _guard(planner.edit_segment, seg_id, body.sentences, body.text, **f)


class Move(BaseModel):
    direction: int


@router.post("/segments/{seg_id}/move")
async def move_segment(seg_id: str, body: Move):
    return _guard(storyboard.move_segment, seg_id, body.direction)


@router.patch("/scenes/{scene_id}")
async def patch_scene(scene_id: str, patch: dict):
    return _guard(storyboard.edit_scene, scene_id, patch)


class Regen(BaseModel):
    note: str = ""


@router.post("/scenes/{scene_id}/regenerate")
async def regenerate_scene(scene_id: str, body: Regen | None = None):
    sc = _guard(storyboard.get_scene, scene_id)

    async def step(be, s, progress):
        progress(0, 1, "redrawing one scene")
        await storyboard.regenerate_scene(scene_id, be, s, body.note if body else "")
        progress(1, 1, "done")
    return _start(sc["plan_id"], "scene", step)


@router.patch("/assets/{asset_id}")
async def patch_asset(asset_id: str, patch: dict):
    a = db.one("SELECT * FROM assets WHERE id=?", (asset_id,))
    if not a:
        raise HTTPException(404, "asset not found")
    data = db.jload(a["data"], {})
    for k in ("description", "fixed", "flexible", "period", "fictionalisation", "evidence_note"):
        if k in patch:
            data[k] = patch[k]
    locked = a["locked"] if "locked" not in patch else (1 if patch["locked"] else 0)
    db.ex("UPDATE assets SET data=?, locked=?, rev=rev+1, updated_at=? WHERE id=?", (db.jdump(data), locked, db.now(), asset_id))
    return planner.get_plan(a["plan_id"])


@router.post("/{plan_id}/validate")
async def validate(plan_id: str):
    def both():
        n = planner.validate_plan(plan_id)
        b = storyboard.validate_storyboard(plan_id)
        return {"narration": n, "storyboard": b, "ok": n["ok"] and b["ok"]}
    return await asyncio.to_thread(_guard, both)
