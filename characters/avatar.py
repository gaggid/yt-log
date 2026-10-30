"""The avatar tab of a person (plan: docs/PLAN_avatar.md): the voice the person speaks with, and a ready test. The test makes a 3-second talking clip of the approved portrait with that voice
through InfiniteTalk, samples frames, and asks the vision model whether the mouth really moves with speech, the hands look natural and it is still the same person. The answer
(`pass` or `weak`) is kept on the character with the clip, so a short can tell at a glance whether this character is ready to talk."""
import asyncio
import base64
import tempfile
import time
from pathlib import Path

import httpx

from shorts import frames, models, wan
from story import llm, settings as settings_mod
from story2 import voices
from story3 import store as media, voice as voice3
from story3.voice import MediaError

from . import store

KIND = "char_avatar"
TEST_LINE = "Namaste! Main aapko ek chhoti si kahani sunane wali hoon, dhyan se suniye."
TEST_SECONDS = 3.0
SAMPLES = 8
PASS_MOUTH, PASS_HANDS, PASS_IDENTITY = 6.0, 6.0, 7.0
PROMPT = ("You are a strict quality checker for talking avatar videos. The FIRST picture is the reference portrait of the character. The next pictures are frames taken in order from a 3-second clip in "
          "which this character speaks. Judge three things and score each from 0 to 10: "
          '"mouth": do the lips and jaw really open and close in different shapes from frame to frame like speech (10), or is the mouth mostly frozen or only wobbling (0-4); '
          '"hands": are the hands and arms, where visible, natural with five fingers and no melting or extra limbs (10), or distorted (0-4); a clip with no hands visible scores 8; '
          '"identity": is it clearly the same person as the reference in every frame, face, hair and skin tone (10) or does the face drift (0-4). '
          'Reply with JSON only: {"mouth": 0-10, "hands": 0-10, "identity": 0-10, "notes": ["short, concrete"]}')


def voice_of(char: dict) -> dict:
    """The voice the person speaks with: the one chosen on the avatar tab, else the app's default voice."""
    v = (char.get("avatar") or {}).get("voice") or {}
    return v if v.get("engine") and v.get("voice") else {}


def verdict(scores: dict) -> str:
    ok = scores["mouth"] >= PASS_MOUTH and scores["hands"] >= PASS_HANDS and scores["identity"] >= PASS_IDENTITY
    return "pass" if ok else "weak"


def picture_path(char: dict) -> Path:
    canon = store.canon_items(char)
    it = canon.get("portrait") or canon.get("body")
    if not it:
        raise MediaError("approve a portrait first: the avatar is made from it")
    return media.path_of(it)


def sample_frames(video: Path, out_dir: Path, n: int = SAMPLES) -> list[Path]:
    info = frames.info(video)
    dur = max(0.5, float(info.get("duration_s") or TEST_SECONDS))
    paths = []
    for i in range(n):
        p = out_dir / f"f{i}.jpg"
        frames.run(["-ss", f"{dur * (i + 0.5) / n:.3f}", "-i", str(video), "-frames:v", "1", "-vf", "scale=360:-1", "-q:v", "4", str(p)])
        paths.append(p)
    return paths


async def judge(portrait: Path, shots: list[Path], s: dict | None = None, key: str = "") -> dict:
    s = s or settings_mod.get()
    b64 = lambda p: base64.b64encode(Path(p).read_bytes()).decode()          # noqa: E731
    content = [{"type": "text", "text": PROMPT}] + [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64(p)}} for p in [portrait, *shots]]
    j = None
    for attempt in range(3):                                                   # the vision model sometimes answers with nothing: ask again with more room
        async with httpx.AsyncClient(timeout=300) as c:
            r = await c.post(s["base_url"].rstrip("/") + "/chat/completions", headers={"Authorization": f"Bearer {key or settings_mod.api_key()}"},
                             json={**llm.model_field(s), "messages": [{"role": "user", "content": content}], "max_tokens": 2500 + 1500 * attempt, "temperature": 0})
        if r.status_code != 200:
            raise MediaError(f"the check was refused ({r.status_code}): {r.text[:160]}")
        try:
            j = llm.parse_json(r.json()["choices"][0]["message"].get("content") or "")
            break
        except ValueError:
            continue
    if not isinstance(j, dict):
        raise MediaError("the check model sent no answer")
    scores = {k: max(0.0, min(10.0, float(j.get(k, 0)))) for k in ("mouth", "hands", "identity")}
    return {**scores, "notes": [str(x) for x in (j.get("notes") or []) if str(x).strip()][:4]}


async def _speak(char: dict, s: dict, key: str) -> bytes:
    narrator = {"tts": voice_of(char)} if voice_of(char) else {}
    cur = voices.current(narrator or None)
    body = voices.request_body(cur, TEST_LINE, 1)
    async with httpx.AsyncClient(timeout=voice3.REQUEST_TIMEOUT_S) as client:
        return await voice3._speak_all(client, s["base_url"], key, [body])


def request(char: dict, image_url: str, audio_url: str, seed: int = 7) -> dict:
    return {"model": models.TALK, "prompt": "A person speaks to the camera, natural expression, subtle head and hand movement.", "negative_prompt": "",
            "image": image_url, "audio": audio_url, "size": models.SIZE_PORTRAIT, "duration": TEST_SECONDS, "fps": models.MODELS[models.TALK]["fps"], "steps": 6, "seed": seed, "response_format": "mp4"}


async def run_test(char_id: str, progress=None, s: dict | None = None, key: str = "") -> dict:
    """Make the clip, judge it, keep both on the character. Raises MediaError with a plain message when a step cannot be done."""
    s = s or settings_mod.get()
    key = key or settings_mod.api_key()
    base = s["base_url"].rstrip("/")
    char = store.get(char_id)
    if char["kind"] != "person":
        raise MediaError("only a person can talk")
    portrait = picture_path(char)
    if progress:
        progress(0, 4, "making the test voice")
    wav = await _speak(char, s, key)
    it = media.add(char_id, KIND, "test", 0, "running", {"voice": voice_of(char) or "default", "version": char["version"]})
    t0 = time.time()
    try:
        if progress:
            progress(1, 4, "making the 3-second talking clip (this takes a while)")
        body = request(char, wan.data_url(frames.crop_916(portrait.read_bytes(), models.SIZE_PORTRAIT), "image/jpeg"), wan.data_url(wav, "audio/wav"))
        data, res = await wan.run(body, base, key, on_job=lambda jid: media.update(it["id"], meta={"job_id": jid}), limit_s=3600)
        rel = f"avatar/test-a{it['attempt']}.mp4"
        path = store.media_dir(char_id, "avatar") / f"test-a{it['attempt']}.mp4"
        path.write_bytes(data)
        if progress:
            progress(2, 4, "looking at the clip")
        with tempfile.TemporaryDirectory() as td:
            shots = sample_frames(path, Path(td))
            scores = await judge(portrait, shots, s, key)
        result = {**scores, "state": verdict(scores), "item": it["id"], "version": char["version"], "checked_at": time.time()}
        media.update(it["id"], status="done", file=rel, meta={"seconds_taken": round(time.time() - t0, 1), "check": result, "model": body["model"], "seed": body["seed"], "steps": body["steps"]})
    except (wan.WanError, MediaError) as e:
        media.update(it["id"], status="failed", meta={"error": str(e)[:300], "seconds_taken": round(time.time() - t0, 1)})
        raise MediaError(str(e)) from e
    char = store.get(char_id)
    char["avatar"] = {**(char.get("avatar") or {}), "ready": result}
    store.save(char)
    if progress:
        progress(4, 4, "done")
    return result


def ready_state(char: dict) -> dict:
    """What the screen and the Shorts checks need: the stored result and whether it still belongs to this version of the character."""
    r = (char.get("avatar") or {}).get("ready") or {}
    return {"state": r.get("state", ""), "stale": bool(r) and r.get("version") != char["version"], "mouth": r.get("mouth"), "hands": r.get("hands"), "identity": r.get("identity"), "notes": r.get("notes", []),
            "item": r.get("item", "")}
