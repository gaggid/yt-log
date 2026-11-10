"""The drama director (docs/PLAN_drama.md part B): arc phases, tension target, neglected material, risk calibration, the guarantee that a failed act costs, opposition."""
import copy

from sim import drama
from test_sim_api import client, new_story, wait  # noqa: F401
from test_sim_health import TRACKERS, st
from test_sim_things_api import detail, make_plan, start


def test_a_planned_length_gives_one_arc_and_an_open_story_repeats_a_wave():
    seq = [drama.phase(i, 12) for i in range(1, 13)]
    assert seq[0] == "setup" and seq[5] == "midpoint" and seq[-1] == "resolution" and "crisis" in seq and "climax" in seq
    assert seq.index("rising") < seq.index("midpoint") < seq.index("crisis") < seq.index("climax")
    assert [drama.phase(i, 0) for i in range(1, 8)] == ["setup", "rising", "rising", "midpoint", "crisis", "release", "complication"]
    assert drama.target(1, 12) < drama.target(8, 12) < drama.target(11, 12) and drama.target(12, 12) < drama.target(11, 12)          # builds, peaks, then eases for the resolution
    assert drama.phase(3, 6) == "midpoint" and drama.phase(1, 2) == "setup" and drama.phase(2, 2) == "resolution"


def test_the_arc_note_asks_for_more_pressure_when_the_story_is_below_target():
    a = drama.arc(5, 12, [3, 3, 3])
    assert a["phase"] in ("rising", "midpoint", "crisis") and "must reach about" in a["note"] and a["chapters_left"] == 7
    easing = drama.arc(2, 12, [8, 8, 9])
    assert easing["note"].startswith("The last chapters reached 8, 8, 9") and "ease" in easing["note"]
    assert "ARC AND PACING" in drama.arc_block(a, 5, 12) and "open-ended" in drama.arc_block(drama.arc(2, 0, []), 2, 0)


def rep(**kw):
    base = {"chapters": 4, "dice": {"rolls": 8, "tiers": {"success": 8}, "free_streak": 0}, "intensity": [3, 3, 3, 3],
            "spotlight": {"A": {"away": 0, "mentions": [3], "share": 0.6}, "Silas": {"away": 4, "mentions": [0], "share": 0.0}},
            "material": [{"who": "Sarah", "kind": "secret", "text": "She was hosting a dinner party tonight", "last": 0, "age": 4}, {"who": "A", "kind": "goal", "text": "Survive", "last": 4, "age": 0}],
            "threads": [{"text": "Who knocked on the shutter?", "age": 5}]}
    base.update(kw)
    return base


def test_neglected_material_is_listed_and_a_plan_must_touch_it():
    items = drama.neglected(rep())
    texts = " | ".join(x["text"] for x in items)
    assert "Silas has not been in the story for 4 chapters" in texts and "Sarah's secret" in texts and "open thread" in texts and len(items) <= drama.MAX_NEGLECTED
    assert drama.neglected(rep(chapters=2)) == []                                           # too early to call anything neglected
    assert drama.plan_touches(items, "Silas limps behind the others") and drama.plan_touches(items, "Sarah thinks of the dinner she was hosting")
    assert not drama.plan_touches(items, "They walk to the next aisle and look at the shelves")
    assert "NEGLECTED" in drama.neglected_block(items) and drama.neglected_block([]) == ""


def test_calibration_makes_acts_harder_after_free_chapters_and_easier_after_punishing_ones():
    risks = [{"act": "stay calm", "difficulty": "easy"}, {"act": "scan", "difficulty": "normal"}]
    notes = drama.calibrate(risks, rep(dice={"rolls": 8, "tiers": {"success": 8}, "free_streak": 2}), 6)
    assert risks[0]["difficulty"] == "normal" and risks[0]["calibrated"] == "harder" and "made harder" in notes[0] and risks[1]["difficulty"] == "normal"       # the easiest act is raised one step
    risks = [{"act": "a", "difficulty": "hard"}, {"act": "b", "difficulty": "normal"}]
    assert drama.calibrate(copy.deepcopy(risks), rep(intensity=[9, 9]), 5)[0].startswith("made easier")
    assert drama.calibrate([{"act": "a", "difficulty": "hard"}], rep(dice={"rolls": 8, "tiers": {}, "free_streak": 3}), 5) == []         # already at the top
    assert drama.calibrate(risks, {"chapters": 0}, 5) == [] and drama.calibrate([], rep(), 5) == []


def test_a_failed_or_partial_act_always_costs_something():
    before = st()
    for tier in ("partial", "fail", "disaster"):
        after, extra = drama.ensure_cost([{"tier": tier, "who": "A", "act": "run"}], before, copy.deepcopy(before), TRACKERS)
        assert extra and extra[0]["op"] == "cost" and tier in extra[0]["text"]
        assert after["trackers"]["m1"] < before["trackers"]["m1"] or after["trackers"]["m2"] > before["trackers"]["m2"]
    after, extra = drama.ensure_cost([{"tier": "success", "who": "A", "act": "run"}], before, copy.deepcopy(before), TRACKERS)
    assert extra == [] and after == before                                                  # a success costs nothing extra
    paid = st()
    paid["trackers"]["r1"] = {"trust": 0, "tension": 2}                                     # the changes already hurt: nothing is added
    assert drama.ensure_cost([{"tier": "fail", "who": "A", "act": "run"}], before, paid, TRACKERS)[1] == []
    only_clock = [t for t in TRACKERS if t["kind"] == "clock"]                              # no meters: the clock moves
    s0 = {"time": "", "trackers": {"c1": 0}, "entities": {}}
    after, extra = drama.ensure_cost([{"tier": "fail", "who": "A", "act": "run"}], s0, copy.deepcopy(s0), only_clock)
    assert after["trackers"]["c1"] == 1 and extra
    assert drama.ensure_cost([{"tier": "fail", "who": "A", "act": "x"}], s0, copy.deepcopy(s0), [])[1] == []


def test_the_planner_gets_the_arc_and_must_name_an_opposition(client):
    from sim import store
    c = client
    pid = new_story(c)
    store.set_bible(pid, {})                                                                  # a story with no plan: the pacing block steers it (a planned story gets its acts from the plan)
    assert c.patch(f"/api/sim/{pid}", json={"settings": {"length": 12}}).status_code == 200 and detail(c, pid)["project"]["settings"]["length"] == 12
    assert c.patch(f"/api/sim/{pid}", json={"settings": {"length": 500}}).status_code == 200 and detail(c, pid)["project"]["settings"]["length"] == 99
    c.patch(f"/api/sim/{pid}", json={"settings": {"length": 12}})
    c.post(f"/api/sim/{pid}/start")
    wait(c, pid)
    p = c.fake.last("sm_plan")
    assert "## ARC AND PACING\nchapter 1 of 12, phase: SETUP" in p["user"] and "opposition" in p["system"] and "ARC AND PACING" in p["system"]
    ch = detail(c, pid)["chapters"][-1]
    assert ch["plan"]["opposition"] and ch["flags"]["arc"] == {"phase": "setup", "target": 3, "length": 12}
    assert "Opposition (show its effect): The noise outside" in c.fake.last("sm_write")["user"] and "Opposition: The noise" in c.fake.last("sm_delta")["user"]
    n = c.fake.count("sm_plan")                                                             # a plan without an opposition is sent back once
    c.fake.answers["sm_plan"] = lambda user, k: {**c.fake._sm_plan(user), "opposition": "" if k == n + 1 else "The shutter rattles."}
    c.post(f"/api/sim/{pid}/chapters", json={"kind": "auto"})
    wait(c, pid)
    assert c.fake.count("sm_plan") == n + 2 and detail(c, pid)["chapters"][-1]["plan"]["opposition"] == "The shutter rattles."


def test_easy_chapters_get_harder_and_the_planned_length_ends_the_story(client):
    c = client
    pid = start(c, dice=True)
    c.patch(f"/api/sim/{pid}", json={"settings": {"length": 4}})
    make_plan(c, [{"act": "stay calm", "kind": "other", "difficulty": "easy"}])
    for _ in range(2):
        c.post(f"/api/sim/{pid}/chapters", json={"kind": "auto"})
        wait(c, pid)
    h = detail(c, pid)["health"]
    assert h["chapters"] == 3 and detail(c, pid)["chapters"][-1]["flags"]["arc"]["phase"] == "climax" and "calibration" in detail(c, pid)["chapters"][-1]["plan"]
    c.post(f"/api/sim/{pid}/chapters", json={"kind": "auto"})
    wait(c, pid)
    ch = detail(c, pid)["chapters"][-1]
    assert ch["flags"]["arc"]["phase"] == "resolution"
    from sim import engine, store
    assert "planned length of 4" in engine.stop_reason(store.chapter(ch["id"]), set())


def test_the_sections_of_a_neglected_story_reach_the_planner(client):
    c = client
    pid = start(c)
    for _ in range(3):
        c.post(f"/api/sim/{pid}/chapters", json={"kind": "auto"})
        wait(c, pid)
    h = detail(c, pid)["health"]
    away = [n for n, s in h["spotlight"].items() if s["away"] >= 3]
    last = c.fake.last("sm_plan")["user"]
    assert ("NEGLECTED" in last) == bool(away) or "NEGLECTED" in last or not away


def test_a_chapter_that_ends_on_a_menu_of_routes_is_sent_back(client):
    from sim_fakes import words
    c = client
    pid = new_story(c)
    menu = words(350) + " They stop. To the left, a path opens into the dairy; to the right, the dense shelves."
    n = c.fake.count("sm_write")
    c.fake.answers["sm_write"] = lambda user, k: {"title": "Crossroads", "prose": menu if k == n + 1 else words(350) + " Behind them the door opened. Footsteps.", "story_time": "Day 1, 23:40"}
    c.post(f"/api/sim/{pid}/start")
    wait(c, pid)
    assert c.fake.count("sm_write") == n + 2                                                # the first draft is sent back once, the second ends on a hook
    ch = detail(c, pid)["chapters"][-1]
    assert "Footsteps" in ch["prose"] and "to the left" not in ch["prose"].lower()


def test_options_are_dilemmas_with_a_cost_and_no_repeats(client):
    c = client
    pid = new_story(c)
    opts = [{"who": "Ravi", "label": "Ravi sprints through the meat shelves to open a clear route", "hint": "Opens a route; Risk: Medium", "cost": "burns stamina and makes noise", "risk": "medium"},
            {"who": "Meera", "label": "Meera pushes through the meat shelves to clear a route", "hint": "same move again", "cost": "noise", "risk": "low"},
            {"who": "Dev", "label": "Dev stays to guard the shutter alone", "hint": "keeps the exit safe · low risk", "cost": "the group splits", "risk": "low"},
            {"who": "Sana", "label": "Sana reads the note she found", "hint": "may explain the outbreak", "cost": "costs a minute in the open", "risk": "high"}]
    c.fake.answers["sm_archive"] = lambda user, k: {**c.fake._sm_archive(user), "options": opts}
    c.post(f"/api/sim/{pid}/start")
    wait(c, pid)
    got = detail(c, pid)["chapters"][-1]["options"]
    assert [o["who"] for o in got] == ["Ravi", "Dev", "Sana"]                                  # the repeat of the same move is gone
    assert got[0]["hint"] == "Opens a route" and got[1]["hint"] == "keeps the exit safe" and got[0]["cost"] == "burns stamina and makes noise"
    assert "cost" in c.fake.last("sm_archive")["system"] and "at least two of them conflict" in c.fake.last("sm_archive")["system"]
    js = open("static/sim.js", encoding="utf-8").read()
    assert "cost: ${esc(o.cost)}" in js


def test_setup_makes_relation_trackers_for_the_pairs_the_cast_cards_relate(client):
    c = client
    pid = new_story(c)
    rel = [t for t in detail(c, pid)["trackers"] if t["kind"] == "relation"]
    pairs = {frozenset((t["a"], t["b"])) for t in rel}
    assert 2 <= len(rel) <= 3 and frozenset(("Ravi", "Meera")) in pairs and len(pairs) == len(rel)         # the model's own tracker is kept and no pair is doubled
    assert all(t["start"]["trust"] == 2 for t in rel if t["name"] != "Ravi and Meera")                     # "colleague" is a warm word
    from sim import prompts
    assert "relation_change" in prompts.DELTA and "clash, help, betray" in prompts.DELTA
    assert "2 or 3 pairs" in c.fake.last("sm_trackers")["system"]
    from sim import seed
    cold = seed._relation_trackers  # the word lists are plain data
    assert "rival" in seed.COLD and "mother" in seed.WARM and callable(cold)


def test_costs_spread_over_meters_that_still_have_room_and_a_meter_at_its_end_counts_as_pressure():
    from sim import health, models as m
    trackers = [{"id": "g", "kind": "meter", "name": "Morale", "min": 0, "max": 10, "owner": "group", "start": 0}, {"id": "s", "kind": "meter", "name": "Stamina", "min": 0, "max": 100, "owner": "Elias", "start": 80},
                {"id": "n", "kind": "meter", "name": "Noise", "min": 0, "max": 100, "danger_above": 70, "start": 10}]
    s0 = {"time": "", "trackers": {"g": 0.0, "s": 80.0, "n": 10.0}, "entities": {}}
    after, extra = drama.ensure_cost([{"tier": "fail", "who": "Mira", "act": "hold the line"}], s0, copy.deepcopy(s0), trackers)
    assert extra and after["trackers"]["g"] == 0.0 and (after["trackers"]["s"] < 80 or after["trackers"]["n"] > 10)          # morale is already at the bottom: another meter pays
    flat = {"idx": 1, "rolls": [], "state_before": s0, "state_after": copy.deepcopy(s0), "prose": "x."}
    calm = {"idx": 1, "rolls": [], "state_before": s0, "state_after": {**s0, "trackers": {"g": 6.0, "s": 80.0, "n": 10.0}}, "prose": "x."}
    assert health.chapter_numbers(flat, trackers)["intensity"] > health.chapter_numbers(calm, trackers)["intensity"]
    ops = m.DeltaOut.model_validate({"ops": [{"op": "clock_change", "tracker": "Dawn", "amount": 1}]}).ops
    assert ops[0].op == "clock_advance"
