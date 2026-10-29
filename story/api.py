"""HTTP API for the story module (mounted under /api). All routes sit behind the app login (auth.install)."""
import asyncio

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from . import db, eta, export, figures, guide, llm, pipeline, projects, review, settings as settings_mod, storytypes
from .pipeline import manager
from .tokens import Budget

router = APIRouter(prefix="/api")
MAX_UPLOAD = 200 * 1024 * 1024


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except (projects.ProjectError, review.ReviewError, settings_mod.SettingsError) as e:
        raise HTTPException(400, str(e))


def _project_or_404(pid: str) -> dict:
    try:
        return projects.get(pid)
    except projects.ProjectError:
        raise HTTPException(404, "project not found")


# ── settings / model ────────────────────────────────────────────────────────

@router.get("/settings")
async def get_settings():
    s = settings_mod.public()
    b = Budget.from_settings(s)
    s["derived"] = {
        "usable_tokens": b.usable, "input_limit": b.input_limit(),
        "effective_chunk_tokens": b.chunk_target(s["chunk_tokens"], 1500),
        "warnings": b.warnings(s["chunk_tokens"], 1500),
    }
    s["sampling_defaults"] = settings_mod.SAMPLING
    return s


@router.put("/settings")
async def put_settings(patch: dict):
    _guard(settings_mod.update, patch)
    return await get_settings()


@router.post("/llm/test")
async def llm_test():
    s = settings_mod.get()
    res = await llm.connection_test(s, settings_mod.api_key())
    if res.get("ok") and res.get("sampling_supported") is not None:
        _guard(settings_mod.update, {"sampling_probe": res["sampling_supported"]})              # remembered: top_p and the penalties are sent only when the server took them
    if res.get("ok") and "json_mode_supported" in res:
        res["note"] = ("JSON mode is supported; enable it in Settings if replies keep failing validation."
                       if res["json_mode_supported"] else "JSON mode is not supported; prompts alone enforce the format.")
    return res


# ── projects ────────────────────────────────────────────────────────────────

@router.get("/projects")
async def list_projects(q: str = "", status: str = "", format: str = "", sort: str = "created", desc: bool = True):
    return projects.list_projects(q, status, format, sort, desc)


@router.post("/projects/upload")
async def upload(file: UploadFile = File(...), title: str = Form(""), author: str = Form(""), story_type: str = Form("")):
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "file is larger than 200 MB")
    pid = await asyncio.to_thread(_guard, projects.import_file, file.filename or "upload", data, title, author)
    return _with_type(pid, story_type)


def _with_type(pid: str, story_type: str) -> dict:
    """An import that names a story type sets it on the new project; none named leaves the default (incident)."""
    return _guard(projects.set_story_type, pid, story_type) if story_type else projects.get(pid)


class UrlIn(BaseModel):
    url: str
    title: str = ""
    author: str = ""
    story_type: str = ""


@router.post("/projects/url")
async def from_url(body: UrlIn):
    try:
        pid = await projects.import_url(body.url, body.title, body.author)
    except projects.ProjectError as e:
        raise HTTPException(400, str(e))
    return _with_type(pid, body.story_type)


class TextIn(BaseModel):
    text: str
    title: str = ""
    author: str = ""
    story_type: str = ""


@router.post("/projects/text")
async def from_text(body: TextIn):
    pid = _guard(projects.import_text, body.text, body.title, body.author)
    return _with_type(pid, body.story_type)


@router.get("/projects/{pid}")
async def get_project(pid: str):
    p = _project_or_404(pid)
    p["running"] = manager.is_running(pid)
    p["chapters"] = projects.get_chapters(pid)
    return p


class MetaIn(BaseModel):
    title: str | None = None
    author: str | None = None


@router.patch("/projects/{pid}")
async def patch_project(pid: str, body: MetaIn):
    _project_or_404(pid)
    return _guard(projects.update_meta, pid, body.title, body.author)


class StoryTypeIn(BaseModel):
    story_type: str


@router.get("/story-types")
async def story_types():
    return {"types": storytypes.public(), "default": storytypes.DEFAULT}


@router.patch("/projects/{pid}/story-type")
async def patch_story_type(pid: str, body: StoryTypeIn):
    _project_or_404(pid)
    return _guard(projects.set_story_type, pid, body.story_type)


@router.delete("/projects/{pid}")
async def delete_project(pid: str):
    _project_or_404(pid)
    if manager.is_running(pid):
        manager.cancel(pid)
        await manager.wait(pid)
    projects.delete(pid)
    return {"ok": True}


@router.get("/projects/{pid}/original")
async def original(pid: str):
    _project_or_404(pid)
    p = _guard(projects.original_path, pid)
    return FileResponse(p, filename=p.name)


@router.get("/projects/{pid}/paras")
async def paras(pid: str, offset: int = 0, limit: int = 100, chapter: int | None = None, q: str = ""):
    _project_or_404(pid)
    return projects.get_paras(pid, offset, min(limit, 500), chapter, q)


class ParaIn(BaseModel):
    text: str


@router.put("/projects/{pid}/paras/{idx}")
async def edit_para(pid: str, idx: int, body: ParaIn):
    _project_or_404(pid)
    return _guard(projects.edit_para, pid, idx, body.text)


class ChaptersIn(BaseModel):
    chapters: list[dict]


@router.put("/projects/{pid}/chapters")
async def put_chapters(pid: str, body: ChaptersIn):
    _project_or_404(pid)
    if manager.is_running(pid):
        raise HTTPException(409, "pause processing before changing chapters")
    return _guard(projects.set_chapters, pid, body.chapters)


@router.get("/projects/{pid}/scope")
async def get_scope(pid: str):
    _project_or_404(pid)
    return _with_eta(pid, _guard(projects.scope_preview, pid))


def _with_eta(pid: str, prev: dict) -> dict:
    e = eta.estimate(pid)
    prev["eta_seconds"], prev["eta_low"], prev["eta_high"] = e["remaining"]["seconds"], e["remaining"]["low"], e["remaining"]["high"]
    prev["eta_confidence"], prev["eta_basis"] = e["confidence"], e["basis"]
    return prev


class ScopeIn(BaseModel):
    scope: dict
    reset: bool = False


@router.put("/projects/{pid}/scope")
async def put_scope(pid: str, body: ScopeIn):
    """Choose what to process: the whole source, selected chapters, a page range or a paragraph range."""
    _project_or_404(pid)
    if manager.is_running(pid):
        raise HTTPException(409, "pause or cancel processing before changing the scope")
    started = db.one("SELECT 1 x FROM tasks WHERE project_id=? AND stage='analyze' LIMIT 1", (pid,))
    if started and not body.reset:
        raise HTTPException(409, "this source was already processed; changing the scope means reprocessing from the "
                                 "start (stories you reviewed or edited are kept). Confirm to continue.")
    old = projects.get_scope(pid)
    prev = _guard(projects.set_scope, pid, body.scope)
    if started:
        pipeline.reset(pid, stage="analyze")
    prev["reset"] = bool(started)
    prev["previous"] = old
    return _with_eta(pid, prev)


@router.get("/projects/{pid}/analysis")
async def analysis(pid: str):
    """Intermediate structure: source index and chapter records."""
    _project_or_404(pid)
    idx = pipeline.done_results(pid, "index")
    recs = sorted(pipeline.done_results(pid, "rollup"), key=lambda r: r["idx"])
    return {"index": idx[0] if idx else None,
            "chapters": [{"idx": r["idx"], "title": r["title"], "summary": r["summary"], "themes": r["themes"],
                          "threads": r["threads"], "events": len(r["events"]), "facts": len(r["facts"]),
                          "entities": r["entities"][:15], "open_questions": r["open_questions"][:10]} for r in recs]}


@router.get("/projects/{pid}/figures")
async def list_figures(pid: str):
    _project_or_404(pid)
    return figures.list_figures(pid)


@router.get("/projects/{pid}/figures/{fid}/image")
async def figure_image(pid: str, fid: str):
    _project_or_404(pid)
    p = figures.image_path(pid, fid)
    if not p:
        raise HTTPException(404, "figure not found")
    return FileResponse(p, media_type="image/jpeg")


# ── processing control ──────────────────────────────────────────────────────

@router.get("/projects/{pid}/progress")
async def progress(pid: str):
    _project_or_404(pid)
    p = pipeline.progress(pid)
    p["running"] = manager.is_running(pid)
    p.update(guide.live(pid))
    p["next"] = guide.next_step(pid)
    p["steps"] = [{"key": k, "label": l} for k, l in guide.STEPS]
    p["step_index"] = guide.step_index(p["next"])
    return p


@router.get("/performance")
async def performance():
    """Speed history the estimates are learned from."""
    return eta.performance()


class ProcessIn(BaseModel):
    retry_failed: bool = False
    from_stage: str | None = None


@router.post("/projects/{pid}/process")
async def process(pid: str, body: ProcessIn | None = None):
    _project_or_404(pid)
    body = body or ProcessIn()
    if manager.is_running(pid):
        raise HTTPException(409, "already processing")
    if body.from_stage:
        _guard_stage(body.from_stage)
        pipeline.reset(pid, stage=body.from_stage)
    elif body.retry_failed:
        pipeline.reset(pid, failed_only=True)
    manager.start(pid)
    return {"started": True}


def _guard_stage(stage: str) -> None:
    if stage not in pipeline.STAGES:
        raise HTTPException(400, f"stage must be one of {', '.join(pipeline.STAGES)}")


@router.post("/projects/{pid}/pause")
async def pause(pid: str):
    _project_or_404(pid)
    return {"ok": manager.pause(pid)}


@router.post("/projects/{pid}/cancel")
async def cancel(pid: str):
    _project_or_404(pid)
    ok = manager.cancel(pid)
    return {"ok": ok}


@router.post("/projects/{pid}/tasks/{task_id}/retry")
async def retry_task(pid: str, task_id: int):
    _project_or_404(pid)
    if manager.is_running(pid):
        raise HTTPException(409, "pause processing first")
    pipeline.reset(pid, task_id=task_id)
    return {"ok": True}


@router.get("/projects/{pid}/tasks/{task_id}")
async def task_detail(pid: str, task_id: int):
    r = db.one("SELECT id,stage,key,status,attempts,error,raw_failed,tokens_in,tokens_out,duration_ms FROM tasks WHERE id=? AND project_id=?", (task_id, pid))
    if not r:
        raise HTTPException(404, "task not found")
    r["raw_failed"] = db.jload(r["raw_failed"], [])
    return r


class ExpandIn(BaseModel):
    count: int = 10


@router.post("/projects/{pid}/expand")
async def expand(pid: str, body: ExpandIn):
    _project_or_404(pid)
    if manager.is_running(pid):
        raise HTTPException(409, "already processing")
    n = pipeline.expand_leads(pid, max(1, min(body.count, 100)))
    if n:
        manager.start(pid)
    return {"queued": n}


@router.post("/projects/{pid}/rescore")
async def rescore(pid: str):
    _project_or_404(pid)
    s = settings_mod.get()
    return {"rescored": review.rescore_project(pid, s["weights"], s["evidence_influence"], s["completeness_influence"])}


# ── stories ─────────────────────────────────────────────────────────────────

@router.get("/projects/{pid}/stories")
async def stories(pid: str, status: str = "", q: str = "", min_priority: float | None = None,
                  research: bool | None = None, kind: str = "", sort: str = "priority", desc: bool = True,
                  nature: str = ""):
    _project_or_404(pid)
    return review.list_candidates(pid, status, q, min_priority, research, kind, sort, desc, nature=nature)


@router.get("/stories/{cid}")
async def story(cid: str):
    try:
        return review.get_candidate(cid)
    except review.ReviewError:
        raise HTTPException(404, "story not found")


@router.patch("/stories/{cid}")
async def patch_story(cid: str, patch: dict):
    return _guard(review.update_candidate, cid, patch)


class MergeIn(BaseModel):
    ids: list[str]
    title: str = ""
    premise: str = ""


@router.get("/projects/{pid}/merge-suggestions")
async def merge_suggestions(pid: str):
    """Pending stories that are mostly the same passages, with the title of the strongest: the review screen offers to merge them into one richer story."""
    return {"suggestions": _guard(review.merge_suggestions, pid)}


@router.post("/stories/merge")
async def merge(body: MergeIn):
    return _guard(review.merge, body.ids, body.title, body.premise)


class SplitIn(BaseModel):
    groups: list[dict]


@router.post("/stories/{cid}/split")
async def split(cid: str, body: SplitIn):
    return _guard(review.split, cid, body.groups)


# ── export ──────────────────────────────────────────────────────────────────

@router.get("/projects/{pid}/export")
async def export_project(pid: str, format: str = "json", statuses: str = "approved,pending", text: bool = True):
    _project_or_404(pid)
    wanted = [s for s in statuses.split(",") if s in ("approved", "pending", "rejected")]
    if statuses == "all":
        wanted = ["approved", "pending", "rejected"]
    if not wanted:
        raise HTTPException(400, "statuses must include approved, pending and/or rejected")
    doc = export.build(pid, wanted, include_text=text)
    name = f"stories-{pid}"
    if format == "csv":
        return Response(export.to_csv(doc), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})
    return Response(export.to_json(doc), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}.json"'})
