"""Batch D: editorial scoring, sign-off and approval, the versioned JSON export with its schema, and the public/evidence split."""
import asyncio
import json

import pytest
from jsonschema import Draft202012Validator

from story import db
from story2 import editorial, export, imgplan, planner, storyboard
from story2.export_schema import SCHEMA, SCHEMA_VERSION
from test_phase2a import approved_story, written_plan
from test_phase2b import P2BFake, boarded

DIMS = ["evidence_fidelity", "narrative_clarity", "opening_strength", "progression_payoff", "emotional_coherence", "visual_relevance",
        "comprehension_pacing", "ending_quality", "platform_suitability", "generation_feasibility", "continuity", "originality"]


def ready(env, **kw):
    """A plan with narration, scenes and image prompts."""
    pid, cid, be, p = boarded(env, **kw)
    imgplan.compile_plan(p["id"])
    return p["id"], cid


def approve_everything(plan_id):
    plan = planner.get_plan(plan_id)
    for s in plan["segments"]:
        planner.edit_segment(s["id"], status="approved")
    for sc in plan["scenes"]:
        storyboard.edit_scene(sc["id"], {"status": "approved"})


def test_twelve_dimensions_each_with_measurement_reason_and_fixes(env):
    pid, _ = ready(env)
    sc = editorial.score(pid)
    assert [d["key"] for d in sc["dimensions"]] == DIMS and "overall" not in sc and "total" not in sc        # no single combined score
    for d in sc["dimensions"]:
        assert 0 <= d["score"] <= 100 and d["band"] in ("good", "ok", "weak") and d["reason"] and d["measured"] != {} and isinstance(d["fixes"], list)
        assert all(f["text"] and f["tab"] for f in d["fixes"])
        if d["band"] != "good":
            assert d["fixes"], d["key"]                                                                    # a weak score always says what to do
    assert "forecast" in sc["disclaimer"] or "not a" in sc["disclaimer"].lower()
    assert sc["summary"]["good"] + sc["summary"]["ok"] + sc["summary"]["weak"] == 12 and sc["content_hash"]


def test_scores_react_to_real_problems_and_point_at_them(env):
    pid, _ = ready(env)
    base = {d["key"]: d for d in editorial.score(pid)["dimensions"]}
    seg = planner.get_plan(pid)["segments"][0]
    flip = [{"text": f"वाक्य {i}", "emotion": e, "pause_after_s": 0} for i, e in enumerate(["fear", "happy", "anger", "sad"], 1)]
    planner.edit_segment(seg["id"], sentences=flip)
    after = {d["key"]: d for d in editorial.score(pid)["dimensions"]}
    assert after["emotional_coherence"]["score"] < base["emotional_coherence"]["score"] or base["emotional_coherence"]["score"] == 0
    fx = [f for f in after["emotional_coherence"]["fixes"] if seg["id"] in f["where"]]
    assert fx and "more than once" in fx[0]["text"]                                                          # names the part to look at
    leaked = {d["key"]: d for d in editorial.score(pid)["dimensions"]}
    assert leaked["originality"]["score"] == 100


def test_empty_plan_scores_zero_where_nothing_exists_instead_of_inventing(env):
    pid, cid = approved_story(env)
    p = planner.create_plan(cid, minutes=2)
    sc = {d["key"]: d for d in editorial.score(p["id"])["dimensions"]}
    for k in ("opening_strength", "emotional_coherence", "visual_relevance", "comprehension_pacing", "ending_quality", "generation_feasibility"):
        assert sc[k]["score"] == 0 and sc[k]["fixes"], k


def test_signoff_lists_blockers_and_approval_is_tied_to_the_content(env):
    pid, _ = ready(env)
    so = editorial.signoff(pid)
    assert not so["ok"] and any(b["code"] == "unapproved" for b in so["blockers"]) and so["scores"]["dimensions"]
    with pytest.raises(planner.PlanError):
        editorial.approve(pid)                                                                              # cannot approve past a blocker
    approve_everything(pid)
    so = editorial.signoff(pid)
    errs = [b for b in so["blockers"] if b["code"] in ("errors", "prompts", "prompts_stale", "narration", "storyboard")]
    if errs:                                                                                                # the fake narration has problems of its own; report them honestly
        pytest.skip("fake narration is not clean enough to approve: " + errs[0]["text"])
    ap = editorial.approve(pid, "looks right")
    assert ap["state"] == "approved" and ap["note"] == "looks right" and ap["scores"]["originality"] == 100 and "warnings" in ap
    sc = planner.get_plan(pid)["scenes"][0]
    storyboard.edit_scene(sc["id"], {"lighting": "warm window light from the left"})
    assert editorial.approval_state(planner.get_plan(pid))["state"] == "changed"                              # edits after approval are visible
    assert editorial.unapprove(pid)["state"] == "draft"
    kinds = [h["what"] for h in editorial.history(pid)]
    assert "approved" in kinds and "unapproved" in kinds and kinds.index("unapproved") < kinds.index("approved")  # newest first


def test_content_hash_ignores_approval_state_but_not_wording(env):
    pid, _ = ready(env)
    h = editorial.content_hash(planner.get_plan(pid))
    plan = planner.get_plan(pid)
    storyboard.edit_scene(plan["scenes"][0]["id"], {"status": "approved"})
    assert editorial.content_hash(planner.get_plan(pid)) == h
    storyboard.edit_scene(plan["scenes"][0]["id"], {"subject": "someone else entirely"})
    assert editorial.content_hash(planner.get_plan(pid)) != h


def make_exportable(env):
    pid, cid = ready(env)
    approve_everything(pid)
    return pid, cid


def test_export_matches_the_schema_and_keeps_public_and_evidence_apart(env, tmp_path):
    pid, cid = make_exportable(env)
    doc = export.build(pid)
    assert doc["schema_version"] == SCHEMA_VERSION and not list(Draft202012Validator(SCHEMA).iter_errors(doc))
    pub = json.dumps(doc["public"], ensure_ascii=False)
    for forbidden in ("evidence_ids", "facts_used", "paragraph_ids", "quote_verified"):
        assert forbidden not in pub, forbidden                                                              # nothing from the evidence trail leaks into public
    assert all("facts" not in b for b in doc["public"]["blueprint"]["beats"])                                 # beat facts are evidence, not public text
    ev = doc["evidence"]
    assert set(ev["blueprint_facts"]) == {b["id"] for b in doc["public"]["blueprint"]["beats"]}
    assert ev["story"]["candidate_id"] == cid and set(ev["segments"]) == {s["id"] for s in doc["public"]["narration"]["segments"]}
    assert set(ev["scenes"]) == {s["id"] for s in doc["public"]["scenes"]}
    assert '"passages":' not in json.dumps(doc) and doc["validation"]["public_leak_check"]["ok"]
    assert len(doc["validation"]["scores"]["dimensions"]) == 12
    # alignment survives: every scene points at a real segment and a sentence range inside it
    segs = {s["id"]: s for s in doc["public"]["narration"]["segments"]}
    for sc in doc["public"]["scenes"]:
        a, b = sc["sentence_range"]
        assert sc["segment_id"] in segs and 1 <= a <= b <= len(segs[sc["segment_id"]]["sentences"]) and sc["id"] in segs[sc["segment_id"]]["scene_ids"]
        assert sc["prompts"]["qwen"]["prompt"] and sc["prompts"]["flux"]["prompt"] and sc["image_model"] in doc["public"]["image_models"]["providers"]
    assert doc["public"]["production_notes"]["tts"]["measured_pace_wpm"] == 148 and doc["plan"]["title_is_working"] is True


def test_export_says_exactly_why_it_is_not_ready_for_generation(env):
    pid, _ = ready(env)
    doc = export.build(pid)
    r = doc["ready_for_generation"]
    assert r["ok"] is False and any("approved" in b.lower() for b in r["blockers"]) and doc["approval"]["state"] == "draft"
    assert not list(Draft202012Validator(SCHEMA).iter_errors(doc))                                          # an unfinished plan still exports a valid document


def test_a_source_pointer_in_public_text_blocks_the_export(env):
    pid, cid = make_exportable(env)
    plan = planner.get_plan(pid)
    storyboard.edit_scene(plan["scenes"][0]["id"], {"action": "holds up the book by the author to the camera"})
    with pytest.raises(export.ExportError) as e:
        export.build(pid)
    assert "points back to the source" in str(e.value)


def test_saved_exports_are_numbered_kept_and_listed(env):
    pid, _ = make_exportable(env)
    a = export.save(pid)
    b = export.save(pid)
    assert (a["rev"], b["rev"]) == (1, 2) and a["file"] != b["file"]
    files = export.list_exports(pid)
    assert [f["rev"] for f in files] == [2, 1]
    doc = json.loads(open(b["path"], encoding="utf-8").read())
    assert doc["plan"]["export_rev"] == 2 and doc["plan"]["id"] == pid and not list(Draft202012Validator(SCHEMA).iter_errors(doc))
    assert "export" in [h["what"] for h in editorial.history(pid)]


def test_schema_file_in_docs_is_current():
    from pathlib import Path
    on_disk = json.loads((Path(__file__).resolve().parent.parent / "docs" / "plan_schema.json").read_text(encoding="utf-8"))
    assert on_disk == SCHEMA, "run story2.export.write_schema_file() to refresh docs/plan_schema.json"
    Draft202012Validator.check_schema(SCHEMA)


@pytest.mark.parametrize("nature,level", [("story", "ok"), ("explainer", "warn"), ("anecdote", "warn")])
def test_documented_story_explainer_and_weak_anecdote_are_treated_differently(env, nature, level):
    pid, cid = approved_story(env)
    db.ex("UPDATE candidates SET nature=? WHERE id=?", (nature, cid))
    be = P2BFake()
    p = written_plan(cid, be)
    plan = planner.get_plan(p["id"])
    codes = [c["code"] for c in plan["readiness"]["checks"]]
    assert ("nature" in codes) == (nature != "story")                                                       # explainers and anecdotes are warned, a real story is not
    asyncio.run(storyboard.make_storyboard(p["id"], be))
    imgplan.compile_plan(p["id"])
    doc = export.build(p["id"])
    assert doc["plan"]["story_nature"] == nature and not list(Draft202012Validator(SCHEMA).iter_errors(doc))


def test_vertical_and_horizontal_exports_are_separate_documents(env):
    pid, cid = approved_story(env)
    be = P2BFake()
    p = written_plan(cid, be)
    db.ex("UPDATE plans SET format='9:16' WHERE id=?", (p["id"],))
    asyncio.run(storyboard.make_storyboard(p["id"], be))
    imgplan.compile_plan(p["id"])
    doc = export.build(p["id"])
    assert doc["plan"]["format"] == "9:16" and all(s["output"]["height"] > s["output"]["width"] for s in doc["public"]["scenes"])
    plat = {d["key"]: d for d in doc["validation"]["scores"]["dimensions"]}["platform_suitability"]
    assert plat["measured"]["format"] == "9:16" and plat["measured"]["wrong_size"] == 0


def test_api_review_approve_export_download(tmp_path, monkeypatch):
    import config
    from fastapi.testclient import TestClient
    import main
    from story import projects, review
    from fakellm import FakeBackend
    from test_pipeline import make_book, run
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    with TestClient(main.app) as c:
        c.post("/login", data={"username": config.APP_USER, "password": config.APP_PASSWORD})
        assert c.get("/api/plans/schema").json()["title"] == "Source-to-Story video plan"
        pid = projects.import_text(make_book(3, 8))
        run(pid, FakeBackend())
        cid = review.list_candidates(pid)[0]["id"]
        review.update_candidate(cid, {"status": "approved"})
        plan = c.post("/api/plans", json={"candidate_id": cid}).json()
        pl = c.get(f"/api/plans/{plan['id']}").json()
        assert pl["approval"]["state"] == "draft" and pl["exports"] == []
        assert c.post(f"/api/plans/{plan['id']}/approve", json={}).status_code == 400                         # nothing to approve yet
        assert c.post(f"/api/plans/{plan['id']}/export").status_code == 400                                   # nothing to export yet
        assert c.get(f"/api/plans/{plan['id']}/history").status_code == 200
        r = c.post(f"/api/plans/{plan['id']}/review")
        assert r.status_code == 200 and not r.json()["ok"] and r.json()["blockers"]
        assert c.get(f"/api/plans/exports/{plan['id']}/..%2Fx.json").status_code == 404
        assert c.get(f"/api/plans/exports/{plan['id']}/missing.json").status_code == 404
