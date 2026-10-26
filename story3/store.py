"""Phase 3 table and file layout. One row per generated file (an "attempt"); nothing is overwritten, approval picks the one that counts."""
import hashlib
import wave
from pathlib import Path

import config
from story import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS media(
  id TEXT PRIMARY KEY, plan_id TEXT, export_rev INTEGER DEFAULT 0, kind TEXT, key TEXT, attempt INTEGER DEFAULT 1,
  status TEXT DEFAULT 'queued', file TEXT DEFAULT '', meta TEXT DEFAULT '{}', approved INTEGER DEFAULT 0, created_at REAL, updated_at REAL
);
CREATE INDEX IF NOT EXISTS media_plan ON media(plan_id, kind, key);
"""


def ensure() -> None:
    with db.tx() as c:
        c.executescript(SCHEMA)


def media_dir(plan_id: str, sub: str = "") -> Path:
    d = config.DATA_DIR / "media" / plan_id / sub if sub else config.DATA_DIR / "media" / plan_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _row(r: dict | None) -> dict | None:
    if r is None:
        return None
    r["meta"] = db.jload(r["meta"], {})
    r["approved"] = bool(r["approved"])
    return r


def items(plan_id: str, kind: str = "", key: str = "") -> list[dict]:
    ensure()
    where, args = ["plan_id=?"], [plan_id]
    if kind:
        where.append("kind=?")
        args.append(kind)
    if key:
        where.append("key=?")
        args.append(key)
    return [_row(r) for r in db.q(f"SELECT * FROM media WHERE {' AND '.join(where)} ORDER BY kind, key, attempt", args)]


def get(item_id: str) -> dict | None:
    ensure()
    return _row(db.one("SELECT * FROM media WHERE id=?", (item_id,)))


def add(plan_id: str, kind: str, key: str, export_rev: int = 0, status: str = "running", meta: dict | None = None) -> dict:
    ensure()
    n = (db.one("SELECT MAX(attempt) m FROM media WHERE plan_id=? AND kind=? AND key=?", (plan_id, kind, key)) or {}).get("m") or 0
    iid = f"md-{hashlib.sha1(f'{plan_id}{kind}{key}{n + 1}{db.now()}'.encode()).hexdigest()[:8]}"
    db.ex("INSERT INTO media(id,plan_id,export_rev,kind,key,attempt,status,meta,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
          (iid, plan_id, export_rev, kind, key, n + 1, status, db.jdump(meta or {}), db.now(), db.now()))
    return get(iid)


def update(item_id: str, **f) -> dict:
    cur = get(item_id)
    meta = {**cur["meta"], **(f.pop("meta", None) or {})}
    sets = {"meta": db.jdump(meta), "updated_at": db.now(), **f}
    db.ex(f"UPDATE media SET {', '.join(k + '=?' for k in sets)} WHERE id=?", [*sets.values(), item_id])
    return get(item_id)


def approve(item_id: str, on: bool = True) -> dict:
    """One approved attempt per (kind, key): approving one un-approves its siblings."""
    it = get(item_id)
    if on:
        db.ex("UPDATE media SET approved=0 WHERE plan_id=? AND kind=? AND key=?", (it["plan_id"], it["kind"], it["key"]))
    db.ex("UPDATE media SET approved=?, updated_at=? WHERE id=?", (1 if on else 0, db.now(), item_id))
    return get(item_id)


def path_of(it: dict) -> Path:
    return media_dir(it["plan_id"]) / it["file"]


def wav_seconds(data: bytes | Path) -> float:
    with wave.open(__import__("io").BytesIO(data) if isinstance(data, bytes) else str(data)) as w:
        return w.getnframes() / w.getframerate()


# ── voice: which attempt counts, and how long it really is ──────────────────

def text_hash(text: str, voice: str) -> str:
    """`voice` is the voice key (`voices.key`): the bare voice name for Svara, `engine:voice` otherwise."""
    return hashlib.sha1(f"{voice}\n{text}".encode("utf-8")).hexdigest()[:12]


def segment_hash(seg: dict, voice: str) -> str:
    from story2 import voices
    return text_hash(voices.text_for(voice, seg), voice)


def voice_key(plan: dict) -> str:
    from story2 import voices
    return voices.key(voices.current(plan["narrator"]))


def chosen_voice(plan_id: str, seg: dict, voice: str) -> dict | None:
    """The approved attempt for this segment, else the latest finished one, as long as it was made from the segment's current wording."""
    want = segment_hash(seg, voice)
    good = [i for i in items(plan_id, "voice", seg["id"]) if i["status"] == "done" and i["meta"].get("text_hash") == want]
    ok = [i for i in good if i["approved"]]
    return (ok or good[-1:] or [None])[0] if good else None


def audio_seconds(plan_id: str) -> dict[str, float]:
    """segment id -> real spoken seconds, for segments whose audio matches their current wording. Used to retime scenes to the real voice."""
    from story2 import planner
    plan = planner.get_plan(plan_id)
    voice = voice_key(plan)
    out = {}
    for seg in plan["segments"]:
        it = chosen_voice(plan_id, seg, voice)
        if it and it["meta"].get("duration_s"):
            out[seg["id"]] = float(it["meta"]["duration_s"])
    return out
