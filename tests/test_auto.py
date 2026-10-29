"""Auto-run: one job that takes every remaining step in order with the default choice at each one."""
import asyncio

import httpx
import pytest

from story import db, settings as settings_mod
from story2 import editorial, export, imgplan, planner, storyboard
from story3 import auto, graphics, refs, scenes, store, video, voice
from test_phase3e import silence
from test_phase3f import planned as _planned


def planned(env, edit=True):
    """A plan with its storyboard. Reference pictures are only part of auto-run when scenes are drawn from them, so most tests choose that."""
    plan_id = _planned(env)
    st = planner.get_plan(plan_id)["settings"]
    db.ex("UPDATE plans SET settings=? WHERE id=?", (db.jdump({**st, "pipeline": "q1"}), plan_id))                # these tests are about the steps of the older chain; the material chain has test_chain_v2
    if edit:
        scenes.set_settings(plan_id, {"mode": "auto"})
    else:
        scenes.set_settings(plan_id, {"mode": "generate", "chosen": True})   # explicit plain: mark chosen so auto-run default setter does not fire
    return plan_id
from test_phase3g import Gateway as ImageGateway
from test_phase3i import TINY

SETTINGS = {"base_url": "http://gw/v1", "model": "chat-model"}


class AllGateway(ImageGateway):
    """Images, edits, the vision check and speech from one fake server."""

    def client(self):
        base = super().client()
        gw = self

        class C(base):
            async def post(self, url, json=None, headers=None, data=None, files=None):
                if url.endswith("/audio/speech"):
                    gw.requests.append({"url": url, "body": json, "files": None, "auth": headers})
                    return httpx.Response(200, content=silence(max(1.0, len(json["input"].split()) / 8.0)))
                return await super().post(url, json=json, headers=headers, data=data, files=files)
        return C


@pytest.fixture
def fast(monkeypatch):
    async def nosleep(_):
        return None
    for mod in (refs, scenes, voice):
        monkeypatch.setattr(mod.asyncio, "sleep", nosleep)
    monkeypatch.setitem(video.PROFILES, "draft", TINY)


def progress_log():
    log = []
    return log, lambda d, t, label="": log.append((d, t, label))


def go(plan_id, monkeypatch, gw=None, **kw):
    gw = gw or AllGateway()
    monkeypatch.setattr(httpx, "AsyncClient", gw.client())
    if isinstance(auto.llm.ChatBackend, type):                       # the thumbnail step asks the model for its words; tests that did not choose a fake get the standard one
        from test_phase2b import P2BFake
        monkeypatch.setattr(auto.llm, "ChatBackend", lambda s, k: P2BFake())
    log, prog = progress_log()
    out = asyncio.run(auto.run(plan_id, prog, {**settings_mod.get(), **SETTINGS}, "k", **kw))
    return out, gw, log


def test_a_planned_storyboard_is_taken_all_the_way_to_a_draft_video(env, monkeypatch, fast):
    plan_id = planned(env)
    st = auto.state(plan_id)
    assert st["next"] == "voicetags" and {"blueprint", "narration", "characters", "storyboard"} <= {s["key"] for s in st["stages"] if s["done"]}
    out, gw, log = go(plan_id, monkeypatch)
    assert out["ran"][0] == "voicetags" and out["ran"][1] == "references" and out["ran"][-1] == "publish"
    assert auto.state(plan_id)["remaining"] == 0 and auto.state(plan_id)["next"] is None
    plan = planner.get_plan(plan_id)
    assert editorial.approval_state(plan)["state"] == "approved" and export.list_exports(plan_id)
    assert refs.state(plan_id)["done"] and scenes.state(plan_id)["done"] and voice.state(plan_id)["approved"] == len(plan["segments"])
    v = video.state(plan_id)
    assert v["done"] and v["videos"][-1]["profile"] == "draft" and store.path_of(store.get(v["videos"][-1]["id"])).is_file()
    assert any("step 1 of" in x[2] or "step 7 of" in x[2] for x in log) and log[-1][2] == "done"


def test_the_first_outcome_is_approved_and_pictures_default_to_plain_qwen(env, monkeypatch, fast):
    plan_id = planned(env)
    out, gw, _ = go(plan_id, monkeypatch)
    assert scenes.settings(planner.get_plan(plan_id))["model"] == "qwen-image-2.1" and scenes.settings(planner.get_plan(plan_id))["mode"] == "generate"
    assert any("drawn plain with Qwen" in n for n in out["notes"])                                      # said as it is: no reference sheets, so no promise of them
    assert {r["body"]["model"] for r in gw.count("/images/generations")} == {"qwen-image-2.1"}
    assert all(r["approved"] for r in scenes.state(plan_id)["scenes"])
    assert all(r["approved"] for r in refs.state(plan_id)["assets"] if not r["skipped"])
    total_pics = len(gw.count("/images/generations")) + len(gw.count("/images/edits"))
    assert total_pics >= len(storyboard.get_scenes(plan_id))                                           # one picture per scene; edit mode uses /edits when refs exist


def test_a_way_chosen_by_hand_is_respected(env, monkeypatch, fast):
    plan_id = planned(env)
    scenes.choose(plan_id, "flux2-klein-9b", "generate")
    out, gw, _ = go(plan_id, monkeypatch, only=["references", "prompts", "approve", "export", "voice", "pictures"])
    assert not any("Qwen" in n for n in out["notes"])
    scene_calls = [r for r in gw.count("/images/generations") if r["body"]["size"].startswith("1344")]
    assert {r["body"]["model"] for r in scene_calls if r["body"]["model"] != "qwen-image-2.1"} == {"flux2-klein-9b"}


def test_finished_steps_are_skipped_and_a_second_run_does_nothing(env, monkeypatch, fast):
    plan_id = planned(env)
    go(plan_id, monkeypatch)
    out, gw, _ = go(plan_id, monkeypatch)
    assert out["ran"] == [] and not gw.requests


def test_it_stops_at_a_signoff_blocker_and_keeps_what_was_done(env, monkeypatch, fast):
    plan_id = planned(env)
    monkeypatch.setattr(editorial, "signoff", lambda pid: {"ok": False, "blockers": [{"text": "2 error(s) must be fixed: coverage."}], "warnings": [], "scores": {}, "content_hash": ""})
    with pytest.raises(auto.AutoStop, match="stopped at “Check, review and approve the plan”.*2 error"):
        go(plan_id, monkeypatch)
    assert refs.state(plan_id)["done"] and auto.state(plan_id)["next"] in ("repeats", "approve")      # references and prompts are kept; the next run re-checks and resumes at the blocker
    assert not export.list_exports(plan_id)


def test_a_failing_model_names_the_step_and_keeps_the_rest(env, monkeypatch, fast):
    plan_id = planned(env)
    gw = AllGateway(fail_for=set(range(1, 60)))                                                   # every image request fails
    with pytest.raises(voice.MediaError, match="stopped at"):
        go(plan_id, monkeypatch, gw=gw)
    assert auto.state(plan_id)["next"] in ("references", "pictures")


def test_only_the_named_steps_run(env, monkeypatch, fast):
    plan_id = planned(env)
    out, gw, _ = go(plan_id, monkeypatch, only=["prompts"])
    assert out["ran"] in ([], ["prompts"]) and not gw.requests


def test_it_can_be_stopped_between_requests(env, monkeypatch, fast):
    plan_id = planned(env)
    gw = AllGateway()
    monkeypatch.setattr(httpx, "AsyncClient", gw.client())

    async def main():
        t = asyncio.create_task(auto.run(plan_id, lambda *a: None, SETTINGS, "k"))
        await asyncio.sleep(0.05)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t
    asyncio.run(main())
    assert auto.state(plan_id)["remaining"] > 0


def test_state_in_the_media_summary_and_the_api(tmp_path, monkeypatch):
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
        a = c.get(f"/api/media/{plan['id']}").json()["auto"]
        assert a["next"] == "material" and a["remaining"] == len(auto.STAGES) - sum(1 for s in a["stages"] if s["done"]) and [s["key"] for s in a["stages"]] == [k for k, _ in auto.STAGES]
        assert c.post(f"/api/media/{plan['id']}/auto", json={"only": ["nonsense"]}).status_code == 400


def test_from_a_brand_new_plan_every_step_runs_including_the_model_steps(env, monkeypatch, fast):
    from test_phase2a import approved_story
    from test_phase2b import P2BFake
    pid, cid = approved_story(env)
    plan_id = planner.create_plan(cid, minutes=2)["id"]
    scenes.set_settings(plan_id, {"mode": "auto"})
    assert auto.state(plan_id)["next"] == "material"                                       # a plan made now starts with the story material
    db.ex("UPDATE plans SET settings=? WHERE id=?", (db.jdump({**planner.get_plan(plan_id)["settings"], "pipeline": "q1"}), plan_id))              # this test walks the older chain; test_chain_v2 walks the new one
    assert auto.state(plan_id)["next"] == "blueprint"
    be = P2BFake()
    monkeypatch.setattr(auto.llm, "ChatBackend", lambda s, k: be)
    pl = planner.get_plan(plan_id)
    db.ex("UPDATE plans SET settings=? WHERE id=?", (db.jdump({**pl["settings"], "cast_indian": True, "gates": {"mode": "warn"}}), plan_id))                # the editor chose the cast first; the fake narration has one 43-second scene
    out, gw, log = go(plan_id, monkeypatch)
    assert out["ran"][:6] == ["blueprint", "narration", "characters", "storyboard", "voicetags", "references"] and out["ran"][-1] == "publish"
    assert auto.state(plan_id)["remaining"] == 0
    plan = planner.get_plan(plan_id)
    assert plan["blueprint"] and plan["segments"] and storyboard.get_scenes(plan_id) and editorial.approval_state(plan)["state"] == "approved"
    assert [c["task"] for c in be.calls if c["task"] == "p2_registry"] and video.state(plan_id)["done"]


def test_a_picture_with_a_hard_problem_gets_more_tries_before_the_best_is_taken(env, monkeypatch, fast):
    plan_id = planned(env)
    n = len(refs.targets(plan_id))
    bad = {"text_visible": True, "text_read": "XD", "defects": ["letters on the tape"]}
    looks = [bad] + [{}] * (n - 1)                                  # the first reference picture shows writing; everything else is fine
    gw = AllGateway(looks=looks)
    out, gw, _ = go(plan_id, monkeypatch, gw=gw, only=["references"])
    gens = gw.count("/images/generations")
    assert len(gens) == n + 2                                       # the weak item was drawn twice more
    rows = refs.state(plan_id)["assets"]
    assert all(r["approved"] for r in rows)
    first = rows[0]
    chosen = next(c for c in first["candidates"] if c["id"] == first["approved"])
    assert not chosen["score"]["hard"] and chosen["attempt"] > 1    # a clean retry won over the flawed first outcome


def test_weak_means_hard_problem_low_score_or_nothing_yet():
    ok = {"id": "a", "status": "done", "current": True, "score": {"hard": False, "total": 80}}
    bad = {"id": "b", "status": "done", "current": True, "score": {"hard": True, "total": 40}}
    low = {"id": "c", "status": "done", "current": True, "score": {"hard": False, "total": 45}}
    assert not auto._weak([ok], "a") and auto._weak([bad], "b") and auto._weak([low], "c") and auto._weak([], None)
    assert auto._weak([ok, bad], "a", approved="b")


def test_reference_pictures_are_skipped_when_scenes_are_drawn_plain(env, monkeypatch, fast):
    plan_id = planned(env, edit=False)                              # plain drawing never sends a reference picture, so none is made
    assert auto.done(plan_id, "references") and auto.state(plan_id)["next"] in ("voicetags", "prompts", "repeats")
    out, gw, _ = go(plan_id, monkeypatch)
    assert "references" not in out["ran"] and not [r for r in gw.requests if r["body"] and "Character model sheet" in str(r["body"].get("prompt", ""))]
    assert auto.state(plan_id)["remaining"] == 0


def test_the_thumbnail_is_made_last_from_the_plan_and_approved(env, monkeypatch, fast):
    from story3 import thumbnail
    plan_id = planned(env)
    assert auto.STAGES[-1][0] == "publish" and auto.state(plan_id)["stages"][-1]["done"] is False
    out, gw, _ = go(plan_id, monkeypatch)
    assert out["ran"][-4:] == ["video", "title", "thumbnail", "publish"] and auto.state(plan_id)["remaining"] == 0
    th = thumbnail.state(plan_id)
    assert th["done"] and th["item"]["approved"] and th["item"]["text"] == "Who removed the handle?"
    path = store.path_of(store.get(th["item"]["id"]))
    from PIL import Image
    assert Image.open(path).size == (1280, 720)                                                     # the size YouTube asks for
    sent = [r for r in gw.requests if r["url"].endswith("/images/generations") and "Composite image" in str(r["body"].get("prompt", ""))]
    assert sent and "close-up" in sent[0]["body"]["prompt"] and "no text" in sent[0]["body"]["prompt"].lower()                   # a composite thumbnail; the headline is written in code, not drawn
    assert 'the words "' not in sent[0]["body"]["prompt"]
    assert thumbnail._fallback_prompt(thumbnail.Option(text="Why now?", image="a street"), None).count('"Why now?"') == 1                # the older way still asks the model for the words
    import pytest
    with pytest.raises(ValueError):
        thumbnail.Option(text="One")                                                                # too short
    with pytest.raises(ValueError):
        thumbnail.Option(text="काहानी क्या थी")                                                       # English letters only


def test_auto_run_stops_at_the_characters_until_the_cast_is_chosen(env, monkeypatch, fast):
    from test_phase2a import approved_story
    from test_phase2b import P2BFake
    pid, cid = approved_story(env)
    plan_id = planner.create_plan(cid, minutes=2)["id"]
    db.ex("UPDATE plans SET settings=? WHERE id=?", (db.jdump({**planner.get_plan(plan_id)["settings"], "pipeline": "q1"}), plan_id))
    be = P2BFake()
    monkeypatch.setattr(auto.llm, "ChatBackend", lambda s, k: be)
    with pytest.raises(auto.AutoStop, match="choose who appears in the pictures"):
        go(plan_id, monkeypatch)
    assert planner.get_plan(plan_id)["segments"] and not storyboard.get_assets(plan_id)               # blueprint and narration were kept, no characters made


def test_edit_mode_chosen_by_hand_makes_the_sheets_first_instead_of_drawing_plain_in_silence(env, monkeypatch, fast):
    plan_id = planned(env)
    scenes.choose(plan_id, "qwen-image-2.1", "edit")
    out, gw, _ = go(plan_id, monkeypatch, only=["prompts", "approve", "export", "voice", "pictures"])
    assert refs.state(plan_id)["done"] and any(r["approved"] for r in refs.state(plan_id)["assets"])
    assert scenes.state(plan_id)["done"] and not any("could not be made" in n for n in out["notes"])
