"""Tasks 2.8, 2.9, 2.11, 2.16 and 2.17: best of two for the opening and ending, the automatic Hindi gate, canonical names, the payoff check, the held pause-and-guess."""
import asyncio
import json
import re
from types import SimpleNamespace

from story.llm import LLMResult
from story2 import hindigate, material, narrate2, planner
from test_narration_v2 import CLEAN, NFake, blueprint_reply
from test_material import material as material_mod, planned


class GFake(NFake):
    """Drafts differ by temperature, the editor returns the prose unchanged, the judge likes the version that contains `zz`, the Hindi gate answers from a script."""

    def __init__(self, *a, gate=None, experience=None, **kw):
        super().__init__(*a, draft=CLEAN, **kw)
        self.gate, self.experience = list(gate or []), experience

    async def complete(self, messages, max_tokens, params=None):
        task = re.match(r"\[TASK:(\w+)\]", messages[0]["content"]).group(1)
        user = messages[-1]["content"]
        if task == "p2_blueprint":
            bp = blueprint_reply()
            if self.experience:
                bp["experience"] = self.experience
            self.calls.append({"task": task, "user": user})
            return LLMResult(json.dumps(bp))
        if task == "p2_narrate_draft":
            self.calls.append({"task": task, "user": user, "params": params, "system": messages[0]["content"]})
            return LLMResult(CLEAN.replace("worda", "zzword") if (params or {}).get("temperature") == 0.9 else CLEAN)
        if task == "p2_narrate_edit":
            self.calls.append({"task": task, "user": user})
            self.edits.append(user)
            return LLMResult(user.split("PART PROSE:\n")[1].split("\n\nPROBLEMS FOUND")[0])
        if task == "p2_judge_narration":
            self.calls.append({"task": task, "user": user})
            a, b = user.split("VERSION A:\n")[1].split("\n\nVERSION B:\n")
            return LLMResult(json.dumps({"winner": "A" if "zz" in a else "B", "reason": "likes zz"}))
        if task == "p2_judge_hindi":
            self.calls.append({"task": task, "user": user})
            verdict = self.gate.pop(0) if self.gate else {}
            return LLMResult(json.dumps({"missing": [], "contradicted": [], "stiff": [], "english_heavy": False, "gender_wrong": False, "samey": False, **verdict}))
        return await super().complete(messages, max_tokens, params)


def ready(env, **kw):
    plan, _ = planned(env)
    be = GFake(**kw)
    asyncio.run(material_mod.make_material(plan["id"], be))
    asyncio.run(planner.make_blueprint(plan["id"], be))
    return plan["id"], be


def test_the_opening_and_ending_are_written_twice_and_the_better_one_kept(env):
    pid, be = ready(env)
    p = asyncio.run(planner.make_narration(pid, be))
    segs = {s["beat"]: s for s in p["segments"]}
    assert "zzword" in segs["b1"]["plain"] and "zzword" in segs["b5"]["plain"] and "zzword" not in segs["b3"]["plain"]       # the warmer version won where it was offered
    alt = p["settings"]["narration_alt"]
    assert set(alt) == {"b1", "b5"} and "zzword" not in alt["b1"] and "worda" in alt["b1"]                                  # the loser is kept for the editor
    swapped = [c["user"] for c in be.calls if c["task"] == "p2_judge_narration"]
    assert len(swapped) == 4 and swapped[0].split("VERSION A:")[1] != swapped[1].split("VERSION A:")[1]                    # asked twice, order swapped


def test_a_split_judgement_keeps_the_first_version(env):
    pid, be = ready(env)

    class Flip(GFake):
        async def complete(self, messages, max_tokens, params=None):
            if messages[0]["content"].startswith("[TASK:p2_judge_narration]"):
                return LLMResult(json.dumps({"winner": "A", "reason": "always the first"}))
            return await super().complete(messages, max_tokens, params)
    p = asyncio.run(planner.make_narration(pid, Flip()))
    assert "zzword" not in " ".join(s["plain"] for s in p["segments"])


def test_the_hindi_gate_sends_a_part_back_once_with_what_it_found(env):
    pid, be = ready(env, gate=[{"contradicted": ["m1"]}])
    p = asyncio.run(planner.make_narration(pid, be))
    assert any("told differently" in e and "m1" in e for e in be.edits)
    assert all(not [i for i in s["issues"] if i["kind"] == "hindi_gate"] for s in p["segments"])                          # the second check passed


def test_a_part_that_still_fails_the_gate_is_stored_as_an_issue(env):
    pid, be = ready(env, gate=[{"stiff": [{"start": "यह एक", "why": "bookish"}], "gender_wrong": True}] * 40)
    p = asyncio.run(planner.make_narration(pid, be))
    seg = sorted(p["segments"], key=lambda s: s["seq"])[0]
    kinds = [i["text"] for i in seg["issues"] if i["kind"] == "hindi_gate"]
    assert any("bookish" in k for k in kinds) and any("masculine" in k for k in kinds)


def test_a_model_failure_in_the_gate_never_stops_the_film():
    class Down:
        async def complete(self, *a, **k):
            from story.llm import LLMError
            raise LLMError("down")
    g = asyncio.run(hindigate.check(["एक वाक्य।"], [{"id": "m1", "detail": "a thing"}], "metro_hinglish", Down(), {"retries": 0, "transport_retries": 0, "retry_backoff_s": 0, "context_limit": 100000, "output_reserve": 1000, "safety_margin": 0.1, "chars_per_token": 3.0, "json_mode": "off", "temperature": 0.2, "timeout_s": 5}))
    assert g["ok"] and g["unchecked"]


def test_pause_and_guess_holds_the_picture_after_its_question(env):
    pid, be = ready(env, experience={"promise": "p", "participation": {"pause_and_guess_beat": "b3", "closing_question": "q"}})
    p = asyncio.run(planner.make_narration(pid, be))
    by = {s["beat"]: s for s in p["segments"]}
    assert by["b3"]["sentences"][-1]["pause_after_s"] >= narrate2.PAUSE_AND_GUESS_HOLD_S
    assert by["b2"]["sentences"][-1]["pause_after_s"] < narrate2.PAUSE_AND_GUESS_HOLD_S


def test_the_payoff_part_must_state_the_answer():
    ctx = SimpleNamespace(first=False, last=False, per_beat=15, avoid=(), questions=0, spoken=["पहले की बात।"], items=[], profile="metro_hinglish", payoff="the transformer was stolen by the night guard",
                          is_payoff=True)
    probs, _ = narrate2.problems(["एक छोटी बात। " * 10], ctx)
    assert any("central question" in x for x in probs)
    ctx.is_payoff = False
    assert not [x for x in narrate2.problems(["एक छोटी बात। " * 10], ctx)[0] if "central question" in x]


def test_a_closing_question_must_be_open():
    ctx = SimpleNamespace(first=False, last=True, per_beat=5, avoid=(), questions=0, spoken=[], items=[], profile="metro_hinglish")
    yes_no = narrate2.problems(["यह खत्म हुआ।", "क्या आप ऐसा करते?"], ctx)[0]
    assert any("yes or no" in x for x in yes_no)
    assert not [x for x in narrate2.problems(["यह खत्म हुआ।", "आपके हिसाब से इसका ज़िम्मेदार कौन था?"], ctx)[0] if "yes or no" in x]


def test_variant_spellings_of_a_name_are_rewritten():
    names = [{"name": "Chhavi Sharma", "say": "छवि"}]
    fixed, found = material.canonical("Chavi घर गई। Chhavi फिर आई। Charge ठीक था।", names)
    assert "Chavi" not in fixed and fixed.count("Chhavi") == 2 and found == [("Chavi", "Chhavi")] and "Charge" in fixed
    assert material.name_variants("Delhi में Chhavi", names) == []


def test_each_story_type_adds_its_own_note_to_the_draft_and_edit_passes(env):
    from story import storytypes
    for t in storytypes.TYPES if hasattr(storytypes, "TYPES") else ("incident", "biography", "documentary", "explainer", "listicle"):
        assert storytypes.tell_note(t) and storytypes.polish_note(t)
    assert storytypes.tell_note("incident") != storytypes.tell_note("explainer") and storytypes.tell_note("nonsense") == ""
    pid, be = ready(env)
    asyncio.run(planner.make_narration(pid, be))
    drafts = [c for c in be.calls if c["task"] == "p2_narrate_draft"]
    assert drafts and all(storytypes.tell_note(storytypes.of_plan(planner.get_plan(pid)))[:40] in c["system"] for c in drafts)


def test_hindi_written_in_latin_letters_is_converted_by_a_plain_transliteration_pass(env):
    """Seen on the real model: the editor kept writing 'Dark matter ek adrishya tatva hai'. After the editor rounds a transliteration step puts the Hindi into Devanagari."""
    roman = "Dark matter ek adrishya tatva hai. Brahmand ka lagbhag hissa isi se bana hai. " + " ".join(f"Hum aksar cheezon par dhyan dete hain word{chr(97 + k)}." for k in range(12))
    pid, _ = ready(env)

    class Roman(GFake):
        async def complete(self, messages, max_tokens, params=None):
            task = re.match(r"\[TASK:(\w+)\]", messages[0]["content"]).group(1)
            if task in ("p2_narrate_draft", "p2_narrate_edit"):
                self.calls.append({"task": task, "user": messages[-1]["content"], "params": params, "system": messages[0]["content"]})
                return LLMResult(roman)
            if task == "p2_devanagari":
                self.calls.append({"task": task, "user": messages[-1]["content"]})
                return LLMResult(CLEAN)
            return await super().complete(messages, max_tokens, params)
    be = Roman()
    p = asyncio.run(planner.make_narration(pid, be))
    assert be.count("p2_devanagari") >= 5
    assert "adrishya" not in " ".join(s["plain"] for s in p["segments"])


def test_a_label_of_the_story_material_spoken_aloud_is_sent_back():
    """Seen on the real model: 'M thirteen interaction dark matter ...'."""
    ctx = SimpleNamespace(first=False, last=False, per_beat=15, avoid=(), questions=0, spoken=["पहले की बात।"], items=[], profile="metro_hinglish")
    probs, _ = narrate2.problems(["M thirteen interaction एक संकेत देता है। " + "यह एक छोटी बात है। " * 6, "m7 के बारे में बात।"], ctx)
    assert any("labels of the details" in p and "M thirteen" in p for p in probs)
    assert not [p for p in narrate2.problems(["यह एक Model thirteen पर बात है। " * 4], ctx)[0] if "labels" in p]
