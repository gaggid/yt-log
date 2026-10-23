"""HTTP API for Phase 2 (mounted under /api/plans). Same login as the rest of the app.
Model steps run as background jobs (start, then poll /api/plans/{id}/job); everything else is immediate."""
import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from story import db, llm, settings as settings_mod
from story.pipeline import manager
from fastapi.responses import FileResponse

from . import editorial, export, imgplan, imgprompts, intake, jobs, planner, providers, storyboard

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


@router.get("/providers")
async def image_providers():
    return {"providers": [providers.public(m) for m in providers.IMAGE_MODELS], "source": providers.CONFIG_SOURCE, "default": providers.DEFAULT_MODEL}


@router.get("/providers/probe")
async def probe_providers():
    return await asyncio.to_thread(providers.probe, settings_mod.get(), settings_mod.api_key())


@router.get("/schema")
async def plan_schema():
    from .export_schema import SCHEMA
    return SCHEMA


@router.get("/exports/{plan_id}/{name}")
async def export_file(plan_id: str, name: str):
    f = export.export_dir(plan_id) / name
    if "/" in name or "\\" in name or ".." in name or not f.is_file():
        raise HTTPException(404, "export not found")
    return FileResponse(f, media_type="application/json", filename=name)


@router.get("/previews/{plan_id}/{name}")
async def preview_file(plan_id: str, name: str):
    f = imgplan.preview_dir(plan_id) / name
    if "/" in name or "\\" in name or ".." in name or not f.is_file():
        raise HTTPException(404, "preview not found")
    return FileResponse(f)


@router.get("/{plan_id}")
async def plan(plan_id: str):
    p = _guard(planner.get_plan, plan_id)
    p["job"] = jobs.status(plan_id)
    p["approval"] = editorial.approval_state(p)
    p["content_hash"] = editorial.content_hash(p)
    p["exports"] = export.list_exports(plan_id)
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
    if "reference_images" in patch:                                  # approved images later scenes can be conditioned on (the gateway takes up to 3)
        data["reference_images"] = [{"id": str(r.get("id") or "")[:60], "file": str(r.get("file") or "")[:200], "approved": bool(r.get("approved")),
                                     "note": str(r.get("note") or "")[:200]} for r in (patch["reference_images"] or []) if r.get("id")]
    locked = a["locked"] if "locked" not in patch else (1 if patch["locked"] else 0)
    db.ex("UPDATE assets SET data=?, locked=?, rev=rev+1, updated_at=? WHERE id=?", (db.jdump(data), locked, db.now(), asset_id))
    return planner.get_plan(a["plan_id"])


@router.post("/{plan_id}/review")
async def review_plan(plan_id: str):
    """Run every automatic check, score the twelve dimensions, and say what stands between the plan and approval."""
    return await asyncio.to_thread(_guard, editorial.signoff, plan_id)


class Approve(BaseModel):
    note: str = ""


@router.post("/{plan_id}/approve")
async def approve_plan(plan_id: str, body: Approve | None = None):
    return await asyncio.to_thread(_guard, editorial.approve, plan_id, (body.note if body else ""))


@router.post("/{plan_id}/unapprove")
async def unapprove_plan(plan_id: str):
    return _guard(editorial.unapprove, plan_id)


@router.get("/{plan_id}/history")
async def plan_history(plan_id: str):
    _guard(planner.get_plan, plan_id)
    return editorial.history(plan_id)


@router.post("/{plan_id}/export")
async def export_plan(plan_id: str):
    def go():
        try:
            return export.save(plan_id)
        except export.ExportError as e:
            raise HTTPException(400, str(e))
    return await asyncio.to_thread(_guard, go)


class ImageModels(BaseModel):
    default: str | None = None
    by_type: dict | None = None
    previews_enabled: bool | None = None
    licence_checks: dict | None = None


@router.patch("/{plan_id}/image-models")
async def image_models(plan_id: str, body: ImageModels):
    try:
        return _guard(imgplan.set_image_models, plan_id, {k: v for k, v in body.model_dump().items() if v is not None})
    except providers.ProviderError as e:
        raise HTTPException(400, str(e))


@router.post("/{plan_id}/compile-prompts")
async def compile_prompts(plan_id: str):
    return await asyncio.to_thread(_guard, imgplan.compile_plan, plan_id)


@router.get("/scenes/{scene_id}/prompts")
async def scene_prompts(scene_id: str):
    sc = _guard(storyboard.get_scene, scene_id)
    plan = _guard(planner.get_plan, sc["plan_id"])
    prompts = sc["data"].get("prompts") or {}
    rep = (plan["validation"] or {}).get("prompts") or {}
    return {"prompts": prompts, "model": providers.model_for(sc["data"], plan["settings"]),
            "comparison": imgprompts.comparison(sc, storyboard.get_assets(sc["plan_id"]), prompts) if prompts else None,
            "issues": [i for i in rep.get("issues", []) if i.get("where") == scene_id], "previews": sc["data"].get("previews", []),
            "previews_enabled": providers.settings_for(plan["settings"])["previews_enabled"]}


class PreviewReq(BaseModel):
    adapter: str = "qwen"
    seed: int | None = None


@router.post("/scenes/{scene_id}/preview")
async def scene_preview(scene_id: str, body: PreviewReq):
    sc = _guard(storyboard.get_scene, scene_id)
    if body.adapter not in imgprompts.ADAPTERS:
        raise HTTPException(400, "adapter must be qwen or flux")

    async def step(be, s, progress):
        progress(0, 1, f"making one {body.adapter} preview image")
        await imgplan.preview(scene_id, body.adapter, body.seed, s, settings_mod.api_key())
        progress(1, 1, "done")
    return _start(sc["plan_id"], "preview", step)


@router.patch("/scenes/{scene_id}/previews/{preview_id}")
async def rate_preview(scene_id: str, preview_id: str, rating: dict):
    return _guard(imgplan.rate_preview, scene_id, preview_id, rating)


@router.post("/{plan_id}/validate")
async def validate(plan_id: str):
    def both():
        n = planner.validate_plan(plan_id)
        b = storyboard.validate_storyboard(plan_id)
        out = {"narration": n, "storyboard": b, "ok": n["ok"] and b["ok"]}
        if any((sc["data"].get("prompts")) for sc in storyboard.get_scenes(plan_id)):
            out["prompts"] = imgplan.validate_prompts(plan_id)
            out["ok"] = out["ok"] and out["prompts"]["ok"]
        return out
    return await asyncio.to_thread(_guard, both)
