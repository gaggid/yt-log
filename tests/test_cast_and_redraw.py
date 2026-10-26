"""Indian cast (on by default), edited reference prompts, and per-scene redraw with a chosen model, mode and prompt."""
import asyncio

import pytest

from story import db
from story2 import describe, imgplan, imgprompts, planner, providers, storyboard
from story3 import refs, scenes, store
from test_phase3f import Gateway, SETTINGS, planned, run as run_refs
from test_phase3g import fast, ready as scenes_ready  # noqa: F401


REFRESH = providers.refresh                                                            # the real one: conftest swaps it for a no-op in every test

PALE = {"gender": "man", "age": "45", "build": "heavy", "skin": "pale", "face": "round face", "hair": "blond, short", "eyes": "blue",
        "top": "white shirt", "bottom": "grey trousers", "footwear": "brown loafers", "accessories": "none", "expression": "tired"}


def test_indianise_sets_ethnicity_and_replaces_colouring_that_cannot_go_with_it():
    ap = describe.indianise(PALE)
    assert ap["ethnicity"] == "Indian" and ap["skin"] != "pale" and "blond" not in ap["hair"] and ap["eyes"] == "dark brown"
    assert describe.describe("person", ap).startswith("Indian man")
    keep = describe.indianise({**PALE, "ethnicity": "Gujarati", "skin": "wheatish", "hair": "black, short", "eyes": "dark brown"})
    assert keep["ethnicity"] == "Gujarati" and keep["skin"] == "wheatish"                       # what already fits is kept


def test_a_person_without_slots_gets_indian_in_front():
    assert describe.indian_prefix("Man, 45 years old, heavy build") == "Indian man, 45 years old, heavy build"
    assert describe.indian_prefix("A tall man in a grey suit") == "Indian person: A tall man in a grey suit"
    assert describe.indian_prefix("Indian woman, 30") == "Indian woman, 30"


def test_indian_cast_is_on_by_default_and_can_be_switched_off():
    assert describe.indian_on({}) and describe.indian_on(None) and not describe.indian_on({"cast_indian": False})
    assert describe.missing("person", {k: v for k, v in PALE.items()}) == []                    # ethnicity is never a gap


def test_ethnicity_is_never_reported_as_a_gap():
    assert "ethnicity" not in describe.missing("person", {})


def person_scene_prompt(plan_id, indian):
    plan = planner.get_plan(plan_id)
    plan["settings"]["cast_indian"] = indian
    assets = storyboard.get_assets(plan_id)
    person = next(a for a in assets if a["kind"] == "person")
    person["data"]["appearance"] = dict(PALE)
    person["data"]["description"] = describe.describe("person", PALE)
    person["data"]["fixed"] = describe.fixed_from("person", PALE)
    sc = storyboard.get_scenes(plan_id)[0]
    sc["data"]["continuity"]["assets"] = [person["id"]]
    sc["data"].setdefault("composition", {})["distance"] = "wide"
    return imgprompts.compile_scene(sc, assets, plan, {}), sc, assets


def test_scene_prompts_carry_the_cast_and_change_with_the_setting(env):
    plan_id = planned(env)
    (on, sc, assets), (off, _sc, _assets) = person_scene_prompt(plan_id, True), person_scene_prompt(plan_id, False)
    for ad in ("qwen", "flux"):
        assert "Indian man" in on[ad]["prompt"] and "blond" not in on[ad]["prompt"] and on[ad]["cast_indian"] is True
        assert "Indian" not in off[ad]["prompt"] and off[ad]["cast_indian"] is False
        assert on[ad]["source_hash"] != off[ad]["source_hash"]                                    # pictures made the other way are flagged old
    assert not [i for i in imgprompts.validate_prompt(on["qwen"], sc, assets, "", None) if i["kind"] == "continuity"]


def test_reference_prompt_and_hash_follow_the_cast(env):
    plan_id = planned(env)
    a = next(t["asset"] for t in refs.targets(plan_id) if t["asset"]["kind"] == "person")
    a["data"]["appearance"] = dict(PALE)
    a["data"]["description"] = describe.describe("person", PALE)
    style = refs.style_text(plan_id)
    assert "Indian man" in refs.build_prompt(a, style, "qwen-image-2.1", True)["prompt"]
    assert "Indian" not in refs.build_prompt(a, style, "qwen-image-2.1", False)["prompt"]
    assert refs.asset_hash(a, style, "qwen-image-2.1", True) != refs.asset_hash(a, style, "qwen-image-2.1", False)


def test_set_cast_recompiles_and_can_write_into_the_character_list(env):
    from story2 import api
    plan_id = planned(env)
    person = next(a for a in storyboard.get_assets(plan_id) if a["kind"] == "person")
    data = {**person["data"], "appearance": dict(PALE), "description": describe.describe("person", PALE)}
    db.ex("UPDATE assets SET data=? WHERE id=?", (db.jdump(data), person["id"]))
    imgplan.compile_plan(plan_id)
    out = asyncio.run(api.set_cast(plan_id, api.Cast(indian=True, write_into_list=True)))
    me = next(a for a in out["assets"] if a["id"] == person["id"])
    assert me["data"]["appearance"]["ethnicity"] == "Indian" and "blond" not in me["data"]["description"]
    out = asyncio.run(api.set_cast(plan_id, api.Cast(indian=False)))
    assert out["settings"]["cast_indian"] is False
    assert all(c["cast_indian"] is False for sc in out["scenes"] for c in (sc["data"].get("prompts") or {}).values())


# ── edited reference prompt ─────────────────────────────────────────────────

def test_a_person_written_reference_prompt_is_used_for_that_asset_only_and_kept_on_the_picture(env, monkeypatch, fast):
    plan_id = planned(env)
    ts = refs.targets(plan_id)
    first, other = ts[0]["asset"], ts[1]["asset"]
    gw = Gateway()
    run_refs(plan_id, gw, monkeypatch, asset_ids=[first["id"], other["id"]], candidates=1, only_missing=False, score=False,
             prompts={first["id"]: "A tall Indian shopkeeper, white background, four views."})
    sent = {r["body"]["prompt"] for r in gw.requests}
    assert "A tall Indian shopkeeper, white background, four views." in sent and len(sent) == 2
    mine = store.items(plan_id, "reference", first["id"])[-1]
    assert mine["meta"]["custom_prompt"] is True and mine["meta"]["prompt"].startswith("A tall Indian")
    st = refs.state(plan_id)
    row = next(r for r in st["assets"] if r["asset_id"] == first["id"])
    assert row["candidates"][-1]["custom"] and row["candidates"][-1]["current"]                  # a custom prompt does not make the picture "old"
    assert row["prompt"] != "A tall Indian shopkeeper, white background, four views."            # the built prompt is untouched
    assert planner.get_plan(plan_id)["assets"] and next(a for a in storyboard.get_assets(plan_id) if a["id"] == first["id"])["data"]["description"] == first["data"]["description"]


def test_a_custom_reference_prompt_still_goes_through_the_leak_gate(env, monkeypatch, fast):
    from story2 import leak
    plan_id = planned(env)
    a = refs.targets(plan_id)[0]["asset"]
    monkeypatch.setattr(refs.leak, "check_many", lambda items, prof: [{"text": "source wording"}])
    out = run_refs(plan_id, Gateway(), monkeypatch, asset_ids=[a["id"]], candidates=1, only_missing=False, score=False, prompts={a["id"]: "anything"})
    assert out["made"] == 0 and out["failed"] and "source wording" in out["failed"][0]["error"]


# ── scene redraw: model, mode and prompt chosen by a person ─────────────────

from test_phase3g import Gateway as SceneGateway, approve_all_references, restore_httpx  # noqa: E402,F401


def redraw(plan_id, gw, monkeypatch, scene_id, **kw):
    monkeypatch.setattr(scenes.httpx, "AsyncClient", gw.client())
    monkeypatch.setattr(scenes.refscore.httpx, "AsyncClient", gw.client())
    return asyncio.run(scenes.redraw(plan_id, scene_id, s=SETTINGS, key="k", **kw))


def first_scene(plan_id):
    return sorted(storyboard.get_scenes(plan_id), key=lambda x: (x["start_s"], x["seq"]))[0]


def test_redraw_uses_the_chosen_model_and_prompt_and_keeps_the_scene_untouched(env, monkeypatch, fast):
    plan_id = scenes_ready(env)
    sc = first_scene(plan_id)
    before = (sc["data"]["subject"], sc["data"]["prompts"]["qwen"]["prompt"], sc["data"]["prompts"]["flux"]["prompt"])
    gw = SceneGateway()
    out = redraw(plan_id, gw, monkeypatch, sc["id"], model="flux2-klein-9b", mode="generate", prompt="A shopkeeper at a brass till, wide shot.", negative_prompt="blur", score=False)
    assert out["made"] == 1
    body = gw.count("/images/generations")[0]["body"]
    assert body["model"] == "flux2-klein-9b" and body["prompt"] == "A shopkeeper at a brass till, wide shot." and body["negative_prompt"] == "blur"
    it = store.items(plan_id, scenes.KIND, sc["id"])[-1]
    assert it["meta"]["custom_prompt"] and it["meta"]["model"] == "flux2-klein-9b" and it["meta"]["redraw"]
    after = storyboard.get_scene(sc["id"])
    assert (after["data"]["subject"], after["data"]["prompts"]["qwen"]["prompt"], after["data"]["prompts"]["flux"]["prompt"]) == before     # wording and compiled prompts never move
    row = next(r for r in scenes.state(plan_id)["scenes"] if r["id"] == sc["id"])
    assert row["candidates"][-1]["custom"] and row["candidates"][-1]["current"] and row["candidates"][-1]["prompt"].startswith("A shopkeeper")


def test_redraw_without_a_prompt_sends_that_models_compiled_prompt(env, monkeypatch, fast):
    plan_id = scenes_ready(env)
    sc = first_scene(plan_id)
    gw = SceneGateway()
    redraw(plan_id, gw, monkeypatch, sc["id"], model="qwen-image-2.1", mode="generate", score=False, candidates=2)
    sent = [r["body"]["prompt"] for r in gw.count("/images/generations")]
    assert sent == [sc["data"]["prompts"]["qwen"]["prompt"]] * 2
    assert not store.items(plan_id, scenes.KIND, sc["id"])[-1]["meta"]["custom_prompt"]


def test_redraw_from_reference_sheets_is_refused_when_there_are_none_or_the_model_cannot_edit(env, monkeypatch, fast):
    plan_id = scenes_ready(env)
    sc = first_scene(plan_id)
    with pytest.raises(scenes.MediaError, match="no approved reference sheet"):
        redraw(plan_id, SceneGateway(), monkeypatch, sc["id"], model="qwen-image-2.1", mode="edit")
    providers.PROVIDERS["plain-only"] = providers._discovered("plain-only", ["images.generations"])
    with pytest.raises(scenes.MediaError, match="cannot use reference pictures"):
        redraw(plan_id, SceneGateway(), monkeypatch, sc["id"], model="plain-only", mode="edit")
    assert not store.items(plan_id, scenes.KIND)                                                # nothing half-made


def test_redraw_from_reference_sheets_sends_them_and_remembers_the_choice(env, monkeypatch, fast):
    plan_id = scenes_ready(env, with_refs=True)
    sc = next(s for s in sorted(storyboard.get_scenes(plan_id), key=lambda x: x["start_s"]) if scenes.reference_files(scenes.compiled(s, "qwen-image-2.1")))
    gw = SceneGateway()
    redraw(plan_id, gw, monkeypatch, sc["id"], model="qwen-image-2.1", mode="edit", remember=True, score=False)
    assert gw.count("/images/edits") and not gw.count("/images/generations")
    plan = planner.get_plan(plan_id)
    assert scenes.settings(plan)["per_scene"][sc["id"]] == {"model": "qwen-image-2.1", "mode": "edit"}
    assert scenes.mode_for(sc, plan) == "edit" and scenes.mode_for(first_other(plan_id, sc), plan) == "generate"
    row = next(r for r in scenes.state(plan_id)["scenes"] if r["id"] == sc["id"])
    assert row["mode"] == "edit" and row["chosen_here"] and row["can_edit"]


def first_other(plan_id, sc):
    return next(s for s in storyboard.get_scenes(plan_id) if s["id"] != sc["id"])


def test_the_options_list_every_model_with_its_own_prompt(env):
    plan_id = scenes_ready(env)
    providers.PROVIDERS["z-image-turbo"] = providers._discovered("z-image-turbo", ["images.generations"])
    sc = first_scene(plan_id)
    o = scenes.options(plan_id, sc["id"])
    assert set(o["models"]) == {"qwen-image-2.1", "flux2-klein-9b", "z-image-turbo"} and o["default_model"] == "qwen-image-2.1" and o["model"] == "qwen-image-2.1"
    assert o["models"]["flux2-klein-9b"]["negative_used"] and not o["models"]["qwen-image-2.1"]["negative_used"]
    assert not o["models"]["z-image-turbo"]["can_edit"] and o["models"]["qwen-image-2.1"]["prompt"] == sc["data"]["prompts"]["qwen"]["prompt"]


def test_a_redraw_prompt_goes_through_the_leak_gate(env, monkeypatch, fast):
    plan_id = scenes_ready(env)
    monkeypatch.setattr(scenes.leak, "check_many", lambda items, prof: [{"text": "source wording"}])
    with pytest.raises(scenes.MediaError, match="source wording"):
        redraw(plan_id, SceneGateway(), monkeypatch, first_scene(plan_id)["id"], model="qwen-image-2.1", prompt="anything")


# ── every image model the gateway lists is a choice ─────────────────────────

def test_listed_image_models_that_can_use_references_are_added_and_qwen_stays_the_default():
    listing = [{"id": "qwen-image-2.1", "capabilities": ["images.generations", "images.edits"]}, {"id": "z-image-turbo", "type": "image", "capabilities": ["images.generations"]},
               {"id": "wan-2.2-ti2v-5b", "capabilities": ["video.generations"]}, {"id": "kokoro", "capabilities": ["audio.speech"]},
               {"id": "new-edit-model", "capabilities": ["images.generations", "images.edits"]}]
    added = providers.register_listing(listing)
    assert added == ["new-edit-model"] and "z-image-turbo" not in providers.PROVIDERS                  # turbo models cannot take reference pictures: no use here
    assert providers.DEFAULT_MODEL == "qwen-image-2.1"
    n = providers.get("new-edit-model")
    assert n["edits"] and n["max_references"] == 3 and n["discovered"]
    assert providers.get("qwen-image-2.1").get("discovered") is None                           # audited entries are never overwritten
    assert providers.settings_for({})["default"] == "qwen-image-2.1"
    assert providers.register_listing(listing) == []


def test_a_discovered_model_can_draw_a_scene(env, monkeypatch, fast):
    plan_id = scenes_ready(env)
    providers.PROVIDERS["z-image-turbo"] = providers._discovered("z-image-turbo", ["images.generations"])
    gw = SceneGateway()
    out = redraw(plan_id, gw, monkeypatch, first_scene(plan_id)["id"], model="z-image-turbo", mode="generate", score=False)
    assert out["made"] == 1 and gw.count("/images/generations")[0]["body"]["model"] == "z-image-turbo"
    assert "negative_prompt" not in gw.count("/images/generations")[0]["body"]


def test_refresh_never_raises_when_the_gateway_is_down(monkeypatch):
    import httpx
    monkeypatch.setattr(providers.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down")))
    providers._listing["at"] = 0.0
    assert REFRESH({"base_url": "http://gw/v1"}, "k") == []


# ── redo pictures after the video exists ────────────────────────────────────

from story3 import video  # noqa: E402
import test_phase3i as t3i  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not video.available()["ffmpeg"], reason="ffmpeg is not installed here")


@pytest.fixture
def tiny_profile(monkeypatch):
    monkeypatch.setitem(video.PROFILES, "tiny", t3i.TINY)


@needs_ffmpeg
def test_a_redone_picture_is_listed_as_a_change_and_only_its_clip_is_rendered_again(env, monkeypatch, fast, tiny_profile):
    plan_id = t3i.ready(env, monkeypatch)
    first = video.build(plan_id, "tiny")
    assert first["item"]["meta"]["used"] and not video.state(plan_id)["changes"]["changed"]
    work = store.media_dir(plan_id, "video") / "work" / "clips-tiny"
    before = {c.name for c in work.glob("*.mp4")}
    sc = first_scene(plan_id)
    out = redraw(plan_id, SceneGateway(), monkeypatch, sc["id"], model="flux2-klein-9b", mode="generate", prompt="A different picture of the same moment.", score=False)
    assert not video.state(plan_id)["changes"]["changed"]                                        # a new picture changes nothing until it is approved
    scenes.approve(out["items"][0])
    st = video.state(plan_id)
    ch = st["changes"]
    assert [c["scene"] for c in ch["changed"]] == [sc["id"]] and ch["changed"][0]["old_url"] and ch["changed"][0]["new_url"] != ch["changed"][0]["old_url"]
    assert ch["changed"][0]["approved"] and st["videos"][-1]["current"] is False              # the video no longer matches: it should be rebuilt
    second = video.build(plan_id, "tiny")
    assert second["item"]["attempt"] == 2 and store.path_of(first["item"]).is_file()              # the earlier video is kept
    after = {c.name for c in work.glob("*.mp4")}
    assert len(after - before) == 1                                                               # one new clip; every other clip was reused
    assert not video.state(plan_id)["changes"]["changed"]


def test_an_approved_picture_older_than_a_changed_reference_stays_in_the_video_and_is_listed(env, monkeypatch, fast):
    plan_id = scenes_ready(env)
    t3i.make_voice(plan_id)
    monkeypatch.setattr(scenes.httpx, "AsyncClient", SceneGateway().client())
    monkeypatch.setattr(scenes.refscore.httpx, "AsyncClient", SceneGateway().client())
    asyncio.run(scenes.generate(plan_id, s=SETTINGS, key="k", score=False))
    for r in scenes.state(plan_id)["scenes"]:
        scenes.approve(r["candidates"][0]["id"])
    assert not video.checklist(plan_id)["blockers"]
    sc = first_scene(plan_id)
    d = sc["data"]
    d["subject"] = d["subject"] + " at dawn"                                                      # the scene changes: its prompt and source hash move on
    db.ex("UPDATE scenes SET data=? WHERE id=?", (db.jdump(d), sc["id"]))
    imgplan.compile_plan(plan_id)
    chk = video.checklist(plan_id)
    assert not chk["blockers"], chk["blockers"]                                                    # redoing something never stops the video
    v = chk["visuals"][sc["id"]]
    assert v["stale"] and v["path"] and "redraw this scene" in v["problem"]
    assert [c["scene"] for c in video.changes_since(plan_id, chk, None)["stale"]] == [sc["id"]]
    redraw(plan_id, SceneGateway(), monkeypatch, sc["id"], model="qwen-image-2.1", mode="generate", score=False)
    v2 = video.checklist(plan_id)["visuals"][sc["id"]]
    assert not v2.get("stale") and v2["problem"] == "picture not approved" and v2["item"] != v["item"]      # the new picture takes over until it is approved
