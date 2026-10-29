"""Task 3.11: the repair sweep turns repeating face scenes into object or place pictures."""
import asyncio

from story import db
from story2 import audit, events, planner, storyboard, worldfix
from test_chain_v2 import ChainFake
from test_narration_v2 import ready


def boarded(env):
    pid, be = ready(env)
    asyncio.run(planner.make_narration(pid, be))
    cf = ChainFake()
    asyncio.run(events.make_events(pid, cf))
    asyncio.run(storyboard.make_registry(pid, cf))
    asyncio.run(storyboard.make_storyboard(pid, cf))
    return pid


def put_person_everywhere(pid, close=True):
    p = planner.get_plan(pid)
    person = next(a["id"] for a in p["assets"] if a["kind"] == "person")
    for s in p["scenes"]:
        d = s["data"]
        d["continuity"] = {**d["continuity"], "assets": [person] + [x for x in d["continuity"].get("assets", []) if x != person]}
        d["composition"] = {**d["composition"], "distance": "close" if close else "wide"}
        d.pop("converted", None)
        db.ex("UPDATE scenes SET data=? WHERE id=?", (db.jdump(d), s["id"]))


def share(pid):
    p = planner.get_plan(pid)
    people = audit._people(p)
    n = len(p["scenes"])
    return sum(1 for s in p["scenes"] if audit._scene_people(s, people)) / n, n


def test_a_film_with_one_face_in_every_scene_is_brought_under_the_rules(env):
    pid = boarded(env)
    put_person_everywhere(pid)
    s0, n = share(pid)
    assert s0 == 1.0 and n >= 8
    changed = worldfix.sweep(pid)
    s1, _ = share(pid)
    assert changed >= 1 and s1 <= worldfix.MAX_PERSON_SHARE + 1 / n
    p = planner.get_plan(pid)
    card = audit.world(p)
    assert card["protagonist_share"]["value"] <= worldfix.MAX_PROTAGONIST + 1 / n and card["max_face_closeup_run"]["value"] <= worldfix.MAX_CLOSEUP_RUN
    conv = [s for s in p["scenes"] if s["data"].get("converted")]
    assert conv and all(not [a for a in s["data"]["continuity"]["assets"] if a in audit._people(p)] for s in conv)          # no person left in a converted scene
    assert all("study" in s["data"]["action"] for s in conv)


def test_locked_scenes_inserts_and_scenes_that_pass_are_left_alone(env):
    pid = boarded(env)
    put_person_everywhere(pid)
    for s in planner.get_plan(pid)["scenes"]:
        db.ex("UPDATE scenes SET locked=1 WHERE id=?", (s["id"],))
    assert worldfix.sweep(pid) == 0
    pid2 = boarded(env)
    put_person_everywhere(pid2, close=False)
    p = planner.get_plan(pid2)
    for s in p["scenes"][3:]:                                                       # only a third of the scenes show the person
        d = s["data"]
        d["continuity"]["assets"] = [a for a in d["continuity"]["assets"] if a not in audit._people(p)]
        db.ex("UPDATE scenes SET data=? WHERE id=?", (db.jdump(d), s["id"]))
    assert worldfix.sweep(pid2) == 0


def test_acts_set_the_camera_grammar_and_the_film_ends_on_a_pull_back():
    from story2 import director
    by = {str(i): {"shots": [{"move": m, "kind": "place", "event": f"e{i}{k}"} for k, m in enumerate(("tilt down", "push in", "hold"))]} for i in range(1, 9)}
    director.apply_acts(by, 8)
    assert [by[str(i)]["act"] for i in range(1, 9)] == [1, 1, 2, 2, 2, 2, 3, 3]
    for key, seg in by.items():
        for sh in seg["shots"]:
            assert sh["move"] in director.ACT_MOVES[seg["act"]] or (key == "8" and sh is seg["shots"][-1])
    assert by["8"]["shots"][-1]["move"] == "pull back"
    flat = [sh["move"] for k in sorted(by, key=int) for sh in by[k]["shots"]]
    assert all(a != b for a, b in zip(flat, flat[1:]))                                    # never the same move twice running


def test_point_of_view_shots_are_chosen_from_events_about_a_screen_or_a_window():
    from story2 import director
    evs = [{"id": f"e{i}", "key_object": o, "doing": d, "who": ["Asha"], "reveal": False} for i, (o, d) in enumerate([
        ("phone", "reads a message on the phone screen"), ("", "walks"), ("car", "watches from the car window"), ("", "sits"), ("CCTV camera", "the lane seen on the CCTV")])]
    by = {"1": {"shots": [{"event": e["id"], "kind": "object", "move": "drift"} for e in evs]}}
    n = director.mark_pov(by, evs)
    assert n == 3
    marked = [sh for sh in by["1"]["shots"] if sh.get("pov")]
    assert {sh["pov"]["through"] for sh in marked} == {"a phone screen", "a car window", "a CCTV camera"} and all(sh["pov"]["of"] == "Asha" for sh in marked)
    evs[0]["reveal"] = True
    by = {"1": {"shots": [{"event": e["id"], "kind": "object", "move": "drift"} for e in evs]}}
    assert director.mark_pov(by, evs) == 2                                               # a reveal keeps its own framing
