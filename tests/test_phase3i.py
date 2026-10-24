"""Phase 3, batch I: assembly of the draft video with the real ffmpeg (tiny pictures, small sizes, so each build takes a few seconds)."""
import shutil
import wave

import pytest

from story import db
from story2 import imgplan, planner, storyboard
from story3 import graphics, scenes, store, video, voice
from test_phase3f import planned
from test_phase3g import Gateway, run

pytestmark = pytest.mark.skipif(not video.available()["ffmpeg"], reason="ffmpeg is not installed here")

TINY = {"label": "Tiny", "size": (160, 90), "fps": 10, "crf": 35, "preset": "ultrafast", "abr": "32k", "speed": 0.1}


@pytest.fixture(autouse=True)
def tiny(monkeypatch):
    monkeypatch.setitem(video.PROFILES, "tiny", TINY)


def wav(path, seconds, rate=24000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))


def make_voice(plan_id, only=None, approve=True):
    """A finished voice take for each segment, as long as the plan expects (a short one, so tests stay quick), then retimed like the real thing."""
    plan = planner.get_plan(plan_id)
    voice_id = plan["narrator"].get("voice") or "hi_male"
    for seg in plan["segments"]:
        if only and seg["id"] not in only:
            continue
        secs = max(1.0, round(seg["duration_s"] / 10, 1))
        it = store.add(plan_id, "voice", seg["id"], 1, "running", {"text_hash": store.text_hash(seg["annotated"], voice_id)})
        wav(store.media_dir(plan_id, "voice") / f"{seg['id']}-a1.wav", secs)
        store.update(it["id"], status="done", file=f"voice/{seg['id']}-a1.wav", meta={"duration_s": secs})
        if approve:
            store.approve(it["id"])
    voice.apply_timing(plan_id)


def ready(env, monkeypatch, voices=True, pictures=True, approve=True):
    plan_id = planned(env)
    if voices:
        make_voice(plan_id, approve=approve)
    if pictures:
        run(plan_id, Gateway(), monkeypatch)
        if approve:
            scenes.approve_best(plan_id, 0)
    return plan_id


def run_build(plan_id, **kw):
    kw.setdefault("profile", "tiny")
    return video.build(plan_id, **kw)


def test_everything_ready_builds_a_video_as_long_as_the_audio(env, monkeypatch):
    plan_id = ready(env, monkeypatch)
    chk = video.checklist(plan_id)
    assert not chk["blockers"] and not chk["warnings"] and chk["length_gap_s"] < 0.05
    out = run_build(plan_id)
    it = out["item"]
    path = store.path_of(it)
    assert path.is_file() and it["status"] == "done" and it["file"].startswith("video/tiny-a1")
    real = video.probe_seconds(path)
    assert abs(real - chk["audio_s"]) < 0.5 and abs(real - chk["plan_s"]) < 0.5            # the timeline adds up to the audio
    assert it["meta"]["scenes"] == len(storyboard.get_scenes(plan_id)) and not out["placeholders"]
    info = video.media_info(path)["streams"]
    assert {s["codec"] for s in info} == {"h264", "aac"}
    v = next(s for s in info if s["type"] == "video")
    assert (v["width"], v["height"]) == (160, 90)


def test_every_scene_appears_once_and_in_order(env, monkeypatch):
    plan_id = ready(env, monkeypatch)
    it = run_build(plan_id)["item"]
    sc = sorted(storyboard.get_scenes(plan_id), key=lambda x: (x["start_s"], x["seq"]))
    assert len(it["meta"]["moves"]) == len(sc) == it["meta"]["scenes"]
    clips = sorted((store.media_dir(plan_id, "video") / "work" / "clips-tiny").glob("*.mp4"))
    assert [c.name[:3] for c in clips] == [f"{n:03d}" for n in range(len(sc))]


def test_the_same_move_is_never_used_twice_in_a_row_and_cards_hold_still():
    def sc(vt, motion):
        return {"data": {"visual_type": vt, "motion_intent": motion}}
    moves = video.pick_moves([sc("character", "slow push in"), sc("character", "slow push in"), sc("establishing", ""), sc("establishing", ""), sc("data_chart", "push in"),
                              sc("atmospheric", "pull back"), sc("atmospheric", "pull back"), sc("atmospheric", "static hold")])
    assert moves[0] == "zoom_in" and moves[4] == "hold" and moves[5] == "zoom_out" and moves[7] == "hold"
    assert all(a != b for a, b in zip(moves, moves[1:]) if "hold" not in (a, b))
    assert all(m in video.MOVES + ["hold"] for m in moves)
    more = video.pick_moves([sc("character", "")] * 30)
    assert all(a != b for a, b in zip(more, more[1:]))


def test_a_dissolve_is_only_where_the_scene_asks_for_one():
    assert video.wants_dissolve({"data": {"visual_type": "transition", "motion_intent": ""}})
    assert video.wants_dissolve({"data": {"visual_type": "character", "motion_intent": "a slow cross-dissolve into the next place"}})
    assert not video.wants_dissolve({"data": {"visual_type": "character", "motion_intent": "slow push in"}})


def test_missing_pictures_and_voice_stop_the_build_and_are_listed(env, monkeypatch):
    plan_id = ready(env, monkeypatch, voices=False, pictures=False)
    chk = video.checklist(plan_id)
    n = len(storyboard.get_scenes(plan_id))
    assert len([b for b in chk["blockers"] if b["kind"] == "picture"]) == n and any(b["kind"] == "voice" for b in chk["blockers"])
    with pytest.raises(voice.MediaError, match="missing"):
        run_build(plan_id)
    assert not store.items(plan_id, video.KIND)
    st = video.state(plan_id)
    assert not st["ready"] and st["blockers"] and not st["done"]


def test_build_anyway_marks_every_gap_and_still_has_the_right_length(env, monkeypatch):
    plan_id = ready(env, monkeypatch, voices=False, pictures=False)
    make_voice(plan_id, only=[planner.get_plan(plan_id)["segments"][0]["id"]])               # only the first part has a voice
    run(plan_id, Gateway(), monkeypatch, scene_ids=[storyboard.get_scenes(plan_id)[0]["id"]])    # and only the first scene a picture
    out = run_build(plan_id, allow_gaps=True)
    kinds = [p["kind"] for p in out["placeholders"]]
    assert kinds.count("picture") == len(storyboard.get_scenes(plan_id)) - 1 and kinds.count("voice") == len(planner.get_plan(plan_id)["segments"]) - 1
    chk = video.checklist(plan_id)
    assert abs(video.probe_seconds(store.path_of(out["item"])) - chk["plan_s"]) < 0.6
    assert not video.state(plan_id)["done"]                                                      # a video with placeholders is never "done"


def test_unapproved_pictures_and_voice_are_used_but_listed(env, monkeypatch):
    plan_id = ready(env, monkeypatch, approve=False)
    chk = video.checklist(plan_id)
    assert not chk["blockers"] and any(w["text"] == "picture not approved" for w in chk["warnings"]) and any(w["text"] == "voice not approved" for w in chk["warnings"])
    out = run_build(plan_id)
    assert out["item"]["meta"]["warnings"] and store.path_of(out["item"]).is_file()


def test_an_old_picture_does_not_count(env, monkeypatch):
    plan_id = ready(env, monkeypatch)
    sc = storyboard.get_scenes(plan_id)[0]
    d = sc["data"]
    d["subject"] = "something else now"
    db.ex("UPDATE scenes SET data=? WHERE id=?", (db.jdump(d), sc["id"]))
    imgplan.compile_plan(plan_id)
    chk = video.checklist(plan_id)
    assert any(b["kind"] == "picture" and "old" in b["text"] for b in chk["blockers"])


def test_an_approved_graphic_is_used_for_a_scene_that_needs_one(env, monkeypatch):
    plan_id = ready(env, monkeypatch)
    sc = storyboard.get_scenes(plan_id)[0]
    d = sc["data"]
    d["visual_type"] = "data_chart"
    d["facts"] = {"fixed": ["fell 17%"], "creative": []}
    db.ex("UPDATE scenes SET data=? WHERE id=?", (db.jdump(d), sc["id"]))
    monkeypatch.setattr(graphics, "facts_ctx", lambda plan: {"text": "17", "lower": "17", "known": {"17"}, "pub": {"chronology": []}})
    graphics.build(plan_id)
    graphics.approve_all(plan_id, include_fallbacks=True)
    pick = video.visual_choices(plan_id)[sc["id"]]
    assert pick["source"] == "graphic" and not pick["problem"] and pick["path"].parent.name == "graphics"
    assert video.pick_moves([storyboard.get_scene(sc["id"])]) == ["hold"]


def test_captions_follow_the_narration_sentences(env, monkeypatch):
    plan_id = ready(env, monkeypatch)
    ev = video.caption_events(plan_id)
    plan = planner.get_plan(plan_id)
    assert len(ev) == sum(len([s_ for s_ in seg["sentences"] if s_["text"].strip()]) for seg in plan["segments"])
    assert all(a < b for a, b, _t in ev) and all(ev[i][1] <= ev[i + 1][0] + 0.01 for i in range(len(ev) - 1))
    assert abs(ev[-1][1] - video.checklist(plan_id)["audio_s"]) < 0.05
    assert video.ass_time(3725.5) == "1:02:05.50"
    if video.available()["captions"]:
        out = run_build(plan_id, captions=True)
        assert out["item"]["meta"]["captions"] and store.path_of(out["item"]).is_file()
        ass = (store.media_dir(plan_id, "video") / "work" / "captions.ass").read_text(encoding="utf-8")
        assert "Nirmala UI" in ass and ass.count("Dialogue:") == len(ev)


def test_rebuilding_reuses_finished_clips_and_a_change_makes_the_video_old(env, monkeypatch):
    plan_id = ready(env, monkeypatch)
    run_build(plan_id)
    clips = sorted((store.media_dir(plan_id, "video") / "work" / "clips-tiny").glob("*.mp4"))
    stamp = {c.name: c.stat().st_mtime_ns for c in clips}
    again = run_build(plan_id)
    assert {c.name: c.stat().st_mtime_ns for c in clips} == stamp and again["item"]["attempt"] == 2
    st = video.state(plan_id)
    assert [v["current"] for v in st["videos"]] == [True, True]
    scenes.approve(scenes.state(plan_id)["scenes"][0]["candidates"][0]["id"], False)
    run(plan_id, Gateway(), monkeypatch, only_missing=False, scene_ids=[scenes.state(plan_id)["scenes"][0]["id"]])
    scenes.approve(scenes.state(plan_id)["scenes"][0]["candidates"][-1]["id"])
    assert not any(v["current"] for v in video.state(plan_id)["videos"])


def test_unknown_profile_and_missing_tool_are_clear_errors(env, monkeypatch):
    plan_id = ready(env, monkeypatch)
    with pytest.raises(voice.MediaError, match="unknown profile"):
        video.build(plan_id, "huge")
    monkeypatch.setattr(video, "available", lambda: {"ffmpeg": False, "captions": False})
    with pytest.raises(voice.MediaError, match="ffmpeg was not found"):
        video.build(plan_id, "tiny")
    monkeypatch.setattr(video, "available", lambda: {"ffmpeg": True, "captions": False})
    with pytest.raises(voice.MediaError, match="libass"):
        video.build(plan_id, "tiny", captions=True)


def test_a_video_does_not_make_an_approved_plan_look_changed(env, monkeypatch):
    from story2 import editorial
    from test_phase3e import exported
    plan_id = exported(env)
    imgplan.compile_plan(plan_id)
    editorial.approve(plan_id)
    h = editorial.content_hash(planner.get_plan(plan_id))
    make_voice(plan_id)
    run(plan_id, Gateway(), monkeypatch)
    scenes.approve_best(plan_id, 0)
    run_build(plan_id)
    assert editorial.content_hash(planner.get_plan(plan_id)) == h and editorial.approval_state(planner.get_plan(plan_id))["state"] == "approved"


def test_api_round_trip(tmp_path, monkeypatch):
    import config
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    with TestClient(main.app) as c:
        c.post("/login", data={"username": config.APP_USER, "password": config.APP_PASSWORD})
        from story import projects, review
        from fakellm import FakeBackend
        from test_pipeline import make_book, run as run1
        pid = projects.import_text(make_book(3, 8))
        run1(pid, FakeBackend())
        cid = review.list_candidates(pid)[0]["id"]
        review.update_candidate(cid, {"status": "approved"})
        plan = c.post("/api/plans", json={"candidate_id": cid}).json()
        r = c.post(f"/api/media/{plan['id']}/video", json={})
        assert r.status_code == 400 and "missing" in r.json()["detail"] or "scenes" in r.json()["detail"]
        assert c.post(f"/api/media/{plan['id']}/video", json={"profile": "huge"}).status_code == 400
        v = c.get(f"/api/media/{plan['id']}").json()["video"]
        assert v["tools"]["ffmpeg"] and not v["ready"] and not v["done"] and set(v["profiles"]) >= {"draft", "preview"}
