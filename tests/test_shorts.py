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
    real = {b["id"]: 8.0 for b in short["beats"]}                                # five beats of eight seconds: too long to fit under 30 even at x1.12
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
    assert short["beats"][0]["sentences"][0]["tag"] == "curious"                  # the beat's voice feeling is on its first sentence
    assert planner.narration_problems(short["beats"]) == []
    chk = checks.run(short)
    assert chk["ok"], chk["issues"]


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
    assert planner.word_limits(30) == (52, 86, 62, 74) and planner.beat_range(30) == (4, 6)
    lo, hi, ask_lo, ask_hi = planner.word_limits(10)
    assert (lo, hi) == (17, 25) and lo <= ask_lo <= ask_hi < hi and planner.beat_range(10) == (2, 3)
    fat = [{"sentences": [{"text": " ".join(["shabd"] * 58)}]}]                       # a 30-second narration is far too long for 10 seconds
    assert any("17 and 25" in p for p in planner.narration_problems(fat, None, 10))
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
    assert run(clips.make_clips(sid, s=S, key="k"))["skipped"], "clips wait for the keyframes"
    kf = run(clips.make_keyframes(sid, s=S, key="k"))
    n = len(store.get(sid)["shots"])
    assert kf["made"] == n and not kf["failed"]
    t2v = [r for r in gw.requests if r["model"] == models.T2V]
    assert len(t2v) == n - 1 and all(r["num_frames"] == 5 and r["speed_lora"] is False for r in t2v), "the user's own picture needs no request"
    res = run(clips.make_clips(sid, s=S, key="k"))
    assert res["made"] == n
    i2v = [r for r in gw.requests if r["model"] == models.I2V]
    assert len(i2v) == n and all(r["speed_lora"] is False and r["image"].startswith("data:image/jpeg") and (r["num_frames"] - 1) % 4 == 0 for r in i2v)
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
    assert run(clips.make_clips(sid, s=S, key="k"))["skipped"], "clips wait for the start pictures"
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
    assert len(st["beats"]) == 5 and st["checks"]["ok"] and st["auto"]["next"] == "voice"
    assert st["estimate_s"] > 0 and st["timeline"]["total_s"] == pytest.approx(30.0)
    shot = st["shots"][0]["id"]
    r = client.patch(f"/api/shorts/{sid}/shots/{shot}", json={"prompt": "A new prompt about a wallet.", "character": True})
    assert r.json()["shots"][0]["prompt"] == "A new prompt about a wallet."
    r = client.patch(f"/api/shorts/{sid}/narration", json={"beats": [{"id": "b1", "sentences": ["सड़क पर एक वॉलेट था।", "अंदर क्या था?"], "tag": "whispers"}]})
    assert r.json()["beats"][0]["sentences"][0]["tag"] == "whispers"
    assert client.patch(f"/api/shorts/{sid}/settings", json={"image_mode": "nonsense"}).status_code == 400
    assert client.patch(f"/api/shorts/{sid}/settings", json={"voice": {"engine": "veena-tts", "voice": "agastya"}}).json()["settings"]["voice"]["engine"] == "veena-tts"
    assert client.patch(f"/api/shorts/{sid}/settings", json={"size": "704x1280"}).json()["settings"]["size"] == "480x832", "only the 5B pipeline has the sharper size"
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
