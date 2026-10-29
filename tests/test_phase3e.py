"""Phase 3, batch E: voice generation from the export, real audio length, and retiming scenes to it."""
import asyncio
import base64
import io
import wave

import httpx
import pytest

from story2 import editorial, export, imgplan, planner, storyboard, voices
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
        self.jobs, self.polls = {}, []

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
                audio = silence(max(1.0, words / 2.0))
                if (headers or {}).get("Prefer") == "respond-async":                       # Veena: a 202 job that is polled
                    gw.jobs[f"job_{n}"] = audio
                    return httpx.Response(202, json={"id": f"job_{n}", "status": "queued"})
                return httpx.Response(200, content=audio)

            async def get(self, url, headers=None):
                gw.polls.append(url)
                jid = url.rsplit("/", 1)[1]
                if len(gw.polls) % 2:                                                       # every job is "running" on its first check
                    return httpx.Response(200, json={"id": jid, "status": "running"})
                return httpx.Response(200, json={"id": jid, "status": "succeeded", "result": {"audio_b64": base64.b64encode(gw.jobs[jid]).decode()}})
        return C


@pytest.fixture
def fast(monkeypatch):
    async def nosleep(_):
        return None
    monkeypatch.setattr(voice.asyncio, "sleep", nosleep)


def exported(env, engine="svara-tts", **kw):
    """Most voice tests use Svara (the proven request); Veena has its own tests below."""
    pid, cid, be, p = boarded(env, **kw)
    plan_id = p["id"]
    planner.set_narrator(plan_id, None, tts={"engine": engine, "voice": voices.ENGINES[engine]["default_voice"]})
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


# ── Veena: the default engine ───────────────────────────────────────────────

def test_new_plans_use_maya_and_old_ones_keep_veena(env):
    pid, cid, be, p = boarded(env)
    assert voices.current(planner.get_plan(p["id"])["narrator"]) == {"engine": "maya-tts", "voice": "Siddhant"}
    assert voices.current({"voice": "hi_male"}) == {"engine": "veena-tts", "voice": "agastya"}          # a plan from before Veena existed


def test_veena_request_is_async_polled_and_has_no_emotion_tags(env, monkeypatch, fast):
    plan_id = exported(env, "veena-tts")
    gw = Gateway()
    out = run(plan_id, gw, monkeypatch)
    segs = planner.get_plan(plan_id)["segments"]
    assert out["made"] == len(segs) and not out["failed"] and gw.polls
    r = gw.requests[0]
    assert r["auth"]["Prefer"] == "respond-async"
    b = r["body"]
    assert b["model"] == "veena-tts" and b["voice"] == "agastya" and b["response_format"] == "wav"
    assert b["temperature"] == 0.4 and b["top_p"] == 0.9 and b["repetition_penalty"] == 1.05
    assert "<" not in b["input"] and b["input"] == voices.veena_text(segs[0])
    assert all(store.path_of(i).is_file() for i in store.items(plan_id, "voice"))


def test_veena_text_keeps_punctuation_and_adds_pauses():
    seg = {"sentences": [{"text": "उसने call उठाया...", "pause_after_s": 0.8}, {"text": "क्या हुआ था", "pause_after_s": 0}, {"text": "Bank खाली था.", "pause_after_s": 0}]}
    assert voices.veena_text(seg) == "उसने call उठाया... [pause:0.8s] क्या हुआ था। Bank खाली था."


def test_switching_voice_makes_old_takes_stop_counting_and_back_again(env, monkeypatch, fast):
    plan_id = exported(env, "svara-tts")
    run(plan_id, Gateway(), monkeypatch)
    plan = planner.get_plan(plan_id)
    seg = plan["segments"][0]
    assert store.chosen_voice(plan_id, seg, store.voice_key(plan))
    planner.set_narrator(plan_id, None, tts={"engine": "veena-tts", "voice": "agastya"})
    plan = planner.get_plan(plan_id)
    assert store.chosen_voice(plan_id, seg, store.voice_key(plan)) is None and not store.audio_seconds(plan_id)
    planner.set_narrator(plan_id, None, tts={"engine": "svara-tts", "voice": "hi_male"})
    assert store.chosen_voice(plan_id, seg, store.voice_key(planner.get_plan(plan_id)))


def test_voice_choice_does_not_change_the_approved_plan(env):
    plan_id = exported(env, "svara-tts")
    before = editorial.content_hash(planner.get_plan(plan_id))
    planner.set_narrator(plan_id, None, tts={"engine": "veena-tts", "voice": "kavya"})
    assert editorial.content_hash(planner.get_plan(plan_id)) == before
    voice.load_export(plan_id)                                                                            # the export still describes the plan


def test_tts_api_validates_engine_and_voice(env):
    from fastapi import HTTPException
    from story2 import api
    plan_id = exported(env)
    assert asyncio.run(api.voice_engines())["default"] == "maya-tts"
    for bad in ({"engine": "nope"}, {"engine": "veena-tts", "voice": "hi_male"}):
        with pytest.raises(HTTPException) as e:
            asyncio.run(api.set_tts(plan_id, api.Tts(**bad)))
        assert e.value.status_code == 400
    out = asyncio.run(api.set_tts(plan_id, api.Tts(engine="veena-tts", voice="kavya")))
    assert out["narrator"]["tts"] == {"engine": "veena-tts", "voice": "kavya"}


def test_a_voice_sample_is_one_short_take_in_the_chosen_voice(env, monkeypatch, fast):
    plan_id = exported(env, "veena-tts")
    gw = Gateway()
    monkeypatch.setattr(voice.httpx, "AsyncClient", gw.client())
    out = asyncio.run(voice.make_sample(plan_id, s=SETTINGS, key="k"))
    assert out["file"] == "voice/sample-veena-tts-agastya.wav" and (store.media_dir(plan_id) / out["file"]).is_file()
    assert gw.requests[0]["body"]["voice"] == "agastya" and not store.items(plan_id, "voice")      # not a numbered take: it never counts toward the video
    assert voice.state(plan_id)["sample"].startswith(f"/api/media/file/{plan_id}/voice/sample-veena-tts-agastya.wav")


def test_maya_text_carries_tags_resets_and_splits_long_segments():
    from story2 import maya
    sents = [{"text": "वो रात थी", "tag": "whispers"}, {"text": "कोई नहीं जानता था", "tag": "whispers"}, {"text": "फिर सब बदल गया", "tag": ""},
             {"text": "उसने गहरी साँस ली", "tag": "sighs"}, {"text": "सब ठीक है", "tag": "neutral", "emotion": "fear"}]
    t = maya.chunks(sents)
    assert t == ["[whispers] वो रात थी। कोई नहीं जानता था। [calm] फिर सब बदल गया। [sighs] उसने गहरी साँस ली। सब ठीक है।"]
    assert maya.chunks([{"text": "यह क्या था", "emotion": "fear"}]) == ["[fearful] यह क्या था।"]               # a Svara emotion still sounds like something
    assert maya.norm_tag("[Whisper]") == "whispers" and maya.norm_tag("made up") == ""
    long = [{"text": "यह एक लंबा वाक्य है " * 6, "tag": "sad"} for _ in range(30)]
    parts = maya.chunks(long)
    assert len(parts) > 1 and all(len(p) <= 1500 for p in parts) and all(p.startswith("[sad]") for p in parts)


def test_maya_request_and_scene_tags_reach_the_sentences(env, monkeypatch, fast):
    from story2 import storyboard
    plan_id = exported(env, "maya-tts")
    plan = planner.get_plan(plan_id)
    seg = plan["segments"][0]
    sc = [x for x in plan["scenes"] if x["segment_id"] == seg["id"]][0]
    data = {**sc["data"], "voice_tag": "worried"}
    from story import db
    db.ex("UPDATE scenes SET data=? WHERE id=?", (db.jdump(data), sc["id"]))
    storyboard.apply_voice_tags(seg["id"])
    seg = next(x for x in planner.get_plan(plan_id)["segments"] if x["id"] == seg["id"])
    assert seg["sentences"][sc["s_from"] - 1]["tag"] == "worried"
    body = voices.request_body({"engine": "maya-tts", "voice": "Siddhant"}, voices.text_for("maya-tts:Siddhant", seg), 1)
    assert body["model"] == "maya-tts" and body["language"] == "hi" and "temperature" not in body and body["input"].startswith("[worried]")


def test_voice_tags_do_not_change_what_was_approved(env):
    from story import db
    from story2 import storyboard
    plan_id = exported(env, "maya-tts")
    before = editorial.content_hash(planner.get_plan(plan_id))
    plan = planner.get_plan(plan_id)
    sc = plan["scenes"][0]
    db.ex("UPDATE scenes SET data=? WHERE id=?", (db.jdump({**sc["data"], "voice_tag": "serious"}), sc["id"]))
    storyboard.apply_voice_tags(sc["segment_id"])
    assert editorial.content_hash(planner.get_plan(plan_id)) == before


def test_ai_voice_direction_writes_tags_onto_sentences_and_keeps_the_plan_approved(env):
    import json
    import re
    from story import db
    from story.llm import LLMResult
    from story2 import voicetags
    pid, cid, be, p = boarded(env)
    plan_id = p["id"]
    before = editorial.content_hash(planner.get_plan(plan_id))
    orig, seen = be.complete, []

    async def complete(messages, max_tokens):
        if "[TASK:p2_voice_tags]" in messages[0]["content"]:
            n = len(re.findall(r"^\d+\. ", messages[1]["content"].split("THE SEGMENT")[1], re.M))
            seen.append(messages[1]["content"])
            return LLMResult(json.dumps({"sentences": [{"n": i, "tag": "Curious" if i == 1 else "sighs" if i == 2 else "", "why": "x"} for i in range(1, n + 1)]}))
        return await orig(messages, max_tokens)
    be.complete = complete
    out = asyncio.run(voicetags.suggest(plan_id, be, {"retries": 1, "context_limit": 65536, "output_reserve": 2000, "safety_margin": 0.1, "chars_per_token": 3.5}))
    plan = planner.get_plan(plan_id)
    assert out["segments"] == len(plan["segments"]) == len(seen) and "THE WHOLE VIDEO" in seen[0] and "WHAT IS ON SCREEN" in seen[0]
    for seg in plan["segments"]:
        tags = [x["tag"] for x in seg["sentences"]]
        assert tags[0] == "curious" and all(t in ("curious", "sighs", "neutral") for t in tags) and (len(tags) < 3 or tags[2] == "neutral")
    assert editorial.content_hash(plan) == before
    text = voices.text_for("maya-tts:Siddhant", plan["segments"][0])
    assert text.startswith("[curious] ") and "[sighs] " in text


def test_tag_checks_and_the_ui_lists_match_the_server():
    import re
    from pathlib import Path
    from story2 import maya, voicetags
    assert voicetags.problems(["curious", "sad", "angry", "calm", "neutral"])                                   # changes too often
    assert voicetags.problems(["sighs", "laughs", "neutral", "neutral", "neutral"])                              # two sounds
    assert not voicetags.problems(["curious", "curious", "neutral", "neutral", "serious", "serious"])
    js = (Path(__file__).resolve().parent.parent / "static" / "plan.js").read_text(encoding="utf-8")
    for name, want in (("MAYA_STYLE", maya.STYLE_TAGS), ("MAYA_SOUND", maya.SOUND_TAGS)):
        got = re.search(rf"const {name} = \[(.*?)\];", js).group(1)
        assert [x.strip().strip("'") for x in got.split(",")] == list(want)


def test_scene_voice_tag_edit_is_a_production_setting(env):
    pid, cid, be, p = boarded(env)
    plan_id = p["id"]
    plan = planner.get_plan(plan_id)
    sc = plan["scenes"][0]
    before = editorial.content_hash(plan)
    out = storyboard.edit_scene(sc["id"], {"voice_tag": "Whisper"})
    assert out["data"]["voice_tag"] == "whispers" and out["status"] == sc["status"]
    seg = next(x for x in planner.get_plan(plan_id)["segments"] if x["id"] == sc["segment_id"])
    assert seg["sentences"][sc["s_from"] - 1]["tag"] == "whispers"
    assert editorial.content_hash(planner.get_plan(plan_id)) == before
    storyboard.edit_scene(sc["id"], {"locked": True})
    storyboard.edit_scene(sc["id"], {"voice_tag": "sad"})                                                   # allowed on a locked scene


def test_auto_run_has_a_voice_direction_step_only_maya_needs(env):
    from story3 import auto
    pid, cid, be, p = boarded(env)
    plan_id = p["id"]
    keys = [k for k, _ in auto.STAGES]
    assert keys.index("voicetags") == keys.index("storyboard") + 1
    assert auto.done(plan_id, "voicetags") is False                                    # new plans use Maya and nobody has directed the voice yet
    narr = voices.choose(planner.get_plan(plan_id)["narrator"], "veena-tts")
    planner.set_narrator(plan_id, None, tts=narr["tts"])
    assert auto.done(plan_id, "voicetags") is True


def test_a_take_with_a_long_silence_is_made_again_and_the_best_one_kept(env, monkeypatch, fast):
    """The engine sometimes goes quiet near the end of a long request: that take is made again with another seed, up to two more times, and flagged."""
    monkeypatch.setattr(voice, "RETAKES", 2)
    plan_id = exported(env)
    gw = Gateway()
    out = run(plan_id, gw, monkeypatch)
    segs = planner.get_plan(plan_id)["segments"]
    assert out["made"] == len(segs) and len(gw.requests) > len(segs)                                   # silent audio is all dead air, so every part was retried
    seeds = {r["body"]["seed"] for r in gw.requests}
    assert len(seeds) > 1                                                                              # a different seed for each retry
    metas = [i["meta"] for i in store.items(plan_id, "voice")]
    assert any("made 3 times" in " ".join(m.get("flags", [])) for m in metas)
