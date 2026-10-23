"""Time estimates learned from this machine's own history.

Every finished model step is recorded in `task_stats` (it outlives projects and reprocessing). Rates are a
recency-weighted average per stage and model, so estimates sharpen with each run. With no history for a stage the
built-in starting values are used and the estimate is labelled a rough guess.
"""
import math

from . import db, projects, settings as settings_mod

STAGES = ["analyze", "rollup", "index", "discover", "discover_global", "draft", "finalize"]

# Starting values measured on the local 12B model (seconds). Analysis scales with input tokens, the rest per call.
SEED = {"analyze": 0.0087, "rollup": 25.0, "index": 50.0, "discover": 50.0, "discover_global": 45.0, "draft": 45.0,
        "finalize": 0.5}
INSTRUCTION_TOKENS = 1500          # prompt overhead added to every analysis chunk
DECAY = 0.96                       # weight multiplier per older sample (about the last 25 samples matter)

SCHEMA = """
CREATE TABLE IF NOT EXISTS task_stats(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, project_id TEXT, stage TEXT, model TEXT,
  tokens_in INTEGER, tokens_out INTEGER, duration_ms INTEGER, context INTEGER
);
CREATE INDEX IF NOT EXISTS stats_stage ON task_stats(stage, model, id);
"""


def ensure() -> None:
    """Create the stats table; the first time, learn from steps that finished before it existed."""
    with db.tx() as c:
        c.executescript(SCHEMA)
        flag = c.execute("SELECT 1 FROM settings WHERE key='stats_backfilled'").fetchone()
        if not flag:
            model = settings_mod.get()["model"]
            c.execute("INSERT INTO task_stats(ts,project_id,stage,model,tokens_in,tokens_out,duration_ms,context) "
                      "SELECT updated_at, project_id, stage, ?, tokens_in, tokens_out, duration_ms, 0 FROM tasks "
                      "WHERE status='done' AND duration_ms>0 AND stage!='finalize' AND (tokens_in>0 OR tokens_out>0) ORDER BY id", (model,))
            c.execute("INSERT INTO settings(key,value) VALUES('stats_backfilled','true')")


def record(pid: str, stage: str, model: str, tokens_in: int, tokens_out: int, duration_ms: int, context: int) -> None:
    ensure()
    if duration_ms <= 0 or stage == "finalize" or (tokens_in <= 0 and tokens_out <= 0):
        return                                                   # steps that never called the model say nothing about speed
    db.ex("INSERT INTO task_stats(ts,project_id,stage,model,tokens_in,tokens_out,duration_ms,context) VALUES(?,?,?,?,?,?,?,?)",
          (db.now(), pid, stage, model, tokens_in, tokens_out, duration_ms, context))


def rate(stage: str, model: str) -> dict:
    """Seconds per unit (per input token for analyze, per call otherwise), with a spread and a confidence label."""
    ensure()
    rows = db.q("SELECT tokens_in, duration_ms FROM task_stats WHERE stage=? AND model=? ORDER BY id DESC LIMIT 120",
                (stage, model))
    seed = SEED[stage]
    if not rows:
        return {"value": seed, "spread": 0.6, "n": 0, "confidence": "rough guess", "learned": False}
    num = den = 0.0
    samples = []
    for i, r in enumerate(rows):
        w = DECAY ** i
        unit = r["tokens_in"] if stage == "analyze" else 1
        if unit <= 0:
            continue
        num += w * r["duration_ms"] / 1000
        den += w * unit
        samples.append((w, r["duration_ms"] / 1000 / unit))
    if den == 0:
        return {"value": seed, "spread": 0.6, "n": 0, "confidence": "rough guess", "learned": False}
    mean = num / den
    var = sum(w * (s - mean) ** 2 for w, s in samples) / sum(w for w, _ in samples)
    rel = math.sqrt(var) / mean if mean else 0.5
    n = len(rows)
    floor = 0.15 if n >= 8 else 0.3 if n >= 3 else 0.5
    conf = "good" if n >= 8 else "fair" if n >= 3 else "low"
    return {"value": mean, "spread": max(floor, min(0.6, rel)), "n": n, "confidence": conf, "learned": True}


def _para_tokens(pid: str) -> dict[int, tuple[int, int]]:
    return {r["idx"]: (r["tokens"], max(1, r["n"])) for r in
            db.q("SELECT idx, tokens, LENGTH(text) n FROM paras WHERE project_id=?", (pid,))}


def _chunk_tokens(inp: dict, pt: dict) -> int:
    tot = 0
    for key in ("items", "context"):
        for i, a, b in inp.get(key, []):
            t, n = pt.get(i, (0, 1))
            tot += t if b == -1 and a == 0 else int(t * min(1.0, ((b if b != -1 else n) - a) / n))
    return tot + INSTRUCTION_TOKENS


def _fmt_range(sec: float, spread: float) -> dict:
    return {"seconds": round(sec), "low": round(sec * (1 - spread)), "high": round(sec * (1 + spread))}


def estimate(pid: str, now: float | None = None) -> dict:
    """Remaining time for a project: tasks already planned plus a forecast of stages not planned yet."""
    now = now or db.now()
    s = settings_mod.get()
    model = s["model"]
    pt = _para_tokens(pid)
    tasks = db.q("SELECT stage,status,input,updated_at FROM tasks WHERE project_id=?", (pid,))
    by: dict[str, list[dict]] = {st: [] for st in STAGES}
    for t in tasks:
        by[t["stage"]].append(t)
    scope_ids = projects.resolve_scope(pid)
    scope_rows = [r for r in db.q("SELECT idx, chapter_idx, tokens FROM paras WHERE project_id=?", (pid,)) if r["idx"] in scope_ids]
    n_tokens = sum(r["tokens"] for r in scope_rows)
    ch_tokens: dict[int, int] = {}
    for r in scope_rows:
        ch_tokens[r["chapter_idx"]] = ch_tokens.get(r["chapter_idx"], 0) + r["tokens"]
    n_ch = len(ch_tokens)
    chunk_target = max(500, int(s["chunk_tokens"]))

    # units still to do per stage, as (count of calls, input tokens for analyze)
    remaining: dict[str, float] = {}
    forecast: dict[str, bool] = {}
    a_tasks = by["analyze"]
    if a_tasks:
        open_ = [t for t in a_tasks if t["status"] in ("pending", "running")]
        remaining["analyze"] = sum(_chunk_tokens(db.jload(t["input"], {}), pt) for t in open_)
        n_chunks = len([t for t in a_tasks if t["status"] != "split"])
    else:
        n_chunks = max(1, -(-n_tokens // chunk_target)) if n_tokens else 0
        remaining["analyze"] = n_tokens + n_chunks * INSTRUCTION_TOKENS
        forecast["analyze"] = True
    multi = sum(1 for tk in ch_tokens.values() if tk > chunk_target * 0.9) or (1 if n_ch == 1 and n_chunks > 1 else 0)
    plan = {
        "rollup": multi, "index": 1 if n_ch >= 2 else 0, "discover": max(1, -(-n_ch // 12)) if n_ch else 0,
        "discover_global": 1 if n_ch >= 3 else 0,
        "draft": min(int(s["max_candidates"]), max(3, round(n_chunks * 0.6 + n_ch * 0.8))) if n_ch else 0,
        "finalize": 1,
    }
    for st in STAGES[1:]:
        if by[st]:
            remaining[st] = sum(1 for t in by[st] if t["status"] in ("pending", "running"))
        else:
            remaining[st] = plan[st]
            forecast[st] = True
    # an unplanned later stage only counts if earlier ones are not already "failed forever"
    total = lo = hi = 0.0
    parts = []
    inflight_elapsed = 0.0
    for t in tasks:
        if t["status"] == "running":
            inflight_elapsed = max(inflight_elapsed, now - (t["updated_at"] or now))
    for st in STAGES:
        units = remaining.get(st, 0)
        if not units:
            continue
        r = rate(st, model)
        sec = units * r["value"]
        total += sec
        lo += sec * (1 - r["spread"])
        hi += sec * (1 + r["spread"])
        parts.append({"stage": st, "seconds": round(sec), "units": round(units, 1), "forecast": bool(forecast.get(st)),
                      "confidence": r["confidence"], "samples": r["n"]})
    if inflight_elapsed:
        total = max(0.0, total - inflight_elapsed * 0.5)         # the running step is partly done; credit half its age
    # confidence follows the stage that accounts for most of the remaining time; the rest is noted in the basis
    conf = max(parts, key=lambda p: p["seconds"])["confidence"] if parts else "good"
    done_sec = (db.one("SELECT COALESCE(SUM(duration_ms),0) d FROM tasks WHERE project_id=? AND status IN ('done','split')", (pid,)) or {"d": 0})["d"] / 1000
    return {"remaining": _fmt_range(total, (hi - lo) / 2 / total if total else 0.3), "confidence": conf,
            "basis": _basis(parts, conf), "stages": parts, "done_seconds": round(done_sec, 1),
            "percent": round(100 * done_sec / (done_sec + total)) if done_sec + total else 0,
            "model": model}


def _basis(parts: list[dict], conf: str) -> str:
    if not parts:
        return "Nothing left to do."
    if conf == "rough guess":
        return "No earlier runs with this model yet; using typical speeds."
    main = max(parts, key=lambda p: p["seconds"])
    text = f"Based on {main['samples']} earlier {main['stage']} calls on this machine."
    if any(p["confidence"] == "rough guess" for p in parts):
        text += " Stages that have not run before use typical speeds."
    return text


def human(sec: float) -> str:
    sec = int(sec)
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m {sec % 60:02d}s" if sec < 600 else f"{round(sec / 60)} min"
    return f"{sec // 3600}h {round(sec % 3600 / 60):02d}m"


def performance() -> list[dict]:
    """Per stage and model: calls recorded, average seconds, tokens per second. Shown in Settings."""
    ensure()
    return db.q("SELECT stage, model, COUNT(*) calls, ROUND(AVG(duration_ms)/1000.0,1) avg_s, "
                "ROUND(SUM(tokens_out)*1000.0/MAX(1,SUM(duration_ms)),1) out_tok_s, SUM(tokens_in) tokens_in, SUM(tokens_out) tokens_out "
                "FROM task_stats GROUP BY stage, model ORDER BY model, stage")

