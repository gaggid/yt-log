"""The second music engine of the Rain Channel, ACE-Step 1.5 (relaxation/acemusic.py, models.ace_*, variety.pick_engine; owner 2026-11-20)."""
import asyncio
import random
import re

import numpy as np
import pytest

from relaxation import acemusic, models as M, store, variety
from story3 import store as media

SR = acemusic.SR


@pytest.fixture(autouse=True)
def _tmp_data(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path, raising=False)


def _ff(*args):
    import subprocess
    import config
    subprocess.run([config.FFMPEG, "-y", "-v", "error", *args], check=True)


def test_the_plan_is_56_bpm_minor_calm_and_has_every_layer():
    for seed in range(20):
        p = variety.pick_music("himalayan_ridge", [], random.Random(seed), engine="acestep")
        assert p["engine"] == "acestep" and p["bpm"] == 56 and p["key"].endswith("minor") and p["layers"]["lead"] == p["instrument"]
        assert len(p["caption"]) < 500 and "beatless" in p["caption"] and "no vocals" in p["caption"] and p["instrument"] in p["caption"]
        tags = M.ace_lyrics(p, 0).split("\n\n")
        assert len(tags) == 7 and all(re.fullmatch(r"\[[^\[\]]+\]", t) for t in tags)            # every section tag alone on its line, no words
        assert tags[0].startswith("[Intro") and tags[-1].startswith("[Outro") and p["layers"]["pad"] in tags[0]
        assert M.ace_lyrics(p, 0) != M.ace_lyrics(p, 1)                                           # the order of the middle layers turns from take to take


def test_the_style_and_key_change_from_video_to_video():
    hist, seen = [], []
    for i in range(12):
        p = variety.pick_music("forest", hist, random.Random(i), engine="acestep")
        seen.append((p["style"], p["key"]))
        hist.insert(0, {"scene": "forest", "instrument": p["instrument"], "mood": p["mood"], "engine": "acestep", "style": p["style"], "key": p["key"]})
    assert len({s for s, _ in seen}) >= 4 and len({k for _, k in seen}) == 3
    assert all(seen[i][0] != seen[i + 1][0] for i in range(len(seen) - 1))                       # never the same style twice in a row
    assert all(seen[i][1] != seen[i + 1][1] for i in range(len(seen) - 1))


def test_the_two_engines_are_used_in_turn_so_their_videos_can_be_compared():
    hist = []
    for i in range(12):
        e = variety.pick_engine(hist, random.Random(i))
        hist.insert(0, {"engine": e})
    last = [h["engine"] for h in hist][:12]
    assert abs(last.count("yue2") - last.count("acestep")) <= 1
    assert variety.pick_engine([{"engine": "yue2"}] * 3 + [{}] * 2, random.Random(1)) == "acestep"        # an old session without the field counts as YuE2
    assert variety.pick_music("forest", [], random.Random(1), engine="yue2")["engine"] == "yue2"
    assert variety.history() == [] or "engine" in variety.history()[0]


def test_a_take_that_opens_with_a_loud_clipping_drone_is_cut_where_it_settles():
    rng = np.random.RandomState(1)
    loud = (rng.randn(25 * SR) * 0.35).clip(-1, 1).astype(np.float32)
    loud[::4000] = 1.0
    quiet = (rng.randn(100 * SR) * 0.1).astype(np.float32)
    cut = acemusic.grind(np.concatenate([loud, quiet]))
    assert 20 <= cut <= 30
    assert acemusic.grind(np.concatenate([quiet, quiet])) == 0.0                                     # an even take is left alone
    assert acemusic.grind(quiet[:SR * 10]) == 0.0


def test_a_bright_busy_take_scores_worse_than_a_dark_even_one():
    t = np.arange(40 * SR) / SR
    dark = (0.1 * np.sin(2 * np.pi * 220 * t) + 0.05 * np.sin(2 * np.pi * 330 * t)).astype(np.float32)
    bright = (0.1 * np.sin(2 * np.pi * 3000 * t) * (np.sin(2 * np.pi * 1.0 * t) > 0)).astype(np.float32)           # 60 bpm clicks of a bright tone
    pd, pb = acemusic.profile(dark), acemusic.profile(bright)
    assert pb["centroid"] > 2 * pd["centroid"] and pb["pulse"] > pd["pulse"]


def test_the_calmest_seed_wins_and_a_rejected_take_is_not_kept(monkeypatch):
    s = store.create(scene="forest", minutes=10)
    sid = s["id"]
    plan = variety.pick_music("forest", [], random.Random(5), engine="acestep")
    calls = []

    async def fake_one(body, st, key):
        calls.append(body["seed"])
        return b"x" * 2000

    scripted = iter([{"trim_s": 0.0, "centroid": 1900, "pulse": 0.8, "score": 2.1, "calm": False},
                     {"trim_s": 26.0, "centroid": 880, "pulse": 0.45, "score": 0.3, "calm": True}])
    monkeypatch.setattr(acemusic, "_one", fake_one)
    monkeypatch.setattr(acemusic, "assess", lambda p: next(scripted))
    it = asyncio.run(acemusic.make_take(sid, plan, 600.0, 0, 1000, {"base_url": "x"}, "k"))
    assert it["status"] == "done" and len(calls) == 2 and calls[1] != calls[0] and it["meta"]["seed"] == calls[1]
    assert it["meta"]["trim_s"] == 26.0 and it["meta"]["calm"] is True and it["meta"]["engine"] == "acestep"
    assert media.path_of(it).is_file() and not list(media.media_dir(sid, "music").glob("*try*"))      # the other attempt's file is removed
    again = asyncio.run(acemusic.make_take(sid, plan, 600.0, 0, 1000, {"base_url": "x"}, "k"))
    assert again["id"] == it["id"] and len(calls) == 2                                                  # the same take is reused, the gateway is not asked again


def test_take_count_gives_four_distinct_ten_minute_takes_for_three_hours():
    assert M.ace_take_count(3 * 3600) == 4 and M.ace_take_count(600) == 1 and M.ace_take_count(60) == 1
    body = acemusic.request(variety.pick_music("forest", [], random.Random(2), engine="acestep"), 7, 0, 3 * 3600)
    assert body["duration"] == 600 and body["bpm"] == 56 and body["model"] == "acestep" and body["wait"] is False and body["thinking"] is False
    assert acemusic.request(variety.pick_music("forest", [], random.Random(2), engine="acestep"), 7, 0, 60)["duration"] == 90


def test_a_session_with_an_ace_step_plan_is_mixed_from_its_takes_and_the_cut_is_applied(monkeypatch):
    from relaxation import audio
    s = store.create(scene="forest", minutes=1)
    sid = s["id"]
    sess = store.get(sid)
    sess["settings"]["music_plan"] = variety.pick_music("forest", [], random.Random(4), engine="acestep")
    store.save(sess)
    seen = {}

    async def fake_takes(session_id, plan, settings, total_s, st, key, progress=None):
        out = []
        for k in range(2):
            it = media.add(session_id, "music", "bgm", 0, "done", {"engine": "acestep", "take": k, "trim_s": 4.0 * k})
            _ff("-f", "lavfi", "-i", f"sine=f={220 + 110 * k}:d=60", str(media.media_dir(session_id, "music") / f"bgm-a{k}.wav"))
            out.append(media.update(it["id"], file=f"music/bgm-a{k}.wav"))
        seen["called"] = True
        return out, ""
    monkeypatch.setattr(acemusic, "make_takes", fake_takes)
    a = asyncio.run(audio.make(sid, {"base_url": "x"}, "k", force=True))
    assert seen.get("called") and a["meta"]["music"] is True and a["meta"]["music_engine"] == "acestep" and a["meta"]["music_takes"] == 2


def test_switching_the_engine_makes_a_new_plan_for_that_engine(monkeypatch):
    from relaxation import audio, publish
    s = store.create(scene="forest", minutes=1)
    sid = s["id"]
    sess = store.get(sid)
    sess["settings"]["music_plan"] = variety.pick_music("forest", [], random.Random(1), engine="yue2")
    store.save(sess)
    captured = {}

    async def fake_make(session_id, st, key, progress=None, force=False):
        captured["plan"] = store.get(session_id)["settings"]["music_plan"]
        return {"id": "a", "meta": {"music": True}}

    async def no_publish(*a, **k):
        return {}
    monkeypatch.setattr(audio, "make", fake_make)
    monkeypatch.setattr(publish, "generate", no_publish)
    asyncio.run(audio.regenerate_music(sid, {"base_url": "x"}, "k", engine="acestep"))
    plan = captured["plan"]
    assert plan["engine"] == "acestep" and plan["bpm"] == 56 and "layers" in plan
    asyncio.run(audio.regenerate_music(sid, {"base_url": "x"}, "k", engine="acestep", instrument="other"))
    assert captured["plan"]["engine"] == "acestep"


# ── the first start of the model can take longer than the gateway waits (2026-11-20, a real run lost its music) ─────────────────────────────────────────────────────────────
def test_a_start_that_failed_is_waited_out_and_tried_again(monkeypatch):
    from shorts import wan
    monkeypatch.setattr(M, "ACE_LOAD_WAIT_S", 0.0)
    calls = []

    async def submit(body, base, key, background=False, path=""):
        calls.append(1)
        if len(calls) < 3:
            raise wan.WanError("the model server did not take the request: Model failed to load: ACE-Step server not ready after 300s")
        return {"status": "succeeded", "url": "u"}

    async def fetch(res, base, key):
        return b"audio"
    monkeypatch.setattr(wan, "submit", submit)
    monkeypatch.setattr(wan, "fetch", fetch)
    assert asyncio.run(acemusic._one({}, {"base_url": "x"}, "k")) == b"audio" and len(calls) == 3

    async def other_error(*a, **k):
        raise wan.WanError("invalid_input: bad bpm")
    monkeypatch.setattr(wan, "submit", other_error)
    from story3.voice import MediaError
    with pytest.raises(MediaError, match="invalid_input"):
        asyncio.run(acemusic._one({}, {"base_url": "x"}, "k"))


def test_when_the_model_does_not_start_the_video_gets_yue2_music_not_none(monkeypatch):
    from relaxation import audio
    from story3 import music as music_mod
    s = store.create(scene="forest", minutes=1)
    sid = s["id"]
    sess = store.get(sid)
    sess["settings"]["music_plan"] = variety.pick_music("forest", [], random.Random(4), engine="acestep")
    store.save(sess)
    asked = []

    async def ace_fails(session_id, plan, settings, total_s, st, key, progress=None):
        return [], "the music could not be made: Model failed to load: ACE-Step server not ready after 300s"

    async def fake_yue(plan_id, cfg, total_s, st, key, progress=None, force=False):
        asked.append(cfg["plan"]["caption"])
        it = media.add(plan_id, "music", "bgm", 0, "done", {"duration_s": 60.0})
        _ff("-f", "lavfi", "-i", "sine=f=330:d=60", str(media.media_dir(plan_id, "music") / "bgm-a1.wav"))
        return media.update(it["id"], file="music/bgm-a1.wav")
    monkeypatch.setattr(acemusic, "make_takes", ace_fails)
    monkeypatch.setattr(music_mod, "make", fake_yue)
    a = asyncio.run(audio.make(sid, {"base_url": "x"}, "k", force=True))
    assert a["meta"]["music"] is True and a["meta"]["music_engine"] == "yue2" and "ACE-Step failed" in a["meta"]["music_note"] and not a["meta"]["music_error"]
    assert asked and asked[0].startswith("English, ambient, sleep music") and "layered" not in asked[0]          # a YuE2 caption, not the ACE-Step one


def test_the_other_takes_are_not_tried_when_the_first_one_cannot_start(monkeypatch):
    s = store.create(scene="forest", minutes=180)
    plan = variety.pick_music("forest", [], random.Random(2), engine="acestep")
    tried = []

    async def make_take(session_id, plan_, total_s, k, seed, st, key, force=False):
        tried.append(k)
        from story3.voice import MediaError
        raise MediaError("the music could not be made: Model failed to load: not ready after 300s")
    monkeypatch.setattr(acemusic, "make_take", make_take)
    takes, err = asyncio.run(acemusic.make_takes(s["id"], plan, {"seed": 1}, 3 * 3600.0, {"base_url": "x"}, "k"))
    assert takes == [] and tried == [0] and "not ready" in err
