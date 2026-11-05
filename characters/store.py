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
CREATE TABLE IF NOT EXISTS char_life_events(
  id TEXT PRIMARY KEY, char_id TEXT NOT NULL, event_type TEXT NOT NULL, trigger TEXT NOT NULL,
  attempt INTEGER DEFAULT 1, inputs TEXT DEFAULT '{}', outputs TEXT DEFAULT '{}', created_at REAL
);
CREATE TABLE IF NOT EXISTS char_memories(
  id TEXT PRIMARY KEY, char_id TEXT NOT NULL, content TEXT NOT NULL,
  tags TEXT DEFAULT '[]', category TEXT DEFAULT 'episodic',
  base_strength REAL DEFAULT 1.0, formed_at REAL, last_accessed_at REAL,
  source TEXT DEFAULT 'think', stable INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS char_memory_bonds(
  id TEXT PRIMARY KEY, char_id TEXT NOT NULL,
  mem_a TEXT NOT NULL, mem_b TEXT NOT NULL,
  co_recalls INTEGER DEFAULT 1,
  bond_strength REAL DEFAULT 0.1,
  last_corecall_at REAL,
  formed_at REAL,
  UNIQUE(mem_a, mem_b)
);
CREATE INDEX IF NOT EXISTS cmb_char ON char_memory_bonds(char_id);
CREATE INDEX IF NOT EXISTS cmb_a ON char_memory_bonds(mem_a);
CREATE INDEX IF NOT EXISTS cmb_b ON char_memory_bonds(mem_b);
CREATE TABLE IF NOT EXISTS char_profile_snapshots(
  id TEXT PRIMARY KEY, char_id TEXT NOT NULL, snapshot_date TEXT NOT NULL,
  interests_json TEXT DEFAULT '{}', curiosities_json TEXT DEFAULT '[]',
  energy INTEGER DEFAULT 80, feeling_primary TEXT DEFAULT '', feeling_intensity INTEGER DEFAULT 5,
  memory_counts_json TEXT DEFAULT '{}', web_surfs_today INTEGER DEFAULT 0,
  created_at REAL,
  UNIQUE(char_id, snapshot_date)
);
CREATE TABLE IF NOT EXISTS char_books(
  id TEXT PRIMARY KEY, char_id TEXT NOT NULL,
  title TEXT NOT NULL, author TEXT DEFAULT '', synopsis TEXT DEFAULT '',
  series_name TEXT DEFAULT '', series_order INTEGER DEFAULT 0,
  status TEXT DEFAULT 'wishlist',
  current_chapter INTEGER DEFAULT 0, total_chapters INTEGER DEFAULT 0,
  added_at REAL, started_at REAL, finished_at REAL,
  skip_reason TEXT DEFAULT '', resurfaced_at REAL
);
CREATE INDEX IF NOT EXISTS cb_char ON char_books(char_id, status);
CREATE TABLE IF NOT EXISTS char_book_chapters(
  id TEXT PRIMARY KEY, book_id TEXT NOT NULL,
  chapter_index INTEGER NOT NULL,
  impressions_json TEXT DEFAULT '[]',
  processed_at REAL,
  UNIQUE(book_id, chapter_index)
);
"""
COLUMNS = ("id", "name", "kind", "status", "created_at", "updated_at")
GEN, SHEET, EDIT = "char_gen", "char_sheet", "char_edit"
KINDS = ("person", "place")
RIGHTS = ("invented", "own", "consent", "licensed")          # basis for a character made from a picture of a real person: own = it is the owner, consent = the person agreed
DECLARED = {"person": ("ethnicity", "gender", "age", "skin", "build"), "place": ("ethnicity",)}      # only the person decides these; the model never invents or changes them
DECLARED_LABEL = {"ethnicity": "ethnicity", "gender": "gender (male or female)", "age": "age", "skin": "skin tone", "build": "build"}
GENDER_WORDS = {"male": ("man", "boy"), "female": ("woman", "girl")}
CANON_VIEWS = {"person": ("portrait", "body"), "place": ("place",)}


class CharError(Exception):
    pass


def ensure() -> None:
    with db.tx() as c:
        c.executescript(SCHEMA)
        # migrate existing char_memories rows — add columns if absent
        have = {r[1] for r in c.execute("PRAGMA table_info(char_memories)")}
        if "source" not in have:
            c.execute("ALTER TABLE char_memories ADD COLUMN source TEXT DEFAULT 'think'")
        if "stable" not in have:
            c.execute("ALTER TABLE char_memories ADD COLUMN stable INTEGER DEFAULT 0")
        # migrate char_profile_snapshots — web_surfs_today added after initial deploy
        snap_have = {r[1] for r in c.execute("PRAGMA table_info(char_profile_snapshots)")}
        if "web_surfs_today" not in snap_have:
            c.execute("ALTER TABLE char_profile_snapshots ADD COLUMN web_surfs_today INTEGER DEFAULT 0")
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


def glamour_problem(char: dict) -> str:
    """Why glamour styling cannot be used for this character, or "" when it can. It is for adult, invented people only: a declared age of 21 or more, and never a person drawn from a
    photograph (a photo is consent to a likeness, not to this)."""
    from . import choices
    if char.get("kind") != "person":
        return "glamour styling is for people"
    age = str((char.get("declared") or {}).get("age") or (char.get("slots") or {}).get("age") or "")
    digits = "".join(ch for ch in age if ch.isdigit())
    if not digits or int(digits) < choices.GLAMOUR_MIN_AGE:
        return f"glamour styling needs a declared adult age of {choices.GLAMOUR_MIN_AGE} or more"
    if char.get("source_photo") or (char.get("rights") or {}).get("basis") not in ("invented", None, ""):
        return "glamour styling is only for invented characters, not for a person drawn from a photograph"
    return ""


def create(name: str, kind: str = "person", slots: dict | None = None, extra: dict | None = None) -> dict:
    ensure()
    if kind not in KINDS:
        raise CharError(f"kind is one of: {', '.join(KINDS)}")
    cid = f"ch-{hashlib.sha1(f'{name}{kind}{db.now()}'.encode()).hexdigest()[:8]}"
    data = {"idea": "", "slots": describe.clean(slots), "personality": "", "render": render.default(), "tags": [], "notes": "", "canon": {}, "version": 1,
            "rights": {"basis": "invented", "confirmed": True, "note": ""}, "source_photo": "", "looks": [], "recipes": [], "declared": {}, "styling": "", "avatar": {}, **(extra or {})}
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


def clean_declared(kind: str, declared: dict | None) -> dict[str, str]:
    d = {k: " ".join(str(v).split()).strip() for k, v in (declared or {}).items() if k in DECLARED[kind] and v is not None and str(v).strip()}
    if "gender" in d:
        g = d["gender"].lower()
        if g not in GENDER_WORDS:
            raise CharError("gender is male or female, as you declare it")
        d["gender"] = g
    if "age" in d and not d["age"].isdigit():
        raise CharError("age is a number of years")
    return d


def missing_declared(char: dict) -> list[str]:
    d = char.get("declared") or {}
    return [k for k in DECLARED[char["kind"]] if not d.get(k)]


def apply_declared(char: dict) -> dict:
    """Write the declared facts into the slots (the slot words an image model needs: man or woman, boy or girl by age). Returns the slots."""
    d = char.get("declared") or {}
    slots = dict(char["slots"])
    if d.get("ethnicity"):
        slots["ethnicity"] = d["ethnicity"]
    if d.get("gender"):
        young = d.get("age", "99").isdigit() and int(d.get("age", 99)) < 18
        slots["gender"] = GENDER_WORDS[d["gender"]][1 if young else 0]
    for k in ("age", "skin", "build"):
        if d.get(k):
            slots[k] = d[k]
    allowed = {k for k, _ in describe.SLOTS[char["kind"]]}                       # a place has no ethnicity slot: its region goes into the words (requests.identity_text)
    return {k: v for k, v in slots.items() if v and k in allowed}
