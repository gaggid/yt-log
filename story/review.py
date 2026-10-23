"""Editorial control over story candidates: list, inspect, edit, approve/reject, merge, split.
Every operation keeps the source links (candidate_refs) intact."""
import copy

from . import db
from .pipeline import next_story_id, uniq

STATUSES = ("pending", "approved", "rejected")
TEXT_FIELDS = ("overview", "curiosity_question", "opening_hook", "conflict", "stakes", "turning_point", "outcome",
               "audience_interest")


class ReviewError(Exception):
    pass


def locator(p: dict) -> str:
    if p.get("page"):
        return f"p. {p['page']}"
    return p.get("section") or f"¶{p['idx']}"


def _row(c: dict) -> dict:
    c["data"] = db.jload(c.get("data"), {})
    c["eff_story"] = c["score_override"] if c.get("score_override") is not None else c["story_score"]
    c["eff_priority"] = c["priority_override"] if c.get("priority_override") is not None else c["priority"]
    c["research"] = bool(c.get("research"))
    c["edited"] = bool(c.get("edited"))
    return c


def list_candidates(pid: str, status: str = "", q: str = "", min_priority: float | None = None, research: bool | None = None,
                    kind: str = "", sort: str = "priority", desc: bool = True, include_superseded: bool = False) -> list[dict]:
    where, args = ["c.project_id=?"], [pid]
    if status:
        where.append("c.status=?")
        args.append(status)
    elif not include_superseded:
        where.append("c.status!='superseded'")
    if q:
        where.append("(c.title LIKE ? OR c.premise LIKE ? OR c.notes LIKE ?)")
        args += [f"%{q}%"] * 3
    if research is not None:
        where.append("c.research=?")
        args.append(1 if research else 0)
    if kind:
        where.append("c.kind=?")
        args.append(kind)
    sql = ("SELECT c.*, COALESCE(c.score_override,c.story_score) AS eff_story, COALESCE(c.priority_override,c.priority) AS eff_priority,"
           "(SELECT COUNT(*) FROM candidate_refs r WHERE r.candidate_id=c.id) AS n_refs FROM candidates c WHERE "
           + " AND ".join(where))
    rows = db.q(sql, args)
    if min_priority is not None:
        rows = [r for r in rows if r["eff_priority"] >= min_priority]
    out = []
    for r in rows:
        d = db.jload(r.pop("data"), {})
        r["research"] = bool(r["research"])
        r["edited"] = bool(r["edited"])
        r["warnings"] = len(d.get("warnings", []))
        r["duplicates"] = len(d.get("duplicate_warnings", []))
        r["claims"] = len(d.get("claims", []))
        r["chapter_idxs"] = d.get("chapter_idxs", [])
        r["pages"] = pages_of(pid, r["id"])
        out.append(r)
    col = {"priority": "eff_priority", "story": "eff_story", "evidence": "evidence_score",
           "created": "created_at", "id": "id"}.get(sort)
    out.sort(key=(lambda r: r[col]) if col else (lambda r: r["title"].lower()), reverse=desc)
    return out


def pages_of(pid: str, cid: str) -> str:
    rows = db.q("SELECT DISTINCT p.page FROM candidate_refs r JOIN paras p ON p.project_id=? AND p.idx=r.para_idx "
                "WHERE r.candidate_id=? AND p.page IS NOT NULL ORDER BY p.page", (pid, cid))
    pg = [r["page"] for r in rows]
    return compress_pages(pg)


def compress_pages(pg: list[int]) -> str:
    out, i = [], 0
    while i < len(pg):
        j = i
        while j + 1 < len(pg) and pg[j + 1] == pg[j] + 1:
            j += 1
        out.append(str(pg[i]) if i == j else f"{pg[i]}-{pg[j]}")
        i = j + 1
    return ", ".join(out)


def get_refs(pid: str, cid: str) -> list[dict]:
    rows = db.q("SELECT p.idx,p.page,p.section,p.chapter_idx,p.kind,p.text, c.title AS chapter_title "
                "FROM candidate_refs r JOIN paras p ON p.project_id=? AND p.idx=r.para_idx "
                "LEFT JOIN chapters c ON c.project_id=p.project_id AND c.idx=p.chapter_idx "
                "WHERE r.candidate_id=? ORDER BY p.idx", (pid, cid))
    for r in rows:
        r["locator"] = locator(r)
    return rows


def get_candidate(cid: str) -> dict:
    r = db.one("SELECT c.*, COALESCE(c.score_override,c.story_score) AS eff_story, "
               "COALESCE(c.priority_override,c.priority) AS eff_priority FROM candidates c WHERE c.id=?", (cid,))
    if not r:
        raise ReviewError("story not found")
    r = _row(r)
    r["refs"] = get_refs(r["project_id"], cid)
    return r


def update_candidate(cid: str, patch: dict) -> dict:
    c = get_candidate(cid)
    if c["status"] == "superseded":
        raise ReviewError("this story was merged or split; edit its replacement instead")
    sets, args, content_edit = [], [], False
    data = c["data"]
    for k, v in patch.items():
        if k in ("title", "premise"):
            v = str(v).strip()
            if not v:
                raise ReviewError(f"{k} cannot be empty")
            sets.append(f"{k}=?")
            args.append(v)
            content_edit = True
        elif k == "notes":
            sets.append("notes=?")
            args.append(str(v))
        elif k == "status":
            if v not in STATUSES:
                raise ReviewError(f"status must be one of {', '.join(STATUSES)}")
            sets.append("status=?")
            args.append(v)
        elif k == "research":
            sets.append("research=?")
            args.append(1 if v else 0)
        elif k in ("score_override", "priority_override"):
            if v is not None:
                v = float(v)
                if not 0 <= v <= 100:
                    raise ReviewError(f"{k} must be between 0 and 100")
            sets.append(f"{k}=?")
            args.append(v)
        elif k in TEXT_FIELDS:
            data[k] = str(v).strip()
            content_edit = True
        else:
            raise ReviewError(f"field {k!r} cannot be edited")
    if any(k in TEXT_FIELDS for k in patch):
        sets.append("data=?")
        args.append(db.jdump(data))
    if content_edit:
        sets.append("edited=1")
    if sets:
        sets.append("updated_at=?")
        args += [db.now(), cid]
        db.ex(f"UPDATE candidates SET {', '.join(sets)} WHERE id=?", args)
    return get_candidate(cid)


def _dedupe_by(items: list[dict], key: str) -> list[dict]:
    seen, out = set(), []
    for it in items:
        k = (it.get(key) or "").strip().lower()
        if k and k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


def merge(cid_list: list[str], title: str = "", premise: str = "") -> dict:
    """Combine stories into one new story: union of source links, claims, people and chronology.
    The strongest story (by priority) provides the base text and scores; originals are kept as 'superseded'."""
    if len(set(cid_list)) < 2:
        raise ReviewError("select at least two stories to merge")
    cs = [get_candidate(i) for i in uniq(cid_list)]
    if len({c["project_id"] for c in cs}) != 1:
        raise ReviewError("stories must belong to the same source")
    if any(c["status"] == "superseded" for c in cs):
        raise ReviewError("a selected story has already been merged or split")
    cs.sort(key=lambda c: -c["eff_priority"])
    base = cs[0]
    pid = base["project_id"]
    d = copy.deepcopy(base["data"])
    for o in cs[1:]:
        od = o["data"]
        d["people"] = _dedupe_by(d["people"] + od.get("people", []), "name")
        d["chronology"] = _dedupe_by(d["chronology"] + od.get("chronology", []), "what")
        d["claims"] = _dedupe_by(d["claims"] + od.get("claims", []), "claim")
        for k in ("context_needed", "uncertainties", "research_questions"):
            d[k] = uniq(d.get(k, []) + od.get(k, []))
        d["chapter_idxs"] = uniq(d.get("chapter_idxs", []) + od.get("chapter_idxs", []))
        d["warnings"] = uniq(d.get("warnings", []) + od.get("warnings", []))
        for k in TEXT_FIELDS:
            if not d.get(k) and od.get(k):
                d[k] = od[k]
    d["warnings"] = uniq(d.get("warnings", []) + ["Merged story: scores come from the strongest original; review and adjust."])
    d["lineage"] = {"merged_from": [{"id": c["id"], "title": c["title"], "premise": c["premise"]} for c in cs],
                    "split_from": None, "lead_titles": uniq([t for c in cs for t in c["data"].get("lineage", {}).get("lead_titles", [])])}
    d["related"], d["duplicate_warnings"] = [], []
    refs = sorted({r["idx"] for c in cs for r in c["refs"]})
    notes = "\n".join(c["notes"] for c in cs if c["notes"])
    research = any(c["research"] for c in cs)
    with db.tx() as con:
        new = next_story_id(pid, con)
        con.execute("INSERT INTO candidates(id,project_id,title,premise,kind,research,story_score,evidence_score,priority,"
                    "score_override,priority_override,notes,origin,edited,created_at,updated_at,data) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (new, pid, title.strip() or base["title"], premise.strip() or base["premise"], base["kind"],
                     1 if research else 0, base["story_score"], base["evidence_score"], base["priority"],
                     base["score_override"], base["priority_override"], notes, "merge", 1, db.now(), db.now(), db.jdump(d)))
        for i in refs:
            con.execute("INSERT INTO candidate_refs(candidate_id,para_idx) VALUES(?,?)", (new, i))
        for c in cs:
            con.execute("UPDATE candidates SET status='superseded', superseded_by=?, updated_at=? WHERE id=?",
                        (new, db.now(), c["id"]))
    from .pipeline import link_candidates
    link_candidates(pid)
    return get_candidate(new)


def split(cid: str, groups: list[dict]) -> list[dict]:
    """Divide one story into several. groups: [{title, premise?, para_idxs:[...]}], each using a subset of the
    story's source links. Claims follow the passages they cite; people/chronology are copied for you to prune."""
    c = get_candidate(cid)
    if c["status"] == "superseded":
        raise ReviewError("this story was already merged or split")
    if len(groups) < 2:
        raise ReviewError("a split needs at least two groups")
    have = {r["idx"] for r in c["refs"]}
    for g in groups:
        ids = {int(i) for i in g.get("para_idxs", [])}
        if not ids:
            raise ReviewError("every group needs at least one source passage")
        if not ids <= have:
            raise ReviewError(f"passages {sorted(ids - have)} are not linked to this story")
        if not str(g.get("title", "")).strip():
            raise ReviewError("every group needs a title")
    pid = c["project_id"]
    new_ids = []
    with db.tx() as con:
        for g in groups:
            ids = sorted({int(i) for i in g["para_idxs"]})
            d = copy.deepcopy(c["data"])
            d["claims"] = [x for x in d["claims"] if not x["para_ids"] or set(x["para_ids"]) & set(ids)]
            d["lineage"] = {"merged_from": [], "split_from": {"id": c["id"], "title": c["title"]},
                            "lead_titles": d.get("lineage", {}).get("lead_titles", [])}
            d["warnings"] = uniq(d.get("warnings", []) + ["Split from another story: people, chronology and scores were copied; review and adjust."])
            d["related"], d["duplicate_warnings"] = [], []
            new = next_story_id(pid, con)
            con.execute("INSERT INTO candidates(id,project_id,title,premise,kind,research,story_score,evidence_score,priority,"
                        "score_override,priority_override,notes,origin,edited,created_at,updated_at,data) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (new, pid, g["title"].strip(), (g.get("premise") or c["premise"]).strip(), c["kind"],
                         1 if c["research"] else 0, c["story_score"], c["evidence_score"], c["priority"],
                         c["score_override"], c["priority_override"], c["notes"], "split", 1, db.now(), db.now(), db.jdump(d)))
            for i in ids:
                con.execute("INSERT INTO candidate_refs(candidate_id,para_idx) VALUES(?,?)", (new, i))
            new_ids.append(new)
        con.execute("UPDATE candidates SET status='superseded', superseded_by=?, updated_at=? WHERE id=?",
                    (",".join(new_ids), db.now(), cid))
    from .pipeline import link_candidates
    link_candidates(pid)
    return [get_candidate(i) for i in new_ids]


def rescore_project(pid: str, weights: dict, influence: float) -> int:
    """Recompute story/priority scores from stored factor scores after the weights changed."""
    from . import scoring
    n = 0
    for c in db.q("SELECT id,data FROM candidates WHERE project_id=? AND status!='superseded'", (pid,)):
        d = db.jload(c["data"], {})
        s, ev, pr = scoring.rescore(d, weights, influence)
        db.ex("UPDATE candidates SET story_score=?, evidence_score=?, priority=? WHERE id=?", (s, ev, pr, c["id"]))
        n += 1
    return n
