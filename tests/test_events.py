"""The visual events ledger (task 3.1): what the camera sees, planned per narration part from the story details."""
import asyncio
import json
import re

from story.llm import LLMResult
from story2 import events, planner
from test_narration_v2 import NFake, ready


def ev(a, b, where="a rooftop room with a tin door", doing="a man counts notes on a cot", kind="hands", ledger=("m1",), who=()):
    return {"sentences": [a, b], "kind": kind, "who": list(who), "where": where, "doing": doing, "key_object": "", "ledger": list(ledger), "reveal": False, "clue": False}


def test_problems_flag_uncovered_long_repeated_and_face_heavy_events():
    secs = [3.0] * 6
    good = [ev(1, 2, "a tea stall by the gate", "a boy pours chai into glasses"), ev(3, 4, "a railway platform with a yellow clock", "a man checks a ticket", kind="object"), ev(5, 6, "a courtyard with a well", "women fill steel pots", kind="place")]
    assert events.problems(good, secs, [], {"m1"}) == []
    msgs = " | ".join(events.problems([ev(1, 5)], secs, [], {"m1"}))
    assert "plays for 15 s" in msgs and "sentences with no event: 6" in msgs
    rep = [ev(1, 2), ev(3, 4, "a rooftop room with a tin door", "a man counts notes on a cot"), ev(5, 6, "another place", "something else happens here")]
    assert "shows the same thing" in " | ".join(events.problems(rep, secs, [], {"m1"}))
    run = [ev(1, 2, "the main bazaar lane", "a cart passes"), ev(3, 4, "the main bazaar lane", "a dog sleeps"), ev(5, 6, "the main bazaar lane", "a shutter rolls down")]
    assert "in a row are in the same place" in " | ".join(events.problems(run, secs, [], {"m1"}))
    faces = [ev(1, 2, "lane one", "a man looks up", kind="person"), ev(3, 4, "lane two", "a woman turns around", kind="reaction"), ev(5, 6, "lane three", "a boy stares ahead", kind="person")]
    assert "are faces" in " | ".join(events.problems(faces, secs, [], {"m1"}))
    bare = [ev(1, 2, "lane one", "a cart passes by", ledger=()), ev(3, 4, "lane two", "a dog sleeps there", ledger=()), ev(5, 6, "lane three", "a shutter rolls down", ledger=())]
    assert "not grounded" in " | ".join(events.problems(bare, secs, [], {"m1"}))


def test_earlier_events_count_as_repeats():
    earlier = [{"where": "a rooftop room with a tin door", "doing": "a man counts notes on a cot", "key_object": "", "who": []}]
    assert "shows the same thing" in " | ".join(events.problems([ev(1, 1)], [3.0], earlier, {"m1"}))


def test_ranges_are_repaired_to_cover_every_sentence():
    fixed = events.repair_ranges([ev(2, 3), ev(3, 5)], 6)
    assert [e["sentences"] for e in fixed] == [[1, 3], [4, 6]] or fixed[0]["sentences"][0] == 1 and fixed[-1]["sentences"][1] == 6


def word(i):
    """A distinct letters-only word for each number (the checks compare words made of letters)."""
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(97 + r) * 2 + s
    return s


class EvFake(NFake):
    async def complete(self, messages, max_tokens, params=None):
        task = re.match(r"\[TASK:(\w+)\]", messages[0]["content"]).group(1)
        if task != "p2_events":
            return await super().complete(messages, max_tokens, params)
        user = messages[1]["content"]
        self.calls.append({"task": task, "user": user})
        n = len(re.findall(r"^\d+\. \(", user, re.M))
        ids = re.findall(r"\bm\d+\b", user.split("OTHER STORY DETAILS")[0])
        out, i = [], 1
        while i <= n:
            j = min(n, i + 1)
            k = len(out)
            out.append({"sentences": [i, j], "kind": ["hands", "place", "object"][k % 3], "who": [], "where": f"place {word(3 * (self.base + k))} with {word(3 * (self.base + k) + 1)} gate",
                        "doing": f"a {word(3 * (self.base + k) + 2)} moves near the {word(3 * (self.base + k) + 900)}", "ledger": [ids[k % len(ids)]], "reveal": k == 0, "clue": False})
            i = j + 1
        self.base += len(out)
        return LLMResult(json.dumps({"events": out}))

    base = 100


def test_events_are_made_for_every_part_and_kept_in_order(env):
    pid, be = ready(env)
    be2 = EvFake()
    asyncio.run(planner.make_narration(pid, be))
    p = asyncio.run(events.make_events(pid, be2))
    evs = events.of(p)
    segs = sorted(p["segments"], key=lambda s: s["seq"])
    assert len(evs) >= len(segs) * 3 and [e["id"] for e in evs][:3] == ["e1", "e2", "e3"]
    for seg in segs:
        mine = events.for_segment(p, seg["id"])
        assert mine[0]["sentences"][0] == 1 and mine[-1]["sentences"][1] == len(seg["sentences"])
        assert all(a["sentences"][1] + 1 == b["sentences"][0] for a, b in zip(mine, mine[1:]))
    assert events.current(p)
    assert all(e["ledger"] == [x for x in e["ledger"] if x.startswith("m")] for e in evs)
    first_user = next(c for c in be2.calls if c["task"] == "p2_events")["user"]
    assert "PLACES USED SO FAR" in first_user and "STORY DETAILS FOR THIS PART" in first_user
    later = [c for c in be2.calls if c["task"] == "p2_events"][1]["user"]
    assert "place " + word(300) in later                                                # the second part is told which places the first one used


def test_a_single_part_can_be_redone_and_the_others_are_kept(env):
    pid, be = ready(env)
    be2 = EvFake()
    asyncio.run(planner.make_narration(pid, be))
    p = asyncio.run(events.make_events(pid, be2))
    segs = sorted(p["segments"], key=lambda s: s["seq"])
    keep = [e["doing"] for e in events.for_segment(p, segs[0]["id"])]
    p2 = asyncio.run(events.make_events(pid, be2, segment_ids=[segs[2]["id"]]))
    assert [e["doing"] for e in events.for_segment(p2, segs[0]["id"])] == keep
    assert len(events.of(p2)) == len(events.of(p))


def test_events_need_the_narration_and_the_pack(env):
    from story2.planner import PlanError
    from test_material import planned
    plan, _ = planned(env)
    try:
        asyncio.run(events.make_events(plan["id"], EvFake()))
    except PlanError as e:
        assert "narration" in str(e)
    else:
        raise AssertionError("no narration, no events")
