"""Storage for the character library. One row per character or place in table `chars` (columns for what a list shows, one JSON blob for the rest). Pictures are rows of the existing
`media` table with the character's id as `plan_id` (story3/store.py), so numbered attempts and one-approved-per-key come with it. Kinds: char_gen (drawn from text, per view),
char_sheet (made from the canon by edit, per view). Nothing is overwritten; every picture records the recipe it was made from."""
import hashlib
import json
import shutil
from pathlib import Path

from story import db
from story2 import describe
from story3 import store as media

from . import render

SCHEMA = """
CREATE TABLE IF NOT EXISTS chars(
  id TEXT PRIMARY KEY, name TEXT DEFAULT '', kind TEXT DEFAULT 'person', status TEXT DEFAULT 'draft', data TEXT DEFAULT '{}', created_at REAL, updated_at REAL
);
"""
COLUMNS = ("id", "name", "kind", "status", "created_at", "updated_at")
GEN, SHEET, EDIT = "char_gen", "char_sheet", "char_edit"
KINDS = ("person", "place")
RIGHTS = ("invented", "own", "consent", "licensed")          # basis for a character made from a picture of a real person: own = it is the owner, consent = the person agreed
CANON_VIEWS = {"person": ("portrait", "body"), "place": ("place",)}


class CharError(Exception):
    pass


def ensure() -> None:
    with db.tx() as c:
        c.executescript(SCHEMA)
    media.ensure()


def _load(r: dict | None) -> dict | None:
    if r is None:
        return None
    data = db.jload(r.pop("data"), {})
    return {**data, **r}


def get(char_id: str) -> dict:
    ensure()
    c = _load(db.one("SELECT * FROM chars WHERE id=?", (char_id,)))
    if not c:
        raise CharError(f"no such character: {char_id}")
    return c


def listing(kind: str = "") -> list[dict]:
    ensure()
    rows = db.q("SELECT * FROM chars WHERE kind=? ORDER BY updated_at DESC", (kind,)) if kind else db.q("SELECT * FROM chars ORDER BY updated_at DESC")
    return [_load(r) for r in rows]


def create(name: str, kind: str = "person", slots: dict | None = None, extra: dict | None = None) -> dict:
    ensure()
    if kind not in KINDS:
        raise CharError(f"kind is one of: {', '.join(KINDS)}")
    cid = f"ch-{hashlib.sha1(f'{name}{kind}{db.now()}'.encode()).hexdigest()[:8]}"
    data = {"idea": "", "slots": describe.clean(slots), "personality": "", "render": render.default(), "tags": [], "notes": "", "canon": {}, "version": 1,
            "rights": {"basis": "invented", "confirmed": True, "note": ""}, "source_photo": "", "looks": [], "recipes": [], **(extra or {})}
    data["render"] = render.clean(data["render"])
    db.ex("INSERT INTO chars(id,name,kind,status,data,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (cid, name.strip() or "Untitled", kind, "draft", db.jdump(data), db.now(), db.now()))
    return get(cid)


def save(char: dict) -> dict:
    data = {k: v for k, v in char.items() if k not in COLUMNS}
    char["status"] = "ready" if all(char["canon"].get(v) for v in CANON_VIEWS[char["kind"]]) else "draft"
    db.ex("UPDATE chars SET name=?, kind=?, status=?, data=?, updated_at=? WHERE id=?", (char["name"], char["kind"], char["status"], db.jdump(data), db.now(), char["id"]))
    return get(char["id"])


def delete(char_id: str) -> None:
    ensure()
    db.ex("DELETE FROM chars WHERE id=?", (char_id,))
    db.ex("DELETE FROM media WHERE plan_id=?", (char_id,))
    shutil.rmtree(media.media_dir(char_id), ignore_errors=True)


def media_dir(char_id: str, sub: str = "") -> Path:
    return media.media_dir(char_id, sub)


def photo_path(char: dict) -> Path | None:
    rel = char.get("source_photo") or ""
    p = media_dir(char["id"]) / rel if rel else None
    return p if p and p.is_file() else None


# ── identity ────────────────────────────────────────────────────────────────

def identity_hash(char: dict) -> str:
    """What the face and body were drawn from: the slots, the render setting and the source photo. A picture made under another hash is kept but shown as 'older'."""
    photo = photo_path(char)
    key = json.dumps({"slots": char["slots"], "render": char["render"], "photo": hashlib.sha1(photo.read_bytes()).hexdigest()[:12] if photo else ""}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def canon_items(char: dict) -> dict[str, dict]:
    out = {}
    for view, iid in (char.get("canon") or {}).items():
        it = media.get(iid) if iid else None
        if it and it["status"] == "done" and it["file"]:
            out[view] = it
    return out


def locked(char: dict) -> bool:
    """The render style, model and LoRAs cannot change once a canon picture is approved."""
    return bool(char.get("canon"))
