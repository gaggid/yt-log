"""Quick-win fixes to the picture prompt (audit tasks 1.2, 1.3, 1.4): no crowd where the scene is quiet, the person (not the place) is the main subject,
and the scene's own `style` and fact fields no longer carry noise."""
from story2 import imgprompts as ip
from story2.scene_schemas import NEEDS_ASSET


def test_quiet_scene_gets_no_bystander_line():
    assert ip._ambient_hint("Ludhiana Street", {}, "quiet, dusty, still", []) == ""
    assert ip._ambient_hint("the main road", {}, "empty at dawn", ["crowds"]) == ""


def test_crowd_exclusion_is_said_as_what_is_there():
    out = ip._ambient_hint("the market street", {}, "busy afternoon", ["crowds"])
    assert "distant figures" in out and "no " not in out.lower().replace("no one", "")


def test_busy_public_place_still_gets_the_default_line():
    assert "populated with bystanders" in ip._ambient_hint("Chandni Chowk bazaar", {}, "hot noon", [])
    assert ip._ambient_hint("a private study", {}, "", []) == ""


def person(name):
    return {"id": "p", "kind": "person", "name": name, "data": {}}


def test_person_is_the_subject_when_the_scene_subject_is_the_place():
    d = {"subject": "Ludhiana Street", "setting": {"location": "Ludhiana Street"}}
    assert ip._subject_lead(d, [person("Chavi Lal Verma")]) == "Chavi Lal Verma"
    assert ip._subject_lead(d, []) == "Ludhiana Street"                        # no person: the place stays the subject
    d2 = {"subject": "Chavi Lal Verma", "setting": {"location": "Ludhiana Street"}}
    assert ip._subject_lead(d2, [person("Chavi Lal Verma")]) == "Chavi Lal Verma"
    d3 = {"subject": "hands on a clay pot", "setting": {"location": "Ludhiana Street"}}
    assert ip._subject_lead(d3, [person("Verma")]) == "hands on a clay pot"


def test_place_asset_name_counts_as_the_place():
    d = {"subject": "The Suri Home", "setting": {"location": "Delhi"}}
    assets = [{"kind": "place", "name": "The Suri Home", "id": "x", "data": {}}]
    assert ip._subject_lead(d, [person("Geeta")], assets) == "Geeta"


def test_only_chart_like_scenes_keep_fact_lines():
    assert "data_chart" in NEEDS_ASSET or "comparison" in NEEDS_ASSET


def test_prompt_lint_finds_negations_contradictions_extra_text_and_wrong_gender():
    from story2 import imgprompts
    c = {"adapter": "qwen", "prompt_version": "v2", "prompt": "A crowded lane where nobody is around. The words \"A\" and the words \"B\". The man walks. Style: painted, no photo look."}
    sc = {"data": {}}
    assets = [{"kind": "person", "name": "Asha", "data": {"appearance": {"gender": "woman"}}}]
    kinds = {i["kind"] for i in imgprompts.lint(c, sc, assets)}
    assert {"lint_contradiction", "lint_text"} <= kinds
    c2 = {**c, "prompt": "Asha stands in a lane. Do not show a crowd. Style: painted."}
    assert any(i["kind"] == "lint_negation" and i["level"] == "error" for i in imgprompts.lint(c2, sc, assets))
    c3 = {**c, "prompt": "Asha, the man, stands in a lane. Style: painted, no photo look."}
    assert [i["kind"] for i in imgprompts.lint(c3, sc, assets)] == ["lint_gender"]                  # the style sentence may say "no"
    assert imgprompts.lint({**c, "prompt_version": ""}, sc, assets) == []                          # the older form is not linted
    assert imgprompts.lint({**c, "prompt": "Asha stands in a lane at dawn. Style: painted."}, sc, assets) == []
