"""Phase 3, batch F: reference pictures for recurring people, places and objects."""
import asyncio
import base64
import io

import httpx
import pytest
from PIL import Image, ImageDraw

from story import db
from story2 import editorial, imgplan, planner, storyboard
from story3 import refs, refscore, store, voice
from test_phase2b import boarded
from test_phase3e import exported

SETTINGS = {"base_url": "http://gw/v1", "model": "chat-model"}


def figure(w=64, h=48, cut=False, blank=False) -> Image.Image:
    """A grey backdrop with one navy subject standing clear of the edges (or running off the top, or nothing at all)."""
    im = Image.new("RGB", (w, h), (200, 200, 200))
    if not blank:
        d = ImageDraw.Draw(im)
        d.rectangle((w * 0.3, 0 if cut else h * 0.12, w * 0.7, h * 0.9), fill=(20, 40, 110))
        d.rectangle((w * 0.4, h * 0.3, w * 0.5, h * 0.5), fill=(30, 160, 90))
    return im


def png(w=64, h=48, **kw) -> str:
    buf = io.BytesIO()
    figure(w, h, **kw).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


class Gateway:
    """Stands in for the image model: answers every generation request with a small picture."""

    def __init__(self, fail_for=(), looks=None, vision_down=False):
        self.requests, self.fail_for, self.vision_down = [], set(fail_for), vision_down
        self.looks = list(looks or [])                                                                  # answers of the vision check, in order

    def client(self):
        gw = self

        class C:
            def __init__(self, *a, **k): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False

            async def post(self, url, json=None, headers=None):
                gw.requests.append({"url": url, "body": json, "auth": headers})
                if url.endswith("/chat/completions"):
                    if gw.vision_down:
                        return httpx.Response(502, text="model not loaded")
                    ans = gw.looks.pop(0) if gw.looks else {}
                    good = {k: 8 for k, _ in refscore.DIMS} | {"text_visible": False, "defects": []}
                    return httpx.Response(200, json={"choices": [{"message": {"content": "```json\n" + __import__("json").dumps(good | ans) + "\n```"}}]})
                if len([r for r in gw.requests if r["url"].endswith("/images/generations")]) in gw.fail_for:
                    return httpx.Response(502, text="image engine error")
                w, h = (int(v) for v in json["size"].split("x"))
                return httpx.Response(200, json={"data": [{"b64_json": png(w // 16, h // 16), "seed": json.get("seed"), "width": w, "height": h}]})
        return C


@pytest.fixture
def fast(monkeypatch):
    async def nosleep(_):
        return None
    monkeypatch.setattr(refs.asyncio, "sleep", nosleep)


def planned(env):
    pid, cid, be, p = boarded(env)
    plan_id = p["id"]
    two_scenes_with_the_person(plan_id)
    more_assets(plan_id)
    imgplan.compile_plan(plan_id)
    return plan_id


def more_assets(plan_id):
    """Add a place and a prop that each appear in two scenes, so there are three recurring items to choose between."""
    scenes = storyboard.get_scenes(plan_id)
    for n, (kind, name, desc) in enumerate([("place", "the old office", "a narrow office with wooden desks and tall windows"),
                                            ("prop", "the brass clock", "a round brass wall clock with a white face")]):
        aid = f"as-test{n}"
        db.ex("INSERT INTO assets(id,plan_id,kind,name,data,updated_at) VALUES(?,?,?,?,?,?)",
              (aid, plan_id, kind, name, db.jdump({"name": name, "kind": kind, "description": desc, "fixed": ["brass frame"], "flexible": [], "period": "",
                                                  "fictionalisation": "generic_reconstruction", "evidence_note": ""}), db.now()))
        for sc in scenes[3 + 2 * n:5 + 2 * n]:
            d = sc["data"]
            d["continuity"]["assets"] = d["continuity"]["assets"] + [aid]
            db.ex("UPDATE scenes SET data=?, updated_at=? WHERE id=?", (db.jdump(d), db.now(), sc["id"]))


def two_scenes_with_the_person(plan_id):
    """The fixture storyboard may show the person once; make sure the registry's person appears in at least two scenes."""
    person = next(a for a in storyboard.get_assets(plan_id) if a["kind"] == "person")
    for sc in storyboard.get_scenes(plan_id)[:3]:
        d = sc["data"]
        ids = d["continuity"]["assets"]
        if person["id"] not in ids:
            d["continuity"]["assets"] = ids + [person["id"]]
            db.ex("UPDATE scenes SET data=?, updated_at=? WHERE id=?", (db.jdump(d), db.now(), sc["id"]))
    return person["id"]


def run(plan_id, gw, monkeypatch, **kw):
    monkeypatch.setattr(refs.httpx, "AsyncClient", gw.client())
    return asyncio.run(refs.generate(plan_id, s=SETTINGS, key="k", **kw))


def test_only_recurring_people_places_and_props_need_a_reference(env):
    plan_id = planned(env)
    t = refs.targets(plan_id)
    assert t and all(x["asset"]["kind"] in ("person", "place", "prop") and len(x["scenes"]) >= refs.MIN_SCENES for x in t)
    assert not [x for x in t if x["asset"]["kind"] in ("style", "narrator")]


def test_prompt_carries_the_fixed_details_the_style_and_a_no_text_rule(env):
    plan_id = planned(env)
    a = refs.targets(plan_id)[0]["asset"]
    style = refs.style_text(plan_id)
    q = refs.build_prompt(a, style, "qwen-image-2.1")
    f = refs.build_prompt(a, style, "flux2-klein-9b")
    assert a["data"]["description"].split(".")[0].lower() in q["prompt"].lower()
    for fx in a["data"].get("fixed", []):
        assert fx.lower() in q["prompt"].lower()
    assert style and style in q["prompt"] and "No text" in q["prompt"]
    assert q["negative_prompt"] == "" and f["negative_prompt"]                               # Qwen ignores a negative prompt; FLUX honours it
    for p in (q, f):
        assert p["width"] % 16 == 0 and p["height"] % 16 == 0 and p["width"] * p["height"] <= 2359296


def test_one_request_per_candidate_with_distinct_seeds_and_files_saved(env, monkeypatch, fast):
    plan_id = planned(env)
    gw = Gateway()
    out = run(plan_id, gw, monkeypatch, candidates=2)
    n = len(refs.targets(plan_id))
    imgs = [r for r in gw.requests if r["url"].endswith("/images/generations")]
    assert out["made"] == len(imgs) == 2 * n and not out["failed"]
    r = imgs[0]
    assert r["url"] == "http://gw/v1/images/generations" and r["auth"]["Authorization"] == "Bearer k"
    assert r["body"]["model"] == "qwen-image-2.1" and r["body"]["response_format"] == "b64_json" and "negative_prompt" not in r["body"]
    assert imgs[0]["body"]["seed"] != imgs[1]["body"]["seed"]
    items = store.items(plan_id, "reference")
    assert all(store.path_of(i).is_file() and i["status"] == "done" and i["meta"]["prompt"] for i in items)


def test_flux_gets_a_negative_prompt(env, monkeypatch, fast):
    plan_id = planned(env)
    gw = Gateway()
    run(plan_id, gw, monkeypatch, candidates=1, model="flux2-klein-9b")
    assert gw.requests[0]["body"]["model"] == "flux2-klein-9b" and gw.requests[0]["body"]["negative_prompt"]


def test_only_missing_skips_assets_that_already_have_pictures(env, monkeypatch, fast):
    plan_id = planned(env)
    gw = Gateway()
    run(plan_id, gw, monkeypatch, candidates=1)
    n = len(gw.requests)
    run(plan_id, gw, monkeypatch, candidates=1)
    assert len(gw.requests) == n
    aid = refs.targets(plan_id)[0]["asset"]["id"]
    run(plan_id, gw, monkeypatch, asset_ids=[aid], candidates=1, only_missing=False)
    assert [i["attempt"] for i in store.items(plan_id, "reference", aid)] == [1, 2]            # new attempt, old file kept


def test_a_failed_picture_is_recorded_and_the_rest_still_run(env, monkeypatch, fast):
    plan_id = planned(env)
    gw = Gateway(fail_for={1, 2})                                                                 # first picture fails both tries
    out = run(plan_id, gw, monkeypatch, candidates=1)
    assert len(out["failed"]) == 1 and out["made"] == len(refs.targets(plan_id)) - 1
    assert [i for i in store.items(plan_id, "reference") if i["status"] == "failed"][0]["meta"]["error"].startswith("502")


def test_unreachable_server_stops_with_a_clear_reason(env, monkeypatch, fast):
    plan_id = planned(env)

    class Down:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): raise httpx.ConnectError("refused")
    monkeypatch.setattr(refs.httpx, "AsyncClient", Down)
    out = asyncio.run(refs.generate(plan_id, s=SETTINGS, key="k"))
    assert out["made"] == 0 and len(out["failed"]) == 1 and "not reachable" in out["failed"][0]["error"]


def test_approving_writes_the_asset_and_switches_later_scenes_to_edit_mode(env, monkeypatch, fast):
    plan_id = planned(env)
    run(plan_id, Gateway(), monkeypatch, candidates=1)
    row = refs.state(plan_id)["assets"][0]
    cand = row["candidates"][0]
    before = refs.state(plan_id)["scenes_using_references"]
    st = refs.approve(cand["id"])
    a = next(x for x in storyboard.get_assets(plan_id) if x["id"] == row["asset_id"])
    assert a["data"]["reference_images"] == [{"id": cand["id"], "file": f"refs/{row['asset_id']}-a1.png", "approved": True, "note": a["data"]["reference_images"][0]["note"]}]
    assert st["assets"][0]["approved"] == cand["id"] and st["approved"] == 1
    assert st["scenes_using_references"] > before                                                 # prompts were recompiled with the reference
    used = [sc for sc in storyboard.get_scenes(plan_id) if row["asset_id"] in sc["data"]["continuity"]["assets"]]
    assert any(sc["data"]["prompts"]["qwen"]["references"] for sc in used)
    assert all(len(sc["data"]["prompts"]["qwen"]["references"]) <= 3 for sc in storyboard.get_scenes(plan_id))
    refs.approve(cand["id"], False)                                                                # taking the approval away undoes it
    assert next(x for x in storyboard.get_assets(plan_id) if x["id"] == row["asset_id"])["data"]["reference_images"] == []
    assert refs.state(plan_id)["scenes_using_references"] == before


def test_approving_one_candidate_unapproves_its_siblings(env, monkeypatch, fast):
    plan_id = planned(env)
    run(plan_id, Gateway(), monkeypatch, candidates=2)
    c = refs.state(plan_id)["assets"][0]["candidates"]
    refs.approve(c[0]["id"])
    refs.approve(c[1]["id"])
    assert not store.get(c[0]["id"])["approved"] and store.get(c[1]["id"])["approved"]
    ref = next(a for a in storyboard.get_assets(plan_id) if a["id"] == refs.state(plan_id)["assets"][0]["asset_id"])["data"]["reference_images"]
    assert [r["id"] for r in ref] == [c[1]["id"]]


def test_a_failed_or_unfinished_picture_cannot_be_approved(env, monkeypatch, fast):
    plan_id = planned(env)
    run(plan_id, Gateway(fail_for={1, 2}), monkeypatch, candidates=1)
    bad = next(i for i in store.items(plan_id, "reference") if i["status"] == "failed")
    with pytest.raises(voice.MediaError, match="finished"):
        refs.approve(bad["id"])


def test_making_references_does_not_make_an_approved_plan_look_changed(env, monkeypatch, fast):
    plan_id = exported(env)
    two_scenes_with_the_person(plan_id)
    ap = editorial.approve(plan_id)
    assert ap["state"] == "approved"
    h = editorial.content_hash(planner.get_plan(plan_id))
    run(plan_id, Gateway(), monkeypatch, candidates=1)
    refs.approve(refs.state(plan_id)["assets"][0]["candidates"][0]["id"])
    assert editorial.content_hash(planner.get_plan(plan_id)) == h                                  # pictures and recompiled prompts are derived data
    assert editorial.approval_state(planner.get_plan(plan_id))["state"] == "approved"


def test_changing_the_description_makes_old_pictures_stop_counting(env, monkeypatch, fast):
    plan_id = planned(env)
    run(plan_id, Gateway(), monkeypatch, candidates=1)
    row = refs.state(plan_id)["assets"][0]
    assert row["candidates"][0]["current"]
    db.ex("UPDATE assets SET data=json_set(data,'$.description','a completely different look') WHERE id=?", (row["asset_id"],))
    st = refs.state(plan_id)
    assert not st["assets"][0]["candidates"][0]["current"] and st["without_pictures"] >= 1


def test_a_prompt_that_carries_source_wording_is_refused_before_any_request(env, monkeypatch, fast):
    plan_id = planned(env)
    monkeypatch.setattr(refs.leak, "check_many", lambda items, prof: [{"where": items[0][0], "text": "title of the source"}])
    gw = Gateway()
    out = run(plan_id, gw, monkeypatch, candidates=1)
    assert not gw.requests and out["made"] == 0 and out["failed"] and "source wording" in out["failed"][0]["error"]


def test_skipping_an_asset_and_the_done_state(env, monkeypatch, fast):
    plan_id = planned(env)
    st = refs.state(plan_id)
    assert not st["done"] and st["open"] == st["total"] and st["eta_missing_s"] > 0
    for r in st["assets"][1:]:
        refs.set_skip(plan_id, r["asset_id"], True)
    run(plan_id, Gateway(), monkeypatch, candidates=1)                                            # skipped assets get nothing
    assert {i["key"] for i in store.items(plan_id, "reference")} == {st["assets"][0]["asset_id"]}
    refs.approve(refs.state(plan_id)["assets"][0]["candidates"][0]["id"])
    st = refs.state(plan_id)
    assert st["done"] and st["open"] == 0
    with pytest.raises(voice.MediaError):
        refs.set_skip(plan_id, "as-not-a-target", True)


def test_state_learns_the_time_per_picture(env, monkeypatch, fast):
    plan_id = planned(env)
    assert refs.state(plan_id)["seconds_per_picture"] == refs.DEFAULT_SECONDS
    run(plan_id, Gateway(), monkeypatch, candidates=1)
    assert refs.state(plan_id)["seconds_per_picture"] >= 0 and refs.state(plan_id)["without_pictures"] == 0


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
        r = c.post(f"/api/media/{plan['id']}/references", json={})
        assert r.status_code == 400 and "no person" in r.json()["detail"]
        assert c.get(f"/api/media/{plan['id']}").json()["refs"]["total"] == 0
        assert c.post(f"/api/media/{plan['id']}/references/skip", json={"asset_id": "as-x"}).status_code == 400


# ── scoring and bulk approval ───────────────────────────────────────────────

def test_measuring_catches_blank_cut_and_cluttered_pictures(tmp_path):
    def save(im, name):
        p = tmp_path / name
        im.save(p)
        return p
    ok = refscore.measure(save(figure(256, 336), "ok.png"), "person", (256, 336))
    assert ok["score"] == 100 and not ok["reasons"]
    assert refscore.measure(save(figure(256, 336, blank=True), "blank.png"), "person")["score"] == 0
    cut = refscore.measure(save(figure(256, 336, cut=True), "cut.png"), "person")
    assert cut["score"] <= 65 and any("cut by the frame" in r for r in cut["reasons"])
    busy = figure(256, 336)
    d = ImageDraw.Draw(busy)
    for x in range(0, 256, 16):
        d.rectangle((x, 0, x + 8, 30), fill=(10, 10, 10))
    assert any("backdrop is not plain" in r for r in refscore.measure(save(busy, "busy.png"), "person")["reasons"])
    assert any("differs from" in r for r in refscore.measure(save(figure(256, 336), "shape.png"), "person", (336, 256))["reasons"])


def test_combine_never_lets_a_hard_problem_through_and_ranks_the_rest():
    auto = {"score": 100, "reasons": []}
    seen = {"score": 80, "defects": ["a hand is melted"], "text_visible": False}
    c = refscore.combine(auto, seen)
    assert c["total"] == 90 and not c["hard"] and c["flags"] == ["looks wrong: a hand is melted"]
    t = refscore.combine(auto, {"score": 95, "defects": [], "text_visible": True})
    assert t["hard"] and t["total"] <= 49
    assert refscore.combine({"score": 65, "reasons": ["subject is cut by the frame (top)"]}, None)["hard"]
    assert refscore.combine({"score": 90, "reasons": []}, None)["total"] == 90              # no vision check: the measured score stands alone


def test_new_pictures_are_scored_after_drawing_and_the_best_is_marked(env, monkeypatch, fast):
    plan_id = planned(env)
    n = len(refs.targets(plan_id))
    looks = []
    for _ in range(n):                                                                              # per item: a weak first picture, a strong second
        looks += [{"anatomy_clean": 4, "defects": ["extra fingers"]}, {}]
    out = run(plan_id, Gateway(looks=looks), monkeypatch, candidates=2)
    assert out["scored"] == 2 * n
    st = refs.state(plan_id)
    for r in st["assets"]:
        a, b = r["candidates"]
        assert a["score"]["total"] < b["score"]["total"] and r["best"] == b["id"]
        assert any("extra fingers" in f for f in a["score"]["flags"])
    assert st["unscored"] == 0 and st["bulk_ready"] == n


def test_bulk_approve_takes_the_best_of_each_and_leaves_problems_for_a_person(env, monkeypatch, fast):
    plan_id = planned(env)
    n = len(refs.targets(plan_id))
    looks = [{"text_visible": True, "defects": ["a caption"]}] * 2 + [{}, {"defects": ["a fold looks odd"]}] * (n - 1)    # the first item has text on both pictures
    run(plan_id, Gateway(looks=looks), monkeypatch, candidates=2)
    before = refs.state(plan_id)["scenes_using_references"]
    res = refs.approve_best(plan_id)
    assert res["approved"] == n - 1 and len(res["left"]) == 1 and "problem" in res["left"][0]["why"]
    st = res["state"]
    assert st["approved"] == n - 1 and st["open"] == 1 and st["scenes_using_references"] > before
    for r in st["assets"]:
        if r["approved"]:
            assert r["approved"] == r["best"]
            a = next(x for x in storyboard.get_assets(plan_id) if x["id"] == r["asset_id"])
            assert a["data"]["reference_images"][0]["id"] == r["best"] and "score" in a["data"]["reference_images"][0]["note"]
    assert refs.approve_best(plan_id)["approved"] == 0                                              # nothing more to take


def test_bulk_approve_respects_the_minimum_and_never_replaces_a_chosen_picture(env, monkeypatch, fast):
    plan_id = planned(env)
    run(plan_id, Gateway(looks=[{k: 3 for k, _ in refscore.DIMS}] * 20), monkeypatch, candidates=1)
    assert refs.approve_best(plan_id)["approved"] == 0                                              # scores around 65 fall under 70
    assert refs.approve_best(plan_id, min_score=50)["approved"] == len(refs.targets(plan_id))
    st = refs.state(plan_id)
    first = st["assets"][0]["approved"]
    run(plan_id, Gateway(), monkeypatch, candidates=1, only_missing=False)
    refs.approve_best(plan_id, min_score=0)
    assert refs.state(plan_id)["assets"][0]["approved"] == first                                    # a chosen picture is not replaced by a newer one


def test_bulk_approve_skips_skipped_items(env, monkeypatch, fast):
    plan_id = planned(env)
    run(plan_id, Gateway(), monkeypatch, candidates=1)
    victim = refs.state(plan_id)["assets"][-1]["asset_id"]
    refs.set_skip(plan_id, victim, True)
    res = refs.approve_best(plan_id, min_score=0)
    assert res["approved"] == len(refs.targets(plan_id)) - 1
    assert next(r for r in res["state"]["assets"] if r["asset_id"] == victim)["approved"] is None


def test_scoring_still_works_when_the_vision_check_is_unavailable(env, monkeypatch, fast):
    plan_id = planned(env)
    out = run(plan_id, Gateway(vision_down=True), monkeypatch, candidates=1)
    assert out["scored"] == len(refs.targets(plan_id))
    c = refs.state(plan_id)["assets"][0]["candidates"][0]["score"]
    assert c["looked_at"] is None and c["measured"] > 0 and "unavailable" in c["note"]


def test_score_later_fills_in_pictures_made_without_scoring(env, monkeypatch, fast):
    plan_id = planned(env)
    run(plan_id, Gateway(), monkeypatch, candidates=1, score=False)
    assert refs.state(plan_id)["unscored"] == len(refs.targets(plan_id))
    monkeypatch.setattr(refscore.httpx, "AsyncClient", Gateway().client())
    out = asyncio.run(refs.score_items(plan_id, s=SETTINGS, key="k"))
    assert out["scored"] == len(refs.targets(plan_id)) and refs.state(plan_id)["unscored"] == 0



def test_recreating_the_characters_after_scenes_exist_reopens_references_and_flags_the_scenes(env):
    from story2 import api as plans_api
    plan_id = planned(env)
    assert refs.targets(plan_id) and not plans_api.orphaned_scenes(planner.get_plan(plan_id) | {"assets": storyboard.get_assets(plan_id), "scenes": storyboard.get_scenes(plan_id)})
    db.ex("DELETE FROM assets WHERE plan_id=? AND kind!='style'", (plan_id,))                      # the registry is made again: new ids, the scenes still hold the old ones
    for n, (kind, name) in enumerate([("person", "the analyst"), ("place", "the floor")]):
        db.ex("INSERT INTO assets(id,plan_id,kind,name,data,updated_at) VALUES(?,?,?,?,?,?)",
              (f"as-new{n}", plan_id, kind, name, db.jdump({"name": name, "kind": kind, "description": "x", "fixed": [], "fictionalisation": "fictional"}), db.now()))
    t = refs.targets(plan_id)
    assert {x["asset"]["id"] for x in t} == {"as-new0", "as-new1"}                                 # references can be made before the scenes are redone
    full = planner.get_plan(plan_id) | {"assets": storyboard.get_assets(plan_id), "scenes": storyboard.get_scenes(plan_id)}
    assert plans_api.orphaned_scenes(full) and plans_api.style_info(full)["storyboard_stale"]


def test_references_can_be_approved_before_the_storyboard_exists(env, monkeypatch, fast):
    from test_phase2a import approved_story
    pid, cid = approved_story(env)
    plan_id = planner.create_plan(cid, minutes=2)["id"]
    db.ex("INSERT INTO assets(id,plan_id,kind,name,data,updated_at) VALUES(?,?,?,?,?,?)",
          ("as-early", plan_id, "person", "the analyst", db.jdump({"name": "the analyst", "kind": "person", "description": "a tall woman", "fixed": [], "fictionalisation": "fictional"}), db.now()))
    db.ex("INSERT INTO assets(id,plan_id,kind,name,data,updated_at) VALUES(?,?,?,?,?,?)",
          ("as-style", plan_id, "style", "style", db.jdump({"name": "style", "kind": "style", "description": "bold outlines", "fixed": []}), db.now()))
    assert [t["asset"]["id"] for t in refs.targets(plan_id)] == ["as-early"] and not storyboard.get_scenes(plan_id)
    run(plan_id, Gateway(), monkeypatch, candidates=1)
    st = refs.approve(refs.state(plan_id)["assets"][0]["candidates"][0]["id"])                       # used to fail: "design the storyboard first"
    assert st["approved"] == 1 and refs.approve_best(plan_id, 0)["approved"] == 0


def test_a_characters_age_or_a_prop_count_from_the_registry_is_not_a_claim_about_the_story(env):
    plan_id = planned(env)
    person = next(a for a in storyboard.get_assets(plan_id) if a["kind"] == "person")
    d = person["data"]
    d["description"] = "Man, 37 years old, tall and lean."
    d["fixed"] = list(d.get("fixed", [])) + ["hair: short grey hair"]
    db.ex("UPDATE assets SET data=?, rev=rev+1 WHERE id=?", (db.jdump(d), person["id"]))
    sc = next(s for s in storyboard.get_scenes(plan_id) if person["id"] in s["data"]["continuity"]["assets"])
    d2 = sc["data"]
    d2["subject"] = "the trader checks the screen"
    d2["action"] = "he watches a 73 percent jump"                                         # a number about the story: still has to be in the facts
    db.ex("UPDATE scenes SET data=? WHERE id=?", (db.jdump(d2), sc["id"]))
    rep = imgplan.compile_plan(plan_id)
    msgs = [i["text"] for i in rep["issues"] if i["kind"] == "number" and i["where"] == sc["id"]]
    assert not any(" 37," in m or "states 37" in m for m in msgs)                           # the age is allowed
    assert any("73" in m for m in msgs)                                                      # a claimed figure is still checked
