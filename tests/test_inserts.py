"""Task 3.12: the region table and the world inserts."""
import asyncio

from story2 import events, inserts, planner, region, storyboard
from test_chain_v2 import ChainFake
from test_narration_v2 import ready


def boarded(env):
    pid, be = ready(env)
    asyncio.run(planner.make_narration(pid, be))
    cf = ChainFake()
    asyncio.run(events.make_events(pid, cf))
    asyncio.run(storyboard.make_registry(pid, cf))
    asyncio.run(storyboard.make_storyboard(pid, cf))
    return pid


def slow(pid, monkeypatch):
    """Make every sentence last a few seconds, so scenes are long enough to cut into."""
    p = planner.get_plan(pid)
    from story import db
    db.ex("UPDATE plans SET settings=? WHERE id=?", (db.jdump({**p["settings"], "wpm": 50}), pid))
    storyboard.retime(pid)
    for k, v in (("LEAD_IN_S", 0.0), ("TAIL_S", 0.0), ("MAX_INSERT_S", 100.0), ("MIN_HOST_S", 3.0)):
        monkeypatch.setattr(inserts, k, v)


def test_the_table_has_regions_with_cues_and_enough_cutaways_for_each():
    t = region.table()
    assert {"generic", "delhi", "punjab", "gujarat", "mumbai", "kolkata", "up_hindi_belt", "south", "rajasthan", "goa", "northeast_hills"} <= set(t)
    assert len(t["generic"]["inserts"]) >= 20
    for rid, r in t.items():
        assert r["cues"]["clothing"] and r["cues"]["street"] and r["inserts"]
        assert len({i["id"] for i in r["inserts"]}) == len(r["inserts"])
        for i in r["inserts"]:
            assert i["subject"] and i["action"] and i["location"]


def test_a_region_is_found_from_the_story_or_chosen_by_the_editor():
    plan = {"settings": {"audience": {"profile": "metro_hinglish", "region": "Punjab"}}, "blueprint": {"cold_open": "A man runs through Mumbai"}}
    assert region.detect(plan)[:2] == ["punjab", "mumbai"] and region.detect(plan)[-1] == "generic"
    plan = {"settings": {}, "blueprint": {"cold_open": "The Dharavi lanes, then Surat, then Dharavi again"}}
    assert region.detect(plan)[0] == "mumbai"
    assert region.detect({"settings": {}, "blueprint": {}}) == ["generic"] and region.note({"settings": {}, "blueprint": {}}) == ""
    n = region.note({"settings": {"audience": {"region": "Gujarat"}}, "blueprint": {}})
    assert "Gujarat" in n and "textile" in n


def test_inserts_are_cut_from_long_scenes_and_the_timeline_still_tiles_the_narration(env, monkeypatch):
    pid = boarded(env)
    slow(pid, monkeypatch)
    before = planner.get_plan(pid)
    n = inserts.add(pid, count=3)
    assert n == 3
    p = planner.get_plan(pid)
    ins = [s for s in p["scenes"] if inserts.is_insert(s)]
    assert len(ins) == 3 and all(s["s_from"] == s["s_to"] for s in ins)                         # one sentence each
    assert len({s["data"]["insert"]["id"] for s in ins}) == 3                                    # never the same cutaway twice
    for s in ins:
        host = next(x for x in p["scenes"] if x["id"] == s["data"]["insert"]["host"])
        assert host["s_to"] == s["s_from"] - 1 and s["data"]["event"].startswith("ins-")
    assert abs(sum(s["duration_s"] for s in p["scenes"]) - sum(s["duration_s"] for s in before["scenes"])) < 0.5      # no time gained or lost
    rep = storyboard.validate_storyboard(pid)
    assert not [i for i in rep["issues"] if i["kind"] == "coverage"]                              # every sentence still has exactly one scene


def test_a_second_run_replaces_the_inserts_and_remove_gives_the_sentences_back(env, monkeypatch):
    pid = boarded(env)
    slow(pid, monkeypatch)
    ranges = sorted((s["segment_id"], s["s_from"], s["s_to"]) for s in planner.get_plan(pid)["scenes"])
    inserts.add(pid, count=3)
    inserts.add(pid, count=2)
    assert len(inserts.existing(pid)) == 2
    assert inserts.remove(pid) == 2
    after = planner.get_plan(pid)["scenes"]
    assert not any(inserts.is_insert(s) for s in after)
    assert sorted((s["segment_id"], s["s_from"], s["s_to"]) for s in after) == ranges


def test_no_cutaway_over_a_death(env, monkeypatch):
    pid = boarded(env)
    slow(pid, monkeypatch)
    from story import db
    for seg in planner.get_plan(pid)["segments"]:
        sents = seg["sentences"]
        for s in sents:
            s["text"] = "उसकी मौत हो गई। " + s["text"]
        db.ex("UPDATE segments SET sentences=? WHERE id=?", (db.jdump(sents), seg["id"]))
    assert inserts.add(pid, count=3) == 0


def test_an_insert_gets_the_v2_picture_prompt_with_its_region_place(env, monkeypatch):
    from story2 import imgplan
    pid = boarded(env)
    slow(pid, monkeypatch)
    inserts.add(pid, count=2)
    imgplan.compile_plan(pid)
    p = planner.get_plan(pid)
    ins = next(s for s in p["scenes"] if inserts.is_insert(s))
    prompt = ins["data"]["prompts"]["qwen"]["prompt"]
    assert ins["data"]["subject"].split()[0].lower() in prompt.lower() and "must not" not in prompt.lower()


def test_invented_people_get_names_that_fit_the_cast_and_story_names_stay():
    from story2 import names
    assert not names.is_indian("Sam Eriksen") and names.is_indian("Gurpreet") and names.is_indian("राजू") and names.is_indian("Rahul Verma") and not names.is_indian("John")
    a = names.suggest(["punjab"], "man", set(), "Sam Eriksen")
    assert a in names.MALE["punjab"] + names.MALE["generic"] and a == names.suggest(["punjab"], "man", set(), "Sam Eriksen")      # the same seed gives the same name
    f = names.suggest(["gujarat"], "a woman in her thirties", set(), "x")
    assert f in names.FEMALE["gujarat"] + names.FEMALE["generic"]
    assert names.suggest(["punjab"], "man", set(names.MALE["punjab"] + names.MALE["generic"][:-1]), "z") == names.MALE["generic"][-1]       # never one already used while others are free


def test_the_registry_renames_an_invented_foreign_name_but_not_a_name_from_the_story(env):
    from story2 import events
    pid, be = ready(env)
    asyncio.run(planner.make_narration(pid, be))
    cf = ChainFake()
    asyncio.run(events.make_events(pid, cf))
    asyncio.run(storyboard.make_registry(pid, cf))
    p = planner.get_plan(pid)
    people = [a["name"] for a in p["assets"] if a["kind"] == "person"]
    assert people and not any(n.startswith("Person ") for n in people)               # "Person alpha" is not a believable name; every invented person got one
