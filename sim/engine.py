"""The chapter engine (docs/PLAN_simulation.md section 5). One chapter is a fixed list of stages; each stage writes its result to the chapter row, so a stopped server loses at most the stage in
flight and "Retry from this stage" continues from what is stored. Stages: gather (code + condition checks), plan, minds (optional), resolve (dice, code), delta, write, referee, archive."""
import copy
import re

from story import llm

from . import dice, memory, models as m, prompts as P, state as S, store

WORD_SLACK = (0.8, 1.23)                 # chapter length accepted around the owner's setting (350 -> 280 to 430)
MAX_RISKS = 3
STAGES = ("gather", "plan", "minds", "resolve", "delta", "write", "referee", "archive")


class Stopped(Exception):
    """The owner pressed Stop; the chapter stays resumable."""


def fence(text: str) -> str:
    return f"<owner>{text}</owner>"


def words_range(settings: dict) -> tuple[int, int, int]:
    w = int(settings["chapter_words"])
    return w, int(w * WORD_SLACK[0]), int(w * WORD_SLACK[1])


def _overlap(a: str, b: str) -> bool:
    wa = {w for w in re.findall(r"[a-z]+", a.lower()) if len(w) > 3}
    return bool(wa & {w for w in re.findall(r"[a-z]+", b.lower()) if len(w) > 3})


async def _json(backend, s, system, user, model, validate=None):
    caller = llm.JsonCaller(backend, s)
    res = await caller.call(system, user, model, (lambda v: validate(v, caller)) if validate else None)
    return res.value


def reconcile(st: dict, trackers: list[dict], entities: list[dict]) -> dict:
    """Bring a state in line with the setup the owner may have edited since: new trackers and people come in with their starting values, removed ones go."""
    st = copy.deepcopy(st)
    ids = {t["id"] for t in trackers}
    for t in trackers:
        st["trackers"].setdefault(t["id"], copy.deepcopy(t.get("start")))
    for k in [k for k in st["trackers"] if k not in ids]:
        del st["trackers"][k]
    for e in entities:
        if e["kind"] == "character":
            st["entities"].setdefault(e["name"], {"alive": bool(e.get("alive", True)), "status": str(e.get("status") or "")})
    names = {e["name"] for e in entities if e["kind"] == "character"}
    places = {e["name"] for e in entities if e["kind"] == "place"}
    for n in [n for n in st["entities"] if n not in names]:                 # a retired person leaves the later chapters
        del st["entities"][n]
    for t in trackers:
        if t["kind"] == "location":
            v = st["trackers"][t["id"]]
            v["at"] = {w: p for w, p in v.get("at", {}).items() if w in names and p in places}
            v["locked"] = [p for p in v.get("locked", []) if p in places]
    return st


def action_text(action: dict, parent: dict | None) -> str:
    kind = action.get("kind", "start")
    if kind == "option" and parent:
        o = next((o for o in parent["options"] if o["id"] == action.get("option_id")), None)
        if o:
            return f"{o['who']}: {o['label']}" if o.get("who") else o["label"]
    if kind == "text":
        return f"{action.get('who') or 'The focus character'}: {fence(action.get('text', ''))}"
    return "(the story begins)" if kind == "start" else "(no action given: the story moves on by itself)"


# ── instructions that are due ─────────────────────────────────────────────────

def _tracker_met(cond: dict, st: dict, trackers: list[dict]) -> bool:
    ref = str(cond.get("tracker", ""))
    t = next((x for x in trackers if x["id"] == ref or S.norm(x["name"]) == S.norm(ref)), None)
    if not t:
        return False
    v = st["trackers"].get(t["id"])
    op, val = cond.get("op", "full"), cond.get("value")
    if t["kind"] == "clock":
        return int(v) >= int(t["max"]) if op == "full" else int(v) >= int(val or 0)
    if t["kind"] == "meter":
        return (float(v) < float(val)) if op == "below" else (float(v) > float(val))
    if t["kind"] == "flag":
        return bool(v) == (op != "off")
    return False


async def due_directives(pid: str, path: list[dict], st: dict, idx: int, backend, s) -> list[dict]:
    trackers = store.trackers(pid)
    summary = path[-1]["summary"] if path else ""
    out = []
    for d in memory.pending_directives(pid, path):
        t, mode = d["timing"], d["timing"].get("mode")
        due, must = False, True
        if mode == "next":
            due = True
        elif mode == "in":
            due = idx >= int(t.get("from", 0)) + int(t.get("chapters", 1))
        elif mode == "when" and t.get("tracker"):
            due = _tracker_met(t, st, trackers)
        elif mode in ("when", "story_time"):
            cond = t.get("condition") or f"the story time has reached: {t.get('at')}"
            if path:
                r = await _json(backend, s, P.CONDITION, f"CONDITION: {fence(cond)}\n\nSTATE:\n{S.describe(st, trackers)}\n\nLAST CHAPTER SUMMARY: {summary}\n\nIs it met now?", m.CondOut)
                due, must = r.met, False
        if due:
            out.append({"id": d["id"], "label": f"D{len(out) + 1}", "kind": d["kind"], "text": d["text"], "must": must})
    return out


# ── one chapter ───────────────────────────────────────────────────────────────

async def run_chapter(pid: str, backend, s: dict, progress=None, *, parent_id: str | None = None, action: dict | None = None, instruction: str = "", salt: str = "",
                      resume_id: str = "", label: str = "", cancel=lambda: False) -> dict:
    progress = progress or (lambda *a: None)
    proj = store.project(pid)
    cfg = proj["settings"]
    if resume_id:
        ch = store.chapter(resume_id)
        parent_id = ch["parent_id"]
        action = action or ch["chosen"] or {"kind": "start"}
        instruction = instruction or ch["flags"].get("instruction", "")
        salt = salt or ch["flags"].get("salt", "")
    else:
        parent_id = proj["head_id"] if parent_id is None else parent_id
        ch = store.add_chapter(pid, parent_id, label)
        action = action or ({"kind": "start"} if not parent_id else {"kind": "auto"})
    cid = ch["id"]
    parent = store.chapter(parent_id) if parent_id else None
    path = store.path(pid, parent_id) if parent_id else []
    trackers, ents = store.trackers(pid), store.entities(pid)
    chars = [e for e in ents if e["kind"] == "character"]
    places = [e["name"] for e in ents if e["kind"] == "place"]
    world = store.world(pid)
    flags = dict(ch["flags"])
    flags.update(instruction=instruction, salt=salt, rules_version=cfg["rules_version"], kind="start" if not parent_id else "normal")
    done = set(flags.get("done", []))
    st0 = reconcile(parent["state_after"], trackers, ents) if parent else S.initial_state(trackers, ents, world)
    store.update_chapter(cid, chosen=action, state_before=st0, flags=flags, status="writing", parent_id=parent_id)
    total = len(STAGES) - (0 if cfg["deep"] else 1)
    state_hold = {"n": 0}

    def begin(name, text):
        if cancel():
            raise Stopped()
        state_hold["n"] += 1
        progress(state_hold["n"] - 1, total, text)
        store.set_run(pid, replace=True, chapter_id=cid, stage=name, error="", stopped=False)

    def finish(name, **fields):
        done.add(name)
        flags["done"] = sorted(done)
        store.update_chapter(cid, flags=flags, **fields)

    try:
        cur = store.chapter(cid)
        # gather ----------------------------------------------------------------
        if "gather" in done:
            due = flags.get("due", [])
        else:
            begin("gather", "reading the situation")
            due = await due_directives(pid, path, st0, ch["idx"], backend, s)
            flags["due"] = due
            flags["pressure"] = S.pressure(st0, trackers)
            finish("gather")
        act = action_text(action, parent)
        pk0 = memory.build(pid, path, st0, None, "", s)
        # plan ------------------------------------------------------------------
        if "plan" in done:
            plan = cur["plan"]
        else:
            begin("plan", "planning the chapter")
            last_beats = [c["plan"].get("beat") for c in path[-2:]]
            by_name = {e["name"].lower(): e["name"] for e in chars}

            def v(p: m.ChapterPlan, caller):
                p.focus = [by_name[n.lower()] for n in p.focus if n.lower() in by_name and st0["entities"].get(by_name[n.lower()], {}).get("alive", True)][:3]
                if not p.focus:
                    raise ValueError("focus must name 1 to 3 living characters from the cast")
                p.beat = p.beat if p.beat in m.BEATS else "escalate"
                labels = {d["label"]: d["id"] for d in due}
                p.addresses = [labels.get(a, a) for a in p.addresses if labels.get(a, a) in {d["id"] for d in due}]
                missing = [d["label"] for d in due if d["must"] and d["id"] not in p.addresses]
                if missing and not caller.last_attempt:
                    raise ValueError(f"addresses must include {', '.join(missing)}: those instructions are due now")
                if p.beat in last_beats and last_beats.count(p.beat) == len(last_beats) and not caller.last_attempt:
                    raise ValueError(f"the last chapters were already '{p.beat}': choose a different beat")
                if action.get("kind") == "text" and not _overlap(action.get("text", ""), p.intent + " " + p.scene) and not caller.last_attempt:
                    raise ValueError("the intent must follow the owner's action")
                p.risks = [r for r in p.risks if r.act][:MAX_RISKS]
                for r in p.risks:
                    r.difficulty = r.difficulty if r.difficulty in m.DIFFICULTY else "normal"

            user = (f"{memory.render(pk0, s)}\n\n## PLAYER'S ACTION\n{act}\n\n## DUE INSTRUCTIONS\n"
                    + ("\n".join(f"{d['label']} (id {d['id']}) [{d['kind']}] {'MUST' if d['must'] else 'MAY WAIT'}: {fence(d['text'])}" for d in due) or "(none)")
                    + "\n\n## UNDER PRESSURE\n" + ("\n".join(p["text"] for p in flags.get("pressure", [])) or "(nothing at its limit)")
                    + "\n\n## BEATS OF THE LAST CHAPTERS\n" + (", ".join(b for b in last_beats if b) or "(none yet)")
                    + (f"\n\n## OWNER'S NOTE FOR THIS CHAPTER\n{fence(instruction)}" if instruction else "") + "\n\nPlan the chapter now.")
            p = await _json(backend, s, P.PLAN, user, m.ChapterPlan, v)
            plan = p.model_dump()
            plan["due_ids"] = [d["id"] for d in due]
            flags["trimmed"] = pk0.trimmed
            finish("plan", plan=plan, focus=plan["focus"])
        # minds (optional) ------------------------------------------------------
        if cfg["deep"]:
            if "minds" not in done:
                begin("minds", "what the others want")
                others = [e for e in chars if e["name"] not in plan["focus"] and st0["entities"].get(e["name"], {}).get("alive", True)][:5]
                if others:
                    pkm = memory.build(pid, path, st0, [e["name"] for e in others], plan["scene"], s)
                    r = await _json(backend, s, P.MINDS, f"{memory.render(pkm, s)}\n\n## SCENE\n{plan['scene']}\n\nOthers: {', '.join(e['name'] for e in others)}", m.MindsOut)
                    plan["minds"] = {k: v for k, v in r.wants.items() if k.lower() in {e['name'].lower() for e in others}}
                finish("minds", plan=plan)
        else:
            done.add("minds")
        # resolve (dice, code) --------------------------------------------------
        if "resolve" in done:
            rolls = store.chapter(cid)["rolls"]
        else:
            begin("resolve", "rolling the dice")
            if cfg["dice"]:
                rolls = [dice.roll(r, st0, trackers, cfg["seed"], ch["idx"], i + 1, cfg["difficulty"], salt) for i, r in enumerate(plan["risks"])]
            else:
                rolls = [dice.free(r, i + 1) for i, r in enumerate(plan["risks"])]
            finish("resolve", rolls=rolls)
        # delta -----------------------------------------------------------------
        if "delta" in done:
            st1 = store.chapter(cid)["state_after"]
            delta = store.chapter(cid)["delta"]
        else:
            begin("delta", "working out what changes")
            pkd = memory.build(pid, path, st0, plan["focus"], plan["scene"], s)
            fired_text = [d for d in due if d["id"] in plan["addresses"]]
            user = (f"{memory.render(pkd, s)}\n\n## CHAPTER PLAN\nScene: {plan['scene']}\nIntent: {plan['intent']}\nPressure: {plan['pressure']}\nTime passes: {plan['time_passes']}\n"
                    + ("\n## DICE RESULTS (fixed)\n" + "\n".join(f"- {r['who']}: {r['act']} -> {r['tier'].upper()}: {r['text']}" for r in rolls) if rolls else "\n## DICE RESULTS\n(no risky acts this chapter)")
                    + ("\n\n## INSTRUCTIONS HAPPENING NOW\n" + "\n".join(f"- [{d['kind']}] {fence(d['text'])}" for d in fired_text) if fired_text else "")
                    + ("\n\n## WHAT THE OTHERS DO\n" + "\n".join(f"- {k}: {v}" for k, v in plan.get("minds", {}).items()) if plan.get("minds") else "")
                    + "\n\nList the operations now.")
            r = await _json(backend, s, P.DELTA, user, m.DeltaOut)
            adopted = _adopt_places(pid, r.ops, ents, world)
            if adopted:
                ents = store.entities(pid)
                places = [e["name"] for e in ents if e["kind"] == "place"]
            allow_death = (not cfg["dice"]) or any(x["tier"] in ("fail", "disaster") for x in rolls) or bool(fired_text) or any(p["kind"] == "clock_full" for p in flags.get("pressure", []))
            ctx = S.Ctx(trackers, [e["name"] for e in ents], places, world.get("exists", ""), allow_death, {e["name"]: e.get("description", "") + " " + e.get("look", "") for e in ents if e["kind"] == "place"})
            st1, applied, dropped = S.apply_ops(st0, r.ops, ctx)
            delta = {"ops": [o.model_dump() for o in r.ops], "applied": applied, "dropped": dropped, "new_places": adopted}
            flags["dropped"] = len([d for d in dropped if not d.get("partial")])
            finish("delta", state_after=st1, delta=delta)
        # write -----------------------------------------------------------------
        if "write" in done:
            cur = store.chapter(cid)
        else:
            begin("write", "writing the chapter")
            await _write(pid, backend, s, cid, path, st0, st1, plan, rolls, delta, instruction, [], cfg, flags)
            done.add("write")
            flags["done"] = sorted(done)
            store.update_chapter(cid, flags=flags)
        # referee ---------------------------------------------------------------
        if "referee" not in done:
            begin("referee", "checking the rules")
            await _referee(pid, backend, s, cid, path, st0, st1, plan, rolls, delta, instruction, cfg, flags)
            finish("referee")
        # archive ---------------------------------------------------------------
        if "archive" not in done:
            begin("archive", "remembering and offering options")
            await _archive(pid, backend, s, cid, path, st1, plan, flags)
            finish("archive")
        fired = [d for d in plan["addresses"] if d in {x["id"] for x in due}]
        store.update_chapter(cid, status="done", fired=fired, flags=flags)
        store.save_project(pid, head_id=cid, status="running")
        await _maybe_rollup(pid, backend, s)
        progress(total, total, "chapter done")
        store.set_run(pid, replace=True, chapter_id=cid, stage="done", error="")
        return store.chapter(cid)
    except Stopped:
        store.update_chapter(cid, status="failed", flags={**flags, "stopped": True})
        store.set_run(pid, replace=True, chapter_id=cid, stage="stopped", error="", stopped=True)
        raise
    except Exception as e:  # noqa: BLE001 - the stage and the reason are kept so the owner can retry from this stage
        store.update_chapter(cid, status="failed", flags={**flags, "error": f"{type(e).__name__}: {e}"[:400]})
        store.set_run(pid, replace=True, chapter_id=cid, stage=store.run_info(pid).get("stage", ""), error=f"{type(e).__name__}: {e}"[:400])
        raise


def _adopt_places(pid: str, ops: list, ents: list[dict], world: dict) -> list[str]:
    """An area the world card names ("the Deli") but the cast list left out becomes a place when the model sends someone or something there: at most three a chapter, only names found in the card."""
    exists = " ".join(sorted(S._toks(world.get("exists", ""))))
    known = {S.norm(e["name"]): e["name"] for e in ents}
    out: list[str] = []
    for o in ops:
        names = []
        if o.op in ("move", "item_move"):
            names.append(o.to)
        if o.op in ("lock", "unlock"):
            names.append(o.target)
        if o.source:
            names.append(o.source)
        for n in names:
            n = (n or "").strip()
            toks = S._toks(n)
            if not n or len(out) >= 3 or S.pick(known, n) or any(S.norm(n) == S.norm(x) for x in out):
                continue
            if toks and toks <= set(exists.split()):
                out.append(n)
    for n in out:
        store.save_entity(pid, {"kind": "place", "name": n, "description": "An area named in the world card.", "adopted": True})
    return out


def _tail(chapter_text: str) -> str:
    return "\n".join([p for p in chapter_text.split("\n") if p.strip()][-1:])


async def _write(pid, backend, s, cid, path, st0, st1, plan, rolls, delta, instruction, violations, cfg, flags) -> None:
    w, lo, hi = words_range(cfg)
    pk = memory.build(pid, path, st1, plan["focus"], plan["scene"], s)
    system = P.WRITE.replace("{words}", str(w)).replace("{lo}", str(lo)).replace("{hi}", str(hi))
    user = (f"{memory.render(pk, s)}\n\n## CHAPTER PLAN\nWhere: {plan['where']}\nFollowing: {', '.join(plan['focus'])}\nScene: {plan['scene']}\nIntent: {plan['intent']}\nTime passes: {plan['time_passes']}\n"
            + ("\n## HOW EACH RISKY ACT ENDS (fixed)\n" + "\n".join(f"- {r['who']}: {r['act']} -> {r['text']}" for r in rolls) if rolls else "")
            + ("\n\n## CHANGES TO SHOW\n" + "\n".join(f"- {a['text']}" + (f" ({a['why']})" if a.get("why") else "") for a in delta["applied"]) if delta["applied"] else "")
            + ("\n\n## WHAT THE OTHERS DO\n" + "\n".join(f"- {k}: {v}" for k, v in plan.get("minds", {}).items()) if plan.get("minds") else "")
            + ("\n\n## INSTRUCTIONS HAPPENING NOW\n" + "\n".join(f"- {fence(t)}" for t in _fired_texts(pid, plan)) if plan.get("addresses") else "")
            + (f"\n\n## OWNER'S NOTE FOR THIS CHAPTER\n{fence(instruction)}" if instruction else "")
            + ("\n\n## FIX THESE PROBLEMS FROM THE LAST DRAFT\n" + "\n".join(f"- {v['rule']}: \"{v['quote']}\" -> {v['fix']}" for v in violations) if violations else "")
            + "\n\nWrite the chapter now.")

    def v(o: m.WriteOut, caller):
        n = len(o.prose.split())
        flags["words"] = n
        if (n < lo or n > hi) and not caller.last_attempt:
            raise ValueError(f"the chapter has {n} words; it must have between {lo} and {hi}")

    o = await _json(backend, s, system, user, m.WriteOut, v)
    st = copy.deepcopy(st1)
    st["time"] = o.story_time or st1.get("time", "")
    store.update_chapter(cid, title=o.title.strip()[:120], prose=o.prose.strip(), story_time=o.story_time.strip()[:60], state_after=st)


def _fired_texts(pid: str, plan: dict) -> list[str]:
    ds = {d["id"]: d["text"] for d in store.directives(pid)}
    return [ds[i] for i in plan.get("addresses", []) if i in ds]


async def _referee(pid, backend, s, cid, path, st0, st1, plan, rolls, delta, instruction, cfg, flags) -> None:
    rules, labels = memory.rules_text(pid)
    hardness = {g["id"]: g["grp"] for g in store.guidelines(pid, enabled_only=True)}
    for attempt in (1, 2):
        ch = store.chapter(cid)
        st = ch["state_after"]
        user = (f"## RULES\n{rules}\n\n## WORLD\n{memory.world_text(store.world(pid))}\n\n## STATE AFTER THE CHAPTER\n{S.describe(st, store.trackers(pid))}\n\n"
                + ("## DICE RESULTS (fixed)\n" + "\n".join(f"- {r['who']}: {r['act']} -> {r['tier']}" for r in rolls) + "\n\n" if rolls else "")
                + f"## CHAPTER\n{ch['prose']}\n\nCheck it now.")
        r = await _json(backend, s, P.REFEREE, user, m.RefereeOut)
        hard = []
        for x in r.violations:
            gid = labels.get(x.rule.upper().strip())
            if x.rule.lower().startswith("continuity") or (gid and hardness.get(gid) in ("hard", "world")):
                hard.append(x.model_dump())
        if not hard:
            flags.pop("rule_break", None)
            flags["referee"] = "ok" if attempt == 1 else "fixed"
            flags["soft"] = [x.model_dump() for x in r.violations if x.model_dump() not in hard]
            store.update_chapter(cid, flags=flags)
            return
        if attempt == 2:
            flags["rule_break"] = hard
            flags["referee"] = "broken"
            store.update_chapter(cid, flags=flags)
            return
        flags["first_violations"] = hard                                    # what made the first draft be written again (kept for the owner and for tuning)
        await _write(pid, backend, s, cid, path, st0, st1, plan, rolls, delta, instruction, hard, cfg, flags)


async def _archive(pid, backend, s, cid, path, st1, plan, flags) -> None:
    ch = store.chapter(cid)
    pk = memory.build(pid, path, ch["state_after"], plan["focus"], plan["scene"], s)
    alive = [n for n, e in ch["state_after"]["entities"].items() if e["alive"]]
    foc = plan["focus"]

    def v(o: m.ArchiveOut, caller):
        opts = []
        for x in o.options:
            who = next((a for a in alive if a.lower() == x.who.lower()), "")
            if not who:
                continue
            if any(_sim(x.label, y["label"]) > 0.6 for y in opts):
                continue
            x.risk = x.risk if x.risk in m.RISKS else "medium"
            opts.append({"who": who, "label": x.label.strip(), "hint": x.hint.strip(), "risk": x.risk})
        if sum(1 for y in opts if y["risk"] == "high") > 1:
            seen = False
            for y in opts:
                if y["risk"] == "high":
                    if seen:
                        y["risk"] = "medium"
                    seen = True
        if len(opts) < 3 and not caller.last_attempt:
            raise ValueError("write 3 or 4 different options, each for a living character")
        missing = [f for f in foc if f in alive and not any(y["who"] == f for y in opts)]
        if missing and len(opts) < 4 and not caller.last_attempt:
            raise ValueError(f"add an option for {', '.join(missing)}")
        o.options = opts[:4]

    user = (f"{memory.render(pk, s)}\n\n## THE CHAPTER\n{ch['title']} ({ch['story_time']})\n{ch['prose']}\n\nAlive: {', '.join(alive)}\nFollowed: {', '.join(foc)}\n\nWrite the archive and the options now.")
    o = await _json(backend, s, P.ARCHIVE, user, m.ArchiveOut, v)
    options = [{"id": f"o{i}", **x} if isinstance(x, dict) else {"id": f"o{i}", **x.model_dump()} for i, x in enumerate(o.options, 1)]
    if not options:                                                           # the last attempt may have none: a story must never dead-end
        options = [{"id": "o1", "who": (foc or alive)[0], "label": "Carry on and see what happens next", "hint": "", "risk": "medium"}]
    store.drop_chapter_memory(cid)
    for f in o.facts[:6]:
        store.add_fact(pid, cid, f.text, f.names, f.tags)
    for t in o.threads_opened[:3]:
        store.add_thread(pid, cid, t)
    labels = pk.thread_labels
    for t in o.threads_closed:
        if t in labels:
            store.close_thread(labels[t], cid)
    store.update_chapter(cid, summary=o.summary.strip(), options=options)


def _sim(a: str, b: str) -> float:
    wa, wb = ({w for w in re.findall(r"[a-z]+", t.lower()) if len(w) > 3} for t in (a, b))
    return len(wa & wb) / max(1, min(len(wa), len(wb)))


async def _maybe_rollup(pid: str, backend, s) -> None:
    path = store.path(pid)
    due = memory.due_for_rollup(path)
    if not due:
        return
    old, take = due
    user = f"EARLIER STORY SO FAR:\n{old or '(none)'}\n\nCHAPTERS TO MERGE:\n" + "\n".join(f"Ch {c['idx']}: {c['summary']}" for c in take) + "\n\nMerge them now."
    r = await _json(backend, s, P.ROLLUP, user, m.RollupOut)
    last = take[-1]
    store.update_chapter(last["id"], flags={**last["flags"], "rollup": r.text.strip()})


# ── choosing, auto-run, hand edits ────────────────────────────────────────────

async def pick_option(pid: str, backend, s, chapter: dict) -> dict:
    """Let it run: the model picks one of the offered options."""
    opts = chapter["options"]
    if not opts:
        return {"kind": "auto"}
    user = ("OPTIONS:\n" + "\n".join(f"{o['id']}: {o['who']} - {o['label']} (risk {o['risk']}) {o['hint']}" for o in opts)
            + f"\n\nLAST CHAPTER SUMMARY: {chapter['summary']}\nPREVIOUS CHOICE: {chapter['chosen'].get('label', '')}\n\nPick now.")
    r = await _json(backend, s, P.PICK, user, m.PickOut)
    oid = r.option if any(o["id"] == r.option for o in opts) else opts[0]["id"]
    return {"kind": "option", "option_id": oid}


def stop_reason(ch: dict, before_alive: set[str]) -> str:
    if ch["flags"].get("rule_break"):
        return "a rule was broken in the last chapter; look at it"
    died = before_alive - {n for n, e in ch["state_after"]["entities"].items() if e["alive"]}
    if died:
        return f"{', '.join(sorted(died))} died"
    full = [p for p in ch["flags"].get("pressure", []) if p["kind"] == "clock_full"]
    if full:
        return full[0]["text"]
    ds = {d["id"]: d for d in store.directives(ch["project_id"])}
    if any(ds.get(i, {}).get("kind") == "steer" for i in ch["fired"]):
        return "a steering instruction was used; check the direction"
    return ""


async def auto_run(pid: str, n: int, backend, s, progress=None, cancel=lambda: False, after=None) -> dict:
    """Let it run for up to n chapters. Stops early on a rule break, a death, a full clock, a used steering instruction, a failed stage or Stop."""
    n = max(1, min(10, n))
    made, why = 0, ""
    for i in range(n):
        if cancel():
            why = "stopped"
            break
        head = store.path(pid)[-1] if store.path(pid) else None
        if not head:
            raise store.SimError("start the story first")
        alive = {k for k, e in head["state_after"]["entities"].items() if e["alive"]}
        action = await pick_option(pid, backend, s, head)
        try:
            ch = await run_chapter(pid, backend, s, (lambda d, t, l, i=i: progress and progress(i, n, f"chapter {i + 1} of {n}: {l}")), parent_id=head["id"], action=action, cancel=cancel)
        except Stopped:
            why = "stopped"
            break
        made += 1
        if after:
            await after(ch)
        why = stop_reason(ch, alive)
        if why:
            break
    return {"made": made, "stopped_because": why}


async def reread(pid: str, cid: str, backend, s) -> dict:
    """After a hand edit: the operations that would bring the state after the chapter in line with the edited prose (nothing is applied until the owner agrees)."""
    ch = store.chapter(cid)
    trackers = store.trackers(pid)
    user = f"STATE BEFORE:\n{S.describe(ch['state_before'], trackers)}\n\nSTATE AFTER (as recorded):\n{S.describe(ch['state_after'], trackers)}\n\nEDITED CHAPTER:\n{fence(ch['prose'])}\n\nList the corrections now."
    r = await _json(backend, s, P.REREAD, user, m.RereadOut)
    ents = store.entities(pid)
    ctx = S.Ctx(trackers, [e["name"] for e in ents], [e["name"] for e in ents if e["kind"] == "place"], store.world(pid).get("exists", ""), True,
                {e["name"]: e.get("description", "") for e in ents if e["kind"] == "place"})
    _, applied, dropped = S.apply_ops(ch["state_after"], r.ops, ctx)
    return {"ops": [o.model_dump() for o in r.ops], "preview": applied, "dropped": dropped, "note": r.note}


def apply_reread(pid: str, cid: str, ops: list[dict]) -> dict:
    ch = store.chapter(cid)
    ents = store.entities(pid)
    ctx = S.Ctx(store.trackers(pid), [e["name"] for e in ents], [e["name"] for e in ents if e["kind"] == "place"], store.world(pid).get("exists", ""), True,
                {e["name"]: e.get("description", "") for e in ents if e["kind"] == "place"})
    st, applied, dropped = S.apply_ops(ch["state_after"], [m.Op(**o) for o in ops], ctx)
    delta = {**ch["delta"], "applied": ch["delta"].get("applied", []) + applied, "dropped": ch["delta"].get("dropped", []) + dropped}
    mark_stale(pid, cid)
    return store.update_chapter(cid, state_after=st, delta=delta)


def mark_stale(pid: str, cid: str) -> int:
    """Chapters after an edited one were written under the old text: they are marked, not changed."""
    n, todo = 0, [cid]
    while todo:
        for c in store.children(pid, todo.pop()):
            store.update_chapter(c["id"], flags={**c["flags"], "stale": True})
            todo.append(c["id"])
            n += 1
    return n
