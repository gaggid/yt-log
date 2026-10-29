"""The Material Pack: a model step that writes 30 to 40 paraphrased details from the source passages, checked by the leak gate."""
import asyncio
import json
import re

from story import db
from story.llm import LLMResult
from story2 import leak, material, planner
from test_phase2a import P2Fake, approved_story


def reply(n=14, copy=None, who="Ada"):
    kinds = ["object", "place", "action"] * 6
    items = [{"kind": kinds[i], "detail": f"Detail number {i} says something concrete about the {kinds[i]} {i}", "when": "1901", "where": "the workshop", "who": who,
              "basis": "stated", "alleged": i % 5 == 0, "visual": 3, "weight": 2, "say": [f"word{chr(97 + i)}"]} for i in range(n)]
    if copy:
        items[0]["detail"] = copy
    return {"items": items, "chain": ["first she noticed it", "then she checked"], "names": [{"name": who, "say": "ऐडा"}]}


class MFake(P2Fake):
    def __init__(self, *a, items=14, copy_first=None, **kw):
        super().__init__(*a, **kw)
        self.items, self.copy_first, self.user_seen = items, copy_first, ""

    async def complete(self, messages, max_tokens):
        task = re.match(r"\[TASK:(\w+)\]", messages[0]["content"]).group(1)
        if task == "p2_material":
            self.calls.append({"task": task, "user": messages[1]["content"]})
            self.user_seen = messages[1]["content"]
            return LLMResult(json.dumps(reply(self.items, self.copy_first)))
        return await super().complete(messages, max_tokens)


def planned(env):
    pid, cid = approved_story(env)
    return planner.create_plan(cid, minutes=2), cid


def test_pack_is_written_with_ids_and_chain(env):
    plan, _ = planned(env)
    be = MFake()
    p = asyncio.run(material.make_material(plan["id"], be))
    pk = material.pack(p)
    assert len(pk["items"]) == 14 and [i["id"] for i in pk["items"]][:2] == ["m1", "m2"] and pk["chain"] and pk["names"][0]["say"] == "ऐडा"
    assert material.has(p) and "m3 [action" in material.text_for(p) and "ALLEGED" in material.text_for(p)
    assert "SOURCE PASSAGES" in be.user_seen and "STORY FACTS" in be.user_seen
    assert planner.get_plan(plan["id"])["settings"]["material"]["pipeline"] == "q2"


def test_copied_source_wording_is_sent_back_then_dropped_if_it_stays(env):
    plan, cid = planned(env)
    story = planner._story_for(plan)
    passage = story["evidence"]["passages"][0]
    copied = " ".join(passage.split()[:12])
    be = MFake(copy_first=copied)
    p = asyncio.run(material.make_material(plan["id"], be))
    assert be.count("p2_material") >= 2                                           # sent back with the finding
    pk = material.pack(p)
    assert pk["dropped"] == 1 and copied not in " ".join(i["detail"] for i in pk["items"])
    assert not leak.check_many([(i["id"], i["detail"]) for i in pk["items"]], leak.profile(story["evidence"]["project_id"], story["evidence"]["passages"]))


def test_a_list_that_is_too_short_is_refused(env):
    plan, _ = planned(env)
    be = MFake(items=5)
    try:
        asyncio.run(material.make_material(plan["id"], be))
    except Exception as e:  # noqa: BLE001
        assert "needs at least" in str(e) or "no valid reply" in str(e)
    else:
        raise AssertionError("a five-item list must not be accepted")


def test_real_names_are_hidden_from_the_model_by_the_name_map(env):
    plan, _ = planned(env)
    st = {**plan["settings"], "name_map": {"Ada": "Sunita"}}
    db.ex("UPDATE plans SET settings=? WHERE id=?", (db.jdump(st), plan["id"]))
    be = MFake()
    asyncio.run(material.make_material(plan["id"], be))
    assert "Ada" not in be.user_seen and "Sunita" in be.user_seen


def test_manual_items_survive_a_new_run_and_edits_are_cleaned(env):
    plan, _ = planned(env)
    asyncio.run(material.make_material(plan["id"], MFake()))
    cur = material.pack(planner.get_plan(plan["id"]))["items"]
    edited = cur[:3] + [{"kind": "thing", "detail": "A hand-written detail about the old brass key", "visual": 3}, {"kind": "object", "detail": "x"}]
    p = material.save_items(plan["id"], edited)
    items = material.pack(p)["items"]
    assert len(items) == 4                                                          # the one-word detail is refused
    mine = [i for i in items if i["manual"]]
    assert len(mine) == 1 and mine[0]["kind"] == "object" and mine[0]["id"].startswith("x")
    p2 = asyncio.run(material.make_material(plan["id"], MFake()))
    assert any(i["detail"].startswith("A hand-written detail") for i in material.pack(p2)["items"])


# ── blueprint v2 (task 2.3) ─────────────────────────────────────────────────

def pack_items(n=10, heavy=(0, 1)):
    return [{"id": f"m{i + 1}", "kind": "object", "detail": f"detail {i} of the story", "weight": 3 if i in heavy else 1} for i in range(n)]


def bp_with(beats, **kw):
    from story2.schemas import Blueprint
    return Blueprint.model_validate({"structure": "mystery", "viewer_promise": "p", "beats": beats, **kw})


def beat(i, use, turn="He learns the truth", show=()):
    return {"id": f"b{i}", "name": "n", "purpose": "p", "use": use, "show": list(show), "turn": turn}


def test_blueprint_must_use_the_pack_and_name_a_turn_that_is_a_statement():
    items = pack_items()
    good = bp_with([beat(1, ["m1", "m2"]), beat(2, ["m3", "M4"]), beat(3, [5, "m6"])], payoff_position="b2")
    assert material.blueprint_problems(good, items) == []
    bad = bp_with([beat(1, ["m1"]), beat(2, ["m99", "m3"], turn="Why did he run?"), beat(3, ["m4", "m5"], turn="")], payoff_position="b9")
    msgs = " | ".join(material.blueprint_problems(bad, items))
    assert "fewer than 2 details" in msgs and "not in the story material: m99" in msgs and "not a question" in msgs and "payoff_position" in msgs
    assert "used by no beat" in " | ".join(material.blueprint_problems(bp_with([beat(1, ["m3", "m4"]), beat(2, ["m5", "m6"]), beat(3, ["m7", "m8"])]), items))      # m1 and m2 are heavy and unused


def test_clean_blueprint_drops_unknown_ids_limits_show_and_sets_a_payoff_beat():
    bp = bp_with([beat(1, ["m1", "m77"], show=["m1", "m2", "m3", "m4"]), beat(2, ["m2"]), beat(3, ["m3"])]).model_dump()
    material.clean_blueprint(bp, pack_items())
    assert "m77" not in bp["beats"][0]["use"] and bp["beats"][0]["use"][0] == "m1" and len(bp["beats"][0]["show"]) == 3 and bp["payoff_position"] == "b2"


def test_blueprint_asks_with_the_material_and_stores_the_new_fields(env):
    from story2 import prompts as Pr

    class BFake(MFake):
        async def complete(self, messages, max_tokens):
            task = re.match(r"\[TASK:(\w+)\]", messages[0]["content"]).group(1)
            if task == "p2_blueprint":
                self.calls.append({"task": task, "user": messages[1]["content"], "system": messages[0]["content"]})
                beats = [{"id": f"b{i}", "name": "n", "purpose": "p", "takeaway": "t", "facts": ["f"], "use": [f"m{i}", f"m{i + 5}"], "turn": "A reversal", "reward": "a key", "question": "why", "answer_beat": "b5"} for i in range(1, 6)]
                return LLMResult(json.dumps({"structure": "mystery", "viewer_promise": "p", "central_question": "q", "payoff_position": "b4", "beats": beats}))
            return await super().complete(messages, max_tokens)

    plan, _ = planned(env)
    be = BFake()
    asyncio.run(material.make_material(plan["id"], be))
    p = asyncio.run(planner.make_blueprint(plan["id"], be))
    call = next(c for c in be.calls if c["task"] == "p2_blueprint")
    assert "STORY MATERIAL (ids you can use)" in call["user"] and "m3 [" in call["user"] and Pr.BLUEPRINT_MATERIAL.strip()[:30] in call["system"]
    b1 = p["blueprint"]["beats"][0]
    assert b1["use"] == ["m1", "m6"] and b1["turn"] == "A reversal" and p["blueprint"]["payoff_position"] == "b4"


def test_blueprint_without_a_pack_is_unchanged(env):
    plan, _ = planned(env)
    be = MFake()
    p = asyncio.run(planner.make_blueprint(plan["id"], be))
    call = next(c for c in be.calls if c["task"] == "p2_blueprint")
    assert "STORY MATERIAL" not in call["user"] and p["blueprint"]["beats"][0]["use"] == []


def test_a_blueprint_with_ids_in_facts_and_no_use_is_repaired_so_the_new_narration_still_runs():
    """Seen on the real model: ids written into `facts`, no `use`, no `turn`. The beats must still end up with details, or narration would silently use the older path."""
    items = [{"id": f"m{i}", "kind": "action", "detail": f"detail number {i} happens", "weight": 3 if i == 9 else 1} for i in range(1, 11)]
    bp = {"beats": [{"id": "b1", "facts": ["m2", "m1"], "reveal": "a reveal"}, {"id": "b2", "facts": ["a plain fact"]}, {"id": "b3", "facts": ["m5", "m6", "m7"], "plant": "a small thing"}],
          "payoff_position": "nope"}
    material.clean_blueprint(bp, items)
    assert bp["beats"][0]["use"][:2] == ["m1", "m2"] and bp["beats"][0]["turn"] == "a reveal"             # ids found in facts, put in story order
    assert all(len(b["use"]) >= 2 for b in bp["beats"]) and "m9" in sum((b["use"] for b in bp["beats"]), [])    # a heavy detail nobody used is given to a beat
    assert bp["beats"][2]["facts"] == ["m5", "m6", "m7"] or not any(f.startswith("m") and f[1:].isdigit() for f in bp["beats"][2]["facts"])
    assert bp["payoff_position"] == "b2" and bp["beats"][2]["reward"] == "a small thing"


def test_experience_design_is_checked_against_the_material():
    items = [{"id": f"m{i}", "kind": "object", "detail": f"a rusty green transformer number {i} by the road", "weight": 1, "visual": 3 if i < 6 else 0} for i in range(1, 9)]
    beats = [beat(i, [f"m{i}", f"m{i + 1}"]) for i in range(1, 6)]
    ok = bp_with(beats, payoff_position="b3", experience={"stake_to_viewer": "your own street", "clue_device": "the transformer", "afterimage": "a rusty green transformer by the road",
                                                           "set_piece": {"beat": "b1", "idea": "x"}})
    ok.beats[0].use = ["m1", "m2", "m3", "m4"]
    ok.beats[0].show = ["m1"]
    assert material.experience_problems(ok, items) == []
    bad = bp_with(beats, payoff_position="b3", experience={"stake_to_viewer": "", "clue_device": "x", "afterimage": "a blue boat at sea", "set_piece": {"beat": "b2", "idea": "x"}})
    msgs = " | ".join(material.experience_problems(bad, items))
    assert "stake_to_viewer" in msgs and "fewer than 4" in msgs and "afterimage" in msgs and "no beat before the answer shows" in msgs
    late = bp_with([beat(i, [f"m{i}", f"m{i + 1}"]) for i in range(1, 8)], payoff_position="b7")
    assert "too late" in " | ".join(material.blueprint_problems(late, items))
    assert "too late" not in " | ".join(material.blueprint_problems(bp_with([beat(i, [f"m{i}", f"m{i + 1}"]) for i in range(1, 8)], payoff_position="b6"), items))
