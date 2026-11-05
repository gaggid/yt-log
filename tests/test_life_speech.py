"""Virtual life speech: the Maya request for a spoken thought, and the wait-and-retry when the model is unavailable."""
import asyncio

import pytest

from characters import brain, speech, studio
from story2 import voices
from story3.voice import MediaError


def test_request_is_the_fixed_female_voice_with_the_tag_in_front():
    body = speech.request("Arre yaar, finally chai ban gayi.", "happy")
    assert body["model"] == "maya-tts" and body["voice"] == speech.VOICE
    assert voices.ENGINES["maya-tts"]["voices"][speech.VOICE] == "female"
    assert body["input"] == "[happy] Arre yaar, finally chai ban gayi." and body["language"] == "en"


def test_neutral_unknown_tag_and_devanagari():
    assert speech.request("Good morning.", "neutral")["input"] == "Good morning."
    assert speech.request("Good morning.", "gibberish")["input"] == "Good morning."
    assert speech.request("आज बहुत थकान है", "tired")["language"] == "hi"


def test_a_long_line_is_cut_and_an_empty_one_refused():
    long = " ".join(["word"] * 200)
    assert len(speech.request(long, "")["input"].split()) <= speech.MAX_WORDS + 1
    with pytest.raises(MediaError):
        speech.request("   ", "")


def test_model_unavailable_detects_gateway_trouble():
    assert brain._model_unavailable("503 Model failed to load: qwen")
    assert brain._model_unavailable("429 concurrency_limit")
    assert not brain._model_unavailable("400 invalid_voice")


def test_speak_waits_and_retries_when_the_model_is_down(monkeypatch, tmp_path):
    calls, slept = [], []

    async def fake_speak(client, base, key, body):
        calls.append(body)
        if len(calls) < 3:
            raise MediaError("503 queue_full")
        return b"RIFFwav"

    async def fake_sleep(n):
        slept.append(n)

    monkeypatch.setattr(speech, "_speak", fake_speak)
    monkeypatch.setattr(speech.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(studio, "_ctx", lambda s, k: ("http://gw/v1", "k"))
    monkeypatch.setattr(speech.profile_mod, "log_event", lambda *a, **k: {"id": "ev"})
    monkeypatch.setattr(speech.store, "media_dir", lambda cid, sub="": tmp_path / sub)
    monkeypatch.setattr(speech.media, "add", lambda *a, **k: {"id": "m1", "attempt": 1})
    monkeypatch.setattr(speech.media, "update", lambda *a, **k: None)
    out = asyncio.run(speech.speak({"id": "ch-1"}, "e1", {"say": "Hello there.", "say_tag": "cheerful"}))
    assert out["media_id"] == "m1" and len(calls) == 3 and slept == list(brain.DRAW_RETRY_WAITS_S[:2])
    assert (tmp_path / "char_voice" / "speech-a1.wav").read_bytes() == b"RIFFwav"
