"""Talking avatar shots (InfiniteTalk): the request carries the shot's slice of the beat's voice and its storyboard picture; checks name what is missing; the clip goes old with the voice."""
import base64
import io
import wave

import pytest

from shorts_fakes import FakeChat
from story3 import store as media
from test_shorts import S, gw, needs_ffmpeg, run  # noqa: F401 - fixtures
from test_shorts_cast import make_char, with_cast

from shorts import avatar, checks, clips, models, pipelines as P, store, voice as svoice


def avatar_short():
    raju = make_char()
    short = with_cast(raju)
    sh = next(s for s in short["shots"] if s["cast"])
    sh["avatar"] = True
    store.save(short)
    return store.get(short["id"]), sh["id"]


def test_an_avatar_shot_needs_its_voice_and_a_cast_character(gw, env):
    short, sid = avatar_short()
    codes = {i["code"] for i in checks.run(short)["issues"]}
    assert "avatar_voice" in codes and "avatar_cast" not in codes
    sh = next(s for s in short["shots"] if s["id"] == sid)
    sh["cast"] = []
    store.save(short)
    assert "avatar_cast" in {i["code"] for i in checks.run(store.get(short["id"]))["issues"]}


@needs_ffmpeg
def test_the_avatar_clip_is_asked_for_with_the_picture_and_the_voice_slice(gw, env):
    short, sid = avatar_short()
    run(svoice.make(short["id"], s=S, key="k"))
    run(clips.make_keyframes(short["id"], s=S, key="k"))
    short = store.get(short["id"])
    shot = next(s for s in short["shots"] if s["id"] == sid)
    info = avatar.slice_info(short, shot)
    assert info and 0 <= info["offset"] < info["span"] and abs(info["seconds"] - shot["seconds"]) < 1e-6
    with wave.open(io.BytesIO(avatar.audio_wav(info))) as w:
        assert abs(w.getnframes() / w.getframerate() - (info["seconds"] + 0.2)) < 0.15, "only this shot's part of the voice is sent"
    res = run(clips.make_clips(short["id"], [sid], s=S, key="k"))
    assert res["made"] == 1 and not res["failed"]
    body = gw.requests[-1]
    assert body["model"] == models.TALK and body["image"].startswith("data:image/jpeg") and body["audio"].startswith("data:audio/wav;base64,")
    assert body["fps"] == 25 and body["steps"] == 6 and body["duration"] > shot["seconds"]
    base64.b64decode(body["audio"].split(",", 1)[1])
    assert clips.chosen_clip(short, shot), "the clip counts for this shot"


@needs_ffmpeg
def test_an_avatar_clip_goes_old_when_the_voice_changes(gw, env):
    short, sid = avatar_short()
    run(svoice.make(short["id"], s=S, key="k"))
    run(clips.make_keyframes(short["id"], s=S, key="k"))
    run(clips.make_clips(short["id"], [sid], s=S, key="k"))
    short = store.get(short["id"])
    shot = next(s for s in short["shots"] if s["id"] == sid)
    assert clips.chosen_clip(short, shot)
    beat = next(b for b in short["beats"] if b["id"] == shot["beat"])
    beat["sentences"][0]["text"] += " Aur phir chup ho gaya."
    store.save(short)
    short = store.get(short["id"])
    assert clips.clip_plan(short, next(s for s in short["shots"] if s["id"] == sid)) is None, "the beat's voice is old; the avatar waits for a new take"


def test_the_estimate_counts_avatar_shots_as_talking_clips(gw, env):
    short, sid = avatar_short()
    base = P.estimate_s(short)
    sh = next(s for s in short["shots"] if s["id"] == sid)
    sh["avatar"] = False
    store.save(short)
    assert base != P.estimate_s(store.get(short["id"]))
