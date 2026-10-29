"""M8: the automatic gates, the judges and the persona panel."""
import asyncio

import pytest

from story import db
from story2 import events, gates, judges, planner, storyboard
from test_chain_v2 import ChainFake
from test_narration_v2 import ready


def boarded(env):
    pid, be = ready(env)
    asyncio.run(planner.make_narration(pid, be))
    cf = ChainFake()
    asyncio.run(events.make_events(pid, cf))
    asyncio.run(storyboard.make_registry(pid, cf))
    asyncio.run(storyboard.make_storyboard(pid, cf))
    return pid, be, cf


def test_the_gate_measures_a_stage_and_names_the_failing_metric(env):
    pid, be, cf = boarded(env)
    res = gates.measure(pid, "storyboard")
    assert res["stage"] == "storyboard" and isinstance(res["ok"], bool)
    names = {f["metric"] for f in res["failures"]}
    assert names <= set(gates.THRESHOLDS["storyboard"])
    p = planner.get_plan(pid)
    db.ex("UPDATE plans SET settings=? WHERE id=?", (db.jdump({**p["settings"], "gates": {"mode": "warn"}}), pid))
    assert gates.mode(planner.get_plan(pid)) == "warn" and gates.mode({"settings": {}}) == "strict"


def test_a_hard_failure_is_repaired_once_and_then_stops_in_strict_mode(env, monkeypatch):
    pid, be, cf = boarded(env)
    calls = []

    async def fake_repair(plan_id, stage, res, backend, s):
        calls.append(stage)
    monkeypatch.setattr(gates, "repair", fake_repair)
    monkeypatch.setitem(gates.THRESHOLDS["storyboard"], "distinct_places", (">=", 999, "hard"))
    with pytest.raises(gates.GateStop, match="distinct_places"):
        asyncio.run(gates.run(pid, "storyboard", cf, {}, []))
    assert calls == ["storyboard"]                                                                  # exactly one repair
    p = planner.get_plan(pid)
    db.ex("UPDATE plans SET settings=? WHERE id=?", (db.jdump({**p["settings"], "gates": {"mode": "warn"}}), pid))
    notes = []
    res = asyncio.run(gates.run(pid, "storyboard", cf, {}, notes))
    assert not res["ok"] and any("warn mode" in n for n in notes)


def test_the_storyboard_repair_applies_the_world_rules_in_code(env):
    pid, be, cf = boarded(env)
    asyncio.run(gates.repair(pid, "storyboard", {}, cf, {}))
    assert storyboard.validate_storyboard(pid)["issues"] is not None


def test_safety_findings_cover_the_rules(env):
    pid, be, cf = boarded(env)
    p = planner.get_plan(pid)
    seg = p["segments"][0]
    sents = seg["sentences"]
    sents[0]["text"] = "उसने उसे मार डाला।"
    sents[1]["text"] = "वह एक mastermind था।"
    sents[2]["text"] = "Rahul Sharma हिंदू समुदाय का था।"
    db.ex("UPDATE segments SET sentences=? WHERE id=?", (db.jdump(sents), seg["id"]))
    db.ex("UPDATE plans SET settings=? WHERE id=?", (db.jdump({**p["settings"], "name_map": {"Geeta Devi": "Sunita"}}), pid))
    last = p["segments"][-1]
    ls = last["sentences"]
    ls[0]["text"] = "Geeta Devi was found in a scam with an OTP."
    db.ex("UPDATE segments SET sentences=? WHERE id=?", (db.jdump(ls), last["id"]))
    f = gates.safety_findings(planner.get_plan(pid))
    kinds = {x["kind"] for x in f}
    assert {"attribution", "glamour", "community", "private_name", "safety_content"} <= kinds
    assert next(x for x in f if x["kind"] == "private_name")["level"] == "hard" and next(x for x in f if x["kind"] == "glamour")["level"] == "soft"
    assert not gates.safety_gate(pid)["ok"]


def test_a_judge_keeps_the_worse_of_two_runs_and_names_the_weakest_point(env):
    pid, be, cf = boarded(env)
    out = asyncio.run(judges.judge(pid, "narration", judges.narration_text(planner.get_plan(pid)), cf))
    assert out["weakest"] == "variety" and out["scores"]["variety"]["score"] == 2 and set(out["scores"]) == {k for k, _ in judges.RUBRICS["narration"]}
    assert planner.get_plan(pid)["settings"]["judges"]["narration"]["total"] == out["total"]


def test_the_panel_reports_where_viewers_leave(env):
    pid, be, cf = boarded(env)
    out = asyncio.run(judges.panel(pid, cf, personas=["P1", "P3"], runs=1))
    assert out["of"] == 2 and out["would_click"] == 2 and planner.get_plan(pid)["settings"]["panel"]["of"] == 2
    assert set(out["personas"]) == {"P1", "P3"} and len(judges.PERSONAS) == 8


def test_bench_check_reports_only_metrics_that_got_worse():
    from story2 import bench

    def card(**v):
        return {"plan_id": "x", "groups": {"g": {k: {"value": val, "status": st, "target": "<= 1"} for k, (val, st) in v.items()}}}
    old = {"plans": {"s": card(stock_phrases=(0, "ok"), questions_share=(0.1, "warn"))}}
    new = {"plans": {"s": card(stock_phrases=(3, "warn"), questions_share=(0.2, "warn"))}}
    out = bench.regressions(old, new)
    assert len(out) == 1 and "stock_phrases was 0 and is now 3" in out[0]
    assert bench.regressions(old, old) == []


def test_the_gates_endpoint_and_the_publish_block(env):
    from story3 import publish
    from story2 import titles
    pid, be, cf = boarded(env)
    asyncio.run(titles.make(pid, cf))
    p = planner.get_plan(pid)
    db.ex("UPDATE plans SET settings=? WHERE id=?", (db.jdump({**p["settings"], "name_map": {"Geeta Devi": "Sunita"}}), pid))
    seg = p["segments"][0]
    sents = seg["sentences"]
    sents[0]["text"] = "Geeta Devi की कहानी।"
    db.ex("UPDATE segments SET sentences=? WHERE id=?", (db.jdump(sents), seg["id"]))
    with pytest.raises(Exception, match="private_name"):
        asyncio.run(publish.build(pid, cf))                                                          # a private name blocks the pack with the fix named
