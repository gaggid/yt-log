"""YouTube tables: the connection (`yt_auth`), the channel's videos (`yt_videos`), their daily numbers (`yt_stats`), which short each video is (`yt_links`) and small state (`yt_kv`)."""
import time

from story import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS yt_auth(id INTEGER PRIMARY KEY CHECK(id=1), data TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS yt_kv(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS yt_videos(
  video_id TEXT PRIMARY KEY, title TEXT DEFAULT '', published_at REAL DEFAULT 0, duration_s INTEGER DEFAULT 0,
  views INTEGER DEFAULT 0, likes INTEGER DEFAULT 0, comments INTEGER DEFAULT 0, fetched_at REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS yt_stats(
  video_id TEXT, day TEXT, views INTEGER DEFAULT 0, minutes REAL DEFAULT 0, avg_view_s REAL DEFAULT 0, avg_view_pct REAL DEFAULT 0,
  likes INTEGER DEFAULT 0, comments INTEGER DEFAULT 0, shares INTEGER DEFAULT 0, subs INTEGER DEFAULT 0,
  PRIMARY KEY(video_id, day)
);
CREATE TABLE IF NOT EXISTS yt_links(video_id TEXT PRIMARY KEY, short_id TEXT NOT NULL, idea_id TEXT DEFAULT '', how TEXT DEFAULT 'title', created_at REAL);
"""


def ensure() -> None:
    with db.tx() as c:
        c.executescript(SCHEMA)


def get_auth() -> dict:
    ensure()
    r = db.one("SELECT data FROM yt_auth WHERE id=1")
    return db.jload(r["data"], {}) if r else {}


def set_auth(data: dict) -> None:
    ensure()
    with db.tx() as c:
        c.execute("INSERT INTO yt_auth(id,data) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (db.jdump(data),))


def clear_auth() -> None:
    ensure()
    db.ex("DELETE FROM yt_auth WHERE id=1")


def kv(key: str, default=None):
    ensure()
    r = db.one("SELECT v FROM yt_kv WHERE k=?", (key,))
    return db.jload(r["v"], default) if r else default


def set_kv(key: str, value) -> None:
    ensure()
    with db.tx() as c:
        c.execute("INSERT INTO yt_kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (key, db.jdump(value)))


def save_videos(vids: list[dict]) -> None:
    ensure()
    now = time.time()
    with db.tx() as c:
        for v in vids:
            c.execute("INSERT INTO yt_videos(video_id,title,published_at,duration_s,views,likes,comments,fetched_at) VALUES(?,?,?,?,?,?,?,?) "
                      "ON CONFLICT(video_id) DO UPDATE SET title=excluded.title, published_at=excluded.published_at, duration_s=excluded.duration_s, views=excluded.views, "
                      "likes=excluded.likes, comments=excluded.comments, fetched_at=excluded.fetched_at",
                      (v["video_id"], v["title"], v["published_at"], v["duration_s"], v["views"], v["likes"], v["comments"], now))


def videos() -> list[dict]:
    ensure()
    return db.q("SELECT * FROM yt_videos ORDER BY published_at DESC")


def video(video_id: str) -> dict | None:
    ensure()
    return db.one("SELECT * FROM yt_videos WHERE video_id=?", (video_id,))


def save_days(video_id: str, days: list[dict]) -> None:
    ensure()
    with db.tx() as c:
        for d in days:
            c.execute("INSERT INTO yt_stats(video_id,day,views,minutes,avg_view_s,avg_view_pct,likes,comments,shares,subs) VALUES(?,?,?,?,?,?,?,?,?,?) "
                      "ON CONFLICT(video_id,day) DO UPDATE SET views=excluded.views, minutes=excluded.minutes, avg_view_s=excluded.avg_view_s, avg_view_pct=excluded.avg_view_pct, "
                      "likes=excluded.likes, comments=excluded.comments, shares=excluded.shares, subs=excluded.subs",
                      (video_id, d["day"], d["views"], d["minutes"], d["avg_view_s"], d["avg_view_pct"], d["likes"], d["comments"], d["shares"], d["subs"]))


def days(video_id: str) -> list[dict]:
    ensure()
    return db.q("SELECT * FROM yt_stats WHERE video_id=? ORDER BY day", (video_id,))


def links() -> list[dict]:
    ensure()
    return db.q("SELECT * FROM yt_links ORDER BY created_at")


def link_of_short(short_id: str) -> dict | None:
    ensure()
    return db.one("SELECT * FROM yt_links WHERE short_id=?", (short_id,))


def set_link(video_id: str, short_id: str, idea_id: str = "", how: str = "title") -> None:
    """One video belongs to one short and one short to one video: a new link replaces the older of either."""
    ensure()
    with db.tx() as c:
        c.execute("DELETE FROM yt_links WHERE short_id=? OR video_id=?", (short_id, video_id))
        c.execute("INSERT INTO yt_links(video_id,short_id,idea_id,how,created_at) VALUES(?,?,?,?,?)", (video_id, short_id, idea_id, how, time.time()))


def remove_link(video_id: str) -> None:
    ensure()
    db.ex("DELETE FROM yt_links WHERE video_id=?", (video_id,))


def summary_by_short() -> dict[str, dict]:
    """{short_id: {video_id, views, likes, comments}} for the idea board."""
    ensure()
    rows = db.q("SELECT l.short_id, l.video_id, v.views, v.likes, v.comments FROM yt_links l LEFT JOIN yt_videos v ON v.video_id=l.video_id")
    return {r["short_id"]: {"video_id": r["video_id"], "views": r["views"] or 0, "likes": r["likes"] or 0, "comments": r["comments"] or 0} for r in rows}
