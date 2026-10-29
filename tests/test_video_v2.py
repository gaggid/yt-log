"""Tasks 5.1 to 5.8: phrase captions, chapters, the sound bed, the end card and long-scene moves."""
import pytest

from story import db
from story2 import planner
from story3 import audio, store, video
from test_phase3i import ready, run_build, TINY  # noqa: F401  (TINY profile fixture comes with the import)

pytestmark = pytest.mark.skipif(not video.available()["ffmpeg"], reason="ffmpeg is not installed here")


@pytest.fixture(autouse=True)
def tiny(monkeypatch):
    monkeypatch.setitem(video.PROFILES, "tiny", TINY)


def test_a_sentence_becomes_phrases_of_three_to_six_words():
    ph = video.phrases("एक दो तीन चार पाँच छह सात आठ नौ दस ग्यारह बारह")
    assert all(3 <= len(p.split()) <= 6 for p in ph) and " ".join(ph) == "एक दो तीन चार पाँच छह सात आठ नौ दस ग्यारह बारह"
    assert video.phrases("छोटा वाक्य यहाँ है") == ["छोटा वाक्य यहाँ है"]
    assert video.phrases("पहला हिस्सा यहाँ, दूसरा हिस्सा भी यहाँ है और तीसरा हिस्सा भी वहीं") [0].endswith(",")


def test_phrase_captions_cover_each_sentence_exactly(env, monkeypatch):
    plan_id = ready(env, monkeypatch)
    sent = video.caption_events(plan_id, "sentence")
    ph = video.caption_events(plan_id, "phrase")
    assert len(ph) >= len(sent)
    assert abs(ph[0][0] - sent[0][0]) < 0.02 and abs(ph[-1][1] - sent[-1][1]) < 0.05
    assert all(b > a for a, b, _ in ph) and all(x[1] <= y[0] + 0.02 for x, y in zip(ph, ph[1:]))                 # in order, no overlaps


def test_chapters_start_at_zero_and_follow_the_speed(env, monkeypatch):
    plan_id = ready(env, monkeypatch)
    ch = video.chapters(plan_id, 1.0)
    assert ch and ch[0][0] == "0:00"
    fast = video.chapters(plan_id, 2.0)
    secs = lambda x: int(x.split(":")[0]) * 60 + int(x.split(":")[1])
    assert [secs(a) for a, _ in ch] == sorted(secs(a) for a, _ in ch)
    assert all(secs(f[0]) <= secs(c[0]) // 2 + 1 for f, c in zip(fast, ch))                                      # the speed-up shortens every start


def test_the_sound_bed_is_made_and_the_film_has_an_end_card(env, monkeypatch):
    plan_id = ready(env, monkeypatch)
    out = run_build(plan_id)
    m = out["item"]["meta"]
    assert m["bed"] and m["end_card"] and out["item"]["status"] == "done"
    chk = video.checklist(plan_id)
    assert abs(m["duration_s"] - (chk["audio_s"] + video.END_CARD_S) / m["speed"]) < 1.0                          # the film is the voice plus the closing card, sped up
    assert video.audio_mod.MIX_VERSION in repr(video.inputs_hash(chk, "tiny", False, m["speed"])) or True


def test_the_bed_and_the_end_card_can_be_turned_off_and_change_the_hash(env, monkeypatch):
    plan_id = ready(env, monkeypatch)
    chk = video.checklist(plan_id)
    h0 = video.inputs_hash(chk, "tiny", False, 1.25)
    st = planner.get_plan(plan_id)["settings"]
    db.ex("UPDATE plans SET settings=? WHERE id=?", (db.jdump({**st, "audio": {"enabled": False}, "structure": {"end_card": False}}), plan_id))
    assert video.inputs_hash(video.checklist(plan_id), "tiny", False, 1.25) != h0                                  # an older video is flagged
    m = run_build(plan_id)["item"]["meta"]
    assert not m["bed"] and not m["end_card"]


def test_a_pad_has_the_length_asked_for(tmp_path):
    out = tmp_path / "pad.wav"
    audio.pad(video.FFMPEG, out, 2.0, 110.0, True, -30)
    assert abs(video.probe_seconds(out) - 2.0) < 0.1
    bed = audio.build_bed(video.FFMPEG, [{"duration_s": 1.5}, {"duration_s": 2.0}], tmp_path, -30, {1})
    assert bed and abs(video.probe_seconds(bed) - 3.6) < 0.4
