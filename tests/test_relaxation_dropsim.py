"""The window-glass drop physics (relaxation/dropsim.py, owner, 2026-11-20): the loop has to be exact, and a bigger drop that meets a smaller one takes it in."""
import random

import numpy as np
from PIL import Image

from relaxation import dropsim, rainfx

VIEW = (60, 30, 1220, 650)


def _sim(seed=3, n=300):
    return dropsim.Sim(random.Random(seed), VIEW, n, 1.0, running=60, drizzle=200)


def test_every_drop_is_gone_before_the_loop_ends_so_the_loop_is_exact():
    sim = _sim()
    assert all(b["life"] <= dropsim.LIFE_MAX < sim.n for b in sim.bigs)
    assert all(t["life"] < sim.n for t in sim.trail_drops)
    first = sim.sprites(0)
    assert first == sim.sprites(sim.n) == sim.sprites(2 * sim.n)                   # frame n is frame 0 again, whatever the number of loops


def test_the_same_seed_gives_the_same_rain_and_another_seed_another():
    a, b, c = _sim(3), _sim(3), _sim(4)
    assert a.sprites(120) == b.sprites(120) and a.sprites(120) != c.sprites(120)


def test_a_bigger_drop_takes_a_smaller_one_in_and_grows():
    sim = _sim()
    eaten = [b for b in sim.bigs if b["dead_by"] is not None]
    assert eaten, "with sixty drops on one window some must meet"
    for b in eaten:
        a = sim.bigs[b["dead_by"]]
        assert a["r0"] >= b["r0"] and b["fade_out"] == 5
        assert any(g > 0 for _, g in a["boosts"])


def test_drops_run_and_stop_and_leave_trail_drops_and_wipe_the_drizzle():
    sim = _sim()
    moved = [b for b in sim.bigs if b["y"][-1] - b["y"][0] > 20]
    assert len(moved) > len(sim.bigs) // 2
    assert any((b["v"] < 0.05).any() and (b["v"] > 0.5).any() for b in sim.bigs)      # a drop that stood still and ran
    assert len(sim.trail_drops) > len(sim.bigs)
    assert sim.dyn_drizzle and sim.static_drizzle
    assert all(len(d["wipes"]) for d in sim.dyn_drizzle)


def test_a_loop_renders_with_the_physics(tmp_path):
    pic = tmp_path / "p.jpg"
    Image.fromarray((np.random.RandomState(1).rand(180, 320, 3) * 255).astype("uint8")).save(pic)
    out = rainfx.render(pic, {"view": [0.05, 0.05, 0.95, 0.9], "water": [], "hard": []}, tmp_path / "o.mp4", size=(320, 180), loop_s=1.0, physics=True)
    assert out.is_file() and out.stat().st_size > 1000
