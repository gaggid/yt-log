"""Things: finds, makes, gives, takes, uses, recipes, skills, carrying limits, binding, undo (docs/PLAN_discoveries.md). State-level tests use hand-built trackers; the engine and API tests use the scripted model."""
import copy

import pytest

from sim import dice, models as m, state as S, things
from test_sim_api import client, new_story, wait  # noqa: F401

PEOPLE = ["Ravi", "Meera", "Dev"]
PLACES = ["Aisle One", "Aisle Two", "Pharmacy"]
EXISTS = "Aisle One food: canned beans, bottled water. Aisle Two hardware: crowbar, rope, duct tape. Pharmacy: bandages."

TRACKERS = [
    {"id": "tk-items", "kind": "items", "name": "Supplies", "start": {
        "Crowbar": things.new_thing(1, "Ravi", "", {"size": 2}, {"how": "start"}),
        "Rope": things.new_thing(2, "Ravi", "", {}, {"how": "start"}),
        "Duct tape": things.new_thing(1, "Aisle Two", "", {}, {"how": "start"}),
        "Keys": things.new_thing(1, "Dev", "", {}, {"how": "start"}, bound_to="Dev"),
        "Bell": things.new_thing(1, "Ravi", "", {"uses": 2}, {"how": "start"})}},
    {"id": "tk-loc", "kind": "location", "name": "Where", "start": {"at": {"Ravi": "Aisle One", "Meera": "Aisle One", "Dev": "Pharmacy"}, "locked": []}},
    {"id": "tk-rel", "kind": "relation", "name": "Ravi and Meera", "a": "Ravi", "b": "Meera", "start": {"trust": 1, "tension": 0}},
    {"id": "tk-know", "kind": "knowledge", "name": "Secrets", "start": {"The code": []}},
    {"id": "tk-m", "kind": "meter", "name": "Morale", "min": 0, "max": 10, "start": 6, "owner": "group"},
]
ENTS = [{"kind": "character", "name": n, "skills": s} for n, s in (("Ravi", ["locks"]), ("Meera", ["first aid"]), ("Dev", []))] + [{"kind": "place", "name": p} for p in PLACES]


def fresh():
    return S.initial_state(copy.deepcopy(TRACKERS), copy.deepcopy(ENTS), {"start_time": "Day 1"})


def roll(kind, who, tier, n=1, **kw):
    return {"n": n, "who": who, "act": kw.pop("act", f"{who} tries"), "kind": kind, "tier": tier, "makes": kw.pop("makes", ""), **kw}


def run(st, ops, rolls=(), fired=(), dice_on=True, carry_default=0, carry=None, trackers=None, chapter=2):
    ctx = S.Ctx(trackers or copy.deepcopy(TRACKERS), PEOPLE, PLACES, EXISTS, True, {}, rolls=list(rolls), fired=list(fired), dice_on=dice_on, carry=carry or {}, carry_default=carry_default, chapter=chapter)
    return S.apply_ops(st, [m.Op(**o) if isinstance(o, dict) else o for o in ops], ctx)


def inv(st):
    return st["trackers"]["tk-items"]


def why(dropped):
    return " | ".join(d["why"] for d in dropped)


# ── finding ───────────────────────────────────────────────────────────────────

def test_a_find_needs_a_search_roll_an_instruction_or_the_world():
    op = {"op": "discover", "kind": "item", "target": "Flare gun", "where": "Aisle One", "who": "Ravi", "text": "in a locker"}
    st, ap, dr = run(fresh(), [op])
    assert "Flare gun" not in inv(st) and "nothing earned it" in why(dr)
    st, ap, dr = run(fresh(), [op], rolls=[roll("search", "Ravi", "success")])
    assert inv(st)["Flare gun"]["at"] == "Ravi" and inv(st)["Flare gun"]["origin"]["how"] == "found" and inv(st)["Flare gun"]["origin"]["chapter"] == 2
    assert st["world_add"][0]["name"] == "Flare gun" and ap[0]["undo"]
    st, ap, dr = run(fresh(), [op], rolls=[roll("search", "Ravi", "partial")])
    assert things.props(inv(st)["Flare gun"])["condition"] == "damaged"                  # found at a price
    st, ap, dr = run(fresh(), [op], rolls=[roll("search", "Ravi", "fail")])
    assert "Flare gun" not in inv(st) and "search failed" in why(dr)
    st, ap, dr = run(fresh(), [op], fired=["A flare gun turns up in the locker"])
    assert "Flare gun" in inv(st)                                                          # an instruction can hand it over


def test_things_the_world_text_names_need_no_roll_and_finds_are_capped():
    st, ap, dr = run(fresh(), [{"op": "discover", "kind": "item", "target": "Bandages", "where": "Pharmacy", "who": "Meera"}])
    assert inv(st)["Bandages"]["at"] == "Meera"
    rolls = [roll("search", "Ravi", "success", n=i) for i in (1, 2, 3)]
    ops = [{"op": "discover", "kind": "item", "target": t, "where": "Aisle One", "who": "Ravi"} for t in ("Flare gun", "Torch", "Lighter")]
    st, ap, dr = run(fresh(), ops, rolls=rolls)
    assert sum(1 for t in ("Flare gun", "Torch", "Lighter") if t in inv(st)) == 2 and "at most 2 finds" in why(dr)


def test_a_found_thing_is_known_only_on_the_line_that_found_it():
    a, _, _ = run(fresh(), [{"op": "discover", "kind": "item", "target": "Flare gun", "where": "Aisle One", "who": "Ravi"}], rolls=[roll("search", "Ravi", "success")])
    b = fresh()
    # later chapter on line A may add more of it; line B (which never found it) may not
    a2, ap, dr = run(a, [{"op": "item_add", "target": "Flare gun", "qty": 1, "to": "Meera", "source": "Aisle One"}], chapter=3)
    assert not dr
    b2, ap, dr = run(b, [{"op": "item_add", "target": "Flare gun", "qty": 1, "to": "Meera", "source": "Aisle One"}], chapter=3)
    assert dr and "Flare gun" not in inv(b2)


def test_places_clues_and_recipes_can_be_found():
    r = [roll("search", "Ravi", "success", n=1), roll("search", "Ravi", "success", n=2)]
    st, ap, dr = run(fresh(), [{"op": "discover", "kind": "place", "target": "Cellar", "where": "Aisle Two", "who": "Ravi", "text": "a door behind the shelves"},
                               {"op": "discover", "kind": "clue", "target": "Torn note", "who": "Ravi", "text": "it names the code", "tracker": "Secrets", "value": "The code"}], rolls=r)
    assert [w["kind"] for w in st["world_add"]] == ["place", "clue"] and "Ravi" in st["trackers"]["tk-know"]["The code"]
    st2, ap, dr = run(st, [{"op": "move", "target": "Ravi", "to": "Cellar"}])                    # a found place can be gone to
    assert st2["trackers"]["tk-loc"]["at"]["Ravi"] == "Cellar"
    st3, ap, dr = run(fresh(), [{"op": "discover", "kind": "recipe", "target": "Alarm rig", "who": "Ravi", "parts": ["Bell", "Rope"], "tools": ["Crowbar"]}], rolls=[roll("learn", "Ravi", "great")])
    assert st3["recipes"]["Alarm rig"]["needs"] == ["Bell", "Rope"] and st3["recipes"]["Alarm rig"]["learned_by"] == ["Ravi"]


# ── making ────────────────────────────────────────────────────────────────────

CRAFT = {"op": "craft", "who": "Ravi", "target": "Alarm rig", "qty": 1, "parts": ["Bell", "Rope"], "tools": ["Crowbar"], "skill": "tinkering", "props": {"uses": 3}}


def test_a_make_uses_up_parts_keeps_tools_and_remembers_the_recipe():
    st, ap, dr = run(fresh(), [CRAFT], rolls=[roll("make", "Ravi", "success", makes="Alarm rig")])
    assert not dr and inv(st)["Alarm rig"]["at"] == "Ravi" and things.props(inv(st)["Alarm rig"])["uses"] == 3 and inv(st)["Alarm rig"]["origin"]["how"] == "made"
    assert "Bell" not in inv(st) and inv(st)["Rope"]["qty"] == 1 and "Crowbar" in inv(st)
    assert st["recipes"]["Alarm rig"]["needs"] == ["Bell", "Rope"] and st["recipes"]["Alarm rig"]["learned_by"] == ["Ravi"]


@pytest.mark.parametrize("tier,cond", [("partial", "crude"), ("great", "well made")])
def test_make_quality_follows_the_tier(tier, cond):
    st, ap, dr = run(fresh(), [CRAFT], rolls=[roll("make", "Ravi", tier)])
    p = things.props(inv(st)["Alarm rig"])
    assert p["condition"] == cond and (p["uses"] == 1 if tier == "partial" else p["uses"] == 4)


def test_a_failed_make_loses_half_the_parts_and_a_disaster_all_of_them():
    st, ap, dr = run(fresh(), [CRAFT], rolls=[roll("make", "Ravi", "fail")])
    assert "Alarm rig" not in inv(st) and "failed to make" in ap[0]["text"]
    assert "Bell" not in inv(st) and inv(st)["Rope"]["qty"] == 2 and "Crowbar" in inv(st)        # two parts: half, rounded up, is one
    st, ap, dr = run(fresh(), [CRAFT], rolls=[roll("make", "Ravi", "disaster")])
    assert "Bell" not in inv(st) and inv(st)["Rope"]["qty"] == 1 and "Crowbar" in inv(st)        # every part used once is gone, the tool stays


def test_a_make_is_refused_without_parts_tools_a_roll_or_room():
    r = [roll("make", "Ravi", "success")]
    st, ap, dr = run(fresh(), [{**CRAFT, "parts": ["Bell", "Wire"]}], rolls=r)
    assert "no Wire" in why(dr)
    st, ap, dr = run(fresh(), [{**CRAFT, "tools": ["Hammer"]}], rolls=r)
    assert "tool Hammer" in why(dr)
    st, ap, dr = run(fresh(), [CRAFT], rolls=[])
    assert "no act of making was rolled" in why(dr)
    st, ap, dr = run(fresh(), [CRAFT], rolls=[roll("make", "Meera", "success")])           # somebody else's act is not Ravi's
    assert "no act of making" in why(dr)
    st, ap, dr = run(fresh(), [{**CRAFT, "props": {"size": 9}}], rolls=r, carry={"Ravi": 6})
    assert "cannot carry more" in why(dr)
    st, ap, dr = run(fresh(), [{**CRAFT, "parts": ["Bell"]}, {**CRAFT, "target": "Second", "parts": ["Rope"]}, {**CRAFT, "target": "Third", "parts": ["Rope"]}], rolls=[roll("make", "Ravi", "success", n=i) for i in (1, 2, 3)])
    assert "at most 2 makes" in why(dr)
    st, ap, dr = run(fresh(), [CRAFT], rolls=[], dice_on=False)
    assert "Alarm rig" in inv(st)                                                           # dice off: the make just works


def test_a_tool_must_be_here_and_not_broken():
    st = fresh()
    inv(st)["Crowbar"]["props"]["condition"] = "broken"
    st2, ap, dr = run(st, [CRAFT], rolls=[roll("make", "Ravi", "success")])
    assert "broken" in why(dr)
    st = fresh()
    inv(st)["Crowbar"]["at"] = "Pharmacy"                                                  # lying elsewhere
    st2, ap, dr = run(st, [CRAFT], rolls=[roll("make", "Ravi", "success")])
    assert "not here" in why(dr)
    inv(st)["Crowbar"]["at"] = "Aisle One"                                                 # lying where Ravi is: fine
    st2, ap, dr = run(st, [CRAFT], rolls=[roll("make", "Ravi", "success")])
    assert not dr


# ── dice ──────────────────────────────────────────────────────────────────────

def test_dice_use_skill_tools_known_recipes_and_relations():
    base = {"who": "Ravi", "act": "rig an alarm", "kind": "make", "difficulty": "normal", "craft": {"makes": "Alarm rig", "skill": "tinkering", "tools": ["Crowbar"]}}
    st = fresh()
    r0 = dice.roll(base, st, TRACKERS, 7, 1, 1, "fair")
    assert r0["improvised"] and r0["target"] == 14 and r0["mod"] == 1 and r0["kind"] == "make" and r0["makes"] == "Alarm rig"        # unskilled: target +2, right tool +1
    st["entities"]["Ravi"]["skills"] = ["tinkering"]
    r1 = dice.roll(base, st, TRACKERS, 7, 1, 1, "fair")
    assert not r1["improvised"] and r1["target"] == 12 and r1["mod"] == 3
    st["recipes"]["Alarm rig"] = {"makes": "Alarm rig"}
    r2 = dice.roll(base, st, TRACKERS, 7, 1, 1, "fair")
    assert r2["target"] == 8                                                                # a known recipe is one step easier
    st["trackers"]["tk-rel"] = {"trust": -2, "tension": 3}
    pr = {"who": "Ravi", "act": "ask for the rope", "kind": "persuade", "target": "Meera", "difficulty": "normal"}
    assert dice.roll(pr, st, TRACKERS, 7, 1, 1, "fair")["mod"] < 0
    assert dice.free(base, 1)["tier"] == "success" and dice.free(base, 1)["kind"] == "make"


# ── giving, taking, binding, carrying ─────────────────────────────────────────

def test_give_works_between_people_in_the_same_place():
    st, ap, dr = run(fresh(), [{"op": "item_give", "who": "Ravi", "target": "Crowbar", "to": "Meera"}])
    assert not dr and inv(st)["Crowbar"]["at"] == "Meera"
    st, ap, dr = run(fresh(), [{"op": "item_give", "who": "Ravi", "target": "Rope", "to": "Meera", "qty": 1}])
    assert inv(st)["Rope"]["at"] == "Ravi" and inv(st)["Rope"]["qty"] == 1 and inv(st)["Rope (Meera)"]["at"] == "Meera"        # a part of a stack goes
    st, ap, dr = run(fresh(), [{"op": "item_give", "who": "Ravi", "target": "Crowbar", "to": "Dev"}])
    assert "not in the same place" in why(dr)
    st, ap, dr = run(fresh(), [{"op": "item_give", "who": "Meera", "target": "Crowbar", "to": "Ravi"}])
    assert "does not hold" in why(dr)


def test_a_bound_thing_stays_with_its_person_unless_an_instruction_lifts_it():
    for op in ({"op": "item_give", "who": "Dev", "target": "Keys", "to": "Ravi"}, {"op": "item_move", "target": "Keys", "to": "Aisle One"}):
        st, ap, dr = run(fresh(), [{**op}])
        assert "bound to Dev" in why(dr) and inv(st)["Keys"]["at"] == "Dev"
    st, ap, dr = run(fresh(), [{"op": "item_take", "who": "Ravi", "source": "Dev", "target": "Keys"}], rolls=[roll("take", "Ravi", "success")])
    assert "bound to Dev" in why(dr)
    st, ap, dr = run(fresh(), [{"op": "item_change", "target": "Keys", "kind": "forced", "props": {"bound_to": ""}}])
    assert inv(st)["Keys"]["bound_to"] == ""
    st, ap, dr = run(st, [{"op": "item_move", "target": "Keys", "to": "Pharmacy"}])
    assert not dr


def test_the_carrying_limit_blocks_taking_more():
    st, ap, dr = run(fresh(), [{"op": "item_give", "who": "Ravi", "target": "Crowbar", "to": "Meera"}], carry={"Meera": 1})
    assert "Meera cannot carry more" in why(dr)
    st, ap, dr = run(fresh(), [{"op": "item_add", "target": "Canned beans", "qty": 9, "to": "Meera", "source": "Aisle One"}], carry_default=8)
    assert "cannot carry more" in why(dr)
    st, ap, dr = run(fresh(), [{"op": "item_move", "target": "Duct tape", "to": "Ravi"}], carry={"Ravi": 4})
    assert "cannot carry more" in why(dr)
    assert things.carried(fresh(), S.Ctx(TRACKERS, PEOPLE, PLACES), "Ravi") == 5               # crowbar size 2, two ropes, a bell


def test_a_give_the_receiver_may_refuse_needs_a_persuading_act():
    st = fresh()
    st["trackers"]["tk-rel"] = {"trust": -1, "tension": 0}
    op = {"op": "item_give", "who": "Ravi", "target": "Crowbar", "to": "Meera"}
    s1, ap, dr = run(st, [op])
    assert "would refuse" in why(dr)
    s1, ap, dr = run(st, [op], rolls=[roll("persuade", "Ravi", "fail")])
    assert "would refuse" in why(dr)
    s1, ap, dr = run(st, [op], rolls=[roll("persuade", "Ravi", "success")])
    assert not dr and inv(s1)["Crowbar"]["at"] == "Meera"
    s1, ap, dr = run(st, [op], dice_on=False)
    assert not dr


def test_taking_needs_a_roll_and_costs_the_relation():
    op = {"op": "item_take", "who": "Meera", "source": "Ravi", "target": "Rope"}
    st, ap, dr = run(fresh(), [op])
    assert "no act of taking" in why(dr)
    st, ap, dr = run(fresh(), [op], rolls=[roll("take", "Meera", "fail")])
    assert "failed to take" in why(dr) and st["trackers"]["tk-rel"]["tension"] == 1 and inv(st)["Rope"]["at"] == "Ravi"
    st, ap, dr = run(fresh(), [op], rolls=[roll("take", "Meera", "success")])
    assert inv(st)["Rope"]["at"] == "Meera" and st["trackers"]["tk-rel"]["tension"] == 1 and inv(st)["Rope"]["origin"]["how"] == "taken"


# ── using, changing, learning ─────────────────────────────────────────────────

def test_use_wears_a_thing_out_and_a_broken_thing_cannot_be_used():
    st = fresh()
    for left in (1, 0):
        st, ap, dr = run(st, [{"op": "item_use", "who": "Ravi", "target": "Bell"}])
        assert not dr and things.props(inv(st)["Bell"])["uses"] == left
    assert things.props(inv(st)["Bell"])["condition"] == "broken"
    st, ap, dr = run(st, [{"op": "item_use", "who": "Ravi", "target": "Bell"}])
    assert "broken or spent" in why(dr)
    st, ap, dr = run(st, [{"op": "item_use", "who": "Meera", "target": "Crowbar"}])
    assert "does not have" in why(dr)
    st, ap, dr = run(st, [{"op": "item_change", "target": "Bell", "value": "worn", "props": {"uses": 2}, "text": "mended"}])
    assert things.props(inv(st)["Bell"])["condition"] == "worn" and things.props(inv(st)["Bell"])["uses"] == 2 and inv(st)["Bell"]["note"] == "mended"


def test_skills_are_learned_only_when_something_taught_them():
    op = {"op": "skill_learn", "who": "Meera", "target": "lock picking"}
    st, ap, dr = run(fresh(), [op])
    assert "nothing taught it" in why(dr)
    st, ap, dr = run(fresh(), [op], rolls=[roll("learn", "Meera", "success")])
    assert "lock picking" in st["entities"]["Meera"]["skills"]
    st, ap, dr = run(fresh(), [op], fired=["Dev teaches Meera to pick locks"])
    assert "lock picking" in st["entities"]["Meera"]["skills"]
    st, ap, dr = run(st, [op], fired=["x"])
    assert "already has" in why(dr)
    st, ap, dr = run(fresh(), [op, {**op, "target": "bartending"}], fired=["x"])
    assert "at most 1 new skill" in why(dr)


def test_the_dead_do_nothing_with_things():
    st = fresh()
    st["entities"]["Ravi"]["alive"] = False
    st, ap, dr = run(st, [{"op": "item_use", "who": "Ravi", "target": "Bell"}])
    assert "dead" in why(dr)


# ── what the model sees ───────────────────────────────────────────────────────

def test_the_state_text_groups_things_by_holder_with_carrying_space_and_skills():
    st = fresh()
    st["recipes"]["Alarm rig"] = {"makes": "Alarm rig", "needs": ["Bell"], "tools": [], "skill": "tinkering", "learned_by": ["Ravi"], "chapter": 1}
    st["world_add"].append({"kind": "item", "name": "Flare gun", "text": "in a locker", "where": "Aisle One", "chapter": 2, "by": "Ravi"})
    txt = S.describe(st, TRACKERS, {"Ravi": 8}, 8)
    assert "Ravi carries (5/8):" in txt and "Rope x2" in txt and "at Aisle Two: Duct tape x1" in txt and "bound to Dev" in txt and "1 use left" not in txt and "2 uses left" in txt
    assert "Ravi (alive, skilled in locks)" in txt
    assert "Alarm rig: needs Bell; skill tinkering; known by Ravi" in S.recipes_text(st) and "item Flare gun at Aisle One: in a locker" in S.found_text(st)


# ── the owner's edits and undo ────────────────────────────────────────────────

def test_every_change_can_be_taken_back():
    start = fresh()
    cases = [
        ([{"op": "discover", "kind": "item", "target": "Flare gun", "where": "Aisle One", "who": "Ravi"}], [roll("search", "Ravi", "success")]),
        ([CRAFT], [roll("make", "Ravi", "success")]),
        ([CRAFT], [roll("make", "Ravi", "fail")]),
        ([{"op": "item_give", "who": "Ravi", "target": "Crowbar", "to": "Meera"}], []),
        ([{"op": "item_use", "who": "Ravi", "target": "Bell"}], []),
        ([{"op": "skill_learn", "who": "Meera", "target": "knots"}], [roll("learn", "Meera", "success")]),
        ([{"op": "discover", "kind": "place", "target": "Cellar", "who": "Ravi"}], [roll("search", "Ravi", "success")]),
        ([{"op": "item_remove", "target": "Rope", "qty": 1, "who": "Ravi"}], []),
    ]
    ctx = S.Ctx(TRACKERS, PEOPLE, PLACES)
    for ops, rolls in cases:
        st, ap, dr = run(start, ops, rolls=rolls)
        assert ap and ap[0].get("undo"), ops
        back = copy.deepcopy(st)
        for a in reversed(ap[0]["undo"]):
            things.edit(back, ctx, a)
        assert back["trackers"] == start["trackers"] and back["world_add"] == start["world_add"] and back["recipes"] == start["recipes"] and back["entities"] == start["entities"], ops


def test_owner_edits_validate_their_input():
    st = fresh()
    ctx = S.Ctx(TRACKERS, PEOPLE, PLACES)
    things.edit(st, ctx, {"do": "set_thing", "name": "Lantern", "fields": {"at": "Meera", "qty": 2, "condition": "worn", "uses": 5, "size": 2, "note": "oil lamp"}})
    e = inv(st)["Lantern"]
    assert e["at"] == "Meera" and e["qty"] == 2 and things.props(e)["uses"] == 5 and e["note"] == "oil lamp" and e["origin"]["how"] == "owner"
    with pytest.raises(ValueError):
        things.edit(st, ctx, {"do": "set_thing", "name": "Lantern", "fields": {"at": "Moon"}})
    with pytest.raises(ValueError):
        things.edit(st, ctx, {"do": "set_thing", "name": "Lantern", "fields": {"bound_to": "Nobody"}})
    things.edit(st, ctx, {"do": "set_thing", "name": "Lantern", "fields": {"bound_to": "Meera"}})
    assert inv(st)["Lantern"]["bound_to"] == "Meera"
    things.edit(st, ctx, {"do": "remove_thing", "name": "Lantern"})
    assert "Lantern" not in inv(st)
    things.edit(st, ctx, {"do": "add_skill", "who": "Dev", "skill": "driving"})
    assert st["entities"]["Dev"]["skills"] == ["driving"]
    things.edit(st, ctx, {"do": "remove_skill", "who": "Dev", "skill": "driving"})
    assert st["entities"]["Dev"]["skills"] == []
    things.edit(st, ctx, {"do": "set_recipe", "name": "Torch", "needs": ["Rope"], "tools": [], "skill": "fire"})
    assert st["recipes"]["Torch"]["needs"] == ["Rope"]
    things.edit(st, ctx, {"do": "remove_recipe", "name": "Torch"})
    assert "Torch" not in st["recipes"]
    with pytest.raises(ValueError):
        things.edit(st, ctx, {"do": "explode"})


def test_old_states_without_the_new_fields_still_work():
    old = {"time": "Day 1", "trackers": {"tk-items": {"Crowbar": {"qty": 1, "at": "Ravi", "note": ""}}, "tk-loc": {"at": {"Ravi": "Aisle One"}, "locked": []}}, "entities": {"Ravi": {"alive": True, "status": ""}}}
    txt = S.describe(old, TRACKERS[:2])
    assert "Ravi carries: Crowbar x1" in txt
    st, ap, dr = run(old, [{"op": "item_give", "who": "Ravi", "target": "Crowbar", "to": "Meera"}], trackers=TRACKERS[:2])
    assert not dr and st["trackers"]["tk-items"]["Crowbar"]["at"] == "Meera"
    st, ap, dr = run(old, [{"op": "item_use", "who": "Ravi", "target": "Crowbar"}], trackers=TRACKERS[:2])
    assert not dr and "world_add" in st and st["world_add"] == []
    assert things.props(st["trackers"]["tk-items"]["Crowbar"])["uses"] is None


def test_a_make_may_use_scenery_the_world_text_names_and_parts_already_taken_out():
    here = {"op": "craft", "who": "Ravi", "target": "Wedge", "parts": ["canned beans"], "tools": [], "props": {"uses": 1}}
    st, ap, dr = run(fresh(), [here], rolls=[roll("make", "Ravi", "success")])           # beans are named in the world text and lie in Ravi's aisle
    assert not dr and "Wedge" in inv(st)
    st, ap, dr = run(fresh(), [{**here, "parts": ["spaceship"]}], rolls=[roll("make", "Ravi", "success")])
    assert "no spaceship" in why(dr)
    ops = [{"op": "item_remove", "target": "Bell", "qty": 1, "who": "Ravi"}, {**here, "parts": ["Bell"]}]          # the model removed the part itself and then made the thing
    st, ap, dr = run(fresh(), ops, rolls=[roll("make", "Ravi", "success")])
    assert not dr and "Wedge" in inv(st) and "Bell" not in inv(st)


def test_only_things_places_clues_and_recipes_can_be_found():
    st, ap, dr = run(fresh(), [{"op": "discover", "kind": "entity", "target": "Lurker", "who": "Ravi"}], rolls=[roll("search", "Ravi", "success")])
    assert "not a entity" in why(dr) and not st["world_add"]
    st, ap, dr = run(fresh(), [{"op": "discover", "target": "Torch", "who": "Ravi"}], rolls=[roll("search", "Ravi", "success")])        # no kind written: an item
    assert "Torch" in inv(st)


def test_a_reply_that_will_not_parse_is_asked_again_without_thinking():
    import asyncio
    import json
    from sim import engine, prompts as P
    from story import settings as sm
    from story.llm import LLMResult

    class Bad:
        def __init__(self):
            self.calls = []

        async def complete(self, messages, max_tokens, params=None):
            self.calls.append((max_tokens, dict(params or {})))
            return LLMResult('{"ops" [') if len(self.calls) <= 3 else LLMResult(json.dumps({"ops": []}))      # three bad replies fill the first round

    s = {**sm.get(), "retries": 2, "retry_backoff_s": 0}
    be = Bad()
    assert asyncio.run(engine._json(be, s, P.DELTA, "STATE", m.DeltaOut)).ops == []
    assert be.calls[3][1]["thinking_budget"] == 0 and be.calls[3][0] > be.calls[0][0]


def test_a_failed_search_for_a_thing_the_world_names_still_fails_and_tools_may_be_scenery():
    op = {"op": "discover", "kind": "item", "target": "Tape dispenser", "where": "Aisle One", "who": "Ravi"}           # "tape" is named in the world text
    st, ap, dr = run(fresh(), [op], rolls=[roll("search", "Ravi", "fail", act="Ravi searches for the duct tape")])
    assert "Tape dispenser" not in inv(st) and "search failed" in why(dr)
    st, ap, dr = run(fresh(), [op], rolls=[roll("search", "Ravi", "success", act="Ravi searches for the duct tape")])
    assert "Tape dispenser" in inv(st)
    st, ap, dr = run(fresh(), [op], rolls=[roll("search", "Ravi", "fail", act="Ravi searches the shelves for anything useful")])          # a roll about something else does not block a thing the world holds
    assert "Tape dispenser" in inv(st)
    make = {"op": "craft", "who": "Ravi", "target": "Wedge", "parts": ["Bell"], "tools": ["crowbar", "water"], "props": {}}
    st, ap, dr = run(fresh(), [make], rolls=[roll("make", "Ravi", "success")])                                          # water is scenery in the world text
    assert not dr


def test_a_find_is_not_added_a_second_time_in_the_same_chapter():
    ops = [{"op": "discover", "kind": "item", "target": "Torch", "where": "Aisle One", "who": "Ravi"}, {"op": "item_add", "target": "Torch", "qty": 1, "to": "Ravi", "source": "Aisle One"}]
    st, ap, dr = run(fresh(), ops, rolls=[roll("search", "Ravi", "success")])
    assert inv(st)["Torch"]["qty"] == 1 and "already added" in why(dr)
