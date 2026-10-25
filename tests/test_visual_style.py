"""Visual direction: illustrated story scenes in one chosen style, characters made before scenes, references first."""
import asyncio

import pytest

from story import db
from story2 import imgplan, planner, prompts as P, storyboard, styles
from story3 import refs
from test_phase2b import approved_story, boarded, written_plan, P2BFake
from test_phase3f import Gateway, fast, planned, run as run_refs  # noqa: F401 - fast is a fixture


def test_presets_are_complete_and_the_default_is_the_game_art_look():
    assert styles.DEFAULT == "filmic" and set(styles.PRESETS) == {"filmic", "gta", "noir", "concept"}
    for sid, p in styles.PRESETS.items():
        assert {"label", "description", "short", "look", "palette", "linework"} <= set(p) and "photograph" in p["look"]       # each says what it is not
    a = styles.style_asset_data({"visual_style": "noir"})
    assert a["kind"] == "style" and a["preset"] == "noir" and a["description"] == styles.PRESETS["noir"]["look"]
    assert styles.style_id({"visual_style": "nope"}) == "filmic" and styles.style_id(None) == "filmic"
    with pytest.raises(styles.StyleError):
        styles.get("nope")


def test_the_instructions_to_the_storyboard_model_ask_for_story_pictures_with_faces():
    assert "TELL THE STORY WITH PICTURES" in P.SCENES and "at most one scene in six" in P.SCENES and "runner, a train" in P.SCENES
    assert "composite characters" in P.REGISTRY and "never list a chart" in P.REGISTRY.lower() or "Never list a chart" in P.REGISTRY
    assert "anonymous figures" not in P.SCENES                                                    # the old direction is gone


def test_registry_writes_the_style_asset_from_the_preset_not_from_the_model(env):
    pid, cid, be, p = boarded(env)
    assets = storyboard.get_assets(p["id"])
    st = [a for a in assets if a["kind"] == "style"]
    assert len(st) == 1 and st[0]["data"]["description"] == styles.PRESETS["filmic"]["look"] and st[0]["data"]["preset"] == "filmic"
    s = planner.get_plan(p["id"])["settings"]
    assert s["registry_direction"] == styles.DIRECTION and s["storyboard_direction"] == styles.DIRECTION and s["storyboard_style"] == "filmic"


def test_every_prompt_leads_with_the_style_and_says_what_it_is_not(env):
    pid, cid, be, p = boarded(env)
    imgplan.compile_plan(p["id"])
    look = styles.PRESETS[styles.DEFAULT]["look"]
    for sc in storyboard.get_scenes(p["id"]):
        q, f = sc["data"]["prompts"]["qwen"], sc["data"]["prompts"]["flux"]
        assert ("Visual style: " + look[:60]) in q["prompt"] and look[:60] in f["prompt"]
        assert styles.NOT_PHOTO in f["prompt"]
        assert "photograph" in f["negative_prompt"] and "plain white background" in f["negative_prompt"] and not q["negative_prompt"]
        assert "anonymous figure" not in q["prompt"] and "anonymous figure" not in f["prompt"]
        assert q["params"]["style"] == styles.DEFAULT and q["params"]["lora"] == {}


def test_a_real_named_person_is_a_silhouette_but_an_invented_character_has_a_face(env):
    pid, cid, be, p = boarded(env)
    person = next(a for a in storyboard.get_assets(p["id"]) if a["kind"] == "person")
    sc = next(s for s in storyboard.get_scenes(p["id"]))
    d = sc["data"]
    d["continuity"]["assets"] = [person["id"]]
    db.ex("UPDATE scenes SET data=? WHERE id=?", (db.jdump(d), sc["id"]))
    for fic, want in (("generic_reconstruction", False), ("real_person_no_likeness", True)):
        data = {**person["data"], "fictionalisation": fic}
        db.ex("UPDATE assets SET data=? WHERE id=?", (db.jdump(data), person["id"]))
        imgplan.compile_plan(p["id"])
        prompt = storyboard.get_scene(sc["id"])["data"]["prompts"]["qwen"]["prompt"]
        assert ("silhouette" in prompt) is want and "anonymous figure" not in prompt


def test_choosing_another_style_rewrites_the_style_asset_recompiles_and_flags_old_work(env):
    pid, cid, be, p = boarded(env)
    imgplan.compile_plan(p["id"])
    from fastapi import HTTPException
    from story2 import api
    info = asyncio.run(api.plan(p["id"]))["style"]
    assert info["id"] == styles.DEFAULT and not info["registry_stale"] and not info["storyboard_stale"]
    assert [s["id"] for s in asyncio.run(api.visual_styles())["styles"]] == ["filmic", "gta", "noir", "concept"]
    with pytest.raises(HTTPException):
        asyncio.run(api.set_visual_style(p["id"], api.VisualStyle(style="nope")))
    got = asyncio.run(api.set_visual_style(p["id"], api.VisualStyle(style="noir")))
    assert got["style"]["id"] == "noir" and got["style"]["registry_stale"] and got["style"]["storyboard_stale"]       # made for the old look
    st = next(a for a in storyboard.get_assets(p["id"]) if a["kind"] == "style")
    assert st["data"]["preset"] == "noir"
    q = storyboard.get_scenes(p["id"])[0]["data"]["prompts"]["qwen"]["prompt"]
    assert "heavy black ink" in q and "Grand Theft Auto" not in q                                  # prompts follow at once


def test_storyboard_keeps_approved_scenes_unless_asked_to_replace_them(env):
    pid, cid, be, p = boarded(env)
    scenes = storyboard.get_scenes(p["id"])
    for sc in scenes:
        storyboard.edit_scene(sc["id"], {"status": "approved"})
    ids = {s["id"] for s in storyboard.get_scenes(p["id"])}
    asyncio.run(storyboard.make_storyboard(p["id"], be))
    assert {s["id"] for s in storyboard.get_scenes(p["id"])} == ids                                # approved scenes protected
    asyncio.run(storyboard.make_storyboard(p["id"], be, replace_approved=True))
    after = {s["id"] for s in storyboard.get_scenes(p["id"])}
    assert after and not (after & ids)                                                              # all replaced
    first = storyboard.get_scenes(p["id"])[0]
    storyboard.edit_scene(first["id"], {"locked": True})
    asyncio.run(storyboard.make_storyboard(p["id"], be, replace_approved=True))
    assert first["id"] in {s["id"] for s in storyboard.get_scenes(p["id"])}                         # locked scenes are always kept


def test_reference_pictures_can_be_made_before_any_scene_exists(env, monkeypatch, fast):
    pid, cid = approved_story(env)
    be = P2BFake()
    p = written_plan(cid, be)
    asyncio.run(storyboard.make_registry(p["id"], be))
    assert not storyboard.get_scenes(p["id"])
    t = refs.targets(p["id"])
    assert t and all(x["asset"]["kind"] in ("person", "place", "prop") for x in t)
    gw = Gateway()
    out = run_refs(p["id"], gw, monkeypatch, candidates=1)
    assert out["made"] == len(t)
    prompt = [r for r in gw.requests if r["url"].endswith("/images/generations")][0]["body"]["prompt"]
    assert prompt.startswith(styles.PRESETS[styles.DEFAULT]["look"][:60]) and "white background" in prompt or "Location design" in prompt


def test_a_style_lora_is_sent_to_the_model_when_one_is_configured(env, monkeypatch, fast):
    monkeypatch.setitem(styles.LORAS, styles.DEFAULT, {"qwen-image-2.1": {"comic-style": 0.8}})
    plan_id = planned(env)
    assert storyboard.get_scenes(plan_id)[0]["data"]["prompts"]["qwen"]["params"]["lora"] == {"comic-style": 0.8}
    gw = Gateway()
    run_refs(plan_id, gw, monkeypatch, candidates=1)
    assert [r for r in gw.requests if r["url"].endswith("/images/generations")][0]["body"]["lora"] == {"comic-style": 0.8}


def test_people_and_objects_are_drawn_as_white_background_sheets_with_several_poses(env):
    plan_id = __import__("test_phase3f").planned(env)
    style = refs.style_text(plan_id)
    for t in refs.targets(plan_id):
        a = t["asset"]
        b = refs.build_prompt(a, style, "qwen-image-2.1")
        if a["kind"] == "person":
            assert "pure white background" in b["prompt"] and "four times" in b["prompt"] and "three-quarter" in b["prompt"] and "seated" in b["prompt"]
        if a["kind"] == "prop":
            assert "pure white background" in b["prompt"] and "three times" in b["prompt"]
        assert (b["width"], b["height"]) == (1344, 768)
    from story3 import refscore
    assert "consistent_poses" in [k for k, _ in refscore.dims_for("person")] and "consistent_poses" not in [k for k, _ in refscore.dims_for("place")]


def test_the_registry_reads_the_whole_narration_and_the_editor_can_add_what_is_missing(env):
    from fastapi import HTTPException
    from story2 import api
    seen = {}

    class Spy(P2BFake):
        async def complete(self, messages, max_tokens):
            seen.setdefault("user", messages[-1]["content"])
            return await super().complete(messages, max_tokens)
    pid, cid = approved_story(env)
    be = Spy()
    p = written_plan(cid, be)
    seen.clear()
    asyncio.run(storyboard.make_registry(p["id"], be))
    assert "NARRATION" in seen["user"] and planner.get_plan(p["id"])["segments"][0]["plain"][:30] in seen["user"]
    n = len(storyboard.get_assets(p["id"]))
    out = asyncio.run(api.add_asset(p["id"], api.NewAsset(name="the manager", kind="person", description="a stern man in a grey suit")))
    assert len(out["assets"]) == n + 1 and next(a for a in out["assets"] if a["name"] == "the manager")["data"]["evidence_note"] == "added by the editor"
    with pytest.raises(HTTPException):
        asyncio.run(api.add_asset(p["id"], api.NewAsset(name="The Manager", kind="person")))
    with pytest.raises(HTTPException):
        asyncio.run(api.add_asset(p["id"], api.NewAsset(name="x", kind="style")))


def test_objects_and_places_are_drawn_without_the_clause_that_puts_faces_on_screens(env):
    plan_id = __import__("test_phase3f").planned(env)
    style = refs.style_text(plan_id)
    assert style.rstrip(". ") == styles.PRESETS[styles.DEFAULT]["look"].rstrip(". ")
    for t in refs.targets(plan_id):
        a = t["asset"]
        prompt = refs.build_prompt(a, style, "qwen-image-2.1")["prompt"]
        if a["kind"] in ("prop", "place"):
            assert "expressive faces" not in prompt and styles.PRESETS[styles.DEFAULT]["object_look"][:50] in prompt
        else:
            assert "natural faces" in prompt
    assert "Grand Theft Auto" not in styles.PRESETS[styles.DEFAULT]["look"] and "GTA" not in styles.PRESETS[styles.DEFAULT]["short"]       # a game's name prints as a logo
