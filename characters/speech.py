"""Virtual life: the character says her thought aloud with Maya (`maya-tts`, docs#speech-maya).

One fixed female voice for every character (`VOICE`). The think step writes `say` (the words) and `say_tag` (one Maya style or sound tag, or neutral);
`story2.maya.chunks` turns them into the request text, `story3.voice._speak` makes the audio (async job + polling), the result is a `char_voice` media row
and a `speak` event next to the `think` event it came from. When the model is down the request waits and tries again (same waits as the pictures).
"""
import asyncio
import re
import time

import httpx

from story2 import maya, voices
from story3 import store as media
from story3.voice import MediaError, REQUEST_TIMEOUT_S, _speak

from . import profile as profile_mod, store

VOICE = "Ahana"                    # the one female voice every character speaks with (female in voices.ENGINES["maya-tts"]; the gateway's default voice)
KIND = "char_voice"
MAX_WORDS = 45                     # she speaks a line or two, not a monologue
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def clean_tag(v) -> str:
    return maya.norm_tag(v) or maya.NEUTRAL


def request(say: str, tag: str) -> dict:
    """The /audio/speech body for one spoken line."""
    words = maya.plain_text(say).split()[:MAX_WORDS]
    parts = maya.chunks([{"text": " ".join(words), "tag": clean_tag(tag)}])
    if not parts:
        raise MediaError("nothing to say")
    body = voices.request_body({"engine": "maya-tts", "voice": VOICE}, "\n".join(parts), 1)
    body["language"] = "hi" if _DEVANAGARI.search(say) else "en"
    return body


async def speak(char: dict, event_id: str, thought: dict, s: dict | None = None, key: str = "", trigger: str = "manual", progress=None) -> dict:
    from . import brain, studio
    say = (thought.get("say") or "").strip()
    if not say:
        raise MediaError("she had nothing to say in this moment")
    body = request(say, thought.get("say_tag", ""))
    inputs = {"text": body["input"][:300], "voice": VOICE, "event_id": event_id}
    t0 = time.time()
    try:
        base_url, api_key = studio._ctx(s, key)
        audio = None
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S) as client:
            for wait in (*brain.DRAW_RETRY_WAITS_S, None):
                try:
                    audio = await _speak(client, base_url, api_key, body)
                    break
                except MediaError as e:
                    if wait is None or not brain._model_unavailable(str(e)):
                        raise
                    profile_mod.log_event(char["id"], "retry", trigger, inputs, {"reason": str(e)[:200], "retry_after_s": wait})
                    if progress:
                        progress(0, 0, f"the model server could not speak ({str(e)[:80]}); trying again in {wait} s")
                    await asyncio.sleep(wait)
                    if progress:
                        progress(0, 0, "speaking")
        store.media_dir(char["id"], KIND).mkdir(parents=True, exist_ok=True)
        it = media.add(char["id"], KIND, "speech", 0, "done", {"event_id": event_id, "text": say, "voice": VOICE})
        fname = f"{KIND}/speech-a{it['attempt']}.wav"
        (store.media_dir(char["id"]) / fname).write_bytes(audio)
        media.update(it["id"], file=fname, meta={"event_id": event_id, "text": say, "voice": VOICE, "seconds_taken": round(time.time() - t0, 1)})
        url = f"/api/characters/file/{char['id']}/{fname}"
        profile_mod.log_event(char["id"], "speak", trigger, inputs, {"media_id": it["id"], "url": url, "status": "done", "latency_ms": round((time.time() - t0) * 1000)})
        return {"media_id": it["id"], "url": url}
    except Exception as e:
        profile_mod.log_event(char["id"], "error", trigger, inputs, {"error": str(e)[:300], "latency_ms": round((time.time() - t0) * 1000)})
        raise
