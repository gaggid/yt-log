"""Every blocking check has a way out: an explanation, a fix the app can do, and a plain-words result."""
import asyncio

import pytest
from fastapi import HTTPException

from story import db
from story2 import api, planner, resolve, storyboard
from test_phase2b import boarded


def put_issues(plan_id, narration=None, storyboard_=None, prompts=None):
    p = planner.get_plan(plan_id)
    v = {**(p["validation"] or {})}
    v["issues"] = narration or []
    v["storyboard"] = {"issues": storyboard_ or [], "ok": not storyboard_}
    v["prompts"] = {"issues": prompts or [], "ok": not prompts}
    db.ex("UPDATE plans SET validation=? WHERE id=?", (db.jdump(v), plan_id))


def test_every_catalogued_blocker_names_real_fixes_and_a_place_to_go():
    assert resolve.CATALOG and all(c["fixes"] and all(f in resolve.FIXES for f in c["fixes"]) and c["why"] and c["jump"].startswith("sec-") for c in resolve.CATALOG.values())
    assert all(f["kind"] in ("instant", "job") and f["label"] and f["does"] for f in resolve.FIXES.values())
    assert resolve.DEFAULT["fixes"] == ["recheck"]                                                # a kind nobody catalogued still has a button


def test_blockers_are_grouped_explained_and_unknown_kinds_still_get_a_way_out(env):
    pid, cid, be, p = boarded(env)
    sc = p["scenes"][0]["id"]
    put_issues(p["id"], prompts=[{"where": sc, "kind": "continuity", "level": "error", "text": "the trader: “hair: grey” must stay the same but is not in the prompt"},
                                 {"where": sc, "kind": "continuity", "level": "error", "text": "the trader: “top: coat” must stay the same but is not in the prompt"},
                                 {"where": sc, "kind": "mystery", "level": "error", "text": "something new"},
                                 {"where": sc, "kind": "vague", "level": "warn", "text": "not a blocker"}])
    bl = resolve.blockers(p["id"])
    assert [b["kind"] for b in bl] == ["continuity", "mystery"] and bl[0]["count"] == 2
    assert [f["id"] for f in bl[0]["fixes"]] == ["recompile", "relax", "recheck"] and bl[0]["why"] and bl[0]["jump"] == "sec-assets"
    assert [f["id"] for f in bl[1]["fixes"]] == ["recheck"] and bl[1]["manual"] and bl[1]["sample"] == "something new"


def test_relax_moves_the_named_details_to_flexible_and_the_message_says_so(env):
    pid, cid, be, p = boarded(env)
    person = next(a for a in storyboard.get_assets(p["id"]) if a["kind"] == "person")
    detail = person["data"]["fixed"][0]
    put_issues(p["id"], prompts=[{"where": p["scenes"][0]["id"], "kind": "continuity", "level": "error",
                                  "text": f"{person['name']}: “{detail}” must stay the same but is not in the prompt"}])
    msg = resolve.run_instant(p["id"], "relax", "Image prompts|continuity")
    after = next(a for a in storyboard.get_assets(p["id"]) if a["id"] == person["id"])
    assert detail not in after["data"]["fixed"] and detail in after["data"]["flexible"]
    assert "Moved 1 detail(s)" in msg and detail in msg and "error(s) before" in msg or "cleared" in msg


def test_recheck_clears_a_report_left_over_from_before_the_last_change(env):
    pid, cid, be, p = boarded(env)
    put_issues(p["id"], storyboard_=[{"where": p["scenes"][0]["id"], "kind": "purpose", "level": "error", "text": "no narrative purpose"}])
    assert resolve.blockers(p["id"])
    msg = resolve.run_instant(p["id"], "recheck", "Storyboard|purpose")
    assert not resolve.blockers(p["id"]) and "cleared" in msg and "you can move on" in msg


def test_scenes_whose_narration_is_gone_can_be_removed_and_nothing_else(env):
    pid, cid, be, p = boarded(env)
    n = len(p["scenes"])
    db.ex("UPDATE scenes SET segment_id='seg-gone' WHERE id=?", (p["scenes"][0]["id"],))
    assert resolve.drop_orphans(p["id"]) == 1 and len(storyboard.get_scenes(p["id"])) == n - 1


def test_a_model_fix_redesigns_only_the_named_unlocked_scenes_and_reports(env):
    pid, cid, be, p = boarded(env)
    a, b = p["scenes"][0]["id"], p["scenes"][1]["id"]
    storyboard.edit_scene(b, {"locked": True})
    put_issues(p["id"], storyboard_=[{"where": a, "kind": "purpose", "level": "error", "text": "no narrative purpose"},
                                     {"where": b, "kind": "purpose", "level": "error", "text": "no narrative purpose"}])
    from story import settings as settings_mod
    out = asyncio.run(resolve.run_job(p["id"], "redo_scenes", "Storyboard|purpose", be, settings_mod.get(), lambda *x: None))
    assert "Redesigned 1 scene(s)" in out and "1 locked scene(s) were kept" in out


def test_the_resolve_endpoint_runs_an_instant_fix_and_refuses_a_fix_that_was_not_offered(env):
    pid, cid, be, p = boarded(env)
    put_issues(p["id"], storyboard_=[{"where": p["scenes"][0]["id"], "kind": "purpose", "level": "error", "text": "no narrative purpose"}])
    with pytest.raises(HTTPException) as e:
        asyncio.run(api.resolve_blocker(p["id"], api.ResolveReq(key="Storyboard|purpose", fix="retime")))
    assert e.value.status_code == 400
    out = asyncio.run(api.resolve_blocker(p["id"], api.ResolveReq(key="Storyboard|purpose", fix="recheck")))
    assert out["kind"] == "instant" and out["blockers"] == [] and "cleared" in out["message"]
    again = asyncio.run(api.resolve_blocker(p["id"], api.ResolveReq(key="Storyboard|purpose")))
    assert "already cleared" in again["message"]                                                     # pressing a stale button is answered, not an error


def test_the_plan_answer_carries_the_blockers_for_the_screen(env):
    pid, cid, be, p = boarded(env)
    put_issues(p["id"], storyboard_=[{"where": p["scenes"][0]["id"], "kind": "orphan", "level": "error", "text": "its narration segment no longer exists"}])
    out = asyncio.run(api.plan(p["id"]))
    assert out["blockers"][0]["kind"] == "orphan" and out["blockers"][0]["fixes"][0]["id"] == "drop_orphans"


def test_a_job_that_answers_with_text_leaves_it_as_the_note():
    from story2 import jobs

    async def go():
        async def work(progress):
            return "Rewrote 2 beats."
        jobs.start("pl-note", "fix", work)
        await jobs._current["task"]
        return jobs.status("pl-note")
    assert asyncio.run(go())["note"] == "Rewrote 2 beats."
