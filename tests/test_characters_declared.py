"""The facts only the person decides (ethnicity, gender, age, skin tone, build; a place's region), the reel-worthy and realistic instruction to the chat model, and preset-or-custom choices."""
import pytest

from characters_fakes import SLOTS, SlotsChat
from story3 import store as media  # noqa: F401
from test_characters import S, client, gw, new, run  # noqa: F401 - fixtures

from characters import choices, requests as R, store, studio

DECL = {"ethnicity": "Tamil", "gender": "female", "age": "26", "skin": "wheatish", "build": "slim"}


def test_declared_facts_are_cleaned_and_a_gender_other_than_male_or_female_is_refused():
    assert store.clean_declared("person", {**DECL, "extra": "x", "age": " 26 "}) == DECL
    with pytest.raises(store.CharError):
        store.clean_declared("person", {"gender": "robot"})
    with pytest.raises(store.CharError):
        store.clean_declared("person", {"age": "young"})
    assert store.clean_declared("place", {"ethnicity": "Kerala", "age": "5"}) == {"ethnicity": "Kerala"}


def test_the_model_cannot_change_what_the_person_declared(gw):
    chat = SlotsChat()                                              # answers a man of 30 with other skin and build
    out = run(studio.suggest_slots("a reel creator", "person", chat, S, None, DECL))
    assert out["slots"]["gender"] == "woman" and out["slots"]["age"] == "26" and out["slots"]["skin"] == "wheatish" and out["slots"]["build"] == "slim" and out["slots"]["ethnicity"] == "Tamil"
    assert out["slots"]["hair"] == SLOTS["hair"], "what was not declared is written by the model"
    teen = run(studio.suggest_slots("a student", "person", SlotsChat(), S, None, {**DECL, "age": "15", "gender": "male"}))
    assert teen["slots"]["gender"] == "boy"


def test_the_instruction_asks_for_reel_worthy_realistic_work_styled_for_the_declared_ethnicity(gw):
    chat = SlotsChat()
    run(studio.suggest_slots("a reel creator", "person", chat, S, None, DECL))
    system = chat.systems[-1]
    assert "Instagram-reel-worthy" in system and "FIXED BY THE PRODUCER" in system and "ethnicity: Tamil" in system and "gender (male or female): female" in system and "skin tone: wheatish" in system
    assert "culturally authentic styling for this ethnicity" in system and "No caricature" in system and "Realistic, not fantasy" in system
    chat2 = SlotsChat()
    run(studio.suggest_slots("a rooftop", "place", chat2, S, None, {"ethnicity": "Mumbai"}))
    s2 = chat2.systems[-1]
    assert "real, lived-in, photographable location" in s2 and "ethnicity: Mumbai" in s2 and "No fantasy" in s2


def test_a_place_draws_in_its_declared_region(gw):
    p = store.create("Lane", "place", {"type": "narrow old-city lane"}, {"declared": {"ethnicity": "Rajasthan"}})
    assert "A location in Rajasthan." in R.build(p, "place", 1)["body"]["prompt"]


def test_api_refuses_the_model_until_everything_is_declared_and_keeps_what_the_person_chose(client):
    cid = client.post("/api/characters", json={"kind": "person", "idea": "a reel creator", "declared": {"gender": "female", "age": "26"}}).json()["id"]
    r = client.post(f"/api/characters/{cid}/suggest", json={})
    assert r.status_code == 400 and "ethnicity" in r.json()["detail"] and "skin tone" in r.json()["detail"] and "build" in r.json()["detail"]
    assert client.patch(f"/api/characters/{cid}", json={"declared": {"gender": "robot"}}).status_code == 400
    st = client.patch(f"/api/characters/{cid}", json={"declared": DECL}).json()
    assert st["declared"] == DECL and st["slots"]["gender"] == "woman" and [k["key"] for k in st["declared_keys"]] == ["ethnicity", "gender", "age", "skin", "build"]
    client.patch(f"/api/characters/{cid}", json={"slots": {**st["slots"], "hair": "bald with a neat beard"}})
    kept = client.post(f"/api/characters/{cid}/suggest", json={}).json()
    assert kept["slots"]["hair"] == "bald with a neat beard" and kept["slots"]["top"].startswith("mustard"), "chosen details stay, empty ones are written"
    again = client.post(f"/api/characters/{cid}/suggest", json={"keep": False}).json()
    assert again["slots"]["hair"] == SLOTS["hair"] and again["declared"] == DECL and again["slots"]["skin"] == "wheatish"


def test_every_characteristic_has_a_preset_list_and_free_text_is_accepted(client):
    o = client.get("/api/characters/options").json()
    ch = o["choices"]
    assert set(k for k, _ in __import__("story2.describe", fromlist=["SLOTS"]).SLOTS["person"]) <= set(ch["person"]) and "Indian (Punjabi)" in ch["person"]["ethnicity"] and ch["person"]["gender"] == ["male", "female"]
    assert {"type", "light", "size", "materials", "ethnicity"} <= set(ch["place"]) and len(choices.PERSON["hair"]) >= 8
    cid = client.post("/api/characters", json={"kind": "person", "idea": "x", "declared": DECL}).json()["id"]
    st = client.patch(f"/api/characters/{cid}", json={"slots": {"hair": "a custom electric-blue mohawk"}}).json()
    assert st["slots"]["hair"] == "a custom electric-blue mohawk"
