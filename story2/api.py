"""HTTP API for Phase 2 (mounted under /api/plans). Same login as the rest of the app.
Model steps run as background jobs (start, then poll /api/plans/{id}/job); everything else is immediate."""
import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from story import db, llm, settings as settings_mod, storytypes
from story.pipeline import manager
from fastapi.responses import FileResponse

from . import describe, editorial, export, imgplan, imgprompts, intake, jobs, planner, providers, resolve, storyboard, styles, voices

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
        return await step(llm.ChatBackend(s, settings_mod.api_key()), s, progress)

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
    return {"providers": [providers.public(m) for m in providers.PROVIDERS], "source": providers.CONFIG_SOURCE, "default": providers.DEFAULT_MODEL}


@router.get("/providers/probe")
async def probe_providers():
    return await asyncio.to_thread(providers.probe, settings_mod.get(), settings_mod.api_key())


@router.get("/styles")
async def visual_styles():
    return {"styles": styles.public(), "default": styles.DEFAULT}


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


@router.get("/voices")
async def voice_engines():
    return {"engines": voices.public(), "default": voices.DEFAULT_ENGINE}


@router.get("/{plan_id}")
async def plan(plan_id: str):
    p = _guard(planner.get_plan, plan_id)
    p["job"] = jobs.status(plan_id)
    p["story_type"] = storytypes.of_plan(p)
    p["story_type_label"] = storytypes.STORY_TYPES[p["story_type"]]["label"]
    p["project_story_type"] = storytypes.for_pid(p["project_id"])          # the project may have been changed since this plan was made
    p["approval"] = editorial.approval_state(p)
    p["content_hash"] = editorial.content_hash(p)
    p["exports"] = export.list_exports(plan_id)
    p["style"] = style_info(p)
    p["steps_done"] = step_times(plan_id)
    p["blockers"] = resolve.blockers(plan_id)
    p["cast_gaps"] = [{"id": a["id"], "name": a["name"], "kind": a["kind"], "missing": describe.missing(a["kind"], a["data"].get("appearance")),
                       "hints": describe.hints(a["kind"])} for a in p["assets"] if a["kind"] in ("person", "place", "prop")
                      and describe.missing(a["kind"], a["data"].get("appearance"))]
    p["working_title"] = intake.load(p["candidate_id"])["evidence"]["working_title"]
    return p


class ResolveReq(BaseModel):
    key: str
    fix: str | None = None


@router.post("/{plan_id}/resolve")
async def resolve_blocker(plan_id: str, body: ResolveReq):
    """Apply one of the fixes offered for a blocking check. Instant fixes run now and answer with what happened; model fixes start the usual background job, whose
    summary arrives as `job.note`."""
    _guard(planner.get_plan, plan_id)
    cur = next((b for b in resolve.blockers(plan_id) if b["key"] == body.key), None)
    if not cur:
        return {"kind": "instant", "message": "That check no longer blocks anything: it was already cleared.", "blockers": resolve.blockers(plan_id)}
    fix = body.fix or cur["fixes"][0]["id"]
    if fix not in {f["id"] for f in cur["fixes"]}:
        raise HTTPException(400, f"'{fix}' is not an offered fix for this check")
    if resolve.FIXES[fix]["kind"] == "instant":
        if jobs.busy():
            raise HTTPException(409, "a step is running; wait for it to finish")
        msg = await asyncio.to_thread(_guard, resolve.run_instant, plan_id, fix, body.key)
        return {"kind": "instant", "message": msg, "blockers": resolve.blockers(plan_id)}

    async def step(be, s, progress):
        return await resolve.run_job(plan_id, fix, body.key, be, s, progress)
    return {"kind": "job", "job": _start(plan_id, "fix: " + resolve.FIXES[fix]["label"].lower(), step)}


STEP_EVENTS = ("blueprint", "narration", "registry", "references", "storyboard", "compile_prompts", "fix_repeats", "approved", "export", "voice", "scene_pictures", "graphics", "video", "thumbnail", "auto_run")


def step_times(plan_id: str) -> dict:
    """When each step of the screen last finished, from the plan's own log (it survives restarts): {event: seconds since 1970}."""
    rows = db.q(f"SELECT what, MAX(ts) AS ts FROM plan_revisions WHERE plan_id=? AND what IN ({','.join('?' * len(STEP_EVENTS))}) GROUP BY what", [plan_id, *STEP_EVENTS])
    return {r["what"]: r["ts"] for r in rows}


def style_info(p: dict) -> dict:
    """The chosen look and whether the characters and scenes were made for it. A plan made before this direction (or in another style) is flagged."""
    st, sid = p["settings"], styles.style_id(p["settings"])
    asset = next((a for a in p["assets"] if a["kind"] == "style"), None)
    return {**{k: v for k, v in styles.get(sid).items() if k in ("id", "label", "description", "short")},
            "registry_stale": bool(p["assets"]) and (st.get("registry_direction") != styles.DIRECTION or st.get("registry_style") != sid or not asset),
            "storyboard_stale": bool(p["scenes"]) and (st.get("storyboard_direction") != styles.DIRECTION or st.get("storyboard_style") != sid or orphaned_scenes(p)),
            "scenes_orphaned": orphaned_scenes(p)}


def orphaned_scenes(p: dict) -> bool:
    """The characters were created again after the scenes were designed: the scenes point at assets that no longer exist, so they must be redesigned."""
    ids = {a["id"] for a in p["assets"] if a["kind"] != "style"}
    used = {x for sc in p["scenes"] for x in (sc["data"].get("continuity") or {}).get("assets", [])}
    return bool(p["scenes"] and p["assets"] and used and not (used & ids))


class VisualStyle(BaseModel):
    style: str


@router.patch("/{plan_id}/visual-style")
async def set_visual_style(plan_id: str, body: VisualStyle):
    """Choose the look. The style asset is rewritten from the preset at once and prompts are recompiled; characters and scenes made for another
    look are flagged so the screen can lead the editor through redoing them."""
    p = _guard(planner.get_plan, plan_id)
    try:
        styles.get(body.style)
    except styles.StyleError as e:
        raise HTTPException(400, str(e))
    st = {**p["settings"], "visual_style": body.style}
    db.ex("UPDATE plans SET settings=?, updated_at=? WHERE id=?", (db.jdump(st), db.now(), plan_id))
    for a in storyboard.get_assets(plan_id):
        if a["kind"] == "style" and not a["locked"]:
            db.ex("UPDATE assets SET data=?, rev=rev+1, updated_at=? WHERE id=?", (db.jdump(styles.style_asset_data(st)), db.now(), a["id"]))
    if storyboard.get_scenes(plan_id):
        imgplan.compile_plan(plan_id)
    return await plan(plan_id)


class Cast(BaseModel):
    indian: bool
    write_into_list: bool = False


class VideoTitle(BaseModel):
    title: str


@router.post("/{plan_id}/title")
async def set_video_title(plan_id: str, body: VideoTitle):
    t = body.title.strip()
    if not t:
        raise HTTPException(400, "title cannot be empty")
    p = _guard(planner.get_plan, plan_id)
    db.ex("UPDATE plans SET settings=?, updated_at=? WHERE id=?", (db.jdump({**p["settings"], "video_title": t}), db.now(), plan_id))
    return {"video_title": t}


@router.patch("/{plan_id}/cast")
async def set_cast(plan_id: str, body: Cast):
    """Draw the people of this video as Indian (on by default) or as the story says. Prompts are recompiled at once and reference sheets and scene pictures
    made the other way are flagged old. `write_into_list` also rewrites the character list itself (skin, hair, eyes), which changes what was approved."""
    p = _guard(planner.get_plan, plan_id)
    db.ex("UPDATE plans SET settings=?, updated_at=? WHERE id=?", (db.jdump({**p["settings"], "cast_indian": body.indian}), db.now(), plan_id))
    if body.indian and body.write_into_list:
        storyboard.apply_cast(plan_id)
    if storyboard.get_scenes(plan_id):
        imgplan.compile_plan(plan_id)
    return await plan(plan_id)


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


class Tts(BaseModel):
    engine: str
    voice: str | None = None


@router.patch("/{plan_id}/tts")
async def set_tts(plan_id: str, body: Tts):
    """Pick the voice engine and voice. Outside the content hash on purpose: it changes which takes count, not what was approved."""
    plan = _guard(planner.get_plan, plan_id)
    try:
        narr = voices.choose(plan["narrator"], body.engine, body.voice)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _guard(planner.set_narrator, plan_id, None, tts=narr["tts"])


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
        await asyncio.to_thread(imgplan.compile_plan, plan_id)             # the prompts follow the new cameras at once, and the checks are run again,
        await asyncio.to_thread(editorial.run_checks, plan_id)             # so the next step is the next step and not "write prompts" or "fix repeats" again
    return _start(plan_id, "fix repeats", step)


@router.post("/{plan_id}/registry")
async def registry(plan_id: str):
    p = _guard(planner.get_plan, plan_id)
    if not describe.cast_chosen(p["settings"]) and not storyboard.get_assets(plan_id):
        raise HTTPException(400, "choose who appears in the pictures first: an Indian cast, or as the story says (the card above the character list)")

    async def step(be, s, progress):
        progress(0, 1, "listing recurring people, places and style")
        await storyboard.make_registry(plan_id, be, s)
        progress(1, 1, "done")
    return _start(plan_id, "registry", step)


class StoryboardReq(BaseModel):
    segment_ids: list[str] | None = None
    replace_approved: bool = False


@router.post("/{plan_id}/storyboard")
async def make_storyboard(plan_id: str, body: StoryboardReq | None = None):
    p = _guard(planner.get_plan, plan_id)
    if not p["segments"]:
        raise HTTPException(400, "write the narration first")

    async def step(be, s, progress):
        await storyboard.make_storyboard(plan_id, be, s, body.segment_ids if body else None, progress, bool(body and body.replace_approved))
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


class NewAsset(BaseModel):
    name: str
    kind: str = "person"
    description: str = ""
    fictionalisation: str = "generic_reconstruction"


@router.post("/{plan_id}/assets")
async def add_asset(plan_id: str, body: NewAsset):
    """Add a person, place or object by hand, for anything the story needs that the list missed."""
    _guard(planner.get_plan, plan_id)
    name = body.name.strip()
    if not name or body.kind not in ("person", "place", "prop"):
        raise HTTPException(400, "give it a name and say whether it is a person, a place or a prop")
    if any(a["name"].lower() == name.lower() for a in storyboard.get_assets(plan_id)):
        raise HTTPException(400, f"there is already an asset called {name}")
    data = {"name": name, "kind": body.kind, "description": body.description.strip(), "fixed": [], "flexible": [], "period": "",
            "fictionalisation": body.fictionalisation if body.fictionalisation in ("generic_reconstruction", "source_supported", "real_person_no_likeness", "fictional") else "generic_reconstruction",
            "evidence_note": "added by the editor"}
    import uuid
    db.ex("INSERT INTO assets(id,plan_id,kind,name,data,updated_at) VALUES(?,?,?,?,?,?)", ("as-" + uuid.uuid4().hex[:8], plan_id, body.kind, name, db.jdump(data), db.now()))
    return _guard(planner.get_plan, plan_id)


@router.patch("/assets/{asset_id}")
async def patch_asset(asset_id: str, patch: dict):
    a = db.one("SELECT * FROM assets WHERE id=?", (asset_id,))
    if not a:
        raise HTTPException(404, "asset not found")
    data = db.jload(a["data"], {})
    for k in ("description", "fixed", "flexible", "period", "fictionalisation", "evidence_note"):
        if k in patch:
            data[k] = patch[k]
    if "appearance" in patch:                                          # slot values: the description and the fixed details are rebuilt from them
        data["appearance"] = {**describe.clean(data.get("appearance")), **describe.clean(patch["appearance"])}
        if "description" not in patch:
            data["description"] = describe.describe(a["kind"], data["appearance"]) or data.get("description", "")
        if "fixed" not in patch and describe.fixed_from(a["kind"], data["appearance"]):
            data["fixed"] = describe.fixed_from(a["kind"], data["appearance"])
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
