"""/api/sim: stories that grow chapter by chapter (docs/PLAN_simulation.md section 14). Reading and editing the setup is instant; every model step runs as the one background job (the gateway serves
one request at a time) and the screen polls /run, so leaving the page loses nothing."""
import copy
import random
import re

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import BaseModel

import config
from story import llm, settings as settings_mod

from . import engine, export as export_mod, health, jobs, memory, paint, portable, seed, state as S, store, templates, things

router = APIRouter(prefix="/api/sim", tags=["sim"])


def _err(e: Exception, code: int = 400):
    raise HTTPException(code, str(e))


def _project(pid: str) -> dict:
    try:
        return store.project(pid)
    except store.SimError as e:
        raise HTTPException(404, str(e))


def _job(pid: str, kind: str, make):
    """Start `make(backend, s, progress, cancel)` as the one background job."""
    _project(pid)
    s, key = settings_mod.get(), settings_mod.api_key()

    async def work(progress):
        return await make(llm.ChatBackend(s, key), s, progress, jobs.cancelled(pid))

    try:
        return jobs.start(pid, kind, work)
    except jobs.Busy as e:
        raise HTTPException(409, str(e))


def _bytes(pid: str) -> int:
    d = config.DATA_DIR / "media" / pid
    return sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) if d.is_dir() else 0


async def _after(pid: str, ch: dict, backend, s, progress, cancel) -> None:
    """With "paint every chapter" on, the pictures follow each finished chapter; a failure there never fails the story."""
    if not store.project(pid)["settings"].get("auto_images"):
        return
    try:
        await paint.paint_chapter(pid, ch["id"], backend, s, settings_mod.api_key(), progress, cancel)
    except engine.Stopped:
        raise
    except Exception as e:  # noqa: BLE001
        c = store.chapter(ch["id"])
        store.update_chapter(ch["id"], flags={**c["flags"], "paint_error": f"{type(e).__name__}: {e}"[:300]})


# ── list, create, read ────────────────────────────────────────────────────────

@router.get("")
async def listing():
    out = []
    for p in store.projects():
        chs = [c for c in store.chapters(p["id"]) if c["status"] == "done"]
        out.append({"id": p["id"], "title": p["title"], "idea": p["idea"], "status": p["status"], "chapters": len(store.path(p["id"])) if p["head_id"] else 0, "all_chapters": len(chs),
                    "updated_at": p["updated_at"], "created_at": p["created_at"], "bytes": _bytes(p["id"]), "running": jobs.status(p["id"]).get("state") == "running"})
    return {"stories": out, "templates": [{"id": t["id"], "name": t["name"], "blurb": t.get("blurb", "")} for t in templates.all_templates()]}


class NewStory(BaseModel):
    idea: str
    title: str = ""
    template_id: str = ""


@router.post("")
async def create(body: NewStory):
    try:
        p = store.create_project(body.idea, body.title, body.template_id)
        if body.template_id:
            templates.apply(p["id"], body.template_id)
    except store.SimError as e:
        _err(e)
    return {"id": p["id"]}


def _state_now(pid: str, path: list[dict]) -> dict:
    trackers, ents = store.trackers(pid), store.entities(pid)
    if path and path[-1]["status"] == "done":
        return engine.reconcile(path[-1]["state_after"], trackers, ents)
    return S.initial_state(trackers, ents, store.world(pid))


def _chapter_view(c: dict, siblings: list[dict]) -> dict:
    return {**{k: c[k] for k in ("id", "parent_id", "idx", "branch_label", "status", "title", "prose", "story_time", "summary", "focus", "rolls", "options", "chosen", "fired", "panels", "flags")},
            "plan": {k: c["plan"].get(k) for k in ("scene", "intent", "pressure", "beat", "where", "time_passes", "risks", "minds", "opposition", "calibration") if k in c["plan"]},
            "applied": c["delta"].get("applied", []), "dropped": c["delta"].get("dropped", []), "state_after": c["state_after"],
            "siblings": [{"id": x["id"], "label": x["branch_label"] or f"branch {i + 1}", "status": x["status"], "title": x["title"]} for i, x in enumerate(siblings)] if len(siblings) > 1 else []}


@router.get("/file/{pid}/{name:path}")
async def media_file(pid: str, name: str):
    """A picture of a story (references and panels). Served only from inside that story's media folder."""
    base = (config.DATA_DIR / "media" / pid).resolve()
    f = (base / name).resolve()
    if not str(f).startswith(str(base)) or not f.is_file():
        raise HTTPException(404, "no such file")
    return FileResponse(f, headers={"Cache-Control": "no-store"})


@router.get("/templates")
async def get_templates():
    return {"templates": templates.all_templates()}


@router.get("/{pid}")
async def detail(pid: str):
    p = _project(pid)
    paint.mark_old(pid)
    path = store.path(pid)
    ents, trackers = store.entities(pid, active_only=False), store.trackers(pid)
    for e in ents:
        r = paint.latest_ref(pid, e["id"])
        e["ref_file"] = r["file"] if r else ""
        e["ref_old"] = paint.ref_is_old(pid, e, p["settings"])
    pending = memory.pending_directives(pid, path)
    fired = {d: c["idx"] for c in path for d in c["fired"]}
    st = _state_now(pid, path)
    chapters = [_chapter_view(c, store.children(pid, c["parent_id"])) for c in path]
    all_ch = store.chapters(pid)
    path_ids = {c["id"] for c in path}
    failed = next((c for c in all_ch if c["status"] == "failed" and c["parent_id"] == (path[-1]["id"] if path else "")), None)
    return {"project": {k: p[k] for k in ("id", "title", "idea", "status", "settings", "head_id", "created_at", "updated_at")},
            "world": store.world(pid), "entities": ents, "trackers": trackers, "guidelines": store.guidelines(pid),
            "directives": [{**d, "fired_in": fired.get(d["id"]), "pending": d["id"] in {x["id"] for x in pending}} for d in store.directives(pid)],
            "chapters": chapters, "state": st, "pressure": S.pressure(st, trackers), "threads": [t for t in memory.open_threads(pid, path)],
            "facts": [f for f in memory.path_facts(pid, path)], "missing": S.validate_setup(trackers, [e for e in ents if e["active"]]),
            "failed": ({"id": failed["id"], "stage": store.run_info(pid).get("stage", ""), "error": failed["flags"].get("error", ""), "done": failed["flags"].get("done", [])} if failed else None),
            "run": {**jobs.status(pid), **store.run_info(pid)}, "reading_minutes": export_mod.reading_minutes(pid), "bytes": _bytes(pid),
            "branches": len([c for c in all_ch if c["id"] not in path_ids and c["status"] == "done"]), "tracker_kinds": list(store.TRACKER_KINDS),
            "carry": {"default": int(p["settings"].get("carry_limit", 0) or 0), "people": memory.carry_map(ents)}, "health": health.report(pid, path)}


class Patch(BaseModel):
    title: str | None = None
    idea: str | None = None
    settings: dict | None = None
    world: dict | None = None


@router.patch("/{pid}")
async def patch(pid: str, body: Patch):
    _project(pid)
    try:
        f = {}
        if body.title is not None:
            f["title"] = body.title.strip()[:120] or "Untitled"
        if body.idea is not None:
            if not body.idea.strip():
                raise store.SimError("the idea cannot be empty")
            f["idea"] = body.idea.strip()
        if body.settings is not None:
            f["settings"] = {k: v for k, v in body.settings.items() if k in store.DEFAULT_SETTINGS and k not in ("seed", "rules_version")}
        if f:
            store.save_project(pid, **f)
        if body.world is not None:
            store.set_world(pid, {k: str(v) for k, v in body.world.items()})
    except (store.SimError, ValueError) as e:
        _err(e)
    return {"ok": True}


@router.delete("/{pid}")
async def delete(pid: str):
    _project(pid)
    if jobs.status(pid).get("state") == "running":
        raise HTTPException(409, "a job is running for this story; stop it first")
    store.delete_project(pid)
    return {"ok": True}


# ── setup: seed, people, trackers, rules, instructions ────────────────────────

class SeedBody(BaseModel):
    instruction: str = ""


@router.post("/{pid}/seed/{part}")
async def seed_part(pid: str, part: str, body: SeedBody):
    if part != "all" and part not in seed.PARTS:
        raise HTTPException(400, "part must be all, world, cast, trackers or rules")
    if part in ("cast", "trackers", "all") and _project(pid)["status"] != "setup":
        raise HTTPException(400, "the story already started; edit people and trackers one by one")

    async def make(backend, s, progress, cancel):
        if part == "all":
            await seed.seed_all(pid, backend, s, progress, cancel)
            return "setup ready: review it, then press Start"
        progress(0, 1, f"writing the {part}")
        await seed.seed_part(pid, part, backend, s, body.instruction)
        return f"the {part} is ready"
    return _job(pid, "seed", make)


class EntityBody(BaseModel):
    id: str | None = None
    kind: str = "character"
    name: str
    data: dict = {}


@router.post("/{pid}/entities")
async def save_entity(pid: str, body: EntityBody):
    _project(pid)
    try:
        return store.save_entity(pid, {**body.data, "kind": body.kind, "name": body.name, **({"id": body.id} if body.id else {})})
    except store.SimError as e:
        _err(e)


@router.delete("/{pid}/entities/{eid}")
async def del_entity(pid: str, eid: str):
    p = _project(pid)
    try:
        e = store.entity(pid, eid)
        if p["head_id"]:
            store.retire_entity(pid, eid)
        else:
            store.delete_entity(pid, eid)
            store.purge_entity_refs(pid, e["name"])
    except store.SimError as err:
        raise HTTPException(404, str(err))
    return {"ok": True, "retired": bool(p["head_id"])}


class TrackerBody(BaseModel):
    id: str | None = None
    kind: str
    name: str
    data: dict = {}


@router.post("/{pid}/trackers")
async def save_tracker(pid: str, body: TrackerBody):
    _project(pid)
    ents = store.entities(pid)
    try:
        data, bad = S.normalize_tracker({**body.data, "kind": body.kind, "name": body.name}, [e["name"] for e in ents if e["kind"] == "character"], [e["name"] for e in ents if e["kind"] == "place"])
        t = store.save_tracker(pid, {**data, **({"id": body.id} if body.id else {})})
    except (store.SimError, KeyError, ValueError) as e:
        _err(e)
    return {"tracker": t, "problems": bad}


@router.delete("/{pid}/trackers/{tid}")
async def del_tracker(pid: str, tid: str):
    _project(pid)
    store.delete_tracker(pid, tid)
    return {"ok": True}


class GuidelineBody(BaseModel):
    id: str | None = None
    grp: str = "hard"
    text: str
    enabled: bool = True


@router.post("/{pid}/guidelines")
async def save_guideline(pid: str, body: GuidelineBody):
    _project(pid)
    try:
        return store.save_guideline(pid, {**body.model_dump(exclude_none=True), "origin": "owner"})
    except store.SimError as e:
        _err(e)


@router.delete("/{pid}/guidelines/{gid}")
async def del_guideline(pid: str, gid: str):
    _project(pid)
    store.retire_guideline(pid, gid)
    return {"ok": True}


@router.post("/{pid}/guidelines/suggest")
async def suggest(pid: str, body: SeedBody):
    async def make(backend, s, progress, cancel):
        progress(0, 1, "suggesting more rules")
        n = len(await seed.suggest_rules(pid, backend, s, body.instruction))
        return f"{n} new rules added"
    return _job(pid, "suggest", make)


class DirectiveBody(BaseModel):
    id: str | None = None
    kind: str = "event"
    text: str
    timing: dict = {"mode": "next"}
    thing: dict | None = None            # grant, take, unbind: {item, to, from, qty}


@router.post("/{pid}/directives")
async def save_directive(pid: str, body: DirectiveBody):
    _project(pid)
    try:
        if body.id:
            d = store.directive(pid, body.id)
            if d["status"] == "cancelled" or d["id"] in memory.fired_ids(store.path(pid)):
                raise store.SimError("this instruction was already used or cancelled")
        data = body.model_dump(exclude_none=True)
        thing = data.pop("thing", None)
        if thing is not None:
            data["timing"] = {**data.get("timing", {"mode": "next"}), "thing": {k: v for k, v in thing.items() if k in ("item", "to", "from", "qty")}}
        return store.save_directive(pid, data)
    except (store.SimError, ValueError) as e:
        _err(e)


@router.delete("/{pid}/directives/{did}")
async def del_directive(pid: str, did: str):
    _project(pid)
    try:
        if did in memory.fired_ids(store.path(pid)):
            raise store.SimError("this instruction was already used; it stays in the history")
        store.cancel_directive(pid, did)
    except store.SimError as e:
        _err(e)
    return {"ok": True}


# ── running chapters ──────────────────────────────────────────────────────────

class ChapterBody(BaseModel):
    parent_id: str | None = None
    kind: str = "auto"                 # option | text | auto
    option_id: str = ""
    text: str = ""
    who: str = ""
    label: str = ""


def _need_start(pid: str):
    miss = S.validate_setup(store.trackers(pid), [e for e in store.entities(pid)])
    if miss:
        raise HTTPException(400, "not ready: " + "; ".join(miss))


@router.post("/{pid}/start")
async def start(pid: str):
    p = _project(pid)
    if p["head_id"]:
        raise HTTPException(400, "the story already started")
    _need_start(pid)

    async def make(backend, s, progress, cancel):
        ch = await engine.run_chapter(pid, backend, s, progress, parent_id="", action={"kind": "start"}, cancel=cancel)
        await _after(pid, ch, backend, s, progress, cancel)
        return f"chapter 1 is ready: {ch['title']}"
    return _job(pid, "chapter", make)


@router.post("/{pid}/chapters")
async def new_chapter(pid: str, body: ChapterBody):
    p = _project(pid)
    if not p["head_id"]:
        raise HTTPException(400, "start the story first")
    parent = body.parent_id if body.parent_id is not None else p["head_id"]
    try:
        par = store.chapter(parent)
    except store.SimError as e:
        raise HTTPException(404, str(e))
    if par["project_id"] != pid or par["status"] != "done":
        raise HTTPException(400, "choose a finished chapter to continue from")
    if body.kind == "option" and not any(o["id"] == body.option_id for o in par["options"]):
        raise HTTPException(400, "that option is not offered by this chapter")
    if body.kind == "text" and not body.text.strip():
        raise HTTPException(400, "write what happens next")

    async def make(backend, s, progress, cancel):
        action = {"kind": body.kind, "option_id": body.option_id, "text": body.text.strip(), "who": body.who}
        if body.kind == "auto":
            action = await engine.pick_option(pid, backend, s, par)
        ch = await engine.run_chapter(pid, backend, s, progress, parent_id=parent, action=action, label=body.label, cancel=cancel)
        await _after(pid, ch, backend, s, progress, cancel)
        return f"chapter {ch['idx']} is ready: {ch['title']}"
    return _job(pid, "chapter", make)


class AutoBody(BaseModel):
    n: int = 3


@router.post("/{pid}/auto")
async def auto(pid: str, body: AutoBody):
    p = _project(pid)
    if not p["head_id"]:
        raise HTTPException(400, "start the story first")

    async def make(backend, s, progress, cancel):
        r = await engine.auto_run(pid, body.n, backend, s, progress, cancel, after=lambda ch: _after(pid, ch, backend, s, progress, cancel))
        return f"{r['made']} chapters made" + (f"; stopped: {r['stopped_because']}" if r["stopped_because"] else "")
    return _job(pid, "auto", make)


@router.post("/{pid}/stop")
async def stop(pid: str):
    _project(pid)
    return {"stopping": jobs.request_stop(pid)}


@router.get("/{pid}/run")
async def run_state(pid: str):
    _project(pid)
    return {**jobs.status(pid), **store.run_info(pid)}


class RewriteBody(BaseModel):
    instruction: str = ""


def _own_chapter(pid: str, cid: str) -> dict:
    _project(pid)
    try:
        c = store.chapter(cid)
    except store.SimError as e:
        raise HTTPException(404, str(e))
    if c["project_id"] != pid:
        raise HTTPException(404, "no such chapter")
    return c


def _redo(pid: str, cid: str, instruction: str, salt: str, label: str):
    c = _own_chapter(pid, cid)
    if c["status"] != "done":
        raise HTTPException(400, "only a finished chapter can be redone")

    async def make(backend, s, progress, cancel):
        if not c["branch_label"]:
            store.update_chapter(cid, branch_label="earlier version")
        n = await engine.run_chapter(pid, backend, s, progress, parent_id=c["parent_id"], action=c["chosen"] or {"kind": "start"}, instruction=instruction, salt=salt, label=label, cancel=cancel)
        await _after(pid, n, backend, s, progress, cancel)
        return f"new version of chapter {n['idx']} ready; the earlier one is kept as a branch"
    return _job(pid, "rewrite", make)


@router.post("/{pid}/chapters/{cid}/rewrite")
async def rewrite(pid: str, cid: str, body: RewriteBody):
    if not body.instruction.strip():
        raise HTTPException(400, "say what to change")
    return _redo(pid, cid, body.instruction.strip(), "", "rewrite")


@router.post("/{pid}/chapters/{cid}/reroll")
async def reroll(pid: str, cid: str):
    return _redo(pid, cid, "", f"{random.randint(1, 10 ** 6)}", "new dice")


@router.post("/{pid}/chapters/{cid}/retry")
async def retry(pid: str, cid: str):
    c = _own_chapter(pid, cid)
    if c["status"] != "failed":
        raise HTTPException(400, "this chapter did not fail")

    async def make(backend, s, progress, cancel):
        n = await engine.run_chapter(pid, backend, s, progress, resume_id=cid, cancel=cancel)
        await _after(pid, n, backend, s, progress, cancel)
        return f"chapter {n['idx']} is ready: {n['title']}"
    return _job(pid, "chapter", make)


@router.post("/{pid}/chapters/{cid}/accept")
async def accept(pid: str, cid: str):
    c = _own_chapter(pid, cid)
    fl = {k: v for k, v in c["flags"].items() if k != "rule_break"}
    fl["accepted"] = True
    store.update_chapter(cid, flags=fl)
    return {"ok": True}


class EditBody(BaseModel):
    title: str | None = None
    prose: str | None = None
    summary: str | None = None


@router.patch("/{pid}/chapters/{cid}")
async def edit_chapter(pid: str, cid: str, body: EditBody):
    c = _own_chapter(pid, cid)
    f = {}
    stale = 0
    if body.title is not None:
        f["title"] = body.title.strip()[:120]
    if body.summary is not None:
        f["summary"] = body.summary.strip()
    if body.prose is not None and body.prose.strip() != c["prose"].strip():
        f["prose"] = body.prose.strip()
        f["flags"] = {**c["flags"], "edited": True}
        stale = engine.mark_stale(pid, cid)
        f["panels"] = [{**p, "old": True} for p in c["panels"]]
    if f:
        store.update_chapter(cid, **f)
    return {"ok": True, "stale_after": stale, "edited_prose": "prose" in f}


@router.post("/{pid}/chapters/{cid}/reread")
async def reread(pid: str, cid: str):
    _own_chapter(pid, cid)

    async def make(backend, s, progress, cancel):
        progress(0, 1, "reading your edit")
        prop = await engine.reread(pid, cid, backend, s)
        c = store.chapter(cid)
        store.update_chapter(cid, flags={**c["flags"], "reread": prop})
        return prop["note"] or "nothing in the state changes"
    return _job(pid, "reread", make)


@router.post("/{pid}/chapters/{cid}/reread/apply")
async def reread_apply(pid: str, cid: str):
    c = _own_chapter(pid, cid)
    prop = c["flags"].get("reread")
    if not prop:
        raise HTTPException(400, "no proposal to apply; read the edit first")
    engine.apply_reread(pid, cid, prop["ops"])
    c = store.chapter(cid)
    store.update_chapter(cid, flags={k: v for k, v in c["flags"].items() if k != "reread"})
    return {"ok": True}


class ThingAction(BaseModel):
    action: dict


def _things_ctx(pid: str, ch: dict) -> S.Ctx:
    return engine.make_ctx(pid, store.entities(pid), store.world(pid), store.trackers(pid), store.project(pid)["settings"], chapter=ch["idx"])


@router.post("/{pid}/things")
async def things_edit(pid: str, body: ThingAction):
    """The Things tab: change a thing, a recipe or a skill in the state the story has now (the last chapter of the current line)."""
    _project(pid)
    if jobs.status(pid).get("state") == "running":
        raise HTTPException(409, "a job is running for this story; wait or stop it")
    path = store.path(pid)
    if not path or path[-1]["status"] != "done":
        raise HTTPException(400, "start the story first")
    head = path[-1]
    st = copy.deepcopy(head["state_after"])
    try:
        text = things.edit(st, _things_ctx(pid, head), body.action)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))
    delta = {**head["delta"], "applied": head["delta"].get("applied", []) + [{"op": "owner_edit", "text": text, "why": "you changed it"}]}
    store.update_chapter(head["id"], state_after=st, delta=delta)
    return {"ok": True, "text": text}


class UndoBody(BaseModel):
    index: int


@router.post("/{pid}/chapters/{cid}/undo")
async def undo_change(pid: str, cid: str, body: UndoBody):
    """Take back one change a chapter made (a find, a make, a give...): its recorded way back is applied to the chapter's state, and the later chapters are marked as written under the old state."""
    c = _own_chapter(pid, cid)
    applied = list(c["delta"].get("applied", []))
    if not 0 <= body.index < len(applied) or not applied[body.index].get("undo") or applied[body.index].get("undone"):
        raise HTTPException(400, "this change cannot be taken back")
    st = copy.deepcopy(c["state_after"])
    ctx = _things_ctx(pid, c)
    try:
        for a in reversed(applied[body.index]["undo"]):
            things.edit(st, ctx, a)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))
    applied[body.index] = {**applied[body.index], "undone": True}
    store.update_chapter(cid, state_after=st, delta={**c["delta"], "applied": applied})
    return {"ok": True, "stale": engine.mark_stale(pid, cid)}


class HeadBody(BaseModel):
    chapter_id: str


@router.post("/{pid}/head")
async def set_head(pid: str, body: HeadBody):
    c = _own_chapter(pid, body.chapter_id)
    if c["status"] != "done":
        raise HTTPException(400, "choose a finished chapter")
    store.save_project(pid, head_id=c["id"])
    return {"ok": True}


@router.delete("/{pid}/chapters/{cid}")
async def del_chapter(pid: str, cid: str):
    _own_chapter(pid, cid)
    if jobs.status(pid).get("state") == "running":
        raise HTTPException(409, "a job is running for this story")
    try:
        store.delete_chapter(pid, cid)
    except store.SimError as e:
        _err(e)
    return {"ok": True}


# ── export, import, duplicate, templates ──────────────────────────────────────

@router.get("/{pid}/export")
async def export(pid: str, format: str = "md", full: bool = False):
    _project(pid)
    if format == "md":
        return PlainTextResponse(export_mod.markdown(pid), headers={"Content-Disposition": f'attachment; filename="{pid}.md"'})
    if format == "zip":
        return Response(export_mod.zipped(pid), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{pid}.zip"'})
    if format == "json":
        return export_mod.chapter_json(pid)
    if format == "story":                                                     # the importable file
        return portable.export_data(pid, full)
    raise HTTPException(400, "format must be md, json, zip or story")


@router.post("/import")
async def import_story(body: dict):
    try:
        return {"id": portable.import_data(body)["id"]}
    except (store.SimError, KeyError, TypeError) as e:
        _err(e)


@router.post("/{pid}/duplicate")
async def duplicate(pid: str, full: bool = False):
    _project(pid)
    return {"id": portable.duplicate(pid, full)["id"]}


class TemplateBody(BaseModel):
    name: str


@router.post("/{pid}/save-template")
async def save_template(pid: str, body: TemplateBody):
    _project(pid)
    t = store.save_template(body.name, portable.as_template(pid))
    return {"id": t["id"], "name": t["name"]}


# ── pictures ──────────────────────────────────────────────────────────────────

class PaintBody(BaseModel):
    panels: list[int] | None = None
    prompt: str = ""


@router.post("/{pid}/chapters/{cid}/paint")
async def paint_chapter(pid: str, cid: str, body: PaintBody):
    c = _own_chapter(pid, cid)
    if c["status"] != "done":
        raise HTTPException(400, "paint a finished chapter")

    async def make(backend, s, progress, cancel):
        return await paint.paint_chapter(pid, cid, backend, s, settings_mod.api_key(), progress, cancel, body.panels)
    return _job(pid, "paint", make)


def _panel(pid: str, cid: str, n: int) -> tuple[dict, dict]:
    c = _own_chapter(pid, cid)
    p = next((x for x in c["panels"] if x["n"] == n), None)
    if not p:
        raise HTTPException(404, "no such picture")
    return c, p


@router.post("/{pid}/chapters/{cid}/panels/{n}/redraw")
async def redraw_panel(pid: str, cid: str, n: int, body: PaintBody):
    c, p = _panel(pid, cid, n)
    if body.prompt.strip():
        p["prompt_override"] = body.prompt.strip()
        store.update_chapter(cid, panels=c["panels"])

    async def make(backend, s, progress, cancel):
        return await paint.paint_chapter(pid, cid, backend, s, settings_mod.api_key(), progress, cancel, [n])
    return _job(pid, "paint", make)


class PanelPatch(BaseModel):
    caption: str | None = None
    action: str | None = None
    mood: str | None = None


@router.patch("/{pid}/chapters/{cid}/panels/{n}")
async def patch_panel(pid: str, cid: str, n: int, body: PanelPatch):
    c, p = _panel(pid, cid, n)
    if body.action is not None:
        p["action"] = body.action.strip()
        p.pop("prompt_override", None)
    if body.mood is not None:
        p["mood"] = body.mood.strip()
    if body.caption is not None:
        p["caption"] = " ".join(body.caption.split()[:12])
        f = config.DATA_DIR / "media" / pid / p["file"] if p.get("file") else None
        if f and f.is_file():                                              # only the lettering changes: no new picture is needed
            cfg = store.project(pid)["settings"]
            if cfg["captions"] and p["caption"]:
                rel = p["file"].rsplit(".", 1)[0] + "-cap.png"
                (config.DATA_DIR / "media" / pid / rel).write_bytes(paint.with_caption(f.read_bytes(), p["caption"]))
                p["capfile"] = rel
            else:
                p["capfile"] = ""
    store.update_chapter(cid, panels=c["panels"])
    paint.mark_old(pid, cid)
    return {"ok": True}


@router.post("/{pid}/chapters/{cid}/panels/{n}/upload")
async def upload_panel(pid: str, cid: str, n: int, file: UploadFile = File(...)):
    import io

    from PIL import Image

    from story3 import store as media
    c, p = _panel(pid, cid, n)
    data = await file.read()
    if not data or len(data) > 20_000_000:
        raise HTTPException(400, "send a picture of up to 20 MB")
    try:
        Image.open(io.BytesIO(data)).verify()
        buf = io.BytesIO()
        Image.open(io.BytesIO(data)).convert("RGB").save(buf, "PNG")
        png = buf.getvalue()
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "this is not a picture")
    item = media.add(pid, "sim_panel", f"{cid}:{n}", meta={"upload": True}, status="done")
    rel = paint._save(pid, "upload", f"{cid}-{n}-{item['attempt']}.png", png)
    media.update(item["id"], file=rel)
    cfg = store.project(pid)["settings"]
    cap = paint._save(pid, "upload", f"{cid}-{n}-{item['attempt']}-cap.png", paint.with_caption(png, p["caption"])) if cfg["captions"] and p.get("caption") else ""
    ents = {e["name"]: e for e in store.entities(pid)}
    p.update(file=rel, capfile=cap, media_id=item["id"], hash=paint.panel_hash(p, ents, cfg), old=False, uploaded=True)
    store.update_chapter(cid, panels=c["panels"])
    return {"ok": True}


@router.delete("/{pid}/chapters/{cid}/panels/{n}")
async def delete_panel(pid: str, cid: str, n: int):
    c, p = _panel(pid, cid, n)
    store.delete_panel_media(pid, f"{cid}:{n}")
    store.update_chapter(cid, panels=[x for x in c["panels"] if x["n"] != n])
    return {"ok": True}


@router.post("/{pid}/entities/{eid}/paint")
async def paint_entity(pid: str, eid: str):
    try:
        store.entity(pid, eid)
    except store.SimError as e:
        raise HTTPException(404, str(e))

    async def make(backend, s, progress, cancel):
        progress(0, 1, "painting")
        e = store.entity(pid, eid)
        await paint.paint_ref(pid, e, store.project(pid)["settings"], s, settings_mod.api_key())
        return f"{e['name']} painted"
    return _job(pid, "paint", make)
