"""Tasks 7.1 and 7.7: the Phase 1 extra scores."""
from story import reach


def story(**kw):
    d = {"premise": "A man fled Delhi in 1991 and was found in Ludhiana 35 years later", "conflict": "hiding versus being found", "stakes": "his freedom", "turning_point": "a call of his old name",
         "outcome": "arrested", "chronology": [{"when": "1991", "what": "He left Delhi by train with a bag"}, {"when": "2026", "what": "Police found him near Ludhiana at a shop"}],
         "people": [{"name": "Geeta", "role": "victim, murdered landlady"}, {"name": "Verma", "role": "accused suspect"}], "claims": ["He was accused of the murder"]}
    d.update(kw)
    return d


def test_a_story_with_a_turn_events_people_and_places_scores_visual_and_hook():
    r = reach.scores(story(), "The fugitive")
    assert r["visual"] >= 30 and r["packaging"] >= 80
    assert r["region"]["covered"] and set(r["region"]["ids"]) >= {"delhi", "punjab"}
    assert reach.scores({"premise": "a thing"}, "x")["packaging"] < 30 and reach.scores({"premise": "a thing"}, "x")["visual"] < 30


def test_safety_flags_are_found_and_a_named_victim_is_called_out():
    r = reach.scores(story(), "t")
    assert "not yet convicted" in r["safety"]["flags"] and any("named victim" in f for f in r["safety"]["flags"]) and r["safety"]["level"] == "check"
    hard = reach.scores(story(premise="a school girl was raped"), "t")
    assert hard["safety"]["level"] == "high"
    assert reach.scores({"premise": "a calm river"}, "t")["safety"] == {"flags": [], "level": "ok"}


def test_community_terms_and_missing_regions_are_reported():
    r = reach.scores(story(premise="a dispute between two communities in a village near Nowhereville"), "t")
    assert r["sensitivity"]["level"] == "check" and "community" not in r["sensitivity"]["terms"] or "communities" not in r["sensitivity"]["terms"]
    none = reach.scores({"premise": "a quiet tale"}, "t")
    assert not none["region"]["covered"] and "choose" in none["region"]["note"] or "add region" in none["region"]["note"]
    assert reach.scores({"premise": "an online fraud with an OTP and a bank"}, "t")["practical"] >= 45


def test_signatures_differ_from_the_recent_films_and_are_stable(env):
    from story import db
    from story2 import store, variety
    store.ensure()
    a = variety.choose("pl-aaaa0001")
    assert a == variety.choose("pl-aaaa0001") and set(a) == set(variety.FIELDS)
    recent = [variety.choose(f"pl-r{i}") for i in range(5)]
    for i, sig in enumerate(recent):                                                  # five earlier plans on the channel
        db.ex("INSERT INTO plans(id,project_id,candidate_id,format,status,narrator,settings,readiness,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
              (f"pl-r{i}", "p", "c", "16:9", "draft", "{}", db.jdump({"signature": sig}), "{}", 1000 + i, 1000 + i))
    new = variety.choose("pl-brandnew")
    assert min(variety.distance(new, r) for r in recent) >= 3                         # at least three fields differ from the closest recent film
    assert variety.distance(a, a) == 0 and variety.look_words(new).startswith("colour palette")


def test_every_new_plan_gets_a_signature_and_the_music_family_changes_the_pads():
    from story3 import audio
    assert audio.roots_for(0) != audio.roots_for(1) and len(audio.roots_for(2)) == len(audio.ROOTS)


def test_a_takeaway_beat_is_asked_for_only_when_the_details_are_about_something_a_viewer_can_guard_against():
    from story2 import planner
    scam = [{"detail": "A fake call asked for an OTP"}, {"detail": "The loan app took access to the phone"}, {"detail": "Online fraud drained the bank account"}]
    assert planner.takeaway_wanted({"settings": {"story_type": "incident"}}, scam)
    assert not planner.takeaway_wanted({"settings": {"story_type": "biography"}}, scam)
    assert not planner.takeaway_wanted({"settings": {"story_type": "incident"}}, [{"detail": "A man fled by train"}])


def test_stories_made_of_the_same_passages_are_suggested_for_merging(monkeypatch):
    from story import review
    cands = [{"id": "S-1", "eff_priority": 50, "title": "Weaker"}, {"id": "S-2", "eff_priority": 80, "title": "Stronger"}, {"id": "S-3", "eff_priority": 70, "title": "Other"}]
    refs = {"S-1": [1, 2, 3, 4], "S-2": [2, 3, 4, 5, 6], "S-3": [20, 21]}
    monkeypatch.setattr(review, "list_candidates", lambda pid, status="": cands)
    monkeypatch.setattr(review, "get_refs", lambda pid, cid: [{"idx": i} for i in refs[cid]])
    out = review.merge_suggestions("P")
    assert len(out) == 1 and out[0]["ids"] == ["S-1", "S-2"] and out[0]["title"] == "Stronger" and out[0]["shared"] == 3
