"""HTTP API for Phase 3 media (mounted under /api/media). Same login as the rest of the app; generation runs as the same one-at-a-time background
jobs as Phase 2 (the model server answers one request at a time)."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from story import llm, settings as settings_mod
from story.pipeline import manager
from story2 import jobs, planner

from . import store, voice

router = APIRouter(prefix="/api/media")


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except (planner.PlanError, voice.MediaError) as e:
        raise HTTPException(400, str(e))


def _start(plan_id: str, kind: str, work):
    _guard(planner.get_plan, plan_id)
    if manager.busy():
        raise HTTPException(409, "story processing is running; wait for it to finish (the model server answers one request at a time)")
    try:
        return jobs.start(plan_id, kind, work)
    except jobs.JobBusy as e:
        raise HTTPException(409, str(e))


@router.get("/file/{plan_id}/{name:path}")
async def media_file(plan_id: str, name: str):
    root = store.media_dir(plan_id).resolve()
    f = (root / name).resolve()
    if root not in f.parents or not f.is_file():
        raise HTTPException(404, "file not found")
    return FileResponse(f)


@router.get("/{plan_id}")
async def media_state(plan_id: str):
    _guard(planner.get_plan, plan_id)
    return {"voice": voice.state(plan_id)}


class VoiceReq(BaseModel):
    segment_ids: list[str] | None = None
    only_missing: bool = True


@router.post("/{plan_id}/voice")
async def make_voice(plan_id: str, body: VoiceReq | None = None):
    body = body or VoiceReq()
    _guard(voice.load_export, plan_id)                                 # refuse early, with the reason, instead of failing inside the job

    async def work(progress):
        await voice.generate(plan_id, body.segment_ids, body.only_missing, progress, settings_mod.get(), settings_mod.api_key())
    return _start(plan_id, "voice", work)


class ItemPatch(BaseModel):
    approved: bool | None = None


@router.patch("/item/{item_id}")
async def patch_item(item_id: str, body: ItemPatch):
    it = store.get(item_id)
    if not it:
        raise HTTPException(404, "item not found")
    if body.approved is not None:
        if body.approved and it["status"] != "done":
            raise HTTPException(400, "only a finished file can be approved")
        store.approve(item_id, body.approved)
        if it["kind"] == "voice":
            voice.apply_timing(it["plan_id"])
    return {"item": store.get(item_id), "voice": voice.state(it["plan_id"]) if it["kind"] == "voice" else None}
