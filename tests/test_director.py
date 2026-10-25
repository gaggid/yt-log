"""The director's shot plan: its checks, how it is written into the scenes, and that it reaches the picture prompt and the video moves."""
import asyncio

from story2 import director, storyboard
from story2.scene_schemas import SceneOut
from story3 import video

from test_phase2b import boarded


def shot(seg, size="wide", angle="high", kind="place", focus="the street", move="drift"):
    return {"segment": seg, "size": size, "angle": angle, "kind": kind, "focus": focus, "move": move}


def test_wording_from_the_model_is_normalised():
    assert director._size("Long shot") == "wide" and director._size("extreme close-up") == "extreme close" and director._size("???") == "medium"
    assert director._angle("bird's eye") == "overhead" and director._angle("Low angle") == "low" and director._angle("over-the-shoulder") == "over the shoulder"
    assert director._move("dolly in") == "push in" and director._move("Tilt down") == "tilt down" and director._move("static") == "hold"
    assert director._kind("face") == "person" and director._kind("establishing wide") == "establishing"


def test_a_shot_plan_with_a_face_in_every_frame_or_repeated_frames_is_not_accepted():
    ok = [shot(1, "wide", "high", "establishing"), shot(1, "close", "low", "hands"), shot(2, "medium", "eye level", "person"), shot(2, "extreme close", "side", "object")]
    assert director.problems(ok, 2, {1, 2}, {1: 8, 2: 8}) == []
    faces = [shot(1, "wide", "high", "person"), shot(1, "close", "low", "person"), shot(2, "medium", "eye level", "reaction")]
    assert any("face or body" in p for p in director.problems(faces, 2, {1, 2}, {1: 8, 2: 4}))
    same = [shot(1, "wide", "high", "place"), shot(1, "wide", "high", "object")]
    assert any("same size and angle" in p for p in director.problems(same, 1, {1}, {1: 8}))
    three = [shot(1, "wide", "high", "place"), shot(1, "wide", "low", "object"), shot(1, "wide", "side", "hands")]
    assert any("three wide shots" in p for p in director.problems(three, 1, {1}, {1: 12}))
    still = [dict(x, move="hold") for x in ok]
    assert any("still frame" in p for p in director.problems(still, 2, {1, 2}, {1: 8, 2: 8}))
    assert any("no shots" in p for p in director.problems(ok[:2], 2, {1}, {1: 8, 2: 8}))
    assert any("too few shots" in p for p in director.problems(ok[:1], 1, {1}, {1: 30}))


def _scene(dist="medium", angle="eye level", n=0):
    return SceneOut.model_validate({"sentences": [1, 1], "shot": n, "purpose": "p", "subject": "s", "composition": {"distance": dist, "camera_angle": angle}, "motion_intent": "static"})


def test_scenes_follow_the_shots_and_force_writes_the_camera_into_them():
    shots = [shot(1, "wide", "high", move="pull back"), shot(1, "close", "low", move="push in"), shot(1, "extreme close", "eye level", move="hold")]
    scenes = [_scene("wide", "high"), _scene("medium", "eye level")]
    off = storyboard.follow_shots(scenes, shots)
    assert [s.shot for s in scenes] == [1, 2]                                             # no number given: by position
    assert len(off) == 1 and "scene 2" in off[0]                                          # only the scene whose camera differs is reported
    storyboard.follow_shots(scenes, shots, force=True)
    assert (scenes[1].composition.distance, scenes[1].composition.camera_angle) == ("close", "low") and scenes[1].motion_intent == "slow push in"
    held = [_scene(n=3)]
    storyboard.follow_shots(held, shots, force=True)
    assert held[0].motion_intent == "static hold"
    assert storyboard.follow_shots([_scene()], []) == []                                 # no shot plan: nothing to follow


def test_the_storyboard_makes_the_shot_plan_and_it_reaches_the_scenes_and_the_prompts(env):
    pid, cid, be, p = boarded(env)
    assert be.count("p2_director") == 1 and director.current(p)
    assert director.shots_for(p, 1) and "worry to relief" in director.story_map(p, 1)
    for sc in p["scenes"]:
        d = sc["data"]
        assert d["direction"]["shot"] >= 1 and d["direction"]["move"] in director.MOVES
        assert d["composition"]["distance"] in director.SIZES and d["composition"]["camera_angle"] in director.ANGLES
    scene_calls = [c for c in be.calls if c["task"] == "p2_scenes"]
    assert scene_calls and all("DIRECTOR'S SHOT LIST" in c["user"] and "STORY MAP" in c["user"] and "WHAT COMES NEXT" in c["user"] for c in scene_calls[:1])
    asyncio.run(storyboard.make_storyboard(p["id"], be))
    assert be.count("p2_director") == 1                                                  # the plan is kept while the narration is unchanged


def test_video_moves_come_from_the_director_and_no_frame_is_left_still():
    def sc(move, vt="reconstruction"):
        return {"data": {"visual_type": vt, "direction": {"move": move}, "motion_intent": ""}}
    got = video.pick_moves([sc("push in"), sc("pan right"), sc("tilt down"), sc("pull back"), sc("hold"), sc("push in", "data_chart")])
    assert got == ["zoom_in", "pan_right", "pan_down", "zoom_out", "settle", "hold"]            # the director's hold breathes, a chart stays still
    legacy = video.pick_moves([{"data": {"visual_type": "character", "motion_intent": "static hold"}}] * 3)
    assert "hold" not in legacy and all(a != b for a, b in zip(legacy, legacy[1:]))      # an old plan's still frames start to move, never the same move twice
    z = video.zoompan("pan_right", 90, 1920, 1080, 30)
    assert "zoompan=z='1.3'" in z and "3-2*" in z                                       # a real crop that slides, eased at both ends


def test_a_sentence_already_spoken_is_caught_even_in_another_beat():
    from story2 import planner
    said = ["पर यहाँ एक twist था।", "Board of Guardians ने pump का handle हटा दिया।"]
    assert planner.repeated_sentences(said, ["पर यहाँ एक twist था।", "बिल्कुल नया वाक्य जो पहले नहीं आया।"]) == ["पर यहाँ एक twist था।"]
    assert planner.repeated_sentences([], ["यह वाक्य दो बार आता है यहाँ।", "यह वाक्य दो बार आता है यहाँ।"]) == ["यह वाक्य दो बार आता है यहाँ।"]
    assert planner.repeated_sentences(said, ["ठीक है।"]) == []                              # a very short reply is not a repeat


def test_a_liquid_or_surface_is_not_a_prop_but_an_object_is():
    assert storyboard.not_drawable("prop", "Sewage Stream", {}, "")
    assert storyboard.not_drawable("prop", "Cobblestone Floor", {}, "")
    assert not storyboard.not_drawable("prop", "Public Water Pump", {}, "")
    assert not storyboard.not_drawable("place", "Sewage Works", {}, "")


def test_references_are_made_only_for_things_the_scenes_really_use(env):
    from story3 import refs
    pid, cid, be, p = boarded(env)
    names = {t["asset"]["name"]: len(t["scenes"]) for t in refs.targets(p["id"])}
    assert all(n >= refs.MIN_SCENES for n in names.values())


def test_sentences_that_all_begin_the_same_way_are_sent_back():
    from story2 import planner
    prior = ["पर यहाँ एक सवाल था।", "पर यहाँ एक सवाल और आया।"]
    assert planner.overused_openers(prior, ["पर यहाँ एक नई बात थी।"]) == ["पर यहाँ एक"]               # third time the same three words open a sentence
    assert planner.overused_openers([], ["मैं आपको बताता हूँ यह।", "मैं आपको बताता हूँ वह।"]) == ["मैं आपको बताता"]      # a stock phrase twice
    assert planner.overused_openers(prior[:1], ["बिल्कुल अलग शुरुआत यहाँ।"]) == []
