"""Task 3.13: the era table, era look in prompts, the clip grade and the year label."""
import subprocess

from story2 import era
from story3 import video


def test_things_that_did_not_exist_yet_are_found():
    assert era.problems("a man holds a smartphone near the lane", 1991) and "smartphone" in era.problems("a man holds a smartphone near the lane", 1991)[0]
    assert era.problems("a man holds a mobile phone", 1991) and not era.problems("a man holds a mobile phone", 2005)
    assert era.problems("UPI QR code sticker on the counter", 2012) and not era.problems("UPI QR code sticker on the counter", 2019)
    assert not era.problems("a black rotary phone on a desk", 1985) and not era.problems("anything at all", None) and not era.problems("smartphone", 9999)


def test_rare_objects_are_a_warning_and_the_story_can_contradict_the_picture():
    assert era.suspects("a CCTV camera above the lane", 1999) and not era.suspects("a CCTV camera", 2015)
    assert era.conflicts_with_story("he checks a smartphone", "he had only a keypad phone and a beedi", 2020)
    assert not era.conflicts_with_story("he checks a keypad phone", "he had only a keypad phone", 2020)


def test_years_come_from_the_period_phrase():
    assert era.year_of("August 1991") == 1991 and era.year_of("present day") == era.NOW and era.year_of("") is None and era.year_of("a long time ago") is None


def test_each_time_has_a_look_a_grade_and_props():
    assert "grain" in era.look(1991) and era.look(2020) == "" and era.look(None) == ""
    assert "noise" in era.grade(1975) and "noise" in era.grade(1995) and era.grade(2020) == "" and era.grade(9999) == ""
    assert "rotary" in era.props_for(1985) and "smartphone" in era.props_for(2020)


def test_the_year_label_goes_where_the_film_jumps_in_time():
    assert era.jumps([1991, 1991, None, 2012, 2012, 9999, None]) == [3, 5]
    assert era.jumps([None, None]) == [] and era.jumps([2000, 2000]) == []


def test_a_graded_clip_with_a_year_label_is_made(tmp_path):
    img = tmp_path / "a.png"
    from PIL import Image
    Image.new("RGB", (320, 180), (120, 90, 60)).save(img)
    out = tmp_path / "c.mp4"
    prof = {"size": (320, 180), "fps": 10, "preset": "ultrafast", "crf": 30}
    video.render_clip(img, out, 12, "drift", prof, False, era.grade(1991), "1991")
    assert out.is_file() and out.stat().st_size > 0


def test_words_on_a_wall_must_come_from_the_story_unless_the_object_is_needed():
    from types import SimpleNamespace
    from story2 import safety
    from story2.scene_schemas import OnScreen
    sc = SimpleNamespace(text_on_screen=[OnScreen(text="FAKE"), OnScreen(text="1930")], subject="an office wall", action="", foreground="", middle="", background="", props=[])
    gone = safety.scrub_text(sc, "the office of the company; the founder joined in 1991")
    assert gone == ["FAKE", "1930"] and sc.text_on_screen == []
    sc = SimpleNamespace(text_on_screen=[OnScreen(text="Sunrise Traders"), OnScreen(text="1991")], subject="a name board outside a shop", action="", foreground="", middle="", background="", props=[])
    assert safety.scrub_text(sc, "irrelevant facts") == ["1991"] and [e.text for e in sc.text_on_screen] == ["Sunrise Traders"]       # a name board is a story object; one text only
    sc = SimpleNamespace(text_on_screen=[OnScreen(text="Police Station")], subject="a lane", action="", foreground="", middle="", background="", props=[])
    assert safety.scrub_text(sc, "") == [] and sc.text_on_screen[0].text == "Police Station"                                   # ordinary sign words are fine


def test_an_explainer_with_mostly_metaphors_is_sent_back_and_the_bank_is_offered():
    from types import SimpleNamespace
    from story2 import analogies, storyboard

    def sc(vt, n):
        return SimpleNamespace(visual_type=vt, subject=f"s{n}", assets=["Shop"], location="Shop", action="a", foreground="", middle="", background="", props=[], period="")
    assets = [{"kind": "place", "name": "Shop"}, {"kind": "person", "name": "Ram"}]
    scenes = [sc("metaphor", 1), sc("metaphor", 2), sc("atmospheric", 3), sc("atmospheric", 4)]
    assert any("metaphors" in p for p in storyboard.scene_problems(scenes, assets, "explainer"))
    assert not any("metaphors" in p for p in storyboard.scene_problems(scenes, assets, "incident"))
    n = analogies.note()
    assert "kirana" in n.lower() and "never as a diagram in empty space" in n and len(analogies.BANK) >= 10


def test_the_same_person_in_the_same_place_seen_the_same_way_twice_is_sent_back():
    from types import SimpleNamespace
    from story2 import storyboard
    from story2.scene_schemas import Compose

    def sc(n, dist):
        return SimpleNamespace(visual_type="person", subject=f"s{n}", assets=["Ram", "Shop"], location="Shop", action="a", foreground="", middle="", background="", props=[], period="",
                               composition=Compose(distance=dist, camera_angle="eye level"))
    assets = [{"kind": "place", "name": "Shop"}, {"kind": "person", "name": "Ram"}, {"kind": "place", "name": "Lane"}]
    assert any("repeats scene 1" in p for p in storyboard.scene_problems([sc(1, "close"), sc(2, "close")], assets))
    assert not any("repeats" in p for p in storyboard.scene_problems([sc(1, "close"), sc(2, "wide")], assets))
