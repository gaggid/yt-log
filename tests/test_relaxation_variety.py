"""Variety of the Rain Channel (owner, 2026-11-19: same lamp, same thumbnail, same text every time): the seeds (relaxation/looks.py), the art director that writes the
prompts and the upload text from them (relaxation/director.py, a fake model here) and the thumbnail layouts (relaxation/thumbrender.py)."""
import asyncio
import random
from types import SimpleNamespace

import pytest

from relaxation import director, looks, models as M, seo, store, thumbrender
from story import llm
from story3 import store as media


def test_every_theme_composes_a_valid_prompt_for_many_seeds():
    for scene in M.SCENES:
        for i in range(25):
            look = looks.pick_look(scene, [], random.Random(i))
            p = looks.compose_prompt(scene, look)
            assert looks.prompt_problems(scene, look, p) == [], (scene, look)
            assert p.startswith(M.WET.strip()[:20]) and p.rstrip().endswith("No people, no text, no logo.")


def test_the_same_theme_does_not_draw_the_same_lamp_light_and_camera_twice_in_a_row():
    hist = []
    seen = []
    for i in range(8):
        look = looks.pick_look("himalayan_ridge", hist, random.Random(i))
        seen.append(look)
        hist.insert(0, {"look": look})
    for a, b in zip(seen, seen[1:]):
        assert a["lamp"] != b["lamp"] and a["light"] != b["light"] and a["camera"] != b["camera"]
    assert len({(x["lamp"], x["side"]) for x in seen}) >= 4              # the lamp changes kind and side


def test_the_model_prompt_is_refused_when_it_drops_a_seed_or_puts_rain_in_the_air():
    look = {"light": "dusk", "lamp": "oil", "side": "left", "season": "monsoon", "air": "mist", "camera": "low", "grade": "teal", "thing": "cat", "flame": True}
    good = looks.compose_prompt("himalayan_ridge", look)
    assert looks.prompt_problems("himalayan_ridge", look, good) == []
    assert any("cat" in p for p in looks.prompt_problems("himalayan_ridge", look, good.replace("cat", "dog")))
    assert any("rain in the air" in p for p in looks.prompt_problems("himalayan_ridge", look, good.replace("mist", "heavy rain falling", 1)))
    assert any("person" in p for p in looks.prompt_problems("himalayan_ridge", look, good + " A woman stands there."))
    assert any("missing" in p for p in looks.prompt_problems("himalayan_ridge", look, good.replace("No people, no text, no logo.", "")))


def test_every_angle_has_a_title_that_fits_and_names_rain_and_the_length():
    for angle, a in looks.ANGLES.items():
        for scene in M.SCENES:
            t = seo.fallback_title(scene, angle, "3 hours", "bamboo flute", "k", [])
            assert len(t) <= seo.TITLE_MAX and "rain" in t.lower() and "3 Hours" in t, (angle, scene, t)
        assert 3 <= len(a["headlines"]) and all(h.isupper() and len(h) <= 16 for h in a["headlines"]), angle
    titles = {seo.fallback_title("ocean", a, "3 hours", "harp", "k", []) for a in looks.ANGLES}
    assert len(titles) == len(looks.ANGLES)                                   # nine angles, nine different titles


def test_the_description_answers_what_who_when_where_how_and_has_no_health_claim():
    look = looks.pick_look("courtyard", [], random.Random(2))
    c = seo.fallback_copy("courtyard", "study", "3 hours", "soft piano", look, "k", [])
    d = seo.description_from_copy("courtyard", "study", "3 hours", "soft piano", c)
    for part in ("WHAT YOU WILL HEAR", "WHO IT IS FOR", "WHEN TO PLAY IT", "WHERE IT WORKS", "HOW TO USE IT", "ABOUT THE SCENE", "AI-generated"):
        assert part in d
    assert d.splitlines()[0] == c["hook"] and len(c["hook"]) <= 190 and d.rstrip().endswith("#StudyMusic #RainAmbience")
    assert not director.BAN.search(d)
    assert seo.tags_for("courtyard", "study", "soft piano")[1] == "study with rain"


def test_title_and_copy_rules():
    assert director.title_problems("Rain Sounds for Sleeping | 3 Hours at a Cabin", "3 hours", []) == []
    assert director.title_problems("Cure Your Anxiety With Rain | 3 Hours", "3 hours", [])
    assert director.title_problems("Soft Piano Music for a Calm Evening", "3 hours", [])            # no rain, no length
    assert director.title_problems("Rain Sounds for Sleeping | 3 Hours at a Cabin", "3 hours", ["Rain Sounds for Sleeping | 3 Hours at a Cabin"])
    assert director.thumb_words_problems("RAIN TO SLEEP", "DEEP SLEEP") == []
    assert director.thumb_words_problems("rain to sleep", "") and director.thumb_words_problems("A VERY LONG HEADLINE HERE", "")


class FakeCaller:
    """Stands in for llm.JsonCaller: `replies` maps the task name to a value (or an exception to raise); validate() runs like the real one."""
    replies: dict = {}

    def __init__(self, backend, s=None):
        pass

    async def call(self, system, user, model_cls, validate=None, **k):
        task = system.split("]")[0].split(":")[-1]
        v = self.replies[task]
        if isinstance(v, Exception):
            raise v
        value = v(user) if callable(v) else v
        if validate:
            validate(value)
        return SimpleNamespace(value=value)


def _good_visual(st):
    def make(user):
        s = store.get(st)["settings"]
        return director.VisualOut(scene_prompt=looks.compose_prompt(s["scene"], s["look"]), thumb_prompt=looks.thumb_prompt(s["scene"], s["thumb"]),
                                  headline="RAIN TO SLEEP", subline="DEEP SLEEP")
    return make


def _good_copy(length, title):
    return director.CopyOut(
        title=title, hook="3 hours of gentle rain and soft piano in a quiet courtyard, made for students, night owls and anyone who studies better with steady sound.",
        scene_paragraph="Water beads on the glass while a brass lamp glows on the left of the sill, and soft piano plays slowly under the sound of the rain in the courtyard.",
        audience=["students before exams", "night owls who read late", "remote workers", "light sleepers"], when=["at the start of a long study block", "late at night when the house is quiet",
                                                                                                                    "on a grey afternoon"],
        how=["keep the volume low", "set the sleep timer in the app", "use a speaker across the room"], about="A quiet courtyard in the rain.")


def _plan(monkeypatch, replies, scene="courtyard"):
    s = store.create(scene=scene)
    monkeypatch.setattr(llm, "ChatBackend", lambda *a, **k: object())
    monkeypatch.setattr(llm, "JsonCaller", FakeCaller)
    FakeCaller.replies = {k: (v(s["id"]) if k == "rl_visual" and callable(v) else v) for k, v in replies.items()}
    st = asyncio.run(director.plan(s["id"], {"base_url": "http://gw/v1"}, force=True))
    return s["id"], st


def test_the_director_uses_the_models_words_when_they_pass_the_checks(monkeypatch):
    s0 = store.create(scene="courtyard")
    sid = s0["id"]
    monkeypatch.setattr(llm, "ChatBackend", lambda *a, **k: object())
    monkeypatch.setattr(llm, "JsonCaller", FakeCaller)
    FakeCaller.replies = {"rl_visual": _good_visual(sid), "rl_copy": _good_copy("3 hours", "Study With Rain & Soft Piano | 3 Hours at a Courtyard")}
    st = asyncio.run(director.plan(sid, {"base_url": "http://gw/v1"}, force=True))
    assert st["director_notes"] == ["visual: model", "copy: model"]
    assert st["copy"]["source"] == "model" and st["copy"]["title"].startswith("Study With Rain")
    assert st["thumb"]["headline"] == "RAIN TO SLEEP" and st["scene_prompt"].startswith(M.WET[:20]) and st["flame"] == bool(st["look"]["flame"])
    from relaxation import image
    assert image._body(st, "courtyard", 5)["prompt"] == st["scene_prompt"]               # the picture is drawn from this video's own prompt


def test_the_director_falls_back_to_code_when_the_model_fails_or_breaks_a_rule(monkeypatch):
    sid, st = _plan(monkeypatch, {"rl_visual": llm.LLMError("down"), "rl_copy": llm.LLMError("down")})
    assert st["director_notes"][0].startswith("visual: stand-in") and st["director_notes"][1].startswith("copy: stand-in")
    assert looks.prompt_problems(st["scene"], st["look"], st["scene_prompt"].replace(M.WET, "", 1).strip()) == [] or st["scene_prompt"]
    assert st["copy"]["source"] == "code" and len(st["copy"]["title"]) <= 70 and st["thumb"]["headline"] in looks.ANGLES[st["angle"]]["headlines"]
    bad = _good_copy("3 hours", "Cure Your Anxiety With Rain | 3 Hours")                    # a health claim: refused, and the stand-in is used
    sid2, st2 = _plan(monkeypatch, {"rl_visual": llm.LLMError("x"), "rl_copy": bad})
    assert st2["copy"]["source"] == "code" and "Cure" not in st2["copy"]["title"]


def test_publish_text_follows_the_directors_copy_and_the_angle(monkeypatch):
    from relaxation import publish
    sid, st = _plan(monkeypatch, {"rl_visual": llm.LLMError("x"), "rl_copy": llm.LLMError("x")})
    pub = asyncio.run(publish.generate(sid, {"base_url": "http://gw/v1"}))
    assert pub["title"] == st["copy"]["title"] and pub["angle"] == st["angle"] and "WHO IT IS FOR" in pub["description"]
    assert pub["hashtags"][1] == seo.ANGLE_HASHTAGS[st["angle"]]


def test_a_new_session_gets_seeds_that_differ_from_the_last_ones():
    sessions = [store.create(scene="himalayan_ridge") for _ in range(4)]
    for s in sessions:
        assert s["settings"]["angle"] in looks.ANGLES and s["settings"]["look"]["lamp"] and s["settings"]["thumb"]["layout"] in looks.LAYOUTS
    angles = [s["settings"]["angle"] for s in sessions]
    assert len(set(angles)) == 4                                                   # no angle repeats within the last six videos
    assert len({s["settings"]["look"]["lamp"] for s in sessions}) >= 3


def test_every_thumbnail_layout_renders_a_small_jpeg(tmp_path):
    from PIL import Image
    pic = tmp_path / "p.jpg"
    Image.new("RGB", (1280, 720), (40, 60, 90)).save(pic)
    for layout in looks.LAYOUTS:
        for side in ("left", "right", "centre"):
            data = thumbrender.render(pic, "3 HOURS", {"layout": layout, "side": side, "font": looks.FONTS[0][0], "palette": 2, "headline": "RAIN TO SLEEP", "subline": "DEEP SLEEP"})
            assert data[:2] == b"\xff\xd8" and len(data) < thumbrender.MAX_BYTES, (layout, side)
    assert thumbrender.render(pic, "3 HOURS")[:2] == b"\xff\xd8"                  # no spec: the old look


def test_thumbnail_prompts_follow_the_subject_and_new_thumbnail_rolls_new_seeds(monkeypatch, tmp_path):
    from relaxation import thumb
    for scene in M.SCENES:
        for subject, word in (("person", "woman"), ("back", "behind"), ("walk", "umbrella"), ("exterior", "outside"), ("landscape", "wide"), ("macro", "macro"),
                              ("still", "mug"), ("animal", "cat"), ("object", "lantern")):
            t = {**looks.pick_thumb("sleep", scene, [], random.Random(1)), "subject": subject, "who": "woman", "animal": "cat", "object": "lantern"}
            p = looks.thumb_prompt(scene, t)
            assert looks.thumb_problems(t, p) == [] and word in p.lower(), (scene, subject)
    kinds = {looks.pick_thumb("sleep", "courtyard", [], random.Random(i))["subject"] for i in range(60)}
    assert len(kinds) >= 7 and looks.SUBJECTS.count("person") + looks.SUBJECTS.count("back") < len(looks.SUBJECTS) * 0.15       # a person at the window is rare
    s = store.create(scene="courtyard")
    before = dict(store.get(s["id"])["settings"]["thumb"])
    t = thumb.reroll(s["id"], "man")
    assert t["subject"] == "person" and t["who"] == "man" and "young man" in store.get(s["id"])["settings"]["thumb_prompt"]
    assert thumb.reroll(s["id"], "")["subject"] in looks.SUBJECTS
    assert t["headline"] in looks.ANGLES[store.get(s["id"])["settings"]["angle"]]["headlines"] and before != t
