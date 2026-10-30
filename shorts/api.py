"""HTTP API for Shorts (mounted under /api/shorts). Same login as the rest of the app. Everything that talks to the gateway runs as the same one-at-a-time background job as the
long-form steps (story2/jobs.py), keyed by the short's id."""
import asyncio
import io
import time

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel

from story import db, llm, settings as settings_mod
from story.pipeline import manager
from story2 import intake, jobs, maya, providers, voices
from story3 import store as media
from story3.voice import MediaError

from characters import store as cstore, studio_edit
from . import auto, cast, checks, clips, frames, models, pipelines as P, planner, remix, stitch, store, timeline, voice as svoice, wan

router = APIRouter(prefix="/api/shorts")
MAX_UPLOAD = 12 * 1024 * 1024
MAX_VIDEO_UPLOAD = 400 * 1024 * 1024
IMAGE_MODES = ("qwen", "anchor", "per_shot", "wan")
SIZES = (models.SIZE_PORTRAIT, models.SIZE_SHARP)


def _get(short_id: str) -> dict:
    try:
        return store.get(short_id)
    except store.ShortError as e:
        raise HTTPException(404, str(e))


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except (store.ShortError, MediaError, wan.WanError, ValueError) as e:
        raise HTTPException(400, str(e))


def _start(short_id: str, kind: str, work):
    _get(short_id)
    if manager.busy():
        raise HTTPException(409, "story processing is running; wait for it to finish (the model server answers one request at a time)")
    try:
        return jobs.start(short_id, kind, work)
    except jobs.JobBusy as e:
        raise HTTPException(409, str(e))


def _backend():
    s = settings_mod.get()
    return s, llm.ChatBackend(s, settings_mod.api_key())


# ── listing, creating ────────────────────────────────────────────────────────

@router.get("/options")
async def options():
    s = settings_mod.get()
    listed = await wan.models(s["base_url"], settings_mod.api_key())
    ids = {m.get("id") for m in listed}
    await asyncio.to_thread(providers.refresh, s, settings_mod.api_key())
    pipes = {}
    for k, p in P.PIPELINES.items():
        have = [m in ids for m in p["models"]] if listed else []
        pipes[k] = {"label": p["label"], "about": p["about"], "models": p["models"], "available": (all(have) if listed else None),
                    "missing": [m for m, h in zip(p["models"], have) if not h] if listed else []}
    return {"pipelines": pipes, "voices": voices.public(), "image_modes": IMAGE_MODES, "image_models": [{"id": k, "label": v["label"], "default": v["default"], "licence": v["licence"]["status"]} for k, v in providers.PROVIDERS.items()], "sizes": SIZES, "gateway_video_models": sorted(i for i in ids if i), "tags": list(maya.STYLE_TAGS),
            "limits": {"target_s": models.TARGET_S, "max_shot_s": models.MAX_SHOT_S}}


@router.get("/stories")
async def stories():
    """Approved stories a short can be made from."""
    rows = db.q("SELECT c.id, c.title, c.premise, p.title AS project FROM candidates c JOIN projects p ON p.id=c.project_id WHERE c.status='approved' ORDER BY c.updated_at DESC")
    return rows


@router.get("")
async def listing():
    return [{"id": s["id"], "title": s["title"], "pipeline": s["pipeline"], "status": s["status"], "updated_at": s["updated_at"], "created_at": s["created_at"],
             "shots": len(s["shots"]), "source": s["source"].get("kind")} for s in store.listing()]


class CreateReq(BaseModel):
    pipeline: str
    kind: str = "idea"                    # idea | story
    text: str = ""
    candidate_id: str = ""
    title: str = ""
    settings: dict | None = None


@router.post("")
async def create(body: CreateReq):
    if body.pipeline not in P.PIPELINES:
        raise HTTPException(400, f"pipeline is one of: {', '.join(P.PIPELINES)}")
    if body.kind == "story":
        try:
            story = intake.load(body.candidate_id)
        except intake.IntakeError as e:
            raise HTTPException(400, str(e))
        ready = intake.readiness(story)
        if not ready["ready"]:
            raise HTTPException(400, next(c["text"] for c in ready["checks"] if c["level"] == "blocked"))
        src = {"kind": "story", "candidate_id": body.candidate_id, "facts": intake.facts_text(story["public"]), "text": ""}
        title = body.title or story["evidence"]["working_title"]
    elif body.kind == "idea":
        if body.pipeline != "remix" and len(body.text.strip()) < 10:
            raise HTTPException(400, "write the idea in a sentence or two")
        src = {"kind": "idea", "text": body.text.strip(), "candidate_id": "", "facts": ""}
        title = body.title or (body.text.strip()[:60] or "Remix")
    else:
        raise HTTPException(400, "kind is idea or story")
    st = {k: v for k, v in (body.settings or {}).items() if k in store.DEFAULT_SETTINGS or k in ("character_text", "tone")}
    short = store.create(title, body.pipeline, src, st, {"remix": dict(remix.DEFAULT)} if body.pipeline == "remix" else None)
    return await state(short["id"])


@router.delete("/{short_id}")
async def delete(short_id: str):
    _get(short_id)
    if jobs.busy() and jobs.status(short_id).get("state") == "running":
        raise HTTPException(409, "a job is running for this short; stop it first")
    store.delete(short_id)
    return {"ok": True}


# ── state ────────────────────────────────────────────────────────────────────

@router.get("/file/{short_id}/{name:path}")
async def file(short_id: str, name: str):
    root = store.media_dir(short_id).resolve()
    f = (root / name).resolve()
    if root not in f.parents or not f.is_file():
        raise HTTPException(404, "file not found")
    return FileResponse(f)


@router.get("/{short_id}/job")
async def job(short_id: str):
    return jobs.status(short_id)


@router.post("/{short_id}/cancel")
async def cancel(short_id: str):
    return {"cancelled": jobs.cancel(short_id)}


@router.get("/{short_id}")
async def state(short_id: str):
    short = _get(short_id)
    real = svoice.real_seconds(short)
    tl = timeline.build(short, real) if short["shots"] else None
    out = {"id": short["id"], "title": short["title"], "pipeline": short["pipeline"], "pipeline_label": P.pipeline(short)["label"], "status": short["status"], "source": short["source"],
           "settings": short["settings"], "plan": short["plan"], "beats": short["beats"], "images": short["images"], "keyframes_confirmed": short.get("keyframes_confirmed", False), "keyframes_on": P.keyframes_on(short),
           "job": jobs.status(short_id), "estimate_s": P.estimate_s(short) if (short["shots"] or short["pipeline"] == "remix") else 0,
           "voice": svoice.state(short), "auto": auto.state(short), "final": stitch.final_state(short_id)}
    if short["pipeline"] == "remix":
        r = remix.data(short)
        ch = remix.character(short)
        out.update(shots=[], remix={**r, "character_label": ch["label"] if ch else "", "character_ok": bool(ch and ch["path"]), "cuts": r["cuts"][:400], "check": remix.check(short), "parts": [p["id"] if p else None for p in remix.chosen_parts(short)],
                                    "source_url": f"/api/shorts/file/{short_id}/{r['source']}" if r["source"] else "",
                                    "driving_urls": [f"/api/shorts/file/{short_id}/{d}" for d in r["driving"]],
                                    "part_clips": [[clips._view(short_id, i) for i in media.items(short_id, store.CLIP, f"remix-{n + 1}")] for n in range(r["segments"])]},
                   checks=remix.check(short), timeline=None)
    else:
        out.update(shots=[{**sh, **row} for sh, row in zip(short["shots"], clips.shot_rows(short))], checks=checks.run(short), timeline=tl)
        out["checks"].pop("timeline", None)
    return out


# ── settings and edits ───────────────────────────────────────────────────────

class SettingsReq(BaseModel):
    image_mode: str | None = None
    image_model: str | None = None
    cast: list[dict] | None = None
    place_id: str | None = None
    size: str | None = None
    steps: int | None = None
    chain: bool | None = None
    seed: int | None = None
    voice: dict | None = None
    captions: bool | None = None
    bed: bool | None = None
    review_keyframes: bool | None = None
    character_text: str | None = None
    tone: str | None = None


@router.patch("/{short_id}/settings")
async def patch_settings(short_id: str, body: SettingsReq):
    short = _get(short_id)
    patch = body.model_dump(exclude_unset=True)
    if "image_mode" in patch and patch["image_mode"] not in IMAGE_MODES:
        raise HTTPException(400, f"image_mode is one of: {', '.join(IMAGE_MODES)}")
    if "image_model" in patch and patch["image_model"] not in providers.PROVIDERS:
        raise HTTPException(400, f"image_model is one of: {', '.join(providers.PROVIDERS)}")
    if "cast" in patch:
        patch["cast"] = [{"character_id": str(e.get("character_id", "")), "look_id": str(e.get("look_id", ""))} for e in (patch["cast"] or []) if e.get("character_id")]
        if len(patch["cast"]) > cast.MAX_PEOPLE:
            raise HTTPException(400, f"at most {cast.MAX_PEOPLE} characters in a short")
        for e in patch["cast"]:
            try:
                cstore.get(e["character_id"])
            except cstore.CharError as ex:
                raise HTTPException(400, str(ex))
    if patch.get("place_id"):
        try:
            if cstore.get(patch["place_id"])["kind"] != "place":
                raise HTTPException(400, "that is not a place")
        except cstore.CharError as ex:
            raise HTTPException(400, str(ex))
    if "size" in patch and patch["size"] not in SIZES:
        raise HTTPException(400, f"size is one of: {', '.join(SIZES)}")
    if "size" in patch and short["pipeline"] != "quick":
        patch.pop("size")                                               # only the 5B pipeline has the sharper size
    if "steps" in patch and patch["steps"] is not None and not 1 <= patch["steps"] <= 100:
        raise HTTPException(400, "steps is between 1 and 100")
    if "voice" in patch:
        try:
            patch["voice"] = voices.choose({}, patch["voice"].get("engine", ""), patch["voice"].get("voice"))["tts"]
        except ValueError as e:
            raise HTTPException(400, str(e))
    short["settings"].update(patch)
    store.save(short)
    if short["shots"]:
        planner.sync_timing(short_id)
    return await state(short_id)


class PlanPatch(BaseModel):
    title: str | None = None
    character: str | None = None
    place: str | None = None
    look: str | None = None


@router.patch("/{short_id}/plan")
async def patch_plan(short_id: str, body: PlanPatch):
    short = _get(short_id)
    p = body.model_dump(exclude_unset=True)
    if "title" in p:
        short["title"] = (p.pop("title") or short["title"]).strip()[:90]
    short["plan"].update({k: (v or "").strip() for k, v in p.items()})
    store.save(short)
    return await state(short_id)


class BeatEdit(BaseModel):
    id: str
    sentences: list[str]
    tag: str | None = None


class NarrationReq(BaseModel):
    beats: list[BeatEdit]


@router.patch("/{short_id}/narration")
async def patch_narration(short_id: str, body: NarrationReq):
    """Edit the words of beats. A beat whose words changed has no valid voice take until it is spoken again."""
    short = _get(short_id)
    by = {b["id"]: b for b in short["beats"]}
    for e in body.beats:
        b = by.get(e.id)
        if not b:
            raise HTTPException(400, f"no such beat: {e.id}")
        texts = [t.strip() for t in e.sentences if t.strip()]
        if not texts:
            raise HTTPException(400, "a beat needs at least one sentence")
        tag = maya.norm_tag(e.tag) if e.tag is not None else b.get("tag", "")
        b["sentences"] = [{"text": t, "tag": tag if i == 0 else ""} for i, t in enumerate(texts)]
        b["tag"] = tag
    store.save(short)
    planner.sync_timing(short_id)
    return await state(short_id)


class ShotPatch(BaseModel):
    prompt: str | None = None
    camera: str | None = None
    still: str | None = None
    character: bool | None = None
    continues: bool | None = None
    setting: str | None = None
    avatar: bool | None = None                     # a talking avatar shot (InfiniteTalk): its picture speaks the voice


@router.patch("/{short_id}/shots/{shot_id}")
async def patch_shot(short_id: str, shot_id: str, body: ShotPatch):
    short = _get(short_id)
    sh = _guard(store.shot_by_id, short, shot_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        sh[k] = v.strip() if isinstance(v, str) else v
    store.save(short)
    return await state(short_id)


# ── pictures the user gives ──────────────────────────────────────────────────

async def _save_image(short_id: str, file: UploadFile, name: str) -> str:
    raw = await file.read()
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(400, "the picture is over 12 MB")
    try:
        im = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "that file is not a picture the app can read (PNG, JPEG or WebP)")
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=94)
    rel = f"upload/{name}-{int(time.time())}.jpg"
    path = store.media_dir(short_id, "upload") / rel.split("/", 1)[1]
    path.write_bytes(buf.getvalue())
    return rel


@router.post("/{short_id}/images/anchor")
async def upload_anchor(short_id: str, file: UploadFile = File(...)):
    short = _get(short_id)
    short["images"]["anchor"] = await _save_image(short_id, file, "anchor")
    if short["settings"]["image_mode"] in ("wan", "qwen"):
        short["settings"]["image_mode"] = "anchor"
    store.save(short)
    return await state(short_id)


@router.delete("/{short_id}/images/anchor")
async def delete_anchor(short_id: str):
    short = _get(short_id)
    short["images"]["anchor"] = ""
    if short["settings"]["image_mode"] == "anchor":
        short["settings"]["image_mode"] = "qwen"
    store.save(short)
    return await state(short_id)


@router.post("/{short_id}/images/shot/{shot_id}")
async def upload_shot_image(short_id: str, shot_id: str, file: UploadFile = File(...)):
    short = _get(short_id)
    _guard(store.shot_by_id, short, shot_id)
    short["images"]["shots"][shot_id] = await _save_image(short_id, file, shot_id)
    if short["settings"]["image_mode"] in ("wan", "qwen"):
        short["settings"]["image_mode"] = "per_shot"
    store.save(short)
    return await state(short_id)


@router.delete("/{short_id}/images/shot/{shot_id}")
async def delete_shot_image(short_id: str, shot_id: str):
    short = _get(short_id)
    short["images"]["shots"].pop(shot_id, None)
    store.save(short)
    return await state(short_id)


# ── steps ────────────────────────────────────────────────────────────────────

@router.post("/{short_id}/plan")
async def make_plan(short_id: str):
    s, be = _backend()
    return _start(short_id, "short_plan", lambda progress: planner.make_plan(short_id, be, s, progress))


@router.post("/{short_id}/fit")
async def fit(short_id: str):
    s, be = _backend()
    return _start(short_id, "short_fit", lambda progress: planner.fit_shots(short_id, be, s, progress))


class BeatReq(BaseModel):
    count: int = 3


@router.post("/{short_id}/beats/{beat_id}/reshoot")
async def reshoot(short_id: str, beat_id: str, body: BeatReq):
    s, be = _backend()

    async def work(progress):
        progress(0, 1, f"writing the shots of {beat_id}")
        await planner.reshoot_beat(short_id, beat_id, max(1, min(6, body.count)), be, s)
        return f"shots of {beat_id} written again"
    return _start(short_id, "short_reshoot", work)


class VoiceReq(BaseModel):
    beat_ids: list[str] | None = None
    only_missing: bool = True


@router.post("/{short_id}/voice")
async def make_voice(short_id: str, body: VoiceReq | None = None):
    body = body or VoiceReq()
    short = _get(short_id)
    if short["pipeline"] == "remix":
        _guard(remix.sync_voiceover, short_id)
    return _start(short_id, "short_voice", lambda progress: svoice.make(short_id, body.beat_ids, body.only_missing, progress))


class ShotsReq(BaseModel):
    shot_ids: list[str] | None = None
    only_missing: bool = True


@router.post("/{short_id}/keyframes")
async def make_keyframes(short_id: str, body: ShotsReq | None = None):
    body = body or ShotsReq()
    if not P.keyframes_on(_get(short_id)):
        raise HTTPException(400, "this short has no start pictures (Wan decides every picture)")
    return _start(short_id, "short_keyframes", lambda progress: clips.make_keyframes(short_id, body.shot_ids, body.only_missing, progress))


class ConfirmReq(BaseModel):
    confirmed: bool = True


@router.post("/{short_id}/keyframes/confirm")
async def confirm_keyframes(short_id: str, body: ConfirmReq | None = None):
    short = _get(short_id)
    short["keyframes_confirmed"] = (body.confirmed if body else True)
    store.save(short)
    return await state(short_id)


@router.post("/{short_id}/clips")
async def make_clips(short_id: str, body: ShotsReq | None = None):
    body = body or ShotsReq()
    short = _get(short_id)
    if short["pipeline"] == "remix":
        raise HTTPException(400, "use /remix/make for a remix")
    chk = checks.run(short)
    if not chk["ok"]:
        raise HTTPException(400, next(i["text"] for i in chk["issues"] if i["level"] == "block"))
    return _start(short_id, "short_clips", lambda progress: clips.make_clips(short_id, body.shot_ids, body.only_missing, progress))


@router.post("/{short_id}/final")
async def make_final(short_id: str):
    short = _get(short_id)

    async def work(progress):
        fn = remix.build if short["pipeline"] == "remix" else stitch.build
        await asyncio.to_thread(fn, short_id, lambda d, t, l="": progress(d, t, l))
        return "the short is put together"
    return _start(short_id, "short_final", work)


@router.post("/{short_id}/auto")
async def auto_run(short_id: str):
    _get(short_id)
    s, be = _backend()
    key = settings_mod.api_key()
    return _start(short_id, "short_auto", lambda progress: auto.run(short_id, be, s, progress, key))


@router.post("/item/{item_id}/approve")
async def approve(item_id: str, body: ConfirmReq | None = None):
    it = media.get(item_id)
    if not it or not it["plan_id"].startswith("sh-"):
        raise HTTPException(404, "no such item")
    media.approve(item_id, body.confirmed if body else True)
    return {"ok": True}


# ── remix ────────────────────────────────────────────────────────────────────

class RemixPatch(BaseModel):
    prompt: str | None = None
    motion_prompt: str | None = None
    pose_strength: float | None = None
    audio: str | None = None
    script: str | None = None
    rights_video: bool | None = None
    rights_character: bool | None = None
    character_id: str | None = None                 # a library character ("" = use the uploaded picture)
    look_id: str | None = None


@router.patch("/{short_id}/remix")
async def patch_remix(short_id: str, body: RemixPatch):
    short = _get(short_id)
    if short["pipeline"] != "remix":
        raise HTTPException(400, "this short is not a remix")
    p = body.model_dump(exclude_unset=True)
    if "audio" in p and p["audio"] not in remix.KEEP_AUDIO:
        raise HTTPException(400, f"audio is one of: {', '.join(remix.KEEP_AUDIO)}")
    if "pose_strength" in p and not 0 <= p["pose_strength"] <= 10:
        raise HTTPException(400, "pose strength is between 0 and 10")
    if p.get("character_id"):
        try:
            c = cstore.get(p["character_id"])
        except cstore.CharError as e:
            raise HTTPException(404, str(e))
        if c["kind"] != "person":
            raise HTTPException(400, "a place cannot be animated; choose a person")
        if p.get("look_id") and not any(x["id"] == p["look_id"] for x in c["looks"]):
            raise HTTPException(400, "this character has no such look")
    if "character_id" in p and not p["character_id"]:
        p["look_id"] = ""
    elif "character_id" in p and "look_id" not in p:
        p["look_id"] = ""
    r = remix.data(short)
    r.update(p)
    short["remix"] = r
    store.save(short)
    if "audio" in p or "script" in p:
        remix.sync_voiceover(short_id)
    return await state(short_id)


class FetchReq(BaseModel):
    url: str


@router.post("/{short_id}/remix/fetch")
async def remix_fetch(short_id: str, body: FetchReq):
    if _get(short_id)["pipeline"] != "remix":
        raise HTTPException(400, "this short is not a remix")
    _guard(remix.check_url, body.url)
    return _start(short_id, "short_fetch", lambda progress: remix.fetch_async(short_id, body.url, lambda d, t, l="": progress(d, t, l)))


@router.post("/{short_id}/remix/upload")
async def remix_upload(short_id: str, file: UploadFile = File(...)):
    """The fallback when a link cannot be fetched: the user's own copy of the video."""
    short = _get(short_id)
    if short["pipeline"] != "remix":
        raise HTTPException(400, "this short is not a remix")
    d = store.media_dir(short_id, "remix")
    path = d / "source.mp4"
    size = 0
    with open(path, "wb") as f:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_VIDEO_UPLOAD:
                f.close()
                path.unlink(missing_ok=True)
                raise HTTPException(400, "the video is over 400 MB")
            f.write(chunk)
    try:
        dur = frames.info(path)["duration_s"]
    except MediaError as e:
        path.unlink(missing_ok=True)
        raise HTTPException(400, str(e))
    if dur < remix.WINDOW_S:
        path.unlink(missing_ok=True)
        raise HTTPException(400, f"the video is {dur:.0f} seconds long; a short needs at least {remix.WINDOW_S:.0f}")
    cuts = await asyncio.to_thread(frames.scene_cuts, path, 0.3, remix.ANALYSE_S)
    r = remix.data(short)
    r.update(url="", info={"title": file.filename or "uploaded video", "duration_s": dur, "id": ""}, source="remix/source.mp4", cuts=cuts, suggest=remix.suggest_windows(cuts, dur), start=0.0, driving=[])
    short["remix"] = r
    store.save(short)
    return await state(short_id)


class WindowReq(BaseModel):
    start: float = 0.0
    fit: str = "crop"
    segments: int = 1


@router.post("/{short_id}/remix/window")
async def remix_window(short_id: str, body: WindowReq):
    if _get(short_id)["pipeline"] != "remix":
        raise HTTPException(400, "this short is not a remix")
    await asyncio.to_thread(_guard, remix.prepare, short_id, body.start, body.fit, body.segments)
    return await state(short_id)


@router.post("/{short_id}/remix/make")
async def remix_make(short_id: str):
    short = _get(short_id)
    if short["pipeline"] != "remix":
        raise HTTPException(400, "this short is not a remix")
    chk = remix.check(short)
    if chk["blockers"]:
        raise HTTPException(400, next(i["text"] for i in chk["issues"] if i["level"] == "block"))
    return _start(short_id, "short_animate", lambda progress: remix.make(short_id, progress))


# ── the library: cast, fixes, a character as the Remix picture ──────────────────────────────────

class FixReq(BaseModel):
    instruction: str


@router.post("/{short_id}/shots/{shot_id}/fix")
async def fix_picture(short_id: str, shot_id: str, body: FixReq):
    short = _get(short_id)
    sh = _guard(store.shot_by_id, short, shot_id)
    if not clips.chosen_keyframe(short, sh):
        raise HTTPException(400, "this shot has no start picture to change yet")
    if len(body.instruction.strip()) < 4:
        raise HTTPException(400, "say what to change")
    return _start(short_id, "short_fix", lambda progress: clips.fix_keyframe(short_id, shot_id, body.instruction, progress))


class AnchorFromChar(BaseModel):
    character_id: str
    view: str = "portrait"


@router.post("/{short_id}/images/anchor/character")
async def anchor_from_character(short_id: str, body: AnchorFromChar):
    """Use a library character's canon picture as the short's character picture (Remix needs one; the other pipelines use it for shots that show the main character)."""
    short = _get(short_id)
    try:
        c = cstore.get(body.character_id)
    except cstore.CharError as e:
        raise HTTPException(404, str(e))
    it = cstore.canon_items(c).get(body.view if body.view in ("portrait", "body") else "portrait")
    if not it:
        raise HTTPException(400, f"approve a {body.view} picture of {c['name']} in the Characters studio first")
    raw = media.path_of(it).read_bytes()
    rel = f"upload/anchor-{int(time.time())}.jpg"
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=94)
    (store.media_dir(short_id, "upload") / rel.split("/", 1)[1]).write_bytes(buf.getvalue())
    short["images"]["anchor"] = rel
    if short["settings"]["image_mode"] in ("wan", "qwen"):
        short["settings"]["image_mode"] = "anchor"
    store.save(short)
    return await state(short_id)
