"""Phase 3, batch H: built graphics (stat card, comparison, bar and line chart, timeline, title card) from the story's verified facts."""
import pytest
from PIL import Image

from story import db
from story2 import editorial, imgplan, planner, storyboard
from story2.scene_schemas import NEEDS_ASSET
from story3 import graphics, store, voice
from test_phase3f import planned
from test_phase3e import exported

FACTS = "Premise: a trading firm lost money.\nWhat happened, in order:\n- 1 August 2012: the firm lost 440 million dollars in 45 minutes\n- 2 August 2012: shares fell 17%"
CHRON = [{"when": "1 August 2012", "what": "the trading firm lost money in 45 minutes"}, {"when": "2 August 2012", "what": "the firm shares fell sharply"},
         {"when": "", "what": "the firm had no date for this trading event"}]


def ctx(facts=FACTS, chron=CHRON):
    text = facts
    return {"text": text, "lower": text.lower(), "known": {x.replace(",", "") for x in storyboard.fact_numbers(text)}, "pub": {"chronology": chron}}


def set_scene(sc, vt="data_chart", fixed=(), texts=(), subject="the firm's losses", action=""):
    d = sc["data"]
    d["visual_type"] = vt
    d["subject"] = subject
    d["action"] = action
    d["facts"] = {"fixed": list(fixed), "creative": []}
    d["text_on_screen"] = [{"text": t, "placement": ""} for t in texts]
    db.ex("UPDATE scenes SET data=? WHERE id=?", (db.jdump(d), sc["id"]))
    return storyboard.get_scene(sc["id"])


def scene(env, **kw):
    plan_id = planned(env)
    sc = storyboard.get_scenes(plan_id)[0]
    return plan_id, set_scene(sc, **kw)


def test_numbers_are_read_with_their_unit_and_label():
    f = graphics.figures("Shares fell 17% in a day")[0]
    assert f["shown"] == "17%" and f["digits"] == "17" and f["label"] == "Shares fell in a day"
    g = graphics.figures("Loss of $440 million")[0]
    assert g["shown"] == "$440 million" and g["digits"] == "440"
    assert graphics.figures("The 1,200 traders")[0]["digits"] == "1200"
    assert graphics.figures("no numbers here") == []


def test_a_number_must_appear_whole_in_the_facts():
    c = ctx()
    assert graphics.verified(graphics.figures("fell 17%")[0], c["known"])
    assert not graphics.verified(graphics.figures("fell 7%")[0], c["known"])              # 7 is not in the facts (17 and 2012 are)
    assert not graphics.verified(graphics.figures("in 20")[0], c["known"])                # 20 is not found inside 2012


def test_one_verified_number_makes_a_stat_card_and_says_a_chart_was_wanted(env):
    plan_id, sc = scene(env, fixed=["Shares fell 17% in a day"])
    spec = graphics.spec_for(sc, ctx())
    assert spec["template"] == "stat" and spec["items"][0]["shown"] == "17%" and spec["items"][0]["label"] == "Shares fell in a day"
    assert "only one number" in graphics.explain(spec, sc)


def test_an_unverified_number_is_left_out_and_reported(env):
    plan_id, sc = scene(env, fixed=["Shares fell 17% in a day", "A rival gained 63% that week"])
    spec = graphics.spec_for(sc, ctx())
    assert [i["shown"] for i in spec["items"]] == ["17%"] and any("63%" in x and "not in the story's facts" in x for x in spec["dropped"])
    assert "63" not in graphics.numbers_on_card(spec)


def test_two_verified_numbers_make_a_comparison(env):
    plan_id, sc = scene(env, vt="screen_interface", fixed=["Lost 440 million dollars", "Time taken 45 minutes"])
    spec = graphics.spec_for(sc, ctx())
    assert spec["template"] == "compare" and [i["value"] for i in spec["items"]] == [440, 45]


def test_a_chart_needs_every_point_from_the_facts(env):
    c = ctx(FACTS + "\n- sales in 2010 were 120, in 2011 were 150, in 2012 were 90")
    plan_id, sc = scene(env, fixed=["2010: 120", "2011: 150", "2012: 90"])
    spec = graphics.spec_for(sc, c)
    assert spec["template"] == "line" and [p["value"] for p in spec["points"]] == [120, 150, 90] and not graphics.explain(spec, sc)
    sc2 = set_scene(storyboard.get_scene(sc["id"]), fixed=["2010: 120", "2011: 150", "2012: 777"])               # the third point is not in the facts: no chart, a comparison of the two that are
    spec2 = graphics.spec_for(sc2, c)
    assert spec2["template"] == "compare" and any("777" in x for x in spec2["dropped"])


def test_a_category_series_is_a_bar_chart(env):
    c = ctx(FACTS + "\n- Alpha 10, Beta 20, Gamma 30")
    plan_id, sc = scene(env, fixed=["Alpha: 10", "Beta: 20", "Gamma: 30"])
    assert graphics.spec_for(sc, c)["template"] == "bar"


def test_a_timeline_uses_only_dated_events_that_match_the_scene(env):
    plan_id, sc = scene(env, vt="map_timeline", subject="the trading firm's two bad days")
    spec = graphics.spec_for(sc, ctx())
    assert spec["template"] == "timeline" and [e["when"] for e in spec["events"]] == ["1 August 2012", "2 August 2012"]
    assert not graphics.explain(spec, sc)


def test_no_facts_gives_a_title_card_and_a_reason(env):
    plan_id, sc = scene(env, vt="document_archival", subject="an old memo", texts=["BOARD MEMO"])
    spec = graphics.spec_for(sc, ctx(chron=[]))
    assert spec["template"] == "text" and spec["title"] == "BOARD MEMO" and "no verified number or dated event" in graphics.explain(spec, sc)
    sc = set_scene(storyboard.get_scene(sc["id"]), vt="screen_interface", subject="a dark trading screen", texts=["ठीक है"])    # Devanagari is never drawn on a card
    assert graphics.spec_for(sc, ctx(chron=[]))["title"] == "a dark trading screen"


@pytest.mark.parametrize("fixed,vt", [(["Shares fell 17% in a day"], "data_chart"), (["Lost 440 million dollars", "Time taken 45 minutes"], "data_chart"),
                                      (["Alpha: 10", "Beta: 20", "Gamma: 30"], "data_chart"), (["2010: 120", "2011: 150", "2012: 90"], "data_chart"), ([], "map_timeline"), ([], "document_archival")])
def test_every_template_draws_a_1080p_picture_with_text_that_fits(env, monkeypatch, fixed, vt):
    plan_id, sc = scene(env, vt=vt, fixed=fixed, subject="the trading firm's losses")
    monkeypatch.setattr(graphics, "facts_ctx", lambda plan: ctx(FACTS + "\n- Alpha 10, Beta 20, Gamma 30; 2010 120 2011 150 2012 90"))
    out = graphics.build(plan_id)
    it = store.items(plan_id, graphics.KIND, sc["id"])[0]
    im = Image.open(store.path_of(it))
    assert im.size == (1920, 1080) and it["status"] == "done" and it["meta"]["animation"] and it["meta"]["style"]
    assert out["made"] >= 1
    px = im.convert("L")
    assert px.getextrema()[1] - px.getextrema()[0] > 60                                         # not a blank card


def test_long_text_is_shrunk_to_fit_the_frame():
    from PIL import ImageDraw
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    f, lines, lh = graphics.fitted(d, "a very long headline " * 12, "bold", 1500, 560, 130, 48, 4)
    assert len(lines) <= 4 and all(graphics.text_w(d, ln, f) <= 1500 for ln in lines)


def test_every_number_on_a_built_card_is_in_the_facts(env, monkeypatch):
    plan_id, sc = scene(env, fixed=["Shares fell 17% in a day", "A rival gained 63% that week", "Lost 440 million dollars"])
    c = ctx()
    monkeypatch.setattr(graphics, "facts_ctx", lambda plan: c)
    graphics.build(plan_id)
    it = store.items(plan_id, graphics.KIND, sc["id"])[0]
    assert it["meta"]["numbers"] and set(it["meta"]["numbers"]) <= c["known"] and it["meta"]["dropped"]


def test_real_story_facts_feed_the_check(env):
    plan_id, sc = scene(env, fixed=["it grew 987654 percent"])
    spec = graphics.spec_for(sc, graphics.facts_ctx(planner.get_plan(plan_id)))
    assert spec["template"] == "text" and any("987654" in x for x in spec["dropped"])


def test_only_scenes_that_need_an_asset_get_a_graphic(env, monkeypatch):
    plan_id = planned(env)
    scs = storyboard.get_scenes(plan_id)
    set_scene(scs[0], vt="data_chart", fixed=["fell 17%"])
    set_scene(scs[1], vt="character", fixed=["fell 17%"])
    monkeypatch.setattr(graphics, "facts_ctx", lambda plan: ctx())
    graphics.build(plan_id)
    assert {i["key"] for i in store.items(plan_id, graphics.KIND)} == {s_["id"] for s_ in storyboard.get_scenes(plan_id) if s_["data"]["visual_type"] in NEEDS_ASSET}


def test_building_again_keeps_current_cards_and_a_changed_fact_makes_a_new_one(env, monkeypatch):
    plan_id, sc = scene(env, fixed=["Shares fell 17% in a day"])
    monkeypatch.setattr(graphics, "facts_ctx", lambda plan: ctx())
    graphics.build(plan_id, [sc["id"]])
    again = graphics.build(plan_id, [sc["id"]])
    assert again["made"] == 0 and again["kept"] == 1
    assert graphics.build(plan_id, [sc["id"]], force=True)["made"] == 1
    set_scene(storyboard.get_scene(sc["id"]), fixed=["Shares fell 17% in a day", "Lost 440 million dollars"])
    out = graphics.build(plan_id, [sc["id"]])
    assert out["made"] == 1
    row = out["state"]["scenes"][0]
    assert row["template"] == "compare" and row["status"] == "needs_choice" and [i["current"] for i in row["items"]] == [False, False, True]


def test_changing_the_style_marks_cards_old(env, monkeypatch):
    plan_id, sc = scene(env, fixed=["Shares fell 17% in a day"])
    monkeypatch.setattr(graphics, "facts_ctx", lambda plan: ctx())
    graphics.build(plan_id)
    graphics.approve(graphics.state(plan_id)["scenes"][0]["current_item"]["id"])
    assert graphics.state(plan_id)["done"]
    plan = planner.get_plan(plan_id)
    db.ex("UPDATE plans SET settings=? WHERE id=?", (db.jdump({**plan["settings"], "visual_style": "noir"}), plan_id))
    st = graphics.state(plan_id)
    assert not st["done"] and st["scenes"][0]["status"] == "needs_build"
    graphics.build(plan_id)
    assert store.items(plan_id, graphics.KIND)[-1]["meta"]["style"] == "noir"


def test_approval_one_per_scene_and_approve_all_leaves_fallbacks(env, monkeypatch):
    plan_id = planned(env)
    scs = storyboard.get_scenes(plan_id)
    set_scene(scs[0], vt="map_timeline", subject="the trading firm's two bad days")                 # a real timeline
    set_scene(scs[1], vt="data_chart", fixed=["Shares fell 17% in a day"])                          # a chart wanted, a stat card given
    monkeypatch.setattr(graphics, "facts_ctx", lambda plan: ctx())
    graphics.build(plan_id)
    graphics.build(plan_id, force=True)                                                              # a second attempt for each
    st = graphics.state(plan_id)
    assert st["total"] == 2 and st["fallbacks"] == 1
    res = graphics.approve_all(plan_id)
    assert res["approved"] == 1 and len(res["left"]) == 1 and "only one number" in res["left"][0]["why"]
    assert sum(1 for i in store.items(plan_id, graphics.KIND) if i["approved"]) == 1
    res2 = graphics.approve_all(plan_id, include_fallbacks=True)
    assert res2["approved"] == 1 and res2["state"]["done"]
    a, b = [i for i in store.items(plan_id, graphics.KIND, scs[0]["id"]) if i["status"] == "done"]
    graphics.approve(a["id"])
    graphics.approve(b["id"])
    assert not store.get(a["id"])["approved"] and store.get(b["id"])["approved"]
    graphics.approve(b["id"], False)
    assert not store.get(b["id"])["approved"]


def test_graphics_do_not_make_an_approved_plan_look_changed(env, monkeypatch):
    plan_id = exported(env)
    imgplan.compile_plan(plan_id)
    first = storyboard.get_scenes(plan_id)[0]
    monkeypatch.setattr(graphics, "graphic_scenes", lambda pid: [first])                          # keeps the plan valid: only the card is built
    editorial.approve(plan_id)
    h = editorial.content_hash(planner.get_plan(plan_id))
    monkeypatch.setattr(graphics, "facts_ctx", lambda plan: ctx())
    graphics.build(plan_id)
    graphics.approve_all(plan_id, include_fallbacks=True)
    assert editorial.content_hash(planner.get_plan(plan_id)) == h
    assert editorial.approval_state(planner.get_plan(plan_id))["state"] == "approved"


def test_build_needs_a_storyboard():
    import config
    from story2 import planner as pl
    with pytest.raises(Exception):
        graphics.build("pl-none")


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
        r = c.post(f"/api/media/{plan['id']}/graphics", json={})
        assert r.status_code == 400 and "storyboard" in r.json()["detail"]
        g = c.get(f"/api/media/{plan['id']}").json()["graphics"]
        assert g["total"] == 0 and not g["done"]
        assert c.post(f"/api/media/{plan['id']}/graphics/approve-all", json={}).json()["approved"] == 0
