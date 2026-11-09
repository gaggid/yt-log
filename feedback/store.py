"""Tables of the feedback loop: frozen idea features and grades (`idea_outcomes`), tags of channel videos (`yt_video_tags`), Playbook versions (`playbooks`), the owner's pinned principles
(`playbook_pins`), public comments of the best videos (`yt_comments`) and small state (`fb_kv`)."""
import time

from story import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS idea_outcomes(
  idea_id TEXT PRIMARY KEY, short_id TEXT DEFAULT '', video_id TEXT DEFAULT '', features TEXT DEFAULT '{}', frozen_at REAL DEFAULT 0,
  metrics TEXT DEFAULT '{}', grade REAL, early_grade REAL, partial INTEGER DEFAULT 0, label TEXT DEFAULT '', stage TEXT DEFAULT 'pending', remixed INTEGER DEFAULT 0, updated_at REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS yt_video_tags(video_id TEXT PRIMARY KEY, territory TEXT DEFAULT '', tagged_at REAL);
CREATE TABLE IF NOT EXISTS playbooks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, version INTEGER, status TEXT DEFAULT 'draft', data TEXT DEFAULT '{}', created_at REAL, decided_at REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS playbook_pins(id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS yt_comments(comment_id TEXT PRIMARY KEY, video_id TEXT, text TEXT, likes INTEGER DEFAULT 0, published_at REAL DEFAULT 0, fetched_at REAL);
CREATE TABLE IF NOT EXISTS fb_kv(k TEXT PRIMARY KEY, v TEXT);
"""


def ensure() -> None:
    with db.tx() as c:
        c.executescript(SCHEMA)


def kv(key: str, default=None):
    ensure()
    r = db.one("SELECT v FROM fb_kv WHERE k=?", (key,))
    return db.jload(r["v"], default) if r else default


def set_kv(key: str, value) -> None:
    ensure()
    with db.tx() as c:
        c.execute("INSERT INTO fb_kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (key, db.jdump(value)))


# ── outcomes ──────────────────────────────────────────────────────────────────

def _out(r: dict | None) -> dict | None:
    if r is None:
        return None
    r = dict(r)
    r["features"] = db.jload(r.get("features"), {})
    r["metrics"] = db.jload(r.get("metrics"), {})
    return r


def outcome(idea_id: str) -> dict | None:
    ensure()
    return _out(db.one("SELECT * FROM idea_outcomes WHERE idea_id=?", (idea_id,)))


def outcomes() -> list[dict]:
    ensure()
    return [_out(r) for r in db.q("SELECT * FROM idea_outcomes ORDER BY frozen_at")]


def freeze_features(idea_id: str, short_id: str, features: dict, overwrite: bool = False) -> None:
    """Keep the features of an idea as it was made. The first freeze stays unless `overwrite`."""
    ensure()
    have = outcome(idea_id)
    if have and not overwrite:
        if short_id and not have["short_id"]:
            db.ex("UPDATE idea_outcomes SET short_id=? WHERE idea_id=?", (short_id, idea_id))
        return
    with db.tx() as c:
        c.execute("INSERT INTO idea_outcomes(idea_id,short_id,features,frozen_at,updated_at) VALUES(?,?,?,?,?) "
                  "ON CONFLICT(idea_id) DO UPDATE SET short_id=excluded.short_id, features=excluded.features, frozen_at=excluded.frozen_at, updated_at=excluded.updated_at",
                  (idea_id, short_id, db.jdump(features), time.time(), time.time()))


def save_grade(idea_id: str, video_id: str, metrics: dict, grade, early, partial: bool, label: str, stage: str) -> None:
    ensure()
    db.ex("UPDATE idea_outcomes SET video_id=?, metrics=?, grade=?, early_grade=?, partial=?, label=?, stage=?, updated_at=? WHERE idea_id=?",
          (video_id, db.jdump(metrics), grade, early, 1 if partial else 0, label, stage, time.time(), idea_id))


def mark_remixed(idea_id: str) -> None:
    ensure()
    db.ex("UPDATE idea_outcomes SET remixed=1 WHERE idea_id=?", (idea_id,))


# ── video tags ────────────────────────────────────────────────────────────────

def video_tags() -> dict[str, str]:
    ensure()
    return {r["video_id"]: r["territory"] for r in db.q("SELECT video_id, territory FROM yt_video_tags")}


def tag_video(video_id: str, territory: str) -> None:
    ensure()
    with db.tx() as c:
        c.execute("INSERT INTO yt_video_tags(video_id,territory,tagged_at) VALUES(?,?,?) ON CONFLICT(video_id) DO UPDATE SET territory=excluded.territory, tagged_at=excluded.tagged_at", (video_id, territory, time.time()))


# ── playbooks and pins ────────────────────────────────────────────────────────

def _pb(r: dict | None) -> dict | None:
    if r is None:
        return None
    r = dict(r)
    r["data"] = db.jload(r.get("data"), {})
    return r


def playbooks() -> list[dict]:
    ensure()
    return [_pb(r) for r in db.q("SELECT * FROM playbooks ORDER BY version DESC")]


def playbook(pid: int) -> dict | None:
    ensure()
    return _pb(db.one("SELECT * FROM playbooks WHERE id=?", (pid,)))


def approved_playbook() -> dict | None:
    ensure()
    return _pb(db.one("SELECT * FROM playbooks WHERE status='approved' ORDER BY version DESC LIMIT 1"))


def add_playbook(data: dict) -> dict:
    ensure()
    v = (db.one("SELECT MAX(version) m FROM playbooks") or {}).get("m") or 0
    pid = db.ex("INSERT INTO playbooks(version,status,data,created_at) VALUES(?,?,?,?)", (v + 1, "draft", db.jdump(data), time.time()))
    return playbook(pid)


def save_playbook_data(pid: int, data: dict) -> None:
    ensure()
    db.ex("UPDATE playbooks SET data=? WHERE id=?", (db.jdump(data), pid))


def set_playbook_status(pid: int, status: str) -> dict:
    ensure()
    if status == "approved":
        db.ex("UPDATE playbooks SET status='archived' WHERE status='approved' AND id<>?", (pid,))
    db.ex("UPDATE playbooks SET status=?, decided_at=? WHERE id=?", (status, time.time(), pid))
    return playbook(pid)


def pins() -> list[dict]:
    ensure()
    return db.q("SELECT * FROM playbook_pins ORDER BY id")


def add_pin(text: str) -> None:
    ensure()
    db.ex("INSERT INTO playbook_pins(text,created_at) VALUES(?,?)", (text.strip()[:300], time.time()))


def remove_pin(pin_id: int) -> None:
    ensure()
    db.ex("DELETE FROM playbook_pins WHERE id=?", (pin_id,))


# ── comments ──────────────────────────────────────────────────────────────────

def save_comments(video_id: str, items: list[dict]) -> None:
    ensure()
    with db.tx() as c:
        for it in items:
            c.execute("INSERT INTO yt_comments(comment_id,video_id,text,likes,published_at,fetched_at) VALUES(?,?,?,?,?,?) ON CONFLICT(comment_id) DO UPDATE SET likes=excluded.likes, fetched_at=excluded.fetched_at",
                      (it["comment_id"], video_id, it["text"], it["likes"], it["published_at"], time.time()))


def comments(video_id: str, limit: int = 20) -> list[dict]:
    ensure()
    return db.q("SELECT * FROM yt_comments WHERE video_id=? ORDER BY likes DESC LIMIT ?", (video_id, limit))
