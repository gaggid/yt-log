"""Every halt has a way out. A check that stops the editor (an error in the narration, the storyboard or the image prompts) is shown with what it means, what the
app can do about it, and a button that does it; when nothing can be done by the app, the exact thing a person must do and where. After a fix the checks run again,
and the outcome is told in plain words (what changed, what is left and why). This module knows the catalogue; `story2/api.py` runs it (instant fixes at once, model
fixes as the usual one-at-a-time job)."""
import re

from story import db

from . import imgplan, planner, storyboard, store

# fix id -> what it is. kind: "instant" (no model, done before the answer) or "job" (asks the writing model, runs as the usual background job).
FIXES = {
    "recompile": {"kind": "instant", "label": "Write the image prompts again", "does": "Rebuilds every image prompt from the scenes and characters as they are now, then checks again. Scene wording is not touched."},
    "relax": {"kind": "instant", "label": "Treat these details as flexible", "does": "Moves the listed character details from “always the same” to “may change”, so a shot that cannot show them stops being refused. The pictures keep the rest."},
    "retime": {"kind": "instant", "label": "Re-time the scenes", "does": "Stretches the scenes so they add up to the narration's length, then checks again."},
    "drop_orphans": {"kind": "instant", "label": "Remove scenes with no narration", "does": "Deletes scenes whose narration part no longer exists (nothing else), then checks again."},
    "recheck": {"kind": "instant", "label": "Check again", "does": "Runs every check again on the plan as it is now; a report left over from before your last change disappears."},
    "narration_parts": {"kind": "job", "label": "Write these narration parts again", "does": "Asks the writing model to rewrite only the narration parts listed (locked or approved parts are kept). Scenes of a rewritten part are marked for review."},
    "redo_scenes": {"kind": "job", "label": "Redesign these scenes", "does": "Asks the writing model to design each listed scene again, told what was wrong with it. Locked scenes are kept."},
    "storyboard_parts": {"kind": "job", "label": "Design the storyboard for these parts", "does": "Designs scenes again for the narration parts that have gaps or overlaps."},
}

# (part, kind) -> title, why, fix ids in order (the first is the main button), what a person does when the fix cannot finish it, where to look
CATALOG: dict[tuple[str, str], dict] = {
    ("Image prompts", "continuity"): {"title": "A character detail the prompt does not carry", "fixes": ["recompile", "relax"],
        "why": "A detail marked “always the same” is missing from a scene's prompt, usually because the shot cannot show it (shoes in a waist-up frame).",
        "manual": "Open the scene and change its camera, or edit the character so the detail is not “always the same”.", "jump": "sec-assets"},
    ("Image prompts", "missing"): {"title": "Something in the scene is not in its prompt", "fixes": ["recompile"],
        "why": "The scene's subject, action, place, light or camera is not in the compiled prompt (the prompt is older than the scene).",
        "manual": "Open the scene and fill the empty field (subject, action or location), then write the prompts again.", "jump": "sec-storyboard"},
    ("Image prompts", "fact"): {"title": "A fixed fact is missing from a prompt", "fixes": ["recompile"],
        "why": "A fact the scene must show is not in its prompt.", "manual": "Open the scene and check its fixed facts.", "jump": "sec-storyboard"},
    ("Image prompts", "style"): {"title": "The visual style is not in a prompt", "fixes": ["recompile"],
        "why": "The plan's style changed after these prompts were written.", "manual": "Choose the style again in the Visual style card.", "jump": "sec-style"},
    ("Image prompts", "exclusion"): {"title": "A “must not appear” rule is not in a prompt", "fixes": ["recompile"],
        "why": "A scene excludes something and its prompt does not say so.", "manual": "Open the scene and check its exclusions.", "jump": "sec-storyboard"},
    ("Image prompts", "text"): {"title": "On-screen text that cannot be drawn", "fixes": ["redo_scenes"],
        "why": "A scene asks for text that is not English or is too long for a picture model to draw correctly.",
        "manual": "Open the scene and shorten the text to 8 English words, or remove it.", "jump": "sec-storyboard"},
    ("Image prompts", "number"): {"title": "A number in a prompt that the story's facts do not have", "fixes": ["redo_scenes"],
        "why": "The prompt states a figure that is not in the story's facts.", "manual": "Open the scene and remove the number or add the fact.", "jump": "sec-storyboard"},
    ("Image prompts", "source_leak"): {"title": "Source wording in a prompt", "fixes": ["redo_scenes"],
        "why": "A prompt carries wording from the source (a name, a title or a quotation), which must never reach a picture model.",
        "manual": "Open the scene and reword the part the message quotes.", "jump": "sec-storyboard"},
    ("Image prompts", "references"): {"title": "More reference pictures than the model accepts", "fixes": ["recompile"],
        "why": "A scene lists more than three reference pictures.", "manual": "Skip a reference for a minor object in the Reference pictures card.", "jump": "sec-refs"},
    ("Image prompts", "negative"): {"title": "Negative prompt does not fit the model", "fixes": ["recompile"],
        "why": "A prompt was compiled for a model with different negative-prompt rules.", "manual": "", "jump": "sec-storyboard"},
    ("Image prompts", "asset"): {"title": "A chart or document would be drawn by a picture model", "fixes": ["recompile"],
        "why": "Charts and documents are built by the app from verified facts, never drawn by a picture model.", "manual": "", "jump": "sec-storyboard"},
    ("Storyboard", "orphan"): {"title": "Scenes whose narration part is gone", "fixes": ["drop_orphans"],
        "why": "These scenes belong to a narration part that was rewritten or removed.", "manual": "Delete the scene by hand.", "jump": "sec-storyboard"},
    ("Storyboard", "no_narration"): {"title": "Scenes with no narration left", "fixes": ["drop_orphans", "redo_scenes"],
        "why": "The narration for the scene's sentences was removed.", "manual": "Remove the scene, or restore its sentences.", "jump": "sec-storyboard"},
    ("Storyboard", "coverage"): {"title": "Narration sentences without a scene, or in two scenes", "fixes": ["storyboard_parts"],
        "why": "Every narration sentence must be in exactly one scene.", "manual": "Use “Design the storyboard” for the part.", "jump": "sec-storyboard"},
    ("Storyboard", "timing"): {"title": "Scenes do not add up to the narration's length", "fixes": ["retime"],
        "why": "Scene lengths and the narration's length differ by more than half a second.", "manual": "", "jump": "sec-storyboard"},
    ("Storyboard", "purpose"): {"title": "Scenes with no purpose", "fixes": ["redo_scenes"],
        "why": "A scene must say why it exists in the story.", "manual": "Open the scene and write its purpose.", "jump": "sec-storyboard"},
    ("Storyboard", "feasibility"): {"title": "A scene needs a chart or document that is not described", "fixes": ["redo_scenes"],
        "why": "A chart, document or screen needs a description of what it shows.", "manual": "Open the scene and describe what the chart shows.", "jump": "sec-storyboard"},
    ("Storyboard", "text"): {"title": "On-screen text too long or not in the facts", "fixes": ["redo_scenes"],
        "why": "On-screen text is limited to 8 words, and numbers must come from the story's facts.", "manual": "Open the scene and shorten or remove the text.", "jump": "sec-storyboard"},
    ("Storyboard", "source_leak"): {"title": "Source wording in a scene", "fixes": ["redo_scenes"],
        "why": "A scene carries wording from the source.", "manual": "Open the scene and reword the part the message quotes.", "jump": "sec-storyboard"},
    ("Narration", "script"): {"title": "Characters or words the voice cannot read", "fixes": ["narration_parts"],
        "why": "Digits, other scripts, or English and Hindi letters joined in one word are skipped or mispronounced by the voice.",
        "manual": "Edit the part: write numbers as words and keep English words separate from Hindi endings.", "jump": "sec-narration"},
    ("Narration", "svara"): {"title": "Voice tags that do not match", "fixes": ["narration_parts", "recheck"],
        "why": "The spoken text and its tagged text differ, or a tag is not one the voice knows.", "manual": "Edit the part, or write it again.", "jump": "sec-narration"},
    ("Narration", "coverage"): {"title": "A beat has no narration yet", "fixes": ["narration_parts"],
        "why": "The plan has a beat nobody has written narration for.", "manual": "Use “Write the narration”.", "jump": "sec-narration"},
}
DEFAULT = {"title": "", "fixes": ["recheck"], "why": "This check found a problem the app has no automatic fix for.",
           "manual": "Open the listed item and correct it; then press “Check again”.", "jump": "sec-storyboard"}
SOURCE_PART = {"narration": "Narration", "storyboard": "Storyboard", "prompts": "Image prompts"}


def _issues(plan_id: str) -> list[dict]:
    plan = planner.get_plan(plan_id)
    v = plan["validation"] or {}
    out = [{**i, "part": "Narration", "level": i.get("level") or "error"} for i in v.get("issues", [])]
    out += [{**i, "part": "Storyboard"} for i in (v.get("storyboard") or {}).get("issues", [])]
    out += [{**i, "part": "Image prompts"} for i in (v.get("prompts") or {}).get("issues", [])]
    return [i for i in out if i["level"] == "error"]


def blockers(plan_id: str) -> list[dict]:
    """The error-level checks, grouped by (part, kind), each with its explanation, its fixes and what a person does if the fixes are not enough."""
    plan = planner.get_plan(plan_id)
    seg_ids = {s["id"] for s in plan["segments"]}
    locked_segs = {s["id"] for s in plan["segments"] if s["locked"] or s["status"] == "approved"}
    locked_scenes = {s["id"] for s in plan["scenes"] if s["locked"]}
    start = {s["id"]: s["start_s"] for s in plan["scenes"]}
    groups: dict[tuple[str, str], list[dict]] = {}
    for i in _issues(plan_id):
        groups.setdefault((i["part"], i["kind"]), []).append(i)
    out = []
    for (part, kind), items in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        cat = CATALOG.get((part, kind)) or {**DEFAULT, "title": f"{part}: {kind.replace('_', ' ')}"}
        where = list(dict.fromkeys(i["where"] for i in items))
        kept = [w for w in where if w in locked_segs or w in locked_scenes]
        fixes = [{"id": f, **FIXES[f]} for f in [*cat["fixes"], *(["recheck"] if "recheck" not in cat["fixes"] else [])]]       # "check again" is always offered: the report may be older than your last change
        out.append({"key": f"{part}|{kind}", "part": part, "kind": kind, "title": cat["title"], "why": cat["why"], "count": len(items), "where": where[:12],
                    "when": [round(start[w]) for w in where if w in start][:12], "sample": items[0]["text"], "fixes": fixes, "manual": cat["manual"], "jump": cat["jump"],
                    "kept": len(kept), "note": (f"{len(kept)} of these are locked or approved: unlock them first, the fix keeps them as they are." if kept else ""),
                    "orphans": sum(1 for w in where if part == "Narration" and w not in seg_ids and w.startswith("seg-"))})
    return out


def recheck(plan_id: str) -> dict:
    n = planner.validate_plan(plan_id)
    b = storyboard.validate_storyboard(plan_id)
    out = {"narration": n, "storyboard": b, "ok": n["ok"] and b["ok"]}
    if any(sc["data"].get("prompts") for sc in storyboard.get_scenes(plan_id)):
        out["prompts"] = imgplan.validate_prompts(plan_id)
        out["ok"] = out["ok"] and out["prompts"]["ok"]
    return out


def targets(plan_id: str, key: str) -> list[str]:
    part, kind = key.split("|", 1)
    return list(dict.fromkeys(i["where"] for i in _issues(plan_id) if i["part"] == part and i["kind"] == kind))


# ── instant fixes ───────────────────────────────────────────────────────────

_CONT = re.compile(r"^(?P<name>.+?): “(?P<detail>.+)” must stay the same but is not in the prompt$")


def relax_details(plan_id: str, key: str) -> list[str]:
    """Move the character details named by the continuity errors from fixed to flexible. Returns "name: detail" lines."""
    assets = {a["name"]: a for a in storyboard.get_assets(plan_id)}
    changed: list[str] = []
    for i in _issues(plan_id):
        m = _CONT.match(i["text"])
        if not m or f"{i['part']}|{i['kind']}" != key:
            continue
        a = assets.get(m["name"])
        if not a:
            continue
        data = a["data"]
        hit = next((x for x in data.get("fixed", []) if str(x).strip().strip(".") == m["detail"].strip().strip(".")), None)
        if hit is None:
            continue
        data["fixed"] = [x for x in data["fixed"] if x != hit]
        data["flexible"] = [*data.get("flexible", []), hit]
        db.ex("UPDATE assets SET data=?, rev=rev+1, updated_at=? WHERE id=?", (db.jdump(data), db.now(), a["id"]))
        changed.append(f"{m['name']}: {m['detail']}")
    return list(dict.fromkeys(changed))


def drop_orphans(plan_id: str) -> int:
    live = {s["id"] for s in planner.get_plan(plan_id)["segments"]}
    gone = [sc["id"] for sc in storyboard.get_scenes(plan_id) if sc["segment_id"] not in live]
    for sid in gone:
        db.ex("DELETE FROM scenes WHERE id=?", (sid,))
    return len(gone)


def run_instant(plan_id: str, fix: str, key: str) -> str:
    """Do an instant fix, check again, and say in plain words what happened."""
    before = len(_issues(plan_id))
    detail = ""
    if fix == "recompile":
        imgplan.compile_plan(plan_id)
        detail = "Wrote the image prompts again from the scenes and characters as they are now."
    elif fix == "relax":
        moved = relax_details(plan_id, key)
        imgplan.compile_plan(plan_id)
        detail = ("Moved " + str(len(moved)) + " detail(s) to “may change”: " + "; ".join(moved[:6]) + (" …" if len(moved) > 6 else "") + ". Wrote the prompts again.") if moved else "No detail could be matched to a character."
    elif fix == "retime":
        storyboard.retime(plan_id)
        detail = "Re-timed the scenes to the narration."
    elif fix == "drop_orphans":
        detail = f"Removed {drop_orphans(plan_id)} scene(s) whose narration part no longer exists."
    elif fix == "recheck":
        detail = "Checked again."
    else:
        raise planner.PlanError(f"unknown fix '{fix}'")
    recheck(plan_id)
    after = _issues(plan_id)
    store.log(plan_id, "resolve", {"fix": fix, "key": key, "before": before, "after": len(after)})
    left = blockers(plan_id)
    if not after:
        return f"{detail} All {before} blocking error(s) are cleared: you can move on."
    why = "; ".join(f"{b['count']} × {b['title'].lower()}" for b in left[:4])
    return f"{detail} {before} error(s) before, {len(after)} now. Still blocking: {why}. Each one is listed below with its next step."


# ── model fixes (run inside the usual job) ──────────────────────────────────

def redo_note(texts: list[str]) -> str:
    """What to tell the writing model. The wording of a failed check is never repeated back: the model copies it, and the same problem returns."""
    asks = []
    if any("not English" in t for t in texts):
        asks.append("On-screen text must be plain ASCII letters and digits only: no superscripts, no symbols like ², no units written with them. Prefer no on-screen text, or a short plain phrase.")
    if any(t.startswith("copied_wording") for t in texts):
        asks.append("A phrase was copied from the source. Describe the idea in entirely different words, in action and facts.fixed too, and show it as a picture, not as the source's sentence.")
    return " ".join(asks) or "Fix this problem: " + " | ".join(texts)


async def run_job(plan_id: str, fix: str, key: str, backend, s, progress) -> str:
    where = targets(plan_id, key)
    plan = planner.get_plan(plan_id)
    if fix == "narration_parts":
        segs = {x["id"]: x for x in plan["segments"]}
        beats = list(dict.fromkeys(segs[w]["beat"] for w in where if w in segs))
        if not beats and key.endswith("coverage"):
            await planner.make_narration(plan_id, backend, s, None, progress, True)
            beats = ["the missing beats"]
        elif beats:
            await planner.make_narration(plan_id, backend, s, beats, progress)
        else:
            return "Nothing to rewrite: the checks name no narration part. Press “Check again”."
        recheck(plan_id)
        left = len(_issues(plan_id))
        note = f"Rewrote {len(beats)} beat(s) of narration. {left} blocking error(s) remain." if left else f"Rewrote {len(beats)} beat(s) of narration; every blocking error is cleared."
        store.log(plan_id, "resolve", {"fix": fix, "key": key, "beats": len(beats), "after": left})
        return note
    if fix == "redo_scenes":
        scenes = {x["id"]: x for x in plan["scenes"]}
        todo = [w for w in where if w in scenes and not scenes[w]["locked"]]
        done, failed = 0, []
        for n, sid in enumerate(todo):
            progress(n, len(todo), f"scene {n + 1} of {len(todo)}")
            texts = [i["text"] for i in _issues(plan_id) if i["where"] == sid][:3]
            try:
                await storyboard.regenerate_scene(sid, backend, s, redo_note(texts))
                done += 1
            except planner.PlanError as e:
                failed.append(str(e)[:80])
        if planner.get_plan(plan_id)["scenes"]:
            imgplan.compile_plan(plan_id)
        recheck(plan_id)
        left = len(_issues(plan_id))
        kept = len(where) - len(todo)
        bits = [f"Redesigned {done} scene(s)"] + ([f"{kept} locked scene(s) were kept"] if kept else []) + ([f"{len(failed)} could not be redone ({failed[0]})"] if failed else [])
        store.log(plan_id, "resolve", {"fix": fix, "key": key, "done": done, "after": left})
        return ". ".join(bits) + f". {left} blocking error(s) remain." if left else ". ".join(bits) + ". Every blocking error is cleared."
    if fix == "storyboard_parts":
        segs = list(dict.fromkeys(w for w in where if w.startswith("seg-")))
        await storyboard.make_storyboard(plan_id, backend, s, segs or None, progress, False)
        recheck(plan_id)
        left = len(_issues(plan_id))
        store.log(plan_id, "resolve", {"fix": fix, "key": key, "segments": len(segs), "after": left})
        return f"Designed scenes again for {len(segs) or 'all'} narration part(s). " + (f"{left} blocking error(s) remain." if left else "Every blocking error is cleared.")
    raise planner.PlanError(f"unknown fix '{fix}'")
