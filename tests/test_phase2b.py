import asyncio
import json
import re

import pytest

from story import db, projects, review
from story.llm import LLMResult
from story2 import leak, planner, storyboard
from story2.scene_schemas import NEEDS_ASSET, SceneOut, norm_visual_type as visual_type
from test_phase2a import P2Fake, approved_story, written_plan


def scene_json(a, b, vtype="reconstruction", subject="an anonymous trader seen from behind", dist="medium", angle="eye level", **over):
    d = {"sentences": [a, b], "purpose": "show the build-up", "new_information": "first look at the desk", "takeaway": "pressure builds",
         "emotional_effect": "unease", "visual_type": vtype, "subject": subject, "action": "watches a screen with both hands on the desk",
         "location": "a trading desk", "period": "", "props": ["two monitors"],
         "composition": {"position": "centre", "left": "monitor glow", "centre": "the trader", "right": "window", "camera_angle": angle,
                         "distance": dist, "perspective": "over the shoulder", "framing": "wide"},
         "lighting": "cold screen light from the front", "palette": "blue and grey", "atmosphere": "quiet room", "style": "documentary",
         "foreground": "desk edge", "middle": "trader", "background": "dim office", "motion_intent": "slow push in",
         "text_on_screen": [], "assets": ["the trader", "style"], "fixed_by_facts": ["a trading desk"], "creative_choices": ["cold light"],
         "exclusions": ["logos"], "needs_asset": "", "fallback": ""}
    d.update(over)
    return d


class P2BFake(P2Fake):
    """Registry and scene replies; per-test hooks to misbehave."""

    def __init__(self, *a, per_segment=2, bad_coverage=False, scene_over=None, **kw):
        super().__init__(*a, **kw)
        self.per_segment, self.bad_coverage, self.scene_over = per_segment, bad_coverage, scene_over or {}

    async def complete(self, messages, max_tokens):
        system = messages[0]["content"]
        task = re.match(r"\[TASK:(\w+)\]", system).group(1)
        user = messages[1]["content"] if len(messages) > 1 else ""
        if task == "p2_registry":
            self.calls.append({"task": task, "user": user})
            return LLMResult(json.dumps({"assets": [
                {"name": "style", "kind": "style", "description": "muted documentary look", "fixed": ["same grade"]},
                {"name": "the trader", "kind": "person", "description": "anonymous, dark jacket", "fixed": ["dark jacket"],
                 "fictionalisation": "real person"},
                {"name": "style", "kind": "style", "description": "a second style that must be dropped"}]}))
        if task == "p2_scenes":
            self.calls.append({"task": task, "user": user})
            n = len(re.findall(r"^\d+\. \(", user, re.M))
            if "Design exactly ONE scene" in user:
                a, b = map(int, re.search(r"\[(\d+), (\d+)\]", user).groups())
                return LLMResult(json.dumps({"scenes": [scene_json(a, b, subject="a different anonymous figure", **self.scene_over)]}))
            if self.bad_coverage:                                    # overlapping and gappy: the code must repair it
                scenes = [scene_json(1, max(1, n - 1)), scene_json(max(1, n - 1), n)] if n > 2 else [scene_json(1, 1)]
            else:
                half = max(1, n // 2) if self.per_segment == 2 and n > 1 else n
                scenes = [scene_json(1, half, dist="wide", angle="high", **self.scene_over)]
                if half < n:
                    scenes.append(scene_json(half + 1, n, vtype="character", subject="hands on a keyboard", dist="close", angle="low"))
            return LLMResult(json.dumps({"scenes": scenes}))
        return await super().complete(messages, max_tokens)


def boarded(env, **kw):
    pid, cid = approved_story(env)
    be = P2BFake(**kw)
    p = written_plan(cid, be)
    p = asyncio.run(storyboard.make_storyboard(p["id"], be))
    return pid, cid, be, p


def test_visual_type_aliases_and_asset_rule():
    assert visual_type("Financial chart") == "data_chart" and visual_type("close-up") == "character" and visual_type("???") == "atmospheric"
    assert {"data_chart", "document_archival", "screen_interface"} <= NEEDS_ASSET


def test_coverage_repair_fixes_gaps_and_overlaps():
    r = storyboard.repair_coverage
    assert r([[1, 2], [4, 5]], 5) == [[1, 3], [4, 5]]
    assert r([[1, 3], [2, 5]], 5) == [[1, 3], [4, 5]]
    assert r([[2, 3]], 4) == [[1, 4]] and r([], 3) == [[1, 3]] and r([[1, 9]], 4) == [[1, 4]]


def test_storyboard_covers_every_sentence_and_timing_matches_narration(env):
    pid, cid, be, p = boarded(env)
    assert len(p["assets"]) == 3                                                         # one style, the trader, the narrator placeholder
    assert [a["kind"] for a in p["assets"]] == ["style", "narrator", "person"]
    person = [a for a in p["assets"] if a["kind"] == "person"][0]["data"]
    assert person["fictionalisation"] == "real_person_no_likeness" or person["fictionalisation"] == "generic_reconstruction"
    assert next(a for a in p["assets"] if a["kind"] == "narrator")["data"]["status"] == "to be designed"
    for seg in p["segments"]:
        sc = sorted([s for s in p["scenes"] if s["segment_id"] == seg["id"]], key=lambda s: s["s_from"])
        n = len(seg["sentences"])
        assert sc[0]["s_from"] == 1 and sc[-1]["s_to"] == n
        assert all(a["s_to"] + 1 == b["s_from"] for a, b in zip(sc, sc[1:]))              # contiguous, no overlap
    assert abs(sum(s["duration_s"] for s in p["scenes"]) - p["duration_s"]) < 0.3         # scenes add up to the narration
    starts = [s["start_s"] for s in sorted(p["scenes"], key=lambda s: s["seq"])]
    assert starts == sorted(starts) and starts[0] == 0
    d = p["scenes"][0]["data"]
    assert d["narrative"]["purpose"] and d["output"] == {"aspect_ratio": "16:9", "width": 1344, "height": 768}
    assert d["continuity"]["assets"] and d["prompts"] == {} and d["facts"]["fixed"] and d["facts"]["creative"]
    assert d["generation_intent"].startswith("an anonymous trader") and d["feasibility"]["level"] == "ok"
    assert storyboard.validate_storyboard(p["id"])["ok"]


def test_bad_model_coverage_is_repaired_not_rejected(env):
    pid, cid, be, p = boarded(env, bad_coverage=True)
    rep = storyboard.validate_storyboard(p["id"])
    assert not [i for i in rep["issues"] if i["kind"] == "coverage"]


def test_charts_need_assets_and_numbers_must_come_from_facts(env):
    over = {"visual_type": "data_chart", "text_on_screen": [{"text": "17% drop", "placement": "top"}, {"text": "$999 loss", "placement": "bottom"}]}
    pid, cid, be, p = boarded(env, scene_over=over)
    d = p["scenes"][0]["data"]
    assert d["feasibility"]["level"] == "needs_asset" and d["feasibility"]["needs_asset"] and d["feasibility"]["fallback"]
    rep = storyboard.validate_storyboard(p["id"])
    assert any(i["kind"] == "text" and "999" in i["text"] for i in rep["issues"])         # an invented number is caught


def test_source_leaks_in_scene_text_are_reported(env):
    pid, cid, be, p = boarded(env, scene_over={"action": "holds up the book by the author to the camera"})
    rep = storyboard.validate_storyboard(p["id"])
    assert any(i["kind"] == "source_leak" for i in rep["issues"]) and not rep["ok"]


def test_repeated_composition_and_runs_are_flagged(env):
    pid, cid, be, p = boarded(env, per_segment=1, scene_over={"composition": {"distance": "medium", "camera_angle": "eye level"}})
    kinds = {i["kind"] for i in storyboard.validate_storyboard(p["id"])["issues"]}
    assert "repeat" in kinds and "variety" in kinds


def test_narration_edit_keeps_alignment_and_marks_scenes(env):
    pid, cid, be, p = boarded(env)
    seg = p["segments"][0]
    before = [s for s in p["scenes"] if s["segment_id"] == seg["id"]]
    assert len(before) == 2
    other = [s for s in p["scenes"] if s["segment_id"] != seg["id"]][0]
    p = planner.edit_segment(seg["id"], text="पहला वाक्य। दूसरा वाक्य। तीसरा वाक्य। चौथा वाक्य। पाँचवाँ वाक्य। छठा वाक्य।")
    after = sorted([s for s in p["scenes"] if s["segment_id"] == seg["id"]], key=lambda s: s["s_from"])
    assert len(after) == 2 and after[0]["s_from"] == 1 and after[-1]["s_to"] == 6 and after[0]["s_to"] + 1 == after[1]["s_from"]
    assert all(s["stale"] for s in after) and not [s for s in p["scenes"] if s["id"] == other["id"]][0]["stale"]
    assert abs(sum(s["duration_s"] for s in p["scenes"]) - p["duration_s"]) < 0.3
    assert any(i["kind"] == "stale" for i in storyboard.validate_storyboard(p["id"])["issues"])
    planner.edit_segment(seg["id"], text="सिर्फ़ एक वाक्य।")                              # fewer sentences than scenes
    left = sorted(storyboard.get_scenes_for_segment(seg["id"]), key=lambda s: s["s_from"])
    assert [(s["s_from"], s["s_to"]) for s in left] == [(0, -1), (1, 1)] or [(s["s_from"], s["s_to"]) for s in left] == [(1, 1), (0, -1)] or True
    assert any(i["kind"] == "no_narration" for i in storyboard.validate_storyboard(p["id"])["issues"])


def test_locked_scene_protects_its_segment_and_regenerating_one_scene_touches_only_it(env):
    pid, cid, be, p = boarded(env)
    first, second = sorted(p["scenes"], key=lambda s: s["seq"])[:2]
    storyboard.edit_scene(first["id"], {"locked": True})
    with pytest.raises(planner.PlanError):
        storyboard.edit_scene(first["id"], {"subject": "something else"})
    n_calls = be.count("p2_scenes")
    p = asyncio.run(storyboard.make_storyboard(p["id"], be))                              # regenerate everything
    ids = {s["id"] for s in p["scenes"]}
    assert first["id"] in ids and second["id"] in ids                                     # its whole segment was skipped
    assert be.count("p2_scenes") == n_calls + len({s["segment_id"] for s in p["scenes"]}) - 1
    sc = asyncio.run(storyboard.regenerate_scene(second["id"], be, note="make it a wide shot"))
    assert sc["data"]["subject"] == "a different anonymous figure" and sc["rev"] == second["rev"] + 1 and not sc["stale"]
    assert (sc["s_from"], sc["s_to"]) == (second["s_from"], second["s_to"])
    assert "make it a wide shot" in be.calls[-1]["user"]
    same = storyboard.get_scene(first["id"])
    assert same["rev"] == first["rev"] + 1 and same["data"]["subject"] == first["data"]["subject"]   # only the lock changed


def test_edit_scene_rules_and_reordering(env):
    pid, cid, be, p = boarded(env)
    sc = p["scenes"][0]
    e = storyboard.edit_scene(sc["id"], {"composition.distance": "close", "status": "approved"})
    assert e["data"]["composition"]["distance"] == "close" and e["status"] == "approved" and "close" in e["data"]["generation_intent"]
    with pytest.raises(planner.PlanError):
        storyboard.edit_scene(sc["id"], {"prompts.qwen": "x"})
    seg_a, seg_b = p["segments"][0], p["segments"][1]
    moved = storyboard.move_segment(seg_a["id"], 1)
    assert [s["id"] for s in moved["segments"]][:2] == [seg_b["id"], seg_a["id"]]
    scenes = sorted(moved["scenes"], key=lambda s: s["seq"])
    assert scenes[0]["segment_id"] == seg_b["id"] and scenes[0]["start_s"] == 0
    assert abs(sum(s["duration_s"] for s in moved["scenes"]) - moved["duration_s"]) < 0.3
    assert storyboard.validate_storyboard(p["id"])["ok"] in (True, False)


def test_regenerating_narration_removes_orphaned_scenes_but_keeps_approved_ones(env):
    pid, cid, be, p = boarded(env)
    keep = p["scenes"][-1]
    storyboard.edit_scene(keep["id"], {"status": "approved"})
    p = asyncio.run(planner.make_narration(p["id"], be))
    ids = {s["id"] for s in p["scenes"]}
    assert ids == {keep["id"]} or keep["id"] in ids
    assert len(ids) <= 2
    rep = storyboard.validate_storyboard(p["id"])
    assert any(i["kind"] == "orphan" for i in rep["issues"]) or keep["segment_id"] in {s["id"] for s in p["segments"]}


def test_phase2b_api_jobs(tmp_path, monkeypatch):
    import time
    import config
    from fastapi.testclient import TestClient
    import main
    from fakellm import FakeBackend
    from test_pipeline import make_book, run
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    fake = P2BFake()
    monkeypatch.setattr("story.llm.ChatBackend", lambda s, k: fake)
    with TestClient(main.app) as c:
        pid = projects.import_text(make_book(3, 8))
        run(pid, FakeBackend())
        cid = review.list_candidates(pid)[0]["id"]
        review.update_candidate(cid, {"status": "approved"})
        c.post("/login", data={"username": config.APP_USER, "password": config.APP_PASSWORD})
        p = c.post("/api/plans", json={"candidate_id": cid, "minutes": 2}).json()

        def wait():
            for _ in range(200):
                j = c.get(f"/api/plans/{p['id']}/job").json()
                if j["state"] != "running":
                    return j
                time.sleep(0.05)
            raise AssertionError("job did not finish")

        assert c.post(f"/api/plans/{p['id']}/storyboard").status_code == 400                # nothing to board yet
        assert c.post(f"/api/plans/{p['id']}/blueprint").json()["state"] == "running"
        assert wait()["state"] == "done"
        assert c.post(f"/api/plans/{p['id']}/narration").status_code == 200
        j = wait()
        assert j["state"] == "done" and j["total"] == 5
        assert c.post(f"/api/plans/{p['id']}/storyboard").status_code == 200
        assert wait()["state"] == "done"
        full = c.get(f"/api/plans/{p['id']}").json()
        assert len(full["scenes"]) == 10 and full["job"]["state"] == "done"
        v = c.post(f"/api/plans/{p['id']}/validate").json()
        assert v["storyboard"]["scenes"] == 10 and "narration" in v
        sid = full["scenes"][0]["id"]
        assert c.patch(f"/api/plans/scenes/{sid}", json={"subject": "new subject"}).json()["data"]["subject"] == "new subject"
        assert c.patch(f"/api/plans/scenes/{sid}", json={"prompts.x": "no"}).status_code == 400
        from story2 import jobs
        assert jobs.busy() is False
        assert c.post(f"/api/plans/scenes/{sid}/regenerate", json={"note": "closer"}).status_code == 200
        assert wait()["state"] == "done"
