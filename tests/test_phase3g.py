"""Phase 3, batch G: scene pictures (plain generation, edit mode with reference sheets, the trial, scoring, approval)."""
import asyncio
import json as jsonlib

import httpx
import pytest

from story import db
from story2 import imgplan, planner, storyboard
from story3 import refs, refscore, scenes, store, voice
from test_phase3f import SETTINGS, planned, png


class Gateway:
    """Stands in for the model server: generations (JSON), edits (multipart) and the vision check."""

    def __init__(self, fail_for=(), looks=None, vision_down=False):
        self.requests, self.fail_for, self.vision_down = [], set(fail_for), vision_down
        self.looks = list(looks or [])

    def count(self, suffix):
        return [r for r in self.requests if r["url"].endswith(suffix)]

    def client(self):
        gw = self

        class C:
            def __init__(self, *a, **k): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False

            async def post(self, url, json=None, headers=None, data=None, files=None):
                gw.requests.append({"url": url, "body": json or data, "files": files, "auth": headers})
                if url.endswith("/chat/completions"):
                    if gw.vision_down:
                        return httpx.Response(502, text="model not loaded")
                    ans = gw.looks.pop(0) if gw.looks else {}
                    good = {k: 8 for k, _ in refscore.SCENE_DIMS} | {"text_visible": False, "text_read": "", "extras": [], "defects": []}
                    return httpx.Response(200, json={"choices": [{"message": {"content": jsonlib.dumps(good | ans)}}]})
                if len(gw.count("/images/generations") + gw.count("/images/edits")) in gw.fail_for:
                    return httpx.Response(502, text="image engine error")
                body = json or data
                w, h = (int(v) for v in body["size"].split("x"))
                return httpx.Response(200, json={"data": [{"b64_json": png(w // 16, h // 16), "seed": int(body.get("seed", 0)), "width": w, "height": h}]})
        return C


@pytest.fixture
def fast(monkeypatch):
    async def nosleep(_):
        return None
    monkeypatch.setattr(scenes.asyncio, "sleep", nosleep)


def ready(env, with_refs=False):
    plan_id = planned(env)
    if with_refs:
        approve_all_references(plan_id)
    imgplan.compile_plan(plan_id)
    return plan_id


def approve_all_references(plan_id):
    class G(refs.httpx.AsyncClient if False else object):
        pass
    from test_phase3f import Gateway as RefGateway
    refs.httpx.AsyncClient = RefGateway().client()
    asyncio.run(refs.generate(plan_id, s=SETTINGS, key="k", candidates=1, score=False))
    refs.approve_best(plan_id, min_score=0) if refs.state(plan_id)["unscored"] == 0 else None
    for r in refs.state(plan_id)["assets"]:
        if not r["approved"]:
            refs.approve(r["candidates"][0]["id"])


def run(plan_id, gw, monkeypatch, **kw):
    monkeypatch.setattr(scenes.httpx, "AsyncClient", gw.client())
    monkeypatch.setattr(scenes.refscore.httpx, "AsyncClient", gw.client())
    return asyncio.run(scenes.generate(plan_id, s=SETTINGS, key="k", **kw))


@pytest.fixture(autouse=True)
def restore_httpx():
    orig = refs.httpx.AsyncClient
    yield
    refs.httpx.AsyncClient = orig


def test_every_scene_gets_one_plain_request_from_its_compiled_prompt(env, monkeypatch, fast):
    plan_id = ready(env)
    gw = Gateway()
    out = run(plan_id, gw, monkeypatch)
    sc = storyboard.get_scenes(plan_id)
    gens = gw.count("/images/generations")
    assert out["made"] == len(gens) == len(sc) and not out["failed"] and not gw.count("/images/edits")
    first = gens[0]
    assert first["url"] == "http://gw/v1/images/generations" and first["auth"]["Authorization"] == "Bearer k"
    w, h = (int(v) for v in first["body"]["size"].split("x"))
    assert (w, h) == (1344, 768) or (w % 16 == 0 and h % 16 == 0 and w * h <= 2359296 and abs(w / h - 16 / 9) < 0.02)
    prompts = {r["body"]["prompt"] for r in gens}
    scene0 = sorted(sc, key=lambda x: (x["start_s"], x["seq"]))[0]
    assert scene0["data"]["prompts"]["qwen"]["prompt"] in prompts
    items = store.items(plan_id, scenes.KIND)
    assert all(store.path_of(i).is_file() and i["meta"]["source_hash"] and i["file"].startswith("scenes/") for i in items)


def test_requests_are_grouped_by_model_to_limit_swaps(env, monkeypatch, fast):
    plan_id = ready(env)
    sc = storyboard.get_scenes(plan_id)
    for n, s_ in enumerate(sorted(sc, key=lambda x: x["start_s"])):
        d = s_["data"]
        d["model"] = "flux2-klein-9b" if n % 2 == 0 else "qwen-image-2.1"
        db.ex("UPDATE scenes SET data=? WHERE id=?", (db.jdump(d), s_["id"]))
    gw = Gateway()
    run(plan_id, gw, monkeypatch, score=False)
    models = [r["body"]["model"] for r in gw.count("/images/generations")]
    assert len(set(models)) == 2 and sum(1 for a, b in zip(models, models[1:]) if a != b) == 1
    assert [r for r in gw.count("/images/generations") if r["body"]["model"] == "flux2-klein-9b"][0]["body"].get("negative_prompt")


def test_prompts_must_be_written_first(env, monkeypatch, fast):
    plan_id = planned(env)
    db.ex("UPDATE scenes SET data=json_remove(data,'$.prompts') WHERE plan_id=?", (plan_id,))
    with pytest.raises(voice.MediaError, match="image prompts"):
        run(plan_id, Gateway(), monkeypatch)


def test_edit_mode_sends_the_reference_sheets_in_order_as_multipart(env, monkeypatch, fast):
    plan_id = ready(env, with_refs=True)
    gw = Gateway()
    run(plan_id, gw, monkeypatch, mode="edit", score=False)
    edits = gw.count("/images/edits")
    assert edits and all(len(r["files"]) <= 3 and all(f[0] == "image" for f in r["files"]) for r in edits)
    one = edits[0]
    sc = next(s_ for s_ in storyboard.get_scenes(plan_id) if s_["data"]["prompts"]["qwen"]["prompt"] == one["body"]["prompt"])
    want = [r["name"] for r in sc["data"]["prompts"]["qwen"]["references"]]
    got = [i["meta"]["references"] for i in store.items(plan_id, scenes.KIND, sc["id"])][0]
    assert got == want and len(one["files"]) == len(want)
    assert "negative_prompt" not in one["body"] and one["body"]["response_format"] == "b64_json"
    plain = [s_ for s_ in storyboard.get_scenes(plan_id) if not s_["data"]["prompts"]["qwen"]["references"]]
    assert len(gw.count("/images/generations")) == len(plain)               # scenes without any reference are drawn plainly even in edit mode


def test_auto_mode_follows_the_scene_and_generate_mode_never_edits(env, monkeypatch, fast):
    plan_id = ready(env, with_refs=True)
    gw = Gateway()
    run(plan_id, gw, monkeypatch, mode="generate", score=False)
    assert gw.count("/images/generations") and not gw.count("/images/edits")
    assert {i["meta"]["mode"] for i in store.items(plan_id, scenes.KIND)} == {"generate"}


def test_a_failed_picture_is_recorded_and_the_rest_still_run(env, monkeypatch, fast):
    plan_id = ready(env)
    out = run(plan_id, Gateway(fail_for={1, 2}), monkeypatch, score=False)
    n = len(storyboard.get_scenes(plan_id))
    assert len(out["failed"]) == 1 and out["made"] == n - 1
    assert [i for i in store.items(plan_id, scenes.KIND) if i["status"] == "failed"][0]["meta"]["error"].startswith("502")


def test_unreachable_server_stops_with_a_clear_reason(env, monkeypatch, fast):
    plan_id = ready(env)

    class Down:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): raise httpx.ConnectError("refused")
    monkeypatch.setattr(scenes.httpx, "AsyncClient", Down)
    out = asyncio.run(scenes.generate(plan_id, s=SETTINGS, key="k"))
    assert out["made"] == 0 and len(out["failed"]) == 1 and "not reachable" in out["failed"][0]["error"]


def test_resume_draws_only_the_scenes_without_a_current_picture(env, monkeypatch, fast):
    plan_id = ready(env)
    run(plan_id, Gateway(fail_for={2, 3}), monkeypatch, score=False)
    gw = Gateway()
    out = run(plan_id, gw, monkeypatch, score=False)
    assert out["made"] == 1 and len(gw.requests) == 1
    assert run(plan_id, Gateway(), monkeypatch, score=False)["made"] == 0


def test_draw_all_never_touches_an_approved_scene_but_draw_again_adds_an_attempt(env, monkeypatch, fast):
    plan_id = ready(env)
    run(plan_id, Gateway(), monkeypatch, score=False)
    row = scenes.state(plan_id)["scenes"][0]
    scenes.approve(row["candidates"][0]["id"])
    gw = Gateway()
    run(plan_id, gw, monkeypatch, only_missing=False, scene_ids=[row["id"]], score=False)       # "Draw again" on one scene
    items = store.items(plan_id, scenes.KIND, row["id"])
    assert [i["attempt"] for i in items] == [1, 2] and items[0]["approved"] and not items[1]["approved"]
    assert items[0]["meta"]["seed"] != items[1]["meta"]["seed"]
    gw2 = Gateway()
    run(plan_id, gw2, monkeypatch, score=False)                                                 # "Draw all": everything already has a picture
    assert not gw2.requests


def test_a_changed_scene_marks_its_old_picture_old(env, monkeypatch, fast):
    plan_id = ready(env)
    run(plan_id, Gateway(), monkeypatch, score=False)
    sid = scenes.state(plan_id)["scenes"][0]["id"]
    sc = storyboard.get_scene(sid)
    d = sc["data"]
    d["subject"] = "a different subject entirely"
    db.ex("UPDATE scenes SET data=? WHERE id=?", (db.jdump(d), sid))
    imgplan.compile_plan(plan_id)
    st = scenes.state(plan_id)
    row = next(r for r in st["scenes"] if r["id"] == sid)
    assert not row["candidates"][0]["current"] and row["status"] == "needs_picture" and st["needs_picture"] == 1
    gw = Gateway()
    assert run(plan_id, gw, monkeypatch, score=False)["made"] == 1                              # only the changed scene is redrawn


def test_changing_an_approved_reference_marks_pictures_old(env, monkeypatch, fast):
    plan_id = ready(env, with_refs=True)
    run(plan_id, Gateway(), monkeypatch, mode="edit", score=False)
    st = scenes.state(plan_id)
    assert st["needs_picture"] == 0
    ref = refs.state(plan_id)["assets"][0]
    refs.approve(ref["candidates"][0]["id"], False)                                              # the sheet is withdrawn, prompts recompile
    assert scenes.state(plan_id)["needs_picture"] >= 1


def test_prompt_with_source_wording_is_refused_before_any_request(env, monkeypatch, fast):
    plan_id = ready(env)
    monkeypatch.setattr(scenes.leak, "check_many", lambda items, prof: [{"where": items[0][0], "text": "title of the source"}])
    gw = Gateway()
    out = run(plan_id, gw, monkeypatch)
    assert not gw.requests and out["made"] == 0 and out["failed"] and "source wording" in out["failed"][0]["error"]


def test_pictures_do_not_make_an_approved_plan_look_changed(env, monkeypatch, fast):
    from story2 import editorial
    from test_phase3e import exported
    plan_id = exported(env)
    imgplan.compile_plan(plan_id)
    editorial.approve(plan_id)
    h = editorial.content_hash(planner.get_plan(plan_id))
    run(plan_id, Gateway(), monkeypatch)
    scenes.approve_best(plan_id, 0)
    assert editorial.content_hash(planner.get_plan(plan_id)) == h
    assert editorial.approval_state(planner.get_plan(plan_id))["state"] == "approved"


# ── the trial ───────────────────────────────────────────────────────────────

def test_trial_picks_three_different_scenes_and_draws_each_on_both_models(env, monkeypatch, fast):
    plan_id = ready(env, with_refs=True)
    picked = scenes.trial_scenes(plan_id)
    assert len(picked) == 3 and len({s_["id"] for s_ in picked}) == 3
    gw = Gateway()
    monkeypatch.setattr(scenes.httpx, "AsyncClient", gw.client())
    monkeypatch.setattr(scenes.refscore.httpx, "AsyncClient", gw.client())
    out = asyncio.run(scenes.run_trial(plan_id, s=SETTINGS, key="k"))
    models = {r["body"]["model"] for r in gw.count("/images/generations") + gw.count("/images/edits")}
    assert models == {"qwen-image-2.1", "flux2-klein-9b"} and out["made"] >= 6 and not out["failed"]
    st = scenes.state(plan_id)
    assert st["trial"] == [s_["id"] for s_ in picked] and st["trial_done"]
    combos = {(c["model"], c["mode"]) for r in st["scenes"] if r["id"] in st["trial"] for c in r["candidates"]}
    assert {("qwen-image-2.1", "generate"), ("flux2-klein-9b", "generate"), ("qwen-image-2.1", "edit"), ("flux2-klein-9b", "edit")} <= combos
    assert all(c["trial"] for r in st["scenes"] if r["id"] in st["trial"] for c in r["candidates"])


def test_trial_without_references_only_draws_plain(env, monkeypatch, fast):
    plan_id = ready(env)
    gw = Gateway()
    monkeypatch.setattr(scenes.httpx, "AsyncClient", gw.client())
    monkeypatch.setattr(scenes.refscore.httpx, "AsyncClient", gw.client())
    asyncio.run(scenes.run_trial(plan_id, s=SETTINGS, key="k"))
    assert not gw.count("/images/edits") and len(gw.count("/images/generations")) == 6        # 3 scenes x 2 models


def test_choosing_a_trial_result_sets_the_model_and_mode_for_the_full_run(env, monkeypatch, fast):
    plan_id = ready(env, with_refs=True)
    st = scenes.choose(plan_id, "flux2-klein-9b", "edit")
    assert st["settings"]["model"] == "flux2-klein-9b" and st["settings"]["mode"] == "edit" and st["settings"]["chosen"]
    gw = Gateway()
    run(plan_id, gw, monkeypatch, score=False)
    assert {r["body"]["model"] for r in gw.count("/images/generations") + gw.count("/images/edits")} == {"flux2-klein-9b"}
    with pytest.raises(voice.MediaError):
        scenes.choose(plan_id, "qwen-image-2.1", "nonsense")


# ── correct this ────────────────────────────────────────────────────────────

def test_correct_sends_the_picture_first_with_a_change_and_keep_instruction(env, monkeypatch, fast):
    plan_id = ready(env)
    run(plan_id, Gateway(), monkeypatch, score=False)
    row = scenes.state(plan_id)["scenes"][0]
    base = row["candidates"][0]["id"]
    gw = Gateway()
    monkeypatch.setattr(scenes.httpx, "AsyncClient", gw.client())
    monkeypatch.setattr(scenes.refscore.httpx, "AsyncClient", gw.client())
    res = asyncio.run(scenes.correct(plan_id, row["id"], "make the sky stormy", ["the trader's face", "the desk"], base, s=SETTINGS, key="k"))
    r = gw.count("/images/edits")[0]
    assert r["files"][0][1][1] == store.path_of(store.get(base)).read_bytes()
    assert "Change only this: make the sky stormy." in r["body"]["prompt"] and "Keep unchanged: the trader's face; the desk." in r["body"]["prompt"]
    new = res["item"]
    assert new["attempt"] == 2 and new["meta"]["corrects"] == base and new["meta"]["mode"] == "correct" and store.get(base)["status"] == "done"
    with pytest.raises(voice.MediaError, match="what to change"):
        asyncio.run(scenes.correct(plan_id, row["id"], "  ", s=SETTINGS, key="k"))


def test_correct_needs_an_existing_picture(env, monkeypatch, fast):
    plan_id = ready(env)
    sid = storyboard.get_scenes(plan_id)[0]["id"]
    with pytest.raises(voice.MediaError, match="no finished picture"):
        asyncio.run(scenes.correct(plan_id, sid, "make it darker", s=SETTINGS, key="k"))


# ── scoring and bulk approval ───────────────────────────────────────────────

def test_pictures_are_scored_and_the_best_is_marked(env, monkeypatch, fast):
    plan_id = ready(env)
    n = len(storyboard.get_scenes(plan_id))
    looks = []
    for _ in range(n):
        looks += [{"anatomy_clean": 4, "defects": ["extra fingers"]}, {}]
    out = run(plan_id, Gateway(looks=looks), monkeypatch, candidates=2)
    assert out["scored"] == 2 * n
    for r in scenes.state(plan_id)["scenes"]:
        a, b = r["candidates"]
        assert a["score"]["total"] < b["score"]["total"] and r["best"] == b["id"]
        assert any("extra fingers" in f for f in a["score"]["flags"])


def test_quoted_text_must_be_read_back_exactly(env, monkeypatch, fast):
    plan_id = ready(env)
    sc = storyboard.get_scenes(plan_id)[0]
    d = sc["data"]
    d["text_on_screen"] = [{"text": "STOCK FALLS 17%", "placement": "on a newspaper"}]
    db.ex("UPDATE scenes SET data=? WHERE id=?", (db.jdump(d), sc["id"]))
    imgplan.compile_plan(plan_id)
    assert scenes.quoted_texts(storyboard.get_scene(sc["id"])) == ["STOCK FALLS 17%"]
    seen_ok = {"score": 90, "defects": [], "text_visible": True, "text_read": "Stock falls 17 %", "extras": [], "dims": {"characters_match": 9}}
    auto = {"score": 100, "reasons": []}
    assert not refscore.combine_scene(auto, seen_ok, ["STOCK FALLS 17%"])["hard"]
    bad = refscore.combine_scene(auto, {**seen_ok, "text_read": "STOCK FALLS FALLS 7%"}, ["STOCK FALLS 17%"])
    assert bad["hard"] and bad["total"] <= 49 and any("differs from the quoted text" in f for f in bad["flags"])
    assert refscore.combine_scene(auto, {**seen_ok, "text_read": "WELCOME"}, [])["hard"]                      # writing where none was asked for


def test_extra_things_and_a_wrong_character_are_flagged(env):
    auto = {"score": 100, "reasons": []}
    seen = {"score": 90, "defects": [], "text_visible": False, "text_read": "", "extras": ["a dog in the corner"], "dims": {"characters_match": 3}}
    c = refscore.combine_scene(auto, seen, [], with_reference=True)
    assert c["hard"] and any("not in the brief: a dog" in f for f in c["flags"]) and any("reference sheet" in f for f in c["flags"])
    c2 = refscore.combine_scene(auto, {**seen, "extras": [], "dims": {"characters_match": 9}}, [])
    assert not c2["hard"] and c2["total"] == 95 and c["total"] <= 49


def test_scene_scoring_asks_for_the_scene_checks_and_sends_the_brief(env, monkeypatch, fast):
    plan_id = ready(env)
    gw = Gateway()
    run(plan_id, gw, monkeypatch)
    ask = gw.count("/chat/completions")[0]["body"]["messages"][0]["content"][0]["text"]
    assert "finished scene picture" in ask and "characters_match" in ask and "text_read" in ask and "Subject:" in ask


def test_bulk_approve_takes_the_best_and_leaves_problems(env, monkeypatch, fast):
    plan_id = ready(env)
    n = len(storyboard.get_scenes(plan_id))
    looks = [{"text_visible": True, "text_read": "OOPS"}] + [{}] * (n - 1)                        # the first scene has writing nobody asked for
    run(plan_id, Gateway(looks=looks), monkeypatch)
    res = scenes.approve_best(plan_id)
    assert res["approved"] == n - 1 and len(res["left"]) == 1 and "problem" in res["left"][0]["why"]
    assert res["state"]["approved"] == n - 1 and res["state"]["needs_choice"] == 1
    assert scenes.approve_best(plan_id)["approved"] == 0


def test_bulk_approve_respects_the_minimum_and_never_replaces_a_chosen_picture(env, monkeypatch, fast):
    plan_id = ready(env)
    run(plan_id, Gateway(looks=[{**{k: 5 for k, _ in refscore.SCENE_DIMS}, "defects": ["a", "b", "c"]}] * 40), monkeypatch)
    assert scenes.approve_best(plan_id)["approved"] == 0
    assert scenes.approve_best(plan_id, min_score=50)["approved"] == len(storyboard.get_scenes(plan_id))
    first = scenes.state(plan_id)["scenes"][0]["approved"]
    run(plan_id, Gateway(), monkeypatch, only_missing=False)
    scenes.approve_best(plan_id, min_score=0)
    assert scenes.state(plan_id)["scenes"][0]["approved"] == first


def test_scoring_still_works_when_the_vision_check_is_unavailable(env, monkeypatch, fast):
    plan_id = ready(env)
    out = run(plan_id, Gateway(vision_down=True), monkeypatch)
    assert out["scored"] == len(storyboard.get_scenes(plan_id))
    c = scenes.state(plan_id)["scenes"][0]["candidates"][0]["score"]
    assert c["looked_at"] is None and c["measured"] > 0 and "unavailable" in c["note"]


def test_approving_one_picture_unapproves_its_siblings_and_failed_ones_cannot_be_approved(env, monkeypatch, fast):
    plan_id = ready(env)
    run(plan_id, Gateway(), monkeypatch, candidates=2, score=False)
    c = scenes.state(plan_id)["scenes"][0]["candidates"]
    scenes.approve(c[0]["id"])
    scenes.approve(c[1]["id"])
    assert not store.get(c[0]["id"])["approved"] and store.get(c[1]["id"])["approved"]
    run(plan_id, Gateway(fail_for={1, 2}), monkeypatch, only_missing=False, scene_ids=[scenes.state(plan_id)["scenes"][1]["id"]], score=False)
    bad = next(i for i in store.items(plan_id, scenes.KIND) if i["status"] == "failed")
    with pytest.raises(voice.MediaError, match="finished"):
        scenes.approve(bad["id"])


def test_state_counts_and_time_estimate(env, monkeypatch, fast):
    plan_id = ready(env)
    st = scenes.state(plan_id)
    n = len(storyboard.get_scenes(plan_id))
    assert st["ready"] and st["total"] == n and st["needs_picture"] == n and st["eta_missing_s"] > 0 and not st["done"]
    run(plan_id, Gateway(), monkeypatch)
    st = scenes.state(plan_id)
    assert st["needs_choice"] == n and st["eta_missing_s"] == 0
    scenes.approve_best(plan_id, 0)
    assert scenes.state(plan_id)["done"]


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
        for path in ("scenes", "scenes/trial"):
            r = c.post(f"/api/media/{plan['id']}/{path}", json={})
            assert r.status_code == 400 and "image prompts" in r.json()["detail"]
        st = c.get(f"/api/media/{plan['id']}").json()["scenes"]
        assert st["total"] == 0 and not st["ready"]
        assert c.post(f"/api/media/{plan['id']}/scenes/settings", json={"mode": "edit", "candidates": 2}).json()["scenes"]["settings"]["mode"] == "edit"
        assert c.post(f"/api/media/{plan['id']}/scenes/settings", json={"mode": "bad"}).status_code == 400
        assert c.post(f"/api/media/{plan['id']}/scenes/choose", json={"model": "nope", "mode": "edit"}).status_code == 400
        assert c.post(f"/api/media/{plan['id']}/scenes/x/correct", json={"change": " "}).status_code == 400
