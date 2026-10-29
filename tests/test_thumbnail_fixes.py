"""Audit task 1.10: the thumbnail's face is the film's main person, and words other than the headline fail the read-back."""
from story3 import thumbnail as th


def test_hero_line_names_gender_age_and_look():
    p = {"data": {"appearance": {"gender": "man", "age": "62", "build": "lean", "face": "weary eyes", "hair": "grey stubble"}}}
    s = th.hero_line(p)
    assert s.startswith("a 62-year-old man") and "lean" in s and "grey stubble" in s
    assert th.hero_line(None) == "one South Asian adult"
    assert th.hero_line({"data": {"appearance": {"gender": "woman"}}}) == "a woman"


def test_read_back_accepts_the_headline_alone_and_rejects_extra_words():
    assert th.read_back_ok("Hidden for 35 Years?", "HIDDEN FOR 35 YEARS?")
    assert th.read_back_ok("Hidden for 35 Years?", "Hidden for 35 Years? i")                # a stray letter is tolerated
    assert not th.read_back_ok("Hidden for 35 Years?", "Hidden for 35 Years? Hablia Monini")  # a garbled map label is not
    assert not th.read_back_ok("Hidden for 35 Years?", "")
    assert not th.read_back_ok("Hidden for 35 Years?", "Another headline")
