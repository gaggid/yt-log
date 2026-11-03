"""Optional background music (story3/music.py): the plan stays inside a calm vocabulary, the request asks for one quiet instrumental loop, the track is looped and levelled under the voice."""
import asyncio
import json

import pytest

from story import llm
from story3 import auto, music, store
from shorts import store as sstore, stitch, auto as sauto
from shorts_fakes import FakeChat, needs_ffmpeg, tone_wav
from test_shorts import S, planned as planned_short


def run(c):
    return asyncio.run(c)


def test_a_caption_has_only_calm_vocabulary_and_the_fixed_tail():
    p = music.clean("heavy metal", ["aggressive", "calm", "tense", "warm"], 200, ["electric guitar", "soft piano", "warm pad", "harp", "cello"], "incident")
    tags = p["caption"].split(", ")
    assert tags[0] == "English" and tags[1] == "cinematic ambient"                      # an unknown genre falls back to the recipe of the story type
    assert [t for t in tags if t in music.MOODS] == ["calm", "tense"]                  # only listed moods, two at most
    assert [t for t in tags if t in music.INSTRUMENTS] == ["soft piano", "warm pad", "harp"] and tags[-4:] == list(music.TAIL)
    assert 6 <= len(tags) <= 12
    assert "92 BPM" in tags                                                              # a tempo is held inside the slow range
    assert "aggressive" not in tags and "electric guitar" not in tags


def test_a_film_that_plays_faster_gets_a_slower_tempo():
    assert music.bpm_range(1.25)[1] < music.bpm_range(1.0)[1]
    assert music.clean("minimal", ["calm"], 90, ["soft piano"], "documentary", 1.25)["bpm"] == music.bpm_range(1.25)[1]


def test_typed_tags_are_sorted_back_into_the_vocabulary():
    p = music.parse_caption("English, dubstep, aggressive, 150 BPM, heavy drums, felt piano", "explainer")
    assert p["genre"] == "lo-fi" and p["moods"] == music.RECIPES["explainer"]["moods"] and p["instruments"] == ["felt piano"] and p["bpm"] == 92
    assert music.parse_caption("   ", "explainer") is None


def test_the_request_is_one_instrumental_loop_with_empty_sections():
    cfg = music.norm({"enabled": True, "plan": music.fallback("documentary")})
    short, long = music.request(cfg, 30), music.request(cfg, 900)
    assert short["model"] == "yue2-3b" and short["lyrics"] == "[intro]\n\n[outro]\n"
    # [Instrumental] is not a valid YuE2 tag; empty [verse]/[bridge] sections are used instead
    assert "[Instrumental]" not in long["lyrics"] and long["lyrics"].count("[verse]") + long["lyrics"].count("[bridge]") == music.MAX_SECTIONS - 2 and long["duration"] <= 300
    assert "no vocals" in long["caption"] and "instrumental" in long["caption"]
    with pytest.raises(music.MediaError):
        music.request(music.norm({"enabled": True}), 30)


def test_a_failed_planning_call_uses_the_recipe_and_a_wild_answer_is_cleaned(monkeypatch):
    async def boom(self, *a, **k):
        raise llm.LLMError("down")
    monkeypatch.setattr(llm.JsonCaller, "call", boom)
    p = run(music.plan_music("STORY TYPE: x", "biography", None, {}))
    assert p["source"] == "recipe" and "neo-classical" in p["caption"]

    class Res:
        value = music.MusicOut(genre="club", moods=["mysterious"], bpm=70, instruments=["soft strings", "tuba"], why="quiet")

    async def ok(self, *a, **k):
        return Res()
    monkeypatch.setattr(llm.JsonCaller, "call", ok)
    p = run(music.plan_music("STORY TYPE: x", "incident", None, {}))
    assert p["source"] == "writer" and p["genre"] == "cinematic ambient" and p["instruments"] == ["soft strings"] and p["moods"] == ["mysterious"]


class Gateway:
    def __init__(self, fail=False):
        self.bodies, self.fail = [], fail

    def install(self, monkeypatch, data):
        from shorts import wan

        async def submit(body, base, key, background=False, path=""):
            assert path == "/audio/music" and background
            self.bodies.append(body)
            if self.fail:
                raise wan.WanError("the model server refused the request (400): missing_input")
            return {"id": "job_1", "status": "queued"}

        async def wait(jid, base, key, limit_s=0, progress=None):
            return {"url": "/music/x.mp3", "duration_s": 12.0}

        async def fetch(res, base, key):
            return data
        monkeypatch.setattr(wan, "submit", submit)
        monkeypatch.setattr(wan, "wait", wait)
        monkeypatch.setattr(wan, "fetch", fetch)


@needs_ffmpeg
def test_the_track_is_made_once_reused_and_looped_to_the_film(env, monkeypatch, tmp_path):
    gw = Gateway()
    gw.install(monkeypatch, tone_wav(12.0))
    cfg = music.norm({"enabled": True, "plan": music.fallback("explainer")})
    it = run(music.make("pl-x", cfg, 90, {"base_url": "http://gw/v1"}, "k"))
    assert it["status"] == "done" and it["file"] == "music/bgm-a1.mp3" and gw.bodies[0]["cot"] == "full"
    assert run(music.make("pl-x", cfg, 90, {"base_url": "http://gw/v1"}, "k"))["id"] == it["id"] and len(gw.bodies) == 1
    assert music.chosen("pl-x", cfg, 90)["id"] == it["id"]
    other = music.norm({"enabled": True, "plan": music.fallback("incident")})
    assert music.chosen("pl-x", other, 90) is None, "a changed plan makes the old track not count"
    from story3 import video
    bed = music.bed_from_track(video.FFMPEG, it, 40.0, tmp_path, -34)               # 12 s track, 40 s film: looped with cross-fades
    assert bed and abs(store.wav_seconds(bed) - 40.0) < 0.5


def test_a_refused_request_leaves_a_failed_row_and_a_plain_message(env, monkeypatch):
    Gateway(fail=True).install(monkeypatch, b"")
    cfg = music.norm({"enabled": True, "plan": music.fallback("explainer")})
    with pytest.raises(music.MediaError, match="could not be made"):
        run(music.make("pl-y", cfg, 60, {"base_url": "http://gw/v1"}, "k"))
    assert [i["status"] for i in store.items("pl-y", music.KIND)] == ["failed"] and not music.chosen("pl-y", cfg, 60)


def test_a_short_plans_its_music_with_the_script_only_when_it_is_on(env, monkeypatch):
    off = planned_short("quick")
    assert not off["settings"]["music"] and not off["settings"]["music_plan"]
    on = planned_short("quick", music=True)
    plan = on["settings"]["music_plan"]
    assert plan["caption"].startswith("English, ") and plan["source"] in ("recipe", "writer")
    assert music.short_wanted(on) and music.short_missing(on)
    assert [s["id"] for s in sauto.steps(on) if s["id"] == "music"] == ["music"]
    assert not [s for s in sauto.steps(off) if s["id"] == "music"]


def test_long_form_stages_skip_when_music_is_off(env):
    ids = [k for k, _ in auto.STAGES]
    assert ids.index("musicplan") == ids.index("blueprint") + 1 and ids.index("music") == ids.index("video") - 1
