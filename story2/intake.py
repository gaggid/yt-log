"""Load an approved Phase 1 story as the input to Phase 2, and judge whether the evidence is ready.

The planner sees only what is needed to tell the story in our own words: facts, people, order of events. Source quotes, page
numbers, figure credits and paragraph ids stay in the `evidence` part and never reach a narration prompt.
"""
from story import db, review, storytypes


class IntakeError(Exception):
    pass


def load(candidate_id: str) -> dict:
    try:
        c = review.get_candidate(candidate_id)
    except review.ReviewError as e:
        raise IntakeError(str(e)) from e
    d = c["data"]
    public = {
        "premise": c["premise"], "overview": d.get("overview", ""), "people": d.get("people", []),
        "chronology": [{"when": x.get("when", ""), "when_basis": x.get("when_basis", ""), "what": x["what"]} for x in d.get("chronology", [])],
        "conflict": d.get("conflict", ""), "stakes": d.get("stakes", ""), "turning_point": d.get("turning_point", ""),
        "outcome": d.get("outcome", ""), "context_needed": d.get("context_needed", []),
        "claims": [x["claim"] for x in d.get("claims", [])],           # claim text only: quotes never travel
        "uncertainties": d.get("uncertainties", []), "gaps": d.get("gaps", []),
        "arc": d.get("arc", {}),
    }
    evidence = {
        "candidate_id": c["id"], "project_id": c["project_id"], "working_title": c["title"],
        "paragraph_ids": [r["idx"] for r in c["refs"]],
        "passages": [r["text"] for r in c["refs"]],                    # used only by the leak/overlap validator
        "pages": sorted({r["page"] for r in c["refs"] if r["page"]}),
        "claims": [{"claim": x["claim"], "basis": x.get("basis", ""), "quote_verified": x.get("quote_verified"),
                    "paragraph_ids": x.get("para_ids", [])} for x in d.get("claims", [])],
        "figures": c.get("figures", []), "flags": d.get("flags", []),
        "scores": {"story": c["eff_story"], "evidence": c["evidence_score"], "completeness": c["completeness"]},
    }
    return {"candidate": {"id": c["id"], "status": c["status"], "nature": c["nature"] or d.get("nature", ""),
                          "research": bool(c["research"])},
            "public": public, "evidence": evidence}


def readiness(story: dict, allow_unapproved: bool = False) -> dict:
    """Checks with a level: ok, warn (proceed, editor decides) or blocked. Missing evidence is reported, never invented."""
    cand, pub, ev = story["candidate"], story["public"], story["evidence"]
    checks: list[dict] = []

    def add(level, code, text):
        checks.append({"level": level, "code": code, "text": text})

    if cand["status"] == "superseded":
        add("blocked", "superseded", "This story was merged or split; use its replacement.")
    elif cand["status"] == "rejected":
        add("blocked", "rejected", "This story was rejected in review.")
    elif cand["status"] != "approved":
        add("warn" if allow_unapproved else "blocked", "not_approved", "The story is not approved yet. Approve it in Stories first.")
    if not pub["overview"] and not pub["chronology"]:
        add("blocked", "no_facts", "The story has no overview or events to tell.")
    nat = cand["nature"]
    stype = storytypes.for_pid(ev["project_id"])
    if stype != "incident":
        if nat in ("anecdote", "hypothetical"):
            add("warn", "nature", f"Labelled {nat}: it is a thin base for a {storytypes.STORY_TYPES[stype]['label'].lower()}; add related material or pick a stronger lead.")
    elif nat in ("explainer", "hypothetical"):
        add("warn", "nature", f"Labelled {nat}: it will work best as a problem-and-mechanism piece, not a suspense story.")
    elif nat == "anecdote":
        add("warn", "nature", "A short anecdote: consider a short video or combine it with related stories.")
    if not pub["outcome"] and stype in ("incident", "documentary"):
        add("warn", "outcome", "The outcome is not in the source. The telling must not invent one; it can end on the open question.")
    stated = sum(1 for x in pub["chronology"] if x["when_basis"] == "stated")
    if pub["chronology"] and not stated:
        add("warn", "dates", "No event has a date stated in the source. Do not give dates in the narration."
            + (" A biography leans on dates: expect a thin life story." if stype == "biography" else ""))
    if len(ev["paragraph_ids"]) < 3:
        add("warn", "thin", "Only a few source passages support this story; keep the telling short.")
    if any(f.get("rights_flag") for f in ev["figures"]):
        add("warn", "figures_rights", "Charts near this story carry a rights notice. They are not reusable; they will be rebuilt from facts later.")
    if any(f["code"] == "stitched" for f in ev["flags"]):
        add("warn", "stitched", "The source passages are far apart; check the order of events before narrating.")
    add("warn", "verification", "Not independently verified yet (allowed). Mark stays on the plan; research questions remain open.")
    level = "blocked" if any(c["level"] == "blocked" for c in checks) else "warn" if any(c["level"] == "warn" for c in checks) else "ok"
    return {"level": level, "ready": level != "blocked", "checks": checks}


def facts_text(pub: dict) -> str:
    """Plain-language facts block for the planner: our understanding of the story, with no source wording attached."""
    L = [f"Premise: {pub['premise']}", f"Overview: {pub['overview']}"]
    if pub["people"]:
        L.append("People and organisations: " + "; ".join(f"{p['name']} ({p['role']})" if p.get("role") else p["name"] for p in pub["people"]))
    if pub["chronology"]:
        L.append("What happened, in order:")
        L += [f"- {(x['when'] + ': ') if x['when'] else ''}{x['what']}" for x in pub["chronology"]]
    for k, label in (("conflict", "The tension"), ("stakes", "What was at stake"), ("turning_point", "The turning point"), ("outcome", "How it ended")):
        L.append(f"{label}: {pub[k] or 'NOT KNOWN - do not invent'}")
    if pub["context_needed"]:
        L.append("Background a viewer needs: " + "; ".join(pub["context_needed"]))
    if pub["claims"]:
        L.append("Key points to get right:")
        L += [f"- {c}" for c in pub["claims"]]
    if pub["uncertainties"] or pub["gaps"]:
        L.append("Unknown or uncertain (do not state as fact): " + "; ".join(pub["uncertainties"] + pub["gaps"]))
    return "\n".join(L)
