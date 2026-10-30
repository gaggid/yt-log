"""HTTP API for the Character Studio (mounted under /api/characters). Same login as the rest of the app. Everything that talks to the gateway runs as the same one-at-a-time background job as
the other steps (story2/jobs.py), keyed by the character's id."""
import asyncio
import os

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from story import llm, settings as settings_mod
from story.pipeline import manager
from story2 import describe, jobs, providers, voices
from story3 import store as media
from story3.voice import MediaError

from . import avatar, choices, pack, check, edits, render, requests as R, store, studio, studio_edit, wardrobe

router = APIRouter(prefix="/api/characters")
MAX_UPLOAD = 12 * 1024 * 1024


def _get(char_id: str) -> dict:
    try:
        return store.get(char_id)
    except store.CharError as e:
        raise HTTPException(404, str(e))


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except (store.CharError, MediaError, ValueError) as e:
        raise HTTPException(400, str(e))


def _start(char_id: str, kind: str, work):
    _get(char_id)
    if manager.busy():
        raise HTTPException(409, "story processing is running; wait for it to finish (the model server answers one request at a time)")
    try:
        return jobs.start(char_id, kind, work)
    except jobs.JobBusy as e:
        raise HTTPException(409, str(e))


def _backend():
    s = settings_mod.get()
    return s, llm.ChatBackend(s, settings_mod.api_key())


def _thumb(char: dict) -> str:
    """The picture a card shows: the canon portrait (or place), else the newest finished candidate."""
    view = store.CANON_VIEWS[char["kind"]][0]
    it = store.canon_items(char).get(view)
    if not it:
        done = [i for i in media.items(char["id"], store.GEN, view) if i["status"] == "done" and i["file"]]
        it = done[-1] if done else None
    return f"/api/characters/file/{char['id']}/{it['file']}" if it else ""


def _view(char_id: str, it: dict, ident: str) -> dict:
    m = it["meta"]
    return {"id": it["id"], "view": it["key"], "attempt": it["attempt"], "status": it["status"], "approved": it["approved"], "error": m.get("error", ""),
            "url": f"/api/characters/file/{char_id}/{it['file']}" if it["file"] else "", "seed": m.get("seed"), "seconds_taken": m.get("seconds_taken"), "prompt": m.get("prompt", ""),
            "how": m.get("how", ""), "loras": m.get("loras", []), "model": m.get("model", ""), "style": m.get("style", ""), "version": m.get("version"), "current": m.get("identity_hash") == ident,
            "kind": it["kind"], "op": m.get("op", ""), "preset": m.get("preset", ""), "value": m.get("value", ""), "depth": m.get("depth", 0), "parent": m.get("parent", ""), "kept": bool(m.get("kept")),
            "check": m.get("check"), "refs": m.get("refs", [])}


def _look_thumb(char: dict, lk: dict) -> str:
    it = studio_edit.look_item(char, lk["id"])
    return f"/api/characters/file/{char['id']}/{it['file']}" if it else ""

def _card(c: dict) -> dict:
    return {"id": c["id"], "name": c["name"], "kind": c["kind"], "status": c["status"], "tags": c["tags"], "version": c["version"], "thumb": _thumb(c), "style": c["render"]["style"],
            "looks": [{"id": x["id"], "name": x["name"], "thumb": _look_thumb(c, x)} for x in c["looks"]],
            "updated_at": c["updated_at"]}


# ── options ──────────────────────────────────────────────────────────────────

@router.get("/options")
async def options():
    s = settings_mod.get()
    await asyncio.to_thread(providers.refresh, s, settings_mod.api_key())
    models = {k: {"label": v["label"], "edits": v["edits"], "licence": v["licence"]["status"], "negative_prompt": v["negative_prompt"]} for k, v in providers.PROVIDERS.items() if v.get("workflow") != "turbo"}
    loras = {}
    for m in models:
        listing = await asyncio.to_thread(studio.lora_listing, m)
        loras[m] = [{"name": n, "strength": listing[n].get("strength", 1.0), "trigger": listing[n].get("trigger", ""), "description": listing[n].get("description", ""),
                     "default": n in (listing.get("__default__") or {}).get("names", [])} for n in studio.lora_names(listing)]
    return {"styles": {k: {"label": v["label"], "loras": v["loras"]} for k, v in render.STYLES.items()}, "default_render": render.default(), "models": models, "loras": loras,
            "views": {k: {"label": v["label"], "how": v["how"], "kind": v["kind"]} for k, v in R.VIEWS.items()}, "sheet_views": list(R.SHEET_VIEWS), "rights": list(store.RIGHTS),
            "slots": {k: [{"key": a, "hint": b} for a, b in describe.SLOTS[k]] for k in store.KINDS}, "presets": list(edits.PRESETS), "scopes": edits.GARMENT_SCOPES,
            "expressions": list(R.EXPRESSIONS), "check_pass_at": check.PASS_AT, "declared": {k: [{"key": x, "label": store.DECLARED_LABEL[x]} for x in v] for k, v in store.DECLARED.items()}, "choices": choices.CHOICES, "styling": choices.STYLING, "outfits": choices.OUTFITS}


# ── wardrobe (garment pictures, reusable on any character) ──────────────────────────────────

@router.get("/wardrobe")
async def wardrobe_list():
    return wardrobe.listing()


@router.post("/wardrobe")
async def wardrobe_add(file: UploadFile = File(...), name: str = Form(""), basis: str = Form(""), confirmed: bool = Form(False), worn: bool = Form(False), tags: str = Form("")):
    if basis not in store.RIGHTS or not confirmed:
        raise HTTPException(400, "confirm that the picture is yours, licensed, or of an invented outfit")
    raw = await file.read()
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(400, "the picture is over 12 MB")
    try:
        return wardrobe.add(raw, name, basis, tags.split(","), worn)
    except store.CharError as e:
        raise HTTPException(400, str(e))
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "that file is not a picture the app can read (PNG, JPEG or WebP)")


@router.delete("/wardrobe/{garment_id}")
async def wardrobe_delete(garment_id: str):
    _guard(wardrobe.delete, garment_id)
    return {"ok": True}


@router.get("/wardrobe/file/{name:path}")
async def wardrobe_file(name: str):
    root = store.media_dir(wardrobe.OWNER).resolve()
    f = (root / name).resolve()
    if root not in f.parents or not f.is_file():
        raise HTTPException(404, "file not found")
    return FileResponse(f)


@router.post("/wardrobe/{garment_id}/flatlay")
async def wardrobe_flatlay(garment_id: str):
    _guard(wardrobe.get, garment_id)
    if manager.busy():
        raise HTTPException(409, "story processing is running; wait for it to finish (the model server answers one request at a time)")
    s, key = settings_mod.get(), settings_mod.api_key()
    try:
        return jobs.start("wardrobe", "char_flatlay", lambda progress: studio_edit.make_flatlay(garment_id, progress, s, key))
    except jobs.JobBusy as e:
        raise HTTPException(409, str(e))


@router.get("/wardrobe/job")
async def wardrobe_job():
    return jobs.status("wardrobe")


@router.post("/import")
async def import_pack(file: UploadFile = File(...)):
    raw = await file.read()
    if len(raw) > 400 * 1024 * 1024:
        raise HTTPException(400, "the pack is over 400 MB")
    c = _guard(pack.import_pack, raw)
    return await state(c["id"])


# ── library ──────────────────────────────────────────────────────────────────

@router.get("")
async def list_all(kind: str = ""):
    return [_card(c) for c in store.listing(kind)]


class CreateReq(BaseModel):
    name: str = ""
    kind: str = "person"
    idea: str = ""
    slots: dict | None = None
    personality: str = ""
    tags: list[str] = []
    render: dict | None = None
    declared: dict | None = None
    styling: str = ""


def _styling(value: str) -> str:
    if value not in {x["id"] for x in choices.STYLING}:
        raise HTTPException(400, "styling is: " + ", ".join(x["id"] or "everyday" for x in choices.STYLING))
    return value


@router.post("")
async def create(body: CreateReq):
    extra = {"idea": body.idea.strip(), "personality": body.personality.strip(), "tags": [t.strip() for t in body.tags if t.strip()],
             "declared": _guard(store.clean_declared, body.kind if body.kind in store.KINDS else "person", body.declared)}
    if body.render:
        extra["render"] = body.render
    if body.styling:
        extra["styling"] = _styling(body.styling)
    c = _guard(store.create, body.name.strip() or "Untitled", body.kind, body.slots, extra)
    if c["styling"] and store.glamour_problem(c):
        why = store.glamour_problem(c)
        store.delete(c["id"])
        raise HTTPException(400, why)
    return await state(c["id"])


@router.post("/{char_id}/duplicate")
async def duplicate(char_id: str, name: str = ""):
    _get(char_id)
    return await state(_guard(studio.duplicate, char_id, name)["id"])


@router.delete("/{char_id}")
async def delete(char_id: str):
    _get(char_id)
    if jobs.busy() and jobs.status(char_id).get("state") == "running":
        raise HTTPException(409, "a job is running for this character; stop it first")
    store.delete(char_id)
    return {"ok": True}


@router.get("/file/{char_id}/{name:path}")
async def file(char_id: str, name: str):
    root = store.media_dir(char_id).resolve()
    f = (root / name).resolve()
    if root not in f.parents or not f.is_file():
        raise HTTPException(404, "file not found")
    return FileResponse(f)


@router.get("/{char_id}/job")
async def job(char_id: str):
    return jobs.status(char_id)


@router.post("/{char_id}/cancel")
async def cancel(char_id: str):
    return {"cancelled": jobs.cancel(char_id)}


# ── one character ────────────────────────────────────────────────────────────

@router.get("/{char_id}")
async def state(char_id: str):
    c = _get(char_id)
    ident = store.identity_hash(c)
    gallery: dict[str, list] = {}
    for kind in (store.GEN, store.SHEET, store.EDIT):
        for it in media.items(char_id, kind):
            gallery.setdefault(it["key"], []).append(_view(char_id, it, ident))
    views = [v for v, spec in R.VIEWS.items() if spec["kind"] == c["kind"]]
    av_look_id = (c.get("avatar") or {}).get("look_id", "")
    av_look_it = studio_edit.look_item(c, av_look_id) if av_look_id else None
    av_picture_url = f"/api/characters/file/{char_id}/{av_look_it['file']}" if av_look_it else (_thumb(c) if store.canon_items(c).get("portrait") else "")
    return {**_card(c), "idea": c["idea"], "slots": c["slots"], "personality": c["personality"], "styling": c.get("styling", ""), "avatar": {"voice": avatar.voice_of(c), "ready": avatar.ready_state(c), "look_id": av_look_id, "picture_url": av_picture_url, "clip": next((f"/api/characters/file/{char_id}/{i['file']}" for i in reversed(media.items(char_id, avatar.KIND)) if i["status"] == "done" and i["file"]), "")}, "glamour_problem": store.glamour_problem(c) if c["kind"] == "person" else "", "notes": c["notes"], "render": c["render"], "locked": store.locked(c), "canon": c["canon"],
            "rights": c["rights"], "photo": f"/api/characters/file/{char_id}/{c['source_photo']}" if store.photo_path(c) else "", "gaps": describe.missing(c["kind"] if c["kind"] != "person" else "person", c["slots"]),
            "identity": R.identity_text(c), "declared": c.get("declared", {}), "declared_keys": [{"key": k, "label": store.DECLARED_LABEL[k]} for k in store.DECLARED[c["kind"]]], "looks": [{**x, "stale": x["version"] != c["version"]} for x in c["looks"]], "recipes": c.get("recipes", []), "gallery": gallery, "views": views, "job": jobs.status(char_id), "identity_hash": ident,
            "estimate_s": {"draw": 70, "edit": 110}}


class PatchReq(BaseModel):
    name: str | None = None
    idea: str | None = None
    slots: dict | None = None
    personality: str | None = None
    notes: str | None = None
    tags: list[str] | None = None
    render: dict | None = None
    declared: dict | None = None
    styling: str | None = None


@router.patch("/{char_id}")
async def patch(char_id: str, body: PatchReq):
    c = _get(char_id)
    p = body.model_dump(exclude_unset=True)
    if "render" in p:
        new = render.clean(p.pop("render"))
        if new != c["render"]:
            if store.locked(c):
                raise HTTPException(400, "the look is locked once a canon picture is approved (the same prompt in another style or with other LoRAs draws a different person). Duplicate the character to start with another look")
            listing = await asyncio.to_thread(studio.lora_listing, new["model"])
            bad = [x["name"] for x in new["loras"] if listing and x["name"] not in studio.lora_names(listing)]
            if bad:
                raise HTTPException(400, f"the gateway does not list the LoRA {', '.join(bad)} for {new['model']}")
            c["render"] = new
    if "slots" in p:
        old = c["slots"]
        c["slots"] = describe.clean(p.pop("slots"))
        if c["slots"] != old and store.locked(c):
            c["version"] += 0                       # a changed description is kept; pictures drawn from the old one show as 'older' until a new canon is approved
    if "declared" in p:
        c["declared"] = _guard(store.clean_declared, c["kind"], p.pop("declared"))
        if c["declared"]:
            c["slots"] = store.apply_declared(c)
    if "styling" in p and p["styling"] is not None:
        c["styling"] = _styling(p.pop("styling"))
    if c.get("styling") == "glamour" and store.glamour_problem(c):
        raise HTTPException(400, store.glamour_problem(c))
    for k in ("name", "idea", "personality", "notes"):
        if k in p and p[k] is not None:
            c[k] = p[k].strip() if k == "name" else p[k]
    if "tags" in p and p["tags"] is not None:
        c["tags"] = [t.strip() for t in p["tags"] if t.strip()]
    store.save(c)
    return await state(char_id)


class SuggestReq(BaseModel):
    idea: str = ""
    keep: bool = True                  # keep every detail the person already chose or typed, and write only the empty ones; false writes all again (the declared facts always stay)


@router.post("/{char_id}/suggest")
async def suggest(char_id: str, body: SuggestReq):
    c = _get(char_id)
    idea = (body.idea or c["idea"]).strip()
    if len(idea) < 5:
        raise HTTPException(400, "write the idea in a sentence first")
    gaps = store.missing_declared(c)
    if gaps:
        raise HTTPException(400, "say these first, they are decided by you and never invented: " + ", ".join(store.DECLARED_LABEL[k] for k in gaps))
    if jobs.busy() or manager.busy():
        raise HTTPException(409, "the model server is busy with another job; try again when it finishes")
    s, be = _backend()
    try:
        out = await studio.suggest_slots(idea, c["kind"], be, s, c["slots"] if body.keep else None, c["declared"], c.get("styling", "") if not store.glamour_problem(c) else "")
    except (llm.LLMError, MediaError, ValueError) as e:
        raise HTTPException(400, f"the slots could not be written: {e}")
    c["idea"], c["slots"] = idea, out["slots"]
    if out["personality"] and not c["personality"]:
        c["personality"] = out["personality"]
    if out["name"] and c["name"] in ("", "Untitled"):
        c["name"] = out["name"]
    store.save(c)
    return await state(char_id)


class AvatarReq(BaseModel):
    voice: dict | None = None                    # {"engine", "voice"}; {} = the app's default voice
    look_id: str | None = None                   # a saved look to use instead of the canon portrait; "" clears it


@router.patch("/{char_id}/avatar")
async def avatar_patch(char_id: str, body: AvatarReq):
    c = _get(char_id)
    if c["kind"] != "person":
        raise HTTPException(400, "only a person can talk")
    p = body.model_dump(exclude_unset=True)
    if "voice" in p:
        v = p["voice"] or {}
        if v:
            try:
                v = voices.choose({}, v.get("engine", ""), v.get("voice"))["tts"]
            except ValueError as e:
                raise HTTPException(400, str(e))
        c["avatar"] = {**(c.get("avatar") or {}), "voice": v}
    if "look_id" in p:
        lid = (p["look_id"] or "").strip()
        if lid and not studio_edit.look_item(c, lid):
            raise HTTPException(400, "that look has no approved picture; approve the picture first or choose another look")
        av = dict(c.get("avatar") or {})
        if av.get("look_id", "") != lid:
            av["look_id"] = lid
            av.pop("ready", None)          # changing the picture invalidates the old test result
            c["avatar"] = av
        else:
            c["avatar"] = {**av, "look_id": lid}
    store.save(c)
    return await state(char_id)


@router.post("/{char_id}/avatar/test")
async def avatar_test(char_id: str):
    """The ready test: a 3-second talking clip with the avatar's voice, judged on mouth, hands and identity. Takes minutes on the gateway."""
    c = _get(char_id)
    if c["kind"] != "person":
        raise HTTPException(400, "only a person can talk")
    look_id = (c.get("avatar") or {}).get("look_id", "")
    if look_id:
        if not studio_edit.look_item(c, look_id):
            raise HTTPException(400, "the selected look has no approved picture; choose another look or clear it")
    elif not store.canon_items(c).get("portrait"):
        raise HTTPException(400, "approve a portrait first (or save a look and pick it as the avatar picture)")
    s, key = settings_mod.get(), settings_mod.api_key()
    return _start(char_id, "char_avatar", lambda progress: avatar.run_test(char_id, progress, s, key))


@router.post("/{char_id}/read-detail")
async def read_detail(char_id: str, file: UploadFile = File(...), aspect: str = Form(...)):
    """Read one detail (hair, outfit, accessories, face, expression) of a reference picture into the character's text slots. The picture is not kept: only the words are, and they can be edited."""
    c = _get(char_id)
    if c["kind"] != "person":
        raise HTTPException(400, "details can only be read for a person")
    if aspect not in studio.ASPECTS:
        raise HTTPException(400, f"aspect is one of: {', '.join(studio.ASPECTS)}")
    raw = await file.read()
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(400, "the picture is over 12 MB")
    if jobs.busy() or manager.busy():
        raise HTTPException(409, "the model server is busy with another job; try again when it finishes")
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as t:
        t.write(raw)
    try:
        got = await studio.read_aspect(t.name, aspect)
    except (MediaError, ValueError, OSError) as e:
        raise HTTPException(400, str(e))
    finally:
        os.unlink(t.name)
    c["slots"] = {**c["slots"], **got["slots"]}
    store.save(c)
    return {**(await state(char_id)), "read": got}


@router.post("/{char_id}/photo")
async def photo(char_id: str, file: UploadFile = File(...), basis: str = Form(""), confirmed: bool = Form(False), read: bool = Form(True)):
    c = _get(char_id)
    if c["kind"] != "person":
        raise HTTPException(400, "a picture can only start a person")
    if basis not in store.RIGHTS or not confirmed:
        raise HTTPException(400, "confirm that the picture is yours, that the person agreed, or that it is licensed or an invented character")
    raw = await file.read()
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(400, "the picture is over 12 MB")
    try:
        rel = studio.save_photo(char_id, raw)
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "that file is not a picture the app can read (PNG, JPEG or WebP)")
    if store.locked(c):
        raise HTTPException(400, "this character already has a canon; duplicate it to start from another picture")
    c["source_photo"], c["rights"] = rel, {"basis": basis, "confirmed": True, "note": ""}
    if read:
        try:
            got = await studio.read_photo(store.media_dir(char_id) / rel)
            c["slots"] = {**got["slots"], **{k: v for k, v in c["slots"].items() if v}} if c["slots"] else got["slots"]
            c["personality"] = c["personality"] or got["personality"]
        except (MediaError, ValueError) as e:
            raise HTTPException(400, str(e))
    store.save(c)
    return await state(char_id)


class GenerateReq(BaseModel):
    views: list[str] = ["portrait"]
    n: int = 2
    seed: int | None = None
    extra: str = ""
    body_ref: str = ""
    custom_prompt: str = ""


@router.post("/{char_id}/generate/preview")
async def generate_preview(char_id: str, body: GenerateReq):
    """Return the prompt that would be sent, without generating. Used by the UI to let the user edit before confirming."""
    c = _get(char_id)
    for v in body.views:
        if v not in R.VIEWS or R.VIEWS[v]["kind"] != c["kind"]:
            raise HTTPException(400, f"'{v}' is not a view of a {c['kind']}")
    s = settings_mod.get()
    key = settings_mod.api_key()
    listing = studio.lora_listing(c["render"]["model"], s, key) if c["render"]["loras"] else {}
    ref_item = media.get(body.body_ref) if body.body_ref and "body" in body.views else None
    req = R.build(c, body.views[0], 1, listing, extra=body.extra, ref_item=ref_item)
    return {"prompt": req["body"]["prompt"], "how": req["how"], "model": req["body"]["model"]}


@router.post("/{char_id}/generate")
async def generate(char_id: str, body: GenerateReq):
    c = _get(char_id)
    for v in body.views:
        if v not in R.VIEWS or R.VIEWS[v]["kind"] != c["kind"]:
            raise HTTPException(400, f"'{v}' is not a view of a {c['kind']}")
    if not 1 <= body.n <= 8:
        raise HTTPException(400, "n is between 1 and 8")
    gaps = describe.missing(c["kind"], c["slots"])
    if gaps:
        raise HTTPException(400, "fill in these details first (an image model invents what is not written): " + ", ".join(gaps))
    s = settings_mod.get()
    key = settings_mod.api_key()
    body_ref = body.body_ref
    custom_prompt = body.custom_prompt
    return _start(char_id, "char_generate", lambda progress: studio.make_views(char_id, body.views, body.n, progress, s, key, body.seed, body.extra, body_ref, custom_prompt))


@router.post("/{char_id}/sheet")
async def sheet(char_id: str):
    c = _get(char_id)
    if c["kind"] != "person":
        raise HTTPException(400, "only a person has a sheet")
    have = store.canon_items(c)
    if "portrait" not in have or "body" not in have:
        raise HTTPException(400, "approve a portrait and a full-body picture first: the sheet is made from them")
    s = settings_mod.get()
    key = settings_mod.api_key()
    return _start(char_id, "char_sheet", lambda progress: studio.make_views(char_id, list(R.SHEET_VIEWS), 1, progress, s, key))


@router.post("/item/{item_id}/canon")
async def canon(item_id: str):
    it = media.get(item_id)
    if not it:
        raise HTTPException(404, "no such picture")
    _get(it["plan_id"])
    _guard(studio.set_canon, it["plan_id"], item_id)
    return await state(it["plan_id"])


@router.delete("/{char_id}/canon/{view}")
async def un_canon(char_id: str, view: str):
    _get(char_id)
    _guard(studio.clear_canon, char_id, view)
    return await state(char_id)


# ── edits, try-on, places, checks, looks (C2, C3) ───────────────────────────────────────────

class EditReq(BaseModel):
    base: str
    preset: str = "custom"
    value: str = ""
    extra: list[str] = []
    garment: str = ""
    scope: str = "outfit"
    n: int = 1
    prompt: str = ""                    # the person's own full instruction (power users): replaces the built one
    lora: list[dict] | None = None      # optional [{name, strength}]; when given the LoRA is sent with the edit request


def _edit_args(c: dict, body: EditReq) -> dict:
    if not 1 <= body.n <= 4:
        raise HTTPException(400, "n is between 1 and 4")
    base = _guard(studio_edit._item, c["id"], body.base)
    extra = [_guard(studio_edit._item, c["id"], x) for x in body.extra]
    garment = _guard(wardrobe.usable, body.garment) if body.garment else None
    return {"base": base, "extra": extra, "garment": garment}


def _clean_lora(lora: list[dict] | None, model: str) -> list[dict] | None:
    if not lora:
        return None
    listing = studio.lora_listing(model)
    known = studio.lora_names(listing)
    bad = [x["name"] for x in lora if x.get("name") and known and x["name"] not in known]
    if bad:
        raise HTTPException(400, f"the gateway does not list the LoRA {', '.join(bad)} for {model}")
    return [{"name": x["name"], "strength": float(x.get("strength", 1.0))} for x in lora if x.get("name")]


@router.post("/{char_id}/upload-ref")
async def upload_ref(char_id: str, file: UploadFile):
    """Store an external photo as a reference picture for this character's edits."""
    import time
    from pathlib import Path
    _get(char_id)
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "file too large")
    ext = (Path(file.filename or "ref.jpg").suffix.lower() or ".jpg").lstrip(".")
    if ext not in ("jpg", "jpeg", "png", "webp"):
        raise HTTPException(400, "jpeg, png or webp only")
    ref_dir = store.media_dir(char_id, "refs")
    fname = f"ref-{int(time.time() * 1000)}.{ext}"
    (ref_dir / fname).write_bytes(data)
    it = media.add(char_id, "char_ref", "ref", 0, "done", {})
    media.update(it["id"], file=f"refs/{fname}")
    return {"id": it["id"], "url": f"/api/characters/file/{char_id}/refs/{fname}"}


@router.post("/{char_id}/edit/preview")
async def edit_preview(char_id: str, body: EditReq):
    """What would be sent, without sending it: the prompt, the pictures in order, the size, and the LoRAs (the prompt drawer)."""
    c = _get(char_id)
    a = _edit_args(c, body)
    lo = _clean_lora(body.lora, c["render"]["model"])
    req = _guard(edits.build, c, a["base"], body.preset, body.value, 1, a["extra"], a["garment"]["path"] if a["garment"] else None, body.scope if a["garment"] else "",
                 override=body.prompt, garment_worn=bool(a["garment"] and a["garment"]["worn"]), lora=lo)
    return {"prompt": req["body"]["prompt"], "refs": req["ref_ids"], "size": req["body"]["size"], "model": req["body"]["model"], "depth": req["meta"]["depth"], "loras": req["meta"]["loras"]}


@router.post("/{char_id}/edit")
async def edit(char_id: str, body: EditReq):
    c = _get(char_id)
    a = _edit_args(c, body)
    lo = _clean_lora(body.lora, c["render"]["model"])
    _guard(edits.build, c, a["base"], body.preset, body.value, 1, a["extra"], a["garment"]["path"] if a["garment"] else None, body.scope if a["garment"] else "",
           override=body.prompt, garment_worn=bool(a["garment"] and a["garment"]["worn"]), lora=lo)   # refuse a bad request before the job starts
    s, key = settings_mod.get(), settings_mod.api_key()
    return _start(char_id, "char_edit", lambda progress: studio_edit.make_edit(char_id, body.base, body.preset, body.value, body.extra, body.garment, body.scope, body.n, body.prompt, progress, s, key, lora=lo))


class PlaceReq(BaseModel):
    place: str
    action: str = ""
    base: str = ""
    n: int = 1
    prompt: str = ""


@router.post("/{char_id}/place")
async def place_character(char_id: str, body: PlaceReq):
    c = _get(char_id)
    if c["kind"] != "person":
        raise HTTPException(400, "only a person can be placed in a place")
    if not 1 <= body.n <= 4:
        raise HTTPException(400, "n is between 1 and 4")
    pl = _guard(studio_edit.place_picture, body.place)
    if body.base:
        _guard(studio_edit._item, char_id, body.base)
    _guard(edits.build_place, c, pl, body.action, 1, None, override=body.prompt)
    s, key = settings_mod.get(), settings_mod.api_key()
    return _start(char_id, "char_place", lambda progress: studio_edit.make_place(char_id, body.place, body.action, body.base, body.n, body.prompt, progress, s, key))


@router.post("/item/{item_id}/check")
async def check_picture(item_id: str):
    it = media.get(item_id)
    if not it:
        raise HTTPException(404, "no such picture")
    c = _get(it["plan_id"])
    if jobs.busy() or manager.busy():
        raise HTTPException(409, "the model server is busy with another job; try again when it finishes")
    try:
        await studio_edit.check_item(c["id"], item_id)
    except (MediaError, store.CharError, ValueError) as e:
        raise HTTPException(400, str(e))
    return await state(c["id"])


@router.post("/item/{item_id}/keep")
async def keep_picture(item_id: str, on: bool = True):
    it = media.get(item_id)
    if not it:
        raise HTTPException(404, "no such picture")
    _get(it["plan_id"])
    _guard(studio_edit.keep, it["plan_id"], item_id, on)
    return await state(it["plan_id"])


@router.post("/item/{item_id}/retry")
async def retry_item(item_id: str):
    """Re-run a failed generate or edit attempt with the same parameters."""
    it = media.get(item_id)
    if not it:
        raise HTTPException(404, "no such picture")
    if it["status"] != "failed":
        raise HTTPException(400, "only failed items can be retried")
    char_id = it["plan_id"]
    _get(char_id)
    m = it["meta"]
    s, key = settings_mod.get(), settings_mod.api_key()
    if it["kind"] == store.GEN:
        return _start(char_id, "char_generate", lambda p: studio.make_views(char_id, [it["key"]], 1, p, s, key))
    if it["kind"] == store.EDIT:
        if m.get("op") == "tryon":
            raise HTTPException(400, "try-on retry: use the Edit section and choose the garment again")
        refs = m.get("refs", [])
        base_id = refs[0] if refs else m.get("parent", "")
        extra_ids = [x for x in refs[1:] if x != "garment"]
        return _start(char_id, "char_edit", lambda p: studio_edit.make_edit(
            char_id, base_id, m.get("preset", "custom"), m.get("value", ""),
            extra_ids, "", "", 1, m.get("prompt", ""), p, s, key))
    raise HTTPException(400, "this kind of item cannot be retried automatically")


@router.delete("/item/{item_id}")
async def delete_picture(item_id: str):
    """Delete one picture and free its file from disk. Refused if the picture is a canon or referenced by a saved look."""
    it = media.get(item_id)
    if not it:
        raise HTTPException(404, "no such picture")
    c = _get(it["plan_id"])
    if item_id in store.canon_items(c).values():
        raise HTTPException(400, "this picture is the canon for its view; un-canon it first before deleting")
    look_items = {lk["item"] for lk in c["looks"]}
    if item_id in look_items:
        raise HTTPException(400, "this picture is used by a saved look; delete the look first")
    av_look_id = (c.get("avatar") or {}).get("look_id", "")
    if av_look_id and studio_edit.look_item(c, av_look_id) and studio_edit.look_item(c, av_look_id)["id"] == item_id:
        raise HTTPException(400, "this picture is set as the avatar picture; change the avatar picture first")
    if it["status"] == "running":
        raise HTTPException(409, "this picture is still being generated; cancel the job first")
    media.delete(item_id)
    return await state(it["plan_id"])


class LookReq(BaseModel):
    name: str = ""


@router.post("/item/{item_id}/look")
async def save_look(item_id: str, body: LookReq):
    it = media.get(item_id)
    if not it:
        raise HTTPException(404, "no such picture")
    _get(it["plan_id"])
    _guard(studio_edit.save_look, it["plan_id"], item_id, body.name)
    return await state(it["plan_id"])


@router.delete("/{char_id}/looks/{look_id}")
async def delete_look(char_id: str, look_id: str):
    _get(char_id)
    _guard(studio_edit.delete_look, char_id, look_id)
    return await state(char_id)


@router.post("/item/{item_id}/canon/{view}")
async def promote(item_id: str, view: str):
    it = media.get(item_id)
    if not it:
        raise HTTPException(404, "no such picture")
    _get(it["plan_id"])
    _guard(studio_edit.set_canon_view, it["plan_id"], item_id, view)
    return await state(it["plan_id"])


class MatrixReq(BaseModel):
    looks: list[str] = []
    expressions: list[str] = ["smile", "angry", "worried"]


@router.post("/{char_id}/matrix")
async def matrix(char_id: str, body: MatrixReq):
    c = _get(char_id)
    if not store.canon_items(c).get("portrait"):
        raise HTTPException(400, "approve a portrait first")
    s, key = settings_mod.get(), settings_mod.api_key()
    if not body.expressions:
        raise HTTPException(400, "choose at least one expression")
    return _start(char_id, "char_matrix", lambda progress: studio_edit.make_matrix(char_id, body.looks, body.expressions, progress, s, key))


class RecipesReq(BaseModel):
    recipes: list[dict]


@router.put("/{char_id}/recipes")
async def recipes(char_id: str, body: RecipesReq):
    c = _get(char_id)
    c["recipes"] = [{"name": str(r.get("name", "")).strip()[:60], "preset": str(r.get("preset", "custom")), "value": str(r.get("value", ""))[:600]} for r in body.recipes if str(r.get("name", "")).strip()][:40]
    store.save(c)
    return await state(char_id)


@router.get("/{char_id}/pack")
async def export_pack(char_id: str):
    c = _get(char_id)
    name = "".join(ch if ch.isalnum() else "-" for ch in c["name"]).strip("-") or "character"
    return Response(pack.export(char_id), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}.character.zip"'})
