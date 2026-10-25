"""Auto-run: one job that walks the plan screen's steps in order, from wherever the plan is now, and takes the default at every choice: the best (else
first) finished outcome is approved, plain Qwen is used for the scene pictures unless a way was already chosen, and cards built from thin facts are
accepted as they are. It uses the same functions as the buttons, so everything it makes can be looked at, unapproved and redone afterwards. It stops at
the first thing that needs a person (a sign-off blocker, a missing model) and says what, keeping everything finished so far. Gaps in a character's
description are not filled in (that needs a person); the models invent the missing details."""
import asyncio
import re

from story import db, llm, settings as settings_mod
from story2 import api as plans_api, director, editorial, export, imgplan, planner, storyboard, store as plan_store

from . import graphics, refs, scenes, store, thumbnail, video, voice
from .voice import MediaError

STAGES = [("blueprint", "Plan the story"), ("narration", "Write the narration"), ("characters", "Create characters and places"),
          ("storyboard", "Design the storyboard"), ("references", "Make and approve reference pictures"), ("prompts", "Write image prompts"), ("repeats", "Fix camera repeats"), ("approve", "Check, review and approve the plan"),
          ("export", "Export"), ("voice", "Make and approve the voice"), ("pictures", "Draw and approve the scene pictures"), ("graphics", "Build and approve the graphics"),
          ("video", "Make the draft video"), ("thumbnail", "Make the video thumbnail")]


class AutoStop(MediaError):
    """A step that needs a person. The message says what."""


def _full(plan_id: str) -> dict:
    plan = planner.get_plan(plan_id)
    return {**plan, "assets": storyboard.get_assets(plan_id), "scenes": storyboard.get_scenes(plan_id)}


def _beats_missing(plan: dict) -> list:
    return [b for b in (plan["blueprint"] or {}).get("beats", []) if b["id"] not in {s["beat"] for s in plan["segments"]}]


def _uncovered(plan: dict) -> list:
    covered = {s["segment_id"] for s in plan["scenes"]}
    return [s for s in plan["segments"] if s["id"] not in covered]


def _compiled(plan: dict) -> bool:
    return bool(plan["scenes"]) and all((s["data"].get("prompts") or {}).get("qwen") for s in plan["scenes"])


def uses_references(plan: dict) -> bool:
    """Reference pictures reach the picture model only when scenes are drawn from them (edit mode). Plain drawing, which auto-run uses unless a person chose
    otherwise, never sends them, so making them would cost minutes and change nothing."""
    return scenes.settings(plan)["mode"] != "generate"


def done(plan_id: str, key: str, st: dict | None = None) -> bool:
    """Is this stage already finished? `st` may hold the media states the screen has just computed (refs, scenes, graphics, video)."""
    st = st or {}
    plan = _full(plan_id)
    if key == "blueprint":
        return bool(plan["blueprint"])
    if key == "narration":
        return bool(plan["blueprint"]) and bool(plan["segments"]) and not _beats_missing(plan)
    if key == "characters":
        return bool(plan["assets"]) and not plans_api.style_info(plan)["registry_stale"]
    if key == "references":
        if not uses_references(plan):
            return True
        r = st.get("refs") or refs.state(plan_id)
        return bool(r["done"] or r["total"] == 0)
    if key == "storyboard":
        return bool(plan["scenes"]) and not _uncovered(plan) and not plans_api.style_info(plan)["storyboard_stale"] and director.current(plan)
    if key == "prompts":
        return _compiled(plan) and not any(i["kind"] in ("stale", "not_compiled") for i in imgplan.validate_prompts(plan_id)["issues"])
    if key == "repeats":
        rep = (plan["validation"] or {}).get("storyboard")
        return bool(rep) and not any(i.get("kind") == "repeat" for i in rep.get("issues", []))
    if key == "approve":
        return editorial.approval_state(plan)["state"] == "approved"
    if key == "export":
        ex = export.list_exports(plan_id)
        return bool(ex and ex[0]["content_hash"] == editorial.content_hash(plan))
    if key == "voice":
        v = st.get("voice") or voice.state(plan_id)
        return bool(v["total"] and v["have"] == v["total"] and v["approved"] == v["total"])
    if key == "pictures":
        s = st.get("scenes") or scenes.state(plan_id)
        return bool(s["done"] or not s["total"])
    if key == "graphics":
        g = st.get("graphics") or graphics.state(plan_id)
        return bool(g["done"] or not g["total"])
    if key == "video":
        v = st.get("video") or video.state(plan_id)
        return bool(v["done"])
    if key == "thumbnail":
        return bool(thumbnail.state(plan_id)["done"])
    return False


def state(plan_id: str, st: dict | None = None) -> dict:
    """The stages in order, which are finished, and the first one still to do."""
    rows = []
    try:
        for key, label in STAGES:
            rows.append({"key": key, "label": label, "done": done(plan_id, key, st)})
    except Exception as e:  # noqa: BLE001 - the screen still shows the button
        return {"stages": rows, "next": None, "remaining": 0, "error": str(e)[:200]}
    todo = [r for r in rows if not r["done"]]
    return {"stages": rows, "next": todo[0]["key"] if todo else None, "remaining": len(todo)}


# ── the stages ──────────────────────────────────────────────────────────────

WEAK_BELOW = 50


def _weak(cands: list[dict], best_id: str | None, approved: str | None = None) -> bool:
    """No finished current picture yet, or the best (or the approved) one has a hard problem or scores under 50."""
    pick = next((c for c in cands if c["id"] == (approved or best_id)), None)
    if not pick:
        return True
    sc = pick.get("score")
    return bool(sc and (sc["hard"] or sc["total"] < WEAK_BELOW))


def _approve_first(plan_id: str, kind: str) -> int:
    """Approve what is still open: the best finished outcome of each item, and where nothing scored well, its first finished one."""
    n = 0
    if kind == "references":
        n += refs.approve_best(plan_id, 0)["approved"]
        for r in refs.state(plan_id)["assets"]:
            if not r["approved"] and not r["skipped"]:
                first = next((c for c in r["candidates"] if c["status"] == "done" and c["current"]), None)
                if first:
                    refs.approve(first["id"])
                    n += 1
    elif kind == "scenes":
        n += scenes.approve_best(plan_id, 0)["approved"]
        for r in scenes.state(plan_id)["scenes"]:
            if not r["approved_current"]:
                first = next((c for c in r["candidates"] if c["status"] == "done" and c["current"]), None)
                if first:
                    scenes.approve(first["id"])
                    n += 1
    return n


def _approve_content(plan_id: str) -> None:
    """The plan's own sign-off needs every narration part and scene approved (the screen's "Approve all" buttons)."""
    plan = planner.get_plan(plan_id)
    for seg in plan["segments"]:
        if seg["status"] != "approved" and not seg["locked"]:
            planner.edit_segment(seg["id"], None, None, status="approved")
    for sc in storyboard.get_scenes(plan_id):
        if sc["status"] != "approved" and not sc["locked"] and not any(i.get("level") == "error" for i in sc.get("issues", [])):
            storyboard.edit_scene(sc["id"], {"status": "approved"})


async def _repair_scenes(plan_id: str, be, s: dict, sub, notes: list[str]) -> None:
    """A scene whose prompt or text carries an error (a year or number that is not in the facts, wording copied from the source) is redrawn with the error as
    the editor's request, twice at most, so one bad scene does not stop the whole run."""
    for attempt in range(3):
        reports = await asyncio.to_thread(editorial.run_checks, plan_id)
        bad: dict[str, list[str]] = {}
        for rep in (reports["storyboard"], reports["prompts"]):
            for i in (rep or {}).get("issues", []):
                if i.get("level") == "error" and str(i.get("where", "")).startswith("sc-"):
                    bad.setdefault(i["where"], []).append(i["text"])
        bad = {k: v for k, v in bad.items() if not storyboard.get_scene(k)["locked"]}
        if not bad:
            return
        for n, (sid, why) in enumerate(bad.items(), 1):
            sub(n, len(bad), f"fixing scene {n} of {len(bad)}")
            if attempt == 2:                                        # the model keeps writing a number of its own (a year it worked out): take it out
                gone = [m for t in why for m in re.findall(r"states (\S+?),", t)] + [t.split("copied_wording:", 1)[1].strip() for t in why if "copied_wording:" in t]
                await asyncio.to_thread(storyboard.scrub_numbers, sid, gone)
                continue
            await storyboard.regenerate_scene(sid, be, s, "Fix this problem and keep the same story beat: " + "; ".join(dict.fromkeys("some wording is copied from the source: describe it in completely new words" if "copied_wording" in t else t for t in why)) + ". Use only years, numbers and names that are in the story facts.")
        await asyncio.to_thread(imgplan.compile_plan, plan_id)
        notes.append(f"{len(bad)} scene(s) had an error in their wording and were redrawn")


async def run_stage(plan_id: str, key: str, be, s: dict, api_key: str, progress, notes: list[str]) -> None:
    sub = lambda d, t, label="": progress(None, None, label)          # noqa: E731 - stage progress shown as the label only
    if key == "blueprint":
        await planner.make_blueprint(plan_id, be, s)
    elif key == "narration":
        plan = planner.get_plan(plan_id)
        if not plan["blueprint"]:
            raise AutoStop("the story is not planned")
        await planner.make_narration(plan_id, be, s, None, sub, bool(plan["segments"]))
    elif key == "characters":
        if not planner.get_plan(plan_id)["segments"]:
            raise AutoStop("write the narration first")
        await storyboard.make_registry(plan_id, be, s)
        gaps = _full(plan_id)
        from story2 import describe
        n = sum(1 for a in gaps["assets"] if a["kind"] in ("person", "place", "prop") and describe.missing(a["kind"], a["data"].get("appearance")))
        if n:
            notes.append(f"{n} character, place or object description(s) have gaps: use Fill in the gaps later, the models invent the missing details until then")
    elif key == "references":
        if not refs.targets(plan_id) or not uses_references(planner.get_plan(plan_id)):
            return
        await refs.generate(plan_id, None, 1, True, None, sub, s, api_key, True)
        weak = [r["asset_id"] for r in refs.state(plan_id)["assets"] if not r["approved"] and not r["skipped"] and _weak(r["candidates"], r["best"])]
        if weak:                                                    # a picture with a hard problem or a poor score gets two more tries before the best of them is taken
            await refs.generate(plan_id, weak, 2, False, None, sub, s, api_key, True)
        _approve_first(plan_id, "references")
        left = [r["name"] for r in refs.state(plan_id)["assets"] if r["approved"] and _weak(r["candidates"], r["best"], approved=r["approved"])]
        if left:
            notes.append("reference picture(s) approved with problems after three tries, look at them: " + ", ".join(left))
        imgplan_ok = bool(storyboard.get_scenes(plan_id))
        if imgplan_ok:
            imgplan.compile_plan(plan_id)
    elif key == "storyboard":
        stale = plans_api.style_info(_full(plan_id))["storyboard_stale"]
        await storyboard.make_storyboard(plan_id, be, s, None, sub, bool(stale))
    elif key == "prompts":
        await asyncio.to_thread(imgplan.compile_plan, plan_id)
    elif key == "repeats":
        await asyncio.to_thread(editorial.run_checks, plan_id)
        if not done(plan_id, "repeats"):
            await storyboard.fix_repeats(plan_id, be, s, sub)
            await asyncio.to_thread(imgplan.compile_plan, plan_id)
    elif key == "approve":
        await _repair_scenes(plan_id, be, s, sub, notes)
        await asyncio.to_thread(_approve_content, plan_id)
        so = await asyncio.to_thread(editorial.signoff, plan_id)
        if not so["ok"]:
            raise AutoStop("the plan cannot be approved yet: " + " ".join(b["text"] for b in so["blockers"]))
        await asyncio.to_thread(editorial.approve, plan_id, "approved by the automatic run")
    elif key == "export":
        await asyncio.to_thread(export.save, plan_id)
    elif key == "voice":
        await voice.generate(plan_id, None, True, sub, s, api_key)
        plan = planner.get_plan(plan_id)
        vid = plan["narrator"].get("voice") or "hi_male"
        for seg in plan["segments"]:
            it = store.chosen_voice(plan_id, seg, vid)
            if it and not it["approved"]:
                store.approve(it["id"])
        await asyncio.to_thread(voice.apply_timing, plan_id)
        if voice.state(plan_id)["approved"] != len(plan["segments"]):
            raise AutoStop("some narration parts have no voice (see the Voice section)")
    elif key == "pictures":
        plan = planner.get_plan(plan_id)
        if not scenes.settings(plan)["chosen"]:
            scenes.set_settings(plan_id, {"model": "qwen-image-2.1", "mode": "generate", "chosen": True})
            notes.append("scene pictures use Qwen, drawn plain from each scene's prompt (run the three-scene trial yourself to try the reference-sheet mode)")
        await scenes.generate(plan_id, None, 1, True, None, None, sub, s, api_key, True)
        weak = [r["id"] for r in scenes.state(plan_id)["scenes"] if not r["approved_current"] and _weak(r["candidates"], r["best"])]
        if weak:                                                    # one more try for each picture with a hard problem or a poor score
            await scenes.generate(plan_id, weak, 1, False, None, None, sub, s, api_key, True)
        _approve_first(plan_id, "scenes")
        n_left = sum(1 for r in scenes.state(plan_id)["scenes"] if r["approved_current"] and _weak(r["candidates"], r["best"], approved=r["approved"]))
        if n_left:
            notes.append(f"{n_left} scene picture(s) approved with problems after two tries: filter the Scene pictures list and look at them")
        st = scenes.state(plan_id)
        if not st["done"]:
            raise AutoStop(f"{st['needs_picture'] + st['needs_choice']} scene(s) still have no approved picture (see Scene pictures)")
    elif key == "graphics":
        if graphics.state(plan_id)["total"]:
            await asyncio.to_thread(graphics.build, plan_id)
            graphics.approve_all(plan_id, include_fallbacks=True)
    elif key == "video":
        chk = await asyncio.to_thread(video.checklist, plan_id)
        if chk["blockers"]:
            raise AutoStop(f"{len(chk['blockers'])} thing(s) are missing for the video (see the Draft video section)")
        await asyncio.to_thread(video.build, plan_id, "draft", bool(video.available()["captions"]), False, sub)          # most people watch with the sound off: captions on whenever ffmpeg can burn them
    elif key == "thumbnail":
        await thumbnail.make(plan_id, be, s, api_key, sub)
    else:
        raise AutoStop(f"unknown step {key}")


async def run(plan_id: str, progress, s: dict | None = None, api_key: str = "", only: list[str] | None = None) -> dict:
    """Run every unfinished stage in order. `progress(done, total, label)`; a stage is skipped when it is already finished."""
    s = s or settings_mod.get()
    api_key = api_key or settings_mod.api_key()
    be = llm.ChatBackend(s, api_key)
    keys = [k for k, _l in STAGES if not only or k in only]
    ran, notes = [], []
    total = len(keys)
    for n, key in enumerate(keys):
        label = dict(STAGES)[key]
        if done(plan_id, key):
            continue
        cur = {"n": n}

        def p(d, t, text=""):
            progress(cur["n"], total, f"step {cur['n'] + 1} of {total}: {label}" + (f" ({text})" if text else ""))
        p(None, None)
        try:
            await run_stage(plan_id, key, be, s, api_key, p, notes)
        except asyncio.CancelledError:
            raise
        except AutoStop as e:
            plan_store.log(plan_id, "auto_stopped", {"stage": key, "why": str(e)})
            raise AutoStop(f"Auto-run stopped at “{label}”: {e}. Everything finished so far is kept.") from e
        except Exception as e:  # noqa: BLE001 - reported with the stage that failed
            plan_store.log(plan_id, "auto_failed", {"stage": key, "why": f"{type(e).__name__}: {e}"[:300]})
            raise MediaError(f"Auto-run stopped at “{label}”: {type(e).__name__}: {str(e)[:240]}. Everything finished so far is kept; press Auto-run again to continue.") from e
        ran.append(key)
    progress(total, total, "done")
    plan_store.log(plan_id, "auto_run", {"ran": ran, "notes": notes})
    return {"ran": ran, "notes": notes}
