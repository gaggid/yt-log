"""Phase 3, batch E: voice generation from the export, real audio length, and retiming scenes to it."""
import asyncio
import io
import wave

import httpx
import pytest

from story2 import editorial, export, imgplan, planner, storyboard
from story3 import store, voice
from test_phase2b import boarded

SETTINGS = {"base_url": "http://gw/v1"}


def silence(seconds: float) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00\x00" * int(24000 * seconds))
    return buf.getvalue()


class Gateway:
    """Stands in for the model server: answers speech requests with silence whose length follows the word count (2 words a second)."""

    def __init__(self, fail_for=(), always=None):
        self.requests, self.fail_for, self.always = [], set(fail_for), always

    def client(self):
        gw = self

        class C:
            def __init__(self, *a, **k): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False

            async def post(self, url, json=None, headers=None):
                gw.requests.append({"url": url, "body": json, "auth": headers})
                if gw.always is not None:
                    return gw.always
                n = len(gw.requests)
                if n in gw.fail_for:
                    return httpx.Response(502, text="Speech engine error")
                words = len(json["input"].split())
                return httpx.Response(200, content=silence(max(1.0, words / 2.0)))
        return C


@pytest.fixture
def fast(monkeypatch):
    async def nosleep(_):
        return None
    monkeypatch.setattr(voice.asyncio, "sleep", nosleep)


def exported(env, **kw):
    pid, cid, be, p = boarded(env, **kw)
    plan_id = p["id"]
    imgplan.compile_plan(plan_id)
    plan = planner.get_plan(plan_id)
    for s in plan["segments"]:
        planner.edit_segment(s["id"], status="approved")
    for sc in plan["scenes"]:
        storyboard.edit_scene(sc["id"], {"status": "approved"})
    export.save(plan_id)
    return plan_id


def run(plan_id, gw, monkeypatch, **kw):
    monkeypatch.setattr(voice.httpx, "AsyncClient", gw.client())
    return asyncio.run(voice.generate(plan_id, s=SETTINGS, key="k", **kw))


def test_one_request_per_segment_with_the_proven_settings(env, monkeypatch, fast):
    plan_id = exported(env)
    gw = Gateway()
    out = run(plan_id, gw, monkeypatch)
    segs = planner.get_plan(plan_id)["segments"]
    assert len(gw.requests) == len(segs) == out["made"] and not out["failed"]
    r = gw.requests[0]
    assert r["url"] == "http://gw/v1/audio/speech" and r["auth"]["Authorization"] == "Bearer k"
    b = r["body"]
    assert b["model"] == "svara-tts" and b["voice"] == "hi_male" and b["response_format"] == "wav" and b["seed"] == 7
    assert b["temperature"] == 0.6 and b["repetition_penalty"] == 1.25 and b["input"] == segs[0]["annotated"]    # the tagged text goes in untouched
    assert all(store.path_of(i).is_file() for i in store.items(plan_id, "voice"))


def test_scenes_are_retimed_to_the_real_audio(env, monkeypatch, fast):
    plan_id = exported(env)
    before = planner.get_plan(plan_id)
    run(plan_id, Gateway(), monkeypatch)
    plan = planner.get_plan(plan_id)
    real = store.audio_seconds(plan_id)
    assert set(real) == {s["id"] for s in plan["segments"]}
    for seg in plan["segments"]:
        assert abs(seg["duration_s"] - real[seg["id"]]) < 0.05                                                  # the plan's spoken time is now measured, not guessed
        scenes = sorted((s for s in plan["scenes"] if s["segment_id"] == seg["id"]), key=lambda s: s["start_s"])
        assert abs(sum(s["duration_s"] for s in scenes) - real[seg["id"]]) < 0.1                                # scenes still tile the audio exactly
    assert abs(plan["scenes"][-1]["end_s"] - sum(real.values())) < 0.2
    assert plan["duration_s"] != before["duration_s"]


def test_making_the_voice_does_not_make_an_approved_plan_look_changed(env, monkeypatch, fast):
    plan_id = exported(env)
    ap = editorial.approve(plan_id)
    assert ap["state"] == "approved"
    run(plan_id, Gateway(), monkeypatch)
    assert editorial.approval_state(planner.get_plan(plan_id))["state"] == "approved"                           # timings are derived data
    assert export.list_exports(plan_id)[0]["content_hash"] == editorial.content_hash(planner.get_plan(plan_id))


def test_only_missing_skips_finished_segments_and_regenerate_keeps_old_attempts(env, monkeypatch, fast):
    plan_id = exported(env)
    gw = Gateway()
    run(plan_id, gw, monkeypatch)
    n = len(gw.requests)
    run(plan_id, gw, monkeypatch)
    assert len(gw.requests) == n                                                                                # nothing missing: no requests
    sid = planner.get_plan(plan_id)["segments"][0]["id"]
    run(plan_id, gw, monkeypatch, segment_ids=[sid], only_missing=False)
    att = store.items(plan_id, "voice", sid)
    assert [a["attempt"] for a in att] == [1, 2] and att[1]["meta"]["seed"] != att[0]["meta"]["seed"]          # a new seed, the old file kept
    assert store.path_of(att[0]).is_file() and store.path_of(att[1]).is_file()


def test_approving_an_attempt_chooses_it_and_unchooses_its_siblings(env, monkeypatch, fast):
    plan_id = exported(env)
    gw = Gateway()
    run(plan_id, gw, monkeypatch)
    seg = planner.get_plan(plan_id)["segments"][0]
    run(plan_id, gw, monkeypatch, segment_ids=[seg["id"]], only_missing=False)
    a1, a2 = store.items(plan_id, "voice", seg["id"])
    assert store.chosen_voice(plan_id, seg, "hi_male")["id"] == a2["id"]                                         # latest counts until one is approved
    store.approve(a1["id"])
    assert store.chosen_voice(plan_id, seg, "hi_male")["id"] == a1["id"]
    store.approve(a2["id"])
    assert not store.get(a1["id"])["approved"] and store.get(a2["id"])["approved"]
    run(plan_id, gw, monkeypatch, only_missing=False)                                                           # "all again" makes new attempts but never touches the approved choice
    assert store.get(a2["id"])["approved"]


def test_changed_wording_makes_old_audio_stop_counting(env, monkeypatch, fast):
    plan_id = exported(env)
    run(plan_id, Gateway(), monkeypatch)
    seg = planner.get_plan(plan_id)["segments"][0]
    planner.edit_segment(seg["id"], sentences=[{"text": "बिल्कुल नया वाक्य", "emotion": "neutral", "pause_after_s": 0}])
    seg2 = planner.get_plan(plan_id)["segments"][0]
    assert store.chosen_voice(plan_id, seg2, "hi_male") is None and seg["id"] not in store.audio_seconds(plan_id)
    st = voice.state(plan_id)
    row = next(r for r in st["segments"] if r["segment_id"] == seg["id"])
    assert row["chosen"] is None and row["attempts"][0]["current"] is False and st["have"] == st["total"] - 1


def test_media_needs_a_current_export(env, monkeypatch, fast):
    pid, cid, be, p = boarded(env)
    imgplan.compile_plan(p["id"])
    with pytest.raises(voice.MediaError, match="export the plan first"):
        asyncio.run(voice.generate(p["id"], s=SETTINGS, key="k"))
    plan = planner.get_plan(p["id"])
    for s in plan["segments"]:
        planner.edit_segment(s["id"], status="approved")
    export.save(p["id"])
    storyboard.edit_scene(plan["scenes"][0]["id"], {"subject": "someone different"})
    with pytest.raises(voice.MediaError, match="changed after export v1"):
        asyncio.run(voice.generate(p["id"], s=SETTINGS, key="k"))


def test_a_failed_segment_is_recorded_and_the_rest_still_run(env, monkeypatch, fast):
    plan_id = exported(env)
    segs = len(planner.get_plan(plan_id)["segments"])
    gw = Gateway(fail_for={1, 2, 3})                                                                            # the first segment fails every try
    out = run(plan_id, gw, monkeypatch)
    assert out["made"] == segs - 1 and len(out["failed"]) == 1
    failed = [i for i in store.items(plan_id, "voice") if i["status"] == "failed"]
    assert len(failed) == 1 and "502" in failed[0]["meta"]["error"]
    run(plan_id, gw, monkeypatch)                                                                               # run again: only the missing one is made
    assert not [r for r in voice.state(plan_id)["segments"] if not r["chosen"]]


def test_unreachable_server_stops_the_job_with_a_clear_reason(env, monkeypatch, fast):
    plan_id = exported(env)

    class Down:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): raise httpx.ConnectError("refused")
    monkeypatch.setattr(voice.httpx, "AsyncClient", Down)
    out = asyncio.run(voice.generate(plan_id, s=SETTINGS, key="k"))
    assert out["made"] == 0 and len(out["failed"]) == 1 and "not reachable" in out["failed"][0]["error"]       # one clear failure, not a pile of retries


def test_unusual_length_is_flagged(env, monkeypatch, fast):
    plan_id = exported(env)
    gw = Gateway(always=httpx.Response(200, content=silence(1.0)))                                              # one second for a whole part
    run(plan_id, gw, monkeypatch)
    flags = [f for i in store.items(plan_id, "voice") for f in i["meta"]["flags"]]
    assert flags and "unusual length" in flags[0]


def test_state_reports_real_versus_estimated_and_an_honest_wait(env, monkeypatch, fast):
    plan_id = exported(env)
    st = voice.state(plan_id)
    assert st["have"] == 0 and st["export"]["current"] and st["eta_missing_s"] > 0 and st["speed_ratio"] == 3.7
    run(plan_id, Gateway(), monkeypatch)
    st = voice.state(plan_id)
    assert st["have"] == st["total"] and st["real_s"] > 0 and st["eta_missing_s"] == 0


def test_api_round_trip(tmp_path, monkeypatch):
    import config
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    with TestClient(main.app) as c:
        c.post("/login", data={"username": config.APP_USER, "password": config.APP_PASSWORD})
        assert c.get("/api/media/pl-nothing").status_code == 400
        from story import projects, review
        from fakellm import FakeBackend
        from test_pipeline import make_book, run as run1
        pid = projects.import_text(make_book(3, 8))
        run1(pid, FakeBackend())
        cid = review.list_candidates(pid)[0]["id"]
        review.update_candidate(cid, {"status": "approved"})
        plan = c.post("/api/plans", json={"candidate_id": cid}).json()
        r = c.post(f"/api/media/{plan['id']}/voice", json={})
        assert r.status_code == 400 and "export" in r.json()["detail"]                                          # refused up front, with the reason
        assert c.get(f"/api/media/{plan['id']}").json()["voice"]["total"] == 0
        assert c.get(f"/api/media/file/{plan['id']}/..%2F..%2Fx").status_code == 404
        assert c.patch("/api/media/item/md-missing", json={"approved": True}).status_code == 404


def test_a_later_export_carries_the_real_audio_and_still_matches_the_schema(env, monkeypatch, fast):
    from jsonschema import Draft202012Validator
    from story2.export_schema import SCHEMA
    plan_id = exported(env)
    first = export.build(plan_id, refresh=False)
    assert all("audio" not in s for s in first["public"]["narration"]["segments"])
    run(plan_id, Gateway(), monkeypatch)
    doc = export.build(plan_id, refresh=False)
    assert not list(Draft202012Validator(SCHEMA).iter_errors(doc))
    for s in doc["public"]["narration"]["segments"]:
        assert s["audio"]["file"].startswith("voice/") and s["audio"]["duration_s"] == pytest.approx(s["duration_s"], abs=0.05)
