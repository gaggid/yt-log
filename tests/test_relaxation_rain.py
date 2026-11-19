"""Rain clip: long wait, and a job the gateway still has is picked up instead of made again."""
import asyncio
from pathlib import Path

import pytest

from relaxation import models as M, rain, store
from shorts import wan
from story3 import store as media


@pytest.fixture(autouse=True)
def _wan_engine_unless_asked(monkeypatch):
    """Most of these tests are about the Wan rain clip, the old engine; the code engine tests ask for it by name."""
    monkeypatch.setattr(M, "RAIN_ENGINE", "wan")


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
    assert M.CLIP_SIZE == "1280x720" and rain._FRAMES == 57
    assert 1000 < M.estimate_rain_s(rain._FRAMES) < 2200 and 2800 < M.estimate_rain_s(81) < 3100 and M.estimate_rain_s(57, "832x480") < 700
    assert M.total_s({"minutes": 5, "hours": 3}) == 300 and M.total_s({"hours": 3}) == 10800 and M.total_s({}) == 10800
    assert M.duration_label({"minutes": 5}) == "5 minutes" and M.duration_label({"hours": 3}) == "3 hours"
    s = store.create(scene="forest", minutes=5)
    assert s["settings"]["minutes"] == 5


def test_scene_prompts_are_first_person():
    for k, v in M.SCENES.items():
        assert v["prompt"].startswith(M.WET) and "First-person point of view" in v["prompt"][:500], k


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
        assert "no percussion" in p["caption"] and "instrumental" in p["caption"] and p["caption"].count(",") <= 13
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
        it = media.add(plan_id, "music", "bgm", 0, "done", {"duration_s": 60.0})
        _ff("-f", "lavfi", "-i", "sine=f=330:d=60", str(media.media_dir(plan_id, "music") / "bgm-a1.wav"))
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
    a2 = [i for i in media.items(sid, M.KIND_AUDIO) if i["attempt"] == 2][0]
    assert a2["status"] == "done" and a2["meta"]["music"] is True and a2["meta"]["mix_removed"] and a2["file"] == ""      # mixed, put into the video, then removed
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


def test_scene_prompts_are_cinematic_and_loras_are_optional():
    from relaxation import image
    for k, v in M.SCENES.items():
        assert v["prompt"].count("Cinematic wide-angle photograph") == 1 and v["prompt"].rstrip().endswith("No people, no text, no logo."), k
    b = image._body({}, "courtyard", 5)
    assert "lora" not in b and b["size"] == M.IMAGE_SIZE                       # none unless a session asks for one
    b = image._body({"image_loras": [{"name": "purelens-realism", "strength": 0.6}]}, "courtyard", 5)
    assert b["lora"] == {"purelens-realism": 0.6} and b["prompt"].startswith("p3r4l4ns. Just after heavy rain")


# ── the video is encoded once and repeated; a restart does not leave a session 'running' ─────────

def test_final_video_repeats_the_loop_without_re_encoding_and_keeps_exact_length(tmp_path):
    import subprocess
    import config
    from relaxation import video
    s = store.create(scene="courtyard", minutes=1)
    sid = s["id"]
    rain = media.add(sid, M.KIND_RAIN, "rain", 0, "done", {"upscaled": False})
    aud = media.add(sid, M.KIND_AUDIO, "audio", 0, "done", {"total_s": 60.0})
    _ff("-f", "lavfi", "-i", "testsrc=s=96x54:d=2:r=16", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(media.media_dir(sid, "rain") / "r.mp4"))
    media.update(rain["id"], file="rain/r.mp4")
    _ff("-f", "lavfi", "-i", "sine=f=330:d=60", str(media.media_dir(sid, "audio") / "a.wav"))
    media.update(aud["id"], file="audio/a.wav")
    final = asyncio.run(video.make(sid, {"base_url": "x"}, "k"))
    assert final["status"] == "done"
    path = media.path_of(final)
    log = subprocess.run([config.FFMPEG, "-hide_banner", "-v", "error", "-i", str(path), "-f", "null", "-"], capture_output=True, text=True).stderr
    assert log.strip() == "", log                                           # decodes cleanly through every repeat
    info = subprocess.run([config.FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    assert "Duration: 00:01:00" in info or "Duration: 00:00:59.9" in info or "Duration: 00:01:01" in info
    assert "Video: h264" in info and "Audio: aac" in info
    n = subprocess.run([config.FFMPEG, "-hide_banner", "-i", str(path), "-map", "0:v:0", "-c", "copy", "-f", "null", "-"], capture_output=True, text=True).stderr
    frames = int(__import__("re").findall(r"frame=\s*(\d+)", n)[-1])
    assert abs(frames - 60 * M.OUT_FPS) <= 2 * M.OUT_FPS * 0.1 + 6         # 30 fps for 60 s, within a few frames
    assert not list((media.media_dir(sid) / "work").glob("*"))


def test_a_session_left_running_by_a_restart_is_marked_failed_and_can_continue():
    s = store.create(scene="courtyard", minutes=1)
    s["status"], s["step"] = store.RUNNING, "audio"
    store.save(s)
    other = store.create(scene="courtyard", minutes=1)               # not running: untouched
    assert store.repair() == 1
    now = store.get(s["id"])
    assert now["status"] == store.FAILED and now["step"] == "" and "restarted" in now["error"]
    assert store.get(other["id"])["status"] == store.NEW


# ── music for a long video: several different takes, no intro or ending, a seamless cycle ───────

def test_loopable_music_has_no_intro_or_outro_and_other_users_keep_theirs():
    from story3 import music as music_mod
    plain = music_mod.lyrics_for(5)
    assert plain.startswith("[intro]") and "[outro]" in plain
    loop = music_mod.lyrics_for(5, loopable=True)
    assert "[intro]" not in loop and "[outro]" not in loop and loop.count("[") == 5
    assert loop.count("[instrumental]") == 5 and "[verse]" not in loop and "[bridge]" not in loop          # empty sung sections made wordless humming
    assert "[instrumental]" not in plain and "[verse]" in music_mod.lyrics_for(6)                          # other users unchanged
    assert M.take_count(300) == 2 and M.take_count(60) == 1 and M.take_count(10800) == M.MUSIC_TAKES


def test_the_music_cycle_joins_takes_and_repeats_without_a_gap(tmp_path):
    import subprocess
    import config
    from relaxation import audio
    srcs = []
    for i, f in enumerate((220, 262, 330)):
        p = tmp_path / f"t{i}.wav"
        _ff("-f", "lavfi", "-i", f"sine=f={f}:d=40", "-af", "volume='min(1,t/3)':eval=frame,afade=t=out:st=36:d=4", str(p))   # each take swells in and dies away
        srcs.append(p)
    items = []
    for i, p in enumerate(srcs):
        items.append({"file": str(p)})
    monkey = __import__("pytest").MonkeyPatch()
    monkey.setattr(audio.media, "path_of", lambda it: Path(it["file"]))
    try:
        work = tmp_path / "w"
        work.mkdir()
        bed = audio._music_bed(items, 400.0, work, -20.0, 1)
    finally:
        monkey.undo()
    assert bed is not None and abs(audio._rain_duration(bed) - 400.0) < 1
    assert abs(audio._loudness(bed) - -20.0) < 3
    log = subprocess.run([config.FFMPEG, "-hide_banner", "-nostats", "-i", str(bed), "-af", "silencedetect=n=-50dB:d=0.4", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    assert "silence_start" not in log.replace("silence_start: 0", "").replace("silence_start: -", "") or log.count("silence_start") <= 1   # only the soft fade-in at the very start may be quiet


# ── the rain must really move ────────────────────────────────────────────────

def test_a_clip_that_barely_moves_is_made_again_and_the_better_one_is_kept(monkeypatch):
    sid = _session_with_scene(None)
    pcts = iter([0.3, 3.1])
    calls = []

    async def run_clip(*a, **k):
        it = media.add(sid, M.KIND_RAIN, "rain", 0, "done", {"seed": a[2], "guidance": a[6]})
        calls.append((a[2], a[6]))
        return media.update(it["id"], file="rain/x.mp4", meta={"motion": {"changed_pixels_pct": next(pcts)}})
    monkeypatch.setattr(rain, "_clip", run_clip)
    got = asyncio.run(rain.generate(sid, _settings(), "k", force=True))
    seed = store.get(sid)["settings"]["seed"]
    assert calls == [(seed, M.RAIN_GUIDANCE), (seed + 1, M.RAIN_GUIDANCE_RETRY)]
    assert got["meta"]["motion"]["changed_pixels_pct"] == 3.1 and store.chosen(sid, M.KIND_RAIN)["id"] == got["id"]
    assert [i["status"] for i in media.items(sid, M.KIND_RAIN)].count("failed") == 1      # the weak one is out of the way


def test_a_good_clip_is_made_once(monkeypatch):
    sid = _session_with_scene(None)
    calls = []

    async def run_clip(*a, **k):
        calls.append(1)
        it = media.add(sid, M.KIND_RAIN, "rain", 0, "done", {})
        return media.update(it["id"], file="rain/x.mp4", meta={"motion": {"changed_pixels_pct": 3.4}})
    monkeypatch.setattr(rain, "_clip", run_clip)
    asyncio.run(rain.generate(sid, _settings(), "k", force=True))
    assert calls == [1]


def test_clip_request_carries_guidance_and_the_scene_prompts_are_wet():
    b = rain._rain_body(b"x", 7, "monastery_window")
    assert b["guidance"] == b["guidance_low"] == M.RAIN_GUIDANCE >= 5
    assert all(v["prompt"].startswith(M.WET) for v in M.SCENES.values())


def test_motion_measure_tells_a_still_clip_from_a_moving_one(tmp_path):
    from relaxation import motion
    still, moving = tmp_path / "still.mp4", tmp_path / "moving.mp4"
    _ff("-f", "lavfi", "-i", "color=c=gray:s=160x90:d=3:r=16", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(still))
    _ff("-f", "lavfi", "-i", "testsrc2=s=160x90:d=3:r=16", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(moving))
    a, b = motion.measure(still), motion.measure(moving)
    assert motion.weak(a) and a["changed_pixels_pct"] < 0.5
    assert not motion.weak(b) and b["changed_pixels_pct"] > 2
    assert motion.measure(tmp_path / "missing.mp4") == {} and not motion.weak({})


def test_the_loop_path_itself_works_and_has_no_step_at_the_seam(tmp_path):
    """Called directly: the fallback in video.make would hide a broken loop filter."""
    import re
    import subprocess
    import config
    from relaxation import video
    clip, aud = tmp_path / "c.mp4", tmp_path / "a.wav"
    _ff("-f", "lavfi", "-i", "testsrc2=s=128x72:d=3:r=16", "-vf", "eq=brightness='t*0.05'", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip))   # it brightens over its length
    _ff("-f", "lavfi", "-i", "sine=f=330:d=10", str(aud))
    work = tmp_path / "w"
    work.mkdir()
    video._encode_by_loop(clip, aud, 10.0, 128, 72, work, tmp_path / "o.mp4")
    seg = subprocess.run([config.FFMPEG, "-hide_banner", "-i", str(work / "loop.mp4")], capture_output=True, text=True).stderr
    secs = float(re.search(r"Duration: 00:00:0?([\d.]+)", seg).group(1))
    assert abs(secs - (3.0 - M.SEAM_S)) < 0.2                       # the loop is the clip minus the seam


# ── disk: deleting a session removes everything, the mix goes once the video exists, the storage page lists rain videos ──

def _put(sid, kind, key, rel, size=1000, status="done"):
    it = media.add(sid, kind, key, 0, status, {})
    p = media.media_dir(sid) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    return media.update(it["id"], file=rel)


def test_deleting_a_session_removes_every_file_including_the_2k_clip_and_the_folder():
    sid = store.create(scene="courtyard", minutes=1)["id"]
    _put(sid, M.KIND_FINAL, "final", "final/final-a1.mp4")
    _put(sid, M.KIND_RAIN, "rain", "rain/rain-a1.mp4")
    (media.media_dir(sid) / "rain" / "rain-a1-2k.mp4").write_bytes(b"y" * 500)          # has no media row
    (media.media_dir(sid) / "work" / "x").mkdir(parents=True)
    (media.media_dir(sid) / "work" / "x" / "tmp.wav").write_bytes(b"z")
    folder = media.media_dir(sid)
    store.delete(sid)
    assert not folder.exists()
    assert media.items(sid) == []


def test_the_audio_mix_is_removed_once_the_video_exists_and_the_card_still_shows_audio_ready():
    from relaxation import audio
    sid = store.create(scene="courtyard", minutes=1)["id"]
    a = _put(sid, M.KIND_AUDIO, "audio", "audio/audio-a1.wav", 5000)
    assert audio.drop_mix(sid) == 0 and (media.media_dir(sid) / "audio" / "audio-a1.wav").exists()        # no video yet: keep it
    _put(sid, M.KIND_FINAL, "final", "final/final-a1.mp4")
    assert audio.drop_mix(sid) == 5000
    assert not (media.media_dir(sid) / "audio" / "audio-a1.wav").exists()
    v = store.view(store.get(sid))
    assert v["audio_ready"] and v["final_ready"] and store.chosen(sid, M.KIND_AUDIO) is None


def test_a_finished_video_is_not_rebuilt_when_generate_is_pressed_again(monkeypatch):
    from relaxation import auto, image, publish, thumb, video
    from relaxation import audio as audio_mod
    sid = store.create(scene="courtyard", minutes=1)["id"]
    _put(sid, M.KIND_FINAL, "final", "final/final-a1.mp4")
    calls = []

    async def ok(name):
        async def f(*a, **k):
            calls.append(name)
            return {}
        return f
    for mod, fn in ((image, "generate"), (rain, "generate"), (rain, "upscale"), (audio_mod, "make"), (video, "make"), (publish, "generate")):
        monkeypatch.setattr(mod, fn, asyncio.run(ok(f"{mod.__name__}.{fn}")))
    monkeypatch.setattr(thumb, "make", lambda *a, **k: calls.append("thumb"))
    monkeypatch.setattr(auto.settings_mod, "get", lambda: {"base_url": "x"})
    monkeypatch.setattr(auto.settings_mod, "api_key", lambda: "k")
    asyncio.run(auto.run(sid))
    assert not any(c.endswith("audio.make") or c.endswith("video.make") for c in calls)
    assert store.get(sid)["status"] == store.READY


def test_the_storage_page_lists_rain_videos_with_their_title(tmp_path):
    from admin import storage
    sid = store.create(scene="courtyard", minutes=1)["id"]
    _put(sid, M.KIND_FINAL, "final", "final/final-a1.mp4", 4000)
    _put(sid, M.KIND_AUDIO, "audio", "audio/audio-a1.wav", 2000)
    ov = storage.overview()
    p = next(x for x in ov["projects"] if x["id"] == sid)
    assert p["kind"] == "rain" and p["bytes"] == 6000 and "Courtyard" in p["title"]
    r = storage.clear(sid, "folders", ["audio"], dry_run=False)
    assert r["freed_bytes"] == 2000 and (media.media_dir(sid) / "final" / "final-a1.mp4").exists()


def test_drop_after_upload_frees_big_files_and_keeps_small(tmp_path):
    sid = _session_with_scene(tmp_path)
    kept = media.add(sid, M.KIND_RAIN, "rain", 0, "done", {})
    d = media.media_dir(sid, "rain")
    (d / "rain-a1.mp4").write_bytes(b"clip")
    (d / "rain-a1-2k.mp4").write_bytes(b"2k" * 100)
    media.update(kept["id"], file="rain/rain-a1.mp4")
    rows = {}
    for kind, sub, name in ((M.KIND_AUDIO, "audio", "audio-a1.wav"), (M.KIND_FINAL, "final", "final-a1.mp4")):
        it = media.add(sid, kind, kind, 0, "done", {})
        (media.media_dir(sid, sub) / name).write_bytes(b"x" * 1000)
        rows[kind] = media.update(it["id"], file=f"{sub}/{name}")

    assert store.drop_after_upload(sid) == 0                       # not on YouTube yet: nothing is removed
    assert media.path_of(rows[M.KIND_FINAL]).is_file()

    s = store.get(sid)
    s["youtube_video_id"] = "abc"
    s["status"] = store.UPLOADED
    store.save(s)
    assert store.drop_after_upload(sid) == 2200
    assert not media.path_of(rows[M.KIND_FINAL]).exists() and not media.path_of(rows[M.KIND_AUDIO]).exists()
    assert not (d / "rain-a1-2k.mp4").exists()
    assert (d / "rain-a1.mp4").is_file() and store.chosen(sid, M.KIND_SCENE)      # small files stay
    assert media.get(rows[M.KIND_FINAL]["id"])["meta"]["removed_after_upload"] is True
    assert store.view(store.get(sid))["video_removed"] is True
    assert store.drop_after_upload(sid) == 0                       # again: nothing left


def test_stream_answers_byte_ranges(tmp_path):
    """The page's player seeks in a 3 hour file with Range requests; there is no attachment header, so it plays inline."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from relaxation import api as rapi
    sid = _session_with_scene(tmp_path)
    it = media.add(sid, M.KIND_FINAL, M.KIND_FINAL, 0, "done", {})
    data = bytes(range(256)) * 4
    (media.media_dir(sid, "final") / "final-a1.mp4").write_bytes(data)
    media.update(it["id"], file="final/final-a1.mp4")
    assert "/stream?v=" in store.view(store.get(sid))["stream_url"]

    app = FastAPI()
    app.include_router(rapi.router)
    c = TestClient(app)
    r = c.get(f"/api/relaxation/{sid}/stream", headers={"Range": "bytes=100-199"})
    assert r.status_code == 206 and r.content == data[100:200] and r.headers["content-range"] == "bytes 100-199/1024"
    assert "attachment" not in r.headers.get("content-disposition", "")
    assert c.get("/api/relaxation/rl-00000000/stream").status_code == 404


def test_run_status_follows_the_youtube_upload_job(tmp_path):
    """The page polls /run for a session; while the YouTube upload (its own job, keyed `<id>:upload`) runs, that call shows its progress."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from relaxation import api as rapi
    from story2 import jobs
    sid = _session_with_scene(tmp_path)
    app = FastAPI()
    app.include_router(rapi.router)
    c = TestClient(app)
    jobs._jobs.pop(sid, None)
    jobs._jobs.pop(sid + ":upload", None)
    assert c.get(f"/api/relaxation/{sid}/run").json()["state"] == "idle"
    jobs._jobs[sid + ":upload"] = {"state": "running", "kind": "yt_upload", "started": 0, "done": 100, "total": 400, "label": "uploading 100 / 400 MB", "error": ""}
    try:
        j = c.get(f"/api/relaxation/{sid}/run").json()
        assert j["kind"] == "yt_upload" and j["done"] == 100 and j["total"] == 400
    finally:
        jobs._jobs.pop(sid + ":upload", None)


def test_streaks_that_keep_their_places_are_weak(tmp_path):
    """A clip with the same streak pattern in every frame (rain that does not fall) must fail the check; streaks that are new in
    every frame pass."""
    from relaxation import motion
    fixed, falling = tmp_path / "fixed.mp4", tmp_path / "falling.mp4"
    enc = ["-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p"]
    _ff("-f", "lavfi", "-i", "color=c=0x303030:s=320x180:d=4:r=16", "-vf", "noise=alls=70:allf=u", *enc, str(fixed))
    _ff("-f", "lavfi", "-i", "color=c=0x303030:s=320x180:d=4:r=16", "-vf", "noise=alls=70:allf=t+u", *enc, str(falling))
    a, b = motion.measure(fixed), motion.measure(falling)
    assert a["streak_same"] > motion.MAX_STREAK_SAME and motion.weak(a)
    assert b["streak_same"] < 0.5 and not motion.weak(b)


def test_no_scene_picture_asks_for_rain_in_the_air():
    """The rain is drawn by code; a picture with streaks in it would show fixed lines under the falling ones."""
    import re
    for k, v in M.SCENES.items():
        assert not re.search(r"rain (falling|pouring|streaming|hammering|running|pocking|dripping|rings)|rain streaks|falling rain|silver (lines|threads)", v["prompt"], re.I), k


def test_code_engine_makes_a_4k_seamless_loop_and_skips_the_upscale(tmp_path, monkeypatch):
    """rain.generate on a new session: the window finder (a fake here) and rainfx.render are used, no Wan job, no upscale step."""
    from relaxation import rainfx, zones as zmod
    from story import llm
    monkeypatch.setattr(M, "RAIN_ENGINE", "code")
    sid = _session_with_scene(tmp_path)
    assert rain.engine(sid) == "code" and store.get(sid)["settings"]["rain_engine"] == "code"
    asked = {}

    async def fake_find(pic, backend, s):
        asked["pic"] = pic
        return {"view": [0.1, 0.1, 0.9, 0.9], "water": [[0.3, 0.7, 0.6, 0.85]], "hard": [], "source": "vision"}

    def fake_render(pic, z, out, size, seed, loop_s, flame):
        asked["size"], asked["flame"], asked["loop_s"] = size, flame, loop_s
        out.write_bytes(b"mp4")
        return out
    monkeypatch.setattr(zmod, "find", fake_find)
    monkeypatch.setattr(rainfx, "render", fake_render)
    monkeypatch.setattr(llm, "ChatBackend", lambda s, k: object())

    async def boom(*a, **k):
        raise AssertionError("no Wan job for the code engine")
    monkeypatch.setattr(wan, "submit", boom)
    row = asyncio.run(rain.generate(sid, {"base_url": "http://gw/v1"}, "k"))
    assert row["status"] == "done" and row["file"].startswith("rain/") and row["meta"]["engine"] == "code" and row["meta"]["seamless"]
    assert asked["size"] == M.OUT_4K and asked["loop_s"] == rainfx.LOOP_S and row["meta"]["zones"]["water"]
    assert asyncio.run(rain.generate(sid, {"base_url": "http://gw/v1"}, "k"))["id"] == row["id"]            # a finished one is kept


def test_rainfx_renders_a_loop_that_comes_round_and_falls(tmp_path, monkeypatch):
    """A small real render: 2 s loop, rain in the view, every frame drawn; the last frame leads into the first (no jump), and the streaks move."""
    from PIL import Image
    from relaxation import motion, rainfx
    assert not rainfx.STREAKS and not rainfx.ROCK_BURSTS and rainfx.MIST > 0            # the owner's look: glass drops, mist, bokeh, ripples; no streaks, no rock splashes
    monkeypatch.setattr(rainfx, "STREAKS", True)                                          # the streak code still works when switched on
    monkeypatch.setattr(rainfx, "ROCK_BURSTS", True)
    pic = tmp_path / "p.jpg"
    Image.new("RGB", (640, 360), (40, 60, 90)).save(pic)
    out = tmp_path / "loop.mp4"
    rainfx.render(pic, {"view": [0.1, 0.1, 0.9, 0.9], "water": [[0.2, 0.7, 0.8, 0.88]], "hard": [[0.2, 0.62, 0.5, 0.7]]}, out, size=(640, 360), seed=3, loop_s=2.0, flame=True)
    m = motion.measure(out)
    assert m["frames"] == int(round(rainfx.FPS * 2.0)) and m["changed_pixels_pct"] > 0.3
    assert m["streak_same"] < motion.MAX_STREAK_SAME and not motion.weak(m)


def test_zones_cleaning_keeps_splashes_to_the_ground_and_falls_back_on_nonsense():
    from relaxation import zones
    z = zones.clean(zones.ZonesOut(view=[0.1, 0.1, 0.9, 0.9], water=[[0.2, 0.2, 0.5, 0.4], [0.2, 0.7, 0.5, 0.85]], hard=[[0.0, 0.0, 1.0, 1.0]]))
    assert z["view"] == [0.1, 0.1, 0.9, 0.9]
    ground = 0.1 + 0.45 * 0.8
    assert len(z["water"]) == 1                                       # the box above the ground is dropped, not flipped
    assert all(b[1] >= ground - 1e-6 for b in z["water"] + z["hard"]) and z["hard"] and z["hard"][0][0] >= 0.1
    assert zones.clean(zones.ZonesOut(view=[0.4, 0.4, 0.5, 0.5]))["source"] == "fallback"


def test_video_uses_the_4k_size_and_a_bitrate_cap_for_the_code_loop():
    from relaxation import video
    assert video._out_size(False, True) == M.OUT_4K == (3840, 2160)
    assert video._out_size(True) == (2560, 1440) and video._out_size(False) == (M.OUT_W, M.OUT_H)
    assert video.MAXRATE == "13M"


def test_thumbnail_person_prompt_names_the_themes_view_and_alternates():
    assert {M.thumb_person(s) for s in range(10)} == {"woman", "man"}
    assert set(M.THUMB_VIEWS) == set(M.SCENES)
    p = M.thumb_prompt("old_town_lane", "man")
    assert "young man" in p and "cobblestone lane" in p and "right side of the frame" in p and "No text" in p
    assert "young woman" in M.thumb_prompt("old_town_lane", "anything else")            # an unknown value never leaks into the prompt


def test_thumbnail_uses_the_person_picture_and_falls_back_to_the_scene(tmp_path, monkeypatch):
    import base64
    import io
    from PIL import Image
    from relaxation import thumb
    sid = _session_with_scene(tmp_path)
    scene_path = media.path_of(store.chosen(sid, M.KIND_SCENE))
    Image.new("RGB", (1280, 720), (20, 40, 80)).save(scene_path)
    row = thumb.make(sid)                                               # no person picture: the scene picture
    assert row["meta"]["source"] == "scene"
    sent = {}
    buf = io.BytesIO(); Image.new("RGB", (1280, 720), (200, 120, 40)).save(buf, "JPEG")

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, headers=None, json=None):
            sent.update(json=json, url=url)
            import httpx
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(buf.getvalue()).decode()}]})
    monkeypatch.setattr(thumb.httpx, "AsyncClient", FakeClient)
    pic = asyncio.run(thumb.picture(sid, {"base_url": "http://gw/v1"}, "k", person="man"))
    assert pic["status"] == "done" and pic["meta"]["person"] == "man" and store.get(sid)["settings"]["thumb_person"] == "man"
    assert "young man" in sent["json"]["prompt"] and sent["json"]["size"] == "1280x720" and sent["url"].endswith("/images/generations")
    again = thumb.make(sid, force=True)
    assert again["meta"]["source"] == "person" and again["id"] != row["id"]
    assert asyncio.run(thumb.picture(sid, {"base_url": "http://gw/v1"}, "k"))["id"] == pic["id"]       # kept unless forced

    class Down(FakeClient):
        async def post(self, url, headers=None, json=None):
            import httpx
            return httpx.Response(500, text="boom")
    monkeypatch.setattr(thumb.httpx, "AsyncClient", Down)
    with pytest.raises(Exception, match="thumbnail picture failed"):
        asyncio.run(thumb.picture(sid, {"base_url": "http://gw/v1"}, "k", force=True))


def test_no_theme_offers_a_cello_and_the_tempo_and_caption_follow_the_owners_changes():
    assert not any(ins in M.MUSIC_AVOID for v in M.SCENES.values() for ins in v["instruments"])
    assert all(len(v["instruments"]) >= 3 for v in M.SCENES.values())               # enough for the never-the-same-twice rule
    assert M.MUSIC_BPM == (64, 72) and M.MUSIC_TRIM_END_S > M.MUSIC_TRIM_S
    assert "melody" not in M.music_caption("harp", "warm pad", "serene", 68) and "no vocals" in M.music_caption("harp", "warm pad", "serene", 68)


def test_regenerating_an_old_plan_drops_the_cello_and_the_slow_tempo(tmp_path, monkeypatch):
    from relaxation import audio, publish
    from story3 import music as music_mod
    sid = _session_with_video(tmp_path)

    async def fake_music(plan_id, cfg, total_s, s, key, progress=None, force=False):
        it = media.add(plan_id, "music", "bgm", 0, "done", {"duration_s": 60.0})
        _ff("-f", "lavfi", "-i", "sine=f=330:d=60", str(media.media_dir(plan_id, "music") / "bgm-a1.wav"))
        return media.update(it["id"], file="music/bgm-a1.wav")

    async def no_publish(*a, **k):
        return {}
    monkeypatch.setattr(music_mod, "make", fake_music)
    monkeypatch.setattr(publish, "generate", no_publish)
    s = store.get(sid)
    s["settings"]["music_plan"] = {"instrument": "cello", "secondary": "warm pad", "mood": "warm", "bpm": 56,
                                   "caption": "English, ambient, sleep music, tranquil, warm, 56 BPM, cello, warm pad, instrumental, no vocals, no percussion, soft dynamics"}
    store.save(s)
    asyncio.run(audio.regenerate_music(sid, {"base_url": "x"}, "k"))                 # no instrument asked for: the old plan is brought up to date
    plan = store.get(sid)["settings"]["music_plan"]
    assert plan["instrument"] not in M.MUSIC_AVOID and plan["instrument"] in M.SCENES["courtyard"]["instruments"]
    assert M.MUSIC_BPM[0] <= plan["bpm"] <= M.MUSIC_BPM[1] and "cello" not in plan["caption"]
    # an old plan with a good instrument and a slow tempo keeps the instrument and gets a new tempo
    s = store.get(sid)
    s["settings"]["music_plan"] = {"instrument": "harp", "secondary": "warm pad", "mood": "warm", "bpm": 55, "caption": "x"}
    store.save(s)
    asyncio.run(audio.regenerate_music(sid, {"base_url": "x"}, "k"))
    plan = store.get(sid)["settings"]["music_plan"]
    assert plan["instrument"] == "harp" and M.MUSIC_BPM[0] <= plan["bpm"] <= M.MUSIC_BPM[1] and "harp" in plan["caption"]
