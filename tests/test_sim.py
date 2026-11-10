"""The story simulator: state rules, dice, memory packet, the chapter engine, seed, directives, branches, delete. The model is a scripted fake (tests/sim_fakes.py)."""
import asyncio

import pytest

from sim import dice, engine, memory, models as m, seed, state as S, store
from sim_fakes import SimFake, words
from story import db, settings as settings_mod


def run(co):
    return asyncio.run(co)


def cfg():
    return {**settings_mod.get(), "retries": 1, "retry_backoff_s": 0}


@pytest.fixture
def sm(env):
    store.ensure()
    return env


def make(fake=None, template=""):
    fake = fake or SimFake()
    p = store.create_project("A night-shift salesman is trapped in a supermarket when an outbreak starts", template_id=template)
    run(seed.seed_all(p["id"], fake, cfg()))
    return p["id"], fake


def go(pid, fake, **kw):
    return run(engine.run_chapter(pid, fake, cfg(), **kw))


# ── state ─────────────────────────────────────────────────────────────────────

def test_seed_builds_a_valid_setup(sm):
    pid, fake = make()
    assert store.world(pid)["place"] == "Fairview Supermarket"
    assert [e["name"] for e in store.entities(pid, "character")] == ["Ravi", "Meera", "Dev", "Sana"]
    kinds = {t["kind"] for t in store.trackers(pid)}
    assert kinds == {"items", "meter", "clock", "relation", "location", "knowledge", "flag"}
    assert len([g for g in store.guidelines(pid) if g["grp"] == "hard"]) == 2
    items = next(t for t in store.trackers(pid) if t["kind"] == "items")
    assert items["start"]["Crowbar"]["qty"] == 1
    assert S.validate_setup(store.trackers(pid), store.entities(pid)) == []


def test_validate_setup_lists_what_is_missing(sm):
    p = store.create_project("x")
    assert S.validate_setup([], []) == ["add at least one character", "add at least one place", "add a clock or a meter so something is at stake"]


def _ctx(pid, allow_death=True):
    ents = store.entities(pid)
    return S.Ctx(store.trackers(pid), [e["name"] for e in ents], [e["name"] for e in ents if e["kind"] == "place"], store.world(pid)["exists"], allow_death,
                 {e["name"]: e.get("description", "") for e in ents if e["kind"] == "place"})


def op(**k):
    return m.Op(**k)


def test_an_item_cannot_appear_from_nothing(sm):
    pid, _ = make()
    st = S.initial_state(store.trackers(pid), store.entities(pid), store.world(pid))
    new, applied, dropped = S.apply_ops(st, [op(op="item_add", target="Rocket launcher", qty=1)], _ctx(pid))
    assert not applied and "can only appear" in dropped[0]["why"]
    new, applied, dropped = S.apply_ops(st, [op(op="item_add", target="Rope", qty=2, source="Aisle Two", to="Ravi")], _ctx(pid))
    items = next(t for t in store.trackers(pid) if t["kind"] == "items")
    assert applied and new["trackers"][items["id"]]["Rope"]["qty"] == 2


def test_crafting_needs_the_parts_to_be_used_up_first(sm):
    pid, _ = make()
    st = S.initial_state(store.trackers(pid), store.entities(pid), store.world(pid))
    items = next(t for t in store.trackers(pid) if t["kind"] == "items")
    ops = [op(op="item_remove", target="Crowbar", qty=1), op(op="item_add", target="Spiked bat", parts=["Crowbar"])]
    new, applied, dropped = S.apply_ops(st, ops, _ctx(pid))
    assert len(applied) == 2 and "Spiked bat" in new["trackers"][items["id"]] and "Crowbar" not in new["trackers"][items["id"]]
    new, applied, dropped = S.apply_ops(st, [op(op="item_add", target="Spiked bat", parts=["Crowbar"])], _ctx(pid))
    assert dropped and not applied


def test_more_than_is_there_cannot_be_used(sm):
    pid, _ = make()
    st = S.initial_state(store.trackers(pid), store.entities(pid), store.world(pid))
    _, applied, dropped = S.apply_ops(st, [op(op="item_remove", target="Canned beans", qty=9)], _ctx(pid))
    assert not applied and dropped


def test_meters_clamp_clocks_move_forward_and_the_dead_stay_dead(sm):
    pid, _ = make()
    trk = {t["name"]: t for t in store.trackers(pid)}
    st = S.initial_state(store.trackers(pid), store.entities(pid), store.world(pid))
    new, applied, dropped = S.apply_ops(st, [op(op="meter_change", tracker="Group morale", amount=-9)], _ctx(pid))
    assert new["trackers"][trk["Group morale"]["id"]] == 1          # limited to half the range (5), 6 - 5
    assert dropped[0].get("partial")
    new, applied, dropped = S.apply_ops(st, [op(op="clock_advance", tracker="Horde nears", amount=9)], _ctx(pid))
    assert new["trackers"][trk["Horde nears"]["id"]] == 6
    _, _, dropped = S.apply_ops(st, [op(op="clock_set", tracker="Horde nears", value=0)], _ctx(pid))
    assert dropped and "reason" in dropped[0]["why"]
    new, applied, _ = S.apply_ops(st, [op(op="entity_dies", target="Dev", why="overrun")], _ctx(pid))
    assert not new["entities"]["Dev"]["alive"]
    _, a2, d2 = S.apply_ops(new, [op(op="move", target="Dev", to="Pharmacy"), op(op="learn", tracker="Why the dead walk", target="The source", who="Dev")], _ctx(pid))
    assert not a2 and len(d2) == 2
    _, a3, d3 = S.apply_ops(st, [op(op="entity_dies", target="Dev", why="x")], _ctx(pid, allow_death=False))
    assert not a3 and "allows" in d3[0]["why"]


def test_locked_places_and_unknown_names_are_refused(sm):
    pid, _ = make()
    st = S.initial_state(store.trackers(pid), store.entities(pid), store.world(pid))
    st1, _, _ = S.apply_ops(st, [op(op="lock", target="Pharmacy")], _ctx(pid))
    _, a, d = S.apply_ops(st1, [op(op="move", target="Ravi", to="Pharmacy")], _ctx(pid))
    assert not a and "locked" in d[0]["why"]
    _, a, d = S.apply_ops(st, [op(op="move", target="Ghost", to="Pharmacy"), op(op="meter_change", tracker="Nothing", amount=1)], _ctx(pid))
    assert not a and len(d) == 2


# ── dice ──────────────────────────────────────────────────────────────────────

def test_dice_are_seeded_and_use_the_trackers(sm):
    pid, _ = make()
    trackers = store.trackers(pid)
    st = S.initial_state(trackers, store.entities(pid), store.world(pid))
    risk = {"who": "Ravi", "act": "barricade", "stats": ["Group morale"], "items": ["Crowbar"], "difficulty": "normal"}
    a = dice.roll(risk, st, trackers, 5, 1, 1, "fair")
    assert a == dice.roll(risk, st, trackers, 5, 1, 1, "fair")
    assert any(dice.roll(risk, st, trackers, 5, 1, 1, "fair", salt=str(i))["die"] != a["die"] for i in range(30))                 # a new salt changes the dice
    assert a["mod"] >= 1 and a["target"] == 12 and a["tier"] in dice.TIERS
    assert dice.roll(risk, st, trackers, 5, 1, 1, "brutal")["target"] == 14 and dice.roll(risk, st, trackers, 5, 1, 1, "gentle")["target"] == 10
    assert dice.free(risk, 1)["tier"] == "success"


def test_every_tier_can_happen(sm):
    pid, _ = make()
    trackers = store.trackers(pid)
    st = S.initial_state(trackers, store.entities(pid), store.world(pid))
    seen = {dice.roll({"act": "x", "difficulty": "hard"}, st, trackers, i, 1, 1, "brutal")["tier"] for i in range(400)}
    assert seen == set(dice.TIERS)


# ── the chapter engine ────────────────────────────────────────────────────────

def test_chapter_one_runs_every_stage_and_stores_it(sm):
    pid, fake = make()
    ch = go(pid, fake)
    assert ch["status"] == "done" and ch["idx"] == 1 and ch["parent_id"] == ""
    assert 280 <= len(ch["prose"].split()) <= 430 and ch["title"] == "Beat 1"
    assert ch["rolls"] and ch["rolls"][0]["tier"] in dice.TIERS
    assert [o["id"] for o in ch["options"]] == ["o1", "o2", "o3", "o4"]
    assert sum(1 for o in ch["options"] if o["risk"] == "high") <= 1
    assert ch["delta"]["dropped"] and "Rocket launcher" in str(ch["delta"]["dropped"])        # the invented item was refused
    clock = next(t for t in store.trackers(pid) if t["kind"] == "clock")
    assert ch["state_after"]["trackers"][clock["id"]] == ch["state_before"]["trackers"][clock["id"]] + 1
    assert ch["state_after"]["time"] == "Day 1"
    assert store.project(pid)["head_id"] == ch["id"] and store.project(pid)["status"] == "running"
    assert store.facts(pid) and store.threads(pid)
    chapter_tasks = [c["task"] for c in fake.calls if c["task"] not in ("sm_world", "sm_cast", "sm_trackers", "sm_rules", "sm_bible", "sm_beats")]
    n_actors = fake.count("sm_actor")
    assert n_actors >= 1 and all(t == "sm_actor" for t in chapter_tasks[:n_actors])
    assert chapter_tasks[n_actors:] == ["sm_plan", "sm_delta", "sm_write", "sm_referee", "sm_archive"]
    assert fake.count("sm_plan") == fake.count("sm_write") == fake.count("sm_referee") == fake.count("sm_archive") == 1


def test_chapter_two_continues_from_the_option_and_the_state(sm):
    pid, fake = make()
    c1 = go(pid, fake)
    c2 = go(pid, fake, action={"kind": "option", "option_id": "o2"})
    assert c2["idx"] == 2 and c2["parent_id"] == c1["id"] and c2["state_before"] == c1["state_after"]
    assert "Ravi tries plan number" not in c2["prose"]
    assert "PLAYER'S ACTION" in fake.last("sm_plan")["user"] and "plan number 2" in fake.last("sm_plan")["user"]
    assert "Beat 1" in fake.last("sm_plan")["user"]                           # the last chapter's ending is in the packet
    assert [p["id"] for p in store.path(pid)] == [c1["id"], c2["id"]]


def test_the_owners_text_must_show_in_the_plan(sm):
    pid, fake = make()
    go(pid, fake)
    c2 = go(pid, fake, action={"kind": "text", "text": "barricade the doors with pallets", "who": "Ravi"})
    assert "barricade" in fake.last("sm_plan")["user"] and "<owner>barricade the doors with pallets</owner>" in fake.last("sm_plan")["user"]
    assert c2["chosen"]["kind"] == "text"


def test_a_wrong_length_is_sent_back_once_then_accepted_and_flagged(sm):
    fake = SimFake(prose_words=100)
    pid, _ = make(fake)
    ch = go(pid, fake)
    assert fake.count("sm_write") == 2 and ch["status"] == "done" and ch["flags"]["words"] == 100


def test_the_referee_rewrites_once_then_flags(sm):
    bad = lambda user, n: {"ok": False, "violations": [{"rule": "R1", "quote": "w1 w2", "fix": "remove it"}]}
    fake = SimFake(sm_referee=bad)
    pid, _ = make(fake)
    ch = go(pid, fake)
    assert fake.count("sm_write") == 2 and fake.count("sm_referee") == 2
    assert ch["flags"]["rule_break"] and ch["flags"]["referee"] == "broken"
    assert "FIX THESE PROBLEMS" in [c for c in fake.calls if c["task"] == "sm_write"][1]["user"]
    assert ch["status"] == "done"
    ok_second = lambda user, n: {"ok": True, "violations": []} if n > 1 else {"ok": False, "violations": [{"rule": "continuity", "quote": "w3", "fix": "fix"}]}
    fake2 = SimFake(sm_referee=ok_second)
    pid2, _ = make(fake2)
    ch2 = go(pid2, fake2)
    assert ch2["flags"]["referee"] == "fixed" and not ch2["flags"].get("rule_break")


def test_a_soft_rule_does_not_force_a_rewrite(sm):
    pid, fake = make()
    tone = next(g for g in store.guidelines(pid) if g["grp"] == "tone")
    labels = memory.rules_text(pid)[1]
    label = next(k for k, v in labels.items() if v == tone["id"])
    fake.answers["sm_referee"] = {"ok": False, "violations": [{"rule": label, "quote": "w1", "fix": "lighter"}]}
    ch = go(pid, fake)
    assert fake.count("sm_write") == 1 and ch["flags"]["soft"] and not ch["flags"].get("rule_break")


def test_options_are_checked_and_never_a_dead_end(sm):
    pid, _ = make()
    dup = lambda user, n: {"summary": "s", "facts": [], "options": [{"who": "Ravi", "label": "open the shutter wide", "risk": "high"}, {"who": "Ravi", "label": "open the shutter wide now", "risk": "high"},
                                                                  {"who": "Ghost", "label": "haunt", "risk": "low"}]}
    fake = SimFake(sm_archive=dup)
    ch = go(pid, fake)
    assert ch["options"] and all(o["who"] == "Ravi" or o["label"].startswith("Carry on") for o in ch["options"])
    assert len(ch["options"]) == 1


def test_a_stage_failure_can_be_resumed_from_that_stage(sm):
    pid, fake = make()

    def boom(user, n):
        raise RuntimeError("gateway down")
    fake.answers["sm_write"] = boom
    with pytest.raises(Exception):
        go(pid, fake)
    ch = store.chapters(pid)[0]
    assert ch["status"] == "failed" and set(ch["flags"]["done"]) >= {"gather", "plan", "resolve", "delta"} and "write" not in ch["flags"]["done"]
    assert store.project(pid)["head_id"] == ""
    plans = fake.count("sm_plan")
    del fake.answers["sm_write"]
    done = go(pid, fake, resume_id=ch["id"])
    assert done["status"] == "done" and fake.count("sm_plan") == plans and store.project(pid)["head_id"] == done["id"]


def test_a_chapter_left_writing_is_marked_failed_at_start_up(sm):
    pid, fake = make()
    ch = store.add_chapter(pid, "")
    assert store.repair() >= 1 and store.chapter(ch["id"])["status"] == "failed"


def test_stop_leaves_a_resumable_chapter(sm):
    pid, fake = make()
    with pytest.raises(engine.Stopped):
        go(pid, fake, cancel=lambda: True)
    assert store.chapters(pid)[0]["status"] == "failed" and store.run_info(pid)["stopped"]


def test_dice_off_makes_every_act_succeed(sm):
    pid, fake = make()
    store.save_project(pid, settings={"dice": False})
    ch = go(pid, fake)
    assert ch["rolls"] and all(r["tier"] == "success" and r.get("dice_off") for r in ch["rolls"])


def test_the_cast_minds_stage_is_gone(sm):
    from sim import engine
    assert "minds" not in engine.STAGES and "deep" not in store.DEFAULT_SETTINGS
    pid, fake = make()
    go(pid, fake)
    assert fake.count("sm_minds") == 0


# ── directives ────────────────────────────────────────────────────────────────

def test_a_next_instruction_must_be_handled_and_fires_once(sm):
    pid, fake = make()
    d = store.save_directive(pid, {"kind": "event", "text": "Raiders arrive at the loading bay", "timing": {"mode": "next"}})
    c1 = go(pid, fake)
    assert c1["fired"] == [d["id"]] and "Raiders arrive" in fake.last("sm_plan")["user"] and "Raiders arrive" in fake.last("sm_write")["user"]
    c2 = go(pid, fake, action={"kind": "auto"})
    assert c2["fired"] == [] and "Raiders arrive" not in fake.last("sm_plan")["user"]


def test_an_in_n_instruction_waits_for_its_chapter(sm):
    pid, fake = make()
    c1 = go(pid, fake)
    store.save_directive(pid, {"kind": "event", "text": "The power fails", "timing": {"mode": "in", "chapters": 2}})
    c2 = go(pid, fake)
    assert c2["fired"] == []
    c3 = go(pid, fake)
    assert len(c3["fired"]) == 1


def test_a_tracker_condition_fires_when_the_clock_is_full(sm):
    pid, fake = make()
    d = store.save_directive(pid, {"kind": "twist", "text": "Dev betrays the group", "timing": {"mode": "when", "tracker": "Horde nears", "op": "full"}})
    c1 = go(pid, fake)
    assert c1["fired"] == []
    clock = next(t for t in store.trackers(pid) if t["kind"] == "clock")
    head = store.chapter(c1["id"])
    st = head["state_after"]
    st["trackers"][clock["id"]] = 6
    store.update_chapter(head["id"], state_after=st)
    c2 = go(pid, fake)
    assert c2["fired"] == [d["id"]]


def test_a_text_condition_asks_the_model_and_may_wait(sm):
    pid, fake = make()
    go(pid, fake)
    store.save_directive(pid, {"kind": "event", "text": "Helicopter passes", "timing": {"mode": "when", "condition": "when the power fails"}})
    c2 = go(pid, fake)
    assert fake.count("sm_condition") == 1 and c2["fired"] == []
    fake.answers["sm_condition"] = {"met": True, "why": "lights died"}
    c3 = go(pid, fake)
    assert len(c3["fired"]) == 1


def test_a_cancelled_instruction_never_fires(sm):
    pid, fake = make()
    d = store.save_directive(pid, {"kind": "event", "text": "Hail", "timing": {"mode": "next"}})
    store.cancel_directive(pid, d["id"])
    assert go(pid, fake)["fired"] == []


# ── branches and memory ───────────────────────────────────────────────────────

def test_branches_do_not_share_facts_threads_or_fired_instructions(sm):
    pid, fake = make()
    c1 = go(pid, fake)
    d = store.save_directive(pid, {"kind": "event", "text": "Raiders", "timing": {"mode": "next"}})
    a = go(pid, fake, action={"kind": "option", "option_id": "o1"})
    assert a["fired"] == [d["id"]]
    b = go(pid, fake, parent_id=c1["id"], action={"kind": "option", "option_id": "o3"}, label="other way")
    assert b["parent_id"] == c1["id"] and b["fired"] == [d["id"]]                      # fired again on its own line
    assert {c["id"] for c in store.children(pid, c1["id"])} == {a["id"], b["id"]}
    path_a = store.path(pid, a["id"])
    path_b = store.path(pid, b["id"])
    assert memory.fired_ids(path_a) == memory.fired_ids(path_b) == {d["id"]}
    assert {f["chapter_id"] for f in memory.path_facts(pid, path_a)} == {c1["id"], a["id"]}
    assert {f["chapter_id"] for f in memory.path_facts(pid, path_b)} == {c1["id"], b["id"]}
    assert {t["opened_in"] for t in memory.open_threads(pid, path_b)} == {c1["id"], b["id"]}
    assert store.project(pid)["head_id"] == b["id"]


def test_the_packet_drops_low_priority_parts_first_and_never_cuts_one(sm):
    pid, fake = make()
    go(pid, fake)
    path = store.path(pid)
    pk = memory.build(pid, path, path[-1]["state_after"], ["Ravi"], "Ravi at the doors")
    full = pk.text(100000, lambda t: len(t) // 4)
    assert "REMEMBERED FACTS" in full and "OTHER PEOPLE AND PLACES" in full
    pk2 = memory.build(pid, path, path[-1]["state_after"], ["Ravi"], "Ravi at the doors")
    small = pk2.text(len(full) // 4 - 60, lambda t: len(t) // 4)
    assert pk2.trimmed and pk2.trimmed[0] == "REMEMBERED FACTS" and "WORLD" in small and "STATE" in small
    assert all(not t.startswith("##") or t.split("\n")[0][3:] in small for t in ["## WORLD"])


def test_a_long_story_is_rolled_up(sm):
    pid, fake = make()
    for _ in range(13):
        go(pid, fake)
    path = store.path(pid)
    rolled = [c for c in path if c["flags"].get("rollup")]
    assert len(rolled) == 1 and rolled[0]["idx"] == 8 and fake.count("sm_rollup") == 1
    text, after = memory.story_so_far(path)
    assert text and len(after) == 5
    go(pid, fake)
    assert "STORY SO FAR" in fake.last("sm_plan")["user"]


def test_no_names_leak_between_stories(sm):
    pid, fake = make()
    go(pid, fake)
    pid2 = store.create_project("A court case")["id"]
    store.save_entity(pid2, {"kind": "character", "name": "Judge Iyer", "role": "judge"})
    store.save_entity(pid2, {"kind": "place", "name": "Courtroom 4", "description": "a court"})
    store.save_tracker(pid2, {"kind": "clock", "name": "Days to verdict", "max": 5, "start": 1})
    store.set_world(pid2, {"place": "High court"})
    path = store.path(pid2)
    st = S.initial_state(store.trackers(pid2), store.entities(pid2), store.world(pid2))
    text = memory.render(memory.build(pid2, path, st, None, ""))
    assert "Ravi" not in text and "Fairview" not in text and "Judge Iyer" in text


# ── steering ──────────────────────────────────────────────────────────────────

def test_let_it_run_picks_an_option_and_auto_run_stops_on_a_death(sm):
    pid, fake = make()
    c1 = go(pid, fake)
    act = run(engine.pick_option(pid, fake, cfg(), c1))
    assert act == {"kind": "option", "option_id": "o2"}
    res = run(engine.auto_run(pid, 3, fake, cfg()))
    assert res["made"] == 3 and not res["stopped_because"]
    # a death stops it
    def kill(user, n):
        return {"ops": [{"op": "entity_dies", "target": "Dev", "why": "overrun"}]}
    fake.answers["sm_delta"] = kill
    fake.answers["sm_pick"] = {"option": "o1"}
    store.save_project(pid, settings={"dice": False})                      # with dice on a death needs a failed roll
    pid2 = pid
    res = run(engine.auto_run(pid2, 5, fake, cfg()))
    assert res["made"] == 1 and "Dev died" in res["stopped_because"]


def test_auto_run_stops_when_asked(sm):
    pid, fake = make()
    go(pid, fake)
    n = {"c": 0}

    def cancel():
        n["c"] += 1
        return n["c"] > 12
    res = run(engine.auto_run(pid, 10, fake, cfg(), cancel=cancel))
    assert 0 <= res["made"] < 10 or res["stopped_because"] == "stopped"


def test_hand_edit_reread_proposes_and_applies_and_marks_later_chapters_stale(sm):
    pid, fake = make()
    c1 = go(pid, fake)
    c2 = go(pid, fake)
    prop = run(engine.reread(pid, c1["id"], fake, cfg()))
    assert prop["preview"] and prop["note"]
    out = engine.apply_reread(pid, c1["id"], prop["ops"])
    assert out["state_after"]["entities"]["Ravi"]["status"] == "limping"
    assert store.chapter(c2["id"])["flags"]["stale"] is True


def test_suggested_rules_are_new_and_the_version_counter_moves(sm):
    pid, fake = make()
    v = store.project(pid)["settings"]["rules_version"]
    made = run(seed.suggest_rules(pid, fake, cfg()))
    assert len(made) == 1 and made[0]["origin"] == "ai"
    assert store.project(pid)["settings"]["rules_version"] > v
    assert run(seed.suggest_rules(pid, fake, cfg())) == []                          # the same rule again is not added twice


def test_redoing_the_cast_is_refused_after_the_story_started(sm):
    pid, fake = make()
    go(pid, fake)
    with pytest.raises(store.SimError):
        run(seed.seed_cast(pid, fake, cfg()))


# ── the engine knows no genre ─────────────────────────────────────────────────

def test_a_courtroom_story_runs_on_the_same_engine(sm):
    fake = SimFake()
    p = store.create_project("A junior lawyer defends a client against a powerful prosecutor")
    pid = p["id"]
    store.set_world(pid, {"place": "County court", "exists": "Exhibit A: a torn receipt. Witness list: a baker, a clerk.", "start_time": "Day 1, 09:00"})
    for n, r in (("Asha", "defence lawyer"), ("Mr Rao", "prosecutor"), ("Judge Bose", "judge")):
        store.save_entity(pid, {"kind": "character", "name": n, "role": r, "goal": "win", "fear": "losing"})
    store.save_entity(pid, {"kind": "place", "name": "Courtroom", "description": "the main hall"})
    store.save_tracker(pid, {"kind": "meter", "name": "Jury support", "min": 0, "max": 10, "start": 5})
    store.save_tracker(pid, {"kind": "clock", "name": "Days to verdict", "max": 5, "start": 0})
    store.save_tracker(pid, {"kind": "knowledge", "name": "Evidence", "start": {"The receipt is torn": ["Asha"]}})
    store.save_guideline(pid, {"grp": "hard", "text": "Only evidence already introduced may be used."})
    assert S.validate_setup(store.trackers(pid), store.entities(pid)) == []
    c1 = go(pid, fake)
    c2 = go(pid, fake, action={"kind": "option", "option_id": "o1"})
    assert c1["status"] == c2["status"] == "done" and c2["state_before"]["trackers"] == c1["state_after"]["trackers"]
    assert "Asha" in fake.last("sm_plan")["user"] and "Ravi" not in fake.last("sm_plan")["user"]
    jury = next(t for t in store.trackers(pid) if t["name"] == "Jury support")
    cost = [a for a in c1["delta"]["applied"] if a["op"] == "cost"]                       # a failed or partial act with no real cost gets one added by the system
    from sim import drama
    step = max([max(1, round(10 * drama.COST_PERCENT[r["tier"]])) for r in c1["rolls"] if r["tier"] in drama.COST_PERCENT] or [0])
    assert c1["state_after"]["trackers"][jury["id"]] == (4 if not cost else 4 - step)


# ── delete ────────────────────────────────────────────────────────────────────

def test_deleting_a_story_leaves_nothing(sm, tmp_path):
    pid, fake = make()
    c1 = go(pid, fake)
    store.save_directive(pid, {"kind": "event", "text": "x", "timing": {"mode": "next"}})
    from story3 import store as media
    media.ensure()
    media.media_dir(pid).joinpath("f.png").write_bytes(b"x")
    media.add(pid, "sim_panel", f"{c1['id']}:1")
    store.set_run(pid, stage="x")
    other = store.create_project("another story")["id"]
    store.delete_project(pid)
    for t in store.TABLES:
        assert db.one(f"SELECT 1 FROM {t} WHERE project_id=?", (pid,)) is None, t
    assert db.one("SELECT 1 FROM sim_projects WHERE id=?", (pid,)) is None
    assert db.one("SELECT 1 FROM media WHERE plan_id=?", (pid,)) is None
    assert not (tmp_path / "media" / pid).exists()
    assert store.project(other)
    with pytest.raises(store.SimError):
        store.project(pid)


def test_only_a_leaf_chapter_can_be_deleted(sm):
    pid, fake = make()
    c1 = go(pid, fake)
    c2 = go(pid, fake)
    with pytest.raises(store.SimError):
        store.delete_chapter(pid, c1["id"])
    store.delete_chapter(pid, c2["id"])
    assert store.project(pid)["head_id"] == c1["id"] and not [f for f in store.facts(pid) if f["chapter_id"] == c2["id"]]
