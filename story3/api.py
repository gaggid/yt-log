"""HTTP API for Phase 3 media (mounted under /api/media). Same login as the rest of the app; generation runs as the same one-at-a-time background
jobs as Phase 2 (the model server answers one request at a time)."""
import asyncio

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from story import llm, settings as settings_mod
from story.pipeline import manager
from story2 import jobs, planner, providers

from . import auto, clips, graphics, likeness, refs, scenes, store, thumbnail, video, voice

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
    await asyncio.to_thread(providers.refresh, settings_mod.get(), settings_mod.api_key())             # image models the gateway lists become choices
    st = {"voice": voice.state(plan_id), "refs": refs.state(plan_id), "scenes": scenes.state(plan_id), "clips": clips.state(plan_id), "graphics": graphics.state(plan_id), "video": video.state(plan_id), "thumbnail": thumbnail.state(plan_id), "likeness": likeness.state(plan_id)}
    return {**st, "auto": auto.state(plan_id, st)}


class LikenessMode(BaseModel):
    mode: str
    public_figure: bool | None = None


class PhotoOn(BaseModel):
    approved: bool = True


@router.get("/{plan_id}/likeness")
async def likeness_state(plan_id: str):
    return _guard(likeness.state, plan_id)


@router.post("/{plan_id}/likeness/{asset_id}/mode")
async def likeness_mode(plan_id: str, asset_id: str, body: LikenessMode):
    return _guard(likeness.set_mode, plan_id, asset_id, body.mode, body.public_figure)


@router.post("/{plan_id}/likeness/{asset_id}/search")
async def likeness_search(plan_id: str, asset_id: str):
    return await asyncio.to_thread(_guard, likeness.find_photos, plan_id, asset_id)


@router.post("/{plan_id}/likeness/{asset_id}/upload")
async def likeness_upload(plan_id: str, asset_id: str, file: UploadFile = File(...)):
    raw = await file.read()
    if len(raw) > likeness.MAX_BYTES:
        raise HTTPException(413, "the photo is larger than 8 MB")
    _guard(likeness.add_photo, plan_id, asset_id, raw, {"origin": "upload", "url": file.filename or "", "licence": "supplied by the editor"})
    return _guard(likeness.state, plan_id)


@router.post("/{plan_id}/likeness/{asset_id}/photos/{photo_id}/approve")
async def likeness_approve(plan_id: str, asset_id: str, photo_id: str, body: PhotoOn | None = None):
    return _guard(likeness.approve_photo, plan_id, asset_id, photo_id, (body or PhotoOn()).approved)


@router.post("/{plan_id}/likeness/{asset_id}/photos/{photo_id}/reject")
async def likeness_reject(plan_id: str, asset_id: str, photo_id: str):
    return _guard(likeness.reject_photo, plan_id, asset_id, photo_id)


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


@router.post("/{plan_id}/voice/sample")
async def voice_sample(plan_id: str):
    async def work(progress):
        await voice.make_sample(plan_id, progress, settings_mod.get(), settings_mod.api_key())
    return _start(plan_id, "voice sample", work)


class RefsReq(BaseModel):
    asset_ids: list[str] | None = None
    candidates: int = refs.DEFAULT_CANDIDATES
    only_missing: bool = True
    model: str | None = None
    score: bool = True
    prompts: dict[str, str] | None = None              # asset id -> a prompt written by a person, for that asset's new pictures only


def _known_model(model: str | None) -> None:
    if model and model not in providers.PROVIDERS:
        raise HTTPException(400, f"unknown image model '{model}' (known: {', '.join(providers.PROVIDERS)})")


@router.post("/{plan_id}/references")
async def make_references(plan_id: str, body: RefsReq | None = None):
    body = body or RefsReq()
    if not refs.targets(plan_id):
        raise HTTPException(400, "no person, place or object appears in two or more scenes, so no reference pictures are needed")
    _known_model(body.model)

    async def work(progress):
        await refs.generate(plan_id, body.asset_ids, body.candidates, body.only_missing, body.model, progress, settings_mod.get(), settings_mod.api_key(), score=body.score, prompts=body.prompts)
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
    score: bool = False


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


@router.get("/{plan_id}/scenes/{scene_id}/options")
async def scene_options(plan_id: str, scene_id: str):
    return _guard(scenes.options, plan_id, scene_id)


class RedrawReq(BaseModel):
    model: str
    mode: str = "generate"
    prompt: str | None = None
    negative_prompt: str | None = None
    candidates: int = 1
    remember: bool = False


@router.post("/{plan_id}/scenes/{scene_id}/redraw")
async def redraw_scene(plan_id: str, scene_id: str, body: RedrawReq):
    _need_prompts(plan_id)
    _known_model(body.model)
    if body.mode not in ("generate", "edit"):
        raise HTTPException(400, "mode must be generate (plain) or edit (from the reference sheets)")
    _guard(scenes.options, plan_id, scene_id)                                    # refuses an unknown scene before a job starts
    if body.mode == "edit":
        opt = scenes.options(plan_id, scene_id)["models"].get(body.model) or {}
        if not opt.get("can_edit"):
            raise HTTPException(400, "this model or scene cannot use reference sheets: " + ("the scene has no approved reference sheet" if opt.get("edits") else "the model cannot edit"))

    async def work(progress):
        await scenes.redraw(plan_id, scene_id, body.model, body.mode, body.prompt, body.negative_prompt, body.candidates, body.remember, progress,
                            settings_mod.get(), settings_mod.api_key())
    return _start(plan_id, "scene picture", work)


class AutoReq(BaseModel):
    only: list[str] | None = None


@router.post("/{plan_id}/auto")
async def auto_run(plan_id: str, body: AutoReq | None = None):
    _guard(planner.get_plan, plan_id)
    if not auto.state(plan_id)["remaining"]:
        raise HTTPException(400, "every step is already finished")
    only = (body.only if body else None)
    if only and not set(only) <= {k for k, _l in auto.STAGES}:
        raise HTTPException(400, "unknown step")

    async def work(progress):
        await auto.run(plan_id, progress, settings_mod.get(), settings_mod.api_key(), only)
    return _start(plan_id, "auto-run", work)


class VideoReq(BaseModel):
    profile: str = "draft"
    captions: bool = False
    allow_gaps: bool = False


@router.post("/{plan_id}/thumbnail")
async def make_thumbnail(plan_id: str):
    plan = _guard(planner.get_plan, plan_id)
    if not plan["blueprint"]:
        raise HTTPException(400, "plan the story first")

    async def work(progress):
        be = llm.ChatBackend(settings_mod.get(), settings_mod.api_key())
        await thumbnail.make(plan_id, be, settings_mod.get(), settings_mod.api_key(), progress)
    return _start(plan_id, "thumbnail", work)


@router.post("/{plan_id}/video")
async def make_video(plan_id: str, body: VideoReq | None = None):
    body = body or VideoReq()
    _guard(planner.get_plan, plan_id)
    if body.profile not in video.PROFILES:
        raise HTTPException(400, f"unknown profile '{body.profile}'")
    chk = _guard(video.checklist, plan_id)
    if chk["blockers"] and not body.allow_gaps:
        raise HTTPException(400, f"{len(chk['blockers'])} thing(s) are missing (see the checklist); make them first or build anyway with placeholders")

    async def work(progress):
        await asyncio.to_thread(video.build, plan_id, body.profile, body.captions, body.allow_gaps, progress)
    return _start(plan_id, "video", work)


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
            "clips": clips.state(it["plan_id"]) if it["kind"] == "clip" else None,
            "graphics": graphics.state(it["plan_id"]) if it["kind"] == "graphic" else None}


# ── motion clips ──────────────────────────────────────────────────────────────

class ClipsSettings(BaseModel):
    enabled: bool


@router.get("/{plan_id}/clips")
async def clips_state(plan_id: str):
    _guard(planner.get_plan, plan_id)
    return _guard(clips.state, plan_id)


@router.post("/{plan_id}/clips/settings")
async def clips_settings(plan_id: str, body: ClipsSettings):
    _guard(planner.get_plan, plan_id)
    _guard(clips.set_settings, plan_id, {"enabled": body.enabled})
    return _guard(clips.state, plan_id)


@router.post("/{plan_id}/clips/generate")
async def clips_generate(plan_id: str):
    _guard(planner.get_plan, plan_id)
    s, api_key = settings_mod.get(), settings_mod.api_key()

    async def work(progress):
        await clips.generate(plan_id, None, progress, s, api_key)
    return _start(plan_id, "clips", work)


@router.post("/{plan_id}/clips/{item_id}/approve")
async def clip_approve(plan_id: str, item_id: str):
    _guard(planner.get_plan, plan_id)
    return _guard(clips.approve, item_id)


@router.post("/{plan_id}/clips/{item_id}/unapprove")
async def clip_unapprove(plan_id: str, item_id: str):
    _guard(planner.get_plan, plan_id)
    return _guard(clips.unapprove, item_id)
