"""The bench: snapshot, save, load, compare, and a run on the fake model up to the prompts stage."""
import asyncio

import pytest

from story2 import bench
from test_phase2a import approved_story
from test_phase2b import P2BFake, boarded


def test_snapshot_save_load_and_compare(env, monkeypatch):
    pid, cid, be, p = boarded(env)
    snap = bench.snapshot({"fugitive": p["id"]})
    assert "world" in snap["plans"]["fugitive"]["groups"]
    path = bench.save("t1", snap)
    assert path.is_file() and bench.load("t1")["plans"]["fugitive"]["plan_id"] == p["id"]
    table = bench.compare(snap, snap, "a", "b")
    assert "fugitive" in table and "distinct_places" in table
    with pytest.raises(FileNotFoundError):
        bench.load("missing-run")


def test_compare_marks_better_and_worse():
    def card(v, status):
        return {"plan_id": "p", "groups": {"g": {"distinct_places": {"value": v, "target": ">= 12", "status": status}}}}
    a = {"plans": {"s": card(4, "warn")}}
    b = {"plans": {"s": card(14, "ok")}}
    assert "better" in bench.compare(a, b)
    assert "worse" in bench.compare(b, a)


def test_run_story_up_to_prompts_on_the_fake_model(env, monkeypatch):
    pid, cid = approved_story(env)
    monkeypatch.setitem(bench.BENCH, "fugitive", {**bench.BENCH["fugitive"], "candidate": cid})
    from test_chain_v2 import ChainFake
    plan_id = asyncio.run(bench.run_story("fugitive", "prompts", ChainFake(), minutes=2))
    card = bench.snapshot({"fugitive": plan_id})["plans"]["fugitive"]
    assert card["groups"]["world"]["scenes"]["value"] > 0
    assert card["groups"]["prompts"]["prompt_words"]["value"] is not None


def test_run_story_rejects_a_bad_stage(env):
    with pytest.raises(ValueError):
        asyncio.run(bench.run_story("fugitive", "pictures", None))
