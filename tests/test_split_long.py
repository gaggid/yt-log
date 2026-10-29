"""Task 3.5: a scene that plays longer than eight seconds is split at sentence boundaries; the new scenes look at the same event from elsewhere."""
from story import db
from story2 import planner, storyboard
from test_phase2b import boarded


def one_long_scene(env):
    pid, cid, be, p = boarded(env)
    seg = sorted(p["segments"], key=lambda s: s["seq"])[0]
    scs = sorted([s for s in p["scenes"] if s["segment_id"] == seg["id"]], key=lambda s: s["seq"])
    with db.tx() as c:
        for extra in scs[1:]:
            c.execute("DELETE FROM scenes WHERE id=?", (extra["id"],))
        c.execute("UPDATE scenes SET s_from=1, s_to=? WHERE id=?", (len(seg["sentences"]), scs[0]["id"]))
    storyboard.retime(p["id"])
    return p["id"], seg, scs[0]["id"]


def test_long_scene_is_split_with_other_camera_and_covers_the_same_sentences(env):
    pid, seg, sid = one_long_scene(env)
    before = storyboard.get_scene(sid)
    assert before["duration_s"] > 8
    added = storyboard.split_long(pid, 8.0)
    assert added >= 1
    mine = sorted([s for s in storyboard.get_scenes(pid) if s["segment_id"] == seg["id"]], key=lambda s: s["seq"])
    assert mine[0]["id"] == sid and mine[0]["s_from"] == 1 and mine[-1]["s_to"] == len(seg["sentences"])
    assert all(a["s_to"] + 1 == b["s_from"] for a, b in zip(mine, mine[1:]))                       # every sentence is in exactly one scene
    assert len(mine) == 2                                                                          # the two sentences of the test narration are each longer than the limit: one scene each
    var = mine[1]["data"]
    assert var["variant_of"] == sid and var["prompts"] == {}
    assert (var["composition"]["distance"], var["composition"]["camera_angle"]) != (before["data"]["composition"]["distance"], before["data"]["composition"]["camera_angle"])
    assert var["direction"]["move"] != before["data"]["direction"]["move"]
    assert mine[0]["data"]["prompts"] == {}                                                        # the first part is drawn again too: its words changed


def test_short_scenes_and_locked_scenes_are_left_alone(env):
    pid, seg, sid = one_long_scene(env)
    storyboard.edit_scene(sid, {"locked": True})
    assert storyboard.split_long(pid, 8.0) == 0
    pid2, seg2, sid2 = one_long_scene(env)
    assert storyboard.split_long(pid2, 1000.0) == 0


def test_the_limit_is_a_plan_setting(env):
    pid, seg, sid = one_long_scene(env)
    p = planner.get_plan(pid)
    db.ex("UPDATE plans SET settings=? WHERE id=?", (db.jdump({**p["settings"], "max_scene_s": 3.0}), pid))
    many = storyboard.split_long(pid)
    assert many >= 1
