"""Story types (B1): the type is chosen on the project, copied to the plan, and read through story/storytypes.py; old projects and plans are `incident`."""
import asyncio

import pytest

from story import api as sapi, projects, storytypes
from story2 import api as p2api, planner
from test_phase2b import approved_story


def test_unset_or_unknown_type_is_incident():
    assert storytypes.of_plan({}) == storytypes.of_plan({"settings": {"story_type": "nonsense"}}) == storytypes.of_project({"meta": {}}) == "incident"
    assert set(storytypes.STORY_TYPES) == {"incident", "biography", "documentary", "explainer", "listicle"}


def test_project_type_is_stored_listed_and_validated(env):
    pid, cid = approved_story(env)
    assert projects.get(pid)["story_type"] == "incident"
    assert projects.set_story_type(pid, "biography")["story_type"] == "biography"
    with pytest.raises(projects.ProjectError):
        projects.set_story_type(pid, "podcast")
    assert {t["id"] for t in asyncio.run(sapi.story_types())["types"]} == set(storytypes.STORY_TYPES)


def test_import_with_a_type_sets_it_and_the_plan_copies_it(env):
    pid = asyncio.run(sapi.from_text(sapi.TextIn(text="A short article about a harbour. " * 40, title="t", story_type="documentary")))["id"]
    assert projects.get(pid)["story_type"] == "documentary"
    pid2, cid = approved_story(env)
    projects.set_story_type(pid2, "listicle")
    plan = planner.create_plan(cid, allow_unapproved=True)
    assert plan["settings"]["story_type"] == "listicle"
    got = asyncio.run(p2api.plan(plan["id"]))
    assert got["story_type"] == "listicle" and got["story_type_label"] == "Listicle"


def test_scoring_rules_depend_on_the_type():
    from story import scoring
    arc_bad = {"form": "event", "actor": "", "decision": "", "consequence": ""}
    assert scoring.final_nature("story", ["x"], 1, False, 0, arc_bad)[0] == "anecdote"                         # incident: strict
    assert scoring.final_nature("story", ["x"], 1, False, 0, arc_bad, "biography") == ("story", [])         # other types: a good fit stays a story
    d = {"chronology": [{}, {}, {}], "overview": "o", "turning_point": "t"}
    inc, _ = scoring.completeness(d, "story", 120, "incident")
    bio, detail = scoring.completeness(d, "story", 120, "biography")
    assert bio > inc and detail["story_type"] == "biography"                                                  # far-apart pages do not cost a life story


def test_phase1_prompts_carry_the_project_type(env):
    from story import pipeline
    pid, cid = approved_story(env)
    assert pipeline.Pipeline(pid, None).story_type == "incident"
    projects.set_story_type(pid, "listicle")
    assert pipeline.Pipeline(pid, None).story_type == "listicle"
    assert "LISTICLE" in storytypes.discover_note("listicle") and "LISTICLE" in storytypes.draft_note("listicle")
    assert storytypes.discover_note("incident") == storytypes.draft_note("incident") == ""


def test_pipeline_sends_the_type_note_to_the_model(env):
    import asyncio as aio
    from fakellm import FakeBackend
    from story.pipeline import Pipeline
    systems = []

    class Spy(FakeBackend):
        async def complete(self, messages, max_tokens):
            systems.append(messages[0]["content"])
            return await super().complete(messages, max_tokens)
    text = "In 1928 the harbour board surveyed the coast near the old pier and logged every reading carefully. " * 60
    pid = projects.import_text(text, title="Harbour")
    projects.set_story_type(pid, "biography")
    assert aio.run(Pipeline(pid, Spy()).run()) == "done"
    assert any("PROJECT TYPE: BIOGRAPHY" in s and s.startswith("[TASK:discover]") for s in systems)
    assert any("PROJECT TYPE: BIOGRAPHY" in s and s.startswith("[TASK:draft_story]") for s in systems)
    systems.clear()
    pid2 = projects.import_text(text, title="Harbour two")
    assert aio.run(Pipeline(pid2, Spy()).run()) == "done"
    assert not any("PROJECT TYPE" in s for s in systems)                  # incident projects are unchanged


def test_phase2_prompts_carry_the_plan_type(env):
    import json
    from test_phase2b import P2BFake, written_plan
    pid, cid = approved_story(env)
    projects.set_story_type(pid, "biography")
    systems = {}

    class Spy(P2BFake):
        async def complete(self, messages, max_tokens):
            systems.setdefault(messages[0]["content"].split("]")[0], []).append(messages[0]["content"])
            return await super().complete(messages, max_tokens)
    be = Spy()
    plan = written_plan(cid, be)                                    # blueprint + narration
    assert plan["settings"]["story_type"] == "biography"
    assert any("BIOGRAPHY" in s and "life_arc" in s for s in systems["[TASK:p2_blueprint"])
    assert any("PROJECT TYPE: BIOGRAPHY" in s for s in systems["[TASK:p2_narrate"])


def test_every_type_names_a_structure_the_blueprint_accepts():
    from story2.schemas import STRUCTURES
    for t, name in storytypes.STRUCTURE.items():
        assert name in STRUCTURES and name in storytypes.BLUEPRINT_NOTE[t]
    for t in ("biography", "documentary", "explainer", "listicle"):
        assert storytypes.narrate_note(t) and storytypes.director_note(t) and storytypes.blueprint_note(t)
    assert storytypes.blueprint_note("incident") == storytypes.narrate_note("incident") == storytypes.director_note("incident") == ""


def test_readiness_is_type_aware(env):
    from story import db
    from story2 import intake
    pid, cid = approved_story(env)
    db.ex("UPDATE candidates SET nature='explainer' WHERE id=?", (cid,))
    assert "nature" in {c["code"] for c in intake.readiness(intake.load(cid))["checks"]}              # incident: an explainer is a warning
    projects.set_story_type(pid, "explainer")
    assert "nature" not in {c["code"] for c in intake.readiness(intake.load(cid))["checks"]}          # explainer project: it is the point
    db.ex("UPDATE candidates SET nature='anecdote' WHERE id=?", (cid,))
    assert "nature" in {c["code"] for c in intake.readiness(intake.load(cid))["checks"]}


def test_director_gets_the_type_note(env):
    from story2 import director
    from test_phase2b import P2BFake, boarded, written_plan
    pid, cid = approved_story(env)
    projects.set_story_type(pid, "listicle")
    seen = []

    class Spy(P2BFake):
        async def complete(self, messages, max_tokens):
            if "[TASK:p2_director]" in messages[0]["content"]:
                seen.append(messages[0]["content"])
            return await super().complete(messages, max_tokens)
    from story2 import storyboard
    be = Spy()
    plan = written_plan(cid, be)
    asyncio.run(storyboard.make_registry(plan["id"], be))
    asyncio.run(storyboard.make_storyboard(plan["id"], be))
    assert seen and all("PROJECT TYPE: LISTICLE" in s for s in seen)


def test_scene_designer_is_told_which_cards_the_type_wants(env):
    from story2 import storyboard
    from test_phase2b import P2BFake, written_plan
    pid, cid = approved_story(env)
    projects.set_story_type(pid, "listicle")
    seen = []

    class Spy(P2BFake):
        async def complete(self, messages, max_tokens):
            if "[TASK:p2_scenes]" in messages[0]["content"]:
                seen.append(messages[0]["content"])
            return await super().complete(messages, max_tokens)
    be = Spy()
    plan = written_plan(cid, be)
    asyncio.run(storyboard.make_registry(plan["id"], be))
    asyncio.run(storyboard.make_storyboard(plan["id"], be))
    assert seen and all("number card" in s for s in seen)
    assert storytypes.scenes_note("incident") == ""
    assert all(storytypes.scenes_note(t) for t in ("biography", "documentary", "explainer", "listicle"))


def test_a_listicle_number_card_is_built_by_the_existing_text_template():
    """The scene designer asks for visual_type diagram + one short English text; graphics.spec_for turns that into the text card (no new drawing code needed)."""
    from story3 import graphics
    scene = {"data": {"visual_type": "diagram", "subject": "item", "action": "", "text_on_screen": [{"text": "3. The quiet fix"}], "facts": {"fixed": []}}}
    spec = graphics.spec_for(scene, {"known": set(), "pub": {"chronology": []}, "text": "", "lower": ""})
    assert spec["template"] == "text" and spec["title"] == "3. The quiet fix"


def test_the_export_records_the_story_type_and_still_validates(env):
    from jsonschema import Draft202012Validator
    from story import db
    from story2 import export
    from story2.export_schema import SCHEMA
    from test_phase2d import make_exportable
    pid, cid = make_exportable(env)
    assert export.build(pid)["plan"]["story_type"] == "incident"
    p = planner.get_plan(pid)
    db.ex("UPDATE plans SET settings=? WHERE id=?", (db.jdump({**p["settings"], "story_type": "documentary"}), pid))
    doc = export.build(pid)
    assert doc["plan"]["story_type"] == "documentary" and not list(Draft202012Validator(SCHEMA).iter_errors(doc))


def test_plan_screen_flags_a_project_type_changed_after_the_plan(env):
    pid, cid = approved_story(env)
    plan = planner.create_plan(cid, allow_unapproved=True)
    projects.set_story_type(pid, "biography")
    got = asyncio.run(p2api.plan(plan["id"]))
    assert got["story_type"] == "incident" and got["project_story_type"] == "biography"


def test_a_short_video_gets_few_beats_and_the_cap_reaches_the_blueprint_request(env):
    from test_phase2b import P2BFake
    assert planner.max_beats(1) == 3 and planner.max_beats(8) == 9 and planner.max_beats(3) == 9 and planner.max_beats(2) == 7
    pid, cid = approved_story(env)
    plan = planner.create_plan(cid, minutes=1)
    seen = []

    class Spy(P2BFake):
        async def complete(self, messages, max_tokens):
            if "[TASK:p2_blueprint]" in messages[0]["content"]:
                seen.append(messages[1]["content"])
            return await super().complete(messages, max_tokens)
    asyncio.run(planner.make_blueprint(plan["id"], Spy()))
    assert seen and "AT MOST 3 beats" in seen[0]


def test_characters_cannot_be_created_before_the_cast_is_chosen(env):
    from fastapi import HTTPException
    pid, cid = approved_story(env)
    plan = planner.create_plan(cid, allow_unapproved=True)
    with pytest.raises(HTTPException) as e:
        asyncio.run(p2api.registry(plan["id"]))
    assert "choose who appears in the pictures" in e.value.detail


def test_planning_the_story_again_removes_narration_of_beats_that_no_longer_exist(env):
    from story import db
    from test_phase2b import P2BFake, written_plan
    pid, cid = approved_story(env)
    be = P2BFake()
    plan = written_plan(cid, be)
    keep = plan["blueprint"]["beats"][0]["id"]
    bp = {**plan["blueprint"], "beats": plan["blueprint"]["beats"][:1]}
    db.ex("UPDATE plans SET blueprint=? WHERE id=?", (db.jdump(bp), plan["id"]))
    asyncio.run(planner.make_narration(plan["id"], be, None, None, None, False))
    assert {s["beat"] for s in planner.get_plan(plan["id"])["segments"]} == {keep}


def test_a_beat_far_longer_than_its_share_of_the_target_is_sent_back_once(env, monkeypatch):
    from test_phase2b import P2BFake
    monkeypatch.setattr(planner, "LONG_BEAT_FACTOR", 1.6)
    pid, cid = approved_story(env)
    plan = planner.create_plan(cid, minutes=1, allow_unapproved=True)
    be = P2BFake()
    asyncio.run(planner.make_blueprint(plan["id"], be))
    n = len(planner.get_plan(plan["id"])["blueprint"]["beats"])
    asyncio.run(planner.make_narration(plan["id"], be, None, None, None, False))
    assert be.count("p2_narrate") >= n                                          # the fake's long beats are retried, then the last attempt is accepted: no failure
    assert planner.get_plan(plan["id"])["segments"]
