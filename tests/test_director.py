"""The Director (shorts/director.py): fixes objective defects in drawn pictures one trial at a time, keeps a fix only when the defect is gone, otherwise puts the old picture back.
A defect is made with the review fake: the model "reads text" on a picture until the fake is told it came out clean."""
import asyncio
import copy

import pytest
from fastapi.testclient import TestClient

import config
from shorts_fakes import FakeChat, VideoGateway, fake_speak_all
from story import settings as settings_mod
from story3 import store as media, voice as voice3

from shorts import auto, clips, director, planner, review, store

S = {**settings_mod.DEFAULTS, "base_url": "http://gw/v1", "retry_backoff_s": 0}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def gw(env, monkeypatch):
    g = VideoGateway(env).install(monkeypatch)
    monkeypatch.setattr(voice3, "_speak_all", fake_speak_all)
    return g


def drawn(gw, **settings):
    s = store.create("T", "keyframe", {"kind": "idea", "text": "a courier finds a wallet", "candidate_id": "", "facts": ""}, settings)
    short = run(planner.make_plan(s["id"], FakeChat(), S))
    run(clips.make_keyframes(short["id"], s=S, key="k"))
    return store.get(short["id"])


class Dirty:
    """A review fake: while `on`, the model reads text on the shots in `bad`; the Director's trial pictures are described with the same answer unless `on` is switched off."""
    def __init__(self, bad=("s2",)):
        self.on, self.bad = True, set(bad)

    def __call__(self, ids, n):
        return {i: {"style": "photograph", **({"readable_text": "SALE 50%"} if self.on and i in self.bad else {})} for i in ids}     # the test short is photographic: a clean picture is a photograph


def reviewed(short, dirty):
    chat = FakeChat(review=True, stills=True, review_fn=dirty)
    run(review.run(short["id"], chat, S))
    return store.get(short["id"]), chat


def keyframes(short, sid):
    return [i for i in media.items(short["id"], store.KEY, sid)]


# ── what it would fix, and what it never touches ─────────────────────────────────────────

def test_the_mode_comes_from_the_setting_and_an_old_short_is_off(gw):
    assert director.mode(drawn(gw)) == "shadow", "a new short starts in shadow"
    assert director.mode(drawn(gw, director="defects")) == "defects"
    old = drawn(gw)
    del old["settings"]["director"]
    assert director.mode(old) == "off" and director.report(old)["ready"] is False


def test_the_actions_name_the_defect_and_only_objective_defects_are_listed(gw):
    short, _ = reviewed(drawn(gw), Dirty(("s2",)))
    acts = director.actions(short)
    assert [a["shot"] for a in acts] == ["s2"] and acts[0]["kinds"] == ["text_in_picture"] and not acts[0]["skip"]
    assert "no readable text" in acts[0]["note"] and "SALE" in acts[0]["defects"][0]
    clean, _ = reviewed(drawn(gw), Dirty(()))
    assert director.actions(clean) == [], "a short with no defect has nothing to fix, however low its engagement score"


def test_a_picture_of_the_persons_own_an_approved_picture_and_a_made_clip_are_never_touched(gw):
    short, _ = reviewed(drawn(gw), Dirty(("s1", "s2", "s3")))
    media.approve(clips.chosen_keyframe(short, short["shots"][1])["id"])
    short["shots"][2]["avatar"] = True
    store.save(short)
    short = store.get(short["id"])
    why = {a["shot"]: a["skip"] for a in director.actions(short)}
    assert why["s1"] == "" and "approved" in why["s2"] and "avatar" in why["s3"]


def test_shadow_writes_down_what_it_would_fix_and_changes_nothing(gw):
    short, chat = reviewed(drawn(gw), Dirty(("s2",)))
    before = copy.deepcopy(short["shots"])
    pics = {sh["id"]: [i["id"] for i in keyframes(short, sh["id"])] for sh in short["shots"]}
    calls = len(chat.calls)
    rep = run(director.run(short["id"], chat, S, "k"))
    after = store.get(short["id"])
    assert rep["mode"] == "shadow" and [a["shot"] for a in rep["planned"]] == ["s2"] and rep["log"] == []
    assert after["shots"] == before and len(chat.calls) == calls, "shadow draws nothing and asks the model nothing"
    assert pics == {sh["id"]: [i["id"] for i in keyframes(after, sh["id"])] for sh in after["shots"]}
    assert director.current(after)


# ── trials: keep or put the old picture back ─────────────────────────────────────────────

def test_a_fix_that_removes_the_defect_is_kept(gw):
    dirty = Dirty(("s2",))
    short, chat = reviewed(drawn(gw, director="defects"), dirty)
    old = clips.chosen_keyframe(short, short["shots"][1])["id"]
    dirty.on = False                                  # the redrawn picture comes out clean
    rep = run(director.run(short["id"], chat, S, "k"))
    after = store.get(short["id"])
    assert [e["result"] for e in rep["log"]] == ["kept"] and rep["before"] == 1 and rep["after"] == 0
    assert clips.chosen_keyframe(after, after["shots"][1])["id"] != old, "the new picture is the current one"
    assert not director.actions(after) and director.current(after)


def test_a_fix_that_does_not_remove_the_defect_puts_the_old_picture_back(gw):
    dirty = Dirty(("s2",))
    short, chat = reviewed(drawn(gw, director="defects"), dirty)
    old = clips.chosen_keyframe(short, short["shots"][1])["id"]
    old_shot = {k: copy.deepcopy(short["shots"][1].get(k)) for k in director.FIELDS if k in short["shots"][1]}
    rep = run(director.run(short["id"], chat, S, "k"))               # the defect stays
    after = store.get(short["id"])
    assert [e["result"] for e in rep["log"]] == ["reverted"] and "text_in_picture" in rep["log"][0]["why"]
    assert {k: after["shots"][1].get(k) for k in old_shot} == old_shot, "the old prompt is back"
    assert clips.chosen_keyframe(after, after["shots"][1])["id"] == old, "so the old picture is current again"
    trial = [i for i in keyframes(after, "s2") if i["id"] != old]
    assert trial and all(i["status"] == "failed" and "set aside by the Director" in str(i["meta"]) for i in trial), "the trial picture stays as a failed attempt that says why"
    assert after["director"]["failed"] == {"s2": 1}


def test_a_shot_that_failed_two_trials_is_left_for_a_person(gw):
    short, chat = reviewed(drawn(gw, director="defects"), Dirty(("s2",)))
    run(director.run(short["id"], chat, S, "k"))
    run(director.run(short["id"], chat, S, "k"))
    after = store.get(short["id"])
    assert after["director"]["failed"] == {"s2": 2}
    act = director.actions(after)[0]
    assert "failed two trials" in act["skip"]
    assert len(run(director.run(short["id"], chat, S, "k"))["log"]) == 2, "no third trial"


def test_a_trial_that_brings_a_new_defect_is_set_aside_too(gw):
    dirty = Dirty(("s2",))
    short, chat = reviewed(drawn(gw, director="defects"), dirty)
    dirty.on = False
    chat.review_overrides = {"s2": {"place": "none", "background": "blank"}}   # the text is gone but the background is empty
    rep = run(director.run(short["id"], chat, S, "k"))
    assert rep["log"][0]["result"] == "reverted" and "new: blank_background" in rep["log"][0]["why"]


def test_a_failure_in_a_trial_is_logged_and_never_raised(gw, monkeypatch):
    short, chat = reviewed(drawn(gw, director="defects"), Dirty(("s2",)))

    async def boom(*a, **k):
        raise RuntimeError("the gateway is busy")
    monkeypatch.setattr(clips, "make_keyframes", boom)
    rep = run(director.run(short["id"], chat, S, "k"))
    assert rep["log"][0]["result"] == "failed" and "busy" in rep["log"][0]["why"]


def test_at_most_a_third_of_the_shots_are_tried_per_round_and_the_budget_stops_it(gw):
    short, chat = reviewed(drawn(gw, director="defects"), Dirty(tuple(f"s{i}" for i in range(1, 30))))
    n = len(short["shots"])
    rep = run(director.run(short["id"], chat, S, "k"))
    assert len([e for e in rep["log"] if e["round"] == 1]) <= max(1, -(-3 * n // 10))
    short2, chat2 = reviewed(drawn(gw, director="defects"), Dirty(("s1", "s2")))
    rep2 = run(director.run(short2["id"], chat2, {**S, "director_budget_s": -1}, "k"))
    assert rep2["log"] == [], "no time left: nothing is tried"


def test_the_two_rounds_stop_when_a_round_fixes_nothing(gw):
    short, chat = reviewed(drawn(gw, director="defects"), Dirty(("s2",)))
    rep = run(director.run(short["id"], chat, S, "k"))
    assert rep["rounds"] == 1 and rep["after"] == rep["before"] == 1


def test_the_hook_floor_marks_the_short_as_needing_a_look(gw):
    short, chat = reviewed(drawn(gw, director="defects"), Dirty(()))
    short["review"]["floors"] = [{"floor": "hook", "text": "the first 3 seconds are weak", "shots": ["s1"]}]
    store.save(short)
    run(director.run(short["id"], chat, S, "k"))
    assert [f["floor"] for f in store.get(short["id"])["needs_look"]["floors"]] == ["hook"]
    short = store.get(short["id"])
    short["review"]["floors"] = []
    store.save(short)
    run(director.run(short["id"], chat, S, "k", ""))
    assert "needs_look" not in store.get(short["id"]), "the mark goes when the floor is fine again"


# ── auto-run ──────────────────────────────────────────────────────────────────────────────

def ids_of(short):
    return [x["id"] for x in auto.steps(short)]


def test_the_director_step_follows_the_review_and_comes_before_the_look(gw):
    short = drawn(gw)
    assert "director" not in ids_of(short), "nothing to check before the review"
    short, _ = reviewed(short, Dirty(()))
    ids = ids_of(short)
    assert ids.index("scenes") < ids.index("director") < ids.index("review")
    off = copy.deepcopy(short)
    off["settings"]["director"] = "off"
    assert "director" not in ids_of(off)


def test_auto_run_in_shadow_mode_changes_no_picture(gw, monkeypatch):
    monkeypatch.setattr(auto.svoice, "missing", lambda s: False)
    short = drawn(gw)
    before = {sh["id"]: clips.chosen_keyframe(short, sh)["id"] for sh in short["shots"]}
    out = run(auto.run(short["id"], FakeChat(review=True, review_fn=Dirty(("s2",))), S, lambda *a, **k: None))
    after = store.get(short["id"])
    assert "director shadow (1 it would fix)" in out, out
    assert before == {sh["id"]: clips.chosen_keyframe(after, sh)["id"] for sh in after["shots"]}


def test_auto_run_in_defects_mode_stops_for_a_look_when_a_floor_fails(gw, monkeypatch):
    monkeypatch.setattr(auto.svoice, "missing", lambda s: False)
    short = drawn(gw, director="defects", review_keyframes=False)
    orig = review.floors

    def weak(*a, **k):
        return [{"floor": "hook", "text": "the first 3 seconds are weak", "shots": ["s1"]}]
    monkeypatch.setattr(review, "floors", weak)
    out = run(auto.run(short["id"], FakeChat(review=True, stills=True), S, lambda *a, **k: None))
    assert "Needs your look before the clips" in out and "first 3 seconds" in out, out
    monkeypatch.setattr(review, "floors", orig)


def test_with_two_other_shorts_already_waiting_the_autopilot_goes_on(gw, monkeypatch):
    monkeypatch.setattr(auto.svoice, "missing", lambda s: False)
    for _ in range(2):
        other = drawn(gw)
        other["needs_look"] = {"floors": [{"floor": "hook", "text": "x", "shots": ["s1"]}], "at": 1}
        store.save(other)
    short = drawn(gw, director="defects")                    # the run then stops at the usual "look at the start pictures", and says why it did not stop earlier
    monkeypatch.setattr(review, "floors", lambda *a, **k: [{"floor": "hook", "text": "weak", "shots": ["s1"]}])
    out = run(auto.run(short["id"], FakeChat(review=True, stills=True), S, lambda *a, **k: None))
    assert "Needs your look before the clips" not in out and "two others are waiting" in out, out


def test_a_failing_director_never_stops_auto_run(gw, monkeypatch):
    monkeypatch.setattr(auto.svoice, "missing", lambda s: False)

    async def boom(*a, **k):
        raise RuntimeError("no model")
    monkeypatch.setattr(director, "run", boom)
    short = drawn(gw)
    out = run(auto.run(short["id"], FakeChat(review=True), S, lambda *a, **k: None))
    assert "director skipped" in out


# ── API and the Ideas config ──────────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    import main
    from shorts import api as shorts_api
    g = VideoGateway(tmp_path).install(monkeypatch)
    monkeypatch.setattr(voice3, "_speak_all", fake_speak_all)
    monkeypatch.setattr(shorts_api, "_backend", lambda: ({**settings_mod.get(), "retry_backoff_s": 0}, FakeChat(review=True, stills=True, review_fn=Dirty(("s2",)))))
    with TestClient(main.app) as c:
        c.post("/login", data={"username": config.APP_USER, "password": config.APP_PASSWORD})
        yield c


def wait_job(c, sid, timeout=30):
    import time
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = c.get(f"/api/shorts/{sid}/job").json()
        if j.get("state") in ("done", "error", "cancelled"):
            return j
        time.sleep(0.05)
    raise AssertionError("the job did not finish")


def test_the_api_runs_shadow_and_shows_the_state(client, gw):
    short = drawn(gw)
    sid = short["id"]
    st = client.get(f"/api/shorts/{sid}").json()["director"]
    assert st["mode"] == "shadow" and st["ready"] is True and st["at"] is None
    assert client.post(f"/api/shorts/{sid}/director", json={"mode": "shadow"}).status_code in (200, 202)
    job = wait_job(client, sid)
    assert job["state"] == "done" and "nothing changed" in str(job), job
    after = client.get(f"/api/shorts/{sid}").json()["director"]
    assert [a["shot"] for a in after["planned"]] == ["s2"] and after["current"] is True


def test_the_api_refuses_a_bad_mode_and_a_short_without_pictures_and_saves_the_setting(client, gw):
    s = store.create("T", "keyframe", {"kind": "idea", "text": "a courier finds a wallet", "candidate_id": "", "facts": ""}, {})
    short = run(planner.make_plan(s["id"], FakeChat(), S))
    assert client.post(f"/api/shorts/{short['id']}/director", json={"mode": "shadow"}).status_code == 400, "no pictures yet"
    assert client.post(f"/api/shorts/{short['id']}/director", json={"mode": "bogus"}).status_code == 400
    assert client.patch(f"/api/shorts/{short['id']}/settings", json={"director": "bogus"}).status_code == 400
    assert client.patch(f"/api/shorts/{short['id']}/settings", json={"director": "defects"}).status_code == 200
    assert store.get(short["id"])["settings"]["director"] == "defects"


def test_the_api_fixes_the_defect_in_defects_mode(client, gw):
    short = drawn(gw)
    sid = short["id"]
    assert client.post(f"/api/shorts/{sid}/director", json={"mode": "defects"}).status_code in (200, 202)
    job = wait_job(client, sid)
    assert job["state"] == "done" and "Director:" in str(job), job
    rep = client.get(f"/api/shorts/{sid}").json()["director"]
    assert rep["log"] and rep["log"][0]["shot"] == "s2"


def test_the_ideas_config_carries_the_director_setting(client):
    cfg = client.get("/api/shorts/ideas/config").json()
    assert cfg["run"]["director"] == "shadow", "the autopilot's shorts start in shadow"
    assert client.put("/api/shorts/ideas/config", json={"run": {"director": "defects"}}).status_code == 200
    assert client.get("/api/shorts/ideas/config").json()["run"]["director"] == "defects"
    client.put("/api/shorts/ideas/config", json={"run": {"director": "bogus"}})
    assert client.get("/api/shorts/ideas/config").json()["run"]["director"] == "shadow"
