"""Safety rules in code: no cheerful voice and no smiling face over a death or an injury."""
from story2 import mood, safety
from types import SimpleNamespace as NS


def test_grave_detects_hindi_and_english_whole_words_only():
    assert safety.grave("उसने Geeta Suri को मार दिया.")
    assert safety.grave("the victim was killed")
    assert safety.grave("उसकी मौत हो गई")
    assert not safety.grave("मरम्मत का काम चल रहा था")                        # a longer word that contains मर is not a death
    assert not safety.grave("वह खुश था और सब ठीक था")


def test_cheerful_tags_are_replaced_over_a_death():
    assert safety.guard_tag("happy", "उसने उसे मार दिया") == "serious"
    assert safety.guard_tag("cheerful", "उसकी मौत हो गई") == "sad"
    assert safety.guard_tag("happy", "आज धूप खिली थी") == "happy"             # nothing grave: untouched
    assert safety.guard_tag("sad", "उसकी मौत हो गई") == "sad"


def test_tag_lasts_so_the_sentence_after_a_killing_is_guarded_too():
    sents = [{"text": "उसने Geeta को मार दिया.", "tag": "serious"}, {"text": "फिर सब शांत हो गया.", "tag": "cheerful"}, {"text": "सुबह हुई.", "tag": "happy"}]
    n = safety.guard_tags(sents)
    assert sents[1]["tag"] == "serious" and sents[2]["tag"] == "happy" and n == 1


def test_smiles_are_scrubbed_from_a_scene_over_grave_narration():
    sc = NS(subject="Geeta Suri's face", action="Her eyes are closed, a slight, peaceful smile on her lips.", translation="A close-up of Geeta, calm and smiling.")
    changed = safety.scrub_scene(sc, "उसने Geeta Suri को मार दिया.")
    assert "action" in changed and "smile" not in sc.action.lower() and "still, unreadable face" in sc.action
    assert "smiling" not in sc.translation.lower()


def test_scene_over_ordinary_narration_is_left_alone():
    sc = NS(subject="x", action="She smiles at the child.")
    assert safety.scrub_scene(sc, "बच्चे ने खेल जीता.") == [] and "smiles" in sc.action


def test_a_glad_feeling_becomes_sorrow_over_grave_narration():
    assert mood.label(["hopeful", mood.GRAVE_MARK]) == "sorrow"
    assert mood.label(["relief and joy", mood.GRAVE_MARK]) == "sorrow"
    assert mood.label(["fear", mood.GRAVE_MARK]) == "fear"
    assert mood.label(["hopeful"]) == "hope"
    assert "smile" not in mood.line(["hopeful", mood.GRAVE_MARK])


def test_a_crime_word_at_the_end_of_a_sentence_is_still_found_before_the_danda():
    """Found with the real narration: every sentence ends in a danda, and the word-boundary rule counted the danda as part of the word."""
    assert safety.accusations(["उसने उसे मार डाला।"]) and safety.grave("उसने उसे मार डाला।") and safety.loss("वह मर गया।")
    assert not safety.accusations(["पुलिस के मुताबिक उसने उसे मार डाला।"])
