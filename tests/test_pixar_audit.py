"""The audit of the Pixar-style short sh-2bf15321: a generic word ("top", "s", "1") must not pull a subject into a shot, a subject's look says what it is and not where it stands, the
3D style never gives an object eyes, and the review no longer calls a 3D picture a style break, a lab an office-in-a-street or traffic an extra car."""
import copy

from shorts import director, lint, looks, review, stills, subjects

SUBJECTS = [
    {"name": "India's Economy", "kind": "organisation", "visual": "A high-angle cinematic shot of a bustling modern Indian city skyline featuring a mix of glass skyscrapers and traditional structures, bathed in golden morning light."},
    {"name": "The Top 1%", "kind": "group", "visual": "A small group of five wealthy Indian people dressed in elegant silk clothes, standing on a podium, glowing with a subtle golden aura."},
    {"name": "The Titans", "kind": "person", "visual": "A successful Indian entrepreneur in a sharp navy blue suit, looking confident, standing in a high-tech futuristic laboratory with holographic displays."},
    {"name": "K-shaped growth graph", "kind": "other", "visual": "A 3D glowing graph where the line splits into a 'K' shape: the top arm climbs sharply upward."},
    {"name": "The Cake", "kind": "object", "visual": "A massive, multi-layered chocolate cake with various fruits on top, sitting on a large wooden table in the center of a bright room."},
    {"name": "A luxury car", "kind": "object", "visual": "A sleek, polished black luxury sedan parked on a clean paved driveway, reflecting the surrounding trees."},
    {"name": "A humble bicycle", "kind": "object", "visual": "A simple, slightly rusted iron bicycle with a wicker basket, leaning against a brick wall."},
]
STILLS = {
    "s18": "Wide shot of a modern Indian city skyline. The camera is placed high and looks down at the city from above. Three glass skyscrapers stand on the left side. Golden morning light shines from the top right corner.",
    "s3": "Close-up of one man's face. The man is The Titans. He looks forward at a holographic display in front of him. The background is a high-tech laboratory.",
    "s9": "Wide shot of one massive multi-layered chocolate cake. The cake sits on one large wooden table. One strawberry and one blueberry sit on the top of the cake.",
    "s6": "Wide shot of one 3D glowing graph. The top arm of the 'K' climbs sharply upward to the top right.",
    "s5": "Wide shot of one black luxury car and one rusted iron bicycle. The car is on the left side of the frame. A dusty rural road is in the foreground.",
}


def pixar(**settings):
    shots = [{"id": i, "beat": "b1", "prompt": t, "still": t, "subjects": [], "seconds": 2.0, "setting": "a high-tech futuristic laboratory" if i == "s3" else ""} for i, t in STILLS.items()]
    shots[0]["subjects"] = ["India's Economy"]
    shots[1]["subjects"] = ["The Titans"]
    shots[2]["subjects"] = ["The Cake"]
    shots[3]["subjects"] = ["K-shaped growth graph"]
    shots[4]["subjects"] = ["A luxury car", "A humble bicycle"]
    return {"id": "sh-x", "settings": {"visual_style": "pixar3d", "storyboard_lint": True, "scene_review": True, **settings},
            "plan": {"title": "t", "logline": "l", "place": "A vibrant, modern Indian city street.", "look": "", "character": "", "subjects": copy.deepcopy(SUBJECTS)}, "shots": shots, "beats": []}


def shot(short, sid):
    return next(s for s in short["shots"] if s["id"] == sid)


# -- generic words do not name a subject -------------------------------------------

def test_top_one_percent_is_not_named_by_the_word_top():
    short = pixar()
    top1 = SUBJECTS[1]
    for sid in ("s18", "s9", "s6"):
        assert not lint.mentioned(short, top1, STILLS[sid]), sid
    assert lint.mentioned(short, top1, "Five people from The Top 1% stand together.")


def test_a_possessive_s_or_a_number_names_nothing():
    short = pixar()
    assert not lint.mentioned(short, SUBJECTS[0], STILLS["s3"])           # "man's" must not find "India's Economy"
    assert "s" not in lint.distinctive(short, SUBJECTS[0]) and "1" not in lint.distinctive(short, SUBJECTS[1])


def test_the_prompt_of_a_shot_lists_only_the_subjects_it_names():
    short = pixar()
    for sid in ("s18", "s9", "s6", "s3"):
        who = stills.looks_line(short, shot(short, sid), "")[0]
        assert "The Top 1%" not in who, (sid, who)
    assert "India's Economy" not in stills.looks_line(short, shot(short, "s3"), "")[0]


# -- a look says what it is, not where it stands -----------------------------------

def test_a_subject_look_has_no_place_or_pose():
    assert "podium" not in subjects.appearance(SUBJECTS[1]["visual"])
    assert "driveway" not in subjects.appearance(SUBJECTS[5]["visual"])
    assert "brick wall" not in subjects.appearance(SUBJECTS[6]["visual"])
    assert "wicker basket" in subjects.appearance(SUBJECTS[6]["visual"])
    assert "sedan" in subjects.appearance(SUBJECTS[5]["visual"])
    assert subjects.appearance("Standing on a podium") == "Standing on a podium"                 # nothing left: the plain look stays


def test_the_prompt_uses_the_appearance_only_when_the_storyboard_check_is_on():
    checked, old = pixar(), pixar(storyboard_lint=False)
    assert "driveway" not in stills.prompt(checked, shot(checked, "s5"))
    assert "driveway" in stills.prompt(old, shot(old, "s5")), "a short made before the check keeps its prompts"


# -- the 3D style gives people eyes, not cars ---------------------------------------

def test_the_pixar_style_puts_eyes_on_people_and_animals_only():
    short = pixar()
    text = stills.prompt(short, shot(short, "s5"))
    assert "any face has large expressive eyes" not in text
    assert "every human and animal face has large expressive eyes" in text
    assert "vehicles, machines and objects keep their ordinary real-world design" in text


# -- the review knows the style ----------------------------------------------------

def seen(**kw):
    return {"place": "street", "setting_type": "outdoor", "people_count": 0, "objects": [], "readable_text": "none", "style": "3d", "background": "city street", "object_faces": "none", **kw}


def kinds(short, sid, s):
    return {d["kind"] for d in review.defects(short, shot(short, sid), s)[0]}


def test_a_3d_picture_in_a_3d_short_is_not_a_style_break():
    short = pixar()
    assert "style_break" not in kinds(short, "s6", seen(place="city street"))
    assert "style_break" in kinds(short, "s6", seen(style="photo"))
    assert "style_break" in kinds(short, "s6", seen(style="painted"))


def test_a_lab_shot_is_not_a_wrong_place_for_the_streets_backdrop():
    short = pixar()
    assert "wrong_place" not in kinds(short, "s3", seen(place="office", background="cityscape through a window", people_count=1))


def test_traffic_in_a_street_picture_is_not_an_extra_car():
    short = pixar()
    assert "extra_object" not in kinds(short, "s18", seen(objects=["skyscrapers", "temple", "cars", "street"]))


def test_people_the_shot_never_names_are_an_extra_person():
    short = pixar()
    assert "extra_person" in kinds(short, "s18", seen(place="cityscape with temple", background="blue sky and city", people_count=5, objects=["skyscrapers"]))
    assert "extra_person" not in kinds(short, "s3", seen(place="office", people_count=1))
    assert "extra_person" not in kinds(short, "s18", seen(people_count=5, objects=["skyscrapers"]))        # a street: passers-by are normal


def test_an_object_with_a_face_is_a_defect():
    short = pixar()
    assert "object_face" in kinds(short, "s5", seen(place="country road", background="brick wall and grass", objects=["car", "bicycle"], object_faces="the car has an eye in its headlight"))
    for none in ("none", "None.", "", "no objects"):
        assert "object_face" not in kinds(short, "s5", seen(place="country road", background="grass", objects=["car"], object_faces=none)), none


def test_the_director_can_fix_the_new_kinds_in_the_style_of_the_short():
    assert {"extra_person", "object_face"} <= set(director.FIXABLE)
    note = director.NOTES["object_face"].format(look=looks.label(pixar()))
    assert "Pixar" in note and "no face" in note


def test_a_head_count_said_once_in_total_and_once_per_position_is_not_added_twice():
    short = pixar()
    t = "Wide shot of five wealthy Indian people. One person stands on the far left, one person stands in the middle-left, one person stands in the middle, one person stands in the middle-right, and one person stands on the far right."
    sh = {**shot(short, "s18"), "still": t, "prompt": t}
    found, notes = review.defects(short, sh, seen(people_count=5, objects=[]))
    assert not any(d["kind"] == "wrong_count" for d in found) and not notes


# -- the framework gaps found in the audit ---------------------------------------------

def test_a_review_made_under_older_rules_is_not_current(monkeypatch):
    short = pixar()
    monkeypatch.setattr(review, "pictures", lambda s: [(sh, {"id": "md-" + sh["id"]}, None) for sh in s["shots"]])
    short["review"] = {"stamp": review.stamp(short)}
    assert review.current(short)
    monkeypatch.setattr(review, "RULES", "next")
    assert not review.current(short)


def test_a_close_up_drawn_wide_is_a_note_not_a_defect():
    short = pixar()
    found, notes = review.defects(short, shot(short, "s3"), seen(place="office", people_count=1, shot_size="medium"))
    assert any("close shot" in n for n in notes) and not any(d["kind"] == "wrong_count" for d in found)
    assert not any("close shot" in n for n in review.defects(short, shot(short, "s3"), seen(place="office", people_count=1, shot_size="close-up"))[1])


def test_the_storyboard_notes_a_subject_added_by_a_loose_word():
    short = pixar()
    short["plan"]["subjects"].append({"name": "Cake Slice", "kind": "object", "visual": "A slice of chocolate cake on a plate."})
    short["shots"].append({"id": "s30", "beat": "b1", "prompt": "x", "still": "Close-up of one slice of chocolate cake. The camera is placed close to the plate.", "subjects": [], "seconds": 2.0})
    assert lint.prompt_extras(short, shot(short, "s30")) == [("Cake Slice", "slice")]
    leaks = [n for n in lint.notes(short) if n["rule"] == "prompt_leak"]
    assert len(leaks) == 1 and "Cake Slice" in leaks[0]["text"] and "slice" in leaks[0]["text"] and leaks[0]["shots"] == ["s30"]
    assert not any("The Top 1%" in n["text"] for n in leaks), "the fixed word list leaves no leak in the audited shots"


def test_a_single_unnamed_person_is_sent_back_to_the_picture_writer():
    from shorts import stillwriter
    bad = stillwriter.StillOut(id="s20", still="Medium shot of one wealthy Indian person. The person stands in the center of a bright room. The person holds a large pile of gold coins in both arms. Warm light shines from the front.")
    ok = stillwriter.StillOut(id="s20", still="Medium shot of one wealthy Indian man in his fifties. The man stands in the center of a bright room. The man holds a large pile of gold coins in both arms. Warm light shines from the front.")
    assert any("single \"person\"" in p for p in stillwriter.problems(bad, strict=True))
    assert not any("single \"person\"" in p for p in stillwriter.problems(ok, strict=True))
    assert not any("single \"person\"" in p for p in stillwriter.problems(bad, strict=False))


def test_no_style_text_gives_eyes_to_every_face():
    for sid, p in looks.TRENDING.items():
        assert "any face" not in p["look"] and "any face" not in p.get("lead", ""), sid


# -- the close look for eyes on cars ---------------------------------------------------

def test_a_picture_with_a_vehicle_gets_a_close_second_look_and_only_a_claim_with_a_place_counts(tmp_path, monkeypatch):
    from PIL import Image
    short = pixar()
    items = []
    for sid in ("s5", "s6", "s3"):
        p = tmp_path / f"{sid}.png"
        Image.new("RGB", (72, 128), "white").save(p)
        items.append((shot(short, sid), {"id": "md-" + sid}, p))
    seen_in = {"s5": seen(objects=["car", "bicycle"]), "s6": seen(objects=["arrow"]), "s3": seen(objects=["screen"], people_count=1)}
    asked = []

    class Out:
        def __init__(self, v):
            self.value = v

    class Caller:
        def __init__(self, backend, s):
            pass

        async def call(self, system, user, model, images=None, response_format=None, **kw):
            asked.append((system.splitlines()[0], len(images)))
            return Out(review.FaceLook(things=["car"], face_on_a_thing=True, where="a large eye in the left headlight"))

    monkeypatch.setattr(review.llm, "JsonCaller", Caller)
    import asyncio
    asyncio.run(review.face_pass(short, items, seen_in, None, {}))
    assert len(asked) == 2 and all(a[0] == "[TASK:p4_review_face]" for a in asked) and all(a[1] == 1 for a in asked), "the car (s5) and the graph subject (s6, a thing) are looked at; the man in the lab is not"
    assert "eye in the left headlight" in seen_in["s5"]["object_faces"] and seen_in["s3"]["object_faces"] == "none"
    assert "object_face" in kinds(short, "s5", seen_in["s5"])

    class Liar(Caller):
        async def call(self, *a, **kw):
            return Out(review.FaceLook(things=["car"], face_on_a_thing=True, where="none"))
    monkeypatch.setattr(review.llm, "JsonCaller", Liar)
    again = {"s5": seen(objects=["car"])}
    asyncio.run(review.face_pass(short, items[:1], again, None, {}))
    assert again["s5"]["object_faces"] == "none", "true with 'none' is no claim"
