"""Storage for relaxation sessions. One row per session in `relaxation_sessions`;
generated assets (scene image, rain clip, audio, final video) are rows in the existing
`media` table (story3/store.py) with the session's id as `plan_id`."""
import hashlib
from pathlib import Path

from story import db
from story3 import store as media

from . import models as M

SCHEMA = """
CREATE TABLE IF NOT EXISTS relaxation_sessions(
  id TEXT PRIMARY KEY,
  title TEXT DEFAULT '',
  status TEXT DEFAULT 'new',
  step TEXT DEFAULT '',
  data TEXT DEFAULT '{}',
  created_at REAL,
  updated_at REAL
);
CREATE TABLE IF NOT EXISTS relaxation_config(
  id INTEGER PRIMARY KEY CHECK (id = 1),
  data TEXT DEFAULT '{}'
);
"""

# status values
NEW = "new"
RUNNING = "running"
READY = "ready"
UPLOADING = "uploading"
UPLOADED = "uploaded"
FAILED = "failed"


class SessionError(Exception):
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


def get(session_id: str) -> dict:
    ensure()
    s = _load(db.one("SELECT * FROM relaxation_sessions WHERE id=?", (session_id,)))
    if not s:
        raise SessionError(f"no such session: {session_id}")
    return s


def list_all() -> list[dict]:
    ensure()
    rows = db.q("SELECT * FROM relaxation_sessions ORDER BY created_at DESC")
    return [_load(r) for r in rows]


def _data_cols(s: dict) -> tuple[dict, dict]:
    """Split a session dict into table columns vs JSON blob fields."""
    cols = {k: s[k] for k in ("id", "title", "status", "step") if k in s}
    blob = {k: v for k, v in s.items() if k not in ("id", "title", "status", "step", "created_at", "updated_at")}
    return cols, blob


def create(scene: str | None = None, hours: int | None = None, minutes: int | None = None) -> dict:
    ensure()
    sid = M.session_id()
    from . import variety
    settings = {**M.DEFAULT_SETTINGS, **variety.choose(scene)}      # theme (when not chosen), seed and music: different from the last videos
    if hours and 1 <= hours <= 8:
        settings["hours"] = hours
    if minutes and 1 <= minutes <= 480:
        settings["minutes"] = minutes      # wins over `hours` (M.total_s)
    scene_label = M.SCENES[settings["scene"]]["label"]
    import time
    from datetime import date
    title = f"{scene_label} Rain | {date.today().isoformat()}"
    s: dict = {
        "id": sid,
        "title": title,
        "status": NEW,
        "step": "",
        "settings": settings,
        "scene_item_id": "",
        "rain_item_id": "",
        "audio_item_id": "",
        "final_item_id": "",
        "publish": {},
        "youtube_video_id": "",
        "error": "",
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    _, blob = _data_cols(s)
    db.ex(
        "INSERT INTO relaxation_sessions(id,title,status,step,data,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
        (sid, s["title"], s["status"], s["step"], db.jdump(blob), s["created_at"], s["updated_at"]),
    )
    return get(sid)


def save(s: dict) -> dict:
    """Persist the full session dict (all fields except created_at are overwritten)."""
    ensure()
    import time
    s["updated_at"] = time.time()
    _, blob = _data_cols(s)
    db.ex(
        "UPDATE relaxation_sessions SET title=?,status=?,step=?,data=?,updated_at=? WHERE id=?",
        (s.get("title", ""), s.get("status", NEW), s.get("step", ""), db.jdump(blob), s["updated_at"], s["id"]),
    )
    return get(s["id"])


def set_error(session_id: str, msg: str) -> dict:
    s = get(session_id)
    s["status"] = FAILED
    s["error"] = msg[:500]
    return save(s)


def delete(session_id: str) -> None:
    ensure()
    db.ex("DELETE FROM relaxation_sessions WHERE id=?", (session_id,))
    # media rows cleaned by cascade through the shared media table
    for item in media.items(session_id):
        if not item.get("file"):
            continue
        try:
            p = media.path_of(item)
            if p.is_file():
                p.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
    db.ex("DELETE FROM media WHERE plan_id=?", (session_id,))
    # remove the media folder if empty
    folder = media.media_dir(session_id)
    try:
        if folder.exists() and not any(folder.iterdir()):
            folder.rmdir()
    except OSError:
        pass


def chosen(session_id: str, kind: str) -> dict | None:
    """The latest done item of this kind for a session (approved first)."""
    items = [i for i in media.items(session_id, kind) if i["status"] == "done" and i["file"]]
    ok = [i for i in items if i["approved"]]
    return (ok or items)[-1] if (ok or items) else None


def view(s: dict) -> dict:
    """The session dict augmented with per-step status for the UI."""
    out = {**s}
    for key, kind in (("scene", M.KIND_SCENE), ("rain", M.KIND_RAIN), ("audio", M.KIND_AUDIO), ("final", M.KIND_FINAL)):
        item = chosen(s["id"], kind)
        out[f"{key}_ready"] = bool(item)
        if item:
            if kind == M.KIND_FINAL:
                out["final_url"] = f"/api/relaxation/{s['id']}/download"
            elif kind == M.KIND_SCENE:
                out["scene_url"] = f"/api/media/file/{s['id']}/{item['file']}"
    tracks = [i for i in media.items(s["id"], "music", "bgm") if i["status"] == "done" and i["file"]]
    if tracks:
        out["music_url"] = f"/api/media/file/{s['id']}/{tracks[-1]['file']}"
    au = chosen(s["id"], M.KIND_AUDIO)
    if au and au["meta"].get("music_error"):
        out["music_error"] = au["meta"]["music_error"]
    th = chosen(s["id"], M.KIND_THUMB)
    if th:
        out["thumb_url"] = f"/api/media/file/{s['id']}/{th['file']}"
    return out


def repair() -> int:
    """At start-up: a session still marked running/uploading belonged to a job that died with the previous process.
    Mark it failed (so the Generate button works again; finished steps are kept and skipped). Returns how many."""
    ensure()
    n = 0
    for s in list_all():
        if s.get("status") in (RUNNING, UPLOADING):
            s["status"] = FAILED
            s["step"] = ""
            s["error"] = "interrupted: the app restarted while this was running. Press Generate to continue; finished steps are kept."
            save(s)
            n += 1
    return n
