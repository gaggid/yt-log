"""Pipeline version flag, and the rule that new planning data never changes the content hash of an approved plan."""
from story2 import editorial, version


def test_unnumbered_plans_count_as_q1():
    assert version.of({}) == "q1" and version.of(None) == "q1"
    assert version.at_least({}, "q1") and not version.at_least({}, "q2")


def test_stage_stamp_and_stale(monkeypatch):
    st = version.stamp({"minutes": 5}, "narration")
    assert st["narration_pipeline"] == version.PIPELINE and st["minutes"] == 5
    monkeypatch.setattr(version, "PIPELINE", "q2")
    assert version.stale({"narration_pipeline": "q1"}, "narration")
    assert not version.stale(st | {"narration_pipeline": "q2"}, "narration")
    assert version.stale({}, "storyboard")                                  # never stamped: older


def test_new_settings_keys_do_not_change_the_content_hash():
    plan = {"format": "16:9", "blueprint": {"beats": []}, "narrator": {"name": "A"}, "settings": {"minutes": 6}, "segments": [], "scenes": [], "assets": []}
    before = editorial.content_hash(plan)
    plan["settings"].update({"pipeline": "q2", "material": {"items": [1, 2]}, "events": [{"id": "e1"}], "audience": {"profile": "hindi_first"}, "name_map": {"A": "B"},
                             "experience": {"promise": "x"}, "panel": {"p1": 1}, "judges": {}, "max_scene_s": 8})
    assert editorial.content_hash(plan) == before
