"""Voice for a short: one take per beat, in the engine and voice the short chose (the app's own voices, story2/voices.py). A take is tied to a hash of its words and the voice, so a
beat whose wording changed has no valid take until it is spoken again. Takes are numbered attempts (story3/store.py); the approved one, else the latest valid one, counts."""
import time

import httpx

from story import settings as settings_mod
from story2 import maya, safety, voices
from story3 import audiofix, store as media, voice as voice3
from story3.voice import MediaError

from . import store

RETAKES = 1


def current(short: dict) -> dict:
    return voices.current({"tts": short["settings"].get("voice")})


def segment(beat: dict) -> dict:
    sents = [{"text": s["text"], "tag": s.get("tag", ""), "pause_after_s": 0} for s in beat["sentences"]]
    return {"id": beat["id"], "sentences": sents, "annotated": " ".join(s["text"] for s in sents), "plain": " ".join(s["text"] for s in sents)}


def beat_hash(short: dict, beat: dict) -> str:
    k = voices.key(current(short))
    return store.input_hash(k, voices.text_for(k, segment(beat)))


def chosen(short: dict, beat: dict) -> dict | None:
    return store.chosen(short["id"], store.VOICE, beat["id"], beat_hash(short, beat))


def real_seconds(short: dict) -> dict[str, float]:
    """beat id -> real spoken seconds, for beats that have a valid take."""
    out = {}
    for b in short["beats"]:
        it = chosen(short, b)
        if it and it["meta"].get("duration_s"):
            out[b["id"]] = float(it["meta"]["duration_s"])
    return out


def missing(short: dict) -> list[dict]:
    return [b for b in short["beats"] if not chosen(short, b)]


async def make(short_id: str, beat_ids: list[str] | None = None, only_missing: bool = True, progress=None, s: dict | None = None, key: str = "") -> dict:
    s = s or settings_mod.get()
    key = key or settings_mod.api_key()
    short = store.get(short_id)
    cur = current(short)
    todo = [b for b in short["beats"] if (not beat_ids or b["id"] in beat_ids) and (not only_missing or not chosen(short, b))]
    made, failed = 0, []
    async with httpx.AsyncClient(timeout=voice3.REQUEST_TIMEOUT_S) as client:
        for i, beat in enumerate(todo):
            if progress:
                progress(i, len(todo), f"voice {i + 1} of {len(todo)}")
            safety.guard_tags(beat["sentences"])
            h = beat_hash(short, beat)
            it = media.add(short_id, store.VOICE, beat["id"], 0, "running", {"input_hash": h})
            t0 = time.time()
            try:
                best = None
                for extra in range(RETAKES + 1):                           # a take with long dead air is made once more with another seed
                    bodies = [voices.request_body(cur, t, it["attempt"] + 1000 * extra) for t in voices.texts_for(voices.key(cur), segment(beat))]
                    raw = await voice3._speak_all(client, s["base_url"], key, bodies)
                    got, rep = audiofix.trim(raw, [], audiofix.DEFAULT_MAX_GAP_S)
                    if best is None or rep["longest_removed_s"] < best[1]["longest_removed_s"]:
                        best = (got, rep, bodies[0])
                    if rep["longest_removed_s"] < voice3.RETAKE_GAP_S:
                        break
                audio, rep, body = best
                name = f"voice/{beat['id']}-a{it['attempt']}.wav"
                (store.media_dir(short_id, "voice") / f"{beat['id']}-a{it['attempt']}.wav").write_bytes(audio)
                media.update(it["id"], status="done", file=name, meta={"duration_s": round(media.wav_seconds(audio), 2), "voice": body["voice"], "seed": body["seed"], "model": body["model"],
                                                                      "seconds_taken": round(time.time() - t0, 1), "trim": rep})
                made += 1
            except MediaError as e:
                media.update(it["id"], status="failed", meta={"error": str(e)[:300]})
                failed.append({"beat": beat["id"], "error": str(e)[:200]})
                if "not reachable" in str(e):
                    break
    from . import planner
    planner.sync_timing(short_id)                           # the shots now follow the real length of the voice
    if progress:
        progress(len(todo), len(todo), "done")
    return {"made": made, "failed": failed}


def state(short: dict) -> dict:
    rows = []
    for b in short["beats"]:
        att = media.items(short["id"], store.VOICE, b["id"])
        want = beat_hash(short, b)
        ch = chosen(short, b)
        rows.append({"beat": b["id"], "chosen": ch["id"] if ch else None, "seconds": ch["meta"].get("duration_s") if ch else None,
                     "attempts": [{"id": a["id"], "attempt": a["attempt"], "status": a["status"], "approved": a["approved"], "current": a["meta"].get("input_hash") == want,
                                   "seconds": a["meta"].get("duration_s"), "error": a["meta"].get("error", ""), "url": f"/api/shorts/file/{short['id']}/{a['file']}" if a["file"] else ""} for a in att]})
    return {"engine": current(short)["engine"], "voice": current(short)["voice"], "beats": rows, "have": sum(1 for r in rows if r["chosen"]), "total": len(rows),
            "tags": {"style": list(maya.STYLE_TAGS)}}
