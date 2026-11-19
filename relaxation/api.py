"""FastAPI router for the relaxation channel (/api/relaxation)."""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from story import settings as settings_mod
from story2 import jobs
from story.pipeline import manager
from story3 import store as media
from story3.voice import MediaError

from . import auto, models as M, publish, store

router = APIRouter(prefix="/api/relaxation", tags=["relaxation"])


def _get(session_id: str) -> dict:
    try:
        return store.get(session_id)
    except store.SessionError as e:
        raise HTTPException(404, str(e))


def _start(session_id: str, work) -> dict:
    _get(session_id)
    if manager.busy():
        raise HTTPException(409, "story processing is running; wait for it to finish")
    try:
        return jobs.start(session_id, "relaxation", work)
    except jobs.JobBusy as e:
        raise HTTPException(409, str(e))


# ── list / create ─────────────────────────────────────────────────────────────

@router.get("")
async def list_sessions():
    return {"sessions": [store.view(s) for s in store.list_all()]}


class _CreateReq(BaseModel):
    scene: str = M.DEFAULT_SCENE
    hours: int = M.LOOP_HOURS
    minutes: int | None = None      # a short test run; wins over hours


@router.post("")
async def create_session(body: _CreateReq):
    if body.scene not in M.SCENES:
        raise HTTPException(400, f"unknown scene '{body.scene}'; choose from {list(M.SCENES)}")
    if not (1 <= body.hours <= 8):
        raise HTTPException(400, "hours must be 1 to 8")
    if body.minutes is not None and not (1 <= body.minutes <= 480):
        raise HTTPException(400, "minutes must be 1 to 480")
    s = store.create(scene=body.scene, hours=body.hours, minutes=body.minutes)
    return store.view(s)


# ── get / delete ──────────────────────────────────────────────────────────────

@router.get("/{session_id}")
async def get_session(session_id: str):
    return store.view(_get(session_id))


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    _get(session_id)
    store.delete(session_id)
    return {"ok": True}


# ── run ───────────────────────────────────────────────────────────────────────

@router.post("/{session_id}/run")
async def run_session(session_id: str, force: bool = False):
    """Start or resume the full generation pipeline."""
    async def work(progress):
        return await auto.run(session_id, force=force, progress=progress)
    return _start(session_id, work)


@router.get("/{session_id}/run")
async def run_status(session_id: str):
    return jobs.status(session_id)


# ── publish metadata ──────────────────────────────────────────────────────────

@router.post("/{session_id}/publish")
async def gen_publish(session_id: str, force: bool = False):
    """(Re-)generate YouTube title, description and tags."""
    _get(session_id)
    s = settings_mod.get()
    if manager.busy():
        raise HTTPException(409, "a job is running; wait")
    try:
        return await publish.generate(session_id, s, force=force)
    except MediaError as e:
        raise HTTPException(400, str(e))


# ── download ──────────────────────────────────────────────────────────────────

@router.get("/{session_id}/download")
async def download_video(session_id: str):
    """Stream the final MP4 file."""
    item = store.chosen(session_id, M.KIND_FINAL)
    if not item:
        raise HTTPException(404, "final video not ready")
    path = media.path_of(item)
    if not path.is_file():
        raise HTTPException(404, "file missing on disk")
    return FileResponse(path, media_type="video/mp4",
                        filename=f"{session_id}-{M.duration_label(_get(session_id).get('settings') or {}).replace(' ', '')}.mp4")


# ── options ───────────────────────────────────────────────────────────────────

@router.get("/options/scenes")
async def scenes():
    return {"scenes": {k: {"label": v["label"]} for k, v in M.SCENES.items()}}
