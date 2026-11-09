"""Story health (docs/PLAN_drama.md part A): computed by code from chapters, no model call."""
import copy

from sim import health, state as S
from test_sim_api import client, new_story, wait  # noqa: F401

TRACKERS = [
    {"id": "m1", "kind": "meter", "name": "Stamina", "min": 0, "max": 100, "start": 80},
    {"id": "m2", "kind": "meter", "name": "Noise", "min": 0, "max": 100, "start": 10, "danger_above": 70},
    {"id": "c1", "kind": "clock", "name": "Pressure", "max": 6, "start": 0},
    {"id": "r1", "kind": "relation", "name": "A and B", "a": "A", "b": "B", "start": {"trust": 1, "tension": 0}},
    {"id": "i1", "kind": "items", "name": "Things", "start": {}},
]


def st(m1=80, m2=10, c1=0, trust=1, tension=0, items=None, alive=True, status=""):
    return {"time": "", "trackers": {"m1": m1, "m2": m2, "c1": c1, "r1": {"trust": trust, "tension": tension}, "i1": items or {}}, "entities": {"A": {"alive": alive, "status": status}}}


def test_endings_are_classified():
    k = health.ending_kind
    assert k("They stop. To the left, a path opens into the dairy; to the right, the dense shelves.") == "menu"
    assert k("He could take either path, and neither felt safe.") == "menu"
    assert k("The line went dead. Who had been listening?") == "question"
    assert k("She understood then that the letter was forged.") == "reveal"
    assert k("He had to decide, and the clock was running.") == "decision"
    assert k("Behind them the door opened. Footsteps.") == "hook"
    assert k("They ate in silence by the window") in ("plain", "hook")


def test_costs_come_from_what_got_worse_whatever_the_story_tracks():
    before = st()
    assert health.diff_costs(before, copy.deepcopy(before), TRACKERS) == []
    after = st(m1=50, m2=60, c1=2, trust=0, tension=2, items={"Rope": {"qty": 1, "at": "A", "props": {"condition": "damaged"}}}, status="limping")
    text = " | ".join(x.split("|", 1)[1] for x in health.diff_costs(before, after, TRACKERS))
    assert "Stamina fell by 30" in text and "Noise rose by 50" in text and "Pressure moved to 2/6" in text and "trust fell" in text and "tension rose" in text and "A: limping" in text
    better = st(m1=95, m2=5)                                     # a meter that rises or a danger meter that falls costs nothing
    assert health.diff_costs(before, better, TRACKERS) == []
    died = health.diff_costs(before, st(alive=False), TRACKERS)
    assert any(x.startswith("4|") for x in died)


def test_a_chapter_with_failed_rolls_scores_higher_than_a_calm_one():
    calm = {"idx": 1, "rolls": [{"tier": "success"}], "state_before": st(), "state_after": st(m1=78), "prose": "x. y."}
    hard = {"idx": 2, "rolls": [{"tier": "fail"}, {"tier": "partial"}], "state_before": st(), "state_after": st(m1=60, c1=1), "prose": "x. y."}
    a, b = health.chapter_numbers(calm, TRACKERS), health.chapter_numbers(hard, TRACKERS)
    assert a["free"] and not b["free"] and b["intensity"] > a["intensity"] and b["points"] >= 5


def test_verdicts_name_the_audited_problems():
    chs = [{"idx": i, "free": True, "intensity": 3, "ending": e, "tiers": {"success": 2}} for i, e in ((1, "plain"), (2, "menu"), (3, "menu"))]
    r = {"dice": {"rolls": 6, "tiers": {"success": 6}, "free_streak": 3}, "intensity": [3, 3, 3], "endings": ["plain", "menu", "menu"],
         "spotlight": {"Elias": {"mentions": [4, 6, 4], "away": 0, "share": 0.7}, "Silas": {"mentions": [0, 3, 0], "away": 1, "share": 0.1}, "Sarah": {"mentions": [1, 0, 0], "away": 3, "share": 0.2}},
         "material": [{"who": "Sarah", "kind": "secret", "text": "x", "last": 0, "age": 3}], "threads": [{"text": "Who knocked?", "age": 5}], "repeated": [{"word": "heavy", "count": 10, "per_1000": 8.6}],
         "options": {"duplicates": 2, "errands": 3, "per_person": {}}, "clocks": [{"name": "Dawn", "at": 1, "max": 40, "per_chapter": 0.33, "full_in": 117}]}
    text = " | ".join(v["text"] for v in health.verdicts(r, chs, [], 3))
    for part in ("3 chapters in a row", "All 6 rolls succeeded", "menu of routes", "Sarah has not been", "Elias carries the story", "Sarah's secret", "open thread", "'heavy'", "same move", "small errands", "117 more chapters"):
        assert part in text, part
    ok = {**r, "dice": {"rolls": 4, "tiers": {"success": 2, "fail": 2}, "free_streak": 0}, "intensity": [3, 5, 7], "endings": ["hook", "reveal", "decision"],
          "spotlight": {"A": {"mentions": [2], "away": 0, "share": 0.4}, "B": {"mentions": [2], "away": 0, "share": 0.3}, "C": {"mentions": [2], "away": 0, "share": 0.3}}, "material": [], "threads": [], "repeated": [], "options": {"duplicates": 0, "errands": 0, "per_person": {}}, "clocks": []}
    assert [v["level"] for v in health.verdicts(ok, chs, [], 3)] == ["ok"]


def test_the_story_detail_carries_the_health_report_and_the_card_reads_it(client):
    c = client
    pid = new_story(c)
    assert c.get(f"/api/sim/{pid}").json()["health"] == {"chapters": 0, "per_chapter": [], "verdicts": []}
    c.post(f"/api/sim/{pid}/start")
    wait(c, pid)
    for _ in range(2):
        c.post(f"/api/sim/{pid}/chapters", json={"kind": "auto"})
        wait(c, pid)
    h = c.get(f"/api/sim/{pid}").json()["health"]
    assert h["chapters"] == 3 and len(h["intensity"]) == 3 and len(h["endings"]) == 3 and h["dice"]["rolls"] >= 3 and set(h["spotlight"]) >= {"Ravi"} and h["verdicts"]
    js = open("static/sim.js", encoding="utf-8").read()
    assert "healthHtml" in js and "Story health" in js and "tension ${pc.intensity}/10" in js
