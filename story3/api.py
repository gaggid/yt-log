"""HTTP API for Phase 3 media (mounted under /api/media). Same login as the rest of the app; generation runs as the same one-at-a-time background
jobs as Phase 2 (the model server answers one request at a time)."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from story import llm, settings as settings_mod
from story.pipeline import manager
from story2 import jobs, planner

from . import graphics, refs, scenes, store, voice

router = APIRouter(prefix="/api/media")


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except (planner.PlanError, voice.MediaError) as e:   # refs raises the same MediaError
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
    return {"voice": voice.state(plan_id), "refs": refs.state(plan_id), "scenes": scenes.state(plan_id), "graphics": graphics.state(plan_id)}


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


class RefsReq(BaseModel):
    asset_ids: list[str] | None = None
    candidates: int = refs.DEFAULT_CANDIDATES
    only_missing: bool = True
    model: str | None = None
    score: bool = True


@router.post("/{plan_id}/references")
async def make_references(plan_id: str, body: RefsReq | None = None):
    body = body or RefsReq()
    if not refs.targets(plan_id):
        raise HTTPException(400, "no person, place or object appears in two or more scenes, so no reference pictures are needed")

    async def work(progress):
        await refs.generate(plan_id, body.asset_ids, body.candidates, body.only_missing, body.model, progress, settings_mod.get(), settings_mod.api_key(), score=body.score)
    return _start(plan_id, "references", work)


@router.post("/{plan_id}/references/score")
async def score_references(plan_id: str):
    if not refs.state(plan_id)["unscored"]:
        raise HTTPException(400, "every finished picture already has a score")

    async def work(progress):
        await refs.score_items(plan_id, None, progress, settings_mod.get(), settings_mod.api_key())
        progress(1, 1, "done")
    return _start(plan_id, "references", work)


class BestReq(BaseModel):
    min_score: int = 70


@router.post("/{plan_id}/references/approve-best")
async def approve_best_references(plan_id: str, body: BestReq | None = None):
    return _guard(refs.approve_best, plan_id, (body or BestReq()).min_score)


class SkipReq(BaseModel):
    asset_id: str
    skip: bool = True


@router.post("/{plan_id}/references/skip")
async def skip_reference(plan_id: str, body: SkipReq):
    return {"refs": _guard(refs.set_skip, plan_id, body.asset_id, body.skip)}


class ScenesReq(BaseModel):
    scene_ids: list[str] | None = None
    candidates: int | None = None
    only_missing: bool = True
    model: str | None = None
    mode: str | None = None
    score: bool = True


def _need_prompts(plan_id: str) -> None:
    if not scenes.state(plan_id)["ready"]:
        raise HTTPException(400, "write the image prompts first: scene pictures are drawn from them")


@router.post("/{plan_id}/scenes")
async def make_scene_pictures(plan_id: str, body: ScenesReq | None = None):
    body = body or ScenesReq()
    _need_prompts(plan_id)

    async def work(progress):
        await scenes.generate(plan_id, body.scene_ids, body.candidates, body.only_missing, body.model, body.mode, progress, settings_mod.get(), settings_mod.api_key(), score=body.score)
    return _start(plan_id, "scene pictures", work)


@router.post("/{plan_id}/scenes/trial")
async def scene_trial(plan_id: str):
    _need_prompts(plan_id)

    async def work(progress):
        await scenes.run_trial(plan_id, progress, settings_mod.get(), settings_mod.api_key())
    return _start(plan_id, "scene trial", work)


@router.post("/{plan_id}/scenes/score")
async def score_scene_pictures(plan_id: str):
    if not scenes.state(plan_id)["unscored"]:
        raise HTTPException(400, "every finished picture already has a score")

    async def work(progress):
        await scenes.score_items(plan_id, None, progress, settings_mod.get(), settings_mod.api_key())
        progress(1, 1, "done")
    return _start(plan_id, "scene pictures", work)


@router.post("/{plan_id}/scenes/approve-best")
async def approve_best_scenes(plan_id: str, body: BestReq | None = None):
    return _guard(scenes.approve_best, plan_id, (body or BestReq()).min_score)


class SceneSettings(BaseModel):
    model: str | None = None
    mode: str | None = None
    candidates: int | None = None


@router.post("/{plan_id}/scenes/settings")
async def scene_settings(plan_id: str, body: SceneSettings):
    patch = body.model_dump(exclude_unset=True)
    return {"scenes": _guard(scenes.set_settings, plan_id, patch)}


class ChooseReq(BaseModel):
    model: str
    mode: str


@router.post("/{plan_id}/scenes/choose")
async def scene_choose(plan_id: str, body: ChooseReq):
    return {"scenes": _guard(scenes.choose, plan_id, body.model, body.mode)}


class CorrectReq(BaseModel):
    change: str
    keep: list[str] | None = None
    item_id: str | None = None


@router.post("/{plan_id}/scenes/{scene_id}/correct")
async def correct_scene(plan_id: str, scene_id: str, body: CorrectReq):
    if not body.change.strip():
        raise HTTPException(400, "say what to change")

    async def work(progress):
        await scenes.correct(plan_id, scene_id, body.change, body.keep, body.item_id, progress, settings_mod.get(), settings_mod.api_key())
    return _start(plan_id, "scene picture", work)


class GraphicsReq(BaseModel):
    scene_ids: list[str] | None = None
    force: bool = False


@router.post("/{plan_id}/graphics")
async def build_graphics(plan_id: str, body: GraphicsReq | None = None):
    body = body or GraphicsReq()
    _guard(planner.get_plan, plan_id)
    return _guard(graphics.build, plan_id, body.scene_ids, body.force)


class GraphicsApprove(BaseModel):
    include_fallbacks: bool = False


@router.post("/{plan_id}/graphics/approve-all")
async def approve_all_graphics(plan_id: str, body: GraphicsApprove | None = None):
    return _guard(graphics.approve_all, plan_id, (body or GraphicsApprove()).include_fallbacks)


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
        if it["kind"] == "reference":
            _guard(refs.approve, item_id, body.approved)
        elif it["kind"] == "scene_image":
            _guard(scenes.approve, item_id, body.approved)
        elif it["kind"] == "graphic":
            _guard(graphics.approve, item_id, body.approved)
        else:
            store.approve(item_id, body.approved)
        if it["kind"] == "voice":
            voice.apply_timing(it["plan_id"])
    return {"item": store.get(item_id), "voice": voice.state(it["plan_id"]) if it["kind"] == "voice" else None,
            "refs": refs.state(it["plan_id"]) if it["kind"] == "reference" else None,
            "scenes": scenes.state(it["plan_id"]) if it["kind"] == "scene_image" else None,
            "graphics": graphics.state(it["plan_id"]) if it["kind"] == "graphic" else None}
