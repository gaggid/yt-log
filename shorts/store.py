"""Storage for shorts. One row per short in table `shorts` (columns for what a list shows, one JSON blob for the rest). Pictures, voice, clips and the final video are
rows of the existing `media` table with the short's id as `plan_id` (story3/store.py), so numbered attempts and one-approved-per-key come with it. Kinds: short_key
(keyframe), short_clip, short_voice, short_final."""
import hashlib
from pathlib import Path

from story import db
from story3 import store as media

SCHEMA = """
CREATE TABLE IF NOT EXISTS shorts(
  id TEXT PRIMARY KEY, title TEXT DEFAULT '', pipeline TEXT, status TEXT DEFAULT 'new', data TEXT DEFAULT '{}', created_at REAL, updated_at REAL
);
"""
COLUMNS = ("id", "title", "pipeline", "status", "created_at", "updated_at")
KEY, CLIP, VOICE, FINAL = "short_key", "short_clip", "short_voice", "short_final"

DEFAULT_SETTINGS = {
    "image_mode": "qwen",             # qwen (the image model draws every start picture) | anchor (the user's picture of the main character, the rest drawn) | per_shot (the user's picture for chosen shots, the rest drawn) | wan (no start pictures: Wan decides)
    "image_model": "qwen-image-2.1",  # the gateway's image model that draws the start pictures
    "size": "480x832",
    "steps": None,                    # None = the model's final-quality default (shorts/pipelines.py)
    "chain": True,                    # quick pipeline: a shot marked "continues" starts from the last frame of the one before
    "seed": 7,
    "voice": {"engine": "maya-tts", "voice": "Siddhant"},
    "captions": True,
    "bed": True,                      # the quiet sound bed under the voice
    "review_keyframes": True,         # keyframe pipeline: auto-run stops once for the contact sheet
    "language": "hinglish",
    "cast": [],                       # characters from the Character Studio library: [{"character_id", "look_id"}], at most two people (shorts/cast.py)
    "place_id": "",                   # a place from the library
    "target_s": 30,                   # desired video length in seconds (default 30; shorter values are supported)
}


class ShortError(Exception):
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


def get(short_id: str) -> dict:
    ensure()
    s = _load(db.one("SELECT * FROM shorts WHERE id=?", (short_id,)))
    if not s:
        raise ShortError(f"no such short: {short_id}")
    return s


def listing() -> list[dict]:
    ensure()
    return [_load(r) for r in db.q("SELECT * FROM shorts ORDER BY created_at DESC")]


def create(title: str, pipeline: str, source: dict, settings: dict | None = None, extra: dict | None = None) -> dict:
    ensure()
    sid = f"sh-{hashlib.sha1(f'{title}{pipeline}{db.now()}'.encode()).hexdigest()[:8]}"
    data = {"source": source, "settings": {**DEFAULT_SETTINGS, **(settings or {})}, "plan": {}, "beats": [], "shots": [], "images": {"anchor": "", "shots": {}},
            "keyframes_confirmed": False, **(extra or {})}
    db.ex("INSERT INTO shorts(id,title,pipeline,status,data,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (sid, title, pipeline, "new", db.jdump(data), db.now(), db.now()))
    return get(sid)


def save(short: dict) -> dict:
    """Write the whole short back (a step reads it, changes it and saves it)."""
    data = {k: v for k, v in short.items() if k not in COLUMNS}
    db.ex("UPDATE shorts SET title=?, pipeline=?, status=?, data=?, updated_at=? WHERE id=?",
          (short.get("title", ""), short["pipeline"], short.get("status", "new"), db.jdump(data), db.now(), short["id"]))
    return get(short["id"])


def delete(short_id: str) -> None:
    ensure()
    db.ex("DELETE FROM shorts WHERE id=?", (short_id,))
    db.ex("DELETE FROM media WHERE plan_id=?", (short_id,))


def shot_by_id(short: dict, shot_id: str) -> dict:
    for s in short["shots"]:
        if s["id"] == shot_id:
            return s
    raise ShortError(f"no such shot: {shot_id}")


def media_dir(short_id: str, sub: str = "") -> Path:
    return media.media_dir(short_id, sub)


def image_path(short: dict, rel: str) -> Path | None:
    """A picture the user gave (stored relative to the short's media folder), or None when missing."""
    if not rel:
        return None
    p = media_dir(short["id"]) / rel
    return p if p.is_file() else None


# ── which attempt counts ────────────────────────────────────────────────────

def chosen(short_id: str, kind: str, key: str, need: str = "") -> dict | None:
    """The approved attempt of (kind, key), else the latest finished one. `need` (a hash) restricts to attempts made from the same inputs."""
    its = [i for i in media.items(short_id, kind, key) if i["status"] == "done" and i["file"] and (not need or i["meta"].get("input_hash") == need)]
    ok = [i for i in its if i["approved"]]
    return (ok or its[-1:] or [None])[0]


def input_hash(*parts) -> str:
    return hashlib.sha1("\n".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:12]
