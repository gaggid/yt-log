import pytest

from story import settings as settings_mod
from story.chunker import build_chunks
from story.tokens import Budget, BudgetExceeded, estimate, pack


def test_estimate_scripts():
    assert estimate("") == 0
    assert estimate("a" * 350) < estimate("नमस्ते दुनिया " * 25)             # non-latin costs more per char


def test_budget_math_and_check():
    b = Budget(context=32768, output_reserve=6000, safety=0.10)
    assert b.usable == 29491
    assert b.input_limit(1000) == 29491 - 6000 - 1000
    b.check(b.input_limit())                                                 # exactly fits
    with pytest.raises(BudgetExceeded):
        b.check(b.input_limit() + 1)
    assert b.chunk_target(9000, 1500) == 9000
    assert b.chunk_target(50000, 1500) == b.input_limit(1500)                # clamped, never above the window
    assert b.warnings(50000, 1500)


def test_pack_never_truncates():
    assert pack([5, 5, 5, 5], 10) == [[0, 1], [2, 3]]
    with pytest.raises(BudgetExceeded):
        pack([5, 50], 10)


def test_settings_validation(env):
    s = settings_mod.update({"context_limit": 65536, "chunk_tokens": 12000})
    assert s["context_limit"] == 65536
    for bad in ({"context_limit": 1000}, {"output_reserve": 60000}, {"chunk_overlap": 99999},
                {"nope": 1}, {"weights": {"hook": 1}}, {"safety_margin": 0.9}):
        with pytest.raises(settings_mod.SettingsError):
            settings_mod.update(bad)


def paras(n, chars, chapters_every=0):
    return [{"idx": i + 1, "chapter_idx": (i // chapters_every + 1) if chapters_every else 1,
             "text": ("word " * (chars // 5)).strip() + f" end{i}."} for i in range(n)]


def test_chunks_cover_every_paragraph_once_within_budget():
    est = estimate
    ps = paras(300, 1200, chapters_every=40)
    chunks = build_chunks(ps, target_tokens=2000, overlap_tokens=300, est=est)
    seen = [i for c in chunks for i, _, _ in c.items]
    assert sorted(set(seen)) == [p["idx"] for p in ps]                       # nothing dropped
    assert len(seen) == len(set(seen))                                       # nothing duplicated in main items
    by = {p["idx"]: p for p in ps}
    for c in chunks:
        main = sum(est(by[i]["text"]) + 4 for i, _, _ in c.items)
        assert main <= 2000
        assert c.tokens <= 2000 + 300
    for c in chunks[1:]:                                                     # context never crosses a chapter boundary
        first_ch = by[c.items[0][0]]["chapter_idx"]
        assert all(by[i]["chapter_idx"] == first_ch for i, _, _ in c.context)


def test_oversized_paragraph_is_sliced_not_cut():
    est = estimate
    big = " ".join(f"Sentence number {i} is here." for i in range(1500))
    ps = [{"idx": 1, "chapter_idx": 1, "text": "Intro paragraph."}, {"idx": 2, "chapter_idx": 1, "text": big},
          {"idx": 3, "chapter_idx": 1, "text": "Outro paragraph."}]
    chunks = build_chunks(ps, target_tokens=1500, overlap_tokens=0, est=est)
    pieces = sorted((a, b) for c in chunks for i, a, b in c.items if i == 2)
    assert len(pieces) > 1
    pos = 0
    for a, b in pieces:                                                      # slices tile the paragraph exactly
        assert a == pos or a - pos <= 1
        pos = len(big) if b == -1 else b
    assert pos == len(big)
    for c in chunks:
        assert sum(est(ps[i - 1]["text"][a:(None if b == -1 else b)]) + 4 for i, a, b in c.items) <= 1500


def test_tiny_chapters_are_batched():
    ps = [{"idx": i + 1, "chapter_idx": i + 1, "text": "Short chapter body text here."} for i in range(10)]
    chunks = build_chunks(ps, target_tokens=2000, overlap_tokens=0, est=estimate)
    assert len(chunks) == 1 and chunks[0].chapter_idxs == list(range(1, 11))
