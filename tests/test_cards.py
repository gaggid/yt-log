"""Tasks 3.15 and 3.9: the evidence-card library and the route map."""
import asyncio

from PIL import Image

from story import db
from story2 import events, planner, storyboard
from story3 import cards, graphics, store as mstore
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


def events_about(pid, words):
    """Rewrite the events so some of them are about the given things (a message thread, calls, a report...)."""
    p = planner.get_plan(pid)
    evs = events.of(p)
    for e, w in zip(evs[2:], words):
        e["key_object"], e["doing"] = w, f"someone looks at {w}"
        e["ledger_ids"] = e.get("ledger_ids") or ["m1", "m2"]
    db.ex("UPDATE plans SET settings=? WHERE id=?", (db.jdump({**p["settings"], "events": evs}), pid))


def test_the_event_decides_which_card():
    assert cards.pick_type({"key_object": "bank alert", "doing": "reads a debit alert"}) == "sms"
    assert cards.pick_type({"key_object": "", "doing": "scrolls the group chat"}) == "chat"
    assert cards.pick_type({"key_object": "newspaper", "doing": "reads the headline"}) == "news_clip"
    assert cards.pick_type({"kind": "map", "doing": "plans the route from Surat to Ludhiana"}) == "route_map"
    assert cards.pick_type({"kind": "place", "doing": "walks down the lane"}) == ""


def test_scenes_whose_event_is_a_message_a_report_or_a_route_become_card_scenes(env):
    pid = boarded(env)
    events_about(pid, ["the group chat", "an FIR copy", "a newspaper clipping", "the route from Surat to Ludhiana"])
    n = cards.plan(pid)
    assert 2 <= n <= cards.MAX_CARDS
    p = planner.get_plan(pid)
    cs = [s for s in p["scenes"] if s["data"].get("card")]
    assert len(cs) == n and all(s["data"]["visual_type"] in ("screen_interface", "document_archival", "map_timeline") for s in cs)
    assert cs[0]["id"] != sorted(p["scenes"], key=lambda s: s["start_s"])[0]["id"]                                # never the first scene of the film
    assert cards.undo(pid) == n and not [s for s in planner.get_plan(pid)["scenes"] if s["data"].get("card")]


def test_every_card_type_is_drawn_inside_the_frame_from_story_details_only(env):
    pid = boarded(env)
    p = planner.get_plan(pid)
    ctx = graphics.facts_ctx(p)
    scene = {"data": {"subject": "x", "card": {"type": "chat", "items": ["m1", "m2", "m3"]}}}
    for ct in cards.TYPES:
        scene["data"]["card"] = {"type": ct, "items": ["m1", "m2", "m3", "m4"], "event": "", "year": "1991"}
        sp = cards.spec(scene, p, ctx)
        assert sp["template"] == ct
        im = graphics.draw(sp, "filmic")
        assert isinstance(im, Image.Image) and im.size == graphics.SIZE
        assert graphics.animation(ct)


def test_brand_names_never_appear_on_a_card_and_numbers_come_only_from_the_details(env):
    pid = boarded(env)
    p = planner.get_plan(pid)
    from story2 import material
    pk = material.pack(p)
    pk["items"][0]["detail"] = "He sent 98765 rupees through WhatsApp and Paytm to the account"
    sc = {"data": {"subject": "x", "card": {"type": "sms", "items": [pk["items"][0]["id"]]}}}
    db.ex("UPDATE plans SET settings=? WHERE id=?", (db.jdump({**p["settings"], "material": pk}), pid))
    p2 = planner.get_plan(pid)
    sp = cards.spec(sc, p2, graphics.facts_ctx(p2))
    assert "whatsapp" not in sp["text"].lower() and "paytm" not in sp["text"].lower() and "98765" in sp["text"]          # a number of the details may be shown; a brand never
    assert graphics.numbers_on_card(sp) == ["98765"]
    sc["data"]["card"]["items"] = []                                                                                  # no item named: the card falls back to clue and number details of the pack
    assert cards.spec(sc, p2, graphics.facts_ctx(p2))["text"]


def test_the_route_map_names_only_cities_of_the_details_in_story_order(env):
    pid = boarded(env)
    p = planner.get_plan(pid)
    items = [{"where": "Surat", "detail": "He left Surat by train"}, {"where": "", "detail": "then reached Ludhiana, and later Dharavi in Mumbai"}]
    assert cards.stops(p, None, items) == ["surat", "ludhiana", "mumbai"]
    sp = {"stops": ["surat", "ludhiana", "mumbai"], "template": "route_map"}
    assert graphics.draw(sp, "noir").size == graphics.SIZE


def test_graphics_build_makes_the_card_images(env):
    pid = boarded(env)
    events_about(pid, ["the group chat", "an FIR copy", "the route from Surat to Ludhiana"])
    cards.plan(pid)
    out = graphics.build(pid)
    assert out["made"] >= 2
    metas = [i["meta"] for sc in graphics.graphic_scenes(pid) for i in mstore.items(pid, graphics.KIND, sc["id"]) if i["status"] == "done"]
    assert metas and all(m["template"] in cards.TYPES for m in metas) and all(m["animation"] for m in metas)


def test_motion_clips_go_to_the_hook_the_reveals_and_the_last_picture_within_the_budget(env):
    from story3 import clips
    pid = boarded(env)
    assert clips.choose_scenes(pid) == []                                                        # off unless the plan switched motion clips on
    clips.set_settings(pid, {"enabled": True})
    p = planner.get_plan(pid)
    evs = events.of(p)
    for e in evs[3:6]:
        e["reveal"] = True
    db.ex("UPDATE plans SET settings=? WHERE id=?", (db.jdump({**p["settings"], "events": evs}), pid))
    chosen = clips.choose_scenes(pid, budget=4)
    sc = sorted(planner.get_plan(pid)["scenes"], key=lambda s: (s["start_s"], s["seq"]))
    assert 2 <= len(chosen) <= 4 and chosen[0] == sc[0]["id"] and chosen[-1] == sc[-1]["id"]
    assert {s["id"] for s in sc if s["data"].get("motion_clip")} == set(chosen)
    assert clips.choose_scenes(pid, budget=2) == [sc[0]["id"], sc[-1]["id"]]
