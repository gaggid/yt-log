"""Rain clip: long wait, and a job the gateway still has is picked up instead of made again."""
import asyncio

import pytest

from relaxation import models as M, rain, store
from shorts import wan
from story3 import store as media


def _session_with_scene(tmp_path):
    s = store.create()
    it = media.add(s["id"], M.KIND_SCENE, "scene", 0, "done", {})
    d = media.media_dir(s["id"], "scene")
    (d / "scene-a1.jpg").write_bytes(b"jpg")
    media.update(it["id"], file="scene/scene-a1.jpg")
    return s["id"]


def _settings():
    return {"base_url": "http://gw/v1"}


def test_limit_covers_estimate():
    assert rain.RAIN_LIMIT_S >= 2 * M.estimate_rain_s(rain._FRAMES)
    assert rain.RAIN_LIMIT_S > rain.UPSCALE_LIMIT_S


def test_failed_attempt_resumes_same_job(tmp_path, monkeypatch):
    sid = _session_with_scene(tmp_path)
    old = media.add(sid, M.KIND_RAIN, "rain", 0, "failed", {"frames": rain._FRAMES, "seed": store.get(sid)["settings"]["seed"], "job_id": "job_1", "error": "x"})

    async def resume(job_id, base, key, limit_s=0):
        assert job_id == "job_1" and limit_s == rain.RAIN_LIMIT_S
        return b"mp4", {"width": 1280}

    async def submit(*a, **k):
        raise AssertionError("must not submit a new job")

    monkeypatch.setattr(wan, "resume", resume)
    monkeypatch.setattr(wan, "submit", submit)
    got = asyncio.run(rain.generate(sid, _settings(), "k"))
    assert got["id"] == old["id"] and got["status"] == "done"
    assert (media.media_dir(sid, "rain") / got["file"].split("/")[-1]).read_bytes() == b"mp4"
    assert len(media.items(sid, M.KIND_RAIN)) == 1


def test_gone_job_starts_new_one(tmp_path, monkeypatch):
    sid = _session_with_scene(tmp_path)
    old = media.add(sid, M.KIND_RAIN, "rain", 0, "failed", {"frames": rain._FRAMES, "seed": store.get(sid)["settings"]["seed"], "job_id": "job_1"})
    calls = []

    async def resume(*a, **k):
        raise wan.WanError("the gateway no longer has this job (results are kept for about an hour); make the shot again", lost=True)

    async def submit(*a, **k):
        calls.append("submit")
        return {"id": "job_2", "status": "queued"}

    async def wait(job_id, base, key, limit_s=0, progress=None):
        assert job_id == "job_2" and limit_s == rain.RAIN_LIMIT_S
        return {}

    async def fetch(res, base, key):
        return b"new"

    monkeypatch.setattr(wan, "resume", resume)
    monkeypatch.setattr(wan, "submit", submit)
    monkeypatch.setattr(wan, "wait", wait)
    monkeypatch.setattr(wan, "fetch", fetch)
    got = asyncio.run(rain.generate(sid, _settings(), "k"))
    assert calls == ["submit"] and got["id"] != old["id"] and got["status"] == "done"


def test_still_running_resume_timeout_is_final(tmp_path, monkeypatch):
    sid = _session_with_scene(tmp_path)
    media.add(sid, M.KIND_RAIN, "rain", 0, "failed", {"frames": rain._FRAMES, "seed": store.get(sid)["settings"]["seed"], "job_id": "job_1"})

    async def resume(*a, **k):
        raise wan.WanError("the clip did not finish within 66 minutes", lost=True)

    async def submit(*a, **k):
        raise AssertionError("a job still running on the gateway must not be doubled")

    monkeypatch.setattr(wan, "resume", resume)
    monkeypatch.setattr(wan, "submit", submit)
    with pytest.raises(Exception, match="rain clip failed"):
        asyncio.run(rain.generate(sid, _settings(), "k"))


def test_clip_is_small_and_length_in_minutes():
    assert M.CLIP_SIZE == "1280x720" and rain._FRAMES == 49
    assert 1000 < M.estimate_rain_s(rain._FRAMES) < 2000 and 2800 < M.estimate_rain_s(81) < 3100 and M.estimate_rain_s(49, "832x480") < 600
    assert M.total_s({"minutes": 5, "hours": 3}) == 300 and M.total_s({"hours": 3}) == 10800 and M.total_s({}) == 10800
    assert M.duration_label({"minutes": 5}) == "5 minutes" and M.duration_label({"hours": 3}) == "3 hours"
    s = store.create(scene="forest", minutes=5)
    assert s["settings"]["minutes"] == 5


def test_scene_prompts_are_first_person():
    for k, v in M.SCENES.items():
        assert v["prompt"].startswith("First-person point of view"), k


def test_clip_starts_and_ends_on_the_scene_picture():
    b = rain._rain_body(b"jpg", 7)
    assert b["end_image"] == b["image"] and b["speed_lora"] is False and b["size"] == M.CLIP_SIZE
    assert "slime" in b["negative_prompt"]


def test_mix_has_music_in_front_of_rain():
    assert M.MUSIC_LUFS - M.RAIN_LUFS >= 9


def test_rain_bed_has_no_gap_at_the_restart(tmp_path, monkeypatch):
    """The recording used to restart at its silent head every loop; the bed must hold one level."""
    import subprocess
    import config
    from relaxation import audio
    src = tmp_path / "rain.wav"
    # 100 s of noise that is silent for the first 5 s and swells for 30 s, like the real recording
    subprocess.run([config.FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "anoisesrc=d=100:c=pink:r=44100:a=0.5",
                    "-af", "volume='min(1,max(0,(t-5)/30))':eval=frame", str(src)], check=True)
    monkeypatch.setattr(audio, "RAIN_FILE", src)
    out = tmp_path / "bed.wav"
    audio._rain_loop(200, out, -31.0)
    assert abs(audio._loudness(out) - -31.0) < 2
    for t in (95, 100, 140, 190):                    # around where the old loop restarted and in between
        seg = tmp_path / f"s{t}.wav"
        subprocess.run([config.FFMPEG, "-y", "-v", "error", "-ss", str(t - 3), "-t", "6", "-i", str(out), str(seg)], check=True)
        assert audio._loudness(seg) > -36, t


# ── variety and the daily run ────────────────────────────────────────────────

def test_every_theme_is_used_before_one_repeats_and_music_differs():
    from relaxation import variety
    seen, plans = [], []
    for _ in range(len(M.SCENES)):
        s = store.create()
        seen.append(s["settings"]["scene"])
        plans.append(s["settings"]["music_plan"])
    assert sorted(seen) == sorted(M.SCENES)                          # all 12 themes once
    for a, b in zip(plans, plans[1:]):                                # never the same instrument twice in a row
        assert a["instrument"] != b["instrument"]
    for p in plans:
        assert "no percussion" in p["caption"] and "instrumental" in p["caption"] and p["caption"].count(",") <= 11
        assert M.MUSIC_BPM[0] <= p["bpm"] <= M.MUSIC_BPM[1]
    assert len({store.get(x["id"])["settings"]["seed"] for x in store.list_all()}) == len(M.SCENES)      # a new seed each time
    assert variety.pick_scene(variety.history(), __import__("random").Random(1)) in M.SCENES


def test_a_chosen_theme_is_kept_but_music_and_seed_still_change():
    a = store.create(scene="courtyard")
    b = store.create(scene="courtyard")
    assert a["settings"]["scene"] == b["settings"]["scene"] == "courtyard"
    assert a["settings"]["music_plan"]["instrument"] != b["settings"]["music_plan"]["instrument"]
    assert a["settings"]["seed"] != b["settings"]["seed"]
    assert M.music_recipe("courtyard", b["settings"]["music_plan"])["caption"] == b["settings"]["music_plan"]["caption"]


def test_daily_run_once_a_day_inside_the_window(monkeypatch):
    import time
    from relaxation import daily
    started = []
    monkeypatch.setattr(daily, "start_session", lambda minutes: started.append(minutes) or {"id": "rl-x"})
    monkeypatch.setattr(daily.jobs, "busy", lambda: False)
    monkeypatch.setattr(daily.manager, "busy", lambda: False)
    at = lambda h: time.mktime((2026, 11, 20, h, 10, 0, 0, 0, -1))
    assert daily.tick(at(2)) is None                                  # switched off by default
    daily.save_config({"enabled": True, "hour": 1, "minutes": 5})
    assert daily.tick(at(0)) is None and daily.tick(at(7)) is None    # outside 01:00-06:00
    monkeypatch.setattr(daily.jobs, "busy", lambda: True)
    assert daily.tick(at(2)) is None and not started                  # another job running: wait
    monkeypatch.setattr(daily.jobs, "busy", lambda: False)
    assert daily.tick(at(2)) == "rl-x" and started == [5]
    assert daily.tick(at(3)) is None and started == [5]               # only once that day
    assert daily.tick(at(2) + 86400) == "rl-x" and started == [5, 5]  # and again the next day


def test_only_themes_with_a_real_flame_let_it_flicker():
    flame = {k for k, v in M.SCENES.items() if v.get("flame")}
    assert flame == {"mountain_forest", "himalayan_ridge", "monastery_window", "kerala_veranda"}
    for k in M.SCENES:
        p = M.rain_motion(k)
        assert ("flame flickers" in p) == (k in flame), k
        assert "overall brightness never changes" in p
    assert "flicker" not in M.RAIN_NEGATIVE.replace("flashing", "")        # the ban is on brightness change and flashing, not on a flame
    assert "night" in M.SCENES["monastery_window"]["prompt"] and "dusk" not in M.SCENES["monastery_window"]["prompt"]
    assert rain._rain_body(b"x", 7, "monastery_window")["prompt"] == M.rain_motion("monastery_window")


# ── YouTube text, thumbnail, upload fields ───────────────────────────────────

def test_titles_descriptions_and_tags_follow_the_search_rules():
    from relaxation import seo
    titles = set()
    for k in M.SCENES:
        t = seo.title(k, "3 hours", "rl-" + k)
        titles.add(t)
        assert len(t) <= seo.TITLE_MAX and "Rain" in t and "3 Hours" in t and seo.place_of(k, True) in t or seo.place_of(k) in t
        d = seo.description(k, "3 hours", "harp")
        assert d.split("\n")[0].startswith("3 hours of calming rain sounds at ") and len(d.split("\n")[0]) <= 150, k
        assert seo.place_of(k) in d.split("\n")[0] and "AI-generated" in d
        assert d.splitlines()[-1].count("#") == 3                       # three hashtags, never more
        tg = seo.tags(k, "harp")
        assert tg[0] == "rain sounds" and len(tg) <= 15 and sum(len(x) + 1 for x in tg) <= 450
    assert len(titles) == len(M.SCENES)                                 # no two themes share a title
    assert seo.title("courtyard", "5 minutes", "a") .startswith(("5 Minutes", "Rain Sounds for Sleeping"))


def test_youtube_upload_body_declares_what_it_should():
    from youtube import upload
    b = upload.build_metadata({"title": "t", "description": "d", "tags": ["a"], "category_id": "10"})
    assert b["status"]["selfDeclaredMadeForKids"] is False and "madeForKids" not in b["status"]
    assert b["status"]["containsSyntheticMedia"] is True and b["status"]["privacyStatus"] == "public"
    assert b["snippet"]["defaultLanguage"] == "en" and b["snippet"]["categoryId"] == "10"


def test_thumbnail_is_1280x720_jpeg_under_2mb(tmp_path):
    from PIL import Image
    from relaxation import thumb
    src = tmp_path / "s.png"
    Image.new("RGB", (2048, 1152), (30, 60, 90)).save(src)
    data = thumb.render(src, "3 HOURS")
    im = Image.open(__import__("io").BytesIO(data))
    assert im.size == (1280, 720) and im.format == "JPEG" and len(data) < 2_000_000


# ── regenerate the music and put it into the finished video ──────────────────

def _ff(*args):
    import subprocess
    import config
    subprocess.run([config.FFMPEG, "-y", "-v", "error", *args], check=True)


def _session_with_video(tmp_path):
    s = store.create(scene="courtyard", minutes=1)
    sid = s["id"]
    rain = media.add(sid, M.KIND_RAIN, "rain", 0, "done", {"upscaled": False})
    final = media.add(sid, M.KIND_FINAL, "final", 0, "done", {"total_s": 60.0, "upscaled": False})
    aud = media.add(sid, M.KIND_AUDIO, "audio", 0, "done", {"total_s": 60.0})
    d = media.media_dir(sid, "final")
    _ff("-f", "lavfi", "-i", "color=c=blue:s=64x64:d=3:r=10", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "3", "-c:v", "libx264", "-c:a", "aac", str(d / "final-a1.mp4"))
    media.update(final["id"], file="final/final-a1.mp4")
    media.update(rain["id"], file="rain/r.mp4")
    a = media.media_dir(sid, "audio")
    _ff("-f", "lavfi", "-i", "sine=f=440:d=3", str(a / "audio-a1.wav"))
    media.update(aud["id"], file="audio/audio-a1.wav")
    return sid


def test_remux_replaces_only_the_sound(tmp_path):
    import subprocess
    import config
    from relaxation import video
    sid = _session_with_video(tmp_path)
    new = video.remux(sid)
    assert new["attempt"] == 2 and new["status"] == "done" and new["meta"]["remux_of"]
    assert store.chosen(sid, M.KIND_FINAL)["id"] == new["id"]
    info = subprocess.run([config.FFMPEG, "-hide_banner", "-i", str(media.path_of(new))], capture_output=True, text=True).stderr
    assert "Video: h264" in info and "Audio: aac" in info and "64x64" in info


def test_regenerating_music_changes_seed_and_instrument_and_rebuilds_the_video(tmp_path, monkeypatch):
    from relaxation import audio, publish
    from story3 import music as music_mod
    sid = _session_with_video(tmp_path)
    before = store.get(sid)["settings"]
    seeds = []

    async def fake_music(plan_id, cfg, total_s, s, key, progress=None, force=False):
        seeds.append(cfg["seed"])
        it = media.add(plan_id, "music", "bgm", 0, "done", {"duration_s": 30.0})
        _ff("-f", "lavfi", "-i", "sine=f=330:d=30", str(media.media_dir(plan_id, "music") / "bgm-a1.wav"))
        return media.update(it["id"], file="music/bgm-a1.wav")

    async def no_publish(*a, **k):
        return {}
    monkeypatch.setattr(music_mod, "make", fake_music)
    monkeypatch.setattr(publish, "generate", no_publish)
    out = asyncio.run(audio.regenerate_music(sid, {"base_url": "x"}, "k", instrument="other"))
    after = store.get(sid)["settings"]
    assert after["music_seed"] != before.get("music_seed") and seeds == [after["music_seed"]]
    assert after["music_plan"]["instrument"] != before["music_plan"]["instrument"]
    assert after["music_plan"]["instrument"] in M.SCENES["courtyard"]["instruments"]
    assert out["video"] and store.chosen(sid, M.KIND_FINAL)["attempt"] == 2
    assert store.chosen(sid, M.KIND_AUDIO)["attempt"] == 2 and store.chosen(sid, M.KIND_AUDIO)["meta"]["music"] is True
    assert not list((media.media_dir(sid) / "work").glob("*"))           # the big intermediate files are removed


def test_a_music_failure_is_recorded_not_hidden(tmp_path, monkeypatch):
    from relaxation import audio
    from story3 import music as music_mod
    from story3.voice import MediaError
    sid = _session_with_video(tmp_path)

    async def broken(*a, **k):
        raise MediaError("the music could not be made: gateway busy")
    monkeypatch.setattr(music_mod, "make", broken)
    a = asyncio.run(audio.make(sid, {"base_url": "x"}, "k", force=True))
    assert a["meta"]["music"] is False and "gateway busy" in a["meta"]["music_error"]
    assert "gateway busy" in store.view(store.get(sid))["music_error"]
