"""Character Studio C1 (docs/PLAN_characters.md): the library, the render lock, drawing, canon, the sheet, slots from an idea, and the API."""
import asyncio
import time

import pytest
from fastapi.testclient import TestClient

import config
from characters_fakes import SLOTS, ImageGateway, SlotsChat
from shorts_fakes import png_bytes
from story import settings as settings_mod
from story3 import store as media

from characters import render, requests as R, store, studio

S = {**settings_mod.DEFAULTS, "base_url": "http://gw/v1", "retry_backoff_s": 0}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def gw(env, monkeypatch):
    return ImageGateway().install(monkeypatch)


def new(**kw):
    return store.create("Raju", "person", SLOTS, kw or None)


def draw_canon(cid):
    run(studio.make_views(cid, ["portrait", "body"], 1, s=S, key="k"))
    for v in ("portrait", "body"):
        studio.set_canon(cid, media.items(cid, store.GEN, v)[-1]["id"])
    return store.get(cid)


def test_a_new_character_defaults_to_photographic_realism_with_the_lora(env):
    c = new()
    assert c["render"] == {"style": "photoreal", "model": "qwen-image-2.1", "loras": [{"name": "purelens-realism", "strength": 0.7}]} and c["status"] == "draft"
    assert render.clean({"style": "gta"})["loras"] == [] and len(render.clean({"loras": [{"name": f"l{i}"} for i in range(6)]})["loras"]) == 4


def test_the_draw_request_puts_the_trigger_word_first_and_sends_the_lora(gw):
    c = new()
    req = R.build(c, "portrait", 1, {"purelens-realism": {"trigger": "p3r4l4ns"}})
    p = req["body"]["prompt"]
    assert p.startswith("p3r4l4ns Head and shoulders portrait") and "Indian man" in p and "mustard yellow" in p and "Photograph taken with an 85mm lens" in p and "No text" in p
    assert req["body"]["lora"] == [{"name": "purelens-realism", "strength": 0.7}] and req["how"] == "draw" and req["body"]["size"] == "1024x1024"
    painted = store.create("P", "person", SLOTS, {"render": {"style": "filmic"}})
    assert "lora" not in R.build(painted, "body", 1)["body"]


def test_drawing_saves_numbered_attempts_and_records_the_recipe(gw):
    c = new()
    res = run(studio.make_views(c["id"], ["portrait"], 2, s=S, key="k"))
    assert res["made"] == 2 and not res["failed"] and len(gw.draws) == 2
    its = media.items(c["id"], store.GEN, "portrait")
    assert [i["attempt"] for i in its] == [1, 2] and all(i["status"] == "done" and (store.media_dir(c["id"]) / i["file"]).is_file() for i in its)
    assert its[0]["meta"]["seed"] != its[1]["meta"]["seed"] and its[0]["meta"]["identity_hash"] == store.identity_hash(c) and its[0]["meta"]["loras"]


def test_canon_bumps_the_version_locks_the_look_and_a_changed_description_marks_pictures_older(gw):
    c = new()
    run(studio.make_views(c["id"], ["portrait", "body"], 1, s=S, key="k"))
    studio.set_canon(c["id"], media.items(c["id"], store.GEN, "portrait")[0]["id"])
    c = store.get(c["id"])
    assert c["version"] == 2 and store.locked(c) and c["status"] == "draft"
    studio.set_canon(c["id"], media.items(c["id"], store.GEN, "body")[0]["id"])
    c = store.get(c["id"])
    assert c["status"] == "ready" and c["version"] == 3
    before = store.identity_hash(c)
    c["slots"]["hair"] = "shaved head"
    assert store.identity_hash(c) != before


def test_the_sheet_is_made_from_the_canon_by_edit_with_two_references(gw):
    c = new()
    with pytest.raises(store.CharError):
        R.build(c, "side", 1)
    c = draw_canon(c["id"])
    res = run(studio.make_views(c["id"], list(R.SHEET_VIEWS), 1, s=S, key="k"))
    assert res["made"] == len(R.SHEET_VIEWS) and not res["failed"]
    side = next(e for e in gw.edits if "side view" in e["prompt"])
    assert side["images"] == 2 and "Keep exactly the same person" in side["prompt"] and side["fields"]["size"] == "720x1280"
    expr = next(e for e in gw.edits if "laugh" in e["prompt"])
    assert expr["images"] == 1 and expr["fields"]["size"] == "1024x1024"
    assert len(media.items(c["id"], store.SHEET)) == len(R.SHEET_VIEWS)


def test_a_failed_picture_is_recorded_and_the_rest_go_on(env, monkeypatch):
    g = ImageGateway(fail_edits=True).install(monkeypatch)
    c = draw_canon(new()["id"])
    res = run(studio.make_views(c["id"], ["side", "back"], 1, s=S, key="k"))
    assert res["made"] == 0 and len(res["failed"]) == 2 and all(i["status"] == "failed" for i in media.items(c["id"], store.SHEET))
    assert g.draws


def test_an_unlisted_lora_is_refused_before_anything_is_drawn(gw):
    c = new(render={"loras": [{"name": "no-such-lora", "strength": 0.5}]})
    with pytest.raises(store.CharError, match="no-such-lora"):
        run(studio.make_views(c["id"], ["portrait"], 1, s=S, key="k"))
    assert not gw.draws


def test_slots_from_an_idea_are_sent_back_when_vague_and_keep_what_the_person_wrote(gw):
    chat = SlotsChat(vague_first=True)
    out = run(studio.suggest_slots("a tired courier", "person", chat, S, {"hair": "shaved head"}))
    assert len(chat.calls) >= 2 and not out["gaps"] and out["slots"]["hair"] == "shaved head" and out["slots"]["top"].startswith("mustard") and out["name"] == "Raju"


def test_a_place_has_only_a_place_view(gw):
    place = store.create("Platform", "place", {"type": "railway platform at dusk"})
    with pytest.raises(store.CharError):
        R.build(place, "portrait", 1)
    assert R.build(place, "place", 1)["body"]["size"] == "1280x720"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    import main
    from characters import api
    g = ImageGateway().install(monkeypatch)
    monkeypatch.setattr(api, "_backend", lambda: ({**settings_mod.get(), "retry_backoff_s": 0}, SlotsChat()))
    monkeypatch.setattr(api.providers, "refresh", lambda s, k, ttl=60.0: [])
    with TestClient(main.app) as c:
        c.post("/login", data={"username": config.APP_USER, "password": config.APP_PASSWORD})
        c.gw = g
        yield c


def wait_job(c, cid, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = c.get(f"/api/characters/{cid}/job").json()
        if j.get("state") in ("done", "error", "cancelled"):
            return j
        time.sleep(0.05)
    raise AssertionError("job timed out")


def test_api_library_idea_draw_canon_lock_and_photo_rights(client):
    o = client.get("/api/characters/options").json()
    assert o["default_render"]["loras"][0]["name"] == "purelens-realism" and "portrait" in o["views"]
    assert any(x["name"] == "purelens-realism" and x["trigger"] == "p3r4l4ns" for x in o["loras"]["qwen-image-2.1"])
    cid = client.post("/api/characters", json={"name": "", "kind": "person", "idea": "a tired courier in a yellow jacket", "declared": {"ethnicity": "Indian (Punjabi)", "gender": "male", "age": "30", "skin": "wheatish", "build": "lean and athletic"}}).json()["id"]
    st = client.post(f"/api/characters/{cid}/suggest", json={}).json()
    assert st["name"] == "Raju" and not st["gaps"] and st["slots"]["hair"] == SLOTS["hair"] and "Indian (Punjabi) man" in st["identity"] and st["slots"]["skin"] == "wheatish"
    assert client.post(f"/api/characters/{cid}/generate", json={"views": ["body"], "n": 1}).status_code == 200
    assert wait_job(client, cid)["state"] == "done"
    assert client.post(f"/api/characters/{cid}/generate", json={"views": ["portrait"], "n": 1}).status_code == 200
    wait_job(client, cid)
    st = client.get(f"/api/characters/{cid}").json()
    assert len(st["gallery"]["body"]) == 1 and st["gallery"]["portrait"][0]["current"] and st["gallery"]["portrait"][0]["url"].startswith("/api/characters/file/")
    assert client.get(st["gallery"]["portrait"][0]["url"]).status_code == 200
    assert client.post(f"/api/characters/{cid}/sheet").status_code == 400, "no canon yet"
    for v in ("portrait", "body"):
        assert client.post(f"/api/characters/item/{st['gallery'][v][0]['id']}/canon").status_code == 200
    st = client.get(f"/api/characters/{cid}").json()
    assert st["status"] == "ready" and st["locked"] and st["canon"]["portrait"]
    assert client.patch(f"/api/characters/{cid}", json={"render": {"style": "gta"}}).status_code == 400, "the look is locked"
    assert client.patch(f"/api/characters/{cid}", json={"name": "Raju Bhai", "tags": ["courier"]}).json()["name"] == "Raju Bhai"
    assert client.post(f"/api/characters/{cid}/sheet").status_code == 200 and wait_job(client, cid)["state"] == "done"
    st = client.get(f"/api/characters/{cid}").json()
    assert len(st["gallery"]["side"]) == 1 and client.get("/api/characters").json()[0]["thumb"]
    up = client.post(f"/api/characters/{cid}/photo", files={"file": ("p.png", png_bytes(), "image/png")}, data={"basis": "own", "confirmed": "false"})
    assert up.status_code == 400
    copy = client.post(f"/api/characters/{cid}/duplicate").json()
    assert copy["id"] != cid and not copy["locked"] and copy["slots"] == st["slots"] and not copy["canon"]
    assert client.delete(f"/api/characters/{cid}").status_code == 200 and client.get(f"/api/characters/{cid}").status_code == 404


def test_a_head_and_shoulders_portrait_leaves_out_what_the_frame_cannot_show_and_runs_at_35_steps(env):
    """Qwen draws every word it is given: trousers, flats, wrist jewellery and waist-length hair in a portrait made the face morph (Saira, 2026-10-30)."""
    slots = {**SLOTS, "bottom": "high-waisted wide-leg trousers in cream cotton", "footwear": "gold pointed-toe flats", "hair": "deep black, waist-length, soft waves",
             "accessories": "large gold hoop earrings and a stack of thin gold bangles on one wrist", "eyes": "dark brown, almond-shaped with thick lashes"}
    c = store.create("Saira", "person", slots)
    portrait = R.build(c, "portrait", 1)["body"]
    p = portrait["prompt"].lower()
    for gone in ("trousers", "flats", "bangles", "waist-length", "hoop earrings", "mood:"):
        assert gone not in p, gone
    assert "eyes: dark brown, almond-shaped with thick lashes" in p and "lashes eyes" not in p
    assert portrait["steps"] == 35
    body = R.build(c, "body", 1)["body"]["prompt"].lower()
    assert "trousers" in body and "gold pointed-toe flats" in body, "the full-body view shows the clothes"
    assert "bangles" not in body and "hoop earrings" not in body, "ornaments are added later by edit, the first pictures are a clean human"
    assert R.build(c, "portrait", 1)["meta"]["steps"] == 35


def test_glamour_styling_is_for_adult_invented_characters_only_and_keeps_the_picture_tasteful(env):
    from characters import choices
    c = store.create("Saira", "person", SLOTS, {"declared": {"age": "25"}, "styling": "glamour"})
    assert store.glamour_problem(c) == "" and R.GLAMOUR_LINE in R.build(c, "portrait", 1)["body"]["prompt"]
    assert "no nudity" in R.GLAMOUR_LINE and "fully clothed" in R.GLAMOUR_LINE
    minor = store.create("Kid", "person", SLOTS, {"declared": {"age": "17"}, "styling": "glamour"})
    assert "adult age" in store.glamour_problem(minor) and R.GLAMOUR_LINE not in R.build(minor, "portrait", 1)["body"]["prompt"], "never for under 21"
    noage = store.create("NoAge", "person", {k: v for k, v in SLOTS.items() if k != "age"}, {"styling": "glamour"})
    assert store.glamour_problem(noage), "an age must be declared"
    photo = store.create("Photo", "person", SLOTS, {"declared": {"age": "30"}, "styling": "glamour", "rights": {"basis": "own photo", "confirmed": True, "note": ""}})
    assert "photograph" in store.glamour_problem(photo), "never for a person drawn from a photo"
    assert all(o["styling"] in ("glamour", "") for o in choices.OUTFITS) and {o["gender"] for o in choices.OUTFITS if o["styling"] == "glamour"} == {"female", "male"}
    lowered = " ".join(o["top"] + o["bottom"] for o in choices.OUTFITS).lower()
    assert not any(w in lowered for w in ("nude", "naked", "lingerie", "topless", "underwear", "transparent")), "presets stay clothed"


def test_api_styling_is_refused_for_an_undeclared_or_young_age_and_allowed_for_an_adult(client):
    opts = client.get("/api/characters/options").json()
    assert [x["id"] for x in opts["styling"]] == ["", "glamour"] and any(o["styling"] == "glamour" for o in opts["outfits"])
    bad = client.post("/api/characters", json={"name": "A", "kind": "person", "styling": "glamour"})
    assert bad.status_code == 400 and "adult age" in bad.json()["detail"], "no age declared"
    ok = client.post("/api/characters", json={"name": "Saira", "kind": "person", "styling": "glamour", "declared": {"ethnicity": "Indian (Punjabi)", "gender": "female", "age": "25", "skin_tone": "fair", "build": "curvy"}})
    assert ok.status_code == 200 and ok.json()["styling"] == "glamour" and ok.json()["glamour_problem"] == ""
    cid = ok.json()["id"]
    young = client.patch(f"/api/characters/{cid}", json={"declared": {"ethnicity": "Indian (Punjabi)", "gender": "female", "age": "17", "skin_tone": "fair", "build": "curvy"}})
    assert young.status_code == 400 and "adult age" in young.json()["detail"], "lowering the age under 21 turns it down"
    assert client.patch(f"/api/characters/{cid}", json={"styling": "weird"}).status_code == 400


def test_a_detail_read_from_a_picture_becomes_text_in_the_matching_slots_and_the_picture_is_not_kept(client, monkeypatch):
    async def fake_read(path, aspect, s=None, key=""):
        assert aspect == "hair"
        return {"slots": {"hair": "black hair with soft brown and blonde streaks, shoulder-length"}, "aspect": aspect}
    monkeypatch.setattr(studio, "read_aspect", fake_read)
    cid = client.post("/api/characters", json={"name": "Saira", "kind": "person", "slots": {"hair": "black", "top": "white t-shirt"}}).json()["id"]
    r = client.post(f"/api/characters/{cid}/read-detail", files={"file": ("h.png", png_bytes(40, 40), "image/png")}, data={"aspect": "hair"})
    assert r.status_code == 200 and r.json()["slots"]["hair"].startswith("black hair with soft brown and blonde streaks") and r.json()["slots"]["top"] == "white t-shirt"
    assert not r.json()["photo"], "the reference picture is not stored or used as an image reference"
    assert client.post(f"/api/characters/{cid}/read-detail", files={"file": ("h.png", png_bytes(40, 40), "image/png")}, data={"aspect": "shoes"}).status_code == 400
