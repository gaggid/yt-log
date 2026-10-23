import json

from fakellm import FakeBackend
from story import db, projects, review, scoring
from story.pipeline import done_results, stage_tasks
from story.schemas import DraftOut, Event
from test_pipeline import make_book, run


def draft_json(**over):
    f = {"score": 5, "reason": "r"}
    d = {"title": "T", "premise": "p", "overview": "o", "claims": [{"claim": "c", "quote": "", "para_ids": [1]}],
         "scores": {k: f for k in ("hook", "narrative", "payoff", "emotion", "standalone")}, "evidence": f}
    d.update(over)
    return d


def test_paragraph_tags_never_survive_in_text_fields():
    d = DraftOut.model_validate(draft_json(
        overview="It fell on June 22 [P1454] and recovered (P12, P14).", outcome="Ended [P3-P5]",
        chronology=[{"when": "June 22 [P1454]", "what": "Gap opened [P12]"}], uncertainties=["unclear [P9]"]))
    blob = json.dumps(d.model_dump())
    assert "[P" not in blob and "(P1" not in blob and d.chronology[0].when == "June 22"
    assert Event(what="x [P2]", when="1901 [P2]", para_ids=[2]).para_ids == [2]       # ids stay in the id field


def test_date_basis_and_year_detection():
    src = ["On June 22 the stock gapped down at the open."]
    assert scoring.date_basis("June 22", src) == "stated"
    assert scoring.date_basis("June 22, 2006", src) == "inferred"                      # the year was added by the model
    assert scoring.date_basis("", src) == ""
    assert not scoring.has_year(src) and scoring.has_year(["in 2006 it fell"])


def test_nature_only_downgrades_and_hypotheticals_are_caught():
    assert scoring.final_nature("story", ["x"], 4, True)[0] == "story"
    assert scoring.final_nature("story", ["x"], 1, True)[0] == "anecdote"
    assert scoring.final_nature("story", ["x"], 4, False)[0] == "anecdote"
    hypo = ["Suppose you buy 100 shares. Imagine it falls. For example, say you sell. Assume a gap."]
    assert scoring.final_nature("story", hypo, 1, True)[0] == "hypothetical"
    assert scoring.final_nature("explainer", ["x"], 0, False)[0] == "explainer"


def test_completeness_is_separate_from_evidence_and_capped_by_nature():
    whole = {"turning_point": "t", "outcome": "o", "conflict": "c", "chronology": [{"basis": "quoted"}] * 3}
    full, detail = scoring.completeness(whole, "story", 3)
    assert full == 100 and detail["parts"]["locality"] == 20
    assert scoring.completeness(whole, "explainer", 3)[0] == 40                         # perfect quotes cannot lift an explainer
    scattered, _ = scoring.completeness(whole, "story", 170)
    assert scattered == 80
    assert scoring.priority(80, 100, 0.4, 40, 0.4) < scoring.priority(80, 100, 0.4, 100, 0.4)
    assert scoring.priority(80, 100, 0.4) == 80.0                                       # unchanged when no completeness is known


def test_pipeline_labels_scores_and_flags(env):
    pid = projects.import_text(make_book(3, 8))
    assert run(pid, FakeBackend()) == "done"
    rows = review.list_candidates(pid)
    assert rows and all(r["nature"] == "anecdote" for r in rows)                       # one-event chronology and no outcome: not a full story
    c = review.get_candidate(rows[0]["id"])
    d = c["data"]
    assert d["nature"] == "anecdote" and c["completeness"] == d["completeness"]["score"] <= 60
    assert any(f["code"] == "gap" and "outcome" in f["text"].lower() for f in d["flags"])
    assert any(f["code"] == "nature" for f in d["flags"])
    ch = d["chronology"][0]
    assert "[P" not in ch["what"] and ch["when"] == "1901" and ch["when_basis"] == "inferred" and ch["para_ids"]  # year not in the text
    bases = {x["claim"]: x["basis"] for x in d["claims"]}
    assert bases["Something is true"] == "quoted" and bases["Invented quote claim"] == "summarised"   # unverified quote is demoted
    assert review.list_candidates(pid, nature="story") == [] and len(review.list_candidates(pid, nature="anecdote,story")) == len(rows)


def test_discovery_windows_scale_with_chapters(env):
    pid = projects.import_text(make_book(8, 6))
    run(pid, FakeBackend())
    assert len(stage_tasks(pid, "discover")) >= 3                                       # 8 chapters, 3 per window


def test_seeds_the_shortlist_missed_become_leads(env):
    pid = projects.import_text(make_book(4, 30))
    fake = FakeBackend(discover_limit=1)
    run(pid, fake)
    shortlisted = sum(len(r.get("stubs", [])) for st in ("discover", "discover_global") for r in done_results(pid, st))
    seeds = sum(len(r["seeds"]) for r in done_results(pid, "rollup"))
    stories = len(review.list_candidates(pid))
    assert shortlisted < seeds and stories > shortlisted - 1 and stories >= seeds - 1      # unshortlisted seeds still reach review


def test_draft_gets_neighbouring_passages_with_stories_ranked_first(env):
    pid = projects.import_text(make_book(2, 10))
    fake = FakeBackend()
    run(pid, fake)
    first = [c for c in fake.calls if c["task"] == "draft_story"][0]["user"]
    import re
    ids = [int(i) for i in re.findall(r"^\[P(\d+)\]", first, re.M)]
    assert ids == sorted(ids) and len(ids) > 3 and ids[-1] - ids[0] >= len(ids) - 1      # consecutive: cited + surroundings


def test_export_v11_carries_nature_flags_provenance_and_completeness(env):
    from story import export
    pid = projects.import_text(make_book(3, 8))
    run(pid, FakeBackend())
    doc = export.build(pid, ["pending"])
    s = doc.stories[0]
    assert doc.schema_version == "1.1" and s.nature == "anecdote" and s.scores.completeness is not None
    assert s.claims[0].basis in ("quoted", "summarised") and s.chronology[0].when_basis == "inferred"
    assert any(f.code == "gap" for f in s.flags) and "nature" in export.CSV_COLUMNS
    assert "anecdote" in export.to_csv(doc)


def test_figure_captions_credits_and_spaced_headings():
    from story import figures
    assert figures.despace("w for F I G U R e 1.1 FedEx Gap") == "w for FIGURe 1.1 FedEx Gap"
    assert figures.despace("A few of us") == "A few of us"
    assert figures._caption("FIGURe 1.1 FedEx Gap esignal � 2009. all rights reserved").startswith("FIGURe 1.1 FedEx Gap")
    assert not figures._caption("The weather was fine and nothing else happened here.")
    assert figures.RIGHTS_RE.search("esignal � 2009. a division of Data Corp. all rights reserved. Used with permission.")
    assert not figures.RIGHTS_RE.search("The results were permitted to run.")


def test_story_needs_a_stated_date_and_rescore_reclassifies_without_the_model(env):
    assert scoring.final_nature("story", ["x"], 4, True, stated_dates=0)[0] == "anecdote"
    assert scoring.final_nature("story", ["x"], 4, True, stated_dates=2)[0] == "story"
    pid = projects.import_text(make_book(3, 8))
    run(pid, FakeBackend())
    cid = review.list_candidates(pid)[0]["id"]
    d = review.get_candidate(cid)["data"]
    d["nature"], d["model_nature"] = "story", "story"
    d["chronology"] = [{"when": "1901", "when_basis": "stated", "what": f"e{i}", "basis": "quoted", "para_ids": []} for i in range(4)]
    d["outcome"] = "it ended"
    db.ex("UPDATE candidates SET data=?, nature='story' WHERE id=?", (json.dumps(d), cid))
    review.rescore_project(pid, {"hook": 25, "narrative": 20, "payoff": 20, "emotion": 15, "standalone": 20}, 0.4, 0.4)
    assert review.get_candidate(cid)["nature"] == "story" and review.get_candidate(cid)["completeness"] > 60
    d["chronology"] = [{**c, "when_basis": "inferred"} for c in d["chronology"]]
    db.ex("UPDATE candidates SET data=? WHERE id=?", (json.dumps(d), cid))
    review.rescore_project(pid, {"hook": 25, "narrative": 20, "payoff": 20, "emotion": 15, "standalone": 20}, 0.4, 0.4)
    c = review.get_candidate(cid)
    assert c["nature"] == "anecdote" and c["completeness"] <= 60 and any(f["code"] == "nature" for f in c["data"]["flags"])


def test_arc_check_demotes_setup_examples_and_concepts():
    ev = {"actor": "Knight Capital", "decision": "deployed new code", "consequence": "lost money in 45 minutes", "form": "event"}
    assert scoring.final_nature("story", ["x"], 4, True, 2, ev)[0] == "story"
    assert scoring.final_nature("story", ["x"], 4, True, 2, {**ev, "form": "setup_example"})[0] == "anecdote"
    assert scoring.final_nature("story", ["x"], 4, True, 2, {**ev, "form": "concept"})[0] == "explainer"
    assert scoring.final_nature("story", ["x"], 4, True, 2, {**ev, "decision": ""})[0] == "anecdote"
    assert scoring.final_nature("story", ["x"], 4, True, 2, None)[0] == "story"          # old records without an arc keep their label


def test_flag_noise_is_trimmed():
    gaps = ["The exact value of the three-point spike", "The specific price of the moving averages", "The year it happened",
            "Who the traders were", "Why it ended", "The outcome for the firm"]
    kept = scoring.important_gaps(gaps, has_outcome=True)
    assert len(kept) == 3 and kept[0] == "The year it happened" and not any("price" in g for g in kept)
    assert scoring.important_gaps([], has_outcome=False) == ["the outcome"]
    clash = ["Sears = Sears Roebuck, but the text is about a stock", "Knight Capital = the 2012 trading disaster"]
    assert scoring.real_title_flags(clash) == ["Knight Capital = the 2012 trading disaster"]


def test_pipeline_gap_flag_is_one_short_line(env):
    pid = projects.import_text(make_book(3, 8))
    run(pid, FakeBackend())
    d = review.get_candidate(review.list_candidates(pid)[0]["id"])["data"]
    gaps = [f for f in d["flags"] if f["code"] == "gap"]
    assert len(gaps) == 1 and gaps[0]["text"].startswith("Not in the source:") and d["arc"]["form"] == "event"
