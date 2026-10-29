"""Task 1.1: the last beat never ends on an English teaser; the next-video hook is used only when it is Hinglish and a series follows."""
from story2 import planner


def test_only_the_last_beat_gets_an_ending_rule():
    assert planner.closing({"next_hook": "x"}, False) == ""
    assert "answer the video's central question" in planner.closing({}, True)


def test_english_hook_is_never_added():
    bp = {"next_hook": "If a man can hide for years, what happens next?", "series_placement": "The Invisible Fugitives"}
    assert "plant the next story" not in planner.closing(bp, True)


def test_hook_without_a_series_is_not_added():
    assert "plant the next story" not in planner.closing({"next_hook": "अगली कहानी और भी अजीब है।", "series_placement": ""}, True)


def test_hinglish_hook_with_a_series_is_added():
    out = planner.closing({"next_hook": "अगली कहानी और भी अजीब है।", "series_placement": "Series name"}, True)
    assert "plant the next story" in out and "अगली कहानी" in out
