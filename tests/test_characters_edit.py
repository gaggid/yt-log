"""Character Studio C2 / C3: edits, try-on (a worn garment must not carry the model across), the character in a place, the strict check, looks, the matrix, and the API."""
import pytest

from characters_fakes import SLOTS, ImageGateway
from shorts_fakes import png_bytes
from story3 import store as media

from characters import check, edits, requests as R, store, studio, studio_edit, wardrobe
from test_characters import S, client, draw_canon, gw, new, run, wait_job  # noqa: F401 - fixtures


def test_an_edit_keeps_the_source_look_sends_no_lora_and_counts_the_chain(gw):
    c = draw_canon(new()["id"])
    base = store.canon_items(c)["body"]
    run(studio_edit.make_edit(c["id"], base["id"], "outfit", "a dark green kurta and beige trousers", s=S, key="k", do_check=False))
    first = media.items(c["id"], store.EDIT)[0]
    e = gw.edits[-1]
    assert "Change only the clothes of the person to: a dark green kurta" in e["prompt"] and "Keep exactly the same person" in e["prompt"] and "lora" not in e["fields"] and first["meta"]["depth"] == 1
    run(studio_edit.make_edit(c["id"], first["id"], "expression", "a wide laugh", s=S, key="k", do_check=False))
    second = media.items(c["id"], store.EDIT)[1]
    assert second["meta"]["depth"] == 2 and second["meta"]["parent"] == first["id"]
    with pytest.raises(store.CharError):
        edits.edit_text("outfit", "")


def test_a_worn_garment_gets_the_strong_wording_and_a_flat_lay_removes_the_model_entirely(gw):
    c = draw_canon(new()["id"])
    base = store.canon_items(c)["body"]
    g = wardrobe.add(png_bytes(), "Sherwani on a model", "licensed", ["wedding"], worn=True)
    run(studio_edit.make_edit(c["id"], base["id"], "outfit", "", garment_id=g["id"], scope="top", s=S, key="k", do_check=False))
    e = gw.edits[-1]
    assert e["images"] == 2 and "Copy ONLY the clothing" in e["prompt"] and "Never copy the model" in e["prompt"] and "top (shirt, jacket, kurta)" in e["prompt"] and "Keep the other clothes" in e["prompt"]
    run(studio_edit.make_flatlay(g["id"], s=S, key="k"))
    assert "No person, no mannequin" in gw.edits[-1]["prompt"]
    flat = [x for x in wardrobe.listing() if x["source"] == g["id"]]
    assert len(flat) == 1 and not flat[0]["worn"]
    assert wardrobe.usable(g["id"])["id"] == flat[0]["id"] and wardrobe.usable(g["id"])["worn"] is False
    run(studio_edit.make_edit(c["id"], base["id"], "outfit", "", garment_id=g["id"], s=S, key="k", do_check=False))
    last = gw.edits[-1]["prompt"]
    assert "Dress the person from the first picture" in last and "Copy ONLY the clothing" not in last, "the flat lay has no person, so no worn-photo wording is needed"
    with pytest.raises(store.CharError):
        wardrobe.add(png_bytes(), "x", "stolen")


def test_the_character_in_a_place_uses_three_references(gw):
    c = draw_canon(new()["id"])
    place = store.create("Platform", "place", {"type": "railway platform at dusk"})
    with pytest.raises(store.CharError, match="approve a picture"):
        run(studio_edit.make_place(c["id"], place["id"], "leaning on a pillar", s=S, key="k"))
    run(studio.make_views(place["id"], ["place"], 1, s=S, key="k"))
    studio.set_canon(place["id"], media.items(place["id"], store.GEN, "place")[0]["id"])
    run(studio_edit.make_place(c["id"], place["id"], "leaning on a steel pillar", s=S, key="k", do_check=False))
    e = gw.edits[-1]
    assert e["images"] == 3 and "leaning on a steel pillar" in e["prompt"] and "the last picture is the place" in e["prompt"]
    assert media.items(c["id"], store.EDIT)[-1]["meta"]["op"] == "place"


def test_the_check_is_strict_one_wrong_feature_cannot_hide_behind_good_ones():
    good = {k: 9 for k in check.FEATURES}
    assert check.overall(good) == 9.0
    drift = {**good, "hair": 3, "facial_hair": 4}
    assert check.overall(drift) < check.PASS_AT, "other hair and a fuller beard must fail even when the rest matches"


def test_the_check_scores_a_picture_against_the_canon_and_is_stored_on_it(env, monkeypatch):
    g = ImageGateway(check_scores={**{k: 9 for k in check.FEATURES}, "hair": 3, "facial_hair": 4}).install(monkeypatch)
    c = draw_canon(new()["id"])
    base = store.canon_items(c)["body"]
    run(studio_edit.make_edit(c["id"], base["id"], "pose", "walking away, glancing back", s=S, key="k"))
    it = media.items(c["id"], store.EDIT)[0]
    assert it["meta"]["check"]["ok"] is False and it["meta"]["check"]["score"] < 7
    sent = g.checks[-1]["messages"][0]["content"]
    assert "Written description of the character" in sent[0]["text"] and sum(1 for x in sent if x["type"] == "image_url") == 3, "portrait, body and the picture checked"


def test_a_picture_can_be_kept_saved_as_a_look_and_promoted_to_canon(gw):
    c = draw_canon(new()["id"])
    base = store.canon_items(c)["body"]
    run(studio_edit.make_edit(c["id"], base["id"], "outfit", "a navy blazer", s=S, key="k", do_check=False))
    run(studio_edit.make_edit(c["id"], base["id"], "outfit", "a red hoodie", s=S, key="k", do_check=False))
    a, b = media.items(c["id"], store.EDIT)
    studio_edit.keep(c["id"], a["id"])
    studio_edit.keep(c["id"], b["id"])
    assert media.get(a["id"])["meta"]["kept"] and media.get(b["id"])["meta"]["kept"], "keeping one does not un-keep the others"
    c = studio_edit.save_look(c["id"], a["id"], "Office")
    assert c["looks"][0]["name"] == "Office" and c["looks"][0]["recipe"]["value"] == "a navy blazer"
    v = c["version"]
    c = studio_edit.set_canon_view(c["id"], a["id"], "body")
    assert c["version"] == v + 1 and c["canon"]["body"] == a["id"] and studio_edit.look_item(c, c["looks"][0]["id"])["id"] == a["id"]
    with pytest.raises(store.CharError):
        studio_edit.save_look(c["id"], store.canon_items(c)["portrait"]["id"], "x")


def test_the_matrix_makes_one_picture_per_look_and_expression_and_is_capped(gw):
    c = draw_canon(new()["id"])
    res = run(studio_edit.make_matrix(c["id"], [], ["smile", "angry"], s=S, key="k"))
    assert res["made"] == 2 and all("expression" in e["prompt"].lower() for e in gw.edits)
    with pytest.raises(store.CharError, match="at most"):
        run(studio_edit.make_matrix(c["id"], [], list(R.EXPRESSIONS) * 3, s=S, key="k"))


def test_api_edit_preview_wardrobe_look_and_check(client):
    cid = client.post("/api/characters", json={"name": "Raju", "kind": "person", "idea": "a courier", "slots": SLOTS}).json()["id"]
    for v in ("portrait", "body"):
        client.post(f"/api/characters/{cid}/generate", json={"views": [v], "n": 1})
        wait_job(client, cid)
    st = client.get(f"/api/characters/{cid}").json()
    for v in ("portrait", "body"):
        client.post(f"/api/characters/item/{st['gallery'][v][0]['id']}/canon")
    base = st["gallery"]["body"][0]["id"]
    pv = client.post(f"/api/characters/{cid}/edit/preview", json={"base": base, "preset": "outfit", "value": "a navy blazer"}).json()
    assert "navy blazer" in pv["prompt"] and pv["refs"] == [base] and pv["depth"] == 1
    assert client.post(f"/api/characters/{cid}/edit", json={"base": base, "preset": "outfit", "value": ""}).status_code == 400
    bad = client.post("/api/characters/wardrobe", files={"file": ("g.png", png_bytes(), "image/png")}, data={"name": "x", "basis": "own", "confirmed": "false"})
    assert bad.status_code == 400
    g = client.post("/api/characters/wardrobe", files={"file": ("g.png", png_bytes(), "image/png")}, data={"name": "Sherwani", "basis": "licensed", "confirmed": "true", "worn": "true"}).json()
    assert g["worn"] is True and client.get(g["url"]).status_code == 200 and client.get("/api/characters/wardrobe").json()[0]["name"] == "Sherwani"
    assert client.post(f"/api/characters/{cid}/edit", json={"base": base, "garment": g["id"], "scope": "top"}).status_code == 200
    assert wait_job(client, cid)["state"] == "done"
    st = client.get(f"/api/characters/{cid}").json()
    pic = st["gallery"]["edit"][0]
    assert pic["op"] == "tryon" and pic["check"]["ok"] is True and pic["depth"] == 1
    st = client.post(f"/api/characters/item/{pic['id']}/look", json={"name": "Wedding"}).json()
    assert st["looks"][0]["name"] == "Wedding" and st["looks"][0]["stale"] is False
    assert client.post(f"/api/characters/item/{pic['id']}/check").status_code == 200
    assert client.post(f"/api/characters/item/{pic['id']}/canon/body").json()["version"] == st["version"] + 1
    assert client.delete(f"/api/characters/wardrobe/{g['id']}").status_code == 200 and client.get("/api/characters/wardrobe").json() == []
