"""Build the versioned export (JSON is canonical, CSV is a flat convenience view)."""
import csv
import io
from datetime import datetime, timezone

from . import db, figures, projects, review
from .contract import (SCHEMA_VERSION, ExportDoc, Lineage, Related, Review, Scores, SourceInfo, SourceRef,
                       StoryRecord)

DEFAULT_STATUSES = ("approved", "pending")


def build(pid: str, statuses=DEFAULT_STATUSES, include_text: bool = True) -> ExportDoc:
    proj = projects.get(pid)
    statuses = list(statuses)
    rows = [r for r in review.list_candidates(pid, sort="priority") if r["status"] in statuses]
    stories = [_story(r["id"], include_text) for r in rows]
    index_res = db.one("SELECT result FROM tasks WHERE project_id=? AND stage='index' AND status='done'", (pid,))
    overview = (db.jload(index_res["result"], {}) if index_res else {}).get("overview", "")
    return ExportDoc(
        exported_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        generator={"module": "source-to-story", "schema_version": SCHEMA_VERSION},
        source=SourceInfo(
            project_id=pid, title=proj["title"], author=proj["author"] or "", format=proj["format"],
            url=proj["source_url"] or "", sha256=proj["sha256"] or "", pages=proj["page_count"],
            estimated_tokens=proj["est_tokens"] or 0,
            chapters=[{"index": c["idx"], "title": c["title"], "page_start": c["page_start"], "page_end": c["page_end"]}
                      for c in projects.get_chapters(pid)],
            imported_at=datetime.fromtimestamp(proj["created_at"], timezone.utc).isoformat(timespec="seconds"),
            overview=overview),
        filter={"statuses": statuses, "superseded_excluded": True},
        stories=stories)


def _story(cid: str, include_text: bool) -> StoryRecord:
    c = review.get_candidate(cid)
    d = c["data"]
    sc = d.get("scores", {})
    ev = d.get("evidence", {})
    refs = [SourceRef(paragraph_id=r["idx"], page=r["page"], section=r["section"] or "", chapter_index=r["chapter_idx"],
                      chapter_title=r["chapter_title"] or "", locator=r["locator"], text=r["text"] if include_text else "")
            for r in c["refs"]]
    return StoryRecord(
        id=c["id"], title=c["title"], premise=c["premise"], kind=c["kind"] or "", nature=c["nature"] or "",
        curiosity_question=d.get("curiosity_question", ""), opening_hook=d.get("opening_hook", ""),
        overview=d.get("overview", ""), people=d.get("people", []), chronology=[{**x, "paragraph_ids": x.get("para_ids", [])} for x in d.get("chronology", [])],
        conflict=d.get("conflict", ""), stakes=d.get("stakes", ""), turning_point=d.get("turning_point", ""),
        outcome=d.get("outcome", ""), audience_interest=d.get("audience_interest", ""),
        context_needed=d.get("context_needed", []),
        claims=[{"claim": x["claim"], "quote": x.get("quote", ""), "quote_verified": x.get("quote_verified"),
                 "support": x.get("support", "moderate"), "basis": x.get("basis", ""),
                 "paragraph_ids": x.get("para_ids", [])} for x in d.get("claims", [])],
        gaps=d.get("gaps", []), flags=d.get("flags", []), figures=figures.for_paras(c["project_id"], [r["idx"] for r in c["refs"]]),
        uncertainties=d.get("uncertainties", []), research_questions=d.get("research_questions", []),
        scores=Scores(story_score=c["story_score"], evidence_score=c["evidence_score"], priority=c["priority"],
                      story_score_override=c["score_override"], priority_override=c["priority_override"],
                      effective_priority=c["eff_priority"],
                      factors={k: {"score": v["score"], "reason": v.get("reason", "")} for k, v in sc.items()},
                      evidence_reason=ev.get("reason", ""), evidence_breakdown=ev.get("breakdown", {}),
                      completeness=c["completeness"], completeness_breakdown=(d.get("completeness") or {}).get("parts", {})),
        review=Review(status=c["status"], needs_research=c["research"], notes=c["notes"], edited=c["edited"]),
        references=refs,
        related=[Related(**x) for x in d.get("related", [])],
        duplicate_warnings=[Related(**x) for x in d.get("duplicate_warnings", [])],
        warnings=d.get("warnings", []),
        lineage=Lineage(origin=c["origin"], merged_from=[m["id"] for m in d.get("lineage", {}).get("merged_from", [])],
                        split_from=(d.get("lineage", {}).get("split_from") or {}).get("id")))


def to_json(doc: ExportDoc) -> str:
    return doc.model_dump_json(indent=2)


CSV_COLUMNS = ["id", "title", "premise", "status", "needs_research", "effective_priority", "story_score", "evidence_score",
               "hook", "narrative", "payoff", "emotion", "standalone", "kind", "nature", "completeness", "flags", "figures", "curiosity_question", "opening_hook",
               "overview", "conflict", "stakes", "turning_point", "outcome", "pages", "sections", "paragraph_ids",
               "claims", "unverified_quotes", "uncertainties", "research_questions", "duplicate_of", "related", "notes"]


def to_csv(doc: ExportDoc) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
    w.writeheader()
    for s in doc.stories:
        pages = sorted({r.page for r in s.references if r.page is not None})
        f = s.scores.factors
        w.writerow({
            "id": s.id, "title": s.title, "premise": s.premise, "status": s.review.status,
            "needs_research": s.review.needs_research, "effective_priority": s.scores.effective_priority,
            "story_score": s.scores.story_score, "evidence_score": s.scores.evidence_score,
            **{k: f[k].score if k in f else "" for k in ("hook", "narrative", "payoff", "emotion", "standalone")},
            "kind": s.kind, "nature": s.nature, "completeness": s.scores.completeness,
            "flags": " | ".join(f.text for f in s.flags), "figures": " ".join(f"p{f.page}" for f in s.figures),
            "curiosity_question": s.curiosity_question, "opening_hook": s.opening_hook,
            "overview": s.overview, "conflict": s.conflict, "stakes": s.stakes, "turning_point": s.turning_point,
            "outcome": s.outcome, "pages": review.compress_pages(pages),
            "sections": " | ".join(dict.fromkeys(r.section or r.chapter_title for r in s.references if r.section or r.chapter_title)),
            "paragraph_ids": " ".join(str(r.paragraph_id) for r in s.references),
            "claims": " | ".join(c.claim for c in s.claims),
            "unverified_quotes": sum(1 for c in s.claims if c.quote_verified is False),
            "uncertainties": " | ".join(s.uncertainties), "research_questions": " | ".join(s.research_questions),
            "duplicate_of": " ".join(d.id for d in s.duplicate_warnings), "related": " ".join(r.id for r in s.related),
            "notes": s.review.notes})
    return "﻿" + buf.getvalue()
