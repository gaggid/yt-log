"""Dead-air trimming of voice takes (audit task 1.8): silences shrink, planned pauses survive, nothing else changes."""
import array
import io
import math
import wave

from story2 import planner
from story3 import audiofix, store, voice
from test_phase2b import boarded

RATE = 24000


def tone(seconds, amp=8000):
    n = int(RATE * seconds)
    return array.array("h", (int(amp * math.sin(2 * math.pi * 220 * i / RATE)) for i in range(n)))


def quiet(seconds):
    return array.array("h", [0]) * int(RATE * seconds)


def make_wav(parts, width=2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(width)
        w.setframerate(RATE)
        data = array.array("h")
        for p in parts:
            data.extend(p)
        w.writeframes(data.tobytes() if width == 2 else bytes(len(data)))
    return buf.getvalue()


def seconds(b):
    with wave.open(io.BytesIO(b)) as w:
        return w.getnframes() / w.getframerate()


def test_long_silence_is_shortened_and_speech_is_kept():
    src = make_wav([tone(1.0), quiet(1.5), tone(1.0), quiet(6.0), tone(1.0)])
    out, rep = audiofix.trim(src, [])
    assert abs(seconds(out) - (3.0 + 2 * audiofix.DEFAULT_MAX_GAP_S)) < 0.15
    assert rep["removed_s"] > 6.5 and rep["longest_removed_s"] > 5.0 and rep["gaps_trimmed"] == 2
    assert any(c["was_s"] > 5.5 for c in rep["cut"])


def test_a_planned_pause_keeps_its_length():
    src = make_wav([tone(1.0), quiet(1.3), tone(1.0), quiet(1.0), tone(1.0)])
    out, rep = audiofix.trim(src, [1.2])
    assert 2.9 + 1.2 < seconds(out) < 3.0 + 1.2 + audiofix.DEFAULT_MAX_GAP_S + 0.4          # one pause of about 1.2 s kept, the other cut to the limit


def test_short_silences_are_left_alone():
    src = make_wav([tone(1.0), quiet(0.3), tone(1.0)])
    out, rep = audiofix.trim(src, [])
    assert rep["removed_s"] == 0 and out == src or abs(seconds(out) - seconds(src)) < 0.02


def test_audio_that_is_not_16_bit_is_returned_unchanged():
    src = make_wav([quiet(1.0)], width=1)
    out, rep = audiofix.trim(src, [])
    assert out == src and "not 16-bit" in rep["note"]


def test_retrim_makes_a_new_take_keeps_approval_and_is_idempotent(env):
    pid, cid, be, p = boarded(env)
    seg = sorted(p["segments"], key=lambda s: s["seq"])[0]
    vk = store.voice_key(p)
    src = make_wav([tone(1.0), quiet(5.0), tone(1.0)])
    it = store.add(p["id"], "voice", seg["id"], 1, "running", {"text_hash": store.segment_hash(seg, vk)})
    path = store.media_dir(p["id"], "voice") / f"{seg['id']}-a1.wav"
    path.write_bytes(src)
    store.update(it["id"], status="done", file=f"voice/{seg['id']}-a1.wav", meta={"duration_s": round(seconds(src), 2)})
    store.approve(it["id"])
    r = voice.retrim(p["id"])
    assert len(r["trimmed"]) == 1 and r["removed_s"] > 4
    takes = store.items(p["id"], "voice", seg["id"])
    assert len(takes) == 2 and takes[1]["approved"] and not takes[0]["approved"] and takes[1]["meta"]["trimmed_from"] == it["id"]
    assert takes[1]["meta"]["duration_s"] < takes[0]["meta"]["duration_s"] - 4
    again = voice.retrim(p["id"])
    assert again["trimmed"] == [] and again["already_trimmed"] == 1
    assert len(store.items(p["id"], "voice", seg["id"])) == 2


def test_max_gap_setting_is_read_with_a_floor():
    assert voice.max_gap_s({"settings": {}}) == audiofix.DEFAULT_MAX_GAP_S
    assert voice.max_gap_s({"settings": {"voice": {"max_gap_s": 0.5}}}) == 0.5
    assert voice.max_gap_s({"settings": {"voice": {"max_gap_s": 0.01}}}) == 0.15
    assert voice.max_gap_s({"settings": {"voice": {"max_gap_s": "x"}}}) == audiofix.DEFAULT_MAX_GAP_S


def test_loudnorm_brings_a_quiet_take_near_the_target(tmp_path):
    """Audit task 1.9: the video's audio filter lifts a quiet take (about -26 LUFS) to about -14 LUFS."""
    import shutil
    import subprocess

    import config
    from story2 import audit
    from story3 import video
    if not (shutil.which(config.FFMPEG) or __import__("pathlib").Path(config.FFMPEG).is_file()):
        import pytest
        pytest.skip("ffmpeg is not installed")
    src = tmp_path / "quiet.wav"
    noise = array.array("h", (int(1500 * math.sin(2 * math.pi * 180 * i / RATE) + 700 * math.sin(2 * math.pi * 1300 * i / RATE)) for i in range(RATE * 12)))
    src.write_bytes(make_wav([noise]))
    out = tmp_path / "loud.wav"
    subprocess.run([config.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-af", video.LOUDNORM, str(out)], check=True)
    before, after = audit.audio_stats(src)["lufs"], audit.audio_stats(out)["lufs"]
    assert before < -22 and -16.0 < after < -12.0
