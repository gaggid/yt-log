"""SQLite storage. One short-lived connection per operation (WAL), so threads and tests don't share state."""
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

import config

_path: Path | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects(
  id TEXT PRIMARY KEY, title TEXT, author TEXT, format TEXT, source_url TEXT,
  created_at REAL, updated_at REAL,
  status TEXT DEFAULT 'imported', stage TEXT DEFAULT '', error TEXT DEFAULT '',
  orig_path TEXT, sha256 TEXT, page_count INTEGER, est_tokens INTEGER, char_count INTEGER,
  warnings TEXT DEFAULT '[]', meta TEXT DEFAULT '{}', next_story_no INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS paras(
  project_id TEXT, idx INTEGER, page INTEGER, section TEXT DEFAULT '', chapter_idx INTEGER DEFAULT 0,
  kind TEXT DEFAULT 'p', text TEXT, orig_text TEXT, edited INTEGER DEFAULT 0, tokens INTEGER DEFAULT 0,
  PRIMARY KEY(project_id, idx)
);
CREATE TABLE IF NOT EXISTS chapters(
  project_id TEXT, idx INTEGER, title TEXT, start_para INTEGER, end_para INTEGER,
  page_start INTEGER, page_end INTEGER, source TEXT DEFAULT 'auto', skip INTEGER DEFAULT 0,
  PRIMARY KEY(project_id, idx)
);
CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT, stage TEXT, key TEXT, ord REAL DEFAULT 0,
  status TEXT DEFAULT 'pending', attempts INTEGER DEFAULT 0,
  input TEXT DEFAULT '{}', result TEXT, error TEXT DEFAULT '', raw_failed TEXT DEFAULT '[]',
  tokens_in INTEGER DEFAULT 0, tokens_out INTEGER DEFAULT 0, duration_ms INTEGER DEFAULT 0,
  updated_at REAL, UNIQUE(project_id, stage, key)
);
CREATE TABLE IF NOT EXISTS candidates(
  id TEXT PRIMARY KEY, project_id TEXT, task_id INTEGER,
  title TEXT, premise TEXT, kind TEXT DEFAULT '',
  status TEXT DEFAULT 'pending', research INTEGER DEFAULT 0,
  story_score REAL DEFAULT 0, evidence_score REAL DEFAULT 0, priority REAL DEFAULT 0,
  score_override REAL, priority_override REAL,
  notes TEXT DEFAULT '', origin TEXT DEFAULT 'pipeline', edited INTEGER DEFAULT 0,
  superseded_by TEXT, created_at REAL, updated_at REAL, data TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS cand_proj ON candidates(project_id, status);
CREATE TABLE IF NOT EXISTS candidate_refs(
  candidate_id TEXT, para_idx INTEGER, PRIMARY KEY(candidate_id, para_idx)
);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT, started_at REAL, ended_at REAL,
  status TEXT, settings TEXT, note TEXT DEFAULT ''
);
"""


def init(path: Path | str | None = None) -> None:
    """Point the module at a DB file (default data/story.db) and create tables."""
    global _path
    _path = Path(path) if path else config.DATA_DIR / "story.db"
    _path.parent.mkdir(parents=True, exist_ok=True)
    with tx() as c:
        c.executescript(SCHEMA)
        if "skip" not in {r[1] for r in c.execute("PRAGMA table_info(chapters)")}:
            c.execute("ALTER TABLE chapters ADD COLUMN skip INTEGER DEFAULT 0")


def db_path() -> Path:
    if _path is None:
        init()
    return _path


@contextmanager
def tx():
    con = sqlite3.connect(db_path(), timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=10000")
    try:
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


def q(sql: str, args=()) -> list[dict]:
    with tx() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def one(sql: str, args=()) -> dict | None:
    rows = q(sql, args)
    return rows[0] if rows else None


def ex(sql: str, args=()) -> int:
    with tx() as c:
        return c.execute(sql, args).lastrowid


def now() -> float:
    return time.time()


def jdump(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def jload(s, default=None):
    if s is None or s == "":
        return default
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return default
