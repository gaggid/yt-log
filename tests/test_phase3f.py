"""Phase 3, batch F: reference pictures for recurring people, places and objects."""
import asyncio
import base64
import io

import httpx
import pytest
from PIL import Image

from story import db
from story2 import editorial, imgplan, planner, storyboard
from story3 import refs, store, voice
from test_phase2b import boarded
from test_phase3e import exported

SETTINGS = {"base_url": "http://gw/v1"}


def png(w=64, h=48) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (30, 90, 160)).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


class Gateway:
    """Stands in for the image model: answers every generation request with a small picture."""

    def __init__(self, fail_for=()):
        self.requests, self.fail_for = [], set(fail_for)

    def client(self):
        gw = self

        class C:
            def __init__(self, *a, **k): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False

            async def post(self, url, json=None, headers=None):
                gw.requests.append({"url": url, "body": json, "auth": headers})
                if len(gw.requests) in gw.fail_for:
                    return httpx.Response(502, text="image engine error")
                return httpx.Response(200, json={"data": [{"b64_json": png(), "seed": json.get("seed"), "width": 64, "height": 48}]})
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
    imgplan.compile_plan(plan_id)
    return plan_id


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
    assert out["made"] == len(gw.requests) == 2 * n and not out["failed"]
    r = gw.requests[0]
    assert r["url"] == "http://gw/v1/images/generations" and r["auth"]["Authorization"] == "Bearer k"
    assert r["body"]["model"] == "qwen-image-2.1" and r["body"]["response_format"] == "b64_json" and "negative_prompt" not in r["body"]
    assert gw.requests[0]["body"]["seed"] != gw.requests[1]["body"]["seed"]
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
