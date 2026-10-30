"""Shorts with a cast from the Character Studio library: the planner receives the cast, the start pictures are image edits from the characters' canon pictures, checks, staleness, fixes."""
import pytest

from characters import store as cstore, studio
from characters_fakes import SLOTS
from shorts_fakes import FakeChat, png_bytes
from story3 import store as media
from test_shorts import S, gw, new_short, run  # noqa: F401 - fixtures

from shorts import cast, checks, clips, planner, pipelines as P, stills, store


def make_char(name="Raju", kind="person", slots=None, canon=True):
    c = cstore.create(name, kind, slots or (SLOTS if kind == "person" else {"type": "railway platform at dusk", "light": "warm lamps"}))
    if canon:
        for view in cstore.CANON_VIEWS[kind]:
            it = media.add(c["id"], cstore.GEN, view, 0, "running", {"identity_hash": cstore.identity_hash(c)})
            (cstore.media_dir(c["id"], cstore.GEN) / f"{view}.png").write_bytes(png_bytes(72, 128))
            media.update(it["id"], status="done", file=f"{cstore.GEN}/{view}.png")
            studio.set_canon(c["id"], it["id"])
    return cstore.get(c["id"])


def with_cast(*chars, place=None):
    s = new_short("keyframe", cast=[{"character_id": c["id"], "look_id": ""} for c in chars], place_id=place["id"] if place else "")
    return run(planner.make_plan(s["id"], FakeChat(), S))


def test_the_plan_is_written_for_the_cast_and_shots_name_who_is_in_them(gw):
    raju, plat = make_char(), make_char("Platform", "place")
    short = with_cast(raju, place=plat)
    assert "Raju" in short["plan"]["character"] and "mustard yellow" in short["plan"]["character"] and "ailway platform" in short["plan"]["place"]
    assert "Photograph taken with an 85mm lens" in short["plan"]["look"], "the look comes from the character's render style, not from the model"
    with_char = [sh for sh in short["shots"] if sh["character"]]
    assert with_char and all(sh["cast"] == [raju["id"]] for sh in with_char) and all(not sh["cast"] for sh in short["shots"] if not sh["character"])


def test_start_pictures_with_a_cast_are_edits_from_the_canon_and_the_rest_are_drawn(gw):
    raju, plat = make_char(), make_char("Platform", "place")
    short = with_cast(raju, place=plat)
    res = run(clips.make_keyframes(short["id"], s=S, key="k"))
    n_cast = sum(1 for sh in short["shots"] if sh["cast"])
    assert res["made"] == len(short["shots"]) and not res["failed"] and len(gw.pic_edits) == n_cast and len(gw.images) == len(short["shots"]) - n_cast
    e = gw.pic_edits[0]
    assert e["images"] == 3 and "Picture 1 shows Raju (face)" in e["prompt"] and "Picture 2 shows Raju (whole body)" in e["prompt"] and "Picture 3 shows the place" in e["prompt"] and e["size"] == "720x1280"
    assert "keeps exactly the face, hair, skin tone, build and clothes" in e["prompt"]


def test_two_people_use_their_bodies_and_the_place_and_a_look_replaces_the_body(gw):
    a, b, plat = make_char("Raju"), make_char("Meera", slots={**SLOTS, "gender": "woman", "hair": "long black plait"}), make_char("Platform", "place")
    short = with_cast(a, b, place=plat)
    sh = dict(short["shots"][0], cast=[a["id"], b["id"]])
    refs = cast.refs_for(short, sh)
    assert [w[0] for w in refs["who"]] == ["Raju", "Meera"] and len(refs["pics"]) == 3 and refs["place"] is True
    assert cast.refs_for(short, dict(sh, setting="a rooftop")) ["place"] is False, "a shot with its own setting does not use the place picture"
    assert cast.refs_for(short, dict(sh, cast=[])) is None


def test_the_checks_block_a_cast_without_canon_or_with_too_many_people(gw):
    ok, bare = make_char(), make_char("Bare", canon=False)
    short = with_cast(ok)
    assert not [i for i in checks.run(short)["issues"] if i["code"] == "cast"]
    short["settings"]["cast"].append({"character_id": bare["id"], "look_id": ""})
    store.save(short)
    codes = [i["text"] for i in checks.run(store.get(short["id"]))["issues"] if i["code"] == "cast"]
    assert any("Bare" in t for t in codes)
    short = store.get(short["id"])
    short["settings"]["cast"] = [{"character_id": x["id"], "look_id": ""} for x in (ok, make_char("B"), make_char("C"))]
    store.save(short)
    assert any("at most 2" in i["text"] for i in checks.run(store.get(short["id"]))["issues"] if i["code"] == "cast")


def test_a_new_canon_makes_the_start_picture_old_and_a_fix_counts_as_current(gw):
    raju = make_char()
    short = with_cast(raju)
    run(clips.make_keyframes(short["id"], s=S, key="k"))
    short = store.get(short["id"])
    sh = next(x for x in short["shots"] if x["cast"])
    assert clips.chosen_keyframe(short, sh)
    run(clips.fix_keyframe(short["id"], sh["id"], "make his jacket red", s=S, key="k"))
    short = store.get(short["id"])
    fixed = clips.chosen_keyframe(short, sh)
    assert fixed["meta"]["source"] == "fix" and len(media.items(short["id"], store.KEY, sh["id"])) == 2 and "jacket red" in gw.pic_edits[-1]["prompt"] and gw.pic_edits[-1]["images"] == 1
    body = cstore.canon_items(raju)["body"]
    studio.set_canon(raju["id"], body["id"])                        # the same picture approved again changes nothing...
    assert clips.chosen_keyframe(store.get(short["id"]), sh)
    other = media.add(raju["id"], cstore.GEN, "body", 0, "running", {})
    (cstore.media_dir(raju["id"], cstore.GEN) / "b2.png").write_bytes(png_bytes(72, 128))
    media.update(other["id"], status="done", file=f"{cstore.GEN}/b2.png")
    studio.set_canon(raju["id"], other["id"])                       # ...a different canon bumps the version, so the picture made from the old one is old
    assert not clips.chosen_keyframe(store.get(short["id"]), sh)


def test_a_library_character_can_be_the_short_picture_and_settings_are_validated(gw):
    from fastapi.testclient import TestClient
    import main
    import config
    with TestClient(main.app) as c:                       # the app opens its own database, so the character is made after it started
        c.post("/login", data={"username": config.APP_USER, "password": config.APP_PASSWORD})
        raju = make_char()
        sid = c.post("/api/shorts", json={"pipeline": "remix", "kind": "idea", "text": ""}).json()["id"]
        assert c.patch(f"/api/shorts/{sid}/settings", json={"cast": [{"character_id": "ch-nope"}]}).status_code == 400
        assert c.patch(f"/api/shorts/{sid}/settings", json={"place_id": raju["id"]}).status_code == 400, "a person is not a place"
        st = c.patch(f"/api/shorts/{sid}/settings", json={"cast": [{"character_id": raju["id"]}]}).json()
        assert st["settings"]["cast"][0]["character_id"] == raju["id"]
        st = c.post(f"/api/shorts/{sid}/images/anchor/character", json={"character_id": raju["id"], "view": "portrait"}).json()
        assert st["images"]["anchor"].startswith("upload/anchor-") and st["settings"]["image_mode"] == "anchor"
