"""HTTP API for the Character Studio (mounted under /api/characters). Same login as the rest of the app. Everything that talks to the gateway runs as the same one-at-a-time background job as
the other steps (story2/jobs.py), keyed by the character's id."""
import asyncio

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from story import llm, settings as settings_mod
from story.pipeline import manager
from story2 import describe, jobs, providers
from story3 import store as media
from story3.voice import MediaError

from . import render, requests as R, store, studio

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
            "how": m.get("how", ""), "loras": m.get("loras", []), "model": m.get("model", ""), "style": m.get("style", ""), "version": m.get("version"), "current": m.get("identity_hash") == ident}


def _card(c: dict) -> dict:
    return {"id": c["id"], "name": c["name"], "kind": c["kind"], "status": c["status"], "tags": c["tags"], "version": c["version"], "thumb": _thumb(c), "style": c["render"]["style"],
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
            "slots": {k: [{"key": a, "hint": b} for a, b in describe.SLOTS[k]] for k in store.KINDS}}


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


@router.post("")
async def create(body: CreateReq):
    extra = {"idea": body.idea.strip(), "personality": body.personality.strip(), "tags": [t.strip() for t in body.tags if t.strip()]}
    if body.render:
        extra["render"] = body.render
    c = _guard(store.create, body.name.strip() or "Untitled", body.kind, body.slots, extra)
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
    for kind in (store.GEN, store.SHEET):
        for it in media.items(char_id, kind):
            gallery.setdefault(it["key"], []).append(_view(char_id, it, ident))
    views = [v for v, spec in R.VIEWS.items() if spec["kind"] == c["kind"]]
    return {**_card(c), "idea": c["idea"], "slots": c["slots"], "personality": c["personality"], "notes": c["notes"], "render": c["render"], "locked": store.locked(c), "canon": c["canon"],
            "rights": c["rights"], "photo": f"/api/characters/file/{char_id}/{c['source_photo']}" if store.photo_path(c) else "", "gaps": describe.missing(c["kind"] if c["kind"] != "person" else "person", c["slots"]),
            "identity": R.identity_text(c), "gallery": gallery, "views": views, "job": jobs.status(char_id), "identity_hash": ident,
            "estimate_s": {"draw": 70, "edit": 110}}


class PatchReq(BaseModel):
    name: str | None = None
    idea: str | None = None
    slots: dict | None = None
    personality: str | None = None
    notes: str | None = None
    tags: list[str] | None = None
    render: dict | None = None


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
    for k in ("name", "idea", "personality", "notes"):
        if k in p and p[k] is not None:
            c[k] = p[k].strip() if k == "name" else p[k]
    if "tags" in p and p["tags"] is not None:
        c["tags"] = [t.strip() for t in p["tags"] if t.strip()]
    store.save(c)
    return await state(char_id)


class SuggestReq(BaseModel):
    idea: str = ""
    keep: bool = True                  # keep the slots the person already wrote


@router.post("/{char_id}/suggest")
async def suggest(char_id: str, body: SuggestReq):
    c = _get(char_id)
    idea = (body.idea or c["idea"]).strip()
    if len(idea) < 5:
        raise HTTPException(400, "write the idea in a sentence first")
    if jobs.busy() or manager.busy():
        raise HTTPException(409, "the model server is busy with another job; try again when it finishes")
    s, be = _backend()
    try:
        out = await studio.suggest_slots(idea, c["kind"], be, s, c["slots"] if body.keep else None)
    except (llm.LLMError, MediaError, ValueError) as e:
        raise HTTPException(400, f"the slots could not be written: {e}")
    c["idea"], c["slots"] = idea, out["slots"]
    if out["personality"] and not c["personality"]:
        c["personality"] = out["personality"]
    if out["name"] and c["name"] in ("", "Untitled"):
        c["name"] = out["name"]
    store.save(c)
    return await state(char_id)


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
    return _start(char_id, "char_generate", lambda progress: studio.make_views(char_id, body.views, body.n, progress, s, key, body.seed, body.extra))


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
