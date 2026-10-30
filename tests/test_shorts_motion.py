"""Single-shot Animate: a short reference clip drives one shot; no 30 s minimum; rights gate; the clip request carries the start picture and the window."""
import pytest

from shorts_fakes import tiny_mp4
from test_shorts import S, gw, needs_ffmpeg, run  # noqa: F401 - fixtures
from test_shorts_avatar import avatar_short
from story3 import store as media

from shorts import checks, clips, models, motion, pipelines as P, store, voice as svoice


@needs_ffmpeg
def test_a_five_second_reference_drives_one_shot_and_the_clip_is_an_animate_request(gw, env, tmp_path):
    short, sid = avatar_short()
    sh = next(s for s in short["shots"] if s["id"] == sid)
    sh["avatar"] = False
    store.save(short)
    run(svoice.make(short["id"], s=S, key="k"))
    run(clips.make_keyframes(short["id"], s=S, key="k"))
    ref = tiny_mp4(tmp_path / "reel.mp4", frames=16 * 5, fps=16, size="160x90")
    m = motion.prepare(short["id"], sid, ref, 1.0, "a reel", "", rights=True)
    assert m["length"] == pytest.approx(3.4, abs=0.01) and m["source_s"] == pytest.approx(5.0, abs=0.2) and (store.media_dir(short["id"]) / m["file"]).is_file()
    short = store.get(short["id"])
    assert not [i for i in checks.run(short)["issues"] if i["code"].startswith("motion_") and i["level"] == "block"]
    res = run(clips.make_clips(short["id"], [sid], s=S, key="k"))
    assert res["made"] == 1 and not res["failed"]
    body = gw.requests[-1]
    assert body["model"] == models.ANIMATE and body["image"].startswith("data:image/jpeg") and body["driving_video"].startswith("data:video/mp4") and body["keep_audio"] is False
    shot = next(s for s in store.get(short["id"])["shots"] if s["id"] == sid)
    assert clips.chosen_clip(store.get(short["id"]), shot)
    motion.clear(short["id"], sid)
    assert not (store.media_dir(short["id"]) / m["file"]).exists() and "motion" not in next(s for s in store.get(short["id"])["shots"] if s["id"] == sid)


@needs_ffmpeg
def test_the_rights_box_and_a_missing_file_block_make(gw, env, tmp_path):
    short, sid = avatar_short()
    short = store.get(short["id"])
    sh = next(s for s in short["shots"] if s["id"] == sid)
    sh["motion"] = {"file": "motion/x.mp4", "start": 0, "length": 3, "title": "", "url": "", "rights": False}
    store.save(short)
    codes = {i["code"] for i in checks.run(store.get(short["id"]))["issues"]}
    assert {"motion_rights", "motion_file"} <= codes


def test_a_link_from_instagram_is_accepted_for_a_shot_and_a_foreign_host_is_not():
    from shorts import remix
    assert remix.check_url("https://www.instagram.com/reel/abc/")
    with pytest.raises(Exception):
        remix.check_url("https://tiktok.com/@x/video/1")
