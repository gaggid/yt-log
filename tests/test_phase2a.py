import asyncio
import json
import re

import pytest

from fakellm import FakeBackend
from story import db, projects, review
from story.llm import LLMResult
from story2 import intake, leak, planner, svara
from test_pipeline import make_book, run


class P2Fake(FakeBackend):
    """Adds the Phase 2 tasks to the Phase 1 fake: a blueprint, and Hindi narration with optional bad replies."""

    def __init__(self, *a, bad_script_once=False, leak_text="", **kw):
        super().__init__(*a, **kw)
        self.bad_script_once, self.leak_text = bad_script_once, leak_text

    async def complete(self, messages, max_tokens):
        system = messages[0]["content"]
        task = re.match(r"\[TASK:(\w+)\]", system).group(1)
        if task == "p2_blueprint":
            self.calls.append({"task": task, "user": messages[1]["content"]})
            beats = [{"id": f"b{i}", "name": n, "purpose": f"purpose {i}", "takeaway": "t", "facts": ["f"]}
                     for i, n in enumerate(["opening", "context", "turn", "payoff", "ending"], 1)]
            return LLMResult(json.dumps({"structure": "decision consequence", "viewer_promise": "understand what happened",
                                         "central_question": "why?", "turning_point": "the turn", "payoff": "p", "ending": "e", "beats": beats}))
        if task == "p2_director":
            n = int(re.search(r"Plan the film now: (\d+) segments", messages[1]["content"]).group(1))
            self.calls.append({"task": task, "user": messages[1]["content"]})
            secs = [float(x) for x in re.findall(r"SEGMENT \d+ \(beat \w+, (\d+) s\)", messages[1]["content"])]
            filler = [("medium", "side", "object", "pan right"), ("extreme close", "eye level", "hands", "tilt down")]

            def shots_for(n_shots):                                  # the first shot is wide/high and the middle one close/low, as the fake scenes are
                out = []
                for i in range(n_shots):
                    size, angle, kind, move = (("wide", "high", "establishing", "pull back") if i == 0 else ("close", "low", "person", "push in") if i == n_shots // 2 else filler[i % 2])
                    out.append({"focus": f"shot {i + 1}", "kind": kind, "size": size, "angle": angle, "move": move, "why": "because"})
                return out
            return LLMResult(json.dumps({"arc": "worry to relief", "segments": [{"segment": i, "emotion": "tense", "place": "the office", "state": "the trader is worried",
                                                                                "shots": shots_for(max(3, round((secs[i - 1] if i <= len(secs) else 0) / 8)))} for i in range(1, n + 1)]}))
        if task == "p2_narrate":
            user = messages[1]["content"]
            self.calls.append({"task": task, "user": user, "system": system})
            beat = re.search(r"THIS BEAT ONLY \((b\d+)", user).group(1)
            text = "यह एक परीक्षण वाक्य है " + "और बात आगे बढ़ती है " * 20
            if self.bad_script_once:
                self.bad_script_once = False
                text += "сатдесят"
            if self.leak_text:
                text += self.leak_text
            return LLMResult(json.dumps({"segments": [{"beat": beat, "sentences": [
                {"text": text, "emotion": "scared", "pause_after_s": 0.5}, {"text": "मैं आपको दिखाता हूँ।", "emotion": "neutral"}]}]}))
        return await super().complete(messages, max_tokens)


def approved_story(env, fake=None):
    pid = projects.import_text(make_book(3, 8))
    run(pid, fake or FakeBackend())
    cid = review.list_candidates(pid)[0]["id"]
    review.update_candidate(cid, {"status": "approved"})
    return pid, cid


def written_plan(cid, be, minutes=2):
    p = planner.create_plan(cid, minutes=minutes)
    asyncio.run(planner.make_blueprint(p["id"], be))
    return asyncio.run(planner.make_narration(p["id"], be))


def test_svara_tags_are_valid_separate_and_checked():
    sents = [{"text": "यह खबर बुरी थी।", "emotion": "sad", "pause_after_s": 1.2}, {"text": "फिर सब बदल गया।", "emotion": "afraid"}]
    a = svara.serialise(sents)
    assert a == "यह खबर बुरी थी। <sad> [pause:1.2s] फिर सब बदल गया। <fear>"
    assert svara.plain_text(a) == "यह खबर बुरी थी। फिर सब बदल गया।"
    assert svara.validate(a) == []
    assert len(svara.validate("नमस्ते <excited> [beep:1s] [pause:12s]")) == 3
    assert svara.norm_emotion("unknown") == "neutral" and svara.pause_tag(99) == "[pause:10s]"
    assert svara.foreign_chars("सात दशमलव पाँच") == [] and svara.foreign_chars("सातдесят 5 stock")
    assert svara.foreign_chars("यह एक stock और earnings release है।") == []                  # Hinglish: English words in Latin script are fine
    assert svara.foreign_chars("seventeen percent गिरा 17%") == ["%", "1", "7"]               # digits and symbols are not
    assert svara.mixed_words("यह stockको तोड़ दिया") == ["stockको"] and svara.mixed_words("यह stock को तोड़ दिया") == []
    assert svara.spoken_seconds(" ".join(["w"] * 148)) == 60.0


def test_leak_validator_catches_every_kind_of_trace():
    prof = leak.SourceProfile(title="The Master Swing Trader Toolkit (v2)", author="Alan S. Farley", credits=["eSignal"],
                              chapter_titles=["Part One: Parsing the Modern Markets"],
                              passages=["the stock gapped down at the open and then traded in a narrow range for the first hour of the session"])
    kinds = lambda t: {f.kind for f in leak.check(t, prof)}                        # noqa: E731
    assert "title" in kinds("the master swing trader toolkit says so")
    assert "author" in kinds("Farley explained it") and "credit" in kinds("chart by eSignal")
    assert "self_reference" in kinds("According to the author, it fell") and "self_reference" in kinds("in chapter 3 he writes")
    assert "self_reference" in kinds("इस किताब के अनुसार") and "part_title" in kinds("Part One: Parsing the Modern Markets")
    assert "paragraph_tag" in kinds("it fell [P12]")
    assert "copied_wording" in kinds("remember the stock gapped down at the open and then traded in a narrow range today")
    assert kinds("The shares fell sharply in the morning and recovered by lunch.") == set()
    assert leak.overlap_share("a b c d e f g h", ["a b c d e f g h"]) == 1.0


def test_intake_uses_approved_story_and_keeps_quotes_out(env):
    pid, cid = approved_story(env)
    st = intake.load(cid)
    assert st["candidate"]["status"] == "approved" and st["evidence"]["paragraph_ids"] and st["evidence"]["passages"]
    assert "quote" not in st["public"] and '"quote"' not in json.dumps(st["public"]) and "paragraph_ids" not in json.dumps(st["public"])
    assert "NOT KNOWN" in intake.facts_text(st["public"])                          # a missing outcome is stated as unknown, not filled in
    r = intake.readiness(st)
    assert r["ready"] and any(c["code"] == "outcome" for c in r["checks"]) and any(c["code"] == "verification" for c in r["checks"])
    review.update_candidate(cid, {"status": "rejected"})
    assert not intake.readiness(intake.load(cid))["ready"]
    with pytest.raises(planner.PlanError):
        planner.create_plan(cid)


def test_plan_blueprint_narration_and_alignment(env):
    pid, cid = approved_story(env)
    be = P2Fake()
    p = written_plan(cid, be)
    assert p["blueprint"]["structure"] == "decision_consequence" and len(p["blueprint"]["beats"]) == 5
    segs = p["segments"]
    assert [s["beat"] for s in segs] == ["b1", "b2", "b3", "b4", "b5"]             # one call per beat, in order
    assert all(s["sentences"][0]["emotion"] == "fear" for s in segs)               # "scared" mapped to Svara's label
    assert all("<" not in s["plain"] and "[" not in s["plain"] and "<fear>" in s["annotated"] for s in segs)
    assert abs(p["duration_s"] - sum(s["duration_s"] for s in segs)) < 0.2
    calls = [c for c in be.calls if c["task"] == "p2_narrate"]
    assert "This is the opening" in calls[0]["user"] and "ALREADY NARRATED" in calls[1]["user"]
    assert "not set yet" in calls[0]["system"]                                       # no narrator name yet: the model is told not to invent one
    assert "paragraph" not in calls[0]["user"].lower() and "[P" not in calls[0]["user"]


def test_edit_one_segment_leaves_others_and_locked_survive_regeneration(env):
    pid, cid = approved_story(env)
    be = P2Fake()
    p = written_plan(cid, be)
    a, b, c = p["segments"][0], p["segments"][1], p["segments"][2]
    p = planner.edit_segment(b["id"], text="पहला नया वाक्य। दूसरा नया वाक्य।")
    nb = [s for s in p["segments"] if s["id"] == b["id"]][0]
    assert nb["status"] == "edited" and nb["rev"] == b["rev"] + 1 and len(nb["sentences"]) == 2
    assert [s for s in p["segments"] if s["id"] == a["id"]][0]["rev"] == a["rev"]       # others untouched
    planner.edit_segment(c["id"], locked=True)
    with pytest.raises(planner.PlanError):
        planner.edit_segment(c["id"], text="बदलाव।")
    planner.edit_segment(a["id"], status="approved")
    p = asyncio.run(planner.make_narration(p["id"], be))                                # regenerate everything
    ids = {s["id"] for s in p["segments"]}
    assert a["id"] in ids and c["id"] in ids and b["id"] not in ids                     # approved and locked kept; the rest replaced
    assert [s["beat"] for s in p["segments"]].count("b1") == 1


def test_non_devanagari_reply_is_retried_and_leaks_are_reported(env):
    pid, cid = approved_story(env)
    be = P2Fake(bad_script_once=True)
    p = planner.create_plan(cid, minutes=2)
    asyncio.run(planner.make_blueprint(p["id"], be))
    p = asyncio.run(planner.make_narration(p["id"], be, beat_ids=["b1"]))
    assert be.count("p2_narrate") == 2 and "сатдесят" not in p["segments"][0]["plain"]   # retried once with feedback
    bad = P2Fake(leak_text=" इस किताब के अनुसार")
    p2 = planner.create_plan(cid, minutes=2)
    asyncio.run(planner.make_blueprint(p2["id"], bad))
    asyncio.run(planner.make_narration(p2["id"], bad, beat_ids=["b1"]))
    rep = planner.validate_plan(p2["id"])
    assert not rep["ok"] and {i["kind"] for i in rep["issues"]} >= {"self_reference"}


def test_phase2_api_round_trip(tmp_path, monkeypatch):
    import config
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    with TestClient(main.app) as c:
        pid = projects.import_text(make_book(3, 8))
        run(pid, FakeBackend())
        cid = review.list_candidates(pid)[0]["id"]
        c.post("/login", data={"username": config.APP_USER, "password": config.APP_PASSWORD})
        assert c.post("/api/plans", json={"candidate_id": cid}).status_code == 400        # not approved yet
        review.update_candidate(cid, {"status": "approved"})
        p = c.post("/api/plans", json={"candidate_id": cid, "minutes": 3}).json()
        assert p["format"] == "16:9" and p["narrator"]["person"] == "first" and p["readiness"]["ready"]
        assert c.patch(f"/api/plans/{p['id']}/narrator", json={"name": "Aarav"}).json()["narrator"]["name"] == "Aarav"
        assert c.get(f"/api/plans/{p['id']}").json()["segments"] == []
        assert c.post(f"/api/plans/{p['id']}/narration").status_code == 400                # blueprint first
        assert c.post(f"/api/plans/{p['id']}/validate").status_code == 200
        assert len(c.get("/api/plans", params={"candidate_id": cid}).json()) == 1
