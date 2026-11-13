"""The scene review (shorts/review.py): the vision model describes each picture blind, code decides the defects and scores. The fixture is the audited short sh-16824387 with the
descriptions the real model gave of its 17 drawn pictures."""
import asyncio
import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import config
from shorts_fakes import FakeChat, VideoGateway, fake_speak_all
from story import llm, settings as settings_mod
from story3 import voice as voice3

from shorts import auto, clips, review, store

S = {**settings_mod.DEFAULTS, "base_url": "http://gw/v1", "retry_backoff_s": 0}
FX = json.loads((Path(__file__).parent / "fixtures" / "review_sh16824387.json").read_text(encoding="utf-8"))


def run(coro):
    return asyncio.run(coro)


def audit_short(**settings):
    """The audited short as it was stored before the storyboard check (a painted short)."""
    return {"id": "sh-x", "settings": {"scene_review": True, "visual_style": "filmic", **settings}, "plan": copy.deepcopy(FX["plan"]), "shots": copy.deepcopy(FX["shots"]), "beats": []}


def pictures_for(short, tmp_path):
    """One small picture per shot with its own colours and its own shapes, so the measured match between different shots is low and between a picture and its copy is 1."""
    from PIL import ImageDraw
    items = []
    for n, sh in enumerate(short["shots"]):
        p = tmp_path / f"{sh['id']}.png"
        im = Image.new("RGB", (72, 128), ((37 * n) % 256, (91 * n + 40) % 256, (53 * n + 100) % 256))
        d = ImageDraw.Draw(im)
        d.rectangle(((7 * n) % 40, (11 * n) % 70, (7 * n) % 40 + 25, (11 * n) % 70 + 40), fill=((131 * n + 90) % 256, (17 * n + 200) % 256, (29 * n) % 256))
        im.save(p)
        items.append((sh, {"id": f"md-{sh['id']}"}, p))
    return items


# ── the code decides the defects from the blind descriptions ───────────────────────────

def test_the_real_descriptions_give_the_defects_of_the_manual_audit():
    short = audit_short()
    got = {k: set() for k in ("extra_object", "wrong_place", "blank_background", "style_break", "text_in_picture")}
    for sh in short["shots"]:
        found, _notes = review.defects(short, sh, FX["seen"][sh["id"]])
        for d in found:
            got[d["kind"]].add(sh["id"])
    gold = FX["gold"]
    assert set(gold["extra_object"]) <= got["extra_object"] and got["extra_object"] - set(gold["extra_object"]) == {"s11"}, "all 9 stray money piles; s11 asks for the money but also shows a phone nobody asked for; s14 asks for the money and has no extra"
    assert set(gold["wrong_place"]) <= got["wrong_place"] and got["wrong_place"] - set(gold["wrong_place"]) <= {"s17"}, "all 6 wrong places (s17: a cottage drawn as a kitchen is the one extra)"
    assert set(gold["blank_or_style"]) <= got["blank_background"] | got["style_break"] and got["style_break"] == {"s12"} and got["blank_background"] == {"s10", "s12"}
    assert "s1" in got["text_in_picture"], "the gibberish text on the phone"
    assert not got["wrong_place"] & {"s1", "s3", "s4", "s5", "s6", "s7", "s9", "s12", "s15"}, "pictures that match their prompt are not flagged"


def test_a_crowd_or_a_near_count_is_a_note_never_a_defect():
    short = audit_short()
    s12 = next(sh for sh in short["shots"] if sh["id"] == "s12")
    found, notes = review.defects(short, s12, FX["seen"]["s12"])
    assert not [d for d in found if d["kind"] == "wrong_count"] and any("8 people" in n for n in notes)
    plain = {"id": "s1", "still": "Wide shot of two people standing in one kitchen.", "setting": "", "must_show": []}
    seen = {"place": "kitchen", "background": "a kitchen", "people_count": 5, "objects": [], "readable_text": "none", "style": "painted"}
    found, _ = review.defects(short, plain, seen)
    assert [d["kind"] for d in found] == ["wrong_count"], "five people where two were asked, in a kitchen"


def test_a_room_the_shot_never_asked_for_is_a_note_not_a_defect():
    short = audit_short()
    short["plan"]["place"] = "A modern, bright Indian living room with warm wooden furniture and soft daylight."
    desk = {"id": "s8", "still": "Wide shot of one young Indian office worker sitting at one wooden desk. She looks at one clock on the wall.", "setting": "", "must_show": []}
    seen = {"place": "office", "background": "a wall with a clock", "people_count": 1, "objects": ["desk", "clock"], "readable_text": "none", "style": "painted"}
    found, notes = review.defects(short, desk, seen)
    assert not [d for d in found if d["kind"] == "wrong_place"] and any("names no place" in n for n in notes), "an office for a desk scene in a living-room short"
    market = {**seen, "place": "market", "background": "a crowded market"}
    assert [d["kind"] for d in review.defects(short, desk, market)[0] if d["kind"] == "wrong_place"], "a market is still wrong: it is not a room of the home"
    named = {**desk, "still": "Wide shot of one worker in one bright living room."}
    assert [d["kind"] for d in review.defects(short, named, seen)[0] if d["kind"] == "wrong_place"], "when the shot names the living room itself an office is wrong"


def test_the_shot_label_of_the_contact_sheet_is_not_text_in_the_picture():
    short = audit_short()
    s15 = next(sh for sh in short["shots"] if sh["id"] == "s15")
    for label in ("s15", "S15", " s3 "):
        assert not [d for d in review.defects(short, s15, {**FX["seen"]["s15"], "readable_text": label})[0] if d["kind"] == "text_in_picture"], "a label printed by the sheet"
    assert [d for d in review.defects(short, s15, {**FX["seen"]["s15"], "readable_text": "SALE s15 50%"})[0] if d["kind"] == "text_in_picture"], "real text is still a defect"


def test_a_picture_that_matches_its_prompt_has_no_defect():
    short = audit_short()
    s15 = next(sh for sh in short["shots"] if sh["id"] == "s15")
    assert review.defects(short, s15, FX["seen"]["s15"]) == ([], [])


def test_the_style_check_follows_the_short_style():
    painted, photo = audit_short(visual_style="filmic"), audit_short(visual_style="realism")
    sh = painted["shots"][0]
    iso = {**FX["seen"]["s1"], "style": "isometric diorama", "readable_text": "none"}
    assert any(d["kind"] == "style_break" for d in review.defects(painted, sh, iso)[0])
    anime = {**FX["seen"]["s1"], "style": "painted", "readable_text": "none"}
    assert not any(d["kind"] == "style_break" for d in review.defects(painted, sh, anime)[0])
    assert any(d["kind"] == "style_break" for d in review.defects(photo, sh, anime)[0]), "a painting in a photographic short"


def test_a_3d_short_is_not_flagged_for_looking_3d():
    pixar = audit_short(visual_style="pixar3d")
    sh = pixar["shots"][0]
    for word in ("3d", "3d animation", "cartoon", "isometric diorama"):
        seen = {**FX["seen"]["s1"], "style": word, "readable_text": "none"}
        assert not any(d["kind"] == "style_break" for d in review.defects(pixar, sh, seen)[0]), word
    for word in ("photo", "painted watercolour"):
        seen = {**FX["seen"]["s1"], "style": word, "readable_text": "none"}
        assert any(d["kind"] == "style_break" for d in review.defects(pixar, sh, seen)[0]), word
    broken = [d for d in review.defects(pixar, sh, {**FX["seen"]["s1"], "style": "photo", "readable_text": "none"})[0] if d["kind"] == "style_break"]
    assert "Pixar" in broken[0]["text"]


# ── scores ──────────────────────────────────────────────────────────────────────────────

def test_repeat_compares_every_earlier_picture_and_names_the_closest(tmp_path):
    short = audit_short()
    items = pictures_for(short, tmp_path)
    import shutil
    same = tmp_path / "same.png"
    shutil.copy(items[1][2], same)                                                                           # a copy of the picture of s2
    items[15] = (items[15][0], items[15][1], same)                                                         # s16 is a copy of s2
    res = review.review_scenes(short, items, FX["seen"])
    r16 = res["scenes"]["s16"]["repeat"]
    assert r16["closest"] == "s2" and r16["measured"] > 0.95 and r16["score"] >= 8
    assert res["scenes"]["s1"]["repeat"] == {"score": 0, "closest": "", "measured": 0.0, "tags": 0.0, "duplicate": False}, "the first scene has nothing before it"
    assert res["scenes"]["s4"]["repeat"]["score"] < r16["score"]
    assert review.repeat_score(0.25) == 0 and review.repeat_score(0.8) == 10 and review.repeat_score(0.5) == 5


def test_the_same_place_and_things_match_in_the_descriptions():
    a, b, c = review.tags_of(FX["seen"]["s16"]), review.tags_of(FX["seen"]["s2"]), review.tags_of(FX["seen"]["s4"])
    assert review.tag_match(a, b) > review.tag_match(a, c) and a["place"] == b["place"] != "" and c["place"] == ""


def test_engagement_parts_and_the_first_three_seconds_count_double(tmp_path):
    short = audit_short()
    items = pictures_for(short, tmp_path)
    res = review.review_scenes(short, items, FX["seen"])
    s4, s2 = res["scenes"]["s4"], res["scenes"]["s2"]
    assert s4["parts"]["proof"] == 2 and s2["parts"]["proof"] == 0 and s2["engagement"] < s4["engagement"], "a wrong place and stray money cost the proof part"
    assert s4["parts"]["clean"] == 1, "the numbers on the key labels count as text"
    assert res["summary"]["engagement"] is not None and res["summary"]["reviewed"] == 17 and res["summary"]["defects"] > 15
    assert review.engagement({"read": 2, "pull": None, "proof": 2, "clean": 2, "move": None}) == 10.0, "a missing part is left out, not counted as zero"
    assert review.engagement({"read": None}) is None


def test_the_move_part_follows_the_motion_line():
    assert review.move_part({"move": "The man turns his whole head to the left. The camera pushes in until his face fills the frame."}, "pan") == (2, "push")
    assert review.move_part({"move": "The man turns his whole head. The camera remains static."}, "") == (1, "static")
    assert review.move_part({"move": "The soldier's chest rises and falls as he breathes. The camera pushes in."}, "pan")[0] == 1
    assert review.move_part({"move": "The man turns. The camera pushes in."}, "push")[0] == 1, "the same camera move as the shot before"
    assert review.move_part({}, "") == (None, "")


def test_the_soft_scores_are_left_out_when_the_model_gives_every_picture_the_same(tmp_path):
    short = audit_short()
    items = pictures_for(short, tmp_path)
    flat = {k: {**v, "read": 2, "pull": 1} for k, v in FX["seen"].items()}
    res = review.review_scenes(short, items, flat)
    assert res["soft_scores_flat"] is True and res["scenes"]["s4"]["parts"]["read"] is None and res["scenes"]["s4"]["parts"]["pull"] is None
    varied = review.review_scenes(short, items, {k: {**v, "read": n % 3, "pull": (n + 1) % 3} for n, (k, v) in enumerate(FX["seen"].items())})
    assert varied["soft_scores_flat"] is False


def test_the_three_low_floors():
    scenes = {f"s{i}": {"engagement": e, "repeat": {"duplicate": d}} for i, (e, d) in enumerate([(3.0, False), (6.0, False), (3.0, False), (2.0, False), (1.0, False), (7.0, False), (8.0, True)], 1)}
    order = list(scenes)
    got = {f["floor"]: f for f in review.floors(scenes, order)}
    assert set(got) == {"hook", "dead_stretch", "duplicate"} and got["dead_stretch"]["shots"] == ["s3", "s4", "s5"] and got["duplicate"]["shots"] == ["s7"]
    good = {f"s{i}": {"engagement": e, "repeat": {"duplicate": False}} for i, e in enumerate([6, 7, 3, 3, 6, 7], 1)}
    assert review.floors(good, list(good)) == [], "two low scenes in a row are fine"


# ── the model call ──────────────────────────────────────────────────────────────────────

def test_the_model_sees_labelled_sheets_and_never_the_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    short = audit_short()
    short["id"] = "sh-sheet"
    items = pictures_for(short, tmp_path)
    chat = FakeChat(review=True)
    seen = run(review.describe(short, items, chat, S))
    assert len(seen) == 17 and len([c for c in chat.calls if c["task"] == "p4_review"]) == 3, "17 pictures are 3 sheets of at most 6"
    assert all(c["images"] == 1 for c in chat.calls if c["task"] == "p4_review")
    text = " ".join(c["user"] + c["system"] for c in chat.calls if c["task"] == "p4_review")
    for sh in short["shots"]:
        assert sh["still"][:40] not in text, "the picture prompt is never sent with the sheet"
    assert (tmp_path / "media" / "sh-sheet" / "review" / "sheet-1.jpg").is_file()


def test_the_strict_json_schema_is_sent_to_the_gateway():
    sent = {}

    class Backend:
        async def complete(self, messages, max_tokens, params=None):
            sent["params"] = params
            from story.llm import LLMResult
            return LLMResult(json.dumps({"shots": [{"id": "s1", "place": "kitchen", "setting_type": "indoor", "people_count": 0, "objects": [], "readable_text": "none", "style": "painted", "background": "wall",
                                                     "shot_size": "wide", "arrangement": "x", "face_visible": False, "read": 1, "pull": 1}]}))
    res = run(llm.JsonCaller(Backend(), S).call(review.SYSTEM, "go", review.SeenOut, images=["data:image/jpeg;base64,AA"], response_format=review.RESPONSE_FORMAT))
    assert res.value.shots[0].place == "kitchen"
    rf = sent["params"]["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True and sent["params"]["temperature"] == 0
    assert "enum" not in json.dumps(rf), "no fixed-label lists: they made the model fall back to defaults"


def test_a_sheet_the_model_cannot_describe_is_left_out_not_fatal(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    short = audit_short()
    short["id"] = "sh-off"
    seen = run(review.describe(short, pictures_for(short, tmp_path), FakeChat(review=False), S))
    assert seen == {}


# ── wiring ───────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def gw(env, monkeypatch):
    g = VideoGateway(env).install(monkeypatch)
    monkeypatch.setattr(voice3, "_speak_all", fake_speak_all)
    return g


def drawn_short(gw, **settings):
    from shorts import planner
    s = store.create("T", "keyframe", {"kind": "idea", "text": "a courier finds a wallet", "candidate_id": "", "facts": ""}, settings)
    short = run(planner.make_plan(s["id"], FakeChat(), S))
    run(clips.make_keyframes(short["id"], s=S, key="k"))
    return store.get(short["id"])


def test_a_new_short_has_the_review_on_and_it_reads_the_drawn_pictures(gw):
    short = drawn_short(gw)
    assert short["settings"]["scene_review"] is True and review.ready(short) and not review.current(short)
    rep = run(review.run(short["id"], FakeChat(review=True), S))
    after = store.get(short["id"])
    assert review.current(after) and rep["summary"]["reviewed"] == len(short["shots"]) and rep["current"] is True
    assert set(after["review"]["scenes"]) == {sh["id"] for sh in short["shots"]}
    assert after["shots"] == short["shots"], "the review changes nothing"
    again = copy.deepcopy(after)
    again["shots"][0]["still"] += " One lamp on the left."
    assert not review.current(again), "a changed prompt makes the review stale"


def test_the_review_needs_pictures_and_a_short_made_before_it_is_left_alone(gw):
    from shorts import planner
    s = store.create("T", "keyframe", {"kind": "idea", "text": "a courier finds a wallet", "candidate_id": "", "facts": ""}, {})
    short = run(planner.make_plan(s["id"], FakeChat(), S))
    assert not review.ready(short) and review.report(short)["ready"] is False
    with pytest.raises(ValueError):
        run(review.run(short["id"], FakeChat(review=True), S))
    old = drawn_short(gw, scene_review=False)
    assert not review.enabled(old) and "scenes" not in [x["id"] for x in auto.steps(old)]
    assert review.report(old)["enabled"] is False


def test_auto_run_reviews_the_pictures_before_the_person_looks(gw, monkeypatch):
    short = drawn_short(gw)
    assert next(x for x in auto.steps(short) if x["id"] == "scenes")["done"] is False
    ids = [x["id"] for x in auto.steps(short)]
    assert ids.index("keyframes") < ids.index("scenes") < ids.index("review")
    monkeypatch.setattr(auto.svoice, "missing", lambda s: False)
    msgs = []
    out = run(auto.run(short["id"], FakeChat(review=True), S, lambda *a, **k: None))
    assert "picture review" in out and review.current(store.get(short["id"])), out
    assert next(x for x in auto.steps(store.get(short["id"])) if x["id"] == "scenes")["done"]


def test_a_failed_review_never_stops_auto_run(gw, monkeypatch):
    short = drawn_short(gw)
    monkeypatch.setattr(auto.svoice, "missing", lambda s: False)
    out = run(auto.run(short["id"], FakeChat(review=False), S, lambda *a, **k: None))
    assert "picture review skipped" in out and not review.current(store.get(short["id"]))


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    import main
    from shorts import api as shorts_api
    g = VideoGateway(tmp_path).install(monkeypatch)
    monkeypatch.setattr(voice3, "_speak_all", fake_speak_all)
    monkeypatch.setattr(shorts_api, "_backend", lambda: ({**settings_mod.get(), "retry_backoff_s": 0}, FakeChat(review=True)))
    with TestClient(main.app) as c:
        c.post("/login", data={"username": config.APP_USER, "password": config.APP_PASSWORD})
        yield c


def wait_job(c, sid, timeout=30):
    import time
    t0 = time.time()
    while time.time() - t0 < timeout:
        if c.get(f"/api/shorts/{sid}/job").json().get("state") in ("done", "error", "cancelled"):
            return c.get(f"/api/shorts/{sid}/job").json()
        time.sleep(0.05)
    raise AssertionError("the job did not finish")


def test_the_api_runs_the_review_and_the_state_shows_it(client, gw):
    short = drawn_short(gw)
    sid = short["id"]
    st = client.get(f"/api/shorts/{sid}").json()
    assert st["review"]["enabled"] is True and st["review"]["ready"] is True and st["review"]["at"] is None
    assert client.post(f"/api/shorts/{sid}/review", json={}).status_code in (200, 202)
    job = wait_job(client, sid)
    assert job["state"] == "done" and "Pictures reviewed" in str(job)
    after = client.get(f"/api/shorts/{sid}").json()["review"]
    assert after["current"] is True and after["summary"]["reviewed"] == len(short["shots"]) and set(after["order"]) == set(after["scenes"])


def test_the_api_refuses_without_pictures_or_while_off_and_switches_on(client, gw):
    from shorts import planner
    s = store.create("T", "keyframe", {"kind": "idea", "text": "a courier finds a wallet", "candidate_id": "", "facts": ""}, {})
    short = run(planner.make_plan(s["id"], FakeChat(), S))
    assert client.post(f"/api/shorts/{short['id']}/review", json={}).status_code == 400, "no pictures yet"
    old = drawn_short(gw, scene_review=False)
    assert client.post(f"/api/shorts/{old['id']}/review", json={}).status_code == 400, "off for this short"
    assert client.post(f"/api/shorts/{old['id']}/review", json={"enable": True}).status_code in (200, 202)
    wait_job(client, old["id"])
    assert store.get(old["id"])["settings"]["scene_review"] is True and review.current(store.get(old["id"]))
    assert client.patch(f"/api/shorts/{old['id']}/settings", json={"scene_review": False}).status_code == 200
    assert store.get(old["id"])["settings"]["scene_review"] is False
