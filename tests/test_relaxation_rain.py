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
    old = media.add(sid, M.KIND_RAIN, "rain", 0, "failed", {"frames": rain._FRAMES, "seed": 7, "job_id": "job_1", "error": "x"})

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
    old = media.add(sid, M.KIND_RAIN, "rain", 0, "failed", {"frames": rain._FRAMES, "seed": 7, "job_id": "job_1"})
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
    media.add(sid, M.KIND_RAIN, "rain", 0, "failed", {"frames": rain._FRAMES, "seed": 7, "job_id": "job_1"})

    async def resume(*a, **k):
        raise wan.WanError("the clip did not finish within 66 minutes", lost=True)

    async def submit(*a, **k):
        raise AssertionError("a job still running on the gateway must not be doubled")

    monkeypatch.setattr(wan, "resume", resume)
    monkeypatch.setattr(wan, "submit", submit)
    with pytest.raises(Exception, match="rain clip failed"):
        asyncio.run(rain.generate(sid, _settings(), "k"))


def test_clip_is_small_and_length_in_minutes():
    assert M.CLIP_SIZE == "832x480" and rain._FRAMES == 81
    assert M.estimate_rain_s(rain._FRAMES) < 900
    assert M.total_s({"minutes": 5, "hours": 3}) == 300 and M.total_s({"hours": 3}) == 10800 and M.total_s({}) == 10800
    assert M.duration_label({"minutes": 5}) == "5 minutes" and M.duration_label({"hours": 3}) == "3 hours"
    s = store.create(scene="forest", minutes=5)
    assert s["settings"]["minutes"] == 5


def test_scene_prompts_are_first_person():
    for k, v in M.SCENES.items():
        assert v["prompt"].startswith("First-person point of view"), k
