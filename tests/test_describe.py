"""Literal descriptions: every slot of a character, place or object is filled with something drawable; gaps are reported."""
import asyncio
import json

from story import db
from story.llm import LLMResult
from story2 import api, describe, storyboard
from test_phase2b import P2BFake, approved_story, written_plan

FULL = {"gender": "man", "age": "34", "build": "tall and lean", "skin": "light olive", "face": "square jaw, a small scar on the left eyebrow",
        "hair": "short black hair, side parted", "eyes": "dark brown", "top": "white button-down shirt with rolled sleeves", "bottom": "charcoal grey trousers",
        "footwear": "black leather lace-up shoes", "accessories": "a steel wristwatch and a loosened navy tie", "expression": "tense, jaw set"}


def test_missing_reports_empty_and_vague_slots_only():
    assert describe.missing("person", FULL) == []
    gaps = describe.missing("person", {**FULL, "hair": "", "top": "business casual", "footwear": "various", "accessories": "none"})
    assert gaps == ["hair", "top", "footwear"]                                                  # "none" is a real answer for accessories
    assert "accessories" not in describe.missing("person", {**FULL, "accessories": "none"})
    assert describe.missing("prop", {"type": "monitor", "shape": "boxy", "material": "grey plastic", "colour": "beige", "condition": "worn", "markings": "none"}) == []
    assert set(describe.missing("place", {})) == {k for k, _ in describe.SLOTS["place"]}          # nothing given: everything is missing


def test_the_description_carries_every_slot_value():
    d = describe.describe("person", FULL)
    for v in FULL.values():
        assert v.lower() in d.lower(), v
    assert "34 years old" in d
    fixed = " ".join(describe.fixed_from("person", FULL)).lower()
    assert "charcoal grey trousers" in fixed and "black leather lace-up shoes" in fixed and "short black hair" in fixed
    assert "none" not in describe.describe("person", {**FULL, "accessories": "none"}).lower()


class SlotFake(P2BFake):
    async def complete(self, messages, max_tokens):
        if "[TASK:p2_registry]" in messages[0]["content"]:
            return LLMResult(json.dumps({"assets": [{"name": "the trader", "kind": "person", "appearance": FULL, "fictionalisation": "generic_reconstruction"},
                                                    {"name": "the office", "kind": "place", "appearance": {"type": "open-plan office", "architecture": "two rows of desks under a low white ceiling"}},
                                                    {"name": "stock chart", "kind": "prop", "appearance": {"type": "chart", "shape": "rectangular"}},
                                                    {"name": "earnings report", "kind": "prop", "appearance": {"type": "document"}},
                                                    {"name": "desk phone", "kind": "prop", "appearance": {"type": "desk phone", "colour": "black"}},
                                                    {"name": "the rumour", "kind": "prop", "literal": False, "appearance": {"type": "whisper", "shape": "none"}},
                                                    {"name": "style", "kind": "style", "description": "ignored"}]}))
        return await super().complete(messages, max_tokens)


def test_registry_builds_the_description_and_fixed_details_from_the_slots(env):
    pid, cid = approved_story(env)
    be = SlotFake()
    p = written_plan(cid, be)
    asyncio.run(storyboard.make_registry(p["id"], be))
    assets = {a["name"]: a for a in storyboard.get_assets(p["id"])}
    t = assets["the trader"]["data"]
    assert t["appearance"]["hair"] == FULL["hair"] and "charcoal grey trousers" in t["description"] and "scar on the left eyebrow" in t["description"]
    assert any("black leather lace-up shoes" in f for f in t["fixed"])
    assert assets["the office"]["data"]["description"].startswith("Open-plan office")
    assert "stock chart" not in assets and "earnings report" not in assets and "the rumour" not in assets and "desk phone" in assets               # charts and documents are not drawable objects


def test_the_plan_lists_which_slots_are_still_missing_and_filling_them_rebuilds_the_description(env):
    pid, cid = approved_story(env)
    be = SlotFake()
    p = written_plan(cid, be)
    asyncio.run(storyboard.make_registry(p["id"], be))
    got = asyncio.run(api.plan(p["id"]))
    gaps = {g["name"]: g for g in got["cast_gaps"]}
    assert "the trader" not in gaps and {"signature", "materials", "light", "objects", "size"} <= set(gaps["the office"]["missing"])
    office = next(a for a in storyboard.get_assets(p["id"]) if a["name"] == "the office")
    full = {"signature": "twelve desks in two rows, one monitor on each, a water cooler by the door", "materials": "grey carpet and white laminate desks", "light": "cold fluorescent ceiling light", "objects": "twelve desks, each with one monitor", "size": "large, half full"}
    out = asyncio.run(api.patch_asset(office["id"], {"appearance": full}))
    d = next(a for a in out["assets"] if a["name"] == "the office")["data"]["description"]
    assert "twelve desks" in d and "cold fluorescent" in d and "two rows of desks" in d.lower()
    assert "the office" not in {g["name"] for g in asyncio.run(api.plan(p["id"]))["cast_gaps"]}


def test_a_place_must_say_what_makes_it_recognisable():
    assert "signature" in describe.missing("place", {"type": "trading floor", "architecture": "open hall", "materials": "grey carpet", "light": "fluorescent", "objects": "20 desks", "size": "large"})
    ap = {"type": "stock brokerage trading floor", "signature": "rows of desks with four monitors each, desk phones, a wall of ticker screens", "architecture": "open-plan hall",
          "materials": "grey carpet and blue-grey partitions", "light": "fluorescent panels", "objects": "40 desks", "size": "large"}
    assert not describe.missing("place", ap)
    assert "recognisable by rows of desks with four monitors each" in describe.describe("place", ap).lower()
    assert any(x.startswith("signature: rows of desks") for x in describe.fixed_from("place", ap))
