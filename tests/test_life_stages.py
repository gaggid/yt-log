"""Task 3.6 (ages): a person shown at two ages is drawn at the age of the scene's year."""
from story2 import describe, imgprompts as ip


def asset(stages=None):
    return {"id": "a1", "kind": "person", "name": "Verma", "data": {"description": "a 62 years old lean man", "appearance": {"gender": "man", "age": "62", "build": "lean", "hair": "grey stubble", "top": "cream shirt"},
                                                                   "life_stages": stages if stages is not None else [
                                                                       {"from_year": 1991, "to_year": 1996, "age": 27, "look_changes": "black hair, a thin moustache, a clean shirt"},
                                                                       {"from_year": 1997, "to_year": None, "age": 62, "look_changes": "grey stubble and a worn face"}]}}


def test_stage_for_picks_the_stage_of_the_year():
    a = asset()
    assert describe.stage_for(a, 1991)["age"] == 27 and describe.stage_for(a, 2010)["age"] == 62
    assert describe.stage_for(a, 9999)["age"] == 62                              # "now" is the last stage
    assert describe.stage_for(a, 1980)["age"] == 27                              # before the first stage: the first
    assert describe.stage_for(a, None) is None and describe.stage_for(asset([]), 1991) is None


def test_person_view_uses_the_stage_age_and_look_changes():
    det_then, _ = describe.person_view(asset(), False, frozenset(), 1991)
    det_now, _ = describe.person_view(asset(), False, frozenset(), 9999)
    assert "27 years old" in det_then and "thin moustache" in det_then and "62" not in det_then
    assert "62 years old" in det_now and "worn face" in det_now
    det_none, _ = describe.person_view(asset(), False, frozenset())
    assert "62 years old" in det_none                                              # no year: the base appearance (the age in the main period)


def test_scene_year_reads_the_period():
    f = lambda p: ip.scene_year({"setting": {"period": p}})
    assert f("August 2, 1991") == 1991 and f("Present day") == 9999 and f("") is None and f("a long time ago") is None


def test_the_picture_prompt_draws_the_age_of_the_scene():
    from story2 import imgprompts
    d = {"subject": "Verma", "setting": {"location": "a rented room", "period": "1991"}, "composition": {"distance": "medium"}}
    out = imgprompts._subject_text(d, [asset()], False, None, [])
    assert "27 years old" in out
    d["setting"]["period"] = "present day"
    assert "62 years old" in imgprompts._subject_text(d, [asset()], False, None, [])
