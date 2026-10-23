"""Plain-language guidance: where the project stands and what the user should do next."""
from . import db, eta, pipeline, projects

STEPS = [("import", "Import"), ("scope", "Choose scope"), ("process", "Process"), ("review", "Review stories"), ("export", "Export")]


def next_step(pid: str) -> dict:
    p = projects.get(pid)
    status = p["status"]
    prog = pipeline.progress(pid)
    done = sum(s["done"] for s in prog["stages"])
    total = sum(s["total"] for s in prog["stages"])
    pending, approved, rejected, found = p["cand_pending"], p["cand_approved"], p["cand_rejected"], p["cand_total"]
    base = {"counts": {"found": found, "pending": pending, "approved": approved, "rejected": rejected}}

    if status == "imported":
        pv = projects.scope_preview(pid)
        e = eta.estimate(pid)
        mins = eta.human(e["remaining"]["seconds"])
        return {**base, "step": "scope", "tone": "action", "title": "Ready to process",
                "detail": f"{pv['paragraphs']:,} paragraphs (~{pv['tokens']:,} tokens) will be analysed. Estimated time: about {mins} "
                          f"({e['confidence']}). Check the scope below if you only want part of the source, then start.",
                "primary": {"action": "start", "label": "Start processing"},
                "secondary": {"action": "scroll_scope", "label": "Change scope"}}
    if status in ("queued", "running"):
        e = eta.estimate(pid)
        return {**base, "step": "process", "tone": "busy", "title": "Processing",
                "detail": f"{done} of {total} steps finished so far. About {eta.human(e['remaining']['seconds'])} left. "
                          "You can leave this page; processing continues and resumes if the app restarts.",
                "primary": {"action": "pause", "label": "Pause"}, "secondary": None}
    if status in ("paused", "cancelled"):
        e = eta.estimate(pid)
        return {**base, "step": "process", "tone": "action", "title": "Processing is " + status,
                "detail": f"{done} of {total} steps are finished and kept. Resuming continues where it stopped "
                          f"(about {eta.human(e['remaining']['seconds'])} left).",
                "primary": {"action": "resume", "label": "Resume processing"}, "secondary": None}
    if status == "error":
        first = prog["errors"][0]["error"][:200] if prog["errors"] else (p["error"] or "unknown error")
        return {**base, "step": "process", "tone": "problem", "title": "Processing needs attention",
                "detail": f"{len(prog['errors']) or 1} step(s) failed: {first}. Finished work is kept. Fix the cause "
                          "(for example check the model connection in Settings), then retry the failed steps.",
                "primary": {"action": "retry", "label": "Retry failed steps"},
                "secondary": {"action": "settings", "label": "Open Settings"}}
    if found == 0:
        return {**base, "step": "review", "tone": "problem", "title": "No stories were found",
                "detail": "The source was processed but no story candidates came out. Try a different scope (for example a "
                          "chapter with more narrative), or paste text from a different part.",
                "primary": {"action": "scroll_scope", "label": "Change scope"}, "secondary": None}
    if pending:
        return {**base, "step": "review", "tone": "action", "title": f"{pending} stor{'y' if pending == 1 else 'ies'} to review",
                "detail": f"{found} found: {approved} approved, {rejected} rejected. Open the best-ranked story first; approve or "
                          "reject it, edit what's wrong, and use Next to keep going.",
                "primary": {"action": "review", "label": "Start reviewing"},
                "secondary": {"action": "export", "label": "Export what's approved"} if approved else None}
    if approved:
        return {**base, "step": "export", "tone": "good", "title": "All stories reviewed",
                "detail": f"{approved} approved, {rejected} rejected. Export the approved stories for the next module.",
                "primary": {"action": "export", "label": f"Export {approved} approved"}, "secondary": None}
    return {**base, "step": "export", "tone": "problem", "title": "Everything was rejected",
            "detail": "No stories are approved. Change a decision in the Stories tab, or reprocess a different scope.",
            "primary": {"action": "review", "label": "Open stories"}, "secondary": None}


def step_index(ns: dict) -> int:
    return [k for k, _ in STEPS].index(ns["step"])


def describe_task(pid: str, t: dict, total_analyze: int | None = None) -> str:
    """Short human label for a task row (stage, key, input)."""
    inp = db.jload(t.get("input"), {}) if isinstance(t.get("input"), str) else (t.get("input") or {})
    st, key = t["stage"], t["key"]
    if st == "analyze":
        idxs = [i for i, _, _ in inp.get("items", [])]
        pr = db.one("SELECT MIN(page) a, MAX(page) b FROM paras WHERE project_id=? AND idx BETWEEN ? AND ?",
                    (pid, min(idxs), max(idxs))) if idxs else None
        chs = inp.get("chapter_idxs", [])
        names = ", ".join((db.one("SELECT title FROM chapters WHERE project_id=? AND idx=?", (pid, c)) or {"title": f"Chapter {c}"})["title"]
                          for c in chs[:2]) + (" …" if len(chs) > 2 else "")
        pages = f" (pp. {pr['a']}–{pr['b']})" if pr and pr["a"] else ""
        n = int(key[1:5]) + 1 if key.startswith("c") and key[1:5].isdigit() else None
        pre = f"Chunk {n}" + (f" of {total_analyze}" if total_analyze and n else "") if n else "Chunk"
        return f"{pre}: {names}{pages}"
    if st == "rollup":
        c = inp.get("chapter_idx")
        r = db.one("SELECT title FROM chapters WHERE project_id=? AND idx=?", (pid, c))
        return f"Chapter record: {r['title'] if r else c}"
    if st == "index":
        return "Source overview and index"
    if st == "discover":
        return f"Finding stories in chapters {', '.join(str(c) for c in inp.get('chapters', [])[:6])}"
    if st == "discover_global":
        return "Finding stories that span chapters"
    if st == "draft":
        return f"Drafting: {inp.get('stub', {}).get('title', key)}"
    return "Linking related stories"


def live(pid: str) -> dict:
    """Everything the progress view needs to feel alive: the step running now, estimate, recent activity."""
    total_an = (db.one("SELECT COUNT(*) n FROM tasks WHERE project_id=? AND stage='analyze' AND status!='split'", (pid,)) or {"n": 0})["n"]
    now = db.now()
    cur = db.one("SELECT * FROM tasks WHERE project_id=? AND status='running' ORDER BY updated_at DESC LIMIT 1", (pid,))
    current = None
    if cur:
        current = {"stage": cur["stage"], "label": describe_task(pid, cur, total_an), "elapsed": round(now - (cur["updated_at"] or now), 1),
                   "attempt": cur["attempts"]}
    acts = db.q("SELECT * FROM tasks WHERE project_id=? AND status IN ('done','failed') ORDER BY updated_at DESC LIMIT 12", (pid,))
    activity = [{"stage": a["stage"], "label": describe_task(pid, a, total_an), "seconds": round((a["duration_ms"] or 0) / 1000, 1),
                 "tokens_in": a["tokens_in"], "tokens_out": a["tokens_out"], "status": a["status"], "at": a["updated_at"]} for a in acts]
    run = db.one("SELECT started_at FROM runs WHERE project_id=? ORDER BY id DESC LIMIT 1", (pid,))
    est = eta.estimate(pid)
    return {"server_now": now, "current": current, "activity": activity, "eta": est, "run_started_at": run["started_at"] if run else None}
