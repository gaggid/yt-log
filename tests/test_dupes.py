"""Task 4.5: near-duplicate picture detection."""
from PIL import Image, ImageDraw

from story3 import dupes


def pic(path, kind):
    im = Image.new("RGB", (320, 180), (200, 180, 140) if kind != "blue" else (30, 60, 150))
    d = ImageDraw.Draw(im)
    if kind in ("a", "a2"):
        d.rectangle((40 + (3 if kind == "a2" else 0), 30, 160, 150), fill=(40, 40, 40))
    if kind == "b":
        d.ellipse((180, 20, 300, 160), fill=(220, 60, 40))
        d.rectangle((0, 120, 320, 180), fill=(20, 90, 30))
    im.save(path)
    return path


def test_the_same_picture_twice_is_found_and_different_ones_are_not(tmp_path):
    a, a2, b, blue = (dupes.fingerprint(pic(tmp_path / f"{k}.png", k)) for k in ("a", "a2", "b", "blue"))
    assert dupes.same(a, a2)
    assert not dupes.same(a, b) and not dupes.same(a, blue) and not dupes.same(b, blue)
    bits, hist = dupes.distance(a, a)
    assert bits == 0 and hist == 0


def test_find_flags_the_later_scene_of_a_pair(env):
    import asyncio
    from story2 import events, planner, storyboard
    from story3 import store
    from test_chain_v2 import ChainFake
    from test_narration_v2 import ready
    pid, be = ready(env)
    asyncio.run(planner.make_narration(pid, be))
    cf = ChainFake()
    asyncio.run(events.make_events(pid, cf))
    asyncio.run(storyboard.make_registry(pid, cf))
    asyncio.run(storyboard.make_storyboard(pid, cf))
    sc = sorted(storyboard.get_scenes(pid), key=lambda s: (s["start_s"], s["seq"]))
    d = store.media_dir(pid, "scenes")
    for k, s in enumerate(sc[:3]):
        kind = "a" if k != 2 else "b"
        path = pic(d / f"{s['id']}.png", kind)
        it = store.add(pid, "scene", s["id"], 0, "running", {})
        store.update(it["id"], status="done", file=f"scenes/{s['id']}.png", meta={})
    hits = dupes.find(pid)
    assert [h["scene"] for h in hits] == [sc[1]["id"]] and hits[0]["earlier"] == sc[0]["id"] and "change" in hits[0]["why"]
    assert dupes.note_for(pid, sc[1]["id"]) and dupes.note_for(pid, sc[2]["id"]) == ""


def test_the_judge_asks_whether_the_moment_is_shown_and_a_miss_is_a_hard_problem():
    from story3 import refscore, scenes
    assert any(k == "event_fit" for k, _ in refscore.SCENE_DIMS)
    auto = {"score": 80, "reasons": []}
    seen = {"dims": {"event_fit": 2, "story_fit": 9, "characters_match": 9}, "score": 80, "defects": [], "extras": [], "text_visible": False, "text_read": ""}
    r = refscore.combine_scene(auto, seen, [])
    assert r["hard"] and r["total"] <= 49 and r["event_fit"] == 20 and any("moment" in f for f in r["flags"])
    ok = refscore.combine_scene(auto, {**seen, "dims": {**seen["dims"], "event_fit": 9}}, [])
    assert not ok["hard"] and ok["event_fit"] == 90
    row = {"best_item": {"score": {"flags": ["not in the brief: a second man", "looks wrong: six fingers", "text or marks in the picture"]}}}
    ch = scenes.change_for(row, "different place")
    assert ch.startswith("remove a second man") and "fix six fingers" in ch and ch.endswith("different place")
    assert scenes.change_for({"best_item": {"score": {"flags": []}}}) == "" and scenes.change_for({}) == ""
