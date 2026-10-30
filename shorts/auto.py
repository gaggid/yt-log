"""Auto-run: every unfinished step of a short, in order, as one background job. It stops at the first thing it cannot settle (a failed check, a failed clip, a missing input, the keyframe
checkpoint of the keyframe pipeline) and says which; everything finished is kept, and pressing it again resumes. `steps()` is also what the screen's "Next:" bar reads.

Order, quick and keyframe: plan, voice, fit the shots to the voice, [start pictures, look at them], clips, put together.
Order, remix: (link, window and the rights boxes are done by hand) voice-over, animate, put together."""
from story3 import store as media

from . import checks, clips, pipelines as P, planner, remix, stitch, store, voice as svoice


def changed_since(short: dict, final: dict) -> bool:
    """True when something the video was made from is no longer what counts."""
    used = final["meta"].get("used") or {}
    if short["pipeline"] == "remix":
        parts = remix.chosen_parts(short)
        return not all(parts) or final["meta"].get("input_hash") is None
    now_clips = {sh["id"]: (clips.chosen_clip(short, sh) or {}).get("id") for sh in short["shots"]}
    now_voice = {b["id"]: (svoice.chosen(short, b) or {}).get("id") for b in short["beats"]}
    return used.get("clips") != now_clips or used.get("voice") != now_voice


def steps(short: dict) -> list[dict]:
    """The steps of this short's pipeline, each with whether it is done."""
    out = []

    def add(sid, label, done, optional=False):
        out.append({"id": sid, "label": label, "done": bool(done), "optional": optional})
    if short["pipeline"] == "remix":
        r = remix.data(short)
        add("video", "Fetch the video and choose the window", r["source"] and r["driving"])
        if r["audio"] == "voiceover":
            add("voice", "Make the voice-over", short["beats"] and not svoice.missing(short))
        add("animate", "Animate the character", all(remix.chosen_parts(short)) and r["driving"])
        add("final", "Put the short together", short.get("status") == "made" and _final_ok(short))
        return out
    add("plan", "Plan the short", short["shots"])
    if short.get("settings", {}).get("voice_mode") != "none":
        add("voice", "Make the voice", short["beats"] and not svoice.missing(short))
    tl_ok = bool(short["shots"]) and not [p for p in checks.run(short)["issues"] if p["code"] == "shot_too_long"]
    add("fit", "Fit the shots to the voice", tl_ok and short["beats"] and not svoice.missing(short))
    if P.keyframes_on(short):
        add("keyframes", "Make the start pictures", short["shots"] and all(clips.chosen_keyframe(short, sh) for sh in short["shots"]))
        add("review", "Look at the start pictures", short.get("keyframes_confirmed") or not short["settings"].get("review_keyframes", True), optional=not short["settings"].get("review_keyframes", True))
    add("clips", "Make the clips", short["shots"] and all(clips.chosen_clip(short, sh) for sh in short["shots"]))
    add("final", "Put the short together", short.get("status") == "made" and _final_ok(short))
    return out


def _final_ok(short: dict) -> bool:
    its = [i for i in media.items(short["id"], store.FINAL, "final") if i["status"] == "done" and i["file"]]
    return bool(its) and not changed_since(short, its[-1])


def next_step(short: dict) -> dict | None:
    return next((s for s in steps(short) if not s["done"]), None)


def state(short: dict) -> dict:
    st = steps(short)
    nxt = next((s for s in st if not s["done"]), None)
    return {"steps": st, "next": nxt["id"] if nxt else None, "done": nxt is None}


async def run(short_id: str, backend, s: dict, progress, key: str = "") -> str:
    """Do every unfinished step. Returns a sentence for the screen: what was done and where it stopped."""
    short = store.get(short_id)
    did = []

    def sub(label: str):
        return lambda d, t, l="": progress(d, t, f"{label}: {l}" if l else label)
    if short["pipeline"] == "remix":
        return await _run_remix(short_id, s, progress, key)
    if not short["shots"]:
        progress(0, 1, "planning the short")
        await planner.make_plan(short_id, backend, s, sub("plan"))
        did.append("planned")
        short = store.get(short_id)
    if short.get("settings", {}).get("voice_mode") != "none" and svoice.missing(short):
        res = await svoice.make(short_id, progress=sub("voice"), s=s, key=key)
        did.append(f"voice ({res['made']} made)")
        if res["failed"]:
            return f"Stopped at the voice: {res['failed'][0]['error']}"
        short = store.get(short_id)
    note = await planner.fit_shots(short_id, backend, s, sub("shots"))
    if not note.startswith("every"):
        did.append(note)
        short = store.get(short_id)
        if svoice.missing(short):                                   # a rewritten beat keeps its words, so its voice stays valid; this only fires if wording changed
            await svoice.make(short_id, progress=sub("voice"), s=s, key=key)
    short = planner.sync_timing(short_id)
    chk = checks.run(short)
    if not chk["ok"]:
        first = next(i for i in chk["issues"] if i["level"] == "block")
        return f"Stopped at the checks: {first['text']}"
    if P.keyframes_on(short):
        if not all(clips.chosen_keyframe(short, sh) for sh in short["shots"]):
            res = await clips.make_keyframes(short_id, progress=sub("keyframes"), s=s, key=key)
            did.append(f"start pictures ({res['made']} made)")
            if res["failed"]:
                return f"Stopped at the start pictures: shot {res['failed'][0]['shot']}: {res['failed'][0]['error']}"
            short = store.get(short_id)
        if short["settings"].get("review_keyframes", True) and not short.get("keyframes_confirmed"):
            return "Done so far: " + ", ".join(did or ["nothing new"]) + ". Look at the start pictures, redo or replace any you do not like, press 'Pictures are good', then press Auto-run again."
    if not all(clips.chosen_clip(short, sh) for sh in short["shots"]):
        res = await clips.make_clips(short_id, progress=sub("clips"), s=s, key=key)
        did.append(f"clips ({res['made']} made)")
        if res["failed"] or res["skipped"]:
            bad = (res["failed"] or res["skipped"])[0]
            return f"Stopped at the clips: shot {bad['shot']}: {bad['error']}. Everything finished is kept; press Auto-run to try the rest again."
    progress(0, 1, "putting the short together")
    import asyncio
    await asyncio.to_thread(stitch.build, short_id, sub("final"))
    did.append("put together")
    return "Finished: " + ", ".join(did)


async def _run_remix(short_id: str, s: dict, progress, key: str) -> str:
    short = store.get(short_id)
    chk = remix.check(short)
    if chk["blockers"]:
        return f"Stopped: {chk['issues'][0]['text']}"
    did = []
    short = remix.sync_voiceover(short_id)
    if short["beats"] and svoice.missing(short):
        res = await svoice.make(short_id, progress=lambda d, t, l="": progress(d, t, f"voice-over: {l}"), s=s, key=key)
        if res["failed"]:
            return f"Stopped at the voice-over: {res['failed'][0]['error']}"
        did.append("voice-over")
    if not all(remix.chosen_parts(store.get(short_id))):
        res = await remix.make(short_id, progress=progress, s=s, key=key)
        if res["failed"]:
            return f"Stopped at the animation: {res['failed'][0]['error']}"
        did.append("animation")
    import asyncio
    await asyncio.to_thread(remix.build, short_id, lambda d, t, l="": progress(d, t, f"putting together: {l}"))
    did.append("put together")
    return "Finished: " + ", ".join(did)
