import asyncio
import json

import pytest

import config

from fakellm import FakeBackend
from story import db, export, pipeline, projects, review, scoring, settings as settings_mod
from story.contract import ExportDoc
from story.llm import JsonCaller, ValidationFailed
from story.pipeline import Pipeline, dedupe_stubs
from story.schemas import ChunkAnalysis
from story.tokens import Budget, BudgetExceeded


def make_book(chapters=8, paras_per=50, chars=1000):
    out = []
    for c in range(1, chapters + 1):
        out.append(f"Chapter {c}: The tale of coast {chr(96 + c)}")
        for p in range(paras_per):
            body = f"In part {c} item {p} the surveyors measured the coast near site{c}x{p} and logged every reading. "
            out.append((body * (chars // len(body) + 1))[:chars].strip() + ".")
    return "\n\n".join(out)


def run(pid, fake, **kw):
    return asyncio.run(Pipeline(pid, fake, **kw).run())


@pytest.fixture
def book(env):
    return projects.import_text(make_book(), title="Big Book", author="N. Author")


def usable():
    return Budget.from_settings(settings_mod.get()).usable


def test_source_larger_than_context_never_overflows(book):
    s = settings_mod.get()
    assert projects.get(book)["est_tokens"] > s["context_limit"] * 3          # genuinely bigger than the window
    fake = FakeBackend()
    assert run(book, fake) == "done"
    assert fake.count("analyze_chunk") >= 10
    for c in fake.calls:                                                     # every request fit, with output reserve
        assert c["tokens"] + c["max_tokens"] <= usable(), c["task"]
    # no paragraph dropped: every paragraph is in the main items of exactly one finished analysis task
    covered = [i for t in pipeline.stage_tasks(book, "analyze", "done") for i, _, _ in t["input"]["items"]]
    total = projects.get_paras(book)["total"]
    assert sorted(set(covered)) == list(range(1, total + 1))


def test_candidates_are_independent_and_traceable(book):
    run(book, FakeBackend())
    cands = review.list_candidates(book)
    assert len(cands) >= 5
    titles = {c["title"] for c in cands}
    assert len(titles) == len(cands)
    n_paras = projects.get_paras(book)["total"]
    for c in cands:
        full = review.get_candidate(c["id"])
        assert full["refs"], "story without source links"
        for r in full["refs"]:
            assert 1 <= r["idx"] <= n_paras
            assert r["text"] == db.one("SELECT text FROM paras WHERE project_id=? AND idx=?", (book, r["idx"]))["text"]
            assert r["locator"]
        claims = full["data"]["claims"]
        assert claims[0]["quote_verified"] is True and claims[1]["quote_verified"] is False
        assert any("verbatim" in w for w in full["data"]["warnings"])
        assert 0 <= full["story_score"] <= 100 and full["evidence_score"] < 100
        assert full["priority"] < full["story_score"]                        # imperfect evidence lowers priority
        assert set(full["data"]["scores"]) == set(scoring.FACTORS)
    ghost = [r for r in db.q("SELECT * FROM candidate_refs") if r["para_idx"] in (9999, 123456)]
    assert not ghost                                                         # invented paragraph ids are discarded


def test_cross_chapter_story_and_chapter_records(book):
    run(book, FakeBackend())
    assert any(c["kind"] == "multi_chapter" for c in review.list_candidates(book))
    recs = pipeline.done_results(book, "rollup")
    assert len(recs) == 8 and all(r["events"] and r["facts"] for r in recs)  # details kept, not just summaries
    idx = pipeline.done_results(book, "index")[0]
    assert idx["overview"] and idx["entities"][0]["name"] == "Ada" and idx["timeline"]
    assert all(c <= 8 for t in idx["threads"] for c in t["chapter_idxs"])    # invented chapter 999 removed


def test_failure_then_resume_does_not_repeat_finished_work(book):
    first = FakeBackend(fail_after=5)
    assert run(book, first) == "error"
    p = projects.get(book)
    assert p["status"] == "error" and "failed" in p["error"]
    done_first = len(pipeline.stage_tasks(book, "analyze", "done"))
    assert done_first == 5
    n_chunks = len(pipeline.stage_tasks(book, "analyze"))
    pipeline.reset(book, failed_only=True)
    second = FakeBackend()
    assert run(book, second) == "done"
    assert second.count("analyze_chunk") == n_chunks - done_first            # only unfinished chunks were processed
    assert projects.get(book)["status"] == "done"


def test_interrupted_running_tasks_are_recovered(book):
    run(book, FakeBackend(fail_after=3))
    tid = pipeline.stage_tasks(book, "analyze", "done")[0]["id"]
    db.ex("UPDATE tasks SET status='running' WHERE id=?", (tid,))             # as if the process died mid-task
    pipeline.recover()
    assert db.one("SELECT status FROM tasks WHERE id=?", (tid,))["status"] == "pending"


class SlowFake(FakeBackend):
    async def complete(self, messages, max_tokens):
        await asyncio.sleep(0.03)
        return await super().complete(messages, max_tokens)


def test_pause_cancel_and_resume_via_manager(book):
    fake = SlowFake()
    mgr = pipeline.Manager()
    mgr.backend_factory = lambda s: fake

    async def scenario():
        mgr.start(book)
        await asyncio.sleep(0.25)
        assert mgr.pause(book)
        await mgr.wait(book)
        paused = projects.get(book)["status"]
        done_at_pause = len(pipeline.stage_tasks(book, "analyze", "done"))
        mgr.start(book)
        await asyncio.sleep(0.15)
        assert mgr.cancel(book)
        await mgr.wait(book)
        cancelled = projects.get(book)["status"]
        mid = db.q("SELECT COUNT(*) n FROM tasks WHERE project_id=? AND status='running'", (book,))[0]["n"]
        mgr.start(book)
        await mgr.wait(book)
        return paused, done_at_pause, cancelled, mid

    paused, done_at_pause, cancelled, running_after_cancel = asyncio.run(scenario())
    assert paused == "paused" and 0 < done_at_pause
    assert cancelled == "cancelled" and running_after_cancel == 0
    assert projects.get(book)["status"] == "done"
    n_chunks = len(pipeline.stage_tasks(book, "analyze", "done")) + len(pipeline.stage_tasks(book, "analyze", "split"))
    assert fake.count("analyze_chunk") <= n_chunks + 1                       # at most the one cancelled in-flight call repeated


def test_resume_interrupted_at_startup(book):
    db.ex("UPDATE projects SET status='running' WHERE id=?", (book,))
    mgr = pipeline.Manager()
    fake = FakeBackend()
    mgr.backend_factory = lambda s: fake

    async def go():
        started = mgr.resume_interrupted()
        await mgr.wait(book)
        return started

    assert asyncio.run(go()) == [book]
    assert projects.get(book)["status"] == "done"


def test_invalid_json_is_retried_then_accepted(book):
    fake = FakeBackend(bad_json={"analyze_chunk": 2})
    assert run(book, fake) == "done"
    n = len(pipeline.stage_tasks(book, "analyze"))
    assert fake.count("analyze_chunk") == n + 2
    retry_call = [c for c in fake.calls if c["task"] == "analyze_chunk"][1]
    assert "invalid" in retry_call["user"]                                   # the retry told the model what was wrong


def test_persistent_invalid_json_fails_task_and_keeps_raw_reply(book):
    fake = FakeBackend(always_bad=["analyze_chunk"])
    assert run(book, fake) == "error"
    failed = pipeline.stage_tasks(book, "analyze", "failed")
    assert failed and failed[0]["attempts"] == 1
    assert len(failed[0]["raw_failed"]) == 3                                 # 1 try + 2 bounded retries, all preserved
    assert "this is not json" in failed[0]["raw_failed"][0]["response"]
    assert fake.count("analyze_chunk") == 9                                  # 3 tasks x 3 bounded attempts, then the stage stops
    assert not pipeline.stage_tasks(book, "rollup")                          # nothing downstream was fabricated


def test_cut_off_reply_splits_the_chunk(env):
    settings_mod.update({"chunk_tokens": 3000, "chunk_overlap": 300})
    pid = projects.import_text(make_book(chapters=2, paras_per=30))
    fake = FakeBackend(truncate_over=4)
    assert run(pid, fake) == "done"
    tasks = pipeline.stage_tasks(pid, "analyze")
    assert any(t["status"] == "split" for t in tasks) and any("." in t["key"] for t in tasks)
    done = [t for t in tasks if t["status"] == "done"]
    covered = sorted(i for t in done for i, _, _ in t["input"]["items"])
    assert covered == list(range(1, projects.get_paras(pid)["total"] + 1))   # halves cover everything exactly once
    assert [t["ord"] for t in sorted(tasks, key=lambda t: t["ord"])] == sorted(t["ord"] for t in tasks)


def test_json_caller_refuses_oversized_request(env):
    fake = FakeBackend()
    caller = JsonCaller(fake, settings_mod.get())
    huge = "word " * 60000
    with pytest.raises(BudgetExceeded):
        asyncio.run(caller.call("[TASK:analyze_chunk]\nsys", huge, ChunkAnalysis))
    assert fake.calls == []                                                  # never sent, never truncated


def test_schema_validation_rejects_missing_content(env):
    class Empty(FakeBackend):
        async def complete(self, messages, max_tokens):
            from story.llm import LLMResult
            return LLMResult(json.dumps({"summary": "short", "events": []}))
    caller = JsonCaller(Empty(), settings_mod.get())
    with pytest.raises(ValidationFailed) as e:
        asyncio.run(caller.call("[TASK:analyze_chunk]\nsys", "[P1] text", ChunkAnalysis))
    assert "summary" in str(e.value.raw[-1]["error"])


def test_dedupe_stubs_merges_overlaps_and_keeps_all_links():
    stubs = [
        {"title": "The Flood", "premise": "a", "potential": 8, "para_ids": [10, 11, 12, 13]},
        {"title": "Flood disaster night", "premise": "b", "potential": 5, "para_ids": [11, 12, 13, 14]},
        {"title": "The Flood!", "premise": "c", "potential": 4, "para_ids": [200]},      # same title words -> merged
        {"title": "A separate tale", "premise": "d", "potential": 6, "para_ids": [300, 301]},
    ]
    out = dedupe_stubs(stubs)
    assert len(out) == 2
    flood = next(s for s in out if s["title"] == "The Flood")
    assert flood["para_ids"] == [10, 11, 12, 13, 14, 200]
    assert set(flood["merged_titles"]) == {"Flood disaster night", "The Flood!"}


def test_max_candidates_cap_and_expand_leads(env):
    settings_mod.update({"max_candidates": 3})
    pid = projects.import_text(make_book())
    assert run(pid, FakeBackend()) == "done"
    assert len(review.list_candidates(pid)) == 3
    prog = pipeline.progress(pid)
    assert prog["leads_remaining"] > 0
    assert pipeline.expand_leads(pid, 2) == 2
    assert run(pid, FakeBackend()) == "done"
    assert len(review.list_candidates(pid)) == 5


def test_reprocess_stage_keeps_reviewed_stories(book):
    run(book, FakeBackend())
    cands = review.list_candidates(book)
    keep = cands[0]["id"]
    review.update_candidate(keep, {"status": "approved"})
    pipeline.reset(book, stage="draft")
    left = review.list_candidates(book)
    assert [c["id"] for c in left] == [keep]
    assert run(book, FakeBackend()) == "done"
    assert len(review.list_candidates(book)) > 1                              # redrafted alongside the kept one
    assert review.get_candidate(keep)["status"] == "approved"


def test_review_edit_merge_split_and_export(book):
    run(book, FakeBackend())
    cands = review.list_candidates(book)
    a, b = cands[0], cands[1]
    ra = {r["idx"] for r in review.get_candidate(a["id"])["refs"]}
    rb = {r["idx"] for r in review.get_candidate(b["id"])["refs"]}

    e = review.update_candidate(a["id"], {"title": "Edited title", "notes": "check ch.2", "research": True,
                                          "priority_override": 99, "overview": "New overview."})
    assert e["title"] == "Edited title" and e["edited"] and e["research"] and e["eff_priority"] == 99
    assert e["priority"] != 99                                               # original score preserved next to the override
    with pytest.raises(review.ReviewError):
        review.update_candidate(a["id"], {"status": "bogus"})
    with pytest.raises(review.ReviewError):
        review.update_candidate(a["id"], {"title": " "})

    merged = review.merge([a["id"], b["id"]], title="Merged saga")
    assert {r["idx"] for r in merged["refs"]} == ra | rb                      # source links survive the merge
    assert merged["data"]["lineage"]["merged_from"][0]["id"] in (a["id"], b["id"])
    assert review.get_candidate(a["id"])["status"] == "superseded"
    assert a["id"] not in {c["id"] for c in review.list_candidates(book)}
    with pytest.raises(review.ReviewError):
        review.merge([a["id"], b["id"]])

    refs = sorted(r["idx"] for r in merged["refs"])
    half = len(refs) // 2
    parts = review.split(merged["id"], [{"title": "Part one", "para_idxs": refs[:half]},
                                         {"title": "Part two", "para_idxs": refs[half:]}])
    assert len(parts) == 2 and {r["idx"] for p in parts for r in p["refs"]} == set(refs)
    assert all(p["data"]["lineage"]["split_from"]["id"] == merged["id"] for p in parts)
    with pytest.raises(review.ReviewError):
        review.split(parts[0]["id"], [{"title": "x", "para_idxs": [999999]}, {"title": "y", "para_idxs": [1]}])

    review.update_candidate(parts[0]["id"], {"status": "approved"})
    review.update_candidate(parts[1]["id"], {"status": "rejected"})
    doc = export.build(book, ("approved", "pending"))
    again = ExportDoc.model_validate_json(export.to_json(doc))                # canonical JSON round-trips the contract
    ids = {s.id for s in again.stories}
    assert parts[0]["id"] in ids and parts[1]["id"] not in ids and a["id"] not in ids
    assert again.schema_version == "1.1" and again.source.title == "Big Book" and len(again.source.chapters) == 8
    for s in again.stories:
        assert s.references and all(r.text and r.locator for r in s.references)
        assert set(s.scores.factors) == set(scoring.FACTORS) and s.scores.evidence_score >= 0
    csv_text = export.to_csv(export.build(book, ("approved", "pending", "rejected")))
    assert csv_text.lstrip("﻿").splitlines()[0].startswith("id,title,premise,status")
    assert parts[1]["id"] in csv_text
    no_text = export.build(book, ("approved",), include_text=False)
    assert all(r.text == "" for s in no_text.stories for r in s.references)


def test_rescore_after_weight_change(book):
    run(book, FakeBackend())
    before = review.list_candidates(book)[0]
    s = settings_mod.update({"weights": {"hook": 100, "narrative": 0, "payoff": 0, "emotion": 0, "standalone": 0},
                             "evidence_influence": 0.0})
    review.rescore_project(book, s["weights"], s["evidence_influence"])
    after = review.get_candidate(before["id"])
    assert after["story_score"] == 80.0 and after["priority"] == 80.0       # hook=8 only, evidence ignored
    assert after["story_score"] != before["story_score"]


def test_evidence_gates_dramatic_stories():
    story = scoring.story_score({f: 9 for f in scoring.FACTORS}, settings_mod.DEFAULTS["weights"])
    assert story == 90.0
    weak = scoring.priority(story, 20, 0.4)
    strong = scoring.priority(story, 95, 0.4)
    assert weak < strong and weak < 70


def test_list_filter_sort_and_counts(env):
    a = projects.import_text(make_book(2, 6), title="Alpha", author="X")
    b = projects.import_text(make_book(2, 6), title="Beta", author="Y")
    run(a, FakeBackend())
    assert [p["title"] for p in projects.list_projects(sort="title", desc=False)] == ["Alpha", "Beta"]
    assert [p["id"] for p in projects.list_projects(q="Beta")] == [b]
    assert [p["id"] for p in projects.list_projects(status="done")] == [a]
    pa = projects.get(a)
    assert pa["cand_total"] >= 1 and pa["cand_pending"] == pa["cand_total"] and pa["chapter_count"] == 2
    cid = review.list_candidates(a)[0]["id"]
    review.update_candidate(cid, {"status": "approved"})
    assert projects.get(a)["cand_approved"] == 1
    assert review.list_candidates(a, status="approved")[0]["id"] == cid
    assert review.list_candidates(a, q="zzzz-none") == []


def test_short_article_runs_with_minimal_calls(env):
    html = ("<html><head><title>T</title></head><body><article><h1>Short piece</h1>"
            + "".join(f"<p>Paragraph {i} describes the voyage across the strait and what the crew found there. " * 3 + "</p>" for i in range(8))
            + "</article></body></html>")
    pid = projects.import_file("a.html", html.encode())
    fake = FakeBackend()
    assert run(pid, fake) == "done"
    assert fake.count("analyze_chunk") == 1 and fake.count("chapter_rollup") == 0 and fake.count("book_index") == 0
    assert fake.count("discover_global") == 0 and review.list_candidates(pid)


def test_front_and_back_matter_is_skipped(env):
    body = lambda tag: "\n\n".join(f"{tag} paragraph {i} about the harbour surveys and tides of the coast." * 3 for i in range(8))  # noqa: E731
    text = "\n\n".join(["Contents", "Chapter 1 ..... 5\nChapter 2 ..... 9", "Chapter 1: First", body("one"), "Chapter 2: Second",
                       body("two"), "Glossary", "tide: the rise and fall of the sea level in the harbour", "Index", "harbour, 4, 9"])
    pid = projects.import_text(text)
    chs = {c["title"]: c["skip"] for c in projects.get_chapters(pid)}
    assert chs["Contents"] == 1 and chs["Glossary"] == 1 and chs["Index"] == 1
    assert chs["Chapter 1: First"] == 0 and chs["Chapter 2: Second"] == 0
    fake = FakeBackend()
    assert run(pid, fake) == "done"
    skipped_paras = {p["idx"] for p in db.q("SELECT idx,chapter_idx FROM paras WHERE project_id=?", (pid,))
                     if p["chapter_idx"] in {c["idx"] for c in projects.get_chapters(pid) if c["skip"]}}
    analysed = {i for t in pipeline.stage_tasks(pid, "analyze") for i, _, _ in t["input"]["items"]}
    assert skipped_paras and not (skipped_paras & analysed)                  # skipped text never reaches the model
    assert not any("harbour, 4, 9" in c["user"] for c in fake.calls)
    # user can override: un-skip and re-run from analyze
    chs_list = [{"title": c["title"], "start_para": c["start_para"], "skip": False} for c in projects.get_chapters(pid)]
    projects.set_chapters(pid, chs_list)
    pipeline.reset(pid, stage="analyze")
    assert run(pid, FakeBackend()) == "done"
    analysed2 = {i for t in pipeline.stage_tasks(pid, "analyze") for i, _, _ in t["input"]["items"]}
    assert skipped_paras <= analysed2
    with pytest.raises(projects.ProjectError):
        projects.set_chapters(pid, [{"title": "x", "start_para": 1, "skip": True}])


def analysed_paras(pid):
    return {i for t in pipeline.stage_tasks(pid, "analyze") for i, _, _ in t["input"]["items"]}


def test_scope_selected_chapters(book):
    chs = projects.get_chapters(book)
    prev = projects.set_scope(book, {"mode": "chapters", "chapters": [2, 5]})
    assert prev["chapters"] == [2, 5] and prev["tokens"] > 0
    assert run(book, FakeBackend()) == "done"
    wanted = {r["idx"] for r in db.q("SELECT idx FROM paras WHERE project_id=? AND chapter_idx IN (2,5)", (book,))}
    assert analysed_paras(book) == wanted                                    # exactly those chapters, nothing else
    assert {r["idx"] for r in pipeline.done_results(book, "rollup")} == {2, 5}
    assert len(chs) == 8


def test_scope_page_range_and_validation(env, tmp_path):
    from test_ingest import make_pdf
    pid = projects.import_file("b.pdf", make_pdf(tmp_path / "b.pdf").read_bytes())
    prev = projects.set_scope(pid, {"mode": "pages", "page_from": 5, "page_to": 7})
    assert (prev["page_min"], prev["page_max"]) == (5, 7)
    assert run(pid, FakeBackend()) == "done"
    pages = {r["page"] for r in db.q("SELECT page FROM paras WHERE project_id=? AND idx IN (%s)" %
                                     ",".join(map(str, analysed_paras(pid))), (pid,))}
    assert pages == {5, 6, 7}
    for bad in ({"mode": "pages", "page_from": 7, "page_to": 5}, {"mode": "pages", "page_from": 90, "page_to": 99},
                {"mode": "chapters", "chapters": []}, {"mode": "chapters", "chapters": [99]}, {"mode": "nope"},
                {"mode": "pages"}):
        with pytest.raises(projects.ProjectError):
            projects.set_scope(pid, bad)
    assert projects.get_scope(pid)["page_from"] == 5                         # a rejected scope leaves the old one intact


def test_scope_paragraph_range_for_articles_and_all_resets(env):
    pid = projects.import_text(make_book(2, 20))
    with pytest.raises(projects.ProjectError):
        projects.set_scope(pid, {"mode": "pages", "page_from": 1, "page_to": 3})     # text has no page numbers
    projects.set_scope(pid, {"mode": "paras", "para_from": 5, "para_to": 14})
    assert run(pid, FakeBackend()) == "done"
    assert analysed_paras(pid) == set(range(5, 15))
    projects.set_scope(pid, {"mode": "all"})
    pipeline.reset(pid, stage="analyze")
    assert run(pid, FakeBackend()) == "done"
    assert len(analysed_paras(pid)) == projects.get_paras(pid)["total"]


def test_scope_api_requires_confirmation_to_reprocess(env):
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app) as c:                          # lifespan re-points the DB at DATA_DIR/story.db
        pid = projects.import_text(make_book(2, 10))
        c.post("/login", data={"username": config.APP_USER, "password": config.APP_PASSWORD})
        r = c.put(f"/api/projects/{pid}/scope", json={"scope": {"mode": "chapters", "chapters": [1]}})
        assert r.status_code == 200 and r.json()["chapters"] == [1] and not r.json()["reset"]
        run(pid, FakeBackend())
        r = c.put(f"/api/projects/{pid}/scope", json={"scope": {"mode": "chapters", "chapters": [2]}})
        assert r.status_code == 409 and "reprocessing" in r.json()["detail"]
        r = c.put(f"/api/projects/{pid}/scope", json={"scope": {"mode": "chapters", "chapters": [2]}, "reset": True})
        assert r.status_code == 200 and r.json()["reset"] and not pipeline.stage_tasks(pid, "analyze")
        assert c.get(f"/api/projects/{pid}/scope").json()["chapters"] == [2]
