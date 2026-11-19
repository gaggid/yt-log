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

from . import audio, auto, daily, models as M, publish, store

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
    scene: str = ""                 # empty: the next theme in the rotation (relaxation/variety.py)
    hours: int = M.LOOP_HOURS
    minutes: int | None = None      # a short test run; wins over hours


@router.post("")
async def create_session(body: _CreateReq):
    if body.scene and body.scene not in M.SCENES:
        raise HTTPException(400, f"unknown scene '{body.scene}'; choose from {list(M.SCENES)}")
    if not (1 <= body.hours <= 8):
        raise HTTPException(400, "hours must be 1 to 8")
    if body.minutes is not None and not (1 <= body.minutes <= 480):
        raise HTTPException(400, "minutes must be 1 to 480")
    s = store.create(scene=body.scene, hours=body.hours, minutes=body.minutes)
    return store.view(s)


# ── the daily run (registered before /{session_id}) ───────────────────────────

def _daily_view() -> dict:
    cfg = daily.get_config()
    return {**cfg, "window_h": daily.WINDOW_H, "today": daily.today(), "done_today": cfg["last_date"] == daily.today()}


@router.get("/daily")
async def daily_get():
    return _daily_view()


class _DailyReq(BaseModel):
    enabled: bool | None = None
    hour: int | None = None
    minutes: int | None = None


@router.put("/daily")
async def daily_put(body: _DailyReq):
    daily.save_config({k: v for k, v in body.model_dump().items() if v is not None})
    return _daily_view()


@router.post("/daily/run-now")
async def daily_run_now(minutes: int | None = None):
    """Make a new session the way the daily run does (new theme, instrument and seed) and start it now."""
    if manager.busy():
        raise HTTPException(409, "story processing is running; wait for it to finish")
    try:
        s = daily.start_session(minutes or daily.get_config()["minutes"])
    except jobs.JobBusy as e:
        raise HTTPException(409, str(e))
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


class _MusicReq(BaseModel):
    instrument: str = ""            # "" same instrument, "other" another one of the theme's, or a name


@router.post("/{session_id}/music/regenerate")
async def regenerate_music(session_id: str, body: _MusicReq):
    """Make the music again with a new seed and put it into the finished video (the picture is copied, not re-encoded)."""
    s = _get(session_id)
    if body.instrument and body.instrument != "other" and body.instrument not in (M.SCENES.get((s.get("settings") or {}).get("scene")) or {}).get("instruments", []):
        raise HTTPException(400, "that instrument is not one of this theme's")

    async def work(progress):
        return await audio.regenerate_music(session_id, instrument=body.instrument, progress=progress)
    return _start(session_id, work)


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
