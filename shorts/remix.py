"""Pipeline E, remix: a video's motion (YouTube, Instagram or an uploaded file) performed by a character, made with `wan-2.2-animate-2`. The character is a library character (and
its look) or a picture the person uploads.

What it is and is not (docs: https://llm.tripfick.com/docs): the model copies the motion and expressions of a driving video onto the reference character; the prompt describes the
character and the background, so the result is the character from the picture, in a background from the picture and prompt, moving like the person in the video. It is not the
original scene with only the person swapped. The downloaded video is kept under data/ for the driving clip only; it is never part of an export and is never uploaded.

Steps: link -> download (yt-dlp) -> pick a 30-second window (the cut map shows where the cuts fall) -> re-encode the window small enough for the 25 MB request -> one Animate
request (or two 15-second ones) -> the common ending (shorts/stitch.py)."""
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import config
from characters import store as cstore, studio_edit
from story import settings as settings_mod
from story3 import store as media, video
from story3.voice import MediaError

from . import clips, frames, models, pipelines as P, stitch, store, wan

HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "instagram.com", "www.instagram.com", "instagr.am")
COOKIES = "cookies.txt"                            # optional, in data/: exported browser cookies for sites that ask for a login (Instagram often does); never uploaded or logged
WINDOW_S = 30.0
DRIVING_FPS = 16                                   # 30 s of 16 fps is 480 frames, inside the model's 481 cap
DRIVING_SIZE = models.SIZE_PORTRAIT
DRIVING_LIMIT = 10 * 1024 * 1024                   # raw bytes; base64 makes it a third bigger, and the whole request may be 25 MB
MAX_SOURCE_S = 3 * 3600
ANALYSE_S = 900                                    # the cut map and the window suggestions read at most this much of the video
KEEP_AUDIO = ("none", "original", "voiceover")
DEFAULT = {"url": "", "info": {}, "source": "", "start": 0.0, "fit": "crop", "cuts": [], "suggest": [], "driving": [], "segments": 1, "audio": "none", "script": "", "prompt": "",
           "motion_prompt": "", "pose_strength": 1.0, "rights_video": False, "rights_character": False, "length": WINDOW_S, "character_id": "", "look_id": ""}


def data(short: dict) -> dict:
    return {**DEFAULT, **(short.get("remix") or {})}


def check_url(url: str) -> str:
    u = urlsplit((url or "").strip())
    if u.scheme not in ("http", "https") or (u.hostname or "").lower() not in HOSTS:
        raise MediaError("paste a YouTube or Instagram link (youtube.com, youtu.be, instagram.com), or upload the video file")
    return u.geturl()


def _ytdlp(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    ff = str(Path(video.FFMPEG).parent) if Path(video.FFMPEG).is_file() else ""
    cookies = config.DATA_DIR / COOKIES
    cmd = [sys.executable, "-m", "yt_dlp", "--no-playlist", "--no-warnings", "--no-progress", *(["--ffmpeg-location", ff] if ff else []), *(["--cookies", str(cookies)] if cookies.is_file() else []), *args]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        if "No module named" in err and "yt_dlp" in err:
            raise MediaError("yt-dlp is not installed: run .venv\\Scripts\\python.exe -m pip install -r requirements.txt, then restart the app")
        last = err.splitlines()[-1] if err else str(r.returncode)
        login = " Instagram often needs a login: export your browser cookies to data/cookies.txt (Netscape format) and try again." if "instagram" in err.lower() and any(w in err.lower() for w in ("login", "cookies", "rate-limit", "empty media")) else ""
        raise MediaError(f"the video could not be fetched: {last[:240]}.{login} You can also upload the video file instead")
    return r


def fetch_info(url: str) -> dict:
    r = _ytdlp(["--dump-single-json", "--skip-download", url], 90)
    try:
        j = json.loads(r.stdout)
    except ValueError as e:
        raise MediaError("the link answered with something that is not a video") from e
    dur = float(j.get("duration") or 0)
    if j.get("is_live") or dur <= 0:
        raise MediaError("a live stream or a video without a length cannot be used")
    if dur > MAX_SOURCE_S:
        raise MediaError(f"the video is {dur / 3600:.1f} hours long; use one under {MAX_SOURCE_S // 3600} hours")
    return {"title": str(j.get("title") or "")[:120], "duration_s": dur, "id": str(j.get("id") or "")}


def download(url: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("source.*"):
        old.unlink(missing_ok=True)
    _ytdlp(["-f", "bv*[height<=720]+ba/b[height<=720]/b", "--merge-output-format", "mp4", "--max-filesize", "400M", "-o", str(out_dir / "source.%(ext)s"), url], 1800)
    files = sorted(out_dir.glob("source.*"))
    if not files:
        raise MediaError("the download finished without a file")
    return files[0]


def suggest_windows(cuts: list[float], duration: float, length: float = WINDOW_S, top: int = 3) -> list[dict]:
    """The start times whose window has the most cuts and the fewest stretches over three seconds: where the source video is already fast."""
    best = []
    t = 0.0
    limit = min(duration, ANALYSE_S) - length
    while t <= limit:
        inside = [c - t for c in cuts if t < c < t + length]
        slow = frames.long_stretches(inside, length)
        best.append({"start": round(t, 1), "cuts": len(inside), "slow_s": round(sum(b - a for a, b in slow), 1)})
        t += 5.0
    best.sort(key=lambda w: (w["slow_s"], -w["cuts"]))
    out: list[dict] = []
    for w in best:
        if all(abs(w["start"] - o["start"]) >= length for o in out):
            out.append(w)
        if len(out) == top:
            break
    return out


def fetch(short_id: str, url: str, progress=None) -> dict:
    """Download the video and read it: its length, the cut map and the best windows. Blocking (run in a thread)."""
    url = check_url(url)
    if progress:
        progress(0, 3, "reading the link")
    info = fetch_info(url)
    if info["duration_s"] < WINDOW_S:
        raise MediaError(f"the video is {info['duration_s']:.0f} seconds long; a short needs at least {WINDOW_S:.0f}")
    if progress:
        progress(1, 3, "downloading the video")
    src = download(url, store.media_dir(short_id, "remix"))
    if progress:
        progress(2, 3, "finding the cuts")
    cuts = frames.scene_cuts(src, limit_s=ANALYSE_S)
    short = store.get(short_id)
    r = data(short)
    r.update(url=url, info=info, source=f"remix/{src.name}", cuts=cuts, suggest=suggest_windows(cuts, info["duration_s"]), start=0.0, driving=[])
    short["remix"] = r
    store.save(short)
    if progress:
        progress(3, 3, "done")
    return r


# ── the driving clip ─────────────────────────────────────────────────────────

def _encode(src: Path, start: float, length: float, fit: str, out: Path) -> int:
    w, h = models.size_of(DRIVING_SIZE)
    scale = (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}" if fit == "crop"
             else f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black")
    for crf in (24, 28, 32, 36):
        frames.run(["-ss", f"{start:.2f}", "-t", f"{length:.2f}", "-i", str(src), "-vf", f"fps={DRIVING_FPS},{scale},setsar=1", "-an", "-c:v", "libx264", "-preset", "fast", "-crf", str(crf),
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)])
        if out.stat().st_size <= DRIVING_LIMIT:
            return crf
    raise MediaError("the driving clip is too big for the request even at low quality; pick a window with less motion or detail")


def prepare(short_id: str, start: float, fit: str = "crop", segments: int = 1) -> dict:
    """Cut the chosen window out of the downloaded video and encode it for the model: 9:16, 16 fps, no sound, small. One clip, or two of 15 seconds."""
    short = store.get(short_id)
    r = data(short)
    if not r["source"]:
        raise MediaError("fetch the video first")
    if fit not in ("crop", "pad") or segments not in (1, 2):
        raise MediaError("fit is crop or pad; segments is 1 or 2")
    dur = float(r["info"]["duration_s"])
    start = max(0.0, min(float(start), dur - WINDOW_S))
    src = store.media_dir(short_id) / r["source"]
    d = store.media_dir(short_id, "remix")
    seg_len = WINDOW_S / segments
    paths = []
    for i in range(segments):
        out = d / f"driving{i + 1}.mp4"
        _encode(src, start + i * seg_len, seg_len, fit, out)
        paths.append(f"remix/{out.name}")
    cuts = [round(c - start, 2) for c in r["cuts"] if start < c < start + WINDOW_S]
    r.update(start=round(start, 2), fit=fit, segments=segments, driving=paths, window_cuts=cuts, slow=frames.long_stretches(cuts, WINDOW_S))
    short["remix"] = r
    return store.save(short)


# ── the character ────────────────────────────────────────────────────────────

def character(short: dict) -> dict | None:
    """The library character chosen for this remix (with its picture), or None when the person uploaded a picture instead."""
    r = data(short)
    if not r.get("character_id"):
        return None
    try:
        c = cstore.get(r["character_id"])
    except cstore.CharError:
        return {"char": None, "path": None, "label": "", "version": 0}
    it = studio_edit.look_item(c, r["look_id"]) if r.get("look_id") else None
    it = it or cstore.canon_items(c).get("body") or cstore.canon_items(c).get("portrait")
    look = next((x["name"] for x in c["looks"] if x["id"] == r.get("look_id")), "")
    return {"char": c, "path": media.path_of(it) if it else None, "label": c["name"] + (f" ({look})" if look else ""), "version": c["version"]}


def picture(short: dict) -> Path | None:
    ch = character(short)
    if ch is not None:
        return ch["path"]
    return store.image_path(short, short["images"].get("anchor", ""))


# ── the request ──────────────────────────────────────────────────────────────

def request(short: dict, n: int, attempt: int = 1) -> dict:
    r = data(short)
    image = picture(short)
    drive = store.image_path(short, r["driving"][n]) if n < len(r["driving"]) else None
    if not image:
        raise MediaError("choose a character from the library, or upload the picture of your character first")
    if not drive:
        raise MediaError("choose the window of the video first")
    seg_len = WINDOW_S / max(1, r["segments"])
    body = {"model": models.ANIMATE, "image": wan.data_url(frames.crop_916(image.read_bytes(), DRIVING_SIZE), "image/jpeg"), "driving_video": wan.data_url(drive.read_bytes(), "video/mp4"),
            "prompt": r["prompt"].strip(), "size": DRIVING_SIZE, "fps": DRIVING_FPS, "duration": seg_len, "steps": int(short["settings"].get("steps") or P.DEFAULT_STEPS[models.ANIMATE]),
            "pose_strength": float(r["pose_strength"]), "keep_audio": r["audio"] == "original", "seed": (int(short["settings"].get("seed", 7)) + 101 * (attempt - 1) + 17 * n) % (2 ** 32),
            "response_format": "mp4"}
    if r.get("motion_prompt"):
        body["motion_prompt"] = r["motion_prompt"].strip()
    return body


def input_hash(short: dict, n: int) -> str:
    r = data(short)
    image = picture(short)
    drive = store.image_path(short, r["driving"][n]) if n < len(r["driving"]) else None
    ch = character(short)
    return store.input_hash("remix", r["prompt"], r["motion_prompt"], r["pose_strength"], r["audio"] == "original", clips._fingerprint(image) if image else "", clips._fingerprint(drive) if drive else "",
                            [r["character_id"], r["look_id"], ch["version"]] if ch else "")


def estimate_s(short: dict) -> int:
    r = data(short)
    return int(P.request_seconds(models.ANIMATE, int(WINDOW_S * DRIVING_FPS)) + (OVERHEAD_EXTRA if r["segments"] == 2 else 0))


OVERHEAD_EXTRA = 40


def check(short: dict) -> dict:
    """The problems that stop a remix, in plain words."""
    r = data(short)
    issues = []

    def add(level, code, text):
        issues.append({"level": level, "code": code, "text": text})
    if not r["rights_video"]:
        add("block", "rights_video", "Confirm that you have the right to use the video.")
    ch = character(short)
    if ch is None and not r["rights_character"]:
        add("block", "rights_character", "Confirm that the picture is your own, an invented or a licensed character, not a private person.")
    if ch is not None and ch["char"] is None:
        add("block", "no_character", "The chosen character is not in the library any more; choose another.")
    elif ch is not None and not ch["path"]:
        add("block", "no_character", f"{ch['label']} has no approved full-body picture yet: approve one in the Characters studio.")
    elif ch is None and not picture(short):
        add("block", "no_character", "Choose a character from the library or upload the picture of your character.")
    if not r["source"]:
        add("block", "no_video", "Paste the YouTube or Instagram link and fetch the video, or upload a video file.")
    elif not r["driving"]:
        add("block", "no_window", "Choose the 30-second window of the video.")
    if not r["prompt"].strip():
        add("block", "no_prompt", "Describe the character and the background in a sentence or two (what they wear, where they are). The model reads this, not the video's scene.")
    if r["audio"] == "voiceover" and not r["script"].strip():
        add("block", "no_script", "Write the voice-over, or choose another sound option.")
    if r["audio"] == "voiceover" and len(r["script"].split()) > 80:
        add("block", "script_long", "The voice-over is over eighty words; it would not fit in 30 seconds.")
    if r.get("slow"):
        total = sum(b - a for a, b in r["slow"])
        add("warn", "slow", f"{len(r['slow'])} stretch(es) of this window, {total:.0f} seconds in all, have no cut for over {models.MAX_SHOT_S:g} seconds. The pace follows the source video; "
                            "another window may be faster (see the suggestions).")
    blockers = sum(1 for i in issues if i["level"] == "block")
    return {"ok": blockers == 0, "issues": issues, "blockers": blockers, "warnings": len(issues) - blockers}


# ── making it ────────────────────────────────────────────────────────────────

async def make(short_id: str, progress=None, s: dict | None = None, key: str = "") -> dict:
    base, api_key = clips._ctx(s, key)
    short = store.get(short_id)
    chk = check(short)
    if chk["blockers"]:
        raise MediaError(chk["issues"][0]["text"])
    r = data(short)
    made, failed = 0, []
    for n in range(r["segments"]):
        if progress:
            progress(n, r["segments"], f"animating part {n + 1} of {r['segments']} (about {estimate_s(short) // 60 // r['segments']} minutes)")
        h = input_hash(short, n)
        key_ = f"remix-{n + 1}"
        if store.chosen(short_id, store.CLIP, key_, h):
            continue
        try:
            done = await clips._adopt(short_id, store.CLIP, key_, base, api_key)
            if done:
                it, content, res = done["item"], done["data"], done["res"]
            else:
                attempt = len(media.items(short_id, store.CLIP, key_)) + 1
                it, content, res = await clips._request(short_id, store.CLIP, key_, request(short, n, attempt), h, base, api_key, {"part": n + 1}, limit_s=5400)
            clips._finish(short_id, it, content, res, "clip", key_, "mp4")
            made += 1
        except (wan.WanError, MediaError) as e:
            failed.append({"part": n + 1, "error": str(e)[:200]})
            if "not reachable" in str(e):
                break
    if progress:
        progress(r["segments"], r["segments"], "done")
    return {"made": made, "failed": failed}


def chosen_parts(short: dict) -> list[dict | None]:
    r = data(short)
    return [store.chosen(short["id"], store.CLIP, f"remix-{n + 1}", input_hash(short, n)) if n < len(r["driving"]) else None for n in range(r["segments"])]


def sentences_of(script: str) -> list[str]:
    import re
    return [t.strip() for t in re.split(r"(?<=[.!?।…])\s+", script.strip()) if t.strip()]


def sync_voiceover(short_id: str) -> dict:
    """The one beat that carries a voice-over script (or none), so the common voice code can speak it."""
    short = store.get(short_id)
    r = data(short)
    if r["audio"] == "voiceover" and r["script"].strip():
        short["beats"] = [{"id": "b1", "name": "Voice-over", "feeling": "", "tag": "", "sentences": [{"text": t, "tag": ""} for t in sentences_of(r["script"])], "shot_ids": []}]
    else:
        short["beats"] = []
    return store.save(short)


def build(short_id: str, progress=None) -> dict:
    """The finished remix: the parts as 30 fps 1080x1920, the chosen sound, captions for a voice-over."""
    from . import voice as svoice
    short = sync_voiceover(short_id)
    r = data(short)
    chk = check(short)
    if chk["blockers"]:
        raise MediaError(chk["issues"][0]["text"])
    parts = chosen_parts(short)
    if not all(parts):
        raise MediaError("animate the video first")
    voice_it = None
    if r["audio"] == "voiceover":
        voice_it = svoice.chosen(short, short["beats"][0])
        if not voice_it:
            raise MediaError("make the voice-over first")
    h = store.input_hash(stitch.VERSION, "remix", [p["id"] for p in parts], voice_it["id"] if voice_it else "", r["audio"], short["settings"].get("captions"), short["settings"].get("bed"))
    for it in media.items(short_id, store.FINAL, "final"):
        if it["status"] == "done" and it["meta"].get("input_hash") == h and it["file"]:
            return it
    it = media.add(short_id, store.FINAL, "final", 0, "running", {"input_hash": h})
    work = store.media_dir(short_id, f"work/{it['id']}")
    t0 = time.time()
    try:
        seg_len = WINDOW_S / len(parts)
        segs = []
        for i, p in enumerate(parts):
            if progress:
                progress(i, len(parts) + 1, f"cutting part {i + 1}")
            seg = work / f"seg{i}.mp4"
            stitch.encode_segment(media.path_of(p), seg, round(seg_len * models.OUT_FPS))
            segs.append(seg)
        silent = work / "silent.mp4"
        stitch.join_segments(segs, silent, work)
        t_s = float(short["settings"].get("target_s") or models.TARGET_S)
        voice_wav, bed_parts, ass = None, [{"duration_s": t_s}], None
        if voice_it:
            dur = float(voice_it["meta"]["duration_s"])
            tempo = min(1.12, max(1.0, dur / (t_s - 0.3)))
            voice_wav = work / "voice.wav"
            stitch.beat_audio(media.path_of(voice_it), tempo, t_s, voice_wav)
            if short["settings"].get("captions", True) and video.available()["captions"]:
                ass = work / "captions.ass"
                stitch.write_ass(stitch.caption_events([s["text"] for s in short["beats"][0]["sentences"]], 0.0, dur / tempo), ass)
        elif r["audio"] == "none":
            voice_wav = stitch.silence(work, t_s)                                      # the bed alone under the picture
        elif r["audio"] == "original":
            voice_wav = work / "original.wav"
            wavs = []
            for i, p in enumerate(parts):
                w = work / f"orig{i}.wav"
                frames.run(["-i", str(media.path_of(p)), "-vn", "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", "-af", f"apad=whole_dur={seg_len:.3f}", "-t", f"{seg_len:.3f}", str(w)])
                wavs.append(w)
            lst = work / "orig.txt"
            lst.write_text("".join(f"file '{w.name}'\n" for w in wavs), encoding="utf-8")
            frames.run(["-f", "concat", "-safe", "0", "-i", lst.name, "-c", "copy", str(voice_wav)], cwd=work)
        out = store.media_dir(short_id, "final") / f"short-a{it['attempt']}.mp4"
        notes = stitch.mix_and_mux(silent, voice_wav, bed_parts if r["audio"] != "original" else [], ass, out, work, short["settings"], t_s)
        info = frames.info(out)
        media.update(it["id"], status="done", file=f"final/{out.name}", meta={"input_hash": h, "duration_s": round(info["duration_s"], 2), "seconds_taken": round(time.time() - t0, 1), "audio": r["audio"], **notes})
    except Exception as e:  # noqa: BLE001
        media.update(it["id"], status="failed", meta={"error": str(e)[:300]})
        raise
    short = store.get(short_id)
    short["status"] = "made"
    store.save(short)
    if progress:
        progress(len(parts) + 1, len(parts) + 1, "done")
    return media.get(it["id"])


async def fetch_async(short_id: str, url: str, progress=None) -> dict:
    return await asyncio.to_thread(fetch, short_id, url, progress)
