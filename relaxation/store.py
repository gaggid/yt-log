"""Storage for relaxation sessions. One row per session in `relaxation_sessions`;
generated assets (scene image, rain clip, audio, final video) are rows in the existing
`media` table (story3/store.py) with the session's id as `plan_id`."""
import hashlib
import shutil
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
    settings = {**M.DEFAULT_SETTINGS, "rain_engine": M.RAIN_ENGINE, "youtube_slot": M.YOUTUBE_SLOT, **variety.choose(scene)}      # theme (when not chosen), seed and music: different from the last videos
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
    # the whole folder: it holds only this session's files (some, like the 2K clip, have no media row)
    shutil.rmtree(media.media_dir(session_id), ignore_errors=True)


def chosen(session_id: str, kind: str) -> dict | None:
    """The latest done item of this kind for a session (approved first)."""
    items = [i for i in media.items(session_id, kind) if i["status"] == "done" and i["file"]]
    ok = [i for i in items if i["approved"]]
    return (ok or items)[-1] if (ok or items) else None


def drop_after_upload(session_id: str) -> int:
    """After the video is on YouTube the local copy is not needed: remove the finished video (about 18 GB for 3 hours), the 2K rain clip
    and the audio mix. Kept: scene picture, 720p rain clip, music takes, thumbnail (small; they make the video again if ever wanted).
    The rows stay with no file and `meta.removed_after_upload`. Only when the session has a YouTube id. Returns the bytes freed."""
    if not get(session_id).get("youtube_video_id"):
        return 0
    freed = 0
    for kind in (M.KIND_FINAL, M.KIND_AUDIO):
        for it in media.items(session_id, kind):
            if it["file"]:
                p = media.path_of(it)
                try:
                    freed += p.stat().st_size
                    p.unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    continue
                media.update(it["id"], file="", meta={"removed_after_upload": True})
    for p in media.media_dir(session_id).glob("rain/*-2k.mp4"):
        try:
            freed += p.stat().st_size
            p.unlink()
        except OSError:
            pass
    return freed


def view(s: dict) -> dict:
    """The session dict augmented with per-step status for the UI."""
    out = {**s}
    out["video_removed"] = bool(s.get("youtube_video_id")) and not chosen(s["id"], M.KIND_FINAL)
    final_done = bool(chosen(s["id"], M.KIND_FINAL))
    for key, kind in (("scene", M.KIND_SCENE), ("rain", M.KIND_RAIN), ("audio", M.KIND_AUDIO), ("final", M.KIND_FINAL)):
        item = chosen(s["id"], kind)
        out[f"{key}_ready"] = bool(item)
        if item:
            if kind == M.KIND_FINAL:
                out["final_url"] = f"/api/relaxation/{s['id']}/download"
                out["stream_url"] = f"/api/relaxation/{s['id']}/stream?v={item.get('updated_at') or item['id']}"     # new music changes the file
            elif kind == M.KIND_SCENE:
                out["scene_url"] = f"/api/media/file/{s['id']}/{item['file']}"
    if final_done:
        out["audio_ready"] = True                      # the mix is removed once the video is built (see audio.drop_mix)
    tracks = [i for i in media.items(s["id"], "music", "bgm") if i["status"] == "done" and i["file"]]
    if tracks:
        out["music_url"] = f"/api/media/file/{s['id']}/{tracks[-1]['file']}"
    au = chosen(s["id"], M.KIND_AUDIO)
    if au and au["meta"].get("music_error"):
        out["music_error"] = au["meta"]["music_error"]
    rn = chosen(s["id"], M.KIND_RAIN)
    if rn and rn["meta"].get("motion"):
        from . import motion
        out["rain_motion"] = rn["meta"]["motion"]
        out["rain_weak"] = motion.weak(rn["meta"]["motion"])
    try:                                          # the channel this video will be posted to, from its own connection slot
        from youtube import api as ytapi
        slot = (s.get("settings") or {}).get("youtube_slot") or M.YOUTUBE_SLOT
        st = ytapi.slot_status(slot)
        out["youtube_slot"] = slot
        out["youtube_channel_name"] = st["channel"] or st["label"]
        out["youtube_ready"] = bool(st["connected"] and st["upload"])
    except Exception:  # noqa: BLE001 - the page works without it
        out["youtube_ready"] = False
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
