"""A detail the shot cannot see (shoes in a waist-up frame) must not be forced into the prompt: the picture model draws it anyway, legs and all."""
from story2 import describe, imgprompts

AP = {"gender": "man", "age": "45", "build": "heavy", "skin": "wheatish", "face": "round face", "hair": "grey, short", "eyes": "brown",
      "top": "white cotton shirt", "bottom": "grey trousers", "footwear": "brown leather loafers", "accessories": "none", "expression": "tired"}


def person():
    return {"id": "a1", "name": "Mehta", "kind": "person", "rev": 1,
            "data": {"appearance": AP, "description": describe.describe("person", AP), "fixed": describe.fixed_from("person", AP)}}


def scene(distance, subject="Mehta at work", action="Mehta looks up"):
    return {"id": "s1", "rev": 1, "data": {"subject": subject, "action": action, "composition": {"distance": distance}}}


def test_hidden_slots_follow_the_shot_size_and_posture():
    assert describe.hidden_slots("wide") == {"eyes", "expression"}                       # faces are a few pixels in a wide shot
    assert describe.hidden_slots("medium wide") == {"footwear"}
    assert describe.hidden_slots("medium") == {"bottom", "footwear"}
    assert describe.hidden_slots("close-up") == {"bottom", "footwear"}
    assert describe.hidden_slots("wide", "a man seated behind a desk") == {"bottom", "footwear", "eyes", "expression"}
    assert "top" in describe.hidden_slots("extreme close-up")


def test_a_medium_shot_prompt_leaves_out_shoes_and_says_the_frame_cuts_them_off():
    t = imgprompts._subject_text(scene("medium")["data"], [person()])
    assert "loafers" not in t and "grey trousers" not in t and "white cotton shirt" in t and "no shoes or trousers are visible" in t


def test_a_wide_standing_shot_keeps_the_shoes():
    t = imgprompts._subject_text(scene("wide")["data"], [person()])
    assert "brown leather loafers" in t and "cuts the people off" not in t


def test_seated_man_in_a_wide_shot_has_no_shoes_either():
    t = imgprompts._subject_text(scene("wide", action="Mehta sits behind a desk")["data"], [person()])
    assert "loafers" not in t


def test_the_validator_does_not_demand_hidden_details():
    from story2.imgprompts import validate_prompt, compile_qwen
    # hidden fixed lines are skipped by the continuity check
    hide = describe.hidden_slots("medium")
    assert all(describe.is_hidden(f, hide) for f in person()["data"]["fixed"] if f.startswith(("bottom", "footwear")))


def test_a_person_seen_from_behind_or_only_by_the_hands_shows_no_face_detail():
    assert {"face", "eyes", "expression"} <= describe.hidden_slots("medium", "Mehta seen from behind at the window")
    assert {"face", "hair", "expression"} <= describe.hidden_slots("close-up", "close on the hands of Mehta")
    assert "face" in describe.hidden_slots("extreme wide")


def test_a_close_shot_does_not_list_the_layout_of_a_place():
    assert describe.hidden_place_slots("close-up") == set(describe.PLACE_CLOSE) and describe.hidden_place_slots("wide") == set()
    a = {"kind": "place", "data": {"fixed": ["signature: three brass lamps", "materials: teak", "objects: ten desks"]}}
    assert imgprompts._place_fixed(a, {"composition": {"distance": "close-up"}}) == ["materials: teak"]
    assert len(imgprompts._place_fixed(a, {"composition": {"distance": "wide"}})) == 3
    b = {"kind": "place", "data": {"fixed": ["light: soft evening lamp", "materials: teak"]}}
    assert imgprompts._place_fixed(b, {"composition": {"distance": "wide"}}) == ["materials: teak"]       # the scene has its own lighting


def test_the_feeling_becomes_visible_cues_and_drops_the_face_when_it_is_hidden():
    from story2 import mood
    assert mood.label(["a feeling of dread"]) == "fear" and mood.label(["", "calm"]) == "" and mood.label(["quiet relief", "sorrow"]) == "joy"
    full = mood.line(["dread"], set())
    assert "Feeling of the moment: fear." in full and "eyes wide" in full and "shoulders drawn up" in full and "cold hard side light" in full
    wide = mood.line(["dread"], {"eyes", "expression"})
    assert "eyes wide" not in wide and "shoulders drawn up" in wide
    assert mood.line(["dread"], set(), people=False).endswith("cold hard side light with deep shadow.") and "eyes" not in mood.line(["dread"], set(), people=False)
    assert mood.line([], set()) == ""
    vague = [w for w in imgprompts.VAGUE if any(w in x for row in mood.CUES for x in (row[0], *row[2:]))]
    assert not vague, vague                                                                         # the prompt validator warns on vague words


def test_the_prompt_carries_the_feeling_and_it_moves_the_source_hash():
    sc = {"id": "s1", "rev": 1, "segment_id": "g1", "data": {"subject": "Mehta at work", "action": "Mehta looks up", "composition": {"distance": "medium"},
                                                             "narrative": {"emotional_effect": "growing dread"}, "output": {"width": 1344, "height": 768, "aspect_ratio": "16:9"}}}
    plan = {"settings": {"director": {"by_segment": {"1": {"segment_id": "g1", "emotion": "relief"}}}}}
    assert imgprompts.feeling_texts(sc, plan) == ["growing dread", "relief"]
    h0 = imgprompts.source_hash(sc, [], "16:9")
    assert imgprompts.source_hash(sc, [], "16:9", False, "fear") != h0
