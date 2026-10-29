"""The whole v2 chain on the fake model: material, blueprint, narration (three passes), events, registry from the events, director with one shot per event, and scenes
that each show one event."""
import asyncio
import json
import re

from story.llm import LLMResult
from story2 import director, events, imgplan, planner, storyboard
from test_events import EvFake, word
from test_narration_v2 import ready
from test_phase2b import scene_json

DIST = [("wide", "high"), ("close", "low"), ("medium", "side"), ("extreme close", "eye level"), ("wide", "low"), ("medium", "high")]
MOVES = ["push in", "pan right", "pull back", "tilt up", "pan left", "tilt down", "drift"]


class ChainFake(EvFake):
    async def complete(self, messages, max_tokens, params=None):
        task = re.match(r"\[TASK:(\w+)\]", messages[0]["content"]).group(1)
        user = messages[1]["content"] if len(messages) > 1 else ""
        if task == "p2_registry":
            self.calls.append({"task": task, "user": user, "system": messages[0]["content"]})
            places = [{"name": f"Place {word(i)}", "kind": "place", "appearance": {"type": "lane", "signature": "three green doors"}, "description": "a lane", "fixed": ["green doors"]} for i in range(12)]
            people = [{"name": f"Person {word(i)}", "kind": "person", "appearance": {"gender": "man", "age": str(25 + i)}, "description": "a man", "fixed": ["a red scarf"]} for i in range(6)]
            return LLMResult(json.dumps({"assets": [{"name": "style", "kind": "style", "description": "painted"}] + places + people}))
        if task == "p2_director":
            self.calls.append({"task": task, "user": user, "system": messages[0]["content"]})
            n = int(re.search(r"Plan the film now: (\d+) segments", user).group(1))
            by = {int(m.group(1)): re.findall(r"(e\d+) \[", m.group(2)) for m in re.finditer(r"SEGMENT (\d+): (e\d+ \[.*)", user)}
            segs = []
            for i in range(1, n + 1):
                ids = by.get(i, [])
                shots = [{"focus": f"shot {k}", "kind": "object", "size": DIST[k % len(DIST)][0], "angle": DIST[k % len(DIST)][1], "move": MOVES[k % len(MOVES)], "why": "because", "event": eid} for k, eid in enumerate(ids)]
                segs.append({"segment": i, "emotion": "tense", "place": "Place " + word(0), "state": "the man is worried", "shots": shots})
            return LLMResult(json.dumps({"arc": "worry to relief", "segments": segs}))
        if task == "p2_scenes":
            self.calls.append({"task": task, "user": user, "system": messages[0]["content"]})
            rows = re.findall(r"^(e\d+): sentences (\d+)-(\d+) \|", user, re.M)
            scenes = []
            for k, (eid, a, b) in enumerate(rows):
                d, ang = DIST[k % len(DIST)]
                scenes.append(scene_json(int(a), int(b), subject=f"subject {word(k)} of the event", dist=d, angle=ang, event=eid, location=f"Place {word(k % 12)}",
                                         assets=[f"Place {word(k % 12)}", "style"], action=f"does something about {word(k + 40)}"))
            return LLMResult(json.dumps({"scenes": scenes}))
        return await super().complete(messages, max_tokens, params)


def test_events_drive_the_director_and_the_scenes(env):
    pid, be = ready(env)
    asyncio.run(planner.make_narration(pid, be))
    cf = ChainFake()
    asyncio.run(events.make_events(pid, cf))
    asyncio.run(storyboard.make_registry(pid, cf))
    p = planner.get_plan(pid)
    assert len([a for a in p["assets"] if a["kind"] == "place"]) == 12
    reg = next(c for c in cf.calls if c["task"] == "p2_registry")
    assert "THE EVENTS THE CAMERA WILL SEE" in reg["user"] and "THE WORLD OF THIS FILM" in reg["system"]
    p = asyncio.run(storyboard.make_storyboard(pid, cf))
    evs = events.of(p)
    assert director.current(p)
    for i, seg in enumerate(sorted(p["segments"], key=lambda s: s["seq"]), 1):
        mine = events.for_segment(p, seg["id"])
        shots = director.shots_for(p, i)
        assert [x["event"] for x in shots] == [e["id"] for e in mine]
        scs = sorted([s for s in p["scenes"] if s["segment_id"] == seg["id"]], key=lambda s: s["seq"])
        assert [s["data"]["event"] for s in scs] == [e["id"] for e in mine]
        assert [[s["s_from"], s["s_to"]] for s in scs] == [e["sentences"] if k < len(mine) - 1 else [e["sentences"][0], len(seg["sentences"])] for k, e in enumerate(mine)]
    assert len(p["scenes"]) == len(evs)


def test_a_shot_plan_made_for_other_events_is_not_current(env):
    pid, be = ready(env)
    asyncio.run(planner.make_narration(pid, be))
    cf = ChainFake()
    asyncio.run(events.make_events(pid, cf))
    asyncio.run(storyboard.make_registry(pid, cf))
    asyncio.run(storyboard.make_storyboard(pid, cf))
    assert director.current(planner.get_plan(pid))
    other = ChainFake()
    other.base = 5000                                                         # different places and actions for the first part
    asyncio.run(events.make_events(pid, other, segment_ids=[sorted(planner.get_plan(pid)["segments"], key=lambda s: s["seq"])[0]["id"]]))
    assert events.current(planner.get_plan(pid)) and not director.current(planner.get_plan(pid))


def test_without_events_the_old_storyboard_path_is_unchanged(env):
    from test_phase2b import boarded
    pid, cid, be, p = boarded(env)
    assert not events.current(p) and all(s["data"].get("event", "") == "" for s in p["scenes"])


def test_world_rules_are_reported_for_event_plans_only(env):
    pid, be = ready(env)
    asyncio.run(planner.make_narration(pid, be))
    cf = ChainFake()
    asyncio.run(events.make_events(pid, cf))
    asyncio.run(storyboard.make_registry(pid, cf))
    asyncio.run(storyboard.make_storyboard(pid, cf))
    rep = storyboard.validate_storyboard(pid)
    world = [i for i in rep["issues"] if i["kind"] == "world"]
    assert world and all(i["level"] == "warn" for i in world)                         # the fake film has few people and places per the targets: reported, never an error
    from test_phase2b import boarded
    _, _, _, p = boarded(env)
    assert not [i for i in storyboard.validate_storyboard(p["id"])["issues"] if i["kind"] == "world"]


def test_event_scenes_get_the_v2_prompt_without_negations_and_it_validates(env):
    from story2 import audit, imgprompts
    pid, be = ready(env)
    asyncio.run(planner.make_narration(pid, be))
    cf = ChainFake()
    asyncio.run(events.make_events(pid, cf))
    asyncio.run(storyboard.make_registry(pid, cf))
    asyncio.run(storyboard.make_storyboard(pid, cf))
    imgplan.compile_plan(pid)
    p = planner.get_plan(pid)
    prompts = [s["data"]["prompts"]["qwen"] for s in p["scenes"]]
    assert prompts and all(c.get("prompt_version") == "v2" for c in prompts)
    for c in prompts:
        assert not audit.NEG_RX.search(c["prompt"]) and "must not appear" not in c["prompt"] and "These must" not in c["prompt"]
        assert len(c["prompt"].split()) <= 200 and "Framed as a" in c["prompt"] and "Style:" in c["prompt"]
    assert audit.prompts(p)["prompts_with_negation"]["value"] == 0
    rep = imgplan.validate_prompts(pid)
    assert not [i for i in rep["issues"] if i["level"] == "error" and i["kind"] in ("exclusion", "style", "composition")]


def test_scenes_without_an_event_keep_the_old_prompt(env):
    from test_phase2b import boarded
    pid, cid, be, p = boarded(env)
    imgplan.compile_plan(p["id"])
    sc = planner.get_plan(p["id"])["scenes"][0]
    assert sc["data"]["prompts"]["qwen"].get("prompt_version") is None and "Constraints:" in sc["data"]["prompts"]["qwen"]["prompt"]
