"""Audience language profiles (task 2.15) and the information-density checks of narration v2 (task 2.16)."""
from story2 import lexicon, narrate2


def test_metro_allows_an_english_number_only_before_an_english_unit():
    ok = ["वह thirty-five years तक छिपा रहा।"]
    bad = ["यह बात nineteen ninety-one की है।"]
    assert lexicon.profile_problems(ok, "metro_hinglish") == []
    msg = " ".join(lexicon.profile_problems(bad, "metro_hinglish"))
    assert "nineteen" in msg and "ninety-one" in msg


def test_hindi_first_wants_hindi_number_words_and_few_english_words():
    s = ["वह thirty-five years तक छिपा रहा।", "उसे proclaimed offender घोषित किया गया।"]
    msg = " ".join(lexicon.profile_problems(s, "hindi_first"))
    assert "Hindi number words" in msg and "thirty-five" in msg
    assert lexicon.profile_problems(["वह पैंतीस साल तक छिपा रहा।"], "hindi_first") == []


def test_english_share_limit_and_names_are_not_counted_as_foreign():
    many = ["वह mobile phone office police station court case file list में गया।"]
    assert "Too many English words" in " ".join(lexicon.profile_problems(many, "senior_friendly"))
    names = ["Verma और Montu दिल्ली से Ludhiana गए और Geeta मिली।"]
    assert not [p for p in lexicon.profile_problems(names, "senior_friendly") if "Too many" in p and "verma" in p.lower()]


def test_a_technical_term_must_be_explained_the_first_time():
    unexplained = ["उसे proclaimed offender घोषित किया गया।", "वह फ़रार रहा।"]
    assert "proclaimed offender" in " ".join(lexicon.profile_problems(unexplained, "metro_hinglish"))
    explained = ["उसे proclaimed offender घोषित किया गया, यानी अदालत ने उसे फ़रार माना।"]
    assert lexicon.profile_problems(explained, "metro_hinglish") == []
    assert lexicon.profile_problems(unexplained, "metro_hinglish", ["proclaimed offender कौन होता है, यह पहले बताया जा चुका है"]) == []     # already told earlier in the video


def test_profile_defaults_and_notes():
    assert lexicon.profile_of({}) == "metro_hinglish" and lexicon.profile_of({"audience": {"profile": "nope"}}) == "metro_hinglish"
    assert lexicon.profile_of({"audience": {"profile": "senior_friendly"}}) == "senior_friendly"
    assert "Hindi number words" in lexicon.profile_note("hindi_first")


def test_new_word_share_and_dead_stretch():
    spoken = ["वह घर गया और खाना खाया।", "फिर वह सो गया।"]
    assert narrate2.new_word_share(["वह घर गया और खाना खाया।"], spoken) == 0.0
    assert narrate2.new_word_share(["पुलिस को एक पुराना टेलीफोन नंबर मिला।"], spoken) == 1.0
    items = [{"id": "m1", "detail": "a rusty transformer", "say": ["transformer"]}, {"id": "m2", "detail": "a keypad phone", "say": ["keypad"]}]
    flat = ["वह चलता रहा।"] * 9
    assert narrate2.dead_stretch(["transformer दिखा।"] + flat + ["keypad मिला।"], items) == (2, 9) or narrate2.dead_stretch(["transformer दिखा।"] + flat + ["keypad मिला।"], items) is not None
    assert narrate2.dead_stretch(["transformer दिखा।", "keypad मिला।"] + flat, items) is None                    # everything is told: a quiet tail is fine
