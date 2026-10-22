import asyncio
import base64
import json
import os
import random
import re
import subprocess
import sys
import traceback
import uuid
from datetime import datetime
from pathlib import Path

# Force UTF-8 everywhere on Windows — must be before any I/O
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

import art
import auth
import config
import content
import scenes as scenes_mod
import speech
import video

JOBS_DIR = Path(__file__).with_name("jobs")
JOBS_DIR.mkdir(exist_ok=True)

_PAUSE_RE = re.compile(r'\[pause:([0-9.]+)s\]', re.IGNORECASE)


def _make_silence(path: Path, seconds: float) -> None:
    """Generate a silent MP3 clip via FFmpeg."""
    subprocess.run(
        [config.FFMPEG, "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
         "-t", f"{max(0.1, seconds):.2f}", "-c:a", "libmp3lame", "-q:a", "4", str(path)],
        capture_output=True, check=True)

_STARTED_AT = datetime.now()


def _git_info() -> dict:
    try:
        r = subprocess.run(["git", "log", "-1", "--format=%h|%s"],
                           capture_output=True, text=True, encoding="utf-8",
                           cwd=Path(__file__).parent)
        parts = r.stdout.strip().split("|", 1)
        return {"commit": parts[0], "subject": parts[1] if len(parts) > 1 else ""}
    except Exception:
        return {"commit": "unknown", "subject": ""}


_GIT = _git_info()

app = FastAPI(title="Podcast Video Generator")
auth.install(app)

_jobs: dict[str, dict] = {}

# ── helpers ────────────────────────────────────────────────────────────────────

def _hdrs():
    h = {}
    if config.API_KEY:
        h["Authorization"] = f"Bearer {config.API_KEY}"
    return h

def _clean(s: str) -> str:
    """Strip lone surrogates that json.dumps chokes on."""
    return s.encode("utf-8", errors="replace").decode("utf-8")

async def _post(client: httpx.AsyncClient, path: str, tries: int = 3, **kw) -> httpx.Response:
    """POST with retries on connection errors, timeouts and 5xx (model reloads, tunnel hiccups)."""
    for attempt in range(tries):
        try:
            r = await client.post(f"{config.BASE_URL}{path}", headers=_hdrs(), **kw)
            if r.status_code < 500 and r.status_code != 429:
                r.raise_for_status()
                return r
            err: Exception = httpx.HTTPStatusError(f"{r.status_code} {r.text[:200]}",
                                                   request=r.request, response=r)
        except (httpx.TransportError, httpx.TimeoutException) as e:
            err = e
        if attempt == tries - 1:
            raise err
        await asyncio.sleep(5 * (attempt + 1))

async def _chat(client: httpx.AsyncClient, messages: list, **kwargs) -> str:
    payload = {"model": config.CHAT_MODEL, "messages": messages, **kwargs}
    r = await _post(client, "/chat/completions", json=payload, timeout=300)
    return _clean(r.json()["choices"][0]["message"]["content"])

# ── media steps ────────────────────────────────────────────────────────────────

async def tts_segment(client: httpx.AsyncClient, text: str, voice: str,
                      out: Path, sem: asyncio.Semaphore) -> float:
    async with sem:
        r = await _post(client, "/audio/speech",
                        json={"model": config.TTS_MODEL, "input": text,
                              "voice": voice, "response_format": "mp3", "speed": 1.15},
                        timeout=300)
        out.write_bytes(r.content)
        dur = float(r.headers.get("X-Audio-Seconds", 0))
        if dur <= 0:
            dur = len(r.content) / 16000  # ~128kbps fallback
        return max(dur, 1.0)

async def image_segment(client: httpx.AsyncClient, prompt: str,
                        out: Path, sem: asyncio.Semaphore, seed: int | None = None) -> None:
    body = {"model": config.IMAGE_MODEL, "prompt": prompt, "width": 1280, "height": 720,
            "response_format": "b64_json", "quality": "standard", "n": 1}
    if seed is not None:
        body["seed"] = seed
    async with sem:
        r = await _post(client, "/images/generations", json=body, timeout=300)
        b64 = r.json()["data"][0]["b64_json"]
        out.write_bytes(base64.b64decode(b64))

def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())

async def inspect_image(client: httpx.AsyncClient, path: Path) -> dict:
    """Vision QA via the gateway's multimodal model: what text is readable, is there a close-up face."""
    b64 = base64.b64encode(path.read_bytes()).decode()
    r = await _post(client, "/chat/completions", timeout=300, json={
        "model": config.VISION_MODEL, "preset": "no-think-json", "temperature": 0, "max_tokens": 200,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": 'Look at this illustration. Reply ONLY with JSON: {"text": "<all readable text exactly '
                                     'as written, letter by letter, or empty string>", "closeup_face": true or false '
                                     '(true only if a human face fills a large part of the image)}'},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}}]}]})
    try:
        return content.extract_json(r.json()["choices"][0]["message"]["content"])
    except Exception:
        return {}

# ── job persistence (jobs survive server restarts / auto-deploys) ──────────────

def _save_meta(job_id: str) -> None:
    job = _jobs[job_id]
    keep = {k: job.get(k) for k in ("status", "created_at", "topic", "title", "description", "output", "stats")}
    (JOBS_DIR / job_id).mkdir(exist_ok=True)
    (JOBS_DIR / job_id / "meta.json").write_text(json.dumps(keep, ensure_ascii=False), encoding="utf-8")

def _load_jobs() -> None:
    for d in sorted(JOBS_DIR.iterdir()):
        mf = d / "meta.json"
        if not d.is_dir() or not mf.exists():
            continue
        try:
            m = json.loads(mf.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if m.get("status") in ("queued", "running"):
            m["status"] = "error"           # server restarted mid-job
        m["log"] = [json.dumps({"type": "info", "message": f"Job {d.name} restored from disk ({m['status']})"})]
        _jobs[d.name] = m

# ── main pipeline ──────────────────────────────────────────────────────────────

async def run_pipeline(job_id: str, topic: str, n_segments: int,
                       style: str, voice: str, camera: str):
    job = _jobs[job_id]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(exist_ok=True)
    log: list[str] = job["log"]

    def emit(msg: str, type_: str = "info", **extra):
        entry = {"type": type_, "message": _clean(msg)}
        entry.update(extra)
        log.append(json.dumps(entry, ensure_ascii=False))

    try:
        job["status"] = "running"
        _save_meta(job_id)
        async with httpx.AsyncClient() as client:
            async def chat(messages, **kw):
                return await _chat(client, messages, **kw)

            async def chat_prompt(prompt: str):
                return await chat([{"role": "user", "content": prompt}], max_tokens=2000, temperature=0.2)

            # 1) research, then question the story and research the answers
            emit("🔍 Researching topic via web search...")
            notes = await content.research(chat, topic)
            emit("✓ Research complete", "success")

            emit("🧐 Dissecting the story: finding the contrarian angle and the questions listeners will ask...")
            angles = await content.find_angles(chat, notes)
            emit(f"✓ Contrarian take: {angles.get('contrarian_take', '-')[:160]}", "success")
            emit("Research angles ready", "research_result",
                 topic=topic or "today's news",
                 core_claim=angles.get("core_claim", ""),
                 contrarian_take=angles.get("contrarian_take", ""),
                 questions=angles.get("questions", [])[:4])
            deep = await content.deep_research(chat, topic, angles)
            emit(f"✓ Researched {len(angles.get('questions', []))} follow-up questions", "success")

            # 2) persona script (first person, Hinglish)
            emit(f"✍️ Writing first-person Hinglish script ({n_segments} segments)...")
            script = await content.make_script(chat, notes, angles, deep, n_segments, topic)
            segs = script["segments"]
            n = len(segs)

            # Extract [pause:Xs] markers before purge_english so they aren't mangled
            for sg in segs:
                raw_parts = _PAUSE_RE.split(sg["narration"])
                texts = [raw_parts[k].strip() for k in range(0, len(raw_parts), 2) if raw_parts[k].strip()]
                pdurs = []
                for k in range(1, len(raw_parts), 2):
                    try:
                        pdurs.append(float(raw_parts[k]))
                    except ValueError:
                        pdurs.append(0.8)
                sg["narration_parts"] = texts or [sg["narration"]]
                sg["pause_durs"] = pdurs[:max(0, len(sg["narration_parts"]) - 1)]

            # Clean each part: no full English sentences (Hindi voice mangles them)
            for sg in segs:
                cleaned = []
                for part in sg["narration_parts"]:
                    cleaned.append(await content.purge_english(chat, part))
                sg["narration_parts"] = cleaned
                sg["narration"] = " ".join(cleaned)

            emit(f"✓ Script: \"{script.get('title', '')}\" ({n} segments)", "success")
            emit("Script ready", "script_result",
                 title=script.get("title", ""),
                 description=script.get("description", ""),
                 segments=[{"role": sg.get("role", ""), "preview": sg["narration"][:120]}
                           for sg in segs])

            # 3) + 4) Pronunciation prep (per-part) + voice generation with inline pauses
            emit("🔤 Preparing pronunciation + generating voice...")
            audio_parts: list[list[Path]] = [[] for _ in range(n)]
            durations = [0.0] * n
            sem = asyncio.Semaphore(config.MAX_CONCURRENCY)

            async def narrate(i: int, seg: dict):
                parts = seg.get("narration_parts", [seg["narration"]])
                pdurs = seg.get("pause_durs", [])
                label = f"Segment {i+1}/{n}"
                emit(f"🎙 {label}: TTS ({len(parts)} part{'s' if len(parts)>1 else ''})...")
                files, total = [], 0.0
                for k, part_text in enumerate(parts):
                    spoken = await speech.to_speech(chat_prompt, part_text)
                    p = job_dir / f"audio_{i:03d}_{k:02d}.mp3"
                    dur = await tts_segment(client, spoken, voice, p, sem)
                    files.append(p)
                    total += dur
                    if k < len(pdurs) and pdurs[k] > 0:
                        sil = job_dir / f"silence_{i:03d}_{k:02d}.mp3"
                        await asyncio.to_thread(_make_silence, sil, pdurs[k])
                        files.append(sil)
                        total += pdurs[k]
                audio_parts[i] = files
                durations[i] = max(total, 1.0)
                emit(f"✓ {label} voice ready ({total:.1f}s, {len(files)} clips)", "success")

            await asyncio.gather(*[narrate(i, seg) for i, seg in enumerate(segs)])
            audio_paths_flat = [p for parts in audio_parts for p in parts]

            # 5) scene plan: split each segment into beats (2-5s), design one explanatory visual per beat
            rng = random.Random(job_id)
            style = style if style in art.STYLES else art.DEFAULT_STYLE
            palettes = art.segment_palettes([str(sg.get("emotion", "")) for sg in segs], rng)
            mem = scenes_mod.Memory()
            shot_plan: list[dict] = []
            for i, seg in enumerate(segs):
                k = content.choose_shot_count(durations[i])
                beats = content.split_beats(seg["narration"], k)
                bdur = content.beat_durations(beats, durations[i])
                emit(f"🎞 Segment {i+1}/{n}: planning {len(beats)} scenes...")
                scenes = await scenes_mod.plan_scenes(chat, topic or script.get("title", ""), seg.get("role", ""), beats, mem)
                seg["palette"] = palettes[i]
                seg["scenes"] = [{"beat": b, "dur": round(d, 2), **sc} for b, d, sc in zip(beats, bdur, scenes)]
                shot_plan += [{"scene": sc, "dur": d, "seg": i, "palette": palettes[i]} for sc, d in zip(scenes, bdur)]
            script["total_seconds"] = round(sum(durations), 1)
            with open(job_dir / "script.json", "w", encoding="utf-8") as _f:
                json.dump(script, _f, ensure_ascii=False, indent=2)
            emit(f"✓ Scene plan saved: {len(shot_plan)} scenes, "
                 f"{sum(1 for s in shot_plan if s['scene'].get('text'))} with on-image text", "success")

            # 6) images, one per scene
            total = len(shot_plan)
            emit(f"🖼 Generating {total} images ({style})...")
            for j, s in enumerate(shot_plan):
                s["image"] = job_dir / f"shot_{j:03d}.png"
                s["prompt"] = art.compose(s["scene"], style, s["palette"], rng)
                try:
                    await image_segment(client, s["prompt"], s["image"], sem)
                except Exception as e:
                    if j == 0:
                        raise
                    emit(f"⚠ Scene {j+1} image failed ({type(e).__name__}); reusing previous", "error")
                    s["image"] = shot_plan[j - 1]["image"]
                if (j + 1) % 4 == 0 or j + 1 == total:
                    emit(f"⟳ Images {j+1}/{total}")

            # 6b) vision QA: misspelled on-image text and close-up faces get regenerated with a new seed
            emit("🔎 Checking images (text spelling, faces)...")
            fixed = 0
            for j, s in enumerate(shot_plan):
                if j and s["image"] == shot_plan[j - 1]["image"]:
                    continue
                want = s["scene"].get("text", "")
                for attempt in range(3):
                    try:
                        info = await inspect_image(client, s["image"])
                    except Exception:
                        break                                   # QA unavailable: keep the image
                    bad_text = _norm(info.get("text", "")) != _norm(want) and (want or len(_norm(info.get("text", ""))) > 3)
                    bad_face = bool(info.get("closeup_face"))
                    if not (bad_text or bad_face):
                        break
                    if attempt == 2:
                        if bad_text and want:                   # give up on the text: redraw without it
                            s["scene"]["text"] = ""
                            s["prompt"] = art.compose(s["scene"], style, s["palette"], rng)
                            await image_segment(client, s["prompt"], s["image"], sem, rng.randrange(2**31))
                        break
                    fixed += 1
                    await image_segment(client, s["prompt"], s["image"], sem, rng.randrange(2**31))
            emit(f"✓ Image check done ({fixed} regenerated)", "success")

            (job_dir / "image_prompts.json").write_text(
                json.dumps([{"shot": j, "palette": s["palette"], "prompt": s["prompt"]} for j, s in enumerate(shot_plan)],
                           ensure_ascii=False, indent=2), encoding="utf-8")
            emit(f"🎬 Assembling {total} scenes (camera: {camera}, crossfades) with FFmpeg...")
            output = job_dir / "output.mp4"
            stats = await asyncio.to_thread(video.assemble, job_dir, audio_paths_flat, shot_plan,
                                            output, camera, job_id)

            size_mb = output.stat().st_size // 1024 // 1024
            job.update(status="done", output=str(output), title=script["title"],
                       description=script.get("description", ""), stats=stats)
            _save_meta(job_id)
            emit(f"✅ Done! {size_mb}MB, {stats['seconds']}s, {stats['shots']} scenes — ready to download", "done")

    except UnicodeEncodeError as ue:
        job["status"] = "error"
        ctx = ascii(ue.object[max(0, ue.start - 5):ue.end + 5])
        emit(f"❌ UnicodeEncodeError: codec={ue.encoding!r} pos={ue.start}-{ue.end} context={ctx}", "error")
        for line in traceback.format_exc().splitlines():
            emit(f"  {line}", "error")
    except Exception as e:
        job["status"] = "error"
        emit(f"❌ {type(e).__name__}: {e}", "error")
        for line in traceback.format_exc().splitlines():
            emit(f"  {line}", "error")
    finally:
        _save_meta(job_id)

# ── routes ─────────────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    topic: str = ""
    segments: int = config.DEFAULT_SEGMENTS
    style: str = config.DEFAULT_STYLE
    voice: str = config.DEFAULT_VOICE
    camera: str = config.DEFAULT_CAMERA

@app.on_event("startup")
async def startup():
    _load_jobs()
    try:
        subprocess.run([config.FFMPEG, "-version"], capture_output=True, check=True)
        print(f"FFmpeg OK: {config.FFMPEG}")
    except FileNotFoundError:
        print(f"WARNING: ffmpeg not found at {config.FFMPEG} — video assembly will fail")
    if not config.API_KEY:
        print("WARNING: TRIPFICK_API_KEY not set")
    print(f"Login: user '{config.APP_USER}', password in .env (APP_PASSWORD)")

@app.get("/")
async def root():
    return FileResponse(Path(__file__).with_name("static") / "index.html")

@app.post("/generate")
async def generate(req: GenerateRequest, bg: BackgroundTasks):
    job_id = uuid.uuid4().hex[:8]
    _jobs[job_id] = {
        "status": "queued",
        "log": [json.dumps({"type": "info", "message": "⟳ Job {} queued — topic: {}".format(job_id, req.topic or "today's news")})],
        "created_at": datetime.now().isoformat(),
        "topic": req.topic or "today's news",
    }
    bg.add_task(run_pipeline, job_id, req.topic, req.segments, req.style, req.voice, req.camera)
    return {"job_id": job_id}

@app.get("/status/{job_id}")
async def status_stream(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(404, "Job not found")

    async def gen():
        log = _jobs[job_id]["log"]
        idx = 0
        while True:
            while idx < len(log):
                yield f"data: {log[idx]}\n\n"
                idx += 1
            status = _jobs[job_id]["status"]
            if status in ("done", "error") and idx >= len(log):
                yield f"data: {json.dumps({'type': 'done', 'status': status, 'job_id': job_id})}\n\n"
                break
            await asyncio.sleep(0.3)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})

@app.get("/video/{job_id}")
async def video_stream(job_id: str):
    job = _jobs.get(job_id)
    if not job or job["status"] != "done":
        raise HTTPException(404)
    return FileResponse(Path(job["output"]), media_type="video/mp4")

@app.get("/download/{job_id}")
async def download(job_id: str):
    job = _jobs.get(job_id)
    if not job or job["status"] != "done":
        raise HTTPException(404)
    path = Path(job["output"])
    safe = re.sub(r'[^\w\s-]', '', job.get("title", "podcast"))[:50].strip() or "podcast"
    return FileResponse(path, media_type="video/mp4", filename=f"{safe}.mp4")

@app.get("/jobs")
async def list_jobs():
    return [{"id": k, "status": v["status"], "topic": v.get("topic"),
             "title": v.get("title"), "created_at": v["created_at"]}
            for k, v in _jobs.items()]

@app.get("/health")
async def health():
    return {
        "started_at": _STARTED_AT.isoformat(),
        "uptime_s": (datetime.now() - _STARTED_AT).total_seconds(),
        "commit": _GIT["commit"],
        "subject": _GIT["subject"],
    }


@app.get("/internal/busy")
async def internal_busy():
    """For watch.py (auto-deploy): true while a job is queued or running."""
    return {"busy": any(j["status"] in ("queued", "running") for j in _jobs.values())}

@app.get("/options")
async def options():
    return {"cameras": ["auto", *video.MOVES], "transitions": video.TRANSITIONS,
            "styles": list(art.STYLES), "palettes": list(art.PALETTES)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.HOST, port=config.PORT)
