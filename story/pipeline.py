"""Hierarchical, resumable processing pipeline.

Stages (each unit of work is a row in `tasks`, checkpointed in SQLite):
  analyze         per chunk: faithful summary + events, entities, facts, open questions, story seeds
  rollup          per chapter: chapter record (LLM-consolidated summary + programmatic merge of the details)
  index           source-level overview, threads, entity table, timeline
  discover        per window of chapter records: story leads
  discover_global cross-chapter leads (skipped for short sources)
  draft           per deduplicated lead: full story record from the cited raw passages, scored
  finalize        related-story and duplicate warnings (no LLM)
A restart, pause or failure resumes from the first unfinished task; finished work is never repeated.
"""
import asyncio
import math
import re
import time
import traceback

from . import db, eta, projects, scoring, settings as settings_mod
from . import prompts as P
from .chunker import build_chunks
from .llm import ChatBackend, JsonCaller, LLMError, ValidationFailed
from .schemas import BookIndex, ChapterRollup, ChunkAnalysis, Discovery, DraftOut
from .tokens import Budget, BudgetExceeded, pack

STAGES = ["analyze", "rollup", "index", "discover", "discover_global", "draft", "finalize"]
STAGE_LABELS = {
    "analyze": "Analyzing chunks", "rollup": "Consolidating chapters", "index": "Building source index",
    "discover": "Finding stories", "discover_global": "Finding cross-chapter stories",
    "draft": "Drafting story records", "finalize": "Linking related stories",
}
NATURE_RANK = {"story": 0, "": 1, "anecdote": 1, "explainer": 2, "hypothetical": 3}
MAX_SPLIT_DEPTH = 3
MAX_FAIL_STREAK = 3


class Stopped(Exception):
    pass


class Control:
    def __init__(self):
        self.pause = False
        self.cancel = False

    @property
    def stop(self) -> bool:
        return self.pause or self.cancel


# ── task table helpers ──────────────────────────────────────────────────────

def add_task(pid: str, stage: str, key: str, ord_: float, inp: dict) -> None:
    db.ex("INSERT OR IGNORE INTO tasks(project_id,stage,key,ord,input,updated_at) VALUES(?,?,?,?,?,?)",
          (pid, stage, key, ord_, db.jdump(inp), db.now()))


def stage_tasks(pid: str, stage: str, status: str | None = None) -> list[dict]:
    sql = "SELECT * FROM tasks WHERE project_id=? AND stage=?" + (" AND status=?" if status else "") + " ORDER BY ord, id"
    rows = db.q(sql, (pid, stage) + ((status,) if status else ()))
    for r in rows:
        r["input"] = db.jload(r["input"], {})
        r["result"] = db.jload(r["result"], None)
        r["raw_failed"] = db.jload(r["raw_failed"], [])
    return rows


def done_results(pid: str, stage: str) -> list[dict]:
    return [t["result"] for t in stage_tasks(pid, stage, "done") if t["result"] is not None]


def set_project(pid: str, **f) -> None:
    f["updated_at"] = db.now()
    cols = ", ".join(f"{k}=?" for k in f)
    db.ex(f"UPDATE projects SET {cols} WHERE id=?", [db.jdump(v) if isinstance(v, (dict, list)) else v for v in f.values()] + [pid])


def load_paras(pid: str) -> dict[int, dict]:
    return {r["idx"]: r for r in db.q("SELECT idx,page,section,chapter_idx,kind,text FROM paras WHERE project_id=? ORDER BY idx", (pid,))}


def uniq(seq):
    return list(dict.fromkeys(seq))


# ── rendering helpers ───────────────────────────────────────────────────────

def render_item(p: dict, a: int, b: int) -> str:
    text = p["text"][a:] if b == -1 else p["text"][a:b]
    return f"[P{p['idx']}] " + ("## " if p["kind"] == "h" else "") + text


def render_items(paras: dict[int, dict], items) -> str:
    return "\n\n".join(render_item(paras[i], a, b) for i, a, b in items)


def render_pack(paras: dict[int, dict], ids: list[int], context_ids: set[int] | None = None) -> str:
    """Passages for a draft, in source order, with page markers so the model (and reviewers) can place them in the book."""
    out, page = [], object()
    for i in sorted(ids):
        p = paras[i]
        if p["page"] != page:
            page = p["page"]
            if page:
                out.append(f"--- page {page} ---")
        out.append(render_item(p, 0, -1))
    return "\n\n".join(out)


def _ids_str(ids) -> str:
    return ",".join(f"P{i}" for i in ids)


def prune_ids(rows: list[dict], allowed: set[int], need_ids: bool = True) -> tuple[list[dict], int]:
    """Drop invalid paragraph ids; drop whole items that end up with no valid evidence."""
    kept, dropped = [], 0
    for r in rows:
        r = dict(r)
        r["para_ids"] = [i for i in r.get("para_ids", []) if i in allowed]
        if need_ids and not r["para_ids"]:
            dropped += 1
            continue
        kept.append(r)
    return kept, dropped


# ── pipeline ────────────────────────────────────────────────────────────────

class Pipeline:
    def __init__(self, pid: str, backend, ctl: Control | None = None, s: dict | None = None):
        self.pid = pid
        self.s = s or settings_mod.get()
        self.budget = Budget.from_settings(self.s)
        self.caller = JsonCaller(backend, self.s)
        self.ctl = ctl or Control()
        self.proj = db.one("SELECT * FROM projects WHERE id=?", (pid,))
        self._paras: dict[int, dict] | None = None
        self._inflight: set[asyncio.Task] = set()

    @property
    def paras(self) -> dict[int, dict]:
        if self._paras is None:
            self._paras = load_paras(self.pid)
        return self._paras

    def est(self, t: str) -> int:
        return self.budget.est(t)

    def chapter_title(self, idx: int) -> str:
        r = db.one("SELECT title FROM chapters WHERE project_id=? AND idx=?", (self.pid, idx))
        return r["title"] if r else f"Chapter {idx}"

    def src_header(self) -> str:
        a = f" by {self.proj['author']}" if self.proj.get("author") else ""
        return f"SOURCE: {self.proj['title']}{a}"

    # ── driver ──────────────────────────────────────────────────────────────

    async def run(self) -> str:
        """Run until done, stopped, or a stage fails. Returns the resulting project status."""
        pid = self.pid
        run_id = db.ex("INSERT INTO runs(project_id,started_at,status,settings) VALUES(?,?,?,?)",
                       (pid, db.now(), "running", db.jdump({k: v for k, v in self.s.items()})))
        set_project(pid, status="running", error="")
        status, err = "done", ""
        try:
            for stage in STAGES:
                if self.ctl.stop:
                    raise Stopped
                self._plan(stage)
                set_project(pid, stage=stage)
                await self._execute_stage(stage)
                if self.ctl.stop:
                    raise Stopped
                failed = stage_tasks(pid, stage, "failed")
                if failed:
                    status = "error"
                    err = (f"{STAGE_LABELS[stage]}: {len(failed)} task(s) failed - "
                           f"{failed[0]['error'][:300]}. Fix the cause, then use Retry failed.")
                    break
        except Stopped:
            status = "cancelled" if self.ctl.cancel else "paused"
        except asyncio.CancelledError:
            status = "cancelled"
        except Exception as e:  # noqa: BLE001
            status, err = "error", f"{type(e).__name__}: {e}"
            traceback.print_exc()
        finally:
            set_project(pid, status=status, error=err, stage="" if status == "done" else self._cur_stage())
            db.ex("UPDATE runs SET ended_at=?, status=? WHERE id=?", (db.now(), status, run_id))
        return status

    def _cur_stage(self) -> str:
        r = db.one("SELECT stage FROM projects WHERE id=?", (self.pid,))
        return r["stage"] if r else ""

    async def _execute_stage(self, stage: str) -> None:
        handler = getattr(self, f"_do_{stage}")
        streak = 0                                       # consecutive failures: probably systemic, stop early
        while not self.ctl.stop:
            pending = stage_tasks(self.pid, stage, "pending")
            if not pending or streak >= MAX_FAIL_STREAK:
                return
            batch = pending[:max(1, int(self.s["concurrency"]))]
            tasks = [asyncio.ensure_future(self._run_task(t, handler)) for t in batch]
            self._inflight = set(tasks)
            try:
                await asyncio.gather(*tasks)
            except asyncio.CancelledError:
                for t in tasks:
                    t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise
            finally:
                self._inflight = set()
            for t in batch:
                st = db.one("SELECT status FROM tasks WHERE id=?", (t["id"],))["status"]
                streak = streak + 1 if st == "failed" else (0 if st in ("done", "split") else streak)

    def cancel_inflight(self) -> None:
        for t in list(self._inflight):
            t.cancel()

    async def _run_task(self, t: dict, handler) -> None:
        tid = t["id"]
        db.ex("UPDATE tasks SET status='running', attempts=attempts+1, error='', updated_at=? WHERE id=?", (db.now(), tid))
        t0 = time.time()
        try:
            result, usage = await handler(t)
            eta.record(self.pid, t["stage"], self.s["model"], usage.get("in", 0), usage.get("out", 0),
                       int((time.time() - t0) * 1000), int(self.s["context_limit"]))
            db.ex("UPDATE tasks SET status='done', result=?, tokens_in=?, tokens_out=?, duration_ms=?, error='', updated_at=? WHERE id=?",
                  (db.jdump(result), usage.get("in", 0), usage.get("out", 0), int((time.time() - t0) * 1000), db.now(), tid))
        except asyncio.CancelledError:
            db.ex("UPDATE tasks SET status='pending', updated_at=? WHERE id=?", (db.now(), tid))
            raise
        except (ValidationFailed, BudgetExceeded) as e:
            if t["stage"] == "analyze" and self._split_analyze(t, getattr(e, "truncated", False) or isinstance(e, BudgetExceeded)):
                return
            raw = getattr(e, "raw", [])
            db.ex("UPDATE tasks SET status='failed', error=?, raw_failed=?, duration_ms=?, updated_at=? WHERE id=?",
                  (str(e)[:1000], db.jdump(raw), int((time.time() - t0) * 1000), db.now(), tid))
        except LLMError as e:
            db.ex("UPDATE tasks SET status='failed', error=?, duration_ms=?, updated_at=? WHERE id=?",
                  (str(e)[:1000], int((time.time() - t0) * 1000), db.now(), tid))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            db.ex("UPDATE tasks SET status='failed', error=?, updated_at=? WHERE id=?",
                  (f"{type(e).__name__}: {e}"[:1000], db.now(), tid))

    # ── planning ────────────────────────────────────────────────────────────

    def _plan(self, stage: str) -> None:
        if db.one("SELECT 1 x FROM tasks WHERE project_id=? AND stage=? LIMIT 1", (self.pid, stage)):
            return
        getattr(self, f"_plan_{stage}")()

    def _plan_analyze(self) -> None:
        instr = self.est(P.ANALYZE) + 400
        target = self.budget.chunk_target(int(self.s["chunk_tokens"]), instr)
        include = projects.resolve_scope(self.pid)
        rows = [{"idx": p["idx"], "chapter_idx": p["chapter_idx"], "text": p["text"]}
                for p in self.paras.values() if p["idx"] in include]
        if not rows:
            raise ValueError("nothing to process: the selected scope (or skip flags) leaves no text")
        chunks = build_chunks(rows, target, int(self.s["chunk_overlap"]), self.est)
        for n, c in enumerate(chunks):
            add_task(self.pid, "analyze", f"c{n:04d}", n,
                     {"items": c.items, "context": c.context, "chapter_idxs": c.chapter_idxs})

    def _analyses(self) -> list[dict]:
        out = []
        for t in stage_tasks(self.pid, "analyze", "done"):
            if t["result"]:
                out.append({**t["result"], "key": t["key"], "ord": t["ord"]})
        return out

    def _plan_rollup(self) -> None:
        chs = sorted({c for a in self._analyses() for c in a["chapter_idxs"]})
        for c in chs:
            add_task(self.pid, "rollup", f"ch{c:04d}", c, {"chapter_idx": c})

    def _plan_index(self) -> None:
        add_task(self.pid, "index", "book", 0, {})

    def _plan_discover(self) -> None:
        recs = done_results(self.pid, "rollup")
        idx = self._index_result()
        overview = idx.get("overview", "") if idx else ""
        limit = self.budget.input_limit(self.est(P.DISCOVER) + self.est(overview) + 300)
        levels, sizes = {}, []
        for r in recs:
            for lvl in (2, 1, 0):
                text, _ = render_chapter(r, lvl)
                if self.est(text) <= limit:
                    levels[r["idx"]] = lvl
                    sizes.append(self.est(text))
                    break
            else:
                raise BudgetExceeded(f"chapter {r['idx']} notes do not fit the input budget even at the lowest detail")
        win = max(1, int(self.s.get("discover_window_chapters", 3)))
        groups = [g[k:k + win] for g in pack(sizes, limit) for k in range(0, len(g), win)]
        for n, grp in enumerate(groups):
            add_task(self.pid, "discover", f"w{n:03d}", n,
                     {"chapters": [recs[i]["idx"] for i in grp], "levels": {str(recs[i]["idx"]): levels[recs[i]["idx"]] for i in grp}})

    def _plan_discover_global(self) -> None:
        n_ch = len(done_results(self.pid, "rollup"))
        if n_ch >= 3 or len(stage_tasks(self.pid, "discover")) >= 2:
            add_task(self.pid, "discover_global", "g", 0, {})

    def _plan_draft(self) -> None:
        stubs = []
        for stage in ("discover", "discover_global"):
            for r in done_results(self.pid, stage):
                stubs.extend(r.get("stubs", []))
        stubs.extend(self._uncovered_seeds(stubs))
        merged = dedupe_stubs(stubs, self.paras)
        merged.sort(key=lambda s: (NATURE_RANK.get(s.get("nature", ""), 1), -s["potential"], min(s["para_ids"])))
        cap = int(self.s["max_candidates"])
        chosen, leads = merged[:cap], merged[cap:]
        for n, st in enumerate(chosen):
            add_task(self.pid, "draft", f"d{n:03d}", n, {"stub": st})
        meta = db.jload(self.proj.get("meta"), {}) or {}
        meta["leads"] = leads
        meta["lead_total"] = len(merged)
        set_project(self.pid, meta=meta)
        if not merged:
            w = db.jload(db.one("SELECT warnings FROM projects WHERE id=?", (self.pid,))["warnings"], [])
            msg = "No story candidates were found in this source."
            if msg not in w:
                set_project(self.pid, warnings=w + [msg])

    def _uncovered_seeds(self, stubs: list[dict]) -> list[dict]:
        """Raw story seeds noticed while reading that discovery did not shortlist. They become low-priority leads, so a
        chapter summary that favours broad themes can never hide a concrete event from the review."""
        taken = [set(s["para_ids"]) for s in stubs]
        out = []
        for rec in done_results(self.pid, "rollup"):
            for sd in rec.get("seeds", []):
                ids = set(sd["para_ids"])
                if not ids or any(len(ids & t) / len(ids) >= 0.5 for t in taken):
                    continue
                taken.append(ids)
                out.append({"title": sd["title"], "premise": sd["premise"] or sd["title"], "why": "Noticed while reading; not shortlisted by discovery.",
                            "nature": "", "kind": "incident", "potential": 3.0, "para_ids": sorted(ids), "origin": "seed",
                            "chapter_idxs": uniq(self.paras[i]["chapter_idx"] for i in sorted(ids) if i in self.paras)})
        return out

    def _plan_finalize(self) -> None:
        add_task(self.pid, "finalize", "all", 0, {})

    # ── model call helper ───────────────────────────────────────────────────

    async def _call(self, system: str, user: str, model_cls, validate=None):
        res = await self.caller.call(system, user, model_cls, validate)
        return res, {"in": res.tokens_in, "out": res.tokens_out}

    # ── stage: analyze ──────────────────────────────────────────────────────

    async def _do_analyze(self, t: dict):
        inp = t["input"]
        items = [tuple(x) for x in inp["items"]]
        ctx = [tuple(x) for x in inp.get("context", [])]
        names = "; ".join(f"{c}. {self.chapter_title(c)}" for c in inp["chapter_idxs"])
        user = f"{self.src_header()}\nCHAPTER(S): {names}\n\nMAIN TEXT:\n{render_items(self.paras, items)}"
        if ctx:
            user += f"\n\nCONTEXT (end of the previous portion, already analysed):\n{render_items(self.paras, ctx)}"
        allowed = {i for i, _, _ in items} | {i for i, _, _ in ctx}
        res, usage = await self._call(P.ANALYZE, user, ChunkAnalysis)
        d = res.value.model_dump()
        warn = []
        for key in ("events", "facts", "story_seeds"):
            d[key], dropped = prune_ids(d[key], allowed)
            if dropped:
                warn.append(f"{dropped} {key} dropped: cited paragraphs outside this chunk")
        d["entities"], _ = prune_ids(d["entities"], allowed, need_ids=False)
        d["chapter_idxs"] = inp["chapter_idxs"]
        d["warnings"] = warn
        d["para_range"] = [min(allowed), max(allowed)]
        return d, usage

    def _split_analyze(self, t: dict, can_split: bool) -> bool:
        """The reply was cut off or the chunk no longer fits: halve it into two follow-up tasks."""
        inp = t["input"]
        items = inp["items"]
        depth = t["key"].count(".")
        if not can_split or len(items) < 2 or depth >= MAX_SPLIT_DEPTH:
            return False
        mid = len(items) // 2
        halves = [items[:mid], items[mid:]]
        overlap = int(self.s["chunk_overlap"])
        for i, half in enumerate(halves):
            ctx = inp.get("context", []) if i == 0 else []
            if i == 1:
                used = 0
                for it in reversed(halves[0]):
                    tok = self.est(self.paras[it[0]]["text"][it[1]:(None if it[2] == -1 else it[2])]) + 4
                    if used + tok > overlap:
                        break
                    ctx.insert(0, it)
                    used += tok
            chs = uniq(self.paras[x[0]]["chapter_idx"] for x in half)
            add_task(self.pid, "analyze", f"{t['key']}.{i}", t["ord"] + i * (0.5 ** (depth + 1)),
                     {"items": half, "context": ctx, "chapter_idxs": chs})
        db.ex("UPDATE tasks SET status='split', error='split after oversized/cut-off reply', updated_at=? WHERE id=?",
              (db.now(), t["id"]))
        return True

    # ── stage: rollup ───────────────────────────────────────────────────────

    async def _do_rollup(self, t: dict):
        ch = t["input"]["chapter_idx"]
        paras = self.paras
        in_ch = lambda ids: bool(ids) and paras[ids[0]]["chapter_idx"] == ch  # noqa: E731
        anas = [a for a in self._analyses() if ch in a["chapter_idxs"]]
        rec = {
            "idx": ch, "title": self.chapter_title(ch), "analyses": len(anas),
            "events": [e for a in anas for e in a["events"] if in_ch(e["para_ids"])],
            "facts": [f for a in anas for f in a["facts"] if in_ch(f["para_ids"])],
            "seeds": [s for a in anas for s in a["story_seeds"] if in_ch(s["para_ids"])],
            "open_questions": uniq(q for a in anas for q in a["open_questions"]),
            "entities": merge_entities([e for a in anas for e in a["entities"]]),
        }
        usage = {"in": 0, "out": 0}
        if len(anas) == 1 and len(anas[0]["chapter_idxs"]) == 1:
            rec.update(summary=anas[0]["summary"], themes=[], threads=[s["title"] for s in rec["seeds"]], direct=True)
            return rec, usage
        notes = []
        for k, a in enumerate(anas, 1):
            ev = "\n".join(f"- {e['when'] + ': ' if e['when'] else ''}{e['what']}" for e in a["events"] if in_ch(e["para_ids"]))
            notes.append(f"PART {k} OF {len(anas)}:\nSummary: {a['summary']}" + (f"\nKey events:\n{ev}" if ev else ""))
        out = await self._reduce(P.ROLLUP, f"{self.src_header()}\nCHAPTER {ch}: {rec['title']}\n\n", notes, ChapterRollup,
                                 lambda r: f"SECTION NOTES:\nSummary: {r.summary}\nThemes: {'; '.join(r.themes)}", usage)
        rec.update(summary=out.summary, themes=out.themes, threads=out.threads, direct=False)
        return rec, usage

    async def _reduce(self, system: str, header: str, notes: list[str], model_cls, render_partial, usage: dict):
        """Map-reduce over text notes that may not fit one request: pack, call, and recurse on the partial results."""
        for _ in range(6):
            limit = self.budget.input_limit(self.est(system) + self.est(header) + 200)
            groups = pack([self.est(n) for n in notes], limit)
            outs = []
            for g in groups:
                res, u = await self._call(system, header + "\n\n".join(notes[i] for i in g), model_cls)
                usage["in"] += u["in"]
                usage["out"] += u["out"]
                outs.append(res.value)
            if len(outs) == 1:
                return outs[0]
            notes = [render_partial(o) for o in outs]
        raise BudgetExceeded("could not reduce notes into a single request")

    # ── stage: index ────────────────────────────────────────────────────────

    def _index_result(self) -> dict | None:
        r = done_results(self.pid, "index")
        return r[0] if r else None

    async def _do_index(self, t: dict):
        recs = sorted(done_results(self.pid, "rollup"), key=lambda r: r["idx"])
        usage = {"in": 0, "out": 0}
        ents = merge_entities([{**e, "chapter": r["idx"]} for r in recs for e in r["entities"]])
        timeline = [{"when": e["when"], "what": e["what"], "chapter": r["idx"], "para_ids": e["para_ids"]}
                    for r in recs for e in r["events"] if e["when"]]
        base = {"entities": ents[:300], "timeline": timeline[:400], "chapters": len(recs),
                "events": sum(len(r["events"]) for r in recs), "facts": sum(len(r["facts"]) for r in recs)}
        if len(recs) == 1:
            r = recs[0]
            return {**base, "overview": r["summary"], "themes": r["themes"],
                    "threads": [{"title": x, "description": "", "chapter_idxs": [r["idx"]], "para_ids": []} for x in r["threads"]],
                    "direct": True}, usage
        notes = [f"CHAPTER {r['idx']}: {r['title']}\n{r['summary']}\nThemes: {'; '.join(r['themes'])}\nThreads: {'; '.join(r['threads'])}"
                 for r in recs]
        out = await self._reduce(
            P.INDEX, f"{self.src_header()}\n\n", notes, BookIndex,
            lambda o: "PARTIAL INDEX:\n" + o.overview + "\nThemes: " + "; ".join(o.themes) + "\nThreads: " +
                      "; ".join(f"{x.title} (chapters {x.chapter_idxs})" for x in o.threads), usage)
        valid = {r["idx"] for r in recs}
        threads = [{**x.model_dump(), "chapter_idxs": [c for c in x.chapter_idxs if c in valid]} for x in out.threads]
        return {**base, "overview": out.overview, "themes": out.themes, "threads": threads, "direct": False}, usage

    # ── stage: discover ─────────────────────────────────────────────────────

    async def _do_discover(self, t: dict):
        recs = {r["idx"]: r for r in done_results(self.pid, "rollup")}
        idx = self._index_result() or {}
        parts, allowed = [], set()
        for ch in t["input"]["chapters"]:
            text, ids = render_chapter(recs[ch], t["input"]["levels"][str(ch)])
            parts.append(text)
            allowed |= ids
        user = f"{self.src_header()}\nOVERVIEW: {idx.get('overview', '')}\n\nCHAPTER NOTES:\n\n" + "\n\n".join(parts)
        n_items = min(12, 3 * len(t["input"]["chapters"]) + 2)
        res, usage = await self._call(P.DISCOVER.replace("{max_items}", str(n_items)), user, Discovery)
        stubs, dropped = prune_ids([s.model_dump() for s in res.value.candidates], allowed)
        return {"stubs": self._finish_stubs(stubs), "dropped": dropped}, usage

    def _finish_stubs(self, stubs: list[dict]) -> list[dict]:
        for s in stubs:
            s["para_ids"] = sorted(set(s["para_ids"]))
            s["chapter_idxs"] = uniq(self.paras[i]["chapter_idx"] for i in s["para_ids"])
        return stubs

    async def _do_discover_global(self, t: dict):
        idx = self._index_result() or {}
        recs = sorted(done_results(self.pid, "rollup"), key=lambda r: r["idx"])
        existing = []
        for stage in ("discover",):
            for r in done_results(self.pid, stage):
                existing.extend(r.get("stubs", []))
        existing.sort(key=lambda s: -s["potential"])
        limit = self.budget.input_limit(self.est(P.DISCOVER_GLOBAL) + 300)
        for per_chapter, with_premise in ((6, True), (3, True), (3, False), (1, False)):
            allowed: set[int] = set()
            lines = [f"OVERVIEW: {idx.get('overview', '')}", "", "CROSS-CHAPTER THREADS:"]
            for th in idx.get("threads", []):
                lines.append(f"- {th['title']} (chapters {th['chapter_idxs']}): {th.get('description', '')}")
            lines += ["", "KEY EVENTS BY CHAPTER (first few per chapter):"]
            for r in recs:
                lines.append(f"Chapter {r['idx']} - {r['title']}")
                for e in r["events"][:per_chapter]:
                    lines.append(f"  [{_ids_str(e['para_ids'])}] {e['what']}")
                    allowed |= set(e["para_ids"])
            lines += ["", "STORIES ALREADY FOUND (do not repeat):"]
            for s in existing:
                lines.append(f"- {s['title']}" + (f" :: {s['premise']}" if with_premise else "") + f" [{_ids_str(s['para_ids'])}]")
                allowed |= set(s["para_ids"])
            user = f"{self.src_header()}\n\n" + "\n".join(lines)
            if self.est(user) <= limit:
                break
        else:
            raise BudgetExceeded("cross-chapter material does not fit the input budget; raise the context limit")
        res, usage = await self._call(P.DISCOVER_GLOBAL.replace("{max_items}", "6"), user, Discovery)
        stubs, dropped = prune_ids([s.model_dump() for s in res.value.candidates], allowed)
        return {"stubs": self._finish_stubs(stubs), "dropped": dropped}, usage

    # ── stage: draft ────────────────────────────────────────────────────────

    async def _do_draft(self, t: dict):
        stub = t["input"]["stub"]
        paras = self.paras
        old = db.one("SELECT id FROM candidates WHERE task_id=? AND edited=0", (t["id"],))
        if old:
            delete_candidate(old["id"])
        ids = sorted(i for i in stub["para_ids"] if i in paras)
        head = (f"{self.src_header()}\nSTORY LEAD: {stub['title']}\nPremise: {stub['premise']}\n"
                f"Why it may matter: {stub.get('why', '')}\n\n")
        limit = self.budget.input_limit(self.est(P.DRAFT) + self.est(head) + 300)
        raw_ids, left, used = [], [], 0
        for i in ids:
            cost = self.est(render_item(paras[i], 0, -1)) + 2
            if used + cost <= limit * 0.75 or not raw_ids:
                if used + cost > limit:
                    raise BudgetExceeded(f"passage P{i} alone exceeds the input budget")
                raw_ids.append(i)
                used += cost
            else:
                left.append(i)
        warnings = []
        # surrounding paragraphs of the same chapter give the model the setup and aftermath around each cited passage
        room = limit * 0.75 - used
        near = []
        for i in raw_ids:
            for j in (i - 1, i + 1):
                if j in paras and j not in raw_ids and j not in near and paras[j]["chapter_idx"] == paras[i]["chapter_idx"]:
                    cost = self.est(render_item(paras[j], 0, -1)) + 2
                    if cost <= room * 0.5:
                        near.append(j)
                        room -= cost
                        used += cost
        shown = sorted(raw_ids + near)
        sections = [head + "RAW PASSAGES:\n(source order; --- page N --- markers show where each passage sits in the book)\n\n"
                    + render_pack(paras, shown)]
        note_ids: set[int] = set()
        if left:
            anas = self._analyses()
            notes = []
            for a in anas:
                for e in a["events"] + a["facts"]:
                    if set(e["para_ids"]) & set(left):
                        notes.append(f"- [{_ids_str(e['para_ids'])}] " + (e.get("what") or e.get("claim")))
                        note_ids |= set(e["para_ids"]) & set(left)
            room = limit - used
            keep, tot = [], 0
            for n in uniq(notes):
                if tot + self.est(n) > room * 0.6:
                    warnings.append("Some supporting notes were omitted because the passages exceed the context budget.")
                    break
                keep.append(n)
                tot += self.est(n)
            sections.append("NOTES (second-hand summaries of cited passages that did not fit):\n" + "\n".join(keep))
            warnings.append(f"{len(left)} cited passage(s) were too long to include verbatim; "
                            "those parts are based on earlier analysis notes only.")
            used += tot
        # optional background, added only while it fits
        room = limit - used
        ctx_lines = []
        for ch in stub.get("chapter_idxs", []):
            rec = next((r for r in done_results(self.pid, "rollup") if r["idx"] == ch), None)
            if rec:
                ctx_lines.append(f"Chapter {ch} ({rec['title']}): {rec['summary']}")
        idx = self._index_result() or {}
        for block in (("BACKGROUND (source overview): " + idx.get("overview", "")) if idx.get("overview") else "",
                      "BACKGROUND (chapter context):\n" + "\n".join(ctx_lines) if ctx_lines else ""):
            if block and self.est(block) <= room:
                sections.append(block)
                room -= self.est(block)
        user = "\n\n".join(sections)
        valid_ids = set(shown) | note_ids
        raw_text = {i: paras[i]["text"] for i in shown}

        def validate(d: DraftOut):
            if not any(set(c.para_ids) & valid_ids or c.quote for c in d.claims):
                raise ValueError("claims must cite passage ids shown above (para_ids)")

        res, usage = await self._call(P.DRAFT, user, DraftOut, validate)
        cand_id = save_candidate(self.pid, t["id"], res.value, stub, raw_text, valid_ids, warnings, self.s,
                                 provenance={"model": self.s["model"], "tokens_in": res.tokens_in, "tokens_out": res.tokens_out})
        return {"candidate_id": cand_id}, usage

    # ── stage: finalize ─────────────────────────────────────────────────────

    async def _do_finalize(self, t: dict):
        link_candidates(self.pid)
        return {"ok": True}, {"in": 0, "out": 0}


# ── pure helpers ────────────────────────────────────────────────────────────

def render_chapter(rec: dict, level: int) -> tuple[str, set[int]]:
    """Compact chapter notes at three detail levels (2 = full, 0 = summary + story seeds). Returns (text, ids shown)."""
    ids: set[int] = set()
    out = [f"CHAPTER {rec['idx']}: {rec['title']}", rec["summary"]]
    if rec.get("themes"):
        out.append("Themes: " + "; ".join(rec["themes"]))
    if level >= 1 and rec["events"]:
        out.append("Events:")
        for e in rec["events"]:
            out.append(f"- [{_ids_str(e['para_ids'])}] " + (f"{e['when']}: " if e["when"] else "") + e["what"])
            ids |= set(e["para_ids"])
    if level >= 2 and rec["facts"]:
        out.append("Facts:")
        for f in rec["facts"]:
            out.append(f"- [{_ids_str(f['para_ids'])}] {f['claim']}" + (f" ({f['caveat']})" if f["caveat"] else ""))
            ids |= set(f["para_ids"])
    if rec["seeds"]:
        out.append("Story seeds noticed:")
        for s in rec["seeds"]:
            out.append(f"- [{_ids_str(s['para_ids'])}] {s['title']}: {s['premise']}")
            ids |= set(s["para_ids"])
    return "\n".join(out), ids


def merge_entities(ents: list[dict]) -> list[dict]:
    by: dict[str, dict] = {}
    for e in ents:
        k = re.sub(r"\s+", " ", e["name"].strip().lower())
        if not k:
            continue
        m = by.setdefault(k, {"name": e["name"].strip(), "roles": [], "para_ids": [], "chapters": [], "mentions": 0})
        if e.get("role") and e["role"] not in m["roles"] and len(m["roles"]) < 4:
            m["roles"].append(e["role"])
        m["para_ids"] = uniq(m["para_ids"] + list(e.get("para_ids", [])))
        if e.get("chapter") is not None and e["chapter"] not in m["chapters"]:
            m["chapters"].append(e["chapter"])
        m["mentions"] += 1
    return sorted(by.values(), key=lambda m: -m["mentions"])


_STOP = {"the", "and", "for", "with", "from", "that", "this", "his", "her", "its", "into", "how", "why", "what", "who"}


def _tokens(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", t.lower()) if len(w) > 2 and w not in _STOP}


def similar_titles(a: str, b: str) -> bool:
    """Same wording after dropping filler words, or at least two shared words with high overlap."""
    ta, tb = _tokens(a), _tokens(b)
    return bool(ta) and (ta == tb or (_jac(ta, tb) >= 0.75 and len(ta & tb) >= 2))


def _jac(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def dedupe_stubs(stubs: list[dict], paras: dict[int, dict] | None = None) -> list[dict]:
    """Merge leads that point at largely the same passages (or share a near-identical title).
    Passage ids are unioned so no source link is lost; merged titles are kept for the record."""
    out: list[dict] = []
    for s in sorted(stubs, key=lambda s: -s["potential"]):
        ids = set(s["para_ids"])
        hit = None
        for o in out:
            oi = set(o["para_ids"])
            contained = len(ids & oi) / max(1, min(len(ids), len(oi)))
            similar_size = min(len(ids), len(oi)) / max(1, max(len(ids), len(oi))) >= 0.5
            # a broad cross-chapter story that merely contains several narrow ones is kept separate (flagged as related)
            if _jac(ids, oi) >= 0.5 or (contained >= 0.8 and similar_size) or similar_titles(s["title"], o["title"]):
                hit = o
                break
        if hit is None:
            out.append({**s, "para_ids": sorted(ids), "merged_titles": []})
        else:
            hit["para_ids"] = sorted(set(hit["para_ids"]) | ids)
            hit["merged_titles"] = uniq(hit["merged_titles"] + [s["title"]])
            hit["chapter_idxs"] = uniq(hit.get("chapter_idxs", []) + s.get("chapter_idxs", []))
    return out


def next_story_id(pid: str, c) -> str:
    n = c.execute("SELECT next_story_no FROM projects WHERE id=?", (pid,)).fetchone()["next_story_no"]
    c.execute("UPDATE projects SET next_story_no=? WHERE id=?", (n + 1, pid))
    return f"S-{pid[:6]}-{n:03d}"


def save_candidate(pid: str, task_id: int | None, d: DraftOut, stub: dict, raw_text: dict[int, str],
                   valid_ids: set[int], warnings: list[str], s: dict, provenance: dict | None = None) -> str:
    claims = []
    all_raw = list(raw_text.values())
    for c in d.claims:
        cited = [i for i in c.para_ids if i in valid_ids]
        verified = scoring.verify_quote(c.quote, [raw_text[i] for i in cited if i in raw_text] or all_raw)
        if c.quote and verified and not [i for i in cited if i in raw_text]:
            cited = [i for i, t in raw_text.items() if scoring.verify_quote(c.quote, [t])]
        # provenance: "quoted" must be backed by a quote that was actually found; the model's word is never enough
        basis = c.basis or ("quoted" if verified else "summarised")
        if basis == "quoted" and verified is not True:
            basis = "summarised"
        claims.append({"claim": c.claim, "quote": c.quote, "para_ids": cited, "support": c.support,
                       "quote_verified": verified, "basis": basis})
    refs = sorted({i for i in stub["para_ids"] if i in valid_ids} | {i for c in claims for i in c["para_ids"]})
    if not refs:
        raise ValueError("story has no valid source references")
    page_of = {r["idx"]: r["page"] for r in db.q("SELECT idx,page FROM paras WHERE project_id=?", (pid,))}
    pages = [page_of[i] for i in refs if page_of.get(i)]
    span = (max(pages) - min(pages)) if pages else None
    cited_text = [raw_text[i] for i in refs if i in raw_text] or all_raw

    chronology, flags = [], []
    for e in d.chronology:
        ids = [i for i in e.para_ids if i in valid_ids]
        texts = [raw_text[i] for i in ids if i in raw_text] or cited_text
        basis = "inferred" if not ids else (e.basis or "summarised")
        chronology.append({"when": e.when, "when_basis": scoring.date_basis(e.when, texts), "what": e.what,
                           "basis": basis, "para_ids": ids})
    if any(c["when"] and c["when_basis"] == "stated" and not re.search(r"\b\d{4}\b", c["when"]) for c in chronology) \
            and not scoring.has_year(cited_text):
        flags.append({"code": "date_no_year", "text": "Dates in the source carry no year; do not state one without checking."})
    if any(c["when_basis"] == "inferred" for c in chronology):
        flags.append({"code": "date_inferred", "text": "Some dates are not stated in the cited passages (marked inferred)."})

    nature, notes = scoring.final_nature(d.nature or stub.get("nature", ""), cited_text, len(chronology), bool(d.outcome))
    for n in notes:
        flags.append({"code": "nature", "text": n})
    if span is not None and span > 40:
        flags.append({"code": "stitched", "text": f"Cited passages are {span} pages apart ({min(pages)}-{max(pages)}); "
                                                  "the sequence may be assembled from separate sections."})
    for g in d.gaps + ([] if d.outcome else ["The outcome is not stated in the cited passages."]):
        flags.append({"code": "gap", "text": g})
    for t in d.title_flags:
        flags.append({"code": "title", "text": f"Possible name clash (from model knowledge, unverified): {t}"})

    ev100, breakdown = scoring.evidence_score(d.evidence.score, claims, len(refs))
    factors = {k: getattr(d.scores, k).model_dump() for k in scoring.FACTORS}
    story = scoring.story_score({k: v["score"] for k, v in factors.items()}, s["weights"])
    shell = {"turning_point": d.turning_point, "outcome": d.outcome, "conflict": d.conflict, "stakes": d.stakes,
             "chronology": chronology}
    comp, comp_detail = scoring.completeness(shell, nature, span)
    prio = scoring.priority(story, ev100, s["evidence_influence"], comp, s.get("completeness_influence", 0.0))
    unverified = sum(1 for c in claims if c["quote"] and c["quote_verified"] is False)
    if unverified:
        warnings = warnings + [f"{unverified} supporting quote(s) could not be found verbatim in the cited passages."]
    data = {
        "nature": nature, "curiosity_question": d.curiosity_question, "opening_hook": d.opening_hook, "overview": d.overview,
        "people": [p.model_dump() for p in d.people], "chronology": chronology,
        "conflict": d.conflict, "stakes": d.stakes, "turning_point": d.turning_point, "outcome": d.outcome,
        "audience_interest": d.audience_interest, "context_needed": d.context_needed, "claims": claims,
        "uncertainties": d.uncertainties, "research_questions": d.research_questions,
        "gaps": d.gaps, "flags": flags,
        "scores": factors,
        "evidence": {**d.evidence.model_dump(), "score_100": ev100, "breakdown": breakdown},
        "completeness": {"score": comp, **comp_detail},
        "why": stub.get("why", ""), "chapter_idxs": stub.get("chapter_idxs", []),
        "warnings": warnings, "related": [], "duplicate_warnings": [],
        "lineage": {"merged_from": [], "split_from": None, "lead_titles": [stub["title"]] + stub.get("merged_titles", [])},
        "provenance": provenance or {},
    }
    with db.tx() as c:
        cid = next_story_id(pid, c)
        c.execute("INSERT INTO candidates(id,project_id,task_id,title,premise,kind,nature,completeness,story_score,evidence_score,"
                  "priority,origin,created_at,updated_at,data) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (cid, pid, task_id, d.title, d.premise, stub.get("kind", ""), nature, comp, story, ev100, prio, "pipeline",
                   db.now(), db.now(), db.jdump(data)))
        for i in refs:
            c.execute("INSERT INTO candidate_refs(candidate_id,para_idx) VALUES(?,?)", (cid, i))
    return cid


def delete_candidate(cid: str) -> None:
    with db.tx() as c:
        c.execute("DELETE FROM candidate_refs WHERE candidate_id=?", (cid,))
        c.execute("DELETE FROM candidates WHERE id=?", (cid,))


def link_candidates(pid: str) -> None:
    """Flag overlapping stories as related / probable duplicates. Never merges anything automatically."""
    rows = db.q("SELECT id,title,data FROM candidates WHERE project_id=? AND status!='superseded'", (pid,))
    refs: dict[str, set[int]] = {r["id"]: set() for r in rows}
    for r in db.q("SELECT candidate_id,para_idx FROM candidate_refs WHERE candidate_id IN "
                  "(SELECT id FROM candidates WHERE project_id=?)", (pid,)):
        refs.get(r["candidate_id"], set()).add(r["para_idx"])
    for r in rows:
        data = db.jload(r["data"], {})
        rel, dup = [], []
        for o in rows:
            if o["id"] == r["id"]:
                continue
            j = _jac(refs[r["id"]], refs[o["id"]])
            if j >= 0.6 or similar_titles(r["title"], o["title"]):
                dup.append({"id": o["id"], "title": o["title"], "overlap": round(j, 2)})
            elif j >= 0.2:
                rel.append({"id": o["id"], "title": o["title"], "overlap": round(j, 2)})
        data["related"], data["duplicate_warnings"] = rel, dup
        db.ex("UPDATE candidates SET data=? WHERE id=?", (db.jdump(data), r["id"]))


# ── control / progress ──────────────────────────────────────────────────────

def reset(pid: str, stage: str | None = None, failed_only: bool = False, task_id: int | None = None) -> None:
    """Prepare reprocessing. failed_only/task_id: just re-queue failed tasks. stage: drop that stage and
    everything after it (unreviewed pipeline stories are removed; reviewed or edited ones are kept)."""
    if task_id is not None:
        db.ex("UPDATE tasks SET status='pending', attempts=0, error='' WHERE id=? AND project_id=?", (task_id, pid))
    elif failed_only or not stage:
        db.ex("UPDATE tasks SET status='pending', attempts=0, error='' WHERE project_id=? AND status IN ('failed','running')", (pid,))
    else:
        if stage not in STAGES:
            raise ValueError(f"unknown stage {stage!r}")
        later = STAGES[STAGES.index(stage):]
        q = ",".join("?" * len(later))
        if "draft" in later:
            for c in db.q("SELECT id,status,edited FROM candidates WHERE project_id=? AND origin='pipeline' AND status!='superseded'", (pid,)):
                if c["status"] == "pending" and not c["edited"]:
                    delete_candidate(c["id"])
                else:
                    db.ex("UPDATE candidates SET task_id=NULL WHERE id=?", (c["id"],))
        db.ex(f"DELETE FROM tasks WHERE project_id=? AND stage IN ({q})", [pid] + later)
    set_project(pid, error="", status="imported" if not db.one("SELECT 1 x FROM tasks WHERE project_id=? LIMIT 1", (pid,)) else "paused")


def recover(pid: str | None = None) -> None:
    """After a crash/restart: tasks that were mid-flight go back to pending."""
    if pid:
        db.ex("UPDATE tasks SET status='pending' WHERE project_id=? AND status='running'", (pid,))
    else:
        db.ex("UPDATE tasks SET status='pending' WHERE status='running'")


def expand_leads(pid: str, count: int) -> int:
    """Draft more stories from leads that were over the max_candidates cap."""
    p = db.one("SELECT meta FROM projects WHERE id=?", (pid,))
    meta = db.jload(p["meta"], {})
    leads = meta.get("leads", [])
    take, rest = leads[:count], leads[count:]
    n0 = (db.one("SELECT COUNT(*) n FROM tasks WHERE project_id=? AND stage='draft'", (pid,)) or {"n": 0})["n"]
    for k, st in enumerate(take):
        add_task(pid, "draft", f"d{n0 + k:03d}", n0 + k, {"stub": st})
    meta["leads"] = rest
    set_project(pid, meta=meta)
    if take:
        db.ex("DELETE FROM tasks WHERE project_id=? AND stage='finalize'", (pid,))
    return len(take)


def progress(pid: str) -> dict:
    rows = db.q("SELECT stage,status,COUNT(*) n,COALESCE(SUM(tokens_in),0) ti,COALESCE(SUM(tokens_out),0) to_,"
                "COALESCE(SUM(duration_ms),0) ms FROM tasks WHERE project_id=? GROUP BY stage,status", (pid,))
    stages = []
    for st in STAGES:
        c = {"stage": st, "label": STAGE_LABELS[st], "total": 0, "done": 0, "failed": 0, "pending": 0, "running": 0,
             "tokens_in": 0, "tokens_out": 0, "seconds": 0.0}
        for r in rows:
            if r["stage"] != st:
                continue
            c["total"] += r["n"]
            key = "done" if r["status"] in ("done", "split") else r["status"]
            c[key] = c.get(key, 0) + r["n"]
            c["tokens_in"] += r["ti"]
            c["tokens_out"] += r["to_"]
            c["seconds"] += r["ms"] / 1000
        c["seconds"] = round(c["seconds"], 1)
        c["state"] = ("failed" if c["failed"] else "done" if c["total"] and c["done"] == c["total"]
                      else "running" if c["running"] else "queued" if c["total"] else "waiting")
        stages.append(c)
    errs = db.q("SELECT id,stage,key,error,attempts,raw_failed FROM tasks WHERE project_id=? AND status='failed' ORDER BY id LIMIT 20", (pid,))
    for e in errs:
        e["raw_failed"] = db.jload(e["raw_failed"], [])
    proj = db.one("SELECT status,stage,error,meta FROM projects WHERE id=?", (pid,))
    meta = db.jload(proj["meta"], {})
    return {"status": proj["status"], "stage": proj["stage"], "error": proj["error"], "stages": stages,
            "tokens_in": sum(s["tokens_in"] for s in stages), "tokens_out": sum(s["tokens_out"] for s in stages),
            "seconds": round(sum(s["seconds"] for s in stages), 1), "errors": errs,
            "leads_remaining": len(meta.get("leads", [])), "leads_total": meta.get("lead_total", 0)}


# ── manager: background runs, pause/cancel, restart recovery ────────────────

class Manager:
    def __init__(self):
        self.runs: dict[str, tuple[asyncio.Task, Control, Pipeline | None]] = {}
        self.backend_factory = lambda s: ChatBackend(s, settings_mod.api_key())

    def is_running(self, pid: str) -> bool:
        r = self.runs.get(pid)
        return bool(r and not r[0].done())

    def busy(self) -> bool:
        return any(self.is_running(p) for p in list(self.runs))

    def start(self, pid: str) -> bool:
        if self.is_running(pid):
            return False
        ctl = Control()
        recover(pid)
        set_project(pid, status="queued", error="")
        holder: dict = {}

        async def go():
            s = settings_mod.get()
            pl = Pipeline(pid, self.backend_factory(s), ctl, s)
            holder["pl"] = pl
            return await pl.run()

        task = asyncio.get_running_loop().create_task(go())
        self.runs[pid] = (task, ctl, holder)  # type: ignore[assignment]
        return True

    def pause(self, pid: str) -> bool:
        r = self.runs.get(pid)
        if r and self.is_running(pid):
            r[1].pause = True
            return True
        return False

    def cancel(self, pid: str) -> bool:
        r = self.runs.get(pid)
        if r and self.is_running(pid):
            r[1].cancel = True
            pl = r[2].get("pl") if isinstance(r[2], dict) else None
            if pl:
                pl.cancel_inflight()
            return True
        return False

    async def wait(self, pid: str) -> None:
        r = self.runs.get(pid)
        if r:
            await asyncio.gather(r[0], return_exceptions=True)

    def resume_interrupted(self) -> list[str]:
        """Call at startup: anything that was queued/running when the app stopped continues automatically."""
        recover()
        started = []
        for r in db.q("SELECT id FROM projects WHERE status IN ('running','queued')"):
            if self.start(r["id"]):
                started.append(r["id"])
        return started


manager = Manager()
