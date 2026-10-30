"""The avatar tab: the voice choice, the ready test (clip made with the picture and the voice, judged on mouth, hands and identity) and what is kept on the character."""
import asyncio

import pytest
from fastapi.testclient import TestClient

import config
from characters import avatar, store as cstore
from shorts import models, wan
from shorts_fakes import tiny_mp4, tone_wav
from story3 import store as media
from test_shorts_cast import make_char
from test_shorts import S, gw, needs_ffmpeg, run  # noqa: F401 - fixtures


def test_the_verdict_needs_a_moving_mouth_natural_hands_and_the_same_person():
    assert avatar.verdict({"mouth": 8, "hands": 8, "identity": 9}) == "pass"
    for weak in ({"mouth": 3, "hands": 9, "identity": 9}, {"mouth": 9, "hands": 4, "identity": 9}, {"mouth": 9, "hands": 9, "identity": 5}):
        assert avatar.verdict(weak) == "weak"


@needs_ffmpeg
def test_the_ready_test_makes_a_clip_judges_it_and_keeps_the_result_with_the_character(gw, env, monkeypatch, tmp_path):
    char = make_char()
    sent = {}

    async def speak(c, s, key):
        return tone_wav(2.0)

    async def fake_run(body, base, key, on_job=None, limit_s=0, background=False):
        sent.update(body)
        if on_job:
            on_job("job_1")
        return tiny_mp4(tmp_path / "talk.mp4", 75, 25).read_bytes(), {"frames": 75}

    async def fake_judge(portrait, shots, s=None, key=""):
        sent["frames_judged"] = len(shots)
        return {"mouth": 8.0, "hands": 7.0, "identity": 9.0, "notes": ["fine"]}
    monkeypatch.setattr(avatar, "_speak", speak)
    monkeypatch.setattr(wan, "run", fake_run)
    monkeypatch.setattr(avatar, "judge", fake_judge)
    res = run(avatar.run_test(char["id"], s=S, key="k"))
    assert res["state"] == "pass" and sent["model"] == models.TALK and sent["image"].startswith("data:image/jpeg") and sent["audio"].startswith("data:audio/wav") and sent["duration"] == 3.0
    assert sent["frames_judged"] == avatar.SAMPLES
    c2 = cstore.get(char["id"])
    st = avatar.ready_state(c2)
    assert st["state"] == "pass" and not st["stale"] and st["mouth"] == 8.0
    it = media.items(char["id"], avatar.KIND)[-1]
    assert it["status"] == "done" and (cstore.media_dir(char["id"]) / it["file"]).is_file()
    c2["version"] += 1
    cstore.save(c2)
    assert avatar.ready_state(cstore.get(char["id"]))["stale"], "a new canon picture makes the old test old"


def test_the_test_needs_an_approved_portrait(gw, env):
    char = make_char(canon=False)
    with pytest.raises(Exception, match="approve a portrait"):
        run(avatar.run_test(char["id"], s=S, key="k"))


def test_api_voice_choice_is_validated_and_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    import main
    with TestClient(main.app) as c:
        c.post("/login", data={"username": config.APP_USER, "password": config.APP_PASSWORD})
        cid = c.post("/api/characters", json={"name": "Saira", "kind": "person"}).json()["id"]
        ok = c.patch(f"/api/characters/{cid}/avatar", json={"voice": {"engine": "maya-tts", "voice": "Ahana"}})
        assert ok.status_code == 200 and ok.json()["avatar"]["voice"] == {"engine": "maya-tts", "voice": "Ahana"}
        assert c.patch(f"/api/characters/{cid}/avatar", json={"voice": {"engine": "maya-tts", "voice": "Nobody"}}).status_code == 400
        assert c.patch(f"/api/characters/{cid}/avatar", json={"voice": {}}).json()["avatar"]["voice"] == {}
        assert c.post(f"/api/characters/{cid}/avatar/test").status_code == 400, "no portrait yet"
