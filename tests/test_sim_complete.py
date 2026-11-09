"""Completeness checks for the story simulator (docs/PLAN_simulation.md sections 17, 20, 21): every call the page makes has an endpoint, every setting has an effect, the help text exists."""
import re
from pathlib import Path

from sim import api as sapi, engine, paint, seed, store
from sim_fakes import SimFake
from test_sim import cfg, go, make, run, sm  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "static" / "sim.js").read_text(encoding="utf-8")


def _routes() -> list[tuple[str, re.Pattern]]:
    out = []
    for r in sapi.router.routes:
        pat = "^" + re.sub(r"\{[^}]+\}", "[^/]+", r.path) + "$"
        for method in r.methods or []:
            out.append((method, re.compile(pat)))
    return out


def test_every_call_the_page_makes_has_an_endpoint():
    calls = set()
    for m in re.finditer(r"""(?:api\(|run\([^,]*,\s*|location = )[`'"]((?:/api)?/sim[^`'"]*|/[a-z/${}A-Z:]+)[`'"]""", JS):
        calls.add(m.group(1))
    paths = set()
    for m in re.finditer(r"""`(/sim[^`]*)`""", JS):
        paths.add(m.group(1))
    for m in re.finditer(r"""run\((?:btn|b|null|e\.target|au|go|let_|ar)[^,]*,\s*`([^`]+)`""", JS):
        paths.add("/sim/${SID}" + m.group(1))
    for m in re.finditer(r"""run\((?:btn|b|null|e\.target|au|go|let_|ar)[^,]*,\s*'([^']+)'""", JS):
        paths.add("/sim/${SID}" + m.group(1))
    for m in re.finditer(r"""/api(/sim/[^`'"?]*)""", JS):
        paths.add(m.group(1))
    paths = {p for p in paths if "${path}" not in p}
    assert len(paths) > 25, paths
    routes = _routes()
    missing = []
    for p in paths:
        p = p.split("?")[0]
        norm = "/api" + re.sub(r"\$\{[^}]*\}", "X", p)
        if not any(rx.match(norm) for _, rx in routes):
            missing.append(p)
    assert not missing, f"the page calls endpoints that do not exist: {missing}"


def test_the_plan_s_endpoints_all_exist():
    want = ["GET /api/sim", "POST /api/sim", "GET /api/sim/X", "PATCH /api/sim/X", "DELETE /api/sim/X", "POST /api/sim/X/seed/world", "POST /api/sim/X/start", "POST /api/sim/X/entities",
            "POST /api/sim/X/trackers", "POST /api/sim/X/guidelines", "POST /api/sim/X/guidelines/suggest", "POST /api/sim/X/directives", "DELETE /api/sim/X/directives/X", "POST /api/sim/X/chapters",
            "POST /api/sim/X/auto", "POST /api/sim/X/chapters/X/rewrite", "POST /api/sim/X/chapters/X/reroll", "POST /api/sim/X/chapters/X/accept", "POST /api/sim/X/chapters/X/retry",
            "PATCH /api/sim/X/chapters/X", "POST /api/sim/X/chapters/X/reread/apply", "POST /api/sim/X/head", "DELETE /api/sim/X/chapters/X", "POST /api/sim/X/chapters/X/paint",
            "POST /api/sim/X/chapters/X/panels/X/redraw", "PATCH /api/sim/X/chapters/X/panels/X", "POST /api/sim/X/chapters/X/panels/X/upload", "DELETE /api/sim/X/chapters/X/panels/X",
            "GET /api/sim/X/run", "POST /api/sim/X/stop", "GET /api/sim/X/export", "POST /api/sim/import", "POST /api/sim/X/duplicate", "POST /api/sim/X/save-template", "GET /api/sim/templates"]
    routes = _routes()
    for w in want:
        method, path = w.split(" ", 1)
        assert any(m == method and rx.match(path) for m, rx in routes), w


def test_every_setting_has_a_control_and_an_effect(sm):
    for key, ctl in {"difficulty": "s-diff", "dice": "s-dice", "chapter_words": "s-words", "deep": "s-deep", "auto_images": "s-auto", "panel_shape": "s-shape", "captions": "s-cap", "image_model": "s-img"}.items():
        assert key in store.DEFAULT_SETTINGS and f'id="{ctl}"' in JS, key
    # chapter length: the accepted range follows the setting
    pid, fake = make()
    store.save_project(pid, settings={"chapter_words": 200})
    fake.prose_words = 200
    ch = go(pid, fake)
    assert fake.count("sm_write") == 1 and "about 200 words (between 160 and 246)" in fake.last("sm_write")["system"]
    # image model: it reaches the request
    store.save_project(pid, settings={"image_model": "flux2-klein-9b"})
    e = store.entities(pid, "character")[0]
    assert paint.ref_request(e, store.project(pid)["settings"])["body"]["model"] == "flux2-klein-9b"
    # rules version moves with every rule edit and is written on the chapter
    v = store.project(pid)["settings"]["rules_version"]
    store.save_guideline(pid, {"grp": "tone", "text": "Keep it quiet."})
    assert store.project(pid)["settings"]["rules_version"] == v + 1
    assert go(pid, fake)["flags"]["rules_version"] == v + 1


def test_the_page_has_its_help_and_every_tab():
    assert "How this page works" in JS
    for tab in ("Story", "Setup", "Read"):
        assert f"'{tab}'" in JS


def test_nothing_in_the_engine_names_a_genre():
    banned = re.compile(r"zombie|weapon|survival|supermarket|courtroom|outbreak", re.I)
    for f in ("engine.py", "state.py", "dice.py", "memory.py", "models.py", "store.py", "paint.py", "portable.py", "export.py"):
        text = (ROOT / "sim" / f).read_text(encoding="utf-8")
        assert not banned.search(text), f
    prompts = (ROOT / "sim" / "prompts.py").read_text(encoding="utf-8")
    assert not re.search(r"zombie|supermarket|courtroom|outbreak", prompts, re.I)


def test_old_chapters_are_never_rewritten_by_a_redo(sm):
    pid, fake = make()
    c1 = go(pid, fake)
    first = store.chapter(c1["id"])
    again = run(engine.run_chapter(pid, fake, cfg(), parent_id="", action={"kind": "start"}, instruction="darker", label="rewrite"))
    assert again["id"] != c1["id"] and again["parent_id"] == ""
    after = store.chapter(c1["id"])
    for k in ("prose", "plan", "rolls", "delta", "state_before", "state_after"):
        assert after[k] == first[k], k


def test_operations_in_the_shapes_the_real_model_writes_are_all_read():
    from sim import models as m
    d = m.DeltaOut.model_validate({"ops": [{"move": {"target": "Ravi", "to": "Pharmacy"}}, {"operation": "item_remove", "target": "Rope", "qty": 1}, {"clock_advance": "Horde nears", "amount": 1},
                                           {"op": "flag_set", "tracker": "Power is on", "value": False}]})
    assert [o.op for o in d.ops] == ["move", "item_remove", "clock_advance", "flag_set"]
    assert d.ops[0].target == "Ravi" and d.ops[0].to == "Pharmacy" and d.ops[2].target == "Horde nears"
    assert m.RereadOut.model_validate({"ops": [{"entity_status": {"target": "Ravi", "value": "limping"}}]}).ops[0].op == "entity_status"


def test_deleting_a_person_before_the_start_cleans_the_trackers_and_after_it_retires_them(sm):
    pid, fake = make()
    dev = next(e for e in store.entities(pid) if e["name"] == "Dev")
    store.delete_entity(pid, dev["id"])
    store.purge_entity_refs(pid, "Dev")
    trk = {t["name"]: t for t in store.trackers(pid)}
    assert "Dev" not in trk["Where everyone is"]["start"]["at"] and trk["Why the dead walk"]["start"]["The source"] == []
    ravi_meera = trk["Ravi and Meera"]
    meera = next(e for e in store.entities(pid) if e["name"] == "Meera")
    store.delete_entity(pid, meera["id"])
    store.purge_entity_refs(pid, "Meera")
    assert "Ravi and Meera" not in [t["name"] for t in store.trackers(pid)]
    c1 = go(pid, fake)
    assert "Dev" not in c1["state_after"]["entities"]
    sana = next(e for e in store.entities(pid) if e["name"] == "Sana")
    store.retire_entity(pid, sana["id"])
    c2 = go(pid, fake)
    assert "Sana" not in c2["state_after"]["entities"] and "Sana" not in fake.last("sm_plan")["user"].split("## PEOPLE")[1].split("##")[0]
    assert all(o["who"] != "Sana" for o in c2["options"])
    loc = next(t for t in store.trackers(pid) if t["kind"] == "location")
    assert "Sana" not in c2["state_after"]["trackers"][loc["id"]]["at"]


def test_operations_without_an_exact_tracker_name_still_find_their_tracker(sm):
    from sim import dice, models as m, state as S
    pid, _ = make()
    store.save_tracker(pid, {"kind": "meter", "name": "Ravi's Fatigue", "min": 0, "max": 100, "start": 30, "owner": "Ravi", "danger_above": 80})
    store.save_tracker(pid, {"kind": "clock", "name": "Dawn", "max": 6, "start": 0})
    trackers = store.trackers(pid)
    ents = store.entities(pid)
    st = S.initial_state(trackers, ents, store.world(pid))
    ctx = S.Ctx(trackers, [e["name"] for e in ents], [e["name"] for e in ents if e["kind"] == "place"], "", True)
    ops = [m.Op(op="meter_change", target="Ravi", amount=5, why="x"), m.Op(op="meter_change", tracker="fatigue", amount=5, why="x"), m.Op(op="clock_advance", name="the Dawn clock", amount=1, why="x"),
           m.Op(op="meter_change", target="Nobody", amount=1, why="x")]
    new, applied, dropped = S.apply_ops(st, ops, ctx)
    fat = next(t for t in trackers if t["name"] == "Ravi's Fatigue")
    assert new["trackers"][fat["id"]] == 40 and len(applied) == 3 and len(dropped) == 1             # two meters exist, so the last one (no hint) is refused
    # the actor's own meter counts in the dice, and a meter that is only dangerous when high hurts when high
    low = dice.modifier({"who": "Ravi", "act": "run", "stats": []}, st, trackers)
    st["trackers"][fat["id"]] = 85
    high = dice.modifier({"who": "Ravi", "act": "run", "stats": []}, st, trackers)
    assert low[0] > 0 > high[0] and any("Fatigue" in w for w in high[1])


def test_names_written_loosely_are_matched_and_areas_of_the_world_card_become_places(sm):
    from sim import models as m, state as S
    pid, fake = make()
    assert S.pick({"main entrance": "Main Entrance", "aisle 10 the fortress": "Aisle 10 (The Fortress)"}, "The Main Entrance") == "Main Entrance"
    assert S.pick({"aisle 10": "Aisle 10", "aisle 4": "Aisle 4"}, "Aisle 4") == "Aisle 4"
    assert S.pick({"aisle 10": "Aisle 10"}, "Aisle 4") is None and S.pick({"dev": "Dev"}, "Device") is None
    ents = store.entities(pid)
    store.set_world(pid, {**store.world(pid), "exists": store.world(pid)["exists"] + " The Deli: meat slicers, a meat cleaver, cheese blocks."})
    ops = [m.Op(op="move", target="Ravi", to="The Deli", why="x"), m.Op(op="item_add", target="meat cleaver", to="Ravi", source="The Deli", why="x"), m.Op(op="move", target="Meera", to="The Moon", why="x")]
    assert engine._adopt_places(pid, ops, ents, store.world(pid)) == ["The Deli"]
    ents = store.entities(pid)
    trackers = store.trackers(pid)
    st = S.initial_state(trackers, ents, store.world(pid))
    ctx = S.Ctx(trackers, [e["name"] for e in ents], [e["name"] for e in ents if e["kind"] == "place"], store.world(pid)["exists"], True, {})
    new, applied, dropped = S.apply_ops(st, ops, ctx)
    assert [a["text"] for a in applied][:2] == ["Ravi is now at The Deli", "+1 meat cleaver"] and len(dropped) == 1 and dropped[0]["target"] == "Meera"
    # the model puts the place an item comes from in `who`
    _, a2, d2 = S.apply_ops(st, [m.Op(op="item_add", target="Rope", to="Ravi", who="Aisle Two", why="x")], ctx)
    assert a2 and not d2


def test_an_empty_item_list_is_filled_from_the_world_card(sm):
    fake = SimFake(sm_trackers={"trackers": [{"name": "Supplies", "kind": "items", "start": []}, {"name": "Morale", "kind": "meter", "min": 0, "max": 10, "start": 5}]})
    p = store.create_project("anything")
    pid = p["id"]
    run(seed.seed_world(pid, fake, cfg()))
    run(seed.seed_cast(pid, fake, cfg()))
    run(seed.seed_trackers(pid, fake, cfg()))
    items = next(t for t in store.trackers(pid) if t["kind"] == "items")
    assert fake.count("sm_items") == 1 and set(items["start"]) == {"Crowbar", "Rope", "Bandages"}
