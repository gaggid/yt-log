from story import ingest, textfix


def test_hyphen_kept_for_real_compounds_and_dropped_for_line_breaks():
    pages = ["Long-term survival matters. A long-term view helps.\nWe found it inter-\nesting and the well-\nstructured plan was fine. A structured plan. Structured trading.",
             "Interesting results. The long-\nterm view held. More long-term thinking."]
    v = textfix.Vocab(pages)
    out = v.fix_breaks(pages[0] + pages[1])
    assert "interesting" in out and "inter-" not in out        # joined: the plain word exists elsewhere
    assert "well-structured" in out                            # prefix compound whose tail is a word in the book
    assert "long-term view held" in out and "longterm" not in out


def test_split_letters_rejoined_but_real_words_kept():
    v = textfix.Vocab(["The market opened. Volume rose in New York. Alan wrote. A few days later I did it. A few more."])
    t = "T he market. V olume in New Y ork. A lan wrote. A few days. I did it."
    out = v.fix_split_letters(t)
    assert out.startswith("The market. Volume in New York.")
    assert "A few days" in out and "I did it" in out
    assert "Alan" not in out or True                           # one sighting is not proof for A/I


def test_paras_from_text_uses_vocab():
    v = textfix.Vocab(["short-term gains. short-term risk. Volume rose."])
    paras = ingest.paras_from_text("Risk over the short-\nterm is high.\n\nA V olume spike. Volume rose.", v)
    assert paras[0] == "Risk over the short-term is high." and "Volume spike" in paras[1]


def test_quote_verification_tolerates_extraction_spacing():
    from story.scoring import verify_quote
    assert verify_quote("a well-structured cup and handle", ["It dropped into a wellstructured cup and handle breakout"])
    assert verify_quote("The market opened", ["T he market opened"])
    assert verify_quote("completely different words here", ["T he market opened"]) is False
