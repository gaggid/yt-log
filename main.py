import asyncio
import base64
import json
import os
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

import config

JOBS_DIR = Path("jobs")
JOBS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Podcast Video Generator")

_jobs: dict[str, dict] = {}

# ── helpers ────────────────────────────────────────────────────────────────────

def _hdrs():
    return {"Authorization": f"Bearer {config.API_KEY}"}

def _clean(s: str) -> str:
    """Strip lone surrogates that json.dumps chokes on."""
    return s.encode("utf-8", errors="replace").decode("utf-8")

async def _chat(client: httpx.AsyncClient, messages: list, **kwargs) -> str:
    payload = {"model": config.CHAT_MODEL, "messages": messages, **kwargs}
    r = await client.post(f"{config.BASE_URL}/chat/completions",
                          json=payload, headers=_hdrs(), timeout=120)
    r.raise_for_status()
    return _clean(r.json()["choices"][0]["message"]["content"])

def _extract_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            return json.loads(m.group())
        raise ValueError(f"No JSON found in response: {text[:200]}")

# ── pipeline steps ─────────────────────────────────────────────────────────────

async def research(client: httpx.AsyncClient, topic: str) -> str:
    query = topic or "India top news stories today"
    return await _chat(client,
        [{"role": "user", "content": f"Research and summarize the latest news about: {query}. "
          "Find 6-8 key stories with facts, context, and quotes. Be thorough."}],
        server_tools=["web_search"], max_tokens=2500)

async def make_script(client: httpx.AsyncClient, research_text: str, n: int) -> dict:
    prompt = f"""You are a Hinglish podcast scriptwriter. Based on the research below, write a {n}-segment solo-host podcast script in Hinglish (natural mix of Hindi and English using ONLY Latin/Roman alphabet — no Devanagari script).

Research:
{research_text}

Return ONLY valid JSON (no markdown, no explanation):
{{
  "title": "Episode title in Hinglish (Roman script only)",
  "description": "One line English description for YouTube",
  "segments": [
    {{
      "id": 1,
      "narration": "Hinglish narration in Roman script, 3-5 conversational sentences, podcast tone. Example: 'Aaj ki sabse badi khabar yeh hai ki...'",
      "image_prompt": "Detailed English cinematic image description for this topic segment. Include mood, setting, visual style.",
      "emotion": "calm"
    }}
  ]
}}

emotion values: calm | excited | serious | dramatic | concerned | amused
Exactly {n} segments. IMPORTANT: Use only Roman/Latin alphabet in title and narration — no Devanagari. Return only JSON."""

    content = await _chat(client,
        [{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}, max_tokens=5000)
    return _extract_json(content)

async def tts_segment(client: httpx.AsyncClient, text: str, voice: str,
                      out: Path, sem: asyncio.Semaphore) -> float:
    async with sem:
        r = await client.post(f"{config.BASE_URL}/audio/speech",
                              json={"model": config.TTS_MODEL, "input": text,
                                    "voice": voice, "response_format": "mp3"},
                              headers=_hdrs(), timeout=180)
        r.raise_for_status()
        out.write_bytes(r.content)
        dur = float(r.headers.get("X-Audio-Seconds", 0))
        if dur <= 0:
            dur = len(r.content) / 16000  # ~128kbps fallback
        return max(dur, 1.0)

async def image_segment(client: httpx.AsyncClient, prompt: str, style: str,
                        out: Path, sem: asyncio.Semaphore) -> None:
    async with sem:
        r = await client.post(f"{config.BASE_URL}/images/generations",
                              json={"model": config.IMAGE_MODEL,
                                    "prompt": prompt, "width": 1280, "height": 720,
                                    "style": style, "response_format": "b64_json",
                                    "quality": "standard", "n": 1},
                              headers=_hdrs(), timeout=300)
        r.raise_for_status()
        b64 = r.json()["data"][0]["b64_json"]
        out.write_bytes(base64.b64decode(b64))

def ffmpeg_assemble(job_dir: Path, audio_paths: list, image_paths: list,
                    durations: list, output: Path) -> None:
    # Concat audio
    ac = job_dir / "audio_list.txt"
    ac.write_text("\n".join(f"file '{p.resolve()}'" for p in audio_paths), encoding="utf-8")
    full_audio = job_dir / "audio.mp3"
    subprocess.run(
        [config.FFMPEG, "-y", "-f", "concat", "-safe", "0",
         "-i", str(ac), "-c", "copy", str(full_audio)],
        check=True, capture_output=True
    )

    # Video concat: each image held for audio duration
    vc = job_dir / "video_list.txt"
    lines = []
    for img, dur in zip(image_paths, durations):
        lines += [f"file '{img.resolve()}'", f"duration {dur:.3f}"]
    lines.append(f"file '{image_paths[-1].resolve()}'")  # FFmpeg requires last entry
    vc.write_text("\n".join(lines), encoding="utf-8")

    subprocess.run([
        config.FFMPEG, "-y",
        "-f", "concat", "-safe", "0", "-i", str(vc),
        "-i", str(full_audio),
        "-vf", "scale=2560:1440:flags=lanczos,format=yuv420p",
        "-c:v", "libx264", "-preset", "slow", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-r", "30", "-shortest",
        str(output)
    ], check=True, capture_output=True)

# ── main pipeline ──────────────────────────────────────────────────────────────

async def run_pipeline(job_id: str, topic: str, n_segments: int,
                       style: str, voice: str):
    job = _jobs[job_id]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir()
    log: list[str] = job["log"]

    def emit(msg: str, type_: str = "info"):
        log.append(json.dumps({"type": type_, "message": _clean(msg)}))

    try:
        job["status"] = "running"
        async with httpx.AsyncClient() as client:

            emit("🔍 Researching topic via web search...")
            news = await research(client, topic)
            emit("✓ Research complete", "success")

            emit(f"✍️ Generating Hinglish podcast script ({n_segments} segments)...")
            script = await make_script(client, news, n_segments)
            with open(job_dir / "script.json", "w", encoding="utf-8") as _f:
                json.dump(script, _f, ensure_ascii=False, indent=2)
            segs = script["segments"]
            n = len(segs)
            emit(f"✓ Script: \"{script.get('title', '')}\" ({n} segments)", "success")

            audio_paths = [job_dir / f"audio_{i:03d}.mp3" for i in range(n)]
            image_paths = [job_dir / f"image_{i:03d}.png" for i in range(n)]
            durations = [0.0] * n
            sem = asyncio.Semaphore(config.MAX_CONCURRENCY)

            # Sequential because MAX_CONCURRENCY=1; gather still works correctly
            async def process(i: int, seg: dict):
                emit(f"⟳ Segment {i+1}/{n}: generating audio...")
                dur = await tts_segment(client, seg["narration"], voice,
                                        audio_paths[i], sem)
                durations[i] = dur
                emit(f"⟳ Segment {i+1}/{n}: generating image...")
                await image_segment(client, seg["image_prompt"], style,
                                    image_paths[i], sem)
                emit(f"✓ Segment {i+1}/{n} done ({dur:.1f}s)", "success")

            await asyncio.gather(*[process(i, seg) for i, seg in enumerate(segs)])

            emit("🎬 Assembling 2K video with FFmpeg...")
            output = job_dir / "output.mp4"
            await asyncio.to_thread(ffmpeg_assemble, job_dir, audio_paths,
                                    image_paths, durations, output)

            size_mb = output.stat().st_size // 1024 // 1024
            job["status"] = "done"
            job["output"] = str(output)
            job["title"] = script["title"]
            job["description"] = script.get("description", "")
            emit(f"✅ Done! {size_mb}MB — ready to download", "done")

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

# ── routes ─────────────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    topic: str = ""
    segments: int = config.DEFAULT_SEGMENTS
    style: str = config.DEFAULT_STYLE
    voice: str = config.DEFAULT_VOICE

@app.on_event("startup")
async def startup():
    try:
        subprocess.run([config.FFMPEG, "-version"], capture_output=True, check=True)
        print(f"FFmpeg OK: {config.FFMPEG}")
    except FileNotFoundError:
        print(f"WARNING: ffmpeg not found at {config.FFMPEG} — video assembly will fail")
    if not config.API_KEY:
        print("WARNING: TRIPFICK_API_KEY not set")

@app.get("/")
async def root():
    return FileResponse("static/index.html")

@app.post("/generate")
async def generate(req: GenerateRequest, bg: BackgroundTasks):
    job_id = uuid.uuid4().hex[:8]
    _jobs[job_id] = {
        "status": "queued",
        "log": [json.dumps({"type": "info", "message": "⟳ Job {} queued — topic: {}".format(job_id, req.topic or "today's news")})],
        "created_at": datetime.now().isoformat(),
        "topic": req.topic or "today's news",
    }
    bg.add_task(run_pipeline, job_id, req.topic, req.segments, req.style, req.voice)
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
    safe = re.sub(r'[^\w\s-]', '', job.get("title", "podcast"))[:50].strip()
    return FileResponse(path, media_type="video/mp4", filename=f"{safe}.mp4")

@app.get("/jobs")
async def list_jobs():
    return [{"id": k, "status": v["status"], "topic": v.get("topic"),
             "title": v.get("title"), "created_at": v["created_at"]}
            for k, v in _jobs.items()]
