"""Storage of the story simulator (tables of docs/PLAN_simulation.md section 3). Created lazily in the app database, like feedback/store.py. Pictures are rows of the existing `media`
table with the simulation id as `plan_id`, so numbered attempts and the storage clean-up work without new code."""
import hashlib
import random
import shutil
import time

import config
from story import db
from story3 import store as media

SCHEMA = """
CREATE TABLE IF NOT EXISTS sim_projects(id TEXT PRIMARY KEY, title TEXT DEFAULT '', idea TEXT DEFAULT '', status TEXT DEFAULT 'setup', settings TEXT DEFAULT '{}', head_id TEXT DEFAULT '', created_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS sim_world(project_id TEXT PRIMARY KEY, data TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS sim_entities(id TEXT PRIMARY KEY, project_id TEXT, kind TEXT, name TEXT, data TEXT DEFAULT '{}', position INTEGER DEFAULT 0, active INTEGER DEFAULT 1, created_at REAL);
CREATE INDEX IF NOT EXISTS sim_ent_p ON sim_entities(project_id);
CREATE TABLE IF NOT EXISTS sim_trackers(id TEXT PRIMARY KEY, project_id TEXT, kind TEXT, name TEXT, data TEXT DEFAULT '{}', position INTEGER DEFAULT 0, active INTEGER DEFAULT 1);
CREATE INDEX IF NOT EXISTS sim_trk_p ON sim_trackers(project_id);
CREATE TABLE IF NOT EXISTS sim_guidelines(id TEXT PRIMARY KEY, project_id TEXT, grp TEXT, text TEXT, enabled INTEGER DEFAULT 1, origin TEXT DEFAULT 'ai', position INTEGER DEFAULT 0, created_at REAL, retired INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS sim_gl_p ON sim_guidelines(project_id);
CREATE TABLE IF NOT EXISTS sim_directives(id TEXT PRIMARY KEY, project_id TEXT, kind TEXT, text TEXT, timing TEXT DEFAULT '{}', status TEXT DEFAULT 'pending', created_at REAL);
CREATE INDEX IF NOT EXISTS sim_dr_p ON sim_directives(project_id);
CREATE TABLE IF NOT EXISTS sim_chapters(id TEXT PRIMARY KEY, project_id TEXT, parent_id TEXT DEFAULT '', idx INTEGER DEFAULT 1, branch_label TEXT DEFAULT '', status TEXT DEFAULT 'writing',
  title TEXT DEFAULT '', prose TEXT DEFAULT '', story_time TEXT DEFAULT '', summary TEXT DEFAULT '', focus TEXT DEFAULT '[]', plan TEXT DEFAULT '{}', rolls TEXT DEFAULT '[]', delta TEXT DEFAULT '{}',
  state_before TEXT DEFAULT '{}', state_after TEXT DEFAULT '{}', options TEXT DEFAULT '[]', chosen TEXT DEFAULT '{}', flags TEXT DEFAULT '{}', fired TEXT DEFAULT '[]', panels TEXT DEFAULT '[]',
  created_at REAL, updated_at REAL);
CREATE INDEX IF NOT EXISTS sim_ch_p ON sim_chapters(project_id, parent_id);
CREATE TABLE IF NOT EXISTS sim_facts(id TEXT PRIMARY KEY, project_id TEXT, chapter_id TEXT, text TEXT, tags TEXT DEFAULT '[]', entity_names TEXT DEFAULT '[]', created_at REAL, retired INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS sim_fc_p ON sim_facts(project_id);
CREATE TABLE IF NOT EXISTS sim_threads(id TEXT PRIMARY KEY, project_id TEXT, text TEXT, opened_in TEXT DEFAULT '', closed_in TEXT DEFAULT '', status TEXT DEFAULT 'open');
CREATE INDEX IF NOT EXISTS sim_th_p ON sim_threads(project_id);
CREATE TABLE IF NOT EXISTS sim_runs(project_id TEXT PRIMARY KEY, data TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS sim_templates(id TEXT PRIMARY KEY, name TEXT, data TEXT DEFAULT '{}', builtin INTEGER DEFAULT 0, created_at REAL);
"""
TABLES = ("sim_world", "sim_entities", "sim_trackers", "sim_guidelines", "sim_directives", "sim_chapters", "sim_facts", "sim_threads", "sim_runs")

DEFAULT_SETTINGS = {"difficulty": "fair", "dice": True, "chapter_words": 350, "deep": False, "auto_images": False, "image_model": "", "panel_shape": "wide", "captions": True,
                    "seed": 7, "template_id": "", "rules_version": 1}
DIFFICULTIES = ("gentle", "fair", "brutal")
SHAPES = ("wide", "tall")
GROUPS = ("hard", "world", "tone", "style")
ENTITY_KINDS = ("character", "place", "group")
TRACKER_KINDS = ("items", "meter", "clock", "relation", "location", "knowledge", "flag")
DIRECTIVE_KINDS = ("event", "constraint", "twist", "steer")


class SimError(ValueError):
    pass


def ensure() -> None:
    with db.tx() as c:
        c.executescript(SCHEMA)


def new_id(prefix: str, *parts) -> str:
    return f"{prefix}-{hashlib.sha1((''.join(str(p) for p in parts) + str(time.time()) + str(random.random())).encode()).hexdigest()[:8]}"


# ── projects ──────────────────────────────────────────────────────────────────

def _proj(r: dict | None) -> dict | None:
    if r is None:
        return None
    r = dict(r)
    r["settings"] = {**DEFAULT_SETTINGS, **db.jload(r.get("settings"), {})}
    return r


def project(pid: str) -> dict:
    ensure()
    p = _proj(db.one("SELECT * FROM sim_projects WHERE id=?", (pid,)))
    if not p:
        raise SimError("no such story")
    return p


def projects() -> list[dict]:
    ensure()
    return [_proj(r) for r in db.q("SELECT * FROM sim_projects ORDER BY updated_at DESC")]


def create_project(idea: str, title: str = "", template_id: str = "") -> dict:
    ensure()
    idea = idea.strip()
    if not idea:
        raise SimError("write the idea first")
    pid = new_id("sm", idea)
    st = {**DEFAULT_SETTINGS, "seed": random.randint(1, 2 ** 31 - 1), "template_id": template_id}
    now = time.time()
    db.ex("INSERT INTO sim_projects(id,title,idea,status,settings,head_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (pid, title.strip() or idea[:60], idea, "setup", db.jdump(st), "", now, now))
    db.ex("INSERT INTO sim_world(project_id,data) VALUES(?,?)", (pid, "{}"))
    return project(pid)


def save_project(pid: str, **f) -> dict:
    p = project(pid)
    if "settings" in f:
        st = {**p["settings"], **f["settings"]}
        if st["difficulty"] not in DIFFICULTIES:
            raise SimError("difficulty must be gentle, fair or brutal")
        if st["panel_shape"] not in SHAPES:
            raise SimError("panel shape must be wide or tall")
        st["chapter_words"] = max(150, min(900, int(st["chapter_words"])))
        f["settings"] = db.jdump(st)
    f["updated_at"] = time.time()
    db.ex(f"UPDATE sim_projects SET {', '.join(k + '=?' for k in f)} WHERE id=?", (*f.values(), pid))
    return project(pid)


def touch(pid: str) -> None:
    db.ex("UPDATE sim_projects SET updated_at=? WHERE id=?", (time.time(), pid))


def bump_rules(pid: str) -> None:
    p = project(pid)
    save_project(pid, settings={"rules_version": int(p["settings"]["rules_version"]) + 1})


def delete_project(pid: str) -> None:
    """Remove the story completely: every table row, its media rows and its media folder (docs/PLAN_simulation.md section 17)."""
    project(pid)
    media.ensure()
    with db.tx() as c:
        for t in TABLES:
            c.execute(f"DELETE FROM {t} WHERE project_id=?", (pid,))
        c.execute("DELETE FROM media WHERE plan_id=?", (pid,))
        c.execute("DELETE FROM sim_projects WHERE id=?", (pid,))
    shutil.rmtree(config.DATA_DIR / "media" / pid, ignore_errors=True)


# ── world ─────────────────────────────────────────────────────────────────────

def world(pid: str) -> dict:
    ensure()
    r = db.one("SELECT data FROM sim_world WHERE project_id=?", (pid,))
    return db.jload(r["data"], {}) if r else {}


def set_world(pid: str, data: dict) -> dict:
    ensure()
    db.ex("INSERT INTO sim_world(project_id,data) VALUES(?,?) ON CONFLICT(project_id) DO UPDATE SET data=excluded.data", (pid, db.jdump(data)))
    touch(pid)
    return data


# ── entities, trackers, guidelines, directives ────────────────────────────────

_COLS = ("id", "project_id", "kind", "name", "position", "active")


def _ent(r: dict) -> dict:
    return {"id": r["id"], "project_id": r["project_id"], "kind": r["kind"], "name": r["name"], "position": r["position"], "active": bool(r["active"]), **db.jload(r["data"], {})}


def entities(pid: str, kind: str = "", active_only: bool = True) -> list[dict]:
    ensure()
    rows = db.q("SELECT * FROM sim_entities WHERE project_id=?" + (" AND kind=?" if kind else "") + (" AND active=1" if active_only else "") + " ORDER BY position, created_at", (pid, kind) if kind else (pid,))
    return [_ent(r) for r in rows]


def entity(pid: str, eid: str) -> dict:
    ensure()
    r = db.one("SELECT * FROM sim_entities WHERE id=? AND project_id=?", (eid, pid))
    if not r:
        raise SimError("no such cast member or place")
    return _ent(r)


def save_entity(pid: str, e: dict) -> dict:
    ensure()
    kind = e.get("kind", "character")
    if kind not in ENTITY_KINDS:
        raise SimError("kind must be character, place or group")
    name = str(e.get("name", "")).strip()
    if not name:
        raise SimError("give it a name")
    if [x for x in entities(pid, active_only=False) if x["id"] != e.get("id") and x["name"].lower() == name.lower()]:
        raise SimError(f"the name {name} is already used")
    data = {k: v for k, v in e.items() if k not in _COLS}
    if kind == "character":
        data.setdefault("alive", True)
        data.setdefault("status", "")
    eid = e.get("id") or new_id("en", name)
    if db.one("SELECT id FROM sim_entities WHERE id=?", (eid,)):
        db.ex("UPDATE sim_entities SET kind=?, name=?, data=?, active=? WHERE id=?", (kind, name, db.jdump(data), 1 if e.get("active", True) else 0, eid))
    else:
        db.ex("INSERT INTO sim_entities(id,project_id,kind,name,data,position,active,created_at) VALUES(?,?,?,?,?,?,1,?)", (eid, pid, kind, name, db.jdump(data), e.get("position", len(entities(pid, active_only=False))), time.time()))
    touch(pid)
    return entity(pid, eid)


def delete_entity(pid: str, eid: str) -> None:
    entity(pid, eid)
    media.ensure()
    for m in media.items(pid, "sim_ref", eid):
        media.delete(m["id"])
    db.ex("DELETE FROM sim_entities WHERE id=? AND project_id=?", (eid, pid))
    touch(pid)


def retire_entity(pid: str, eid: str) -> None:
    """After the story started a person or place is retired, not erased: old chapters still name them, later chapters and prompts leave them out."""
    entity(pid, eid)
    db.ex("UPDATE sim_entities SET active=0 WHERE id=? AND project_id=?", (eid, pid))
    touch(pid)


def purge_entity_refs(pid: str, name: str) -> None:
    """Before the story started: take a deleted person or place out of the trackers that mentioned them (relations with them go, locations, secrets and item holders lose them)."""
    low = name.lower()
    for t in trackers(pid):
        s = t.get("start")
        if t["kind"] == "relation" and low in (str(t.get("a", "")).lower(), str(t.get("b", "")).lower()):
            delete_tracker(pid, t["id"])
        elif t["kind"] == "location":
            at = {w: p for w, p in (s or {}).get("at", {}).items() if w.lower() != low and p.lower() != low}
            save_tracker(pid, {**t, "start": {"at": at, "locked": [p for p in (s or {}).get("locked", []) if p.lower() != low]}})
        elif t["kind"] == "knowledge":
            save_tracker(pid, {**t, "start": {k: [w for w in v if w.lower() != low] for k, v in (s or {}).items()}})
        elif t["kind"] == "items":
            save_tracker(pid, {**t, "start": {n: {**i, "at": "" if str(i.get("at", "")).lower() == low else i.get("at", "")} for n, i in (s or {}).items()}})


def clear_entities(pid: str) -> None:
    ensure()
    db.ex("DELETE FROM sim_entities WHERE project_id=?", (pid,))


def _trk(r: dict) -> dict:
    return {"id": r["id"], "project_id": r["project_id"], "kind": r["kind"], "name": r["name"], "position": r["position"], "active": bool(r["active"]), **db.jload(r["data"], {})}


def trackers(pid: str, active_only: bool = True) -> list[dict]:
    ensure()
    rows = db.q("SELECT * FROM sim_trackers WHERE project_id=?" + (" AND active=1" if active_only else "") + " ORDER BY position", (pid,))
    return [_trk(r) for r in rows]


def save_tracker(pid: str, t: dict) -> dict:
    ensure()
    kind = t.get("kind")
    if kind not in TRACKER_KINDS:
        raise SimError("tracker kind must be one of " + ", ".join(TRACKER_KINDS))
    name = str(t.get("name", "")).strip()
    if not name:
        raise SimError("give the tracker a name")
    if [x for x in trackers(pid, active_only=False) if x["id"] != t.get("id") and x["name"].lower() == name.lower()]:
        raise SimError(f"the tracker name {name} is already used")
    data = {k: v for k, v in t.items() if k not in _COLS}
    tid = t.get("id") or new_id("tk", name)
    if db.one("SELECT id FROM sim_trackers WHERE id=?", (tid,)):
        db.ex("UPDATE sim_trackers SET kind=?, name=?, data=?, active=? WHERE id=?", (kind, name, db.jdump(data), 1 if t.get("active", True) else 0, tid))
    else:
        db.ex("INSERT INTO sim_trackers(id,project_id,kind,name,data,position,active) VALUES(?,?,?,?,?,?,1)", (tid, pid, kind, name, db.jdump(data), len(trackers(pid, active_only=False))))
    touch(pid)
    return next(x for x in trackers(pid, active_only=False) if x["id"] == tid)


def delete_tracker(pid: str, tid: str) -> None:
    db.ex("UPDATE sim_trackers SET active=0 WHERE id=? AND project_id=?", (tid, pid))        # old states keep their numbers; the next chapter drops it
    touch(pid)


def clear_trackers(pid: str) -> None:
    ensure()
    db.ex("DELETE FROM sim_trackers WHERE project_id=?", (pid,))


def guidelines(pid: str, enabled_only: bool = False) -> list[dict]:
    ensure()
    rows = db.q("SELECT * FROM sim_guidelines WHERE project_id=? AND retired=0" + (" AND enabled=1" if enabled_only else "") + " ORDER BY position, created_at", (pid,))
    return [{**r, "enabled": bool(r["enabled"])} for r in rows]


def save_guideline(pid: str, g: dict) -> dict:
    ensure()
    grp, text = g.get("grp", "hard"), str(g.get("text", "")).strip()
    if grp not in GROUPS:
        raise SimError("group must be hard, world, tone or style")
    if not text:
        raise SimError("write the rule")
    gid = g.get("id") or new_id("gl", text)
    if db.one("SELECT id FROM sim_guidelines WHERE id=?", (gid,)):
        db.ex("UPDATE sim_guidelines SET grp=?, text=?, enabled=? WHERE id=?", (grp, text, 1 if g.get("enabled", True) else 0, gid))
    else:
        db.ex("INSERT INTO sim_guidelines(id,project_id,grp,text,enabled,origin,position,created_at) VALUES(?,?,?,?,?,?,?,?)",
              (gid, pid, grp, text, 1 if g.get("enabled", True) else 0, g.get("origin", "owner"), len(guidelines(pid)), time.time()))
    bump_rules(pid)
    return next(x for x in guidelines(pid) if x["id"] == gid)


def retire_guideline(pid: str, gid: str) -> None:
    db.ex("UPDATE sim_guidelines SET retired=1 WHERE id=? AND project_id=?", (gid, pid))        # history keeps the text; it just stops applying
    bump_rules(pid)


def clear_guidelines(pid: str, origin: str = "ai") -> None:
    ensure()
    db.ex("UPDATE sim_guidelines SET retired=1 WHERE project_id=? AND origin=?", (pid, origin))
    bump_rules(pid)


def directives(pid: str) -> list[dict]:
    ensure()
    return [{**r, "timing": db.jload(r["timing"], {})} for r in db.q("SELECT * FROM sim_directives WHERE project_id=? ORDER BY created_at", (pid,))]


def directive(pid: str, did: str) -> dict:
    d = next((x for x in directives(pid) if x["id"] == did), None)
    if not d:
        raise SimError("no such instruction")
    return d


def save_directive(pid: str, d: dict) -> dict:
    ensure()
    kind, text = d.get("kind", "event"), str(d.get("text", "")).strip()
    if kind not in DIRECTIVE_KINDS:
        raise SimError("kind must be event, constraint, twist or steer")
    if not text:
        raise SimError("write the instruction")
    timing = dict(d.get("timing") or {"mode": "next"})
    mode = timing.get("mode")
    if mode not in ("next", "in", "when", "story_time"):
        raise SimError("timing must be next, in, when or story_time")
    if mode == "in":
        timing["chapters"] = max(1, int(timing.get("chapters", 1)))
        if "from" not in timing:
            timing["from"] = len(path(pid))
    if mode in ("when", "story_time") and not (timing.get("condition") or timing.get("tracker") or timing.get("at")):
        raise SimError("say when it should happen")
    did = d.get("id") or new_id("dr", text)
    if db.one("SELECT id FROM sim_directives WHERE id=?", (did,)):
        db.ex("UPDATE sim_directives SET kind=?, text=?, timing=?, status=? WHERE id=?", (kind, text, db.jdump(timing), d.get("status", "pending"), did))
    else:
        db.ex("INSERT INTO sim_directives(id,project_id,kind,text,timing,status,created_at) VALUES(?,?,?,?,?,?,?)", (did, pid, kind, text, db.jdump(timing), "pending", time.time()))
    touch(pid)
    return directive(pid, did)


def cancel_directive(pid: str, did: str) -> None:
    directive(pid, did)
    db.ex("UPDATE sim_directives SET status='cancelled' WHERE id=?", (did,))


# ── chapters ──────────────────────────────────────────────────────────────────

_CH_LISTS = ("focus", "rolls", "options", "fired", "panels")
_CH_JSON = ("focus", "plan", "rolls", "delta", "state_before", "state_after", "options", "chosen", "flags", "fired", "panels")


def _ch(r: dict | None) -> dict | None:
    if r is None:
        return None
    r = dict(r)
    for k in _CH_JSON:
        r[k] = db.jload(r.get(k), [] if k in _CH_LISTS else {})
    return r


def chapter(cid: str) -> dict:
    ensure()
    c = _ch(db.one("SELECT * FROM sim_chapters WHERE id=?", (cid,)))
    if not c:
        raise SimError("no such chapter")
    return c


def chapters(pid: str) -> list[dict]:
    ensure()
    return [_ch(r) for r in db.q("SELECT * FROM sim_chapters WHERE project_id=? ORDER BY created_at", (pid,))]


def children(pid: str, parent_id: str) -> list[dict]:
    ensure()
    return [_ch(r) for r in db.q("SELECT * FROM sim_chapters WHERE project_id=? AND parent_id=? ORDER BY created_at", (pid, parent_id))]


def add_chapter(pid: str, parent_id: str, label: str = "") -> dict:
    ensure()
    idx = (chapter(parent_id)["idx"] + 1) if parent_id else 1
    cid = new_id("sc", pid, parent_id)
    now = time.time()
    db.ex("INSERT INTO sim_chapters(id,project_id,parent_id,idx,branch_label,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (cid, pid, parent_id, idx, label, "writing", now, now))
    return chapter(cid)


def update_chapter(cid: str, **f) -> dict:
    for k in _CH_JSON:
        if k in f:
            f[k] = db.jdump(f[k])
    f["updated_at"] = time.time()
    db.ex(f"UPDATE sim_chapters SET {', '.join(k + '=?' for k in f)} WHERE id=?", (*f.values(), cid))
    return chapter(cid)


def path(pid: str, head_id: str | None = None) -> list[dict]:
    """The chapters from the first one to the head (the project's head by default), in order: the current line of the story."""
    head = project(pid)["head_id"] if head_id is None else head_id
    out: list[dict] = []
    seen: set[str] = set()
    while head and head not in seen:
        seen.add(head)
        c = chapter(head)
        out.append(c)
        head = c["parent_id"]
    return out[::-1]


def delete_chapter(pid: str, cid: str) -> None:
    c = chapter(cid)
    if c["project_id"] != pid:
        raise SimError("no such chapter")
    if children(pid, cid):
        raise SimError("only the last chapter of a line can be deleted; it has chapters after it")
    media.ensure()
    for m in media.items(pid, "sim_panel"):
        if m["key"].startswith(cid + ":"):
            delete_panel_media(pid, m["key"])
    drop_chapter_memory(cid)
    db.ex("DELETE FROM sim_chapters WHERE id=?", (cid,))
    if project(pid)["head_id"] == cid:
        save_project(pid, head_id=c["parent_id"])


def delete_panel_media(pid: str, key: str) -> None:
    """Remove every attempt of one picture, with the lettered copy next to it."""
    media.ensure()
    for m in media.items(pid, "sim_panel", key):
        if m["file"]:
            (media.media_dir(pid) / m["file"].replace(".png", "-cap.png")).unlink(missing_ok=True)
        media.delete(m["id"])


# ── memory rows ───────────────────────────────────────────────────────────────

def add_fact(pid: str, cid: str, text: str, names: list[str], tags: list[str]) -> None:
    db.ex("INSERT INTO sim_facts(id,project_id,chapter_id,text,tags,entity_names,created_at) VALUES(?,?,?,?,?,?,?)", (new_id("fc", text), pid, cid, text, db.jdump(tags), db.jdump(names), time.time()))


def facts(pid: str) -> list[dict]:
    ensure()
    return [{**r, "tags": db.jload(r["tags"], []), "entity_names": db.jload(r["entity_names"], [])} for r in db.q("SELECT * FROM sim_facts WHERE project_id=? AND retired=0 ORDER BY created_at", (pid,))]


def add_thread(pid: str, cid: str, text: str) -> str:
    ensure()
    tid = new_id("th", text)
    db.ex("INSERT INTO sim_threads(id,project_id,text,opened_in) VALUES(?,?,?,?)", (tid, pid, text, cid))
    return tid


def threads(pid: str) -> list[dict]:
    ensure()
    return db.q("SELECT * FROM sim_threads WHERE project_id=? ORDER BY rowid", (pid,))


def close_thread(tid: str, cid: str) -> None:
    db.ex("UPDATE sim_threads SET closed_in=?, status='closed' WHERE id=?", (cid, tid))


def drop_chapter_memory(cid: str) -> None:
    """A rewritten or deleted chapter takes back the facts and threads it added (and reopens the threads it closed)."""
    db.ex("DELETE FROM sim_facts WHERE chapter_id=?", (cid,))
    db.ex("DELETE FROM sim_threads WHERE opened_in=?", (cid,))
    db.ex("UPDATE sim_threads SET closed_in='', status='open' WHERE closed_in=?", (cid,))


# ── runs, templates, start-up repair ──────────────────────────────────────────

def run_info(pid: str) -> dict:
    ensure()
    r = db.one("SELECT data FROM sim_runs WHERE project_id=?", (pid,))
    return db.jload(r["data"], {}) if r else {}


def set_run(pid: str, replace: bool = False, **data) -> None:
    ensure()
    cur = {} if replace else run_info(pid)
    cur.update(data)
    db.ex("INSERT INTO sim_runs(project_id,data) VALUES(?,?) ON CONFLICT(project_id) DO UPDATE SET data=excluded.data", (pid, db.jdump(cur)))


def repair() -> int:
    """At start-up: a chapter left 'writing' by a stopped server is marked failed, so no screen shows a ghost job."""
    ensure()
    with db.tx() as c:
        return c.execute("UPDATE sim_chapters SET status='failed' WHERE status='writing'").rowcount


def templates() -> list[dict]:
    ensure()
    return [{**r, "data": db.jload(r["data"], {})} for r in db.q("SELECT * FROM sim_templates ORDER BY created_at")]


def save_template(name: str, data: dict) -> dict:
    ensure()
    tid = new_id("tp", name)
    db.ex("INSERT INTO sim_templates(id,name,data,builtin,created_at) VALUES(?,?,?,0,?)", (tid, name.strip() or "My template", db.jdump(data), time.time()))
    return next(t for t in templates() if t["id"] == tid)
