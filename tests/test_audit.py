"""The audit scorecard: metrics computed on a hand-built plan with known answers (no database, no model)."""
from story2 import audit, lexicon


def scene(i, start, dur, place, who=(), subject="x", dist="medium", prompt="", excl=(), atmosphere="", style="filmic"):
    return {"id": f"sc{i}", "seq": i, "start_s": start, "duration_s": dur, "data": {
        "setting": {"location": place}, "subject": subject, "composition": {"distance": dist}, "continuity": {"assets": list(who)},
        "exclusions": list(excl), "atmosphere": atmosphere, "style": style, "prompts": {"qwen": {"prompt": prompt}}}}


def plan(scenes, sentences=None, minutes_s=None):
    sents = sentences or [{"text": "यह एक परीक्षण है।", "emotion": "neutral"}] * 4
    dur = minutes_s or 120.0
    return {"segments": [{"id": "g1", "seq": 1, "duration_s": dur, "sentences": sents}], "scenes": scenes,
            "assets": [{"id": "p1", "kind": "person", "name": "Asha"}, {"id": "p2", "kind": "person", "name": "Ravi"}, {"id": "pl1", "kind": "place", "name": "Lane"}]}


def test_world_counts_places_people_and_faces():
    sc = [scene(1, 0, 6, "Lane", ["p1"], dist="close"), scene(2, 6, 6, "Lane", ["p1"], dist="close"), scene(3, 12, 6, "Lane", ["p1"], dist="close"),
          scene(4, 18, 6, "Station"), scene(5, 24, 6, "Market", ["p2"])]
    w = audit.world(plan(sc))
    assert w["distinct_places"]["value"] == 3 and w["distinct_places"]["status"] == "warn"
    assert w["top_place_share"]["value"] == 0.6
    assert w["person_scene_share"]["value"] == 0.8
    assert w["face_free_share"]["value"] == 0.2
    assert w["protagonist_share"]["value"] == 0.6 and w["protagonist_share"]["note"] == "Asha"
    assert w["max_face_closeup_run"]["value"] == 3 and w["max_face_closeup_run"]["status"] == "warn"


def test_pace_flags_long_scenes():
    p = audit.pace(plan([scene(1, 0, 4, "a"), scene(2, 4, 33, "b")]))
    assert p["max_scene_s"]["value"] == 33 and p["max_scene_s"]["status"] == "warn"
    assert p["scenes_over_12s"]["value"] == 1


def test_prompt_metrics_find_boilerplate_negation_and_contradictions():
    tail = "Constraints: These must not appear: crowds; cars. No logos or lettering."
    ps = [f"A man {i} walks. Background populated with bystanders, movement and activity. {tail}" for i in range(5)]
    sc = [scene(i, i * 5, 5, "Lane", prompt=ps[i], excl=["crowds"], atmosphere="quiet, still", style="style") for i in range(5)]
    m = audit.prompts(plan(sc))
    assert m["prompts_with_negation"]["value"] == 5
    assert m["crowd_quiet_contradictions"]["value"] == 5
    assert m["style_field_junk"]["value"] == 5
    assert m["identical_prompt_share"]["value"] > 0.6


def test_prompt_metrics_without_prompts_are_not_applicable():
    assert audit.prompts(plan([scene(1, 0, 5, "a")]))["prompt_words"]["status"] == "na"


def test_narration_metrics():
    sents = [{"text": "आप कैसे हैं?", "emotion": "neutral"}, {"text": "सोचिए, वह thirty-five years तक छिपा रहा।", "emotion": "neutral"},
             {"text": "If a man can hide for years, what then?", "emotion": "neutral"}]
    n = audit.narration(plan([], sents))
    assert n["questions_share"]["value"] == 0.67
    assert n["stock_phrases"]["value"] >= 1
    assert n["english_numbers_in_hindi"]["value"] == 1
    assert n["last_line_not_hindi"]["value"] == 1


def test_boredom_map_flags_a_repetitive_stretch():
    fresh = [{"text": f"नया शब्द{i} अलग{i} बात{i} चीज़{i}।", "emotion": "neutral"} for i in range(12)]
    stale = [{"text": "वही शब्द वही बात वही चीज़।", "emotion": "neutral"} for _ in range(12)]
    sc = [scene(i, i * 10, 10, f"place{i}", subject=f"s{i}") for i in range(3)] + [scene(i, i * 10, 10, "same", subject="same") for i in range(3, 12)]
    b = audit.boredom_map(plan(sc, fresh + stale, 120.0))
    assert b["windows"][0]["flags"] == []                                    # the start is fresh
    assert b["drop_windows"], "the repeated second half must be a drop point"
    assert all(d["t"] >= 60 for d in b["drop_windows"])


def test_judge_uses_targets():
    assert audit.judge("questions_share", 0.05) == "ok" and audit.judge("questions_share", 0.2) == "warn"
    assert audit.judge("distinct_places", 12) == "ok" and audit.judge("distinct_places", 4) == "warn"
    assert audit.judge("unknown_metric", 1) == "na" and audit.judge("max_scene_s", None) == "na"


def test_lexicon_finds_stock_and_cliche_once_each():
    assert "सोचिए" in lexicon.hits("सोचिए, वह एक genius था")
    assert "genius" in lexicon.hits("सोचिए, वह एक Genius था")
    assert lexicon.count(["सोचिए", "सब ठीक है"]) == 1
