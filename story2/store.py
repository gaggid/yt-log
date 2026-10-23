"""Phase 2 tables. Created on demand next to the Phase 1 tables; nothing in Phase 1 depends on them."""
from story import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS plans(
  id TEXT PRIMARY KEY, project_id TEXT, candidate_id TEXT, format TEXT DEFAULT '16:9', status TEXT DEFAULT 'draft',
  narrator TEXT DEFAULT '{}', settings TEXT DEFAULT '{}', blueprint TEXT, readiness TEXT, validation TEXT,
  verification TEXT DEFAULT 'unverified', rev INTEGER DEFAULT 1, created_at REAL, updated_at REAL
);
CREATE INDEX IF NOT EXISTS plan_cand ON plans(candidate_id);
CREATE TABLE IF NOT EXISTS segments(
  id TEXT PRIMARY KEY, plan_id TEXT, seq REAL, beat TEXT DEFAULT '', sentences TEXT DEFAULT '[]', plain TEXT DEFAULT '',
  annotated TEXT DEFAULT '', emphasis TEXT DEFAULT '[]', pronounce TEXT DEFAULT '[]', facts_used TEXT DEFAULT '[]',
  duration_s REAL DEFAULT 0, evidence_ids TEXT DEFAULT '[]', scene_ids TEXT DEFAULT '[]',
  status TEXT DEFAULT 'draft', locked INTEGER DEFAULT 0, rev INTEGER DEFAULT 1, issues TEXT DEFAULT '[]', updated_at REAL
);
CREATE INDEX IF NOT EXISTS seg_plan ON segments(plan_id, seq);
CREATE TABLE IF NOT EXISTS plan_revisions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, plan_id TEXT, ts REAL, what TEXT, detail TEXT DEFAULT '{}'
);
"""


def ensure() -> None:
    with db.tx() as c:
        c.executescript(SCHEMA)


def log(plan_id: str, what: str, detail: dict | None = None) -> None:
    db.ex("INSERT INTO plan_revisions(plan_id,ts,what,detail) VALUES(?,?,?,?)", (plan_id, db.now(), what, db.jdump(detail or {})))
