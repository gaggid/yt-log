import asyncio

import pytest

from fakellm import FakeBackend
from story import db, eta, guide, ingest, pipeline, projects, review, settings as settings_mod
from story.pipeline import Pipeline
from test_pipeline import make_book


class SlowFake(FakeBackend):
    async def complete(self, messages, max_tokens):
        await asyncio.sleep(0.02)
        return await super().complete(messages, max_tokens)


def run(pid, fake):
    return asyncio.run(Pipeline(pid, fake).run())


def test_rate_starts_as_rough_guess_then_learns(env):
    r = eta.rate("analyze", "m")
    assert r["confidence"] == "rough guess" and r["value"] == eta.SEED["analyze"] and not r["learned"]
    for _ in range(10):
        eta.record("p", "analyze", "m", 5000, 3000, 50_000, 65536)          # 0.01 s per input token
    r = eta.rate("analyze", "m")
    assert r["learned"] and r["confidence"] == "good" and abs(r["value"] - 0.01) < 1e-9
    assert eta.rate("analyze", "other-model")["learned"] is False             # history is per model
    assert eta.rate("draft", "m")["confidence"] == "rough guess"


def test_recent_samples_weigh_more(env):
    for _ in range(10):
        eta.record("p", "draft", "m", 1, 1, 100_000, 1)                       # slow in the past
    for _ in range(10):
        eta.record("p", "draft", "m", 1, 1, 20_000, 1)                        # fast recently
    assert eta.rate("draft", "m")["value"] < 60                               # closer to 20s than to the 60s plain mean


def test_estimate_scales_with_scope_and_shrinks_as_work_finishes(env):
    pid = projects.import_text(make_book(8, 50))
    full = eta.estimate(pid)
    assert full["remaining"]["seconds"] > 600 and full["confidence"] == "rough guess"
    assert {p["stage"] for p in full["stages"]} >= {"analyze", "draft"} and all(p["forecast"] for p in full["stages"])
    projects.set_scope(pid, {"mode": "chapters", "chapters": [1]})
    one = eta.estimate(pid)
    assert one["remaining"]["seconds"] < full["remaining"]["seconds"] / 3
    projects.set_scope(pid, {"mode": "all"})
    run(pid, SlowFake(fail_after=6))                                          # 6 steps done, then an outage
    part = eta.estimate(pid)
    assert part["remaining"]["seconds"] < full["remaining"]["seconds"]
    assert part["done_seconds"] > 0
    assert eta.rate("analyze", settings_mod.get()["model"])["n"] >= 5        # the run itself fed the statistics


def test_stats_are_kept_after_project_deletion_and_backfilled(env):
    pid = projects.import_text(make_book(2, 12))
    assert run(pid, SlowFake()) == "done"
    n = db.one("SELECT COUNT(*) n FROM task_stats")["n"]
    assert n > 3
    projects.delete(pid)
    assert db.one("SELECT COUNT(*) n FROM task_stats")["n"] == n               # history outlives the project
    assert any(p["stage"] == "analyze" for p in eta.performance())


def test_backfill_learns_from_tasks_finished_before_stats_existed(env):
    pid = projects.import_text(make_book(2, 12))
    run(pid, SlowFake())
    db.ex("DROP TABLE task_stats")
    db.ex("DELETE FROM settings WHERE key='stats_backfilled'")
    eta.ensure()
    assert db.one("SELECT COUNT(*) n FROM task_stats")["n"] > 3


def test_next_step_follows_the_project_state(env):
    pid = projects.import_text(make_book(3, 12))
    n = guide.next_step(pid)
    assert n["step"] == "scope" and n["primary"]["action"] == "start" and "Estimated time" in n["detail"]
    assert guide.step_index(n) == 1
    run(pid, FakeBackend(fail_after=3))
    n = guide.next_step(pid)
    assert n["tone"] == "problem" and n["primary"]["action"] == "retry" and "failed" in n["detail"]
    pipeline.reset(pid, failed_only=True)
    assert run(pid, FakeBackend()) == "done"
    n = guide.next_step(pid)
    pending = n["counts"]["pending"]
    assert n["step"] == "review" and n["primary"]["action"] == "review" and str(pending) in n["title"]
    for c in review.list_candidates(pid):
        review.update_candidate(c["id"], {"status": "approved"})
    n = guide.next_step(pid)
    assert n["step"] == "export" and n["primary"]["action"] == "plans" and n["secondary"]["action"] == "export" and guide.step_index(n) == 4
    for c in review.list_candidates(pid):
        review.update_candidate(c["id"], {"status": "rejected"})
    assert "rejected" in guide.next_step(pid)["title"].lower()


def test_paused_state_offers_resume(env):
    pid = projects.import_text(make_book(2, 12))
    run(pid, FakeBackend(fail_after=2))
    db.ex("UPDATE projects SET status='paused', error='' WHERE id=?", (pid,))
    n = guide.next_step(pid)
    assert n["primary"]["action"] == "resume" and "kept" in n["detail"]


def test_live_view_names_the_running_step_and_recent_work(env):
    pid = projects.import_text(make_book(6, 30))
    run(pid, SlowFake(fail_after=3))
    t = [x for x in pipeline.stage_tasks(pid, "analyze") if x["status"] != "done"][0]
    db.ex("UPDATE tasks SET status='running', updated_at=? WHERE id=?", (db.now() - 42, t["id"]))
    lv = guide.live(pid)
    assert lv["current"]["stage"] == "analyze" and lv["current"]["label"].startswith("Chunk ") and 40 <= lv["current"]["elapsed"] < 60
    assert len(lv["activity"]) >= 3 and all(a["label"] for a in lv["activity"]) and lv["activity"][-1]["status"] == "done"
    assert lv["eta"]["remaining"]["seconds"] > 0


def test_progress_endpoint_carries_guidance(tmp_path, monkeypatch):
    import config
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    with TestClient(main.app) as c:
        pid = projects.import_text(make_book(2, 12))
        c.post("/login", data={"username": config.APP_USER, "password": config.APP_PASSWORD})
        p = c.get(f"/api/projects/{pid}/progress").json()
        assert p["next"]["primary"]["action"] == "start" and p["step_index"] == 1 and len(p["steps"]) == 5
        assert p["eta"]["remaining"]["seconds"] > 0 and p["server_now"] > 0 and p["current"] is None
        assert c.get("/api/performance").status_code == 200
        sc = c.get(f"/api/projects/{pid}/scope").json()
        assert sc["eta_seconds"] > 0 and sc["eta_confidence"] == "rough guess"


def test_a_few_blank_pages_do_not_warn(tmp_path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    p = tmp_path / "blank.pdf"
    c = canvas.Canvas(str(p), pagesize=A4)
    for i in range(30):
        if i != 4:
            c.setFont("Helvetica", 11)
            c.drawString(60, 780, f"Page {i} has a normal amount of readable text for the extractor to find here.")
            c.drawString(60, 760, "A second line of text so that the page is clearly not empty at all, really.")
        c.showPage()
    c.save()
    ex = ingest.extract_pdf(p)
    assert ex.meta["blank_pages"] == [5] and not any("no extractable text" in w for w in ex.warnings)


def test_finished_project_has_an_empty_estimate(env):
    pid = projects.import_text(make_book(2, 12))
    assert run(pid, FakeBackend()) == "done"
    e = eta.estimate(pid)
    assert e["remaining"]["seconds"] == 0 and e["stages"] == [] and e["percent"] in (0, 100) or e["done_seconds"] >= 0
    assert guide.live(pid)["current"] is None
    assert guide.next_step(pid)["step"] == "review"


def test_steps_without_a_model_call_do_not_skew_speed(env):
    eta.record("p", "rollup", "m", 0, 0, 3, 65536)                            # a "direct" chapter record: no model call
    assert eta.rate("rollup", "m")["learned"] is False
    eta.record("p", "rollup", "m", 1200, 800, 30_000, 65536)
    assert eta.rate("rollup", "m")["value"] == 30.0
