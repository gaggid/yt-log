"""Shorts (docs/PLAN_shorts.md): the Wan client, the frame and time arithmetic, the planner and checks, the three pipelines end to end on a fake gateway, and the API."""
import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

import config
from shorts_fakes import FakeChat, VideoGateway, fake_speak_all, needs_ffmpeg, png_bytes, tiny_mp4, tone_wav
from story import db, settings as settings_mod
from story3 import store as media, voice as voice3

from shorts import checks, clips, frames, models, pipelines as P, planner, remix, stitch, store, timeline, voice as svoice, wan

S = {**settings_mod.DEFAULTS, "base_url": "http://gw/v1", "retry_backoff_s": 0}


@pytest.fixture
def gw(env, monkeypatch):
    g = VideoGateway(env).install(monkeypatch)
    monkeypatch.setattr(voice3, "_speak_all", fake_speak_all)
    return g


def run(coro):
    return asyncio.run(coro)


def new_short(pipeline="quick", **settings):
    return store.create("Test", pipeline, {"kind": "idea", "text": "a courier finds a wallet", "candidate_id": "", "facts": ""}, settings)


def planned(pipeline="quick", **settings):
    s = new_short(pipeline, **settings)
    return run(planner.make_plan(s["id"], FakeChat(), S))


# ── arithmetic ───────────────────────────────────────────────────────────────

def test_frames_are_4n_plus_1_and_cover_the_shot():
    for model in (models.TI2V, models.T2V, models.I2V):
        for secs in (1.0, 2.0, 2.56, 2.75, 3.0):
            g = models.gen_frames(secs, model)
            assert (g - 1) % 4 == 0
            assert g >= secs * models.MODELS[model]["fps"] - 1e-6
    assert models.gen_frames(3.0, models.I2V) == 49 and models.gen_frames(3.0, models.TI2V) == 73
    with pytest.raises(ValueError):
        models.gen_frames(12.0, models.I2V)                                     # over the 161-frame cap
    assert models.canon("wan-i2v") == models.I2V and models.out_frames(2.5) == 75


def test_timeline_is_exactly_900_frames_and_no_shot_over_three_seconds():
    short = planned()
    tl = timeline.build(short, {})
    assert sum(s["frames"] for s in tl["shots"]) == 900 and tl["total_s"] == pytest.approx(30.0)
    assert max(s["seconds"] for s in tl["shots"]) <= 3.0 and tl["shots"][0]["seconds"] <= 2.0
    assert not tl["problems"] and 11 <= len(tl["shots"]) <= 14
    real = {b["id"]: 9.0 for b in short["beats"]}                                # five beats of nine seconds: too long to fit under 30 even at x1.35
    assert any(p["code"] == "length" for p in timeline.build(short, real)["problems"])
    few = {b["id"]: 11.0 for b in short["beats"][:1]}                            # a long first beat gets shots over three seconds
    assert any(p["code"] == "shot_too_long" for p in timeline.build(short, few)["problems"])


# ── the Wan client ───────────────────────────────────────────────────────────

def test_wan_polls_downloads_and_finds_a_path_url(gw):
    data, res = run(wan.run({"model": models.TI2V, "prompt": "x", "size": "480x832", "num_frames": 13, "fps": 24, "seed": 1}, "http://gw/v1", "k"))
    assert data[:4] != b"" and res["frames"] == 13 and res["url"].startswith("/video/")
    assert gw.requests[0]["seed"] == 1


def test_wan_finds_a_url_under_the_api_path(env, monkeypatch):
    g = VideoGateway(env, video_under_api=True).install(monkeypatch)
    data, res = run(wan.run({"model": models.TI2V, "prompt": "x", "size": "480x832", "num_frames": 13, "fps": 24}, "http://gw/v1", "k"))
    assert data


def test_wan_retries_a_refused_request_and_never_a_bad_one(env, monkeypatch):
    g = VideoGateway(env, fail_first=2).install(monkeypatch)
    data, res = run(wan.run({"model": models.TI2V, "prompt": "x", "num_frames": 5, "fps": 24}, "http://gw/v1", "k"))
    assert data and len(g.requests) == 1
    with pytest.raises(wan.WanError, match="bad size"):
        run(wan.run({"model": models.TI2V, "prompt": "REFUSE"}, "http://gw/v1", "k"))
    g.fail_first = 5
    with pytest.raises(wan.WanError, match="did not take"):
        run(wan.submit({"model": models.TI2V, "prompt": "x"}, "http://gw/v1", "k"))


def test_wan_reports_an_expired_job_as_lost_and_refuses_a_huge_body(gw):
    with pytest.raises(wan.WanError) as e:
        run(wan.resume("job_999", "http://gw/v1", "k"))
    assert e.value.lost
    with pytest.raises(wan.WanError, match="25 MB"):
        run(wan.submit({"model": models.TI2V, "prompt": "x", "image": "A" * (25 * 1024 * 1024)}, "http://gw/v1", "k"))


def test_models_lists_only_video(gw):
    assert {m["id"] for m in run(wan.models("http://gw/v1", "k"))} == set(gw.listed)


# ── planning and checks ──────────────────────────────────────────────────────

def test_plan_writes_beats_shots_and_a_ready_timeline(gw):
    short = planned()
    assert len(short["beats"]) == 5 and short["status"] == "planned"
    assert [s["id"] for s in short["shots"]] == [f"s{i}" for i in range(1, len(short["shots"]) + 1)]
    assert all(s["beat"] in {b["id"] for b in short["beats"]} for s in short["shots"])
    assert sum(len(b["shot_ids"]) for b in short["beats"]) == len(short["shots"])
    assert short["beats"][0]["sentences"][0]["tag"] == "neutral"                  # every beat starts neutral; the person changes a tag by hand
    assert planner.narration_problems(short["beats"]) == []
    chk = checks.run(short)
    assert [i["code"] for i in chk["issues"] if i["level"] == "block"] == ["no_voice"], chk["issues"]      # the voice is the first gate: nothing else is wrong


def test_the_plan_is_sent_back_when_the_words_break_the_rules(gw):
    bad = [["Aaj ham ek 5 kahani sunenge ki wallet kaise mila."], *[b for b in [["ठीक है।"]] * 3]]
    chat = FakeChat(narration=bad)
    short = new_short()
    run(planner.make_plan(short["id"], chat, {**S, "retries": 1}))                # the last attempt is accepted, so a run never stops on style
    assert chat.count("p4_plan") == 2
    issues = checks.run(store.get(short["id"]))["issues"]
    assert any(i["code"] == "narration" for i in issues)


def test_checks_warn_about_a_missing_anchor_and_text_in_pictures(gw):
    short = planned(image_mode="anchor")
    short["shots"][0]["prompt"] = "A shop sign saying OPEN in neon. The monitor displays a chart."
    store.save(short)
    issues = checks.run(store.get(short["id"]))["issues"]
    levels = {i["code"]: i["level"] for i in issues}
    assert levels["no_anchor"] == "warn" and levels["text_in_picture"] == "warn"      # the start pictures are drawn when there is no upload, so neither stops Make
    assert not any("displays" in i["text"] for i in issues)                              # a plain verb is not a request for words in the picture


def test_a_shorter_short_asks_for_fewer_words_and_beats(gw):
    assert planner.word_limits(30) == (64, 104, 85, 100) and planner.beat_range(30) == (4, 6)
    lo, hi, ask_lo, ask_hi = planner.word_limits(10)
    assert (lo, hi) == (21, 32) and lo <= ask_lo <= ask_hi < hi and planner.beat_range(10) == (2, 3)
    fat = [{"sentences": [{"text": " ".join(["shabd"] * 80)}]}]                       # a 30-second narration is far too long for 10 seconds
    assert any("21 and 32" in p for p in planner.narration_problems(fat, None, 10))
    assert not any("words; it must be" in p for p in planner.narration_problems(fat, None, 30))
    from shorts import prompts
    p = prompts.plan_system("maya-tts", 10, "2 to 3", 21, 24)
    assert "10-second" in p and "between 21 and 24 words" in p and "30" not in p


def test_a_voice_that_runs_long_makes_the_checks_ask_for_more_shots(gw):
    short = planned()
    svoice_ids = {}
    for b in short["beats"]:
        it = media.add(short["id"], store.VOICE, b["id"], 0, "running", {"input_hash": svoice.beat_hash(short, b)})
        (store.media_dir(short["id"], "voice") / f"{b['id']}.wav").write_bytes(tone_wav(9.0 if b["id"] == "b1" else 4.5))
        media.update(it["id"], status="done", file=f"voice/{b['id']}.wav", meta={"duration_s": 9.0 if b["id"] == "b1" else 4.5})
    planner.sync_timing(short["id"])
    chk = checks.run(store.get(short["id"]))
    fix = [i for i in chk["issues"] if i.get("fix") == "fit_shots"]
    assert fix and "b1" in fix[0]["beats"]
    note = run(planner.fit_shots(short["id"], FakeChat(), S))
    assert "b1" in note
    after = timeline.build(store.get(short["id"]), svoice.real_seconds(store.get(short["id"])))
    assert not [p for p in after["problems"] if p["code"] == "shot_too_long"]


# ── pipelines, end to end ────────────────────────────────────────────────────

@needs_ffmpeg
def test_quick_pipeline_end_to_end(gw):
    short = planned("quick", image_mode="wan")
    sid = short["id"]
    run(svoice.make(sid, s=S, key="k"))
    assert not svoice.missing(store.get(sid))
    res = run(clips.make_clips(sid, s=S, key="k"))
    assert res["made"] == len(store.get(sid)["shots"]) and not res["failed"]
    reqs = gw.requests
    assert all(r["model"] == models.TI2V and (r["num_frames"] - 1) % 4 == 0 and r["fps"] == 24 for r in reqs)
    assert any("image" in r for r in reqs), "a shot that continues starts from the last frame of the one before"
    assert not any("image" in r for r in reqs[:1])
    final = stitch.build(sid)
    info = frames.info(store.media_dir(sid) / final["file"])
    assert abs(info["duration_s"] - 30.0) < 0.2 and info["streams"][0]["width"] == 1080 and info["streams"][0]["height"] == 1920
    assert any(s["type"] == "audio" for s in info["streams"])
    assert stitch.build(sid)["id"] == final["id"], "nothing changed, so the same video is reused"
    assert store.get(sid)["status"] == "made"


@needs_ffmpeg
def test_keyframe_pipeline_makes_stills_first_then_animates_each(gw, env):
    short = planned("keyframe", image_mode="wan")
    sid = short["id"]
    run(svoice.make(sid, s=S, key="k"))
    mine = env / "mine.png"
    mine.write_bytes(png_bytes())
    short = store.get(sid)
    short["images"]["shots"][short["shots"][0]["id"]] = "upload/mine.png"
    (store.media_dir(sid, "upload") / "mine.png").write_bytes(png_bytes())
    store.save(short)
    kf = run(clips.make_keyframes(sid, s=S, key="k"))
    n = len(store.get(sid)["shots"])
    assert kf["made"] == n and not kf["failed"]
    t2v = [r for r in gw.requests if r["model"] == models.T2V]
    assert len(t2v) == n - 1 and all(r["num_frames"] == 5 and r["speed_lora"] is False for r in t2v), "the user's own picture needs no request"
    res = run(clips.make_clips(sid, s=S, key="k"))
    assert res["made"] == n
    i2v = [r for r in gw.requests if r["model"] == models.I2V]
    assert len(i2v) == n and all(r["speed_lora"] is True and r["image"].startswith("data:image/jpeg") and (r["num_frames"] - 1) % 4 == 0 for r in i2v)
    assert stitch.checklist(store.get(sid))["ready"]
    final = stitch.build(sid)
    assert abs(frames.info(store.media_dir(sid) / final["file"])["duration_s"] - 30.0) < 0.2


@needs_ffmpeg
@pytest.mark.parametrize("pipeline", ["keyframe", "quick"])
def test_the_image_model_draws_the_start_pictures_then_wan_animates_them(gw, env, pipeline):
    short = planned(pipeline)
    sid = short["id"]
    assert short["settings"]["image_mode"] == "qwen" and all(sh["still"] for sh in short["shots"]) and P.keyframes_on(short)
    run(svoice.make(sid, s=S, key="k"))
    n = len(short["shots"])
    kf = run(clips.make_keyframes(sid, s=S, key="k"))
    assert kf["made"] == n and not kf["failed"] and len(gw.images) == n
    assert not [r for r in gw.requests if r["model"] == models.T2V], "Wan is not asked for pictures"
    assert all(r["model"] == "qwen-image-2.1" and r["size"] == "720x1280" and "A courier stands over a dropped wallet" in r["prompt"] and "No text" in r["prompt"] for r in gw.images)
    assert "yellow delivery jacket" in gw.images[0]["prompt"] and "yellow delivery jacket" not in gw.images[1]["prompt"], "the character block is only in the shots that show them"
    rows = clips.shot_rows(store.get(sid))
    assert all(r["keyframe"] and r["keyframes"][0]["url"] for r in rows)
    res = run(clips.make_clips(sid, s=S, key="k"))
    assert res["made"] == n
    video = [r for r in gw.requests if r["model"] == (models.I2V if pipeline == "keyframe" else models.TI2V)]
    assert len(video) == n and all(r["image"].startswith("data:image/jpeg") for r in video)
    # editing a still prompt makes that picture (and its clip) old; redoing it keeps the old attempt
    short = store.get(sid)
    short["shots"][0]["still"] += " Heavy rain."
    store.save(short)
    short = store.get(sid)
    assert not clips.chosen_keyframe(short, short["shots"][0]) and not clips.chosen_clip(short, short["shots"][0])
    run(clips.make_keyframes(sid, ["s1"], s=S, key="k"))
    assert len(gw.images) == n + 1 and len(media.items(sid, store.KEY, "s1")) == 2 and clips.chosen_keyframe(store.get(sid), store.get(sid)["shots"][0])


def test_a_picture_of_the_users_wins_over_the_image_model(gw, env):
    short = planned("keyframe")
    sid = short["id"]
    short["images"]["shots"]["s1"] = "upload/mine.png"
    (store.media_dir(sid, "upload") / "mine.png").write_bytes(png_bytes())
    store.save(short)
    short = store.get(sid)
    assert P.start_source(short, short["shots"][0]) == "upload" and P.start_source(short, short["shots"][1]) == "qwen"
    run(clips.make_keyframes(sid, s=S, key="k"))
    assert len(gw.images) == len(short["shots"]) - 1


def test_changing_a_prompt_makes_its_clip_old(gw):
    short = planned("quick", image_mode="wan")
    sid = short["id"]
    run(svoice.make(sid, s=S, key="k"))
    run(clips.make_clips(sid, ["s1"], s=S, key="k"))
    short = store.get(sid)
    assert clips.chosen_clip(short, short["shots"][0])
    short["shots"][0]["prompt"] += " It starts to rain."
    store.save(short)
    short = store.get(sid)
    assert not clips.chosen_clip(short, short["shots"][0])
    assert clips.shot_rows(short)[0]["old_clip"]


def test_a_running_attempt_is_picked_up_again_after_a_restart(gw):
    short = planned("quick", image_mode="wan")
    sid = short["id"]
    run(svoice.make(sid, s=S, key="k"))
    run(clips.make_clips(sid, ["s1"], s=S, key="k"))
    gw_job = "job_1"
    short = store.get(sid)
    plan = clips.clip_plan(short, short["shots"][1])
    it = media.add(sid, store.CLIP, "s2", 0, "running", {"input_hash": plan["hash"], "job_id": gw_job, "seed": 1, "model": models.TI2V})
    done = run(clips._adopt(sid, store.CLIP, "s2", "http://gw/v1", "k"))
    assert done and done["item"]["id"] == it["id"] and done["data"]
    orphan = media.add(sid, store.CLIP, "s3", 0, "running", {"seed": 1})
    assert run(clips._adopt(sid, store.CLIP, "s3", "http://gw/v1", "k")) is None
    assert media.get(orphan["id"])["status"] == "failed"


# ── remix ────────────────────────────────────────────────────────────────────

def test_only_youtube_links_are_taken():
    assert remix.check_url("https://www.youtube.com/watch?v=abc").startswith("https://www.youtube.com")
    assert remix.check_url("https://youtu.be/abc")
    for bad in ("https://example.com/watch?v=abc", "ftp://youtube.com/x", "javascript:alert(1)", ""):
        with pytest.raises(Exception):
            remix.check_url(bad)


def test_suggested_windows_prefer_fast_cuts():
    cuts = [round(i * 2.0, 1) for i in range(100, 130)]                           # a fast stretch from 200 s to 260 s
    sug = remix.suggest_windows(cuts, 600.0)
    assert sug and 190 <= sug[0]["start"] <= 235 and sug[0]["slow_s"] == 0


@needs_ffmpeg
def test_remix_end_to_end_with_rights_gate(gw, env, monkeypatch):
    s = store.create("Remix", "remix", {"kind": "idea", "text": "", "candidate_id": "", "facts": ""}, {}, {"remix": dict(remix.DEFAULT)})
    sid = s["id"]
    src = tiny_mp4(store.media_dir(sid, "remix") / "source.mp4", frames=16 * 40, fps=16, size="160x90")
    monkeypatch.setattr(remix, "fetch_info", lambda url: {"title": "t", "duration_s": 40.0, "id": "abc"})
    monkeypatch.setattr(remix, "download", lambda url, d: src)
    r = remix.fetch(sid, "https://youtu.be/abc")
    assert r["source"] == "remix/source.mp4" and r["info"]["duration_s"] == 40.0
    short = remix.prepare(sid, 3.0, "pad", 2)
    assert len(short["remix"]["driving"]) == 2
    chk = remix.check(short)
    assert {i["code"] for i in chk["issues"]} >= {"rights_video", "rights_character", "no_character", "no_prompt"}
    with pytest.raises(Exception, match="right to use"):
        run(remix.make(sid, s=S, key="k"))
    short = store.get(sid)
    short["images"]["anchor"] = "upload/a.jpg"
    (store.media_dir(sid, "upload") / "a.jpg").write_bytes(png_bytes())
    short["remix"].update(rights_video=True, rights_character=True, prompt="A cartoon robot with a yellow helmet in a white studio.")
    store.save(short)
    assert remix.check(store.get(sid))["ok"]
    res = run(remix.make(sid, s=S, key="k"))
    assert res["made"] == 2 and not res["failed"]
    body = gw.requests[-1]
    assert body["model"] == models.ANIMATE and body["keep_audio"] is False and body["fps"] == 16 and body["duration"] == 15.0 and body["driving_video"].startswith("data:video/mp4")
    final = remix.build(sid)
    assert abs(frames.info(store.media_dir(sid) / final["file"])["duration_s"] - 30.0) < 0.2
    assert remix.build(sid)["id"] == final["id"]


# ── the API ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    import main
    from shorts import api as shorts_api
    g = VideoGateway(tmp_path).install(monkeypatch)
    monkeypatch.setattr(voice3, "_speak_all", fake_speak_all)
    chat = FakeChat()
    monkeypatch.setattr(shorts_api, "_backend", lambda: ({**settings_mod.get(), "retry_backoff_s": 0}, chat))

    async def models_stub(base, key):
        return [{"id": m, "type": "video"} for m in g.listed]
    monkeypatch.setattr(wan, "models", models_stub)
    with TestClient(main.app) as c:
        c.post("/login", data={"username": config.APP_USER, "password": config.APP_PASSWORD})
        c.gw, c.chat = g, chat
        yield c


def wait_job(c, sid, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = c.get(f"/api/shorts/{sid}/job").json()
        if j.get("state") in ("done", "error", "cancelled"):
            return j
        time.sleep(0.05)
    raise AssertionError("job timed out")


def test_api_create_plan_edit_and_check(client):
    o = client.get("/api/shorts/options").json()
    assert set(o["pipelines"]) == {"quick", "keyframe", "remix"} and o["pipelines"]["quick"]["available"] is True
    assert client.post("/api/shorts", json={"pipeline": "quick", "kind": "idea", "text": "x"}).status_code == 400
    r = client.post("/api/shorts", json={"pipeline": "keyframe", "kind": "idea", "text": "A courier finds a wallet with a lakh rupees."})
    assert r.status_code == 200
    sid = r.json()["id"]
    assert client.post(f"/api/shorts/{sid}/plan").status_code == 200
    assert wait_job(client, sid)["state"] == "done"
    st = client.get(f"/api/shorts/{sid}").json()
    assert len(st["beats"]) == 5 and [i["code"] for i in st["checks"]["issues"] if i["level"] == "block"] == ["no_voice"] and st["auto"]["next"] == "voice"
    assert st["estimate_s"] > 0 and st["timeline"]["total_s"] == pytest.approx(30.0)
    shot = st["shots"][0]["id"]
    r = client.patch(f"/api/shorts/{sid}/shots/{shot}", json={"prompt": "A new prompt about a wallet.", "character": True})
    assert r.json()["shots"][0]["prompt"] == "A new prompt about a wallet."
    r = client.patch(f"/api/shorts/{sid}/narration", json={"beats": [{"id": "b1", "sentences": ["सड़क पर एक वॉलेट था।", "अंदर क्या था?"], "tag": "whispers"}]})
    assert r.json()["beats"][0]["sentences"][0]["tag"] == "whispers"
    assert client.patch(f"/api/shorts/{sid}/settings", json={"image_mode": "nonsense"}).status_code == 400
    assert client.patch(f"/api/shorts/{sid}/settings", json={"voice": {"engine": "veena-tts", "voice": "agastya"}}).json()["settings"]["voice"]["engine"] == "veena-tts"
    assert client.patch(f"/api/shorts/{sid}/settings", json={"size": "480x832"}).json()["settings"]["size"] == "704x1280", "only the 5B pipeline can change the size"
    up = client.post(f"/api/shorts/{sid}/images/anchor", files={"file": ("a.png", png_bytes(), "image/png")})
    assert up.status_code == 200 and up.json()["settings"]["image_mode"] == "anchor" and up.json()["images"]["anchor"].startswith("upload/")
    assert client.post(f"/api/shorts/{sid}/images/anchor", files={"file": ("a.txt", b"nope", "text/plain")}).status_code == 400
    assert client.get(f"/api/shorts/file/{sid}/../../story.db").status_code in (404, 400)
    assert client.delete(f"/api/shorts/{sid}").status_code == 200
    assert client.get(f"/api/shorts/{sid}").status_code == 404


def test_api_auto_run_stops_at_the_keyframe_checkpoint(client):
    sid = client.post("/api/shorts", json={"pipeline": "keyframe", "kind": "idea", "text": "A courier finds a wallet with a lakh rupees."}).json()["id"]
    assert client.post(f"/api/shorts/{sid}/auto").status_code == 200
    j = wait_job(client, sid, 120)
    assert j["state"] == "done" and "Look at the start pictures" in j["note"], j
    st = client.get(f"/api/shorts/{sid}").json()
    assert st["auto"]["next"] == "review" and all(s["keyframe"] for s in st["shots"])
    assert not any(r["model"] == models.I2V for r in client.gw.requests), "nothing is animated before the keyframes are confirmed"
    assert client.post(f"/api/shorts/{sid}/keyframes/confirm").json()["keyframes_confirmed"] is True
    assert st["voice"]["have"] == 5


def test_api_remix_needs_a_youtube_link(client):
    sid = client.post("/api/shorts", json={"pipeline": "remix"}).json()["id"]
    assert client.post(f"/api/shorts/{sid}/remix/fetch", json={"url": "https://example.com/x"}).status_code == 400
    assert client.post(f"/api/shorts/{sid}/remix/make").status_code == 400
    r = client.patch(f"/api/shorts/{sid}/remix", json={"audio": "voiceover", "script": "यह एक छोटी कहानी है। इसमें एक किरदार है।", "rights_video": True})
    assert r.json()["remix"]["audio"] == "voiceover" and len(r.json()["beats"]) == 1
    assert client.patch(f"/api/shorts/{sid}/remix", json={"audio": "nonsense"}).status_code == 400


def test_a_short_without_voice_is_never_too_long_for_its_words(gw):
    short = planned()
    short["settings"].update(target_s=10, voice_mode="none")                           # five beats of narration that would take about 30 s if spoken
    store.save(short)
    chk = checks.run(store.get(short["id"]))
    assert chk["timeline"]["total_s"] == 10.0 and not any(i["code"] == "length" for i in chk["issues"])


# ── format and subjects ──────────────────────────────────────────────────────

JETS = [{"name": "Chinese J-20 stealth fighter", "kind": "machine", "visual": "A twin-engine stealth fighter with canards, dark grey finish and a red and yellow star roundel."},
        {"name": "Indian Air Force Su-30MKI", "kind": "machine", "visual": "A twin-engine grey fighter with the orange, white and green roundel of the Indian Air Force."}]


def test_a_facts_article_is_a_documentary_with_its_subjects_and_no_invented_person(gw):
    chat = FakeChat(plan_extra={"format": "comparison", "subjects": JETS}, shot_extra={"subjects": ["Chinese J-20 stealth fighter"]})
    short = new_short()
    short = run(planner.make_plan(short["id"], chat, S))
    assert short["plan"]["format"] == "comparison" and [x["name"] for x in short["plan"]["subjects"]] == [j["name"] for j in JETS] + ["Pilot"]
    assert short["plan"]["character"] == "" and not any(sh["character"] for sh in short["shots"])      # the fake model still asked for a character in half the shots
    shots_system = next(c for c in chat.calls if c["task"] == "p4_shots")
    assert "Format comparison" in shots_system["system"] and "THE SUBJECTS" in shots_system["user"] and "Chinese J-20 stealth fighter" in shots_system["user"]
    from shorts import stills
    assert "red and yellow star roundel" in stills.prompt(short, short["shots"][0])


def test_the_producer_can_force_the_format_and_a_story_keeps_its_person(gw):
    short = new_short(format="story")
    short = run(planner.make_plan(short["id"], FakeChat(plan_extra={"format": "documentary"}), S))
    assert short["plan"]["format"] == "story" and short["plan"]["character"] and any(sh["character"] for sh in short["shots"])
    assert planner.chosen_format({"settings": {}}, "nonsense") == "explainer"                         # a format the model invented falls back to the one that invents no person


def test_a_shot_gets_the_look_of_a_subject_it_names_even_when_the_model_forgot_to_list_it(gw):
    from shorts import subjects
    short = {"plan": {"subjects": JETS}}
    shot = {"prompt": "An Indian Air Force Su-30MKI banks over green hills.", "still": "", "subjects": []}
    assert "orange, white and green roundel" in subjects.block(short, shot) and "red and yellow" not in subjects.block(short, shot)
    assert subjects.block({"plan": {}}, shot) == ""                                                   # an older short without a subject list is unchanged
    assert [x["name"] for x in subjects.parse_lines("Tejas: a small delta-wing fighter\nno colon here")] == ["Tejas"]


def test_make_clips_draws_a_missing_or_old_start_picture_first_instead_of_skipping_it(gw, monkeypatch):
    short = planned()
    asked = {}

    async def fake_keys(short_id, shot_ids, only_missing, progress, s, key):
        asked["ids"] = shot_ids
        return {"made": len(shot_ids), "failed": []}
    monkeypatch.setattr(clips, "make_keyframes", fake_keys)
    note = run(clips.make_clips(short["id"], [short["shots"][0]["id"]], True, None, S, "k"))
    assert asked["ids"] == [short["shots"][0]["id"]]                                                  # nothing was drawn yet, so the clip job drew it
    assert note["message"].startswith("1 start picture drawn first")


def test_speed_lora_is_on_by_default_and_the_person_can_turn_it_off():
    short = planned("keyframe")
    sh = short["shots"][0]
    on = P.animate_request(short, sh, 1, "data:image/jpeg;base64,x")
    assert on["speed_lora"] is True and "steps" not in on, "the gateway's own 4 steps and guidance 1 go with the LoRA"
    short["settings"]["speed_lora"] = False
    off = P.animate_request(short, sh, 1, "data:image/jpeg;base64,x")
    assert off["speed_lora"] is False and off["steps"] == P.DEFAULT_STEPS[models.I2V]


def test_the_14b_size_is_480p_or_720p_and_the_picture_follows_it():
    short = planned("keyframe")
    sh = short["shots"][0]
    assert P.animate_request(short, sh, 1, "x")["size"] == models.SIZE_PORTRAIT
    short["settings"]["size_14b"] = "720x1280"
    assert P.animate_request(short, sh, 1, "x")["size"] == "720x1280" and clips.clip_plan.__doc__
    short["settings"]["size_14b"] = "bogus"
    assert P.animate_request(short, sh, 1, "x")["size"] == models.SIZE_PORTRAIT


@needs_ffmpeg
def test_nothing_after_the_voice_starts_until_every_beat_has_one(gw, env):
    short = planned("keyframe")
    sid = short["id"]
    assert checks.voice_gate(short) and "5 of 5" in checks.voice_gate(short)
    run(svoice.make(sid, s=S, key="k"))
    assert not checks.voice_gate(store.get(sid))
    short = store.get(sid)
    short["settings"]["voice_mode"] = "none"
    assert not checks.voice_gate(short), "no narration, no voice gate"


def test_language_needs_the_maya_voice_and_reaches_the_prompt_and_the_voice_request():
    from shorts import languages
    assert languages.problem("hinglish", "veena-tts") == "" and languages.problem("ta", "maya-tts") == ""
    assert "needs the Maya voice" in languages.problem("ta", "veena-tts") and languages.problem("xx", "maya-tts")
    assert "Tamil" in languages.rule({"language": "ta"}) and "Devanagari" in languages.rule({})
    short = planned("keyframe")
    h_hi = svoice.beat_hash(short, short["beats"][0])
    short["settings"]["language"] = "ta"
    assert svoice.beat_hash(short, short["beats"][0]) != h_hi, "another language makes the old take old"


def test_create_takes_style_language_voice_and_sizes_and_refuses_a_voice_that_cannot_speak_the_language(client):
    base = {"pipeline": "keyframe", "kind": "idea", "text": "A courier finds a wallet with a lakh rupees in it."}
    ok = client.post("/api/shorts", json={**base, "settings": {"visual_style": "realism", "language": "ta", "voice": {"engine": "maya-tts", "voice": "Kayal"}, "size_14b": "720x1280", "speed_lora": True}})
    st = ok.json()["settings"]
    assert ok.status_code == 200 and st["visual_style"] == "realism" and st["language"] == "ta" and st["voice"]["voice"] == "Kayal" and st["size_14b"] == "720x1280" and st["speed_lora"] is True
    bad = client.post("/api/shorts", json={**base, "settings": {"language": "ta", "voice": {"engine": "veena-tts", "voice": "agastya"}}})
    assert bad.status_code == 400 and "Maya" in bad.json()["detail"]
    assert client.post("/api/shorts", json={**base, "settings": {"visual_style": "nope"}}).status_code == 400


def test_narration_speed_scales_the_words_asked_for_and_marks_old_voice_old(client):
    short = planned("keyframe")
    h1 = svoice.beat_hash(short, short["beats"][0])
    short["settings"]["voice_speed"] = 0.85
    assert svoice.beat_hash(short, short["beats"][0]) != h1 and svoice.speed(short) == 0.85
    assert planner.word_limits(30, 0.85)[1] < planner.word_limits(30, 1.0)[1] < planner.word_limits(30, 1.15)[1]
    sid = short["id"]
    assert client.patch(f"/api/shorts/{sid}/settings", json={"voice_speed": 3}).status_code == 400
    assert client.patch(f"/api/shorts/{sid}/settings", json={"voice_speed": 1.08}).json()["settings"]["voice_speed"] == 1.08


def test_the_shot_count_asked_for_always_clears_the_three_second_rule():
    from shorts import timeline
    for hook in (False, True):
        for span in [x / 10 for x in range(30, 160)]:
            n = timeline.shots_to_fit(span, hook)
            first = min(models.HOOK_MAX_S, span / n) if (hook and n > 1) else span / n
            rest = (span - first) / (n - 1) if n > 1 else first
            assert round(max(first, rest) * 30) / 30 <= models.MAX_SHOT_S, (span, hook, n)


def test_tones_are_valid_and_reach_the_plan_prompt_and_create_takes_them(client):
    from shorts import tones
    from story2 import maya
    assert tones.DEFAULT in tones.TONES and len(tones.TONES) >= 19
    for k, t in tones.TONES.items():
        assert set(t["tags"]) <= set(maya.STYLE_TAGS) and t["speed"] in (0.85, 0.92, 1.0, 1.08, 1.15) and 1 <= t["energy"] <= 5, k
    text = tones.prompt_text({"tone_id": "osint", "edge": "savage"})
    assert "verified" in text and "Never use slurs" in text
    assert tones.prompt_text({}).count("Friendly big brother") == 1 and "No swearing" in tones.prompt_text({})
    base = {"pipeline": "keyframe", "kind": "idea", "text": "A courier finds a wallet with a lakh rupees in it."}
    st = client.post("/api/shorts", json={**base, "settings": {"tone_id": "motivator", "edge": "spicy"}}).json()["settings"]
    assert st["tone_id"] == "motivator" and st["edge"] == "spicy" and st["voice_speed"] == 1.15, "a tone brings its speed"
    assert client.post("/api/shorts", json={**base, "settings": {"tone_id": "nope"}}).status_code == 400


@needs_ffmpeg
def test_a_beat_of_voice_starts_and_ends_at_silence_so_the_join_does_not_click(env):
    import array, wave
    from shorts import stitch
    src = env / "take.wav"
    with wave.open(str(src), "wb") as w:                                   # a tone that starts at full level, like a take trimmed right at the word
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(24000)
        w.writeframes(array.array("h", [int(20000 * (1 if (i // 20) % 2 else -1)) for i in range(24000)]).tobytes())
    out = env / "beat.wav"
    stitch.beat_audio(src, 1.0, 1.5, out)
    with wave.open(str(out)) as w:
        x = array.array("h"); x.frombytes(w.readframes(w.getnframes()))
    assert abs(x[0]) < 600 and abs(x[-1]) < 600 and max(abs(v) for v in x[5000:6000]) > 15000, "silent at both ends, untouched in the middle"


@needs_ffmpeg
def test_every_choice_made_when_creating_a_short_reaches_the_prompts_and_the_requests(client, gw, monkeypatch):
    from shorts import languages, looks, stills, tones
    chat = FakeChat()
    body = {"pipeline": "keyframe", "kind": "idea", "text": "A courier finds a wallet with a lakh rupees in it.",
            "settings": {"visual_style": "noir", "language": "ta", "voice": {"engine": "maya-tts", "voice": "Kayal"}, "voice_speed": 1.15, "tone_id": "osint", "edge": "spicy",
                         "size_14b": "720x1280", "speed_lora": True}}
    sid = client.post("/api/shorts", json=body).json()["id"]
    short = run(planner.make_plan(sid, chat, S))
    plan_prompt = next(c for c in chat.calls if c["task"] == "p4_plan")
    system, user = plan_prompt["system"], plan_prompt["user"]
    assert "Tamil" in system, "language"                                            # the language rule is in the system text
    assert "Narration tone: Open-source intelligence analyst" in user and "mild everyday swear words" in user, "tone and edge"
    assert short["plan"]["look"] == looks.of(short), "style replaces the model's look"
    assert all(b["tag"] == "neutral" for b in short["beats"]), "voice tags start neutral"
    prompt = stills.prompt(short, short["shots"][0])
    assert "graphic-novel" in prompt and "illustration" in prompt, "picture style and the keep-out sentence follow it"
    assert "graphic-novel" in P.compose(short, short["shots"][0], False), "the text-to-video prompt follows the style"
    assert "graphic-novel" not in P.compose(short, short["shots"][0], True), "a prompt for a picture does not repeat the style: the picture has it"
    req = P.animate_request(short, short["shots"][0], 1, "data:image/jpeg;base64,x")
    assert req["size"] == "720x1280" and req["speed_lora"] is True and "steps" not in req
    sent = []

    async def spy(client, base, key, bodies):
        sent.extend(bodies)
        return await fake_speak_all(client, base, key, bodies)
    monkeypatch.setattr(voice3, "_speak_all", spy)
    run(svoice.make(sid, s=S, key="k"))
    assert sent and all(b["language"] == "ta" and b["speed"] == 1.15 and b["voice"] == "Kayal" and b["model"] == "maya-tts" for b in sent), sent[:1]
    assert svoice.speed(store.get(sid)) == 1.15 and languages.code(short["settings"]) == "ta"
    state = client.get(f"/api/shorts/{sid}").json()
    assert state["voice_gate"] == "" and state["settings"]["tone_id"] == "osint"
    opts = client.get("/api/shorts/options").json()
    assert opts["tones"]["default"] == tones.DEFAULT and len(opts["languages"]) == 13 and any(v["id"] == "realism" for v in opts["visual_styles"])


# ── the director's shot list and the variety check ───────────────────────────

def test_the_director_plans_the_pictures_before_the_shots_and_later_beats_see_earlier_ones(gw):
    chat = FakeChat()
    s = new_short("quick")
    short = run(planner.make_plan(s["id"], chat, S))
    assert chat.count("p4_shotlist") == 1 and chat.calls[1]["task"] == "p4_shotlist"
    assert all(len(b["ideas"]) == len(b["shot_ids"]) for b in short["beats"])
    shot_calls = [c for c in chat.calls if c["task"] == "p4_shots"]
    assert "SHOT IDEAS" in shot_calls[0]["user"] and "Idea 1.1" in shot_calls[0]["user"] and "ALREADY DRAWN" not in shot_calls[0]["user"]
    assert "ALREADY DRAWN" in shot_calls[1]["user"]
    assert any(x["name"] == "Pilot" for x in short["plan"]["subjects"]), "the director's new subjects are kept"


def test_a_failing_director_never_stops_the_plan(gw):
    chat = FakeChat(no_director=True)
    short = run(planner.make_plan(new_short("quick")["id"], chat, S))
    assert short["status"] == "planned" and all("ideas" not in b for b in short["beats"])
    assert "SHOT IDEAS" not in [c for c in chat.calls if c["task"] == "p4_shots"][0]["user"]


def test_rethinking_the_pictures_keeps_the_words_and_makes_new_shots(gw):
    short = planned()
    words = [b["sentences"] for b in short["beats"]]
    old = [s["id"] for s in short["shots"]]
    chat = FakeChat()
    msg = run(planner.reshoot_all(short["id"], chat, S))
    after = store.get(short["id"])
    assert [b["sentences"] for b in after["beats"]] == words and not set(old) & {s["id"] for s in after["shots"]}
    assert chat.count("p4_shotlist") == 1 and chat.count("p4_shots") == len(after["beats"]) and "planned again" in msg
    assert any(x["name"] == "Pilot" for x in after["plan"]["subjects"]), "the director's new subjects are saved by a rethink"


def test_variety_check_flags_one_subject_everywhere_and_the_same_picture_twice(gw):
    from shorts import shotlist
    short = planned()
    short["plan"]["subjects"] = [{"name": "Jet", "kind": "machine", "visual": "A grey jet."}, {"name": "Valley", "kind": "place", "visual": "A snowy valley."}]
    for i, sh in enumerate(short["shots"]):
        sh["subjects"], sh["setting"] = (["Jet"], "") if i < 6 else (["Valley"], "")
        sh["still"] = f"A grey jet flies over a valley {['north', 'east', 'west', 'south', 'sunrise', 'dusk'][i % 6]} wide" if i < 6 else f"Snowy valley view number {i} with {['river', 'tent', 'goat', 'pine', 'hut', 'road'][i % 6]}"
    codes = {p["code"] for p in shotlist.problems(short)}
    assert "one_subject" in codes or len(short["shots"]) < 4
    a, b = short["shots"][0], short["shots"][1]
    a["still"] = b["still"] = "A grey jet on a dusty runway between towering peaks at noon"
    a["subjects"] = b["subjects"] = ["Jet"]
    probs = shotlist.problems(short)
    assert any(p["code"] == "similar_shots" and {a["id"], b["id"]} <= set(p["shots"]) for p in probs)
    warn = [i for i in checks.run(short)["issues"] if i["code"] in ("one_subject", "similar_shots")]
    assert warn and all(i["level"] == "warn" and i["fix"] == "reshoot_all" for i in warn)


def test_api_rethink_endpoint_runs_the_job(client):
    sid = client.post("/api/shorts", json={"pipeline": "keyframe", "kind": "idea", "text": "A courier finds a wallet with a lakh rupees."}).json()["id"]
    client.post(f"/api/shorts/{sid}/plan")
    assert wait_job(client, sid)["state"] == "done"
    assert client.post(f"/api/shorts/{sid}/rethink").status_code == 200
    assert wait_job(client, sid)["state"] == "done"


def test_negative_prompt_of_a_start_picture_reaches_the_prompt_and_makes_the_old_picture_old(gw):
    from shorts import clips as sclips, stills
    short = planned("keyframe")
    sh = short["shots"][0]
    before = sclips.keyframe_plan(short, sh)["hash"]
    plain = stills.prompt(short, sh)
    assert "No extra jets" not in plain
    sh["avoid"] = "extra jets, text on the wing;\nclouds"
    out = stills.prompt(short, sh)
    assert "No extra jets, no text on the wing, no clouds." in out and out.rstrip().endswith(stills.keep_out(short))
    assert sclips.keyframe_plan(short, sh)["hash"] != before, "a new negative prompt makes the drawn picture old, so Again draws it"
    sh["avoid"] = ""
    assert stills.prompt(short, sh) == plain


def test_negative_prompt_is_in_the_request_the_image_gateway_receives(gw):
    short = planned("keyframe")
    sid = short["id"]
    short["shots"][0]["avoid"] = "extra jets, text on the wing"
    store.save(short)
    run(svoice.make(sid, s=S, key="k"))
    kf = run(clips.make_keyframes(sid, [short["shots"][0]["id"], short["shots"][1]["id"]], s=S, key="k"))
    assert kf["made"] == 2 and len(gw.images) == 2
    assert "No extra jets, no text on the wing." in gw.images[0]["prompt"] and "extra jets" not in gw.images[1]["prompt"], "only the shot that has a negative prompt gets it"
    assert short["shots"][0]["id"] and clips.chosen_keyframe(store.get(sid), store.get(sid)["shots"][0]), "the picture drawn with it counts as current"


# ── the writers' room (shorts/script.py) ─────────────────────────────────────

from shorts_fakes import HINDI

SR = {**S, "retries": 0}                                                               # the fake lines are short next to the new word budget; one attempt per call keeps the call counts exact


def test_the_writers_room_writes_the_narration_before_the_plan_and_keeps_its_tags(gw):
    chat = FakeChat(room=True)
    short = run(planner.make_plan(new_short()["id"], chat, SR))
    tasks = [c["task"] for c in chat.calls]
    assert tasks[:2] == ["p4_bible", "p4_map"] and tasks.count("p4_draft") == 5 and tasks.count("p4_punch") == 1
    assert tasks.index("p4_plan") > tasks.index("p4_punch"), "the look is planned from a finished script"
    plan_call = next(c for c in chat.calls if c["task"] == "p4_plan")
    assert "ALREADY WRITTEN" in plan_call["system"] and "THE SCRIPT" in plan_call["user"] and "whispers" not in plan_call["user"]
    assert [b["sentences"][0]["text"] for b in short["beats"]] == [n[0] for n in HINDI]
    assert {x["tag"] for b in short["beats"] for x in b["sentences"]} == {"neutral"}, "the producer sets emotions later: every sentence starts neutral"
    assert short["beats"][0]["job"] == "hook" and short["beats"][-1]["job"] == "sting"
    assert short["script"]["bible"]["premise"] and short["script"]["report"]["score"] == 9 and short["script"]["report"]["rounds"] == 1
    draft = next(c for c in chat.calls if c["task"] == "p4_draft")
    assert "no content limits" in draft["system"] and "Show, do not report" in draft["system"] and '"tag"' not in draft["system"]
    later = [c for c in chat.calls if c["task"] == "p4_draft"][2]
    assert "WRITTEN SO FAR" in later["user"] and "NOW WRITE BEAT 3 of 5" in later["user"]


def test_a_low_score_runs_the_punch_up_again_and_a_broken_rewrite_is_ignored(gw):
    chat = FakeChat(room=True, scores=(5, 9))
    short = run(planner.make_plan(new_short()["id"], chat, S))
    assert chat.count("p4_punch") == 2 and short["script"]["report"]["rounds"] == 2
    bad = FakeChat(room=True, scores=(5,), punch_words=2)                              # a rewrite far under the word budget
    short = run(planner.make_plan(new_short()["id"], bad, {**S, "retries": 1}))
    assert [b["sentences"][0]["text"] for b in short["beats"]] == [n[0] for n in HINDI], "the draft stays when the rewrite breaks the budget"


def test_a_failing_room_falls_back_to_the_one_call_plan(gw):
    chat = FakeChat()                                                                  # room tasks raise
    short = run(planner.make_plan(new_short()["id"], chat, S))
    assert chat.room_refused == 1 and chat.count("p4_plan") == 1 and "script" not in short and len(short["beats"]) == 5
    single = FakeChat(room=True)
    run(planner.make_plan(new_short(script_engine="single")["id"], single, S))
    assert single.count("p4_bible") == 0


def test_word_budget_and_beats_scale_from_five_seconds_to_three_minutes():
    lo5, hi5 = planner.word_limits(5)[:2]
    lo30, hi30 = planner.word_limits(30)[:2]
    lo180, hi180, ask_lo, ask_hi = planner.word_limits(180)
    assert (lo30, hi30) == (64, 104) and 6 <= lo5 < hi5 <= 14 and lo180 > 5 * lo30 and hi180 <= (180 * 0.97 - 0.9) * timeline.TEMPO_MAX * timeline.PACE_WPS and ask_lo < ask_hi < hi180
    assert planner.beat_range(30) == (4, 6) and planner.beat_range(180) == (18, 26) and planner.beat_range(5)[0] == 2
    assert planner.word_limits(60)[0] < planner.word_limits(90)[0] < planner.word_limits(120)[0]


@pytest.mark.parametrize("seconds", [5, 12, 60, 120, 180])
def test_a_short_of_any_length_gets_a_timeline_of_exactly_that_length(gw, seconds):
    n = 2 if seconds < 10 else (4 if seconds <= 30 else (seconds // 9))
    chat = FakeChat(room=True, long=n)
    sid = new_short(language="en", target_s=seconds)["id"]
    short = run(planner.make_plan(sid, chat, S))
    tl = timeline.build(short, {})
    assert tl["total_s"] == pytest.approx(seconds, abs=0.5) and not tl["problems"], tl["problems"]
    assert max(s["seconds"] for s in tl["shots"]) <= 3.0 and sum(s["frames"] for s in tl["shots"]) == round(tl["total_s"] * 30)
    words = sum(len(x["text"].split()) for b in short["beats"] for x in b["sentences"])
    lo, hi = planner.word_limits(seconds)[:2]
    assert lo <= words <= hi, (words, lo, hi)


def test_the_api_takes_a_length_from_five_seconds_to_three_minutes(client):
    for bad in (4, 181, 0):
        assert client.post("/api/shorts", json={"pipeline": "quick", "kind": "idea", "text": "a courier finds a wallet", "settings": {"target_s": bad}}).status_code == 400
    r = client.post("/api/shorts", json={"pipeline": "quick", "kind": "idea", "text": "a courier finds a wallet", "settings": {"target_s": 150}})
    assert r.status_code == 200 and r.json()["settings"]["target_s"] == 150 and r.json()["settings"]["script_engine"] == "room"
    sid = r.json()["id"]
    assert client.patch(f"/api/shorts/{sid}/settings", json={"target_s": 200}).status_code == 400
    assert client.patch(f"/api/shorts/{sid}/settings", json={"target_s": 5}).json()["settings"]["target_s"] == 5


def _planned_room(chat=None):
    chat = chat or FakeChat(room=True)
    return run(planner.make_plan(new_short()["id"], chat, SR)), chat


def test_a_scene_rewrite_follows_the_producers_words_and_keeps_the_rest(gw):
    short, chat = _planned_room()
    before = {b["id"]: [x["text"] for x in b["sentences"]] for b in short["beats"]}
    shots = {b["id"]: list(b["shot_ids"]) for b in short["beats"]}
    after = run(planner.rewrite_beat(short["id"], "b2", "make it colder and let her say his name", chat, SR))
    again = store.get(short["id"])
    new = {b["id"]: [x["text"] for x in b["sentences"]] for b in again["beats"]}
    assert new["b2"] != before["b2"] and all(new[k] == before[k] for k in new if k != "b2")
    assert {b["id"]: b["shot_ids"] for b in again["beats"]} == shots, "the pictures stay"
    call = [c for c in chat.calls if c["task"] == "p4_draft"][-1]
    assert "make it colder and let her say his name" in call["user"] and "THE CURRENT TEXT OF THIS BEAT" in call["user"] and "COMES AFTER" in call["user"] and "NOW WRITE BEAT 2 of 5" in call["user"]
    assert {x["tag"] for x in again["beats"][1]["sentences"]} == {"neutral"} and after["shots"]


def test_the_whole_script_can_be_written_again_with_the_same_beats_and_shots(gw):
    short, chat = _planned_room()
    old = [(b["id"], list(b["shot_ids"]), [x["text"] for x in b["sentences"]]) for b in short["beats"]]
    run(planner.rewrite_script(short["id"], "colder, and end on the door", chat, SR))
    again = store.get(short["id"])
    assert [(b["id"], b["shot_ids"]) for b in again["beats"]] == [(i, s) for i, s, _ in old]
    assert all([x["text"] for x in b["sentences"]] != t for b, (_, _, t) in zip(again["beats"], old))
    drafts = [c for c in chat.calls if c["task"] == "p4_draft"][5:]
    assert len(drafts) == 5 and all("colder, and end on the door" in c["user"] for c in drafts) and chat.count("p4_punch") == 2
    assert again["script"]["report"]["score"] == 9 and again["script"]["bible"]["premise"]


def test_a_short_from_the_one_call_plan_can_be_rewritten_too(gw):
    chat = FakeChat()
    short = run(planner.make_plan(new_short()["id"], chat, S))
    assert "script" not in short
    chat.room = True
    run(planner.rewrite_beat(short["id"], "b1", "shorter and angrier", chat, S))
    assert [x["text"] for x in store.get(short["id"])["beats"][0]["sentences"]] != [x["text"] for x in short["beats"][0]["sentences"]]


def test_api_rewrite_asks_for_the_change_in_a_scene_and_runs_as_a_job(client):
    client.chat.room = True
    sid = client.post("/api/shorts", json={"pipeline": "keyframe", "kind": "idea", "text": "A courier finds a wallet with a lakh rupees."}).json()["id"]
    assert client.post(f"/api/shorts/{sid}/plan").status_code == 200 and wait_job(client, sid)["state"] == "done"
    assert client.post(f"/api/shorts/{sid}/rewrite", json={"beat_id": "b9", "instruction": "scarier"}).status_code == 400
    assert client.post(f"/api/shorts/{sid}/rewrite", json={"beat_id": "b2", "instruction": " "}).status_code == 400
    old = client.get(f"/api/shorts/{sid}").json()["beats"]
    assert client.post(f"/api/shorts/{sid}/rewrite", json={"beat_id": "b2", "instruction": "scarier"}).status_code == 200
    assert wait_job(client, sid)["state"] == "done"
    new = client.get(f"/api/shorts/{sid}").json()["beats"]
    assert new[1]["sentences"] != old[1]["sentences"] and new[0]["sentences"] == old[0]["sentences"]
    assert client.post(f"/api/shorts/{sid}/rewrite", json={}).status_code == 200 and wait_job(client, sid)["state"] == "done"


# ── the picture writer (shorts/stillwriter.py) ───────────────────────────────

from shorts import stillwriter, stills


def test_the_picture_writer_writes_each_start_picture_prompt_from_the_narration_and_the_shots(gw):
    chat = FakeChat(stills=True)
    short = run(planner.make_plan(new_short()["id"], chat, S))
    assert chat.count("p4_still") == len(short["beats"]) and all(sh["still_by"] == "writer" and sh["must_show"] for sh in short["shots"])
    assert all(sh["still"].startswith("Close-up of one courier") for sh in short["shots"])
    first = next(c for c in chat.calls if c["task"] == "p4_still")
    assert "THIS BEAT" in first["user"] and "THE SHOTS OF THIS BEAT" in first["user"] and "Write the pictures of: s1," in first["user"]
    assert "exact number" in first["system"] and "beneath each wing" in first["system"] and "DO NOT REPEAT" in first["system"]


def test_a_failing_picture_writer_keeps_the_planners_stills(gw):
    chat = FakeChat()
    short = run(planner.make_plan(new_short()["id"], chat, S))
    assert chat.count("p4_still") == 0 and all("still_by" not in sh and sh["still"].startswith("A courier stands over") for sh in short["shots"])


def test_the_picture_writer_sends_back_vague_counts_negatives_and_filler():
    bad = stillwriter.StillOut(id="s1", still="Many sleek grey metal jets fly without missiles on top of the wings in a big crowd over the hills at sunset today")
    msg = "; ".join(stillwriter.problems(bad))
    assert "Many" in msg and "without" in msg and "sleek" in msg
    good = stillwriter.StillOut(id="s1", still="Low-angle wide shot of three fighter jets flying left to right over a ridge, one missile on a pylon beneath each wing, the top of the wings bare")
    assert stillwriter.problems(good) == []
    chat = FakeChat(stills=True, still_text=bad.still)
    run(planner.make_plan(new_short()["id"], chat, {**S, "retries": 1}))
    assert chat.count("p4_still") == 2 * 5, "each beat is sent back once, then the last attempt is accepted"


def test_the_start_picture_prompt_says_everything_once_and_starts_with_the_picture(gw):
    short = planned()
    short["plan"]["character"] = "A man in his late twenties, lean build, messy black hair, dark grey oversized hoodie."
    short["plan"]["subjects"] = [{"name": "The Man", "kind": "person", "visual": "An Indian man in his late twenties, lean build, messy black hair, dark grey oversized hoodie."},
                                 {"name": "Phone", "kind": "object", "visual": "A black smartphone with a glowing screen."},
                                 {"name": "Dim Room", "kind": "place", "visual": "A small room with one lamp and a heavy wooden door."}]
    sh = short["shots"][0]
    sh.update(character=True, subjects=["The Man", "Phone", "Dim Room"], camera="slow push in", still="Medium shot of one man holding one phone at chest height, the screen facing him.", setting="")
    out = stills.prompt(short, sh)
    assert out.startswith("Medium shot of one man holding one phone")
    assert out.count("dark grey oversized hoodie") == 1, "the main character is not repeated as a subject"
    assert "Phone: A black smartphone" in out and out.count("Setting:") == 1 and "heavy wooden door" in out and "Camera:" not in out and "slow push" not in out
    assert "Dim Room:" not in out, "a place subject becomes the setting, once"


def test_the_api_rewrites_one_picture_prompt_with_the_producers_instruction(client):
    client.chat.stills = True
    sid = client.post("/api/shorts", json={"pipeline": "quick", "kind": "idea", "text": "A courier finds a wallet with a lakh rupees."}).json()["id"]
    assert client.post(f"/api/shorts/{sid}/plan").status_code == 200 and wait_job(client, sid)["state"] == "done"
    assert client.post(f"/api/shorts/{sid}/pictures/write", json={"shot_id": "s99"}).status_code == 400
    client.chat.still_text = "Wide shot of exactly three couriers waiting at one bus stop, each holding one parcel in the right hand."
    n = client.chat.count("p4_still")
    assert client.post(f"/api/shorts/{sid}/pictures/write", json={"shot_id": "s2", "instruction": "three couriers, parcels in the right hand"}).status_code == 200
    assert wait_job(client, sid)["state"] == "done"
    shots = client.get(f"/api/shorts/{sid}").json()["shots"]
    assert shots[1]["still"].startswith("Wide shot of exactly three couriers") and not shots[0]["still"].startswith("Wide shot of exactly three")
    last = [c for c in client.chat.calls if c["task"] == "p4_still"][-1]
    assert client.chat.count("p4_still") == n + 1 and "three couriers, parcels in the right hand" in last["user"] and "Write the pictures of: s2." in last["user"] and "(KEEP, already written" in last["user"]


# ── the motion writer (shorts/motionwriter.py) ───────────────────────────────

from shorts import motionwriter


def test_the_motion_writer_writes_what_moves_for_every_shot_and_wan_gets_only_that(gw):
    chat = FakeChat(moves=True)
    short = run(planner.make_plan(new_short("keyframe")["id"], chat, S))
    assert chat.count("p4_move") == len(short["beats"]) and all(sh["move_by"] == "writer" and "camera" in sh["move"] for sh in short["shots"])
    first = next(c for c in chat.calls if c["task"] == "p4_move")
    assert "THE LINE THE VIEWER HEARS" in first["user"] and "what the picture shows:" in first["user"] and "(2.0 s" in first["user"] or "s, planner's camera" in first["user"]
    assert "ONLY WHAT MOVES" in first["system"] and "NEVER describe looks" in first["system"]
    sh = short["shots"][1]
    req = P.animate_request(short, sh, 1, "data:image/jpeg;base64,x")
    assert req["prompt"] == f"{sh['move']} {P.HOLD}" and "Camera:" not in req["prompt"] and "graphic" not in req["prompt"]
    assert "morphing face" in req["negative_prompt"] and "scene cut" in req["negative_prompt"]
    assert "morphing face" not in P.quick_request(short, sh, 1)["negative_prompt"], "the text-to-video request keeps the plain negative prompt"
    assert P.compose(short, sh, False).startswith("The courier stops"), "a shot Wan draws from text still uses the planner's prompt"


def test_a_failing_motion_writer_keeps_the_planners_prompt_and_camera(gw):
    short = run(planner.make_plan(new_short("keyframe")["id"], FakeChat(), S))
    assert all("move" not in sh for sh in short["shots"])
    sh = short["shots"][0]
    out = P.compose(short, sh, True)
    assert out.startswith(sh["prompt"]) and out.endswith(f"Camera: {sh['camera']}.") and "graphic" not in out


def test_the_motion_writer_sends_back_looks_negatives_and_a_missing_camera():
    bad = motionwriter.MoveOut(id="s1", move="The man wearing a dark hoodie does not move at all while his sharp cinematic face glows in a noir style room")
    msg = "; ".join(motionwriter.problems(bad))
    assert "wearing" in msg and "not" in msg and "camera" in msg
    good = motionwriter.MoveOut(id="s1", move="The man slowly lifts the phone toward his face, his brow tightening. The camera slowly pushes in. The screen glow flickers brighter.")
    assert motionwriter.problems(good) == []


def test_avatar_and_reference_video_shots_are_left_to_their_own_models(gw):
    short = run(planner.make_plan(new_short("keyframe")["id"], FakeChat(moves=True), S))
    a, m = short["shots"][0], short["shots"][1]
    a["avatar"], m["motion"] = True, {"file": "motion/x.mp4"}
    assert not motionwriter.eligible(a) and not motionwriter.eligible(m) and motionwriter.eligible(short["shots"][2])


def test_the_api_rewrites_the_motion_of_one_shot_with_the_producers_instruction(client):
    client.chat.moves = True
    sid = client.post("/api/shorts", json={"pipeline": "keyframe", "kind": "idea", "text": "A courier finds a wallet with a lakh rupees."}).json()["id"]
    assert client.post(f"/api/shorts/{sid}/plan").status_code == 200 and wait_job(client, sid)["state"] == "done"
    assert client.post(f"/api/shorts/{sid}/motion/write", json={"shot_id": "s99"}).status_code == 400
    client.chat.move_text = "The courier turns his head quickly to the left, the camera pans left to follow him, a bus passes slowly behind."
    n = client.chat.count("p4_move")
    assert client.post(f"/api/shorts/{sid}/motion/write", json={"shot_id": "s3", "instruction": "he turns his head fast"}).status_code == 200
    assert wait_job(client, sid)["state"] == "done"
    shots = client.get(f"/api/shorts/{sid}").json()["shots"]
    assert shots[2]["move"].startswith("The courier turns his head quickly") and not shots[0]["move"].startswith("The courier turns his head")
    last = [c for c in client.chat.calls if c["task"] == "p4_move"][-1]
    assert client.chat.count("p4_move") == n + 1 and "he turns his head fast" in last["user"] and "Write the motion of: s3." in last["user"] and "KEEP, already written" in last["user"]
    assert client.patch(f"/api/shorts/{sid}/shots/s3", json={"move": "The courier raises one hand, the camera holds still."}).json()["shots"][2]["move"].startswith("The courier raises one hand")


def test_cast_must_be_named_by_the_second_beat_and_story_personas_exist():
    from shorts import script, tones
    bible = script.BibleOut(premise="p", cast=[script.CastOut(name="Elias Roy", role="the man")])
    assert script.cast_problems(bible, [{"text": "A man hears a ping."}])
    assert not script.cast_problems(bible, [{"text": "Elias hears a ping."}])
    assert not script.cast_problems(script.BibleOut(premise="p"), [{"text": "A man hears a ping."}]), "no cast, no check"
    assert {t["id"] for t in tones.public()["tones"] if t["group"] == "Story personas"} == {"survivor", "campfire", "investigator", "memoir"}
    real = {"source": {"kind": "story"}}
    assert "never invent a person" in script._people_rules(real)[0] and "name that fits" in script._people_rules({"source": {"kind": "idea"}})[0]


@needs_ffmpeg
def test_2k_upscales_each_clip_then_puts_the_short_together_at_1440x2560(gw):
    from shorts import auto, upscale
    sid = planned("quick", image_mode="wan", upscale="2k")["id"]
    run(svoice.make(sid, s=S, key="k"))
    run(clips.make_clips(sid, s=S, key="k"))
    n = len(store.get(sid)["shots"])
    assert upscale.missing(store.get(sid)) and not stitch.checklist(store.get(sid))["ready"], "the 2K clips are a step of their own"
    with pytest.raises(Exception):
        stitch.build(sid)
    assert next(x for x in auto.steps(store.get(sid)) if x["id"] == "upscale")["done"] is False
    res = run(upscale.make(sid, s=S, key="k"))
    assert res["made"] == n and not res["failed"] and len(gw.upscales) == n
    assert gw.upscales[0]["resolution"] == "2k" and gw.upscales[0]["video"].startswith("data:video/mp4") and not upscale.missing(store.get(sid))
    assert run(upscale.make(sid, s=S, key="k"))["made"] == 0, "a finished 2K clip is kept"
    final = stitch.build(sid)
    info = frames.info(store.media_dir(sid) / final["file"])
    assert info["streams"][0]["width"] == 1440 and info["streams"][0]["height"] == 2560 and abs(info["duration_s"] - 30.0) < 0.2
    assert auto.changed_since(store.get(sid), media.get(final["id"])) is False
    short = store.get(sid)
    short["settings"]["upscale"] = ""
    store.save(short)
    assert auto.changed_since(store.get(sid), media.get(final["id"])), "turning 2K off makes the video old"


def test_2k_is_never_wanted_for_a_remix_short(gw):
    from shorts import upscale
    short = new_short("quick")
    assert not upscale.wanted(short)
    short["settings"]["upscale"] = "2k"
    assert upscale.wanted(short)
    short["pipeline"] = "remix"
    assert not upscale.wanted(short)


def test_style_motion_hint_reaches_motion_writer_and_negative_keeps_what_the_style_needs():
    from shorts import looks, motionwriter, pipelines as P
    short = {"settings": {"visual_style": "claymation"}, "plan": {"title": "t", "logline": "l"}, "beats": [{"id": "b1", "sentences": [], "shot_ids": []}]}
    assert "Stop-motion" in looks.motion_hint(short)
    assert "MOTION FEEL" in motionwriter._context(short, short["beats"][0], [], None)
    neg = looks.negative(short, P.NEGATIVE_MOVE)
    assert "noise" not in neg.split(", ") and "film grain" not in neg.split(", ") and "warping" in neg
    tiny = {"settings": {"visual_style": "tinyworld"}}
    assert "blurry" not in looks.negative(tiny, P.NEGATIVE).split(", ")
    assert "flicker" not in looks.negative({"settings": {"visual_style": "cyberpunk"}}, P.NEGATIVE_MOVE).split(", ")
    plain = {**short, "settings": {"visual_style": "realism"}}
    assert looks.motion_hint(plain) == "" and looks.negative(plain, P.NEGATIVE) == P.NEGATIVE
    assert "MOTION FEEL" not in motionwriter._context(plain, short["beats"][0], [], None)
    for k, v in looks.TRENDING.items():
        assert v["motion"] and not motionwriter.LOOKS.search(v["motion"]), k


def test_trending_looks_name_no_content_so_they_cannot_add_people_buildings_or_sky():
    import re
    from shorts import looks
    content = re.compile(r"\b(figures?|characters?|people|person|buildings?|city|cities|streets?|sky|clouds?|nature|trees?|town|crowd)\b", re.I)
    for k, v in looks.TRENDING.items():
        assert not content.search(v["look"]), (k, content.search(v["look"]).group(0))


def test_a_period_is_not_a_subject_and_camera_words_leave_a_subjects_look():
    from shorts import stills, stillwriter, subjects
    assert not subjects.drawable({"name": "The Construction Era", "kind": "period of history"}) and subjects.drawable({"name": "Cold Kingdom", "kind": "place"})
    assert subjects.plain_visual("A tiny ant with a black shell, seen from a macro perspective.") == "A tiny ant with a black shell."
    assert stills.one_place("A vast kitchen counter that transitions into the frosty interior of a fridge.") == "A vast kitchen counter"
    assert stills.one_place("A rooftop at night") == "A rooftop at night"
    short = {"plan": {"subjects": [{"name": "The Construction Era", "kind": "period", "visual": "A scene of ants building."}, {"name": "Ant", "kind": "person", "visual": "A tiny ant."}]}}
    assert [x["name"] for x in subjects.in_shot(short, {"prompt": "Wide shot of The Construction Era with one Ant", "subjects": ["The Construction Era", "Ant"]})] == ["Ant"]
    big = stillwriter.StillOut(id="s1", still="Wide shot of twelve ants on the left and twelve cockroaches on the right, in a cold hall, facing each other now.")
    assert any("too many to draw" in p for p in stillwriter.problems(big))
    ok = stillwriter.StillOut(id="s1", still="Wide shot of five ants on the left and five cockroaches on the right, in a cold hall, facing each other now.")
    assert not any("too many" in p for p in stillwriter.problems(ok))


def test_a_trending_style_leads_the_picture_prompt_and_the_other_styles_do_not():
    from shorts import looks, stills
    short = planned("keyframe", visual_style="tinyworld")
    p = stills.prompt(short, short["shots"][0])
    assert p.startswith(looks.TRENDING["tinyworld"]["lead"]) and p.count("Miniature diorama") == 1
    assert all(v["lead"].startswith(tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ")) and "every subject" in v["lead"] for v in looks.TRENDING.values())
    plain = planned("keyframe", visual_style="realism")
    assert looks.lead(plain) == "" and not stills.prompt(plain, plain["shots"][0]).startswith("Clay")


def test_narration_addresses_the_viewer_as_aap_and_questions_are_thinned():
    from shorts import languages, script
    assert languages.address_hits("Tu soch raha hoga") == ["tu"]
    assert languages.address_hits("तेरा brain और Tumhara dimaag") == ["तेरा", "tumhara"]
    assert languages.address_hits("आप सोच रहे होंगे, ट्यूब और tuned") == []
    assert "aap" in languages.rule({"language": "hinglish"}) and "aap" not in languages.rule({"language": "en"})
    assert "aap" not in languages.rule({"language": "hinglish", "address": "tu"})
    sents = [{"text": "Tu dekh।", "tag": ""}]
    assert any("aap" in p for p in script.draft_problems(sents, 1, 9, "hinglish", ""))
    assert not any("aap" in p for p in script.draft_problems(sents, 1, 9, "hinglish", "", "tu"))
    assert any("question" in p for p in script.draft_problems([{"text": "Kya?", "tag": ""}], 1, 9, "en", "Par kaise?"))
    beats = [script.MapBeat(name=f"b{i}", job="escalate", seconds=5, cliff="kya hoga?") for i in range(8)]
    kept = [x["cliff"] for x in script.fit_map(beats, 40)]
    assert kept[-1] == "" and sum(bool(c) for c in kept) <= 3 and not any(kept[i] and kept[i + 1] for i in range(7))
    short = {"settings": {"language": "hinglish"}}
    assert script.hard_problems(short, [{"text": "तेरा brain।", "tag": ""}]) and not script.hard_problems(short, [{"text": "आपका brain।", "tag": ""}])


def test_styles_are_lit_bright_unless_dark_by_design():
    from shorts import looks
    c = looks.of({"settings": {"visual_style": "concept"}})
    assert "moody" not in c.lower() and looks.LIGHT in c
    assert looks.of({"settings": {"visual_style": "concept"}}).count(looks.LIGHT) == 1
    assert looks.of({"settings": {"visual_style": "cyberpunk"}}) == looks.presets()["cyberpunk"]["look"]
    assert looks.of({"settings": {"visual_style": "noir"}}) == looks.presets()["noir"]["look"]
    assert looks.of({"settings": {}}, "plan look") == "plan look"


def test_ideas_config_is_saved_on_the_server_and_the_job_reports_ideas_as_they_are_written(client, monkeypatch):
    from shorts import api as shorts_api, ideas as ideas_mod
    assert client.get("/api/shorts/ideas/config").json()["autorun"] is False
    saved = client.put("/api/shorts/ideas/config", json={"autorun": True, "n": 99, "min_score": 6.5, "run": {"voice": "x_voice", "target_s": 400, "bogus": 1}}).json()
    assert saved["autorun"] and saved["n"] == 15 and saved["min_score"] == 6.5 and saved["run"]["voice"] == "x_voice" and saved["run"]["target_s"] == 180 and "bogus" not in saved["run"]
    assert client.get("/api/shorts/ideas/config").json() == saved

    async def fake_generate(n, s, key, diverse=False, progress=None, sink=None, sigs=None):
        for k in range(2):
            progress(k, 2, f"lens {k + 1} of 2")
            sink.append(ideas_mod.add(["Octopus hearts", "Mughal canals"][k], ["Why do octopuses have three hearts?", "How did Mughal engineers move water uphill?"][k], ["novelty"], "p", "w"))
            await asyncio.sleep(0.05)
        return list(sink)

    async def fake_rate(ids, s, key):
        return [ideas_mod.get(i) for i in ids]
    async def no_signals(*a, **k):
        return []
    from shorts import discover
    monkeypatch.setattr(discover, "signals", no_signals)
    monkeypatch.setattr(ideas_mod, "generate", fake_generate)
    monkeypatch.setattr(ideas_mod, "rate", fake_rate)
    r = client.post("/api/shorts/ideas/generate", json={"n": 2, "diverse": True})
    assert r.status_code == 200 and r.json()["state"] == "running"
    assert client.post("/api/shorts/ideas/generate", json={"n": 2}).status_code == 409, "one run at a time"
    t0 = time.time()
    while time.time() - t0 < 10:
        j = client.get("/api/shorts/ideas/run").json()
        if j["state"] != "running":
            break
        time.sleep(0.05)
    assert j["state"] == "done" and len(j["new_ids"]) == 2 and j["rated"] == 2 and j["kind"] == "generate"


def test_auto_queue_picks_the_best_good_enough_conditioned_idea(client):
    from shorts import api as shorts_api, ideas as ideas_mod
    low = ideas_mod.add("low", "low?", [], "p", "w")
    best = ideas_mod.add("best", "best?", [], "p", "w")
    for i, sc in ((low, 5.0), (best, 8.5)):
        ideas_mod.save_score(i["id"], sc, {})
        ideas_mod.save_conditioning(i["id"], {"refined_hook": "h", "narrative_arc": ["0-5s: a"], "key_facts": ["f"], "visual_direction": "bright realism", "suggested_tone": "bigbro"})
    assert ideas_mod.next_for_autoqueue(9.0) is None
    assert ideas_mod.next_for_autoqueue(7.0)["id"] == best["id"]
    out = shorts_api._queue_idea(best["id"], "keyframe", shorts_api._run_settings(ideas_mod.get_config()["run"]), False)
    assert out["idea"]["status"] == "queued" and out["short_id"] and not out["auto_started"]
    assert ideas_mod.next_for_autoqueue(0.0)["id"] == low["id"]
    short = store.get(out["short_id"])
    assert short["settings"]["voice"]["engine"] == "maya-tts" and short["settings"]["review_keyframes"] is False
    text = short["source"]["text"]                                             # concept only: an old brief's arc is not handed to the script room
    assert "Narrative arc" not in text and "0-5s" not in text and "Key facts:" in text and "• f" in text


def test_the_ideas_list_route_is_not_taken_by_the_short_id_route(client):
    from shorts import ideas as ideas_mod
    ideas_mod.add("t", "hook?", [], "p", "w")
    r = client.get("/api/shorts/ideas")
    assert r.status_code == 200 and [i["hook"] for i in r.json()][-1:] == ["hook?"]


def test_duplicates_of_any_earlier_idea_are_rejected_before_scoring(client):
    from shorts import ideas as ideas_mod
    old = ideas_mod.add("Octopus hearts", "Why do octopuses have three hearts and blue blood?", [], "p", "w")
    ideas_mod.set_status(old["id"], "rejected")
    same = ideas_mod.add("Three hearts octopus", "Why do octopuses have three hearts and blue blood really?", [], "p", "w")
    other = ideas_mod.add("Mughal canals", "How did Mughal engineers move water uphill?", [], "p", "w")
    dups = asyncio.run(ideas_mod.dedup([same["id"], other["id"]], {}, "k"))
    assert dups == [same["id"]]
    r = ideas_mod.get(same["id"])
    assert r["status"] == "rejected" and r["dup_of"] == old["id"] and r["reject_reason"].startswith("Duplicate") and ideas_mod.get(other["id"])["status"] == "pending"
    twin = ideas_mod.add("Mughal canals again", "How did Mughal engineers move the water uphill?", [], "p", "w")
    assert asyncio.run(ideas_mod.dedup([twin["id"]], {}, "k")) == [twin["id"]], "a repeat of a pending idea is rejected too"


def test_styles_come_only_from_the_ticked_list_and_rotate(client):
    from shorts import ideas as ideas_mod
    assert ideas_mod.pick_style([], "bright realism") == ""
    cfg = ideas_mod.save_config({"styles": ["anime", "realism", "nonsense"]})
    assert cfg["styles"] == ["anime", "realism"]
    assert ideas_mod.pick_style(cfg["styles"], "Realism - bright daylight") == "realism"
    assert ideas_mod.pick_style(cfg["styles"], "cyberpunk neon") == "anime"            # not allowed: the least used allowed style
    i = ideas_mod.add("t", "hook", [], "p", "w")
    from story import db
    db.ex("UPDATE short_ideas SET style='anime' WHERE id=?", (i["id"],))
    assert ideas_mod.pick_style(cfg["styles"], "") == "realism"


def test_the_autopilot_starts_one_job_at_a_time_on_its_schedule(client, monkeypatch):
    from shorts import api as shorts_api, ideas as ideas_mod
    from story2 import jobs
    started = []
    monkeypatch.setattr(shorts_api, "_start_generate", lambda cfg: started.append("generate"))
    monkeypatch.setattr(shorts_api, "_start_condition", lambda cfg: bool(started.append("condition")) or True)
    monkeypatch.setattr(shorts_api, "_start_make", lambda cfg: started.append("make") or "sh-x")
    tick = lambda now: asyncio.run(shorts_api.conductor_tick(now))
    ideas_mod.save_config({"autopilot": True, "auto_generate": True, "auto_condition": True, "autorun": True, "planning_cap": 2, "gen_every_h": 1, "make_every_h": 2})
    monkeypatch.setattr(jobs, "busy", lambda: True)
    assert tick(1000.0) is None, "never while another job runs"
    monkeypatch.setattr(jobs, "busy", lambda: False)
    assert tick(1000.0) == "generate" and ideas_mod.get_config()["next_gen_at"] == 1000.0 + 3600
    assert tick(1010.0) == "condition", "the batch is not due again; an approved idea waits for its brief"
    monkeypatch.setattr(shorts_api, "_start_condition", lambda cfg: False)
    done = ideas_mod.add("t", "hook one two three", [], "p", "w")
    ideas_mod.set_status(done["id"], "queued", "sh-1")                                      # a short that was made needs no review click: it never blocks the next one
    assert tick(1030.0) == "make" and ideas_mod.get_config()["next_make_at"] == 1030.0 + 7200
    assert tick(1040.0) is None, "the next short is two hours away"
    assert started == ["generate", "condition", "make"]


def test_at_most_planning_cap_briefs_wait_to_be_made(client, monkeypatch):
    from shorts import api as shorts_api, ideas as ideas_mod
    from story2 import jobs
    started = []
    monkeypatch.setattr(shorts_api, "_start_condition", lambda cfg: bool(started.append("condition")) or True)
    monkeypatch.setattr(jobs, "busy", lambda: False)
    ideas_mod.save_config({"autopilot": True, "auto_condition": True, "planning_cap": 2})
    for n in range(2):
        i = ideas_mod.add(f"t{n}", f"hook {n} two three", [], "p", "w")
        ideas_mod.save_conditioning(i["id"], {"refined_hook": "h"})
    assert asyncio.run(shorts_api.conductor_tick(1000.0)) is None and not started, "two briefs are in planning: no third"
    ideas_mod.set_status(ideas_mod.listing("conditioned")[0]["id"], "queued", "sh-1")        # one moved into production
    assert asyncio.run(shorts_api.conductor_tick(1010.0)) == "condition"


def test_the_master_switch_turns_the_whole_autopilot_off(client, monkeypatch):
    from shorts import api as shorts_api, ideas as ideas_mod
    from story2 import jobs
    started = []
    monkeypatch.setattr(shorts_api, "_start_generate", lambda cfg: started.append("generate"))
    monkeypatch.setattr(jobs, "busy", lambda: False)
    ideas_mod.save_config({"autopilot": False, "auto_generate": True})
    assert asyncio.run(shorts_api.conductor_tick(5000.0)) is None and not started, "the sub-switches do nothing while the master switch is off"
    ideas_mod.save_config({"autopilot": True})
    assert asyncio.run(shorts_api.conductor_tick(5000.0)) == "generate"
    assert client.get("/api/shorts/ideas/autopilot").json()["on"] is True


def test_upload_text_is_written_cleaned_and_copy_ready(client):
    from shorts import publish, store
    sid = client.post("/api/shorts", json={"pipeline": "keyframe", "kind": "idea", "text": "A courier finds a wallet with a lakh rupees."}).json()["id"]
    client.post(f"/api/shorts/{sid}/plan")
    wait_job(client, sid)
    r = client.post(f"/api/shorts/{sid}/publish", json={})
    assert r.status_code == 200, r.text
    p = r.json()
    assert 20 <= len(p["title"]) <= publish.TITLE_MAX and "#" not in p["title"]
    assert p["hashtags"][0] == "#Shorts" and "#WalletStory" in p["hashtags"] and len(p["hashtags"]) <= publish.HASHTAGS_MAX
    assert p["description"].rstrip().endswith(" ".join(p["hashtags"])) and p["description"].count("#Shorts") == 1 and len(p["description"]) <= 5000
    assert len(p["tags"]) >= 6 and p["tags_text"] == ", ".join(p["tags"]) and p["stale"] is False
    assert client.get(f"/api/shorts/{sid}").json()["publish"]["title"] == p["title"]
    short = store.get(sid)
    short["beats"][0]["sentences"][0]["text"] = "Kuch aur।"
    store.save(short)
    assert client.get(f"/api/shorts/{sid}").json()["publish"]["stale"] is True, "the narration changed after the text was written"
    assert publish.clean_title('"' + "word " * 30 + '"') .__len__() <= publish.TITLE_MAX


def test_description_keeps_one_hashtag_line_and_dedup_accepts_ids_without_prefix(client, monkeypatch):
    from shorts import ideas as ideas_mod, publish
    d = publish.clean_description("Hook line here.\n\nFollow for more! #Shorts #India\n#Shorts #India #Facts", ["#Shorts", "#India"])
    assert d == "Hook line here.\n\nFollow for more!\n\n#Shorts #India"
    old = ideas_mod.add("S-400 final delivery", "Why is India's final S-400 delivery in November a game-changer?", [], "India gets the last S-400 squadron.", "")
    new = ideas_mod.add("Last S-400 arrives", "What changes when India's last S-400 squadron arrives this month?", [], "The final S-400 system reaches India in November.", "")

    class FakeCaller:
        last_attempt = False

        def __init__(self, *a, **k):
            pass

        async def call(self, system, user, model_cls, validate=None):
            from types import SimpleNamespace
            return SimpleNamespace(value=model_cls(results=[{"id": new["id"].removeprefix("idea-"), "same_as": old["id"].removeprefix("idea-"), "why": "same event"}]))
    monkeypatch.setattr(ideas_mod.llm_mod, "JsonCaller", FakeCaller)
    monkeypatch.setattr(ideas_mod.llm_mod, "ChatBackend", lambda s, k: None)
    assert asyncio.run(ideas_mod.dedup([new["id"]], {}, "k")) == [new["id"]]
    assert ideas_mod.get(new["id"])["dup_of"] == old["id"]


def test_web_signals_use_search_the_now_tool_and_full_pages(client, monkeypatch):
    import random
    from datetime import datetime
    from shorts import discover
    calls = []

    async def fake_post(c, base, key, name, body):
        calls.append((name, body))
        if name == "now":
            return {"data": {"iso": "2026-11-08T10:34:37+05:30"}}
        if name == "web_search":
            q = body["query"]
            return {"data": {"results": [{"title": f"{q} one", "url": f"https://x.test/{abs(hash(q)) % 999}/1", "snippet": "a   snippet"}, {"title": f"{q} two", "url": f"https://x.test/{abs(hash(q)) % 999}/2", "snippet": ""}]}}
        if name == "fetch_url":
            return {"result": "Title: t\nURL: u\n\n" + "A real page about the topic. " * 20}
        return {}
    monkeypatch.setattr(discover, "_post_tool", fake_post)
    sigs = asyncio.run(discover.signals({"base_url": "http://gw/v1"}, "k", rnd=random.Random(1)))
    names = [n for n, _ in calls]
    assert names[0] == "now" and names.count("web_search") == discover.QUERIES_PER_RUN and names.count("fetch_url") == discover.PAGES_PER_RUN
    assert [x["n"] for x in sigs] == list(range(1, len(sigs) + 1)) and len(sigs) <= discover.MAX_SIGNALS
    detailed = [x for x in sigs if x.get("detail")]
    assert len(detailed) == discover.PAGES_PER_RUN and all(len(x["detail"]) <= discover.DETAIL_CHARS and not x["detail"].startswith("Title") for x in detailed)
    assert "November" in " ".join(q["query"] for n, q in calls if n == "web_search"), "queries use the date from the now tool"
    text = discover.block(sigs)
    assert "page: A real page" in text and "WEB SIGNALS" in text and discover.block([]) == ""
    assert discover.pick(sigs, [2, 2, 99, "x"]) == [{"title": sigs[1]["title"], "url": sigs[1]["url"]}]
    assert discover.queries(datetime(2026, 11, 8), random.Random(0))[:2] == ["India news today", "on this day in history November 8"]


def test_web_search_down_means_no_signals_not_an_error(client, monkeypatch):
    from shorts import discover

    async def broken(*a, **k):
        raise RuntimeError("search is down")
    monkeypatch.setattr(discover, "_search", broken)
    monkeypatch.setattr(discover, "RETRY_EMPTY_S", 0)
    monkeypatch.setattr(discover, "_post_tool", lambda *a, **k: asyncio.sleep(0, result={}))
    assert asyncio.run(discover.signals({"base_url": "http://gw/v1"}, "k")) == []


def test_schedule_and_failures_survive_a_restart_and_a_chosen_idea_can_run_now(client, monkeypatch):
    from shorts import api as shorts_api, ideas as ideas_mod
    from story2 import jobs
    ideas_mod.save_config({"autopilot": True, "auto_condition": True})
    ideas_mod.set_state(next_gen_at=123456.0, next_make_at=234567.0)
    cfg = ideas_mod.get_config()                                       # read straight from the database, as a restarted app would
    assert cfg["next_gen_at"] == 123456.0 and cfg["next_make_at"] == 234567.0 and cfg["autopilot"] is True
    a = ideas_mod.add("A", "hook a one two", [], "p", "w")
    b = ideas_mod.add("B", "hook b three four", [], "p", "w")
    for i, sc in ((a, 9.0), (b, 8.0)):
        ideas_mod.save_score(i["id"], sc, {})
        ideas_mod.set_status(i["id"], "approved")
    assert ideas_mod.next_to_condition()["id"] == a["id"]
    ideas_mod.bump_cond_fail(a["id"])
    ideas_mod.bump_cond_fail(a["id"])
    assert ideas_mod.get(a["id"])["cond_fails"] == 2 and ideas_mod.next_to_condition()["id"] == b["id"], "an idea whose brief failed twice is left alone, even after a restart"
    started = []

    def fake_start(kind, work):
        started.append(kind)
        return {}
    monkeypatch.setattr(shorts_api, "_start_idea_job", fake_start)
    monkeypatch.setattr(jobs, "busy", lambda: False)
    r = client.post("/api/shorts/ideas/autopilot/run", json={"stage": "condition", "idea_id": a["id"]})
    assert r.status_code == 200 and started == ["condition"], "a chosen idea runs even after failures"
    assert client.post("/api/shorts/ideas/autopilot/run", json={"stage": "make", "idea_id": a["id"]}).status_code == 400, "not conditioned yet"
    pend = ideas_mod.add("C", "hook c five six", [], "p", "w")
    assert client.post("/api/shorts/ideas/autopilot/run", json={"stage": "condition", "idea_id": pend["id"]}).status_code == 400
    ideas_mod.save_conditioning(a["id"], {"refined_hook": "h"})
    assert ideas_mod.get(a["id"])["cond_fails"] == 0, "a brief that works clears the failures"


def test_queues_and_upload_text_reach_the_ideas_screen(client):
    from shorts import ideas as ideas_mod, store
    x = ideas_mod.add("X", "hook x seven eight", [], "p", "w")
    y = ideas_mod.add("Y", "hook y nine ten", [], "p", "w")
    for i, sc in ((x, 8.0), (y, 9.5)):
        ideas_mod.save_score(i["id"], sc, {})
        ideas_mod.save_conditioning(i["id"], {"refined_hook": "h", "narrative_arc": [], "key_facts": []})
    sh = store.create("Made", "keyframe", {"kind": "idea", "text": "t"}, {})
    sh["beats"] = [{"id": "b1", "name": "n", "sentences": [{"text": "Ek।", "tag": ""}], "shot_ids": []}]
    sh["status"] = "made"
    from shorts import publish
    sh["publish"] = {"title": "A title that is long enough", "description": "d\n\n#Shorts", "hashtags": ["#Shorts"], "tags": ["a"], "for": publish.narration_hash(sh)}
    store.save(sh)
    ideas_mod.set_status(ideas_mod.add("Z", "hook z one two three", [], "p", "w")["id"], "queued", sh["id"])
    q = client.get("/api/shorts/ideas/autopilot").json()["queues"]
    assert [i["id"] for i in q["conditioned"]] == [y["id"], x["id"]], "best score first"
    assert q["queued"] == [], "a finished short is not 'being made'"
    assert q["done"][0]["short_status"] == "made" and q["done"][0]["publish"]["title"].startswith("A title") and q["done"][0]["publish"]["stale"] is False
    assert [i["rank"] for i in q["conditioned"]] == [1, 2] and q["done"][0]["done_at"] > 0
    listed = [i for i in client.get("/api/shorts/ideas").json() if i["status"] == "done"]
    assert listed[0]["publish"]["tags_text"] == "a" and listed[0]["short_status"] == "made"
    assert ideas_mod.get_config()["styles"] == list(ideas_mod.BRIGHT_STYLES), "bright styles are ticked until the person chooses"


def test_the_visual_direction_always_names_an_allowed_style(client):
    from shorts import ideas as ideas_mod
    allowed = ["anime", "realism"]
    assert ideas_mod.direction_with_style("Cinematic realism - deep blues", allowed) == "Cinematic realism - deep blues"
    out = ideas_mod.direction_with_style("Dark noir chiaroscuro", allowed)
    assert out.startswith("anime - bright natural light") and "Dark noir chiaroscuro" in out
    assert ideas_mod.direction_with_style("anything", []) == "anything"


def test_an_empty_search_is_tried_once_more(client, monkeypatch):
    from shorts import discover
    seen = {}

    async def flaky(c, base, key, query):
        seen[query] = seen.get(query, 0) + 1
        return [] if seen[query] == 1 else [{"title": "t " + query, "url": "https://x.test/" + query.replace(" ", "-"), "snippet": "s", "query": query}]

    async def no_tool(*a, **k):
        return {}
    monkeypatch.setattr(discover, "_search", flaky)
    monkeypatch.setattr(discover, "_post_tool", no_tool)
    monkeypatch.setattr(discover, "RETRY_EMPTY_S", 0)
    sigs = asyncio.run(discover.signals({"base_url": "http://gw/v1"}, "k"))
    assert len(sigs) == discover.QUERIES_PER_RUN and all(v == 2 for v in seen.values())


def test_a_finished_short_marks_its_idea_done_and_the_queue_shows_the_order(client):
    from shorts import ideas as ideas_mod, store
    hi = ideas_mod.add("hi", "hook hi one two", [], "p", "w")
    lo = ideas_mod.add("lo", "hook lo one two", [], "p", "w")
    bad = ideas_mod.add("bad", "hook bad one two", [], "p", "w")
    for i, sc in ((hi, 9.0), (lo, 6.0), (bad, 9.9)):
        ideas_mod.save_score(i["id"], sc, {})
        ideas_mod.set_status(i["id"], "approved")
    ideas_mod.bump_cond_fail(bad["id"]); ideas_mod.bump_cond_fail(bad["id"])
    q = ideas_mod.queues(7.0)
    assert [(i["id"], i.get("rank")) for i in q["approved"]] == [(hi["id"], 1), (lo["id"], 2), (bad["id"], None)] and q["approved"][2]["hold"]
    assert ideas_mod.next_to_condition()["id"] == hi["id"], "the screen's #1 is what the autopilot takes"
    assert q["approved"][0]["approved_at"] > 0
    ideas_mod.save_conditioning(lo["id"], {"refined_hook": "h"})
    ideas_mod.save_conditioning(hi["id"], {"refined_hook": "h"})
    c = ideas_mod.queues(7.0)["conditioned"]
    assert c[0]["id"] == hi["id"] and c[0]["rank"] == 1 and not c[0]["hold"]
    assert c[1]["id"] == lo["id"] and "rank" not in c[1] and "under 7" in c[1]["hold"]
    assert c[0]["conditioned_at"] > 0
    sh = store.create("S", "keyframe", {"kind": "idea", "text": "t"}, {})
    ideas_mod.set_status(hi["id"], "queued", sh["id"])
    ideas_mod.set_status(lo["id"], "queued", "sh-gone")
    assert ideas_mod.finish_ready(lambda sid: False) == []
    sh["status"] = "made"
    store.save(sh)
    assert client.get("/api/shorts/ideas/autopilot").status_code == 200
    assert ideas_mod.get(hi["id"])["status"] == "done" and ideas_mod.get(hi["id"])["done_at"] > 0 and ideas_mod.get(hi["id"])["reviewed"] in (0, None), "done needs no review click"
    assert ideas_mod.get(lo["id"])["status"] == "queued", "a deleted short never finishes an idea"
    assert "waiting_review" not in ideas_mod.counts()


def test_the_producer_can_set_the_word_range_and_the_speed_up_limit_per_short():
    short = planned("keyframe")
    base = planner.word_limits(30, 1.0, short)
    assert base == planner.word_limits(30) and timeline.tempo_max(short) == timeline.TEMPO_MAX, "no own numbers: the system's suggestion"
    short["settings"].update({"words_lo": 90, "words_hi": 130})
    lo, hi, a, b = planner.word_limits(30, 1.0, short)
    assert (lo, hi) == (90, 130) and lo <= a <= b <= hi, "the producer's range is the accepted range"
    assert not any("words; it must be" in p for p in planner.narration_problems([{"sentences": [{"text": " ".join(["shabd"] * 110)}]}], None, 30, "en", 1.0, short))
    assert any("words; it must be" in p for p in planner.narration_problems([{"sentences": [{"text": " ".join(["shabd"] * 110)}]}], None, 30, "en", 1.0, {"settings": {}}))
    short["settings"]["tempo_max"] = 1.3
    assert timeline.tempo_max(short) == 1.3
    short["settings"]["tempo_max"] = 9
    assert timeline.tempo_max(short) == 1.6, "never above 1.6"


def test_word_range_and_speed_up_limit_are_saved_checked_and_shown(client):
    sid = client.post("/api/shorts", json={"pipeline": "keyframe", "kind": "idea", "text": "A courier finds a wallet with a lakh rupees."}).json()["id"]
    ok = client.patch(f"/api/shorts/{sid}/settings", json={"words_lo": 90, "words_hi": 120, "tempo_max": 1.3})
    assert ok.status_code == 200
    w = client.get(f"/api/shorts/{sid}").json()["words"]
    assert w["used"]["lo"] == 90 and w["used"]["hi"] == 120 and w["tempo_max"] == 1.3 and w["suggested"]["hi"] > w["suggested"]["lo"]
    assert client.patch(f"/api/shorts/{sid}/settings", json={"words_lo": 130}).status_code == 400, "fewest must be under most"
    assert client.patch(f"/api/shorts/{sid}/settings", json={"tempo_max": 2.5}).status_code == 400
    assert client.patch(f"/api/shorts/{sid}/settings", json={"words_lo": 0, "words_hi": 0, "tempo_max": 0}).status_code == 200
    assert client.get(f"/api/shorts/{sid}").json()["words"]["used"] == client.get(f"/api/shorts/{sid}").json()["words"]["suggested"]


def test_the_ideas_config_keeps_the_word_range_for_autopilot_shorts(client):
    from shorts import api as shorts_api, ideas as ideas_mod
    ideas_mod.save_config({"run": {"words_lo": "90", "words_hi": "125", "tempo_max": "1.3"}})
    st = shorts_api._run_settings(ideas_mod.get_config()["run"])
    assert (st["words_lo"], st["words_hi"], st["tempo_max"]) == (90, 125, 1.3)
    ideas_mod.save_config({"run": {"words_lo": "", "words_hi": "", "tempo_max": ""}})
    st = shorts_api._run_settings(ideas_mod.get_config()["run"])
    assert (st["words_lo"], st["words_hi"], st["tempo_max"]) == (0, 0, 0.0)
