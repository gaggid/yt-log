"""Batch E: voice. One Svara request per narration segment, taken from the exported plan, saved as a numbered attempt, measured, and used to retime
the scenes to the real spoken length. A segment whose wording changed after its audio was made no longer counts until it is generated again."""
import asyncio
import json
import time

import httpx

from story import db, settings as settings_mod
from story2 import editorial, export, maya, planner, storyboard, store as plan_store, svara, voices

from . import audiofix, store

RETRIES = 2
REQUEST_TIMEOUT_S = 1500                 # the gateway's own limit must be raised too (svara-tts timeout_s); see docs/phase2_plan.md


class MediaError(Exception):
    pass


def load_export(plan_id: str) -> tuple[dict, dict]:
    """The latest saved export and its document. Media is made from the exported file, so it must still describe the plan."""
    files = export.list_exports(plan_id)
    if not files:
        raise MediaError("export the plan first: media is made from the exported file")
    latest = files[0]
    plan = planner.get_plan(plan_id)
    if latest["content_hash"] != editorial.content_hash(plan):
        raise MediaError(f"the plan changed after export v{latest['rev']}: export it again before generating")
    doc = json.loads(open(latest["path"], encoding="utf-8").read())
    return latest, doc


def tts_requests(plan: dict, seg: dict, attempt: int, doc: dict | None = None) -> list[dict]:
    """The speech requests for one segment (one, or several when Maya's text is longer than a request may be), in the engine and voice the plan uses
    now. The export's recommended request only overrides Svara's defaults: it was written for Svara."""
    cur = voices.current(plan["narrator"])
    k = voices.key(cur)
    rec = ((doc or {}).get("public", {}).get("production_notes", {}).get("tts", {}).get("recommended_request")) if cur["engine"] == "svara-tts" else None
    return [voices.request_body(cur, t, attempt, rec) for t in voices.texts_for(k, seg)]


async def _speak_all(client: httpx.AsyncClient, base: str, key: str, bodies: list[dict]) -> bytes:
    parts = [await _speak(client, base, key, b) for b in bodies]
    try:
        return maya.join_wavs(parts)
    except ValueError as e:
        raise MediaError(str(e)) from e


def apply_timing(plan_id: str) -> float:
    """Set each segment's duration to its real audio length (where it has valid audio) and recompute every scene's start and end from it."""
    real = store.audio_seconds(plan_id)
    for sid, secs in real.items():
        db.ex("UPDATE segments SET duration_s=? WHERE id=?", (round(secs, 2), sid))
    return storyboard.retime(plan_id)


def estimated_seconds(seg: dict, wpm: float) -> float:
    return svara.spoken_seconds(seg["plain"], wpm, sum(x.get("pause_after_s") or 0 for x in seg["sentences"]))


RETAKES = 2                   # extra tries for a take with a long unplanned silence (the engine sometimes goes quiet near the end of a long request)
RETAKE_GAP_S = 2.0


def max_gap_s(plan: dict) -> float:
    """The longest silence a voice take keeps between sentences, except the pauses the narration asked for (plan setting `voice.max_gap_s`)."""
    try:
        return max(0.15, float((plan["settings"].get("voice") or {}).get("max_gap_s", audiofix.DEFAULT_MAX_GAP_S)))
    except (TypeError, ValueError):
        return audiofix.DEFAULT_MAX_GAP_S


def retrim(plan_id: str, segment_ids: list[str] | None = None) -> dict:
    """Take the voice that already exists and make a new numbered attempt of each part with its dead air removed (nothing is overwritten and nothing is spoken again).
    A part whose counting take was already trimmed is left. The new attempt is approved when the old one was. Returns what was removed."""
    plan = planner.get_plan(plan_id)
    voice = store.voice_key(plan)
    done, saved, skipped = [], 0.0, 0
    for seg in sorted(plan["segments"], key=lambda x: (x["seq"], x["id"])):
        if segment_ids and seg["id"] not in segment_ids:
            continue
        old = store.chosen_voice(plan_id, seg, voice)
        if not old or not old["file"]:
            continue
        if old["meta"].get("trim"):
            skipped += 1
            continue
        raw = store.path_of(old).read_bytes()
        new_audio, rep = audiofix.trim(raw, [float(x.get("pause_after_s") or 0) for x in seg["sentences"]], max_gap_s(plan))
        it = store.add(plan_id, "voice", seg["id"], old["export_rev"], "running", {"text_hash": old["meta"].get("text_hash")})
        name = f"voice/{seg['id']}-a{it['attempt']}.wav"
        (store.media_dir(plan_id, "voice") / f"{seg['id']}-a{it['attempt']}.wav").write_bytes(new_audio)
        flags = [f for f in old["meta"].get("flags", []) if not f.startswith("unusual length")]
        store.update(it["id"], status="done", file=name, meta={**{k: v for k, v in old["meta"].items() if k not in ("duration_s", "flags")}, "duration_s": round(store.wav_seconds(new_audio), 2),
                                                                "flags": flags, "trim": rep, "trimmed_from": old["id"]})
        if old["approved"]:
            store.approve(it["id"])
        done.append({"segment": seg["id"], "removed_s": rep["removed_s"], "longest_removed_s": rep["longest_removed_s"]})
        saved += rep["removed_s"]
    if done:
        apply_timing(plan_id)
        plan_store.log(plan_id, "voice_trim", {"parts": len(done), "removed_s": round(saved, 1)})
    return {"trimmed": done, "removed_s": round(saved, 1), "already_trimmed": skipped}


POLL_S = 3
JOB_LIMIT_S = 1500


async def _wait_job(client: httpx.AsyncClient, base: str, key: str, job: dict) -> bytes:
    """The gateway answered 202 with a job: poll it until it has audio (Prefer: respond-async keeps long requests off one open connection)."""
    import base64
    url = base.rstrip("/") + "/jobs/" + job["id"]
    t0 = time.time()
    while time.time() - t0 < JOB_LIMIT_S:
        r = await client.get(url, headers={"Authorization": f"Bearer {key}"})
        if r.status_code != 200:
            raise MediaError(f"job check failed: {r.status_code} {r.text[:120]}")
        j = r.json()
        if j.get("status") == "succeeded":
            res = j.get("result") or {}
            if not res.get("audio_b64"):
                raise MediaError("the voice job finished without audio")
            return base64.b64decode(res["audio_b64"])
        if j.get("status") in ("failed", "cancelled", "canceled", "error"):
            raise MediaError(f"voice job {j['status']}: {str(j.get('error') or j.get('http_status') or '')[:160]}")
        await asyncio.sleep(POLL_S)
    raise MediaError("the voice job did not finish in time")


async def _speak(client: httpx.AsyncClient, base: str, key: str, body: dict) -> bytes:
    last = ""
    headers = {"Authorization": f"Bearer {key}"}
    if voices.ENGINES.get(body.get("model"), {}).get("async"):
        headers["Prefer"] = "respond-async"
    for n in range(RETRIES + 1):
        try:
            r = await client.post(base.rstrip("/") + "/audio/speech", json=body, headers=headers)
            if r.status_code == 202:
                return await _wait_job(client, base, key, r.json())
        except MediaError:
            raise
        except (httpx.TransportError, httpx.TimeoutException) as e:
            last = f"{type(e).__name__}: {e}"
            if isinstance(e, httpx.ConnectError):
                raise MediaError(f"the model server is not reachable ({last})") from e
        else:
            if r.status_code == 200:
                return r.content
            last = f"{r.status_code} {r.text[:160]}"
            if r.status_code not in (429, 500, 502, 503, 504):
                break
        await asyncio.sleep(3 * (n + 1))
    raise MediaError(last or "no answer from the model server")


async def generate(plan_id: str, segment_ids: list[str] | None = None, only_missing: bool = True, progress=None,
                   s: dict | None = None, key: str = "") -> dict:
    s = s or settings_mod.get()
    key = key or settings_mod.api_key()
    latest, doc = load_export(plan_id)
    plan = planner.get_plan(plan_id)
    wpm = plan["settings"].get("wpm", planner.WPM)
    cur = {x["id"]: x for x in plan["segments"]}
    todo = [x for x in doc["public"]["narration"]["segments"] if x["id"] in cur and (not segment_ids or x["id"] in segment_ids)]
    voice = store.voice_key(plan)
    if only_missing:
        todo = [x for x in todo if not store.chosen_voice(plan_id, cur[x["id"]], voice)]
    made, failed = 0, []
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S) as client:
        for i, seg in enumerate(todo):
            if progress:
                progress(i, len(todo), f"part {i + 1} of {len(todo)}: making the voice")
            now = cur[seg["id"]]                          # the plan's own sentences: voice tags can change after an export without changing what was approved
            it = store.add(plan_id, "voice", seg["id"], latest["rev"], "running", {"text_hash": store.segment_hash(now, voice)})
            bodies = tts_requests(plan, now, it["attempt"], doc)
            body = bodies[0]
            t0 = time.time()
            try:
                est = estimated_seconds(now, wpm)
                best, tries = None, 0
                for extra in range(RETAKES + 1):                  # a take with a long silence nobody asked for is made again with another seed (kept: the one with least dead air)
                    bodies = tts_requests(plan, now, it["attempt"] + 1000 * extra, doc)
                    raw = await _speak_all(client, s["base_url"], key, bodies)
                    got, rep = audiofix.trim(raw, [float(x.get("pause_after_s") or 0) for x in now["sentences"]], max_gap_s(plan))          # dead air out, planned pauses kept
                    tries += 1
                    if best is None or rep["longest_removed_s"] < best[1]["longest_removed_s"]:
                        best, body = (got, rep), bodies[0]
                    if rep["longest_removed_s"] < RETAKE_GAP_S:
                        break
                audio, trimmed = best
                name = f"voice/{seg['id']}-a{it['attempt']}.wav"
                path = store.media_dir(plan_id, "voice") / f"{seg['id']}-a{it['attempt']}.wav"
                path.write_bytes(audio)
                secs = store.wav_seconds(audio)
                flags = []
                if tries > 1:
                    flags.append(f"made {tries} times because of a long silence; the take with the least dead air was kept")
                ratio = secs / est if est else 1
                if ratio < 0.6 or ratio > 1.6:
                    flags.append(f"unusual length: {secs:.0f}s of audio for about {est:.0f}s expected; listen for skipped or repeated words")
                if trimmed["longest_removed_s"] >= 2.0:
                    flags.append(f"{trimmed['longest_removed_s']:.0f}s of blank audio was removed from this take: listen once to check nothing is missing there")
                store.update(it["id"], status="done", file=name, meta={"duration_s": round(secs, 2), "expected_s": round(est, 1), "seconds_taken": round(time.time() - t0, 1),
                                                                         "voice": body["voice"], "seed": body["seed"], "temperature": body.get("temperature"),
                                                                         "repetition_penalty": body.get("repetition_penalty"), "pieces": len(bodies), "flags": flags, "model": body["model"], "trim": trimmed})
                apply_timing(plan_id)
                made += 1
            except asyncio.CancelledError:
                store.update(it["id"], status="failed", meta={"error": "stopped before it finished"})
                raise
            except MediaError as e:
                store.update(it["id"], status="failed", meta={"error": str(e)[:300], "seconds_taken": round(time.time() - t0, 1)})
                failed.append({"segment": seg["id"], "error": str(e)[:200]})
                if "not reachable" in str(e):
                    break
        if progress:
            progress(len(todo), len(todo), "done")
    plan_store.log(plan_id, "voice", {"made": made, "failed": len(failed), "export_rev": latest["rev"]})
    return {"made": made, "failed": failed, "skipped": len(doc["public"]["narration"]["segments"]) - len(todo)}


def sample_mtime(plan_id: str, plan: dict) -> float:
    return (store.media_dir(plan_id) / sample_file(plan)).stat().st_mtime


def sample_file(plan: dict) -> str:
    cur = voices.current(plan["narrator"])
    return f"voice/sample-{cur['engine']}-{cur['voice']}.wav"


async def make_sample(plan_id: str, progress=None, s: dict | None = None, key: str = "") -> dict:
    """One opening sentence in the chosen voice, to audition it before the whole narration is voiced. Not a numbered take and never used in the video."""
    s = s or settings_mod.get()
    key = key or settings_mod.api_key()
    plan = planner.get_plan(plan_id)
    seg = next((x for x in sorted(plan["segments"], key=lambda x: (x["seq"], x["id"])) if x["sentences"]), None)
    if not seg:
        raise MediaError("write the narration first: the sample reads its first sentence")
    cur = voices.current(plan["narrator"])
    one = {**seg, "sentences": seg["sentences"][:2], "annotated": svara.serialise(seg["sentences"][:2])}
    bodies = [voices.request_body(cur, t, 1) for t in voices.texts_for(voices.key(cur), one)]
    if progress:
        progress(0, 1, f"a sample in {voices.ENGINES[cur['engine']]['label']} / {cur['voice']}")
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S) as client:
        audio = await _speak_all(client, s["base_url"], key, bodies)
    (store.media_dir(plan_id, "voice") / f"sample-{cur['engine']}-{cur['voice']}.wav").write_bytes(audio)
    if progress:
        progress(1, 1, "done")
    return {"seconds": round(store.wav_seconds(audio), 1), "file": sample_file(plan)}


def state(plan_id: str) -> dict:
    """Everything the Voice section shows: per segment, its attempts and which one counts, with real versus estimated length."""
    plan = planner.get_plan(plan_id)
    wpm = plan["settings"].get("wpm", planner.WPM)
    cur = voices.current(plan["narrator"])
    voice = store.voice_key(plan)
    beats = {b["id"]: b["name"] for b in (plan["blueprint"] or {}).get("beats", [])}
    rows, real_total, est_total = [], 0.0, 0.0
    for seg in sorted(plan["segments"], key=lambda x: (x["seq"], x["id"])):
        want = store.segment_hash(seg, voice)
        att = store.items(plan_id, "voice", seg["id"])
        chosen = store.chosen_voice(plan_id, seg, voice)
        est = estimated_seconds(seg, wpm)
        est_total += est
        if chosen:
            real_total += chosen["meta"]["duration_s"]
        rows.append({"segment_id": seg["id"], "name": beats.get(seg["beat"], seg["beat"]), "plain": seg["plain"], "expected_s": round(est, 1),
                     "chosen": chosen["id"] if chosen else None,
                     "attempts": [{"id": a["id"], "attempt": a["attempt"], "status": a["status"], "url": f"/api/media/file/{plan_id}/{a['file']}" if a["file"] else "",
                                   "duration_s": a["meta"].get("duration_s"), "approved": a["approved"], "current": a["meta"].get("text_hash") == want,
                                   "flags": a["meta"].get("flags", []), "error": a["meta"].get("error", ""), "seconds_taken": a["meta"].get("seconds_taken"),
                                   "seed": a["meta"].get("seed")} for a in att]})
    have = sum(1 for r in rows if r["chosen"])
    ratio = 3.7
    done_attempts = [a for r in rows for a in r["attempts"] if a["status"] == "done" and a["seconds_taken"] and a["duration_s"]]
    if done_attempts:
        ratio = sum(a["seconds_taken"] for a in done_attempts) / sum(a["duration_s"] for a in done_attempts)
    missing_est = sum(r["expected_s"] for r in rows if not r["chosen"])
    exports = export.list_exports(plan_id)
    cur_hash = editorial.content_hash(plan)
    return {"voice": cur["voice"], "engine": cur["engine"], "sample": f"/api/media/file/{plan_id}/{sample_file(plan)}?t={int(sample_mtime(plan_id, plan))}" if (store.media_dir(plan_id) / sample_file(plan)).is_file() else "", "engines": voices.public(), "segments": rows, "have": have, "total": len(rows), "real_s": round(real_total, 1), "estimated_s": round(est_total, 1),
            "approved": sum(1 for r in rows if any(a["approved"] and a["current"] for a in r["attempts"])),
            "eta_missing_s": round(missing_est * ratio), "speed_ratio": round(ratio, 2),
            "export": {"rev": exports[0]["rev"] if exports else 0, "current": bool(exports and exports[0]["content_hash"] == cur_hash), "exists": bool(exports)}}
