"""Narration v2 (tasks 2.4 to 2.7): draft, edit and tag passes from the Material Pack, with the checks that send the editor back."""
import asyncio
import json
import re

from story.llm import LLMResult
from story2 import lexicon, narrate2, planner
from test_material import MFake, material, planned, reply


def blueprint_reply():
    beats = [{"id": f"b{i}", "name": f"part {i}", "purpose": "p", "takeaway": "t", "facts": ["f"], "use": [f"m{i}", f"m{i + 5}"], "turn": "A reversal", "reward": f"reward {i}",
              "question": "why", "answer_beat": "b5", "ends_on": "the next thing"} for i in range(1, 6)]
    return {"structure": "mystery", "viewer_promise": "p", "central_question": "q", "payoff_position": "b4", "beats": beats}


CLEAN = "यह एक साफ़ शुरुआत है। " + " ".join(f"word{chr(97 + k)} बताया गया था।" for k in range(14))
WORN = "सोचिए, यह क्या हुआ? क्या आप सोच सकते हैं? क्या यह सच है? " + CLEAN


class NFake(MFake):
    def __init__(self, *a, draft=WORN, edit_fixes=True, **kw):
        super().__init__(*a, **kw)
        self.draft, self.edit_fixes, self.edits = draft, edit_fixes, []

    async def complete(self, messages, max_tokens, params=None):
        task = re.match(r"\[TASK:(\w+)\]", messages[0]["content"]).group(1)
        user = messages[-1]["content"] if messages else ""
        if task == "p2_blueprint":
            self.calls.append({"task": task, "user": messages[1]["content"], "system": messages[0]["content"]})
            return LLMResult(json.dumps(blueprint_reply()))
        if task == "p2_narrate_draft":
            self.calls.append({"task": task, "user": messages[1]["content"], "system": messages[0]["content"], "params": params})
            return LLMResult(self.draft)
        if task == "p2_narrate_edit":
            self.calls.append({"task": task, "user": messages[1]["content"]})
            self.edits.append(messages[1]["content"])
            return LLMResult(CLEAN if self.edit_fixes else self.draft)
        if task == "p2_narrate_tag":
            self.calls.append({"task": task, "user": messages[1]["content"]})
            n = len(re.findall(r"^\d+\. ", messages[1]["content"], re.M))
            return LLMResult(json.dumps({"sentences": [{"n": i, "emotion": "clear" if i == 2 else "neutral", "pause_after_s": 0.4 if i == n else 0} for i in range(1, n + 1)],
                                         "pronounce": [{"word": "Ada", "say": "ऐडा", "note": "name"}], "emphasis": ["worda"]}))
        return await super().complete(messages, max_tokens)


def ready(env, **kw):
    plan, _ = planned(env)
    be = NFake(**kw)
    asyncio.run(material.make_material(plan["id"], be))
    asyncio.run(planner.make_blueprint(plan["id"], be))
    return plan["id"], be


def test_split_and_coverage_helpers():
    assert narrate2.split_sentences("एक बात। दो बात? हाँ") == ["एक बात।", "दो बात?", "हाँ।"] or len(narrate2.split_sentences("एक बात। दो बात? हाँ")) == 2
    s = narrate2.split_sentences("वह घर गया। ठीक। फिर लौटा।")
    assert s[0].startswith("वह घर गया") and len(s) == 2                                    # a one-word fragment joins the sentence before it
    it = {"detail": "a rusty transformer by the road", "say": ["transformer"], "who": ""}
    assert narrate2.covered(it, "वह transformer के पास रुका") and not narrate2.covered(it, "वह घर गया")
    assert narrate2.covered({"detail": "a rusty transformer by the road", "say": [], "who": ""}, "rusty transformer था")


def test_applies_only_with_a_pack_and_beats_that_use_it(env):
    plan, _ = planned(env)
    assert not narrate2.applies(planner.get_plan(plan["id"]))
    pid, be = ready(env)
    assert narrate2.applies(planner.get_plan(pid))


def test_three_passes_write_clean_tagged_narration(env):
    pid, be = ready(env)
    p = asyncio.run(planner.make_narration(pid, be))
    segs = sorted(p["segments"], key=lambda s: s["seq"])
    assert [s["beat"] for s in segs] == ["b1", "b2", "b3", "b4", "b5"]
    text = " ".join(s["plain"] for s in segs)
    assert not lexicon.hits(text) and text.count("?") == 0
    assert be.count("p2_narrate_draft") == 7 and be.count("p2_narrate_edit") >= 7 and be.count("p2_narrate_tag") == 5          # the opening and the ending are written twice (best of two)
    assert be.count("p2_judge_narration") == 4 and be.count("p2_backtranslate") == 5                                        # two judge calls per pair, one gate per part
    assert segs[0]["sentences"][1]["emotion"] == "clear" and segs[0]["pronounce"][0]["say"] == "ऐडा"
    assert segs[0]["issues"] == [] and segs[0]["facts_used"] == ["m1", "m6"]
    assert next(c for c in be.calls if c["task"] == "p2_narrate_draft")["params"]["temperature"] == 0.8


def test_the_editor_is_told_what_is_wrong_and_never_the_whole_banned_list(env):
    pid, be = ready(env)
    asyncio.run(planner.make_narration(pid, be))
    first = be.edits[0]
    assert "सोचिए" in first and "worn out" in first and "question" in first.lower()
    assert "genius" not in first and "mastermind" not in first                                # the rest of the list is not shown: a small model copies what it sees


def test_a_defect_the_editor_cannot_fix_is_stored_not_silently_accepted(env):
    pid, be = ready(env, edit_fixes=False)
    p = asyncio.run(planner.make_narration(pid, be))
    seg = sorted(p["segments"], key=lambda s: s["seq"])[0]
    assert seg["issues"] and any("worn out" in i["text"] for i in seg["issues"]) and seg["issues"][0]["level"] == "warn"
    assert be.count("p2_narrate_edit") == 7 * narrate2.EDIT_ROUNDS


def test_details_that_are_missing_are_named_to_the_editor(env):
    pid, be = ready(env, draft="यह बस एक छोटा सा वाक्य है। " * 6)
    asyncio.run(planner.make_narration(pid, be))
    assert "MISSING DETAILS" in be.edits[0] and "m1 [" in be.edits[0]


def test_old_plans_without_a_pack_still_use_the_old_single_call(env):
    plan, _ = planned(env)
    be = NFake()
    asyncio.run(planner.make_blueprint(plan["id"], be))
    asyncio.run(planner.make_narration(plan["id"], be))
    assert be.count("p2_narrate") >= 1 and be.count("p2_narrate_draft") == 0


def test_the_experience_design_reaches_the_beat_it_is_for():
    bp = {"beats": [{"id": "b1"}, {"id": "b2"}, {"id": "b3"}], "experience": {
        "stake_to_viewer": "anyone with a phone could lose their savings", "clock_device": "six hours", "clue_device": "one number calls his family again and again",
        "set_piece": {"beat": "b2", "idea": "the stakeout, hour by hour"}, "participation": {"pause_and_guess_beat": "b3"}}}
    one, two, three = (narrate2.experience_lines(bp, b) for b in ("b1", "b2", "b3"))
    assert "anyone with a phone" in one and "six hours" in one and "THE SET PIECE" not in one
    assert "THE SET PIECE" in two and "stakeout" in two and "anyone with a phone" not in two
    assert "asks the viewer what they think happens next" in three
    assert narrate2.experience_lines({"beats": [{"id": "b1"}]}, "b1") == ""
