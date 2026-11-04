"""HTTP API for the Character Studio (mounted under /api/characters). Same login as the rest of the app. Everything that talks to the gateway runs as the same one-at-a-time background job as
the other steps (story2/jobs.py), keyed by the character's id."""
import asyncio
import os

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from story import db, llm, settings as settings_mod
from story.pipeline import manager
from story2 import describe, jobs, providers, voices
from story3 import store as media
from story3.voice import MediaError

from . import avatar, brain as brain_mod, choices, goals as goals_mod, interests as interests_mod, memory as memory_mod, pack, check, edits, profile as profile_mod, render, requests as R, store, studio, studio_edit, wardrobe

router = APIRouter(prefix="/api/characters")
NO_CACHE = {"Cache-Control": "no-cache"}               # the browser asks again every time (cheap: 304 when the file is unchanged)
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
    return FileResponse(f, headers=NO_CACHE)           # a deleted attempt's number is used again, so the same URL can hold a new picture


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


@router.post("/wardrobe/generate/{char_id}")
async def wardrobe_generate(char_id: str, n: int = 8):
    """Generate n garment flat-lays for this character and save them to the wardrobe."""
    _get(char_id)
    s   = settings_mod.get()
    key = settings_mod.api_key()
    _n  = min(n, 15)
    from .wardrobe_gen import generate as _gen
    return jobs.start("wardrobe", f"Generating {_n} wardrobe items",
                      lambda progress: _gen(char_id, _n, s, key))


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
    return FileResponse(f, headers=NO_CACHE)           # a deleted attempt's number is used again, so the same URL can hold a new picture


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
            "estimate_s": {"draw": 70, "edit": 110}, "profile": profile_mod.get(c)}


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
    swap: str = ""                      # head-swap LoRA name (bfs-head-swap...): base = target photo, extra[0] = face source; no prompt is sent
    note: str = ""                      # with both: the text appended to the swap LoRA's own instruction (prompt then goes to the prompt-only version)
    both: bool = False                  # with swap and prompt: make the LoRA swap and the prompt-only version
    lora: list[dict] | None = None      # optional [{name, strength}]; when given the LoRA is sent with the edit request
    flatten: bool = False               # extra[0] shows the outfit on a person: make a flat lay of it first (outfit from a reference photo)


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
                 override=body.prompt, garment_worn=bool(a["garment"] and a["garment"]["worn"]), lora=lo, swap=body.swap)
    return {"prompt": req["body"]["prompt"], "refs": req["ref_ids"], "size": req["body"].get("size"), "model": req["body"]["model"], "depth": req["meta"]["depth"], "loras": req["meta"]["loras"]}


@router.post("/{char_id}/edit")
async def edit(char_id: str, body: EditReq):
    c = _get(char_id)
    a = _edit_args(c, body)
    lo = _clean_lora(body.lora, c["render"]["model"])
    _guard(edits.build, c, a["base"], body.preset, body.value, 1, a["extra"], a["garment"]["path"] if a["garment"] else None, body.scope if a["garment"] else "",
           override=body.prompt, garment_worn=bool(a["garment"] and a["garment"]["worn"]), lora=lo, swap=body.swap)   # refuse a bad request before the job starts
    s, key = settings_mod.get(), settings_mod.api_key()
    return _start(char_id, "char_edit", lambda progress: studio_edit.make_edit(char_id, body.base, body.preset, body.value, body.extra, body.garment, body.scope, body.n, body.prompt, progress, s, key, lora=lo, swap=body.swap, both=body.both, swap_note=body.note, flatten=body.flatten))


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


@router.post("/{char_id}/in-place")
async def in_place(char_id: str, action: str = Form(""), place_text: str = Form(""), base: str = Form(""),
                   n: int = Form(1), prompt: str = Form(""), place_image: UploadFile | None = File(None)):
    """Put the character in a place described by text, with an optional reference image — no place character needed."""
    import time as _time
    from pathlib import Path
    c = _get(char_id)
    if c["kind"] != "person":
        raise HTTPException(400, "only a person can be placed in a place")
    if not 1 <= n <= 4:
        raise HTTPException(400, "n is between 1 and 4")
    if not place_text.strip() and not (place_image and place_image.filename):
        raise HTTPException(400, "describe the setting or upload a reference image")
    place_image_path: str | None = None
    if place_image and place_image.filename:
        raw = await place_image.read()
        if len(raw) > MAX_UPLOAD:
            raise HTTPException(400, "the image is over 12 MB")
        ext = (place_image.filename.rsplit(".", 1)[-1] or "jpg").lower().replace("jpeg", "jpg")
        if ext not in ("jpg", "png", "webp"):
            raise HTTPException(400, "jpeg, png or webp only")
        ref_dir = store.media_dir(char_id, "place_refs")
        ref_dir.mkdir(parents=True, exist_ok=True)
        fname = f"place-{int(_time.time() * 1000)}.{ext}"
        (ref_dir / fname).write_bytes(raw)
        place_image_path = str(ref_dir / fname)
    if base:
        _guard(studio_edit._item, char_id, base)
    _guard(edits.build_in_place, c, action, place_text, place_image_path, 1)
    s, key = settings_mod.get(), settings_mod.api_key()
    _action, _place_text, _image_path = action, place_text, place_image_path
    return _start(char_id, "char_place",
                  lambda progress: studio_edit.make_in_place(char_id, _action, _place_text, _image_path, base, n, prompt, progress, s, key))


# ── virtual life: profile and life feed ──────────────────────────────────────

class ProfilePatch(BaseModel):
    core_character: str | None = None
    personality: str | None = None
    city: str | None = None
    phone: str | None = None
    fashion_taste: str | None = None
    interests: dict | None = None
    spaces: list | None = None
    current_context: str | None = None
    chronotype: str | None = None
    energy: int | None = None
    sleep_threshold: int | None = None
    life_enabled: bool | None = None
    life_interval_m: int | None = None
    auto_draw: bool | None = None
    shot_styles: list[str] | None = None


@router.get("/{char_id}/profile")
async def get_profile(char_id: str):
    c = _get(char_id)
    return profile_mod.get(c)


@router.patch("/{char_id}/profile")
async def patch_profile(char_id: str, body: ProfilePatch):
    c = _get(char_id)
    updates = body.model_dump(exclude_unset=True)
    if "shot_styles" in updates:
        ok = [x for x in brain_mod.SHOT_CATEGORIES if x in (updates["shot_styles"] or [])]
        if not ok:
            raise HTTPException(400, "pick at least one picture style")
        updates["shot_styles"] = ok
    profile_mod.patch(c, updates)
    store.save(c)
    return profile_mod.get(c)


@router.post("/{char_id}/spaces/{space_name}/ref")
async def upload_space_ref(char_id: str, space_name: str, file: UploadFile = File(...)):
    """Upload a reference photo for a declared space. Stored and injected as draw reference."""
    import time as _time
    from pathlib import Path
    c = _get(char_id)
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "file too large")
    ext = (Path(file.filename or "ref.jpg").suffix.lower() or ".jpg").lstrip(".")
    if ext not in ("jpg", "jpeg", "png", "webp"):
        raise HTTPException(400, "jpeg, png or webp only")
    space_dir = store.media_dir(char_id, "spaces")
    safe_name = space_name.lower().replace(" ", "_")
    fname = f"{safe_name}.{ext}"
    (space_dir / fname).write_bytes(data)
    rel = f"spaces/{fname}"
    # update the matching space entry in profile
    prof = profile_mod.get(c)
    spaces = prof.get("spaces") or []
    matched = False
    for s in spaces:
        if s.get("name", "").lower() == space_name.lower():
            s["ref_image"] = rel
            matched = True
            break
    if not matched:
        raise HTTPException(404, f"space '{space_name}' not in profile — add it first")
    profile_mod.patch(c, {"spaces": spaces})
    store.save(c)
    return {"space": space_name, "ref_image": rel,
            "url": f"/api/characters/file/{char_id}/{rel}"}


@router.delete("/{char_id}/spaces/{space_name}/ref")
async def delete_space_ref(char_id: str, space_name: str):
    """Remove the reference photo for a declared space."""
    c = _get(char_id)
    prof = profile_mod.get(c)
    spaces = prof.get("spaces") or []
    for s in spaces:
        if s.get("name", "").lower() == space_name.lower():
            s.pop("ref_image", None)
            profile_mod.patch(c, {"spaces": spaces})
            store.save(c)
            return {"ok": True}
    raise HTTPException(404, f"space '{space_name}' not found")


from . import spaces as spaces_mod  # noqa: E402


@router.get("/{char_id}/spaces/{space_name}/images")
async def list_space_images(char_id: str, space_name: str):
    _get(char_id)
    return spaces_mod.list_images(char_id, space_name)


class _SpaceGenReq(BaseModel):
    instruction: str = ""


@router.post("/{char_id}/spaces/{space_name}/generate")
async def generate_space_main(char_id: str, space_name: str, body: _SpaceGenReq = Body(default=None)):
    """Start a job to draw the main view of a space."""
    _get(char_id)
    s, _ = _backend()
    key  = settings_mod.api_key()
    instr = (body.instruction if body else "")

    async def work(progress):
        return await spaces_mod.generate_main(char_id, space_name, s, key, progress, instruction=instr)

    return _start(char_id, f"space-{space_name}-main", work)


@router.post("/{char_id}/spaces/{space_name}/corners")
async def generate_space_corners(char_id: str, space_name: str, body: _SpaceGenReq = Body(default=None)):
    """Start a job to draw 4 corner views. Requires an approved main view."""
    _get(char_id)
    s, _ = _backend()
    key  = settings_mod.api_key()
    instr = (body.instruction if body else "")

    async def work(progress):
        return await spaces_mod.generate_corners(char_id, space_name, s, key, progress, instruction=instr)

    return _start(char_id, f"space-{space_name}-corners", work)


@router.post("/{char_id}/spaces/{space_name}/images/{item_id}/approve")
async def approve_space_image(char_id: str, space_name: str, item_id: str):
    _get(char_id)
    return _guard(spaces_mod.approve_image, char_id, space_name, item_id)


@router.delete("/{char_id}/spaces/{space_name}/images/{item_id}")
async def delete_space_image(char_id: str, space_name: str, item_id: str):
    _get(char_id)
    from story3 import store as media_store
    it = media_store.get(item_id)
    if not it or it["plan_id"] != char_id:
        raise HTTPException(404, "image not found")
    media_store.delete(item_id)
    return {"deleted": item_id}


@router.get("/{char_id}/accessories")
async def get_accessories(char_id: str):
    c = _get(char_id)
    return profile_mod.get(c).get("accessories") or []


@router.post("/{char_id}/accessories")
async def add_accessory(char_id: str, name: str = Form(...), description: str = Form("")):
    """Add a recurring accessory (phone, bag, mug, etc.) to track as a draw reference."""
    c = _get(char_id)
    prof = profile_mod.get(c)
    accessories = list(prof.get("accessories") or [])
    if any(a["name"].lower() == name.lower() for a in accessories):
        raise HTTPException(409, "accessory already exists")
    accessories.append({"name": name.strip(), "description": description.strip(), "ref_image": None})
    profile_mod.patch(c, {"accessories": accessories})
    store.save(c)
    return accessories


@router.post("/{char_id}/accessories/{acc_name}/ref")
async def upload_accessory_ref(char_id: str, acc_name: str, file: UploadFile = File(...)):
    """Upload a reference photo for a recurring accessory."""
    from pathlib import Path
    c = _get(char_id)
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "file too large")
    ext = (Path(file.filename or "ref.jpg").suffix.lower() or ".jpg").lstrip(".")
    if ext not in ("jpg", "jpeg", "png", "webp"):
        raise HTTPException(400, "jpeg, png or webp only")
    acc_dir = store.media_dir(char_id, "accessories")
    safe_name = acc_name.lower().replace(" ", "_")
    fname = f"{safe_name}.{ext}"
    (acc_dir / fname).write_bytes(data)
    rel = f"accessories/{fname}"
    prof = profile_mod.get(c)
    accessories = list(prof.get("accessories") or [])
    matched = False
    for a in accessories:
        if a["name"].lower() == acc_name.lower():
            a["ref_image"] = rel
            matched = True
            break
    if not matched:
        raise HTTPException(404, f"accessory '{acc_name}' not found — add it first")
    profile_mod.patch(c, {"accessories": accessories})
    store.save(c)
    return {"accessory": acc_name, "ref_image": rel,
            "url": f"/api/characters/file/{char_id}/{rel}"}


@router.delete("/{char_id}/accessories/{acc_name}")
async def delete_accessory(char_id: str, acc_name: str):
    c = _get(char_id)
    prof = profile_mod.get(c)
    accessories = [a for a in (prof.get("accessories") or [])
                   if a["name"].lower() != acc_name.lower()]
    profile_mod.patch(c, {"accessories": accessories})
    store.save(c)
    return {"ok": True}


@router.get("/{char_id}/life")
async def life_feed(char_id: str, limit: int = 50, before: float | None = None):
    _get(char_id)
    return profile_mod.list_events(char_id, min(limit, 200), before=before)


@router.get("/{char_id}/life/day")
async def life_day(char_id: str, date: str):
    """All life events for a given date (YYYY-MM-DD) in the character's local timezone."""
    import datetime as _dt
    _get(char_id)
    try:
        d = _dt.date.fromisoformat(date)
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    start = _dt.datetime(d.year, d.month, d.day, 0, 0, 0).timestamp()
    end   = _dt.datetime(d.year, d.month, d.day, 23, 59, 59).timestamp()
    return profile_mod.list_events_range(char_id, start, end)


@router.delete("/{char_id}/life/{event_id}")
async def delete_life_event(char_id: str, event_id: str):
    _get(char_id)
    db.ex("DELETE FROM char_life_events WHERE id=? AND char_id=?", (event_id, char_id))
    return {"deleted": event_id}


# ── interest proposals ────────────────────────────────────────────────────────

@router.get("/{char_id}/interests/proposals")
async def list_interest_proposals(char_id: str):
    """Pending interest_proposal events not yet approved or dismissed."""
    _get(char_id)
    rows = db.q(
        "SELECT * FROM char_life_events WHERE char_id=? AND event_type='interest_proposal' "
        "AND (outputs NOT LIKE '%\"dismissed\"%') ORDER BY created_at DESC LIMIT 50",
        (char_id,),
    )
    return [{**r, "inputs": db.jload(r["inputs"], {}), "outputs": db.jload(r["outputs"], {})} for r in rows]


@router.post("/{char_id}/interests/proposals/{event_id}/approve")
async def approve_interest_proposal(char_id: str, event_id: str):
    """Add the proposed interest to the character's profile."""
    c = _get(char_id)
    ev = profile_mod.get_event(event_id)
    if not ev or ev["char_id"] != char_id or ev["event_type"] != "interest_proposal":
        raise HTTPException(404, "no such proposal")
    name = ev["outputs"].get("name", "")
    category = ev["outputs"].get("category", "")
    if not name:
        raise HTTPException(400, "proposal has no name")
    interests_mod.add_character_interest(c, name, category)
    store.save(c)
    # mark dismissed so it won't re-appear
    db.ex(
        "UPDATE char_life_events SET outputs=json_set(outputs,'$.approved',1) WHERE id=?",
        (event_id,),
    )
    return {"approved": name}


@router.post("/{char_id}/interests/proposals/{event_id}/dismiss")
async def dismiss_interest_proposal(char_id: str, event_id: str):
    _get(char_id)
    db.ex(
        "UPDATE char_life_events SET outputs=json_set(outputs,'$.dismissed',1) WHERE id=?",
        (event_id,),
    )
    return {"dismissed": event_id}


# ── aspirations ───────────────────────────────────────────────────────────────

@router.get("/{char_id}/aspirations")
async def list_aspirations(char_id: str):
    c = _get(char_id)
    prof = profile_mod.get(c)
    return prof.get("aspirations") or []


@router.delete("/{char_id}/aspirations/{aspiration_id}")
async def delete_aspiration(char_id: str, aspiration_id: str):
    c = _get(char_id)
    prof = profile_mod.get(c)
    aspirations = [a for a in (prof.get("aspirations") or []) if a["id"] != aspiration_id]
    profile_mod.patch(c, {"aspirations": aspirations})
    store.save(c)
    return {"deleted": aspiration_id}


# ── goals ─────────────────────────────────────────────────────────────────────

class GoalReq(BaseModel):
    title: str
    category: str = "personal"
    description: str = ""


class GoalPatch(BaseModel):
    title: str | None = None
    category: str | None = None
    description: str | None = None
    status: str | None = None
    progress_note: str | None = None   # appended to progress_notes list


@router.get("/{char_id}/goals")
async def list_goals(char_id: str):
    c = _get(char_id)
    return goals_mod.list_goals(c)


@router.post("/{char_id}/goals")
async def add_goal(char_id: str, body: GoalReq):
    c = _get(char_id)
    try:
        return _guard(goals_mod.add_goal, c, body.title, body.category, body.description)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.patch("/{char_id}/goals/{goal_id}")
async def update_goal(char_id: str, goal_id: str, body: GoalPatch):
    c = _get(char_id)
    updates = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if "progress_note" in updates:
        updates["progress_notes"] = updates.pop("progress_note")
    try:
        return goals_mod.update_goal(c, goal_id, **updates)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.delete("/{char_id}/goals/{goal_id}")
async def delete_goal(char_id: str, goal_id: str):
    c = _get(char_id)
    _guard(goals_mod.delete_goal, c, goal_id)
    return {"ok": True}


# ── memories ───────────────────────────────────────────────────────────────────

class MemoryReq(BaseModel):
    content: str
    tags: list[str] = []


@router.get("/{char_id}/memories")
async def list_memories(char_id: str, limit: int = 40, category: str | None = None):
    _get(char_id)
    return memory_mod.list_memories(char_id, min(limit, 100), category=category)


@router.post("/{char_id}/memories")
async def add_memory(char_id: str, body: MemoryReq):
    _get(char_id)
    if not body.content.strip():
        raise HTTPException(400, "content required")
    return memory_mod.add_manual(char_id, body.content, body.tags)


@router.delete("/{char_id}/memories/{memory_id}")
async def delete_memory(char_id: str, memory_id: str):
    _get(char_id)
    memory_mod.delete_memory(char_id, memory_id)
    return {"ok": True}


# ── chat ──────────────────────────────────────────────────────────────────────

class ChatMsg(BaseModel):
    role: str
    content: str

class ChatIn(BaseModel):
    message: str
    history: list[ChatMsg] = []

@router.post("/{char_id}/chat")
async def chat_with_character(char_id: str, body: ChatIn):
    from . import feeling as feeling_mod
    char = _get(char_id)
    s, backend = _backend()

    base_sys = brain_mod._system_prompt(char)
    sys_prompt = (
        base_sys
        + "\n\nYou are now in a direct conversation with your creator. "
        "Respond naturally as yourself — warm, honest, grounded. "
        "2–4 sentences unless the topic genuinely needs more. "
        "Never produce JSON or structured output."
    )

    mems = memory_mod.retrieve(char_id, context=body.message, n=8)
    mem_text = memory_mod.memories_prompt(mems) if mems else ""

    prof = profile_mod.get(char)
    feeling_line = feeling_mod.format_for_prompt(prof.get("feeling"))

    context_parts = []
    if feeling_line:
        context_parts.append(feeling_line)
    if mem_text:
        context_parts.append("Your recent memories:\n" + mem_text)

    messages = [{"role": "system", "content": sys_prompt}]
    if context_parts:
        messages.append({"role": "system", "content": "\n\n".join(context_parts)})

    for h in body.history:
        messages.append({"role": h.role, "content": h.content})
    messages.append({"role": "user", "content": body.message})

    result = await backend.complete(messages, max_tokens=400)
    return {"reply": result.text.strip()}


# ── skills ────────────────────────────────────────────────────────────────────

from . import skills as skills_mod  # noqa: E402

class SkillReq(BaseModel):
    name: str
    category: str = ""
    seed_hours: float = 0.0


class SkillPatch(BaseModel):
    hours: float | None = None
    category: str | None = None


@router.get("/{char_id}/skills")
async def list_skills(char_id: str):
    c = _get(char_id)
    prof = profile_mod.get(c)
    skills = prof.get("skills") or []
    from .skills import level_for
    return [{**s, "level_label": level_for(s.get("hours", 0.0))[1]} for s in skills]


@router.post("/{char_id}/skills")
async def add_skill(char_id: str, body: SkillReq):
    c = _get(char_id)
    sk = skills_mod.add_skill(c, body.name, body.category, body.seed_hours)
    store.save(c)
    return sk


@router.patch("/{char_id}/skills/{skill_name}")
async def patch_skill(char_id: str, skill_name: str, body: SkillPatch):
    c = _get(char_id)
    prof = c.get("profile") or {}
    skills = prof.get("skills") or []
    sk = next((s for s in skills if s["name"].lower() == skill_name.lower()), None)
    if not sk:
        raise HTTPException(404, "skill not found")
    if body.hours is not None:
        sk["hours"] = max(0.0, body.hours)
        from .skills import level_for
        sk["level"] = level_for(sk["hours"])[0]
    if body.category is not None:
        sk["category"] = body.category
    prof["skills"] = skills
    c["profile"] = prof
    store.save(c)
    return sk


@router.delete("/{char_id}/skills/{skill_name}")
async def delete_skill(char_id: str, skill_name: str):
    c = _get(char_id)
    removed = skills_mod.remove_skill(c, skill_name)
    if not removed:
        raise HTTPException(404, "skill not found")
    store.save(c)
    return {"ok": True}


@router.get("/{char_id}/life/status")
async def life_status(char_id: str):
    """Loop status for this character: last think time, next scheduled time, loop running."""
    from characters import loop as loop_mod
    c = _get(char_id)
    prof = profile_mod.get(c)
    last = profile_mod.last_run_time(char_id)
    interval_s = (prof.get("life_interval_m") or 60) * 60
    next_at = (last + interval_s) if last else None
    loop_running = loop_mod._task is not None and not loop_mod._task.done()
    return {
        "life_enabled":    prof.get("life_enabled", False),
        "last_run":        last,         # keep both names; life.js uses last_run
        "last_run_at":     last,
        "next_run":        next_at,
        "next_run_at":     next_at,
        "interval_m":      prof.get("life_interval_m") or 60,
        "loop_running":    loop_running,
        "energy":          prof.get("energy", 80),
        "sleep_threshold": prof.get("sleep_threshold", 20),
        "feeling":         prof.get("feeling") or {},
    }


class OverrideReq(BaseModel):
    energy:  int | None = None          # 0-100
    feeling: dict | None = None         # {primary, intensity, secondary?}


@router.patch("/{char_id}/override")
async def override_state(char_id: str, body: OverrideReq):
    """Directly set energy and/or feeling — bypasses the brain, effective immediately."""
    from . import feeling as feeling_mod
    c = _get(char_id)
    updates: dict = {}
    if body.energy is not None:
        updates["energy"] = max(0, min(100, body.energy))
    if body.feeling:
        primary = body.feeling.get("primary", "")
        if primary not in feeling_mod.ALL_FEELINGS:
            raise HTTPException(400, f"unknown feeling: {primary}")
        updates["feeling"] = {
            "primary":   primary,
            "intensity": max(1, min(10, int(body.feeling.get("intensity", 5)))),
            "secondary": body.feeling.get("secondary", ""),
            "since_ts":  __import__("time").time(),
        }
    if not updates:
        raise HTTPException(400, "nothing to override")
    profile_mod.patch(c, updates)
    store.save(c)
    return updates


class ThinkReq(BaseModel):
    context_override: str = ""


@router.post("/{char_id}/think")
async def think(char_id: str, body: ThinkReq | None = None):
    """Run the brain: one LLM call → thought + image idea. Logs the event."""
    c = _get(char_id)
    if c["kind"] != "person":
        raise HTTPException(400, "only a person has a brain")
    if jobs.busy() or manager.busy():
        raise HTTPException(409, "the model server is busy; try again when it finishes")
    s, be = _backend()
    try:
        return await brain_mod.think(c, be, s, trigger="manual",
                                     context_override=(body.context_override if body else ""))
    except Exception as e:
        raise HTTPException(500, f"the brain could not think: {e}")


class DrawThoughtReq(BaseModel):
    event_id: str


@router.post("/{char_id}/life/{event_id}/draw")
async def draw_thought(char_id: str, event_id: str):
    """Generate a picture from a logged thought. Starts a background job."""
    c = _get(char_id)
    ev = profile_mod.get_event(event_id)
    if not ev or ev["char_id"] != char_id:
        raise HTTPException(404, "no such event for this character")
    if ev["event_type"] != "think":
        raise HTTPException(400, "can only draw from a 'think' event")
    thought = ev["outputs"]
    s, key = settings_mod.get(), settings_mod.api_key()
    return _start(char_id, "char_moment",
                  lambda progress: brain_mod.draw_thought(c, event_id, thought, s, key))


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


class RetryReq(BaseModel):
    note: str = ""                      # extra instruction for this try, added to the end of the same prompt (for example what went wrong last time)


@router.post("/item/{item_id}/retry")
async def retry_item(item_id: str, body: RetryReq | None = None):
    """Re-run a failed attempt, or a finished edit or head swap, as a new attempt with the same inputs (a new seed is drawn by the server)."""
    it = media.get(item_id)
    if not it:
        raise HTTPException(404, "no such picture")
    if it["status"] not in ("failed", "done") or (it["status"] == "done" and it["kind"] != store.EDIT):
        raise HTTPException(400, "only failed pictures and finished edits can be retried")
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
        swap = m.get("swap") or ""
        lo = None if swap else (m.get("loras") or None)                 # a swap keeps its LoRAs in the swap string
        note = (body.note if body else "").strip()
        prompt = (m.get("prompt", "") + (" " + note if note else ""))[:3900]
        return _start(char_id, "char_edit", lambda p: studio_edit.make_edit(
            char_id, base_id, m.get("preset", "custom"), m.get("value", ""),
            extra_ids, "", "", 1, prompt, p, s, key, lora=lo, swap=swap))
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
