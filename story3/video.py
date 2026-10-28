"""Batch I: assembly. Builds a watchable 1080p H.264 + AAC draft (or a small preview) from what is already made: the approved picture or graphic of
every scene, held for exactly the scene's duration with a slow zoom or pan, over the approved (else latest valid) voice of every part, with optional
burned-in Hinglish captions. A missing picture or audio is never skipped silently: it is listed in the checklist, and only "build anyway" draws a
labelled placeholder (or silence) for it. ffmpeg does all the media work; nothing here calls a model."""
import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from PIL import Image, ImageDraw

from story import db
from story2 import planner, storyboard, store as plan_store
from story2.scene_schemas import NEEDS_ASSET

from . import clips as clips_mod, graphics, scenes, store
from .voice import MediaError

KIND = "video"


def _tool(name: str) -> str:
    """The real executable: the known install first, then the PATH (a bare name on the PATH can be a script that Windows cannot start)."""
    known = Path(r"C:\Ffmpeg\bin") / f"{name}.exe"
    return str(known) if known.is_file() else (shutil.which(name) or str(known))


FFMPEG = _tool("ffmpeg")
FONTS_DIR = "C:/Windows/Fonts"
CAPTION_FONT = "Nirmala UI"
PROFILES = {
    "draft": {"label": "Draft (1080p)", "size": (1920, 1080), "fps": 30, "crf": 21, "preset": "veryfast", "abr": "192k", "speed": 0.6},
    "preview": {"label": "Preview (small, fast)", "size": (640, 360), "fps": 15, "crf": 30, "preset": "veryfast", "abr": "64k", "speed": 0.15},
}
MOVES = ["zoom_in", "pan_right", "zoom_out", "pan_left", "drift", "pan_up", "pan_down"]          # "settle" (a director's hold) and "hold" (cards) are not in the rotation
PLAYBACK_SPEED = 1.25                         # the finished video (picture, voice and captions together) is sped up this much; 1 leaves it as made
ZOOM = 0.22                                   # a push in or pull back travels from 1.0 to 1.22 times
PAN_ZOOM = 1.30                               # a pan or tilt is cropped to 1/1.3 of the picture and slides across the rest, so the scene is not shown all at once
SUPERSAMPLE = 3                               # the still is scaled up this many times before the move, so one step of the move is a whole number of source pixels
DIRECTOR_MOVES = {"push in": "zoom_in", "pull back": "zoom_out", "pan right": "pan_right", "pan left": "pan_left", "tilt up": "pan_up", "tilt down": "pan_down",
                  "drift": "drift", "hold": "settle"}          # a held shot still breathes: a 5% push, so no scene is a frozen picture
KEYWORDS = [("zoom_in", r"push in|push-in|zoom in|slow in|move in|closer|creep"), ("zoom_out", r"pull back|pull out|pull-back|zoom out|widen|reveal"),
            ("pan_left", r"pan left|track left|drift left|move left"), ("pan_right", r"pan right|track right|drift right|move right"),
            ("pan_up", r"tilt up|pan up|rise|crane up"), ("pan_down", r"tilt down|pan down|crane down")]
DISSOLVE = re.compile(r"dissolve|cross-?fade|fade in|fade from", re.I)


def _run(cmd: list[str], cwd: Path | None = None) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise MediaError(f"ffmpeg stopped: {(r.stderr or r.stdout).strip().splitlines()[-1][:240] if (r.stderr or r.stdout).strip() else r.returncode}")
    return r.stderr


def available() -> dict:
    ok = bool(Path(FFMPEG).is_file() or shutil.which(FFMPEG))
    ass = False
    if ok:
        try:
            ass = " ass " in subprocess.run([FFMPEG, "-hide_banner", "-filters"], capture_output=True, text=True).stdout
        except OSError:
            ok = False
    return {"ffmpeg": ok, "captions": ass}


def media_info(path: Path) -> dict:
    """Length and streams of a file, read from `ffmpeg -i` (ffprobe is not needed, and the copy on this machine is an empty file)."""
    r = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    if not m:
        raise MediaError(f"could not read the length of {Path(path).name}")
    streams = []
    for ln in r.stderr.splitlines():
        s = re.search(r"Stream #\d+:\d+.*?: (Video|Audio): (\w+)(?:.*?, (\d+)x(\d+))?", ln)
        if s:
            streams.append({"type": s.group(1).lower(), "codec": s.group(2), "width": int(s.group(3) or 0), "height": int(s.group(4) or 0)})
    return {"duration_s": int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)), "streams": streams}


def probe_seconds(path: Path) -> float:
    return media_info(path)["duration_s"]


# ── what goes into the video ────────────────────────────────────────────────

def pick_moves(scene_list: list[dict]) -> list[str]:
    """The camera move of each scene: the director's, else one read from the scene's motion note, else the next in a rotation. Never the same move twice
    in a row, and no still frame unless the director asked for one. Cards (charts, documents) hold still."""
    out, prev, n = [], "", 0
    for sc in scene_list:
        d = sc["data"]
        if d.get("visual_type") in NEEDS_ASSET:
            out.append("hold")
            prev = "hold"
            continue
        want = DIRECTOR_MOVES.get(str((d.get("direction") or {}).get("move") or ""), "")
        if not want:
            text = f"{d.get('motion_intent') or ''}".lower()
            want = next((m for m, rx in KEYWORDS if re.search(rx, text)), "")
        if not want or (want == prev and want not in ("hold", "settle")):
            want = MOVES[n % len(MOVES)]
            while want == prev:
                n += 1
                want = MOVES[n % len(MOVES)]
            n += 1
        out.append(want)
        prev = want
    return out


def wants_dissolve(sc: dict) -> bool:
    d = sc["data"]
    return d.get("visual_type") == "transition" or bool(DISSOLVE.search(str(d.get("motion_intent") or "")))


def visual_choices(plan_id: str) -> dict[str, dict]:
    """Per scene: the file to show, where it came from, and what is wrong with it.
    Priority: approved graphic → approved motion clip → approved picture → best picture → nothing."""
    sst   = scenes.state(plan_id)
    gst   = graphics.state(plan_id)
    cl    = clips_mod.approved_clips(plan_id)      # scene_id -> approved clip row
    grows = {r["id"]: r for r in gst["scenes"]}
    out   = {}
    for r in sst["scenes"]:
        pick  = {"scene": r["id"], "path": None, "source": "", "problem": ""}
        g     = grows.get(r["id"])
        by_id = {c["id"]: c for c in r["candidates"]}
        # 1. approved graphic (chart / doc / map)
        if g:
            item = next((i for i in g["items"] if i["id"] == g["approved"]), None)
            if item:
                pick |= {"path": store.path_of(store.get(item["id"])), "source": "graphic", "item": item["id"]}
            elif g["current_item"] and not g.get("thin"):
                pick |= {"path": store.path_of(store.get(g["current_item"]["id"])), "source": "graphic", "item": g["current_item"]["id"], "problem": "graphic not approved"}
        # 2. approved motion clip
        if not pick["path"]:
            clit = cl.get(r["id"])
            if clit and clit.get("file") and store.path_of(clit).is_file():
                pick |= {"path": store.path_of(clit), "source": "clip", "item": clit["id"]}
        # 3. static picture (original logic unchanged)
        if not pick["path"]:
            ap   = by_id.get(r["approved"]) if r["approved"] else None
            good = [c for c in r["candidates"] if c["status"] == "done" and c["current"]]
            b    = by_id.get(r["best"]) if r["best"] else (good[-1] if good else None)
            if ap and ap["current"]:
                pick |= {"path": store.path_of(store.get(ap["id"])), "source": "picture", "item": ap["id"]}
            elif b:                                                    # a newer picture made after a reference or the scene changed wins over an older approved one
                pick |= {"path": store.path_of(store.get(b["id"])), "source": "picture", "item": b["id"], "problem": "picture not approved"}
            elif ap:                                                   # redoing a reference must not stop the video: the approved picture stays in until the scene is redrawn
                pick |= {"path": store.path_of(store.get(ap["id"])), "source": "picture", "item": ap["id"], "stale": True,
                         "problem": "approved picture was made before a reference or the scene changed: redraw this scene"}
            elif any(c["status"] == "done" for c in r["candidates"]):
                pick |= {"problem": "the only pictures are old (the scene or a reference changed)"}
            else:
                pick |= {"problem": "no picture yet"}
        out[r["id"]] = pick
    return out


def audio_choices(plan_id: str) -> list[dict]:
    plan = planner.get_plan(plan_id)
    voice = store.voice_key(plan)
    out = []
    for seg in plan["segments"]:
        it = store.chosen_voice(plan_id, seg, voice)
        out.append({"segment": seg["id"], "seq": seg["seq"], "duration_s": float(it["meta"]["duration_s"]) if it else float(seg["duration_s"]), "path": store.path_of(it) if it else None,
                    "item": it["id"] if it else None, "problem": "" if it and it["approved"] else "voice not approved" if it else "no voice yet"})
    return out


def checklist(plan_id: str) -> dict:
    sc_list = sorted(storyboard.get_scenes(plan_id), key=lambda x: (x["start_s"], x["seq"]))
    vis = visual_choices(plan_id)
    aud = audio_choices(plan_id)
    plan = planner.get_plan(plan_id)
    blockers, warnings = [], []
    if not sc_list:
        blockers.append({"kind": "scenes", "text": "there are no scenes: design the storyboard first"})
    for sc in sc_list:
        v = vis.get(sc["id"]) or {"problem": "no picture yet", "path": None}
        item = {"kind": "picture", "scene": sc["id"], "at": sc["start_s"], "text": v["problem"]}
        if not v["path"]:
            blockers.append(item)
        elif v["problem"]:
            warnings.append(item)
    for a in aud:
        item = {"kind": "voice", "segment": a["segment"], "text": a["problem"]}
        if not a["path"]:
            blockers.append(item)
        elif a["problem"]:
            warnings.append(item)
    plan_s = round(sum(s["duration_s"] for s in sc_list), 2)
    audio_s = round(sum(a["duration_s"] for a in aud), 2)
    return {"blockers": blockers, "warnings": warnings, "plan_s": plan_s, "audio_s": audio_s, "scenes": len(sc_list), "segments": len(aud),
            "length_gap_s": round(abs(plan_s - audio_s), 2), "visuals": vis, "audio": aud, "plan": plan}


# ── ffmpeg pieces ───────────────────────────────────────────────────────────

def zoompan(move: str, frames: int, w: int, h: int, fps: int) -> str:
    """One still turned into a slow camera move. The progress is eased (slow start, slow end) so a move never starts or stops with a jerk."""
    d = max(frames, 1)
    t = f"(on/{d})"
    e = f"({t}*{t}*(3-2*{t}))"
    z, x, y = "1", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    if move == "zoom_in":
        z = f"1+{ZOOM}*{e}"
    elif move == "zoom_out":
        z = f"{1 + ZOOM}-{ZOOM}*{e}"
    elif move == "pan_right":
        z, x = f"{PAN_ZOOM}", f"(iw-iw/zoom)*{e}"
    elif move == "pan_left":
        z, x = f"{PAN_ZOOM}", f"(iw-iw/zoom)*(1-{e})"
    elif move == "pan_up":
        z, y = f"{PAN_ZOOM}", f"(ih-ih/zoom)*(1-{e})"
    elif move == "pan_down":
        z, y = f"{PAN_ZOOM}", f"(ih-ih/zoom)*{e}"
    elif move == "settle":
        z = f"1+0.05*{e}"
    elif move == "drift":
        z, x = f"1.10+0.08*{e}", f"(iw-iw/zoom)*{e}"
    return f"zoompan=z='{z}':x='{x}':y='{y}':d={d}:s={w}x{h}:fps={fps}"


def placeholder(path: Path, size: tuple[int, int], text: str) -> Path:
    im = Image.new("RGB", size, (60, 20, 20))
    d = ImageDraw.Draw(im)
    d.rectangle((6, 6, size[0] - 7, size[1] - 7), outline=(230, 80, 60), width=max(3, size[0] // 200))
    f = graphics.font("bold", max(18, size[0] // 22))
    for n, ln in enumerate(graphics.wrap(d, text, f, int(size[0] * 0.8))):
        d.text((size[0] / 2 - graphics.text_w(d, ln, f) / 2, size[1] * 0.42 + n * f.size * 1.3), ln, font=f, fill=(255, 235, 220))
    im.save(path)
    return path


def render_clip(img: Path, out: Path, frames: int, move: str, prof: dict, fade: bool) -> None:
    w, h = prof["size"]
    chain = [f"scale={SUPERSAMPLE * w}:{SUPERSAMPLE * h}:flags=lanczos:force_original_aspect_ratio=increase", f"crop={SUPERSAMPLE * w}:{SUPERSAMPLE * h}", zoompan(move, frames, w, h, prof["fps"])]
    if fade:
        chain.append(f"fade=t=in:st=0:d={min(0.5, frames / prof['fps'] / 2):.2f}")
    chain.append("format=yuv420p")
    _run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(img), "-vf", ",".join(chain), "-frames:v", str(frames), "-r", str(prof["fps"]),
          "-c:v", "libx264", "-preset", prof["preset"], "-crf", str(prof["crf"]), "-pix_fmt", "yuv420p", "-an", str(out)])


def _render_video_clip(src: Path, out: Path, frames: int, prof: dict) -> None:
    """Trim a Wan 2.2 MP4 to the scene's frame count and scale to output size."""
    w, h = prof["size"]
    fps  = prof["fps"]
    secs = frames / fps
    _run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
          "-i", str(src),
          "-t", f"{secs:.3f}",
          "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                 f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
          "-frames:v", str(frames),
          "-r", str(fps),
          "-c:v", "libx264", "-preset", prof["preset"], "-crf", str(prof["crf"]),
          "-pix_fmt", "yuv420p", "-an", str(out)])


def render_audio(parts: list[dict], out: Path, work: Path) -> None:
    """Every part as 24 kHz mono, in plan order; a part without audio is silence of its expected length (only reachable with "build anyway")."""
    files = []
    for n, a in enumerate(parts):
        f = work / f"a{n:03d}.wav"
        if a["path"]:
            _run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(a["path"]), "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(f)])
        else:
            _run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{a['duration_s']:.3f}", "-c:a", "pcm_s16le", str(f)])
        files.append(f)
    lst = work / "audio.txt"
    lst.write_text("".join(f"file '{f.name}'\n" for f in files), encoding="utf-8")
    _run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst.name, "-c", "copy", str(out)], cwd=work)


def ass_time(t: float) -> str:
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def caption_events(plan_id: str) -> list[tuple[float, float, str]]:
    """One caption per narration sentence, timed from the same sentence lengths the scenes use (real audio when there is one)."""
    plan = planner.get_plan(plan_id)
    wpm = plan["settings"].get("wpm", planner.WPM)
    real = storyboard.real_audio(plan_id)
    t, out = 0.0, []
    for seg in plan["segments"]:
        sd = storyboard.sentence_seconds(seg, wpm, real.get(seg["id"]))
        at = t
        for s_, secs in zip(seg["sentences"], sd):
            text = re.sub(r"\s+", " ", str(s_.get("text") or "")).strip()
            if text:
                out.append((round(at, 2), round(at + secs, 2), text))
            at += secs
        t += sum(sd)
    return out


def write_ass(events: list[tuple[float, float, str]], path: Path, size: tuple[int, int]) -> None:
    w, h = size
    fs = max(14, round(h * 0.05))
    head = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {w}\nPlayResY: {h}\nWrapStyle: 0\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Default,{CAPTION_FONT},{fs},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,{max(2, round(h * 0.004))},0,2,{round(w * 0.1)},{round(w * 0.1)},{round(h * 0.09)},1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")           # bottom margin keeps captions inside the 16:9 safe area
    body = "".join(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Default,,0,0,0,,{t.replace(chr(10), ' ').replace('{', '(').replace('}', ')')}\n" for a, b, t in events)
    path.write_text(head + body, encoding="utf-8")


def inputs_hash(chk: dict, prof_name: str, captions: bool, speed: float = 1.0) -> str:
    key = json.dumps([prof_name, captions, speed, [(k, str(v.get("item"))) for k, v in sorted(chk["visuals"].items())], [(a["segment"], a["item"]) for a in chk["audio"]],
                      [(s["id"], s["start_s"], s["duration_s"]) for s in sorted(storyboard.get_scenes(chk["plan"]["id"]), key=lambda x: x["id"])]])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


# ── the build ───────────────────────────────────────────────────────────────

def build(plan_id: str, profile: str = "draft", captions: bool = False, allow_gaps: bool = False, progress=None, speed: float | None = None) -> dict:
    speed = PLAYBACK_SPEED if speed is None else float(speed)
    prof = PROFILES.get(profile)
    if not prof:
        raise MediaError(f"unknown profile '{profile}' (known: {', '.join(PROFILES)})")
    tools = available()
    if not tools["ffmpeg"]:
        raise MediaError(f"ffmpeg was not found at {FFMPEG}")
    if captions and not tools["captions"]:
        raise MediaError("this ffmpeg has no libass, so captions cannot be burned in; build without captions")
    chk = checklist(plan_id)
    if chk["blockers"] and not allow_gaps:
        why = "; ".join(f"{b['text']}" + (f" (scene at {int(b['at'] // 60)}:{int(b['at'] % 60):02d})" if b.get("at") is not None else "") for b in chk["blockers"][:6])
        raise MediaError(f"{len(chk['blockers'])} thing(s) are missing: {why}. Make them first, or build anyway to put labelled placeholders where they are missing")
    sc_list = sorted(storyboard.get_scenes(plan_id), key=lambda x: (x["start_s"], x["seq"]))
    t0 = time.time()
    exp = 0
    root = store.media_dir(plan_id, "video")
    work = root / "work"
    clips_dir = work / f"clips-{profile}"
    clips_dir.mkdir(parents=True, exist_ok=True)
    w, h = prof["size"]
    moves = pick_moves(sc_list)
    placeholders, cum, frames_done, lines = [], 0.0, 0, []
    total = len(sc_list) + 3
    for n, (sc, move) in enumerate(zip(sc_list, moves)):
        if progress:
            progress(n, total, f"scene {n + 1} of {len(sc_list)}")
        end = cum + sc["duration_s"]
        frames = max(1, round(end * prof["fps"]) - round(cum * prof["fps"]))                 # cut points on the exact timeline: no drift over 50 scenes
        cum = end
        v      = chk["visuals"].get(sc["id"]) or {"path": None}
        source = v.get("source", "")
        img    = v["path"]
        if not img:
            img    = str(placeholder(work / f"missing-{sc['id']}.png", (w, h), "PICTURE MISSING"))
            source = "placeholder"
            placeholders.append({"kind": "picture", "scene": sc["id"], "at": sc["start_s"]})
        fade  = wants_dissolve(sc) and n > 0
        key   = hashlib.sha1(f"{img}|{Path(img).stat().st_mtime_ns}|{frames}|{move}|{prof['size']}|{prof['fps']}|{prof['crf']}|{fade}|{source}".encode()).hexdigest()[:10]
        clip  = clips_dir / f"{n:03d}-{key}.mp4"
        if not clip.is_file():
            if source == "clip":
                _render_video_clip(Path(img), clip, frames, prof)
            else:
                render_clip(Path(img), clip, frames, move, prof, fade)
        lines.append(clip)
        frames_done += frames
    if progress:
        progress(len(sc_list), total, "joining the pictures")
    listing = work / f"clips-{profile}.txt"
    listing.write_text("".join(f"file '{c.relative_to(work).as_posix()}'\n" for c in lines), encoding="utf-8")
    joined = work / f"joined-{profile}.mp4"
    _run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", listing.name, "-c", "copy", joined.name], cwd=work)
    if progress:
        progress(len(sc_list) + 1, total, "joining the voice")
    for a in chk["audio"]:
        if not a["path"]:
            placeholders.append({"kind": "voice", "segment": a["segment"]})
    audio = work / f"audio-{profile}.wav"
    render_audio(chk["audio"], audio, work)
    if progress:
        progress(len(sc_list) + 2, total, "making the video file" + (" with captions" if captions else ""))
    it = store.add(plan_id, KIND, profile, exp, "running", {"profile": profile})
    name = f"video/{profile}-a{it['attempt']}.mp4"
    out = root / f"{profile}-a{it['attempt']}.mp4"
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", joined.name, "-i", audio.name]
    vf = []
    if captions:
        ev = caption_events(plan_id)
        write_ass(ev, work / "captions.ass", prof["size"])
        vf.append(f"ass=captions.ass:fontsdir='{FONTS_DIR.replace(':', chr(92) + ':')}'")                 # captions are burned in before the speed-up, so they speed up with the voice
    if speed != 1.0:
        vf.append(f"setpts=PTS/{speed}")
        cmd += ["-af", f"atempo={speed}"]                                                                 # the voice keeps its pitch
    if vf:
        cmd += ["-vf", ",".join(vf), "-r", str(prof["fps"]), "-c:v", "libx264", "-preset", prof["preset"], "-crf", str(prof["crf"]), "-pix_fmt", "yuv420p"]
    else:
        cmd += ["-c:v", "copy"]
    cmd += ["-c:a", "aac", "-b:a", prof["abr"], "-map", "0:v:0", "-map", "1:a:0", "-movflags", "+faststart", str(out)]
    try:
        _run(cmd, cwd=work)
        secs = probe_seconds(out)
    except Exception as e:  # noqa: BLE001 - recorded on the attempt and re-raised
        store.update(it["id"], status="failed", meta={"error": str(e)[:300]})
        raise
    store.update(it["id"], status="done", file=name, meta={"duration_s": round(secs, 2), "plan_s": chk["plan_s"], "audio_s": chk["audio_s"], "scenes": len(sc_list), "frames": frames_done,
                                                          "size": f"{w}x{h}", "fps": prof["fps"], "captions": bool(captions), "speed": speed, "placeholders": placeholders,
                                                          "warnings": chk["warnings"], "moves": moves, "used": used_items(chk), "inputs_hash": inputs_hash(chk, profile, captions, speed),
                                                          "seconds_taken": round(time.time() - t0, 1), "bytes": out.stat().st_size})
    plan_store.log(plan_id, "video", {"profile": profile, "seconds": round(secs, 1), "placeholders": len(placeholders), "captions": bool(captions)})
    if progress:
        progress(total, total, "done")
    return {"item": store.get(it["id"]), "placeholders": placeholders}


def used_items(chk: dict) -> dict[str, dict]:
    """scene id -> the picture or card item the video shows for it, kept on the video so a later change can be listed."""
    return {sid: {"item": v.get("item"), "source": v.get("source", "")} for sid, v in chk["visuals"].items() if v.get("item")}


def _url(plan_id: str, item_id: str | None) -> str:
    it = store.get(item_id) if item_id else None
    return f"/api/media/file/{plan_id}/{it['file']}" if it and it["file"] else ""


def changes_since(plan_id: str, chk: dict, last: dict | None) -> dict:
    """What would look different if the video were built now: scenes whose picture is not the one the latest video used, with both pictures, and the scenes
    that still show an approved picture made before a reference or the scene changed (they should be redrawn)."""
    scenes_ = {sc["id"]: sc for sc in storyboard.get_scenes(plan_id)}
    used = (last or {}).get("meta", {}).get("used") or {}
    changed = []
    for sid, v in chk["visuals"].items():
        old = (used.get(sid) or {}).get("item")
        if last and v.get("item") and old != v.get("item") and sid in scenes_:
            sc = scenes_[sid]
            changed.append({"scene": sid, "at": sc["start_s"], "subject": str(sc["data"].get("subject") or ""), "old_url": _url(plan_id, old), "new_url": _url(plan_id, v["item"]),
                            "new_item": v["item"], "approved": not v.get("problem")})
    stale = [{"scene": sid, "at": scenes_[sid]["start_s"], "subject": str(scenes_[sid]["data"].get("subject") or "")} for sid, v in chk["visuals"].items() if v.get("stale") and sid in scenes_]
    return {"since_video": last["id"] if last else None, "changed": sorted(changed, key=lambda c: c["at"]), "stale": sorted(stale, key=lambda c: c["at"])}


def state(plan_id: str) -> dict:
    plan = planner.get_plan(plan_id)
    tools = available()
    try:
        chk = checklist(plan_id)
    except Exception as e:  # noqa: BLE001 - the card still shows the tools
        return {"tools": tools, "error": str(e), "blockers": [], "warnings": [], "videos": [], "ready": False, "done": False, "plan_s": 0, "audio_s": 0, "profiles": {}}
    items = [i for i in store.items(plan_id, KIND) if i["status"] == "done"]
    ratios: dict[str, list[float]] = {}
    for i in items:
        if i["meta"].get("seconds_taken"):
            ratios.setdefault(i["key"], []).append(i["meta"]["seconds_taken"] / max(i["meta"]["duration_s"], 1))
    speed = {k: (sum(ratios[k]) / len(ratios[k]) if ratios.get(k) else p["speed"]) for k, p in PROFILES.items()}
    videos = []
    for i in items:
        want = inputs_hash(chk, i["key"], bool(i["meta"].get("captions")), float(i["meta"].get("speed") or 1.0))
        videos.append({"id": i["id"], "profile": i["key"], "attempt": i["attempt"], "url": f"/api/media/file/{plan_id}/{i['file']}", "duration_s": i["meta"]["duration_s"],
                       "size": i["meta"]["size"], "captions": i["meta"]["captions"], "placeholders": i["meta"]["placeholders"], "warnings": len(i["meta"].get("warnings", [])),
                       "current": i["meta"].get("inputs_hash") == want, "seconds_taken": i["meta"].get("seconds_taken"), "bytes": i["meta"].get("bytes"), "approved": i["approved"]})
    drafts = [v for v in videos if v["profile"] == "draft"]
    return {"tools": tools, "blockers": chk["blockers"], "warnings": chk["warnings"], "plan_s": chk["plan_s"], "audio_s": chk["audio_s"], "length_gap_s": chk["length_gap_s"],
            "scenes": chk["scenes"], "segments": chk["segments"], "videos": videos, "ready": not chk["blockers"] and chk["scenes"] > 0, "done": bool(drafts and drafts[-1]["current"] and not drafts[-1]["placeholders"]),
            "changes": changes_since(plan_id, chk, max(items, key=lambda i: i["updated_at"]) if items else None),
            "profiles": {k: {"label": p["label"], "size": f"{p['size'][0]}x{p['size'][1]}", "eta_s": round(chk["plan_s"] * speed[k])} for k, p in PROFILES.items()}}
