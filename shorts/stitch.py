"""Putting a short together with ffmpeg: every clip is cut to exactly its shot's frames of a 30 fps 1080x1920 picture, the shots are joined with hard cuts (the pace is the point),
the beats' voice takes are sped or slowed a little and laid on the timeline, a quiet bed goes under them, phrase captions are burned into the lower third, and the loudness is
set to -14 LUFS. The result is exactly 30 seconds (900 frames)."""
import json
import re
import time
from pathlib import Path

from story3 import audio as audio_mod, store as media, video
from story3.voice import MediaError

from . import clips, frames, models, planner, store, timeline, voice as svoice

CAPTION_SIZE = 72
CAPTION_MARGIN_V = 340                # captions sit in the lower third, above where the apps put their own buttons
CAPTION_WORDS = (2, 4)                # fast pace: two to four words at a time
VERSION = "s1"                        # part of the final video's cache key: bump when the way it is put together changes


def _ffmpeg(args: list[str], cwd: Path | None = None) -> None:
    frames.run(args, cwd=cwd)


def encode_segment(src: Path, out: Path, n_frames: int) -> None:
    """One shot: the clip at 30 fps, scaled to cover 1080x1920 and cropped, cut to `n_frames`. A clip shorter than needed holds its last frame."""
    w, h = models.OUT_SIZE
    vf = (f"fps={models.OUT_FPS},tpad=stop_mode=clone:stop_duration=3,scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h},setsar=1,format=yuv420p")
    _ffmpeg(["-i", str(src), "-vf", vf, "-frames:v", str(n_frames), "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-r", str(models.OUT_FPS), str(out)])


def join_segments(segs: list[Path], out: Path, work: Path) -> None:
    lst = work / "segments.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in segs), encoding="utf-8")
    _ffmpeg(["-f", "concat", "-safe", "0", "-i", lst.name, "-c", "copy", str(out)], cwd=work)


def beat_audio(src: Path, tempo: float, span: float, out: Path) -> None:
    """A beat's voice at `tempo` (pitch kept), padded with silence or cut to exactly `span` seconds, 24 kHz mono."""
    _ffmpeg(["-i", str(src), "-af", f"atempo={tempo:.4f},apad=whole_dur={span:.3f}", "-t", f"{span:.3f}", "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(out)])


def silence(work: Path, seconds: float) -> Path:
    out = work / "silence.wav"
    _ffmpeg(["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{seconds:.3f}", "-c:a", "pcm_s16le", str(out)])
    return out


def write_ass(events: list[tuple[float, float, str]], path: Path) -> None:
    w, h = models.OUT_SIZE
    head = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {w}\nPlayResY: {h}\nWrapStyle: 0\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Default,{video.CAPTION_FONT},{CAPTION_SIZE},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,1,2,90,90,{CAPTION_MARGIN_V},1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    body = "".join(f"Dialogue: 0,{video.ass_time(a)},{video.ass_time(b)},Default,,0,0,0,,{t.replace(chr(10), ' ').replace('{', '(').replace('}', ')')}\n" for a, b, t in events)
    path.write_text(head + body, encoding="utf-8")


def caption_events(texts: list[str], start: float, voice_s: float) -> list[tuple[float, float, str]]:
    """Phrases of two to four words for the sentences of a stretch of speech, each shown for its share of the time by letters."""
    parts = [(t, video.phrases(re.sub(r"\s+", " ", t).strip(), *CAPTION_WORDS)) for t in texts if t.strip()]
    letters = sum(len(p) for _, ps in parts for p in ps) or 1
    out, at = [], start
    for _, ps in parts:
        for p in ps:
            d = voice_s * len(p) / letters
            out.append((round(at, 2), round(at + d, 2), p))
            at += d
    return out


def short_events(short: dict, tl: dict) -> list[tuple[float, float, str]]:
    ev = []
    for b, t in zip(short["beats"], tl["beats"]):
        ev += caption_events([s["text"] for s in b["sentences"]], t["start"], t["voice_s"])
    return ev


def mix_and_mux(silent: Path, voice_wav: Path | None, bed_parts: list[dict], captions: Path | None, out: Path, work: Path, settings: dict, total_s: float) -> dict:
    """Video + voice + bed + captions -> the final file. Returns notes (for example when the bed could not be made)."""
    notes = {"bed": False}
    args = ["-i", str(silent.name)]
    vf = "null"
    if captions:
        vf = f"ass={captions.name}:fontsdir='{video.FONTS_DIR.replace(':', chr(92) + ':')}'"
    if voice_wav is None:
        graph = f"[0:v]{vf}[v]"
        maps = ["-map", "[v]", "-an"]
    else:
        args += ["-i", str(voice_wav.name)]
        bed = audio_mod.build_bed(video.FFMPEG, bed_parts, work, level_db=-30) if (settings.get("bed", True) and bed_parts) else None
        if bed:
            args += ["-i", str(bed.name)]
            graph = f"[0:v]{vf}[v];{audio_mod.mix_args(2)};[mix]{video.LOUDNORM}[a]"
            notes["bed"] = True
        else:
            graph = f"[0:v]{vf}[v];[1:a]{video.LOUDNORM}[a]"
        maps = ["-map", "[v]", "-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
    _ffmpeg([*args, "-filter_complex", graph, *maps, "-t", f"{total_s:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(models.OUT_FPS),
             "-movflags", "+faststart", str(out)], cwd=work)
    return notes


def final_hash(short: dict, tl: dict, used: dict) -> str:
    return store.input_hash(VERSION, json.dumps([tl["tempo"], [(s["id"], s["frames"]) for s in tl["shots"]], used, short["settings"].get("captions"), short["settings"].get("bed")], sort_keys=True))


def checklist(short: dict) -> dict:
    """What is missing before the short can be put together."""
    missing = []
    if not short["shots"]:
        missing.append("plan the short first")
    for b in short["beats"]:
        if not svoice.chosen(short, b):
            missing.append(f"voice for beat {b['id']}")
    for sh in short["shots"]:
        if not clips.chosen_clip(short, sh):
            missing.append(f"clip for shot {sh['id']}")
    return {"ready": not missing, "missing": missing}


def build(short_id: str, progress=None) -> dict:
    """Put a quick or keyframe short together. Raises MediaError with a plain message when something is missing."""
    short = planner.sync_timing(short_id)               # shot lengths follow the real voice before anything is compared with a clip's hash
    chk = checklist(short)
    if not chk["ready"]:
        raise MediaError("not ready: " + "; ".join(chk["missing"][:6]))
    avail = video.available()
    if not avail["ffmpeg"]:
        raise MediaError("ffmpeg was not found")
    no_voice = short.get("settings", {}).get("voice_mode") == "none"
    voices = {} if no_voice else {b["id"]: svoice.chosen(short, b) for b in short["beats"]}
    tl = timeline.build(short, {k: v["meta"]["duration_s"] for k, v in voices.items()})
    bad = [p for p in tl["problems"] if p["code"] in ("shot_too_long", "length")]
    if bad:
        raise MediaError("; ".join(p["text"] for p in bad) + ": fix this on the checks list first")
    chosen = {sh["id"]: clips.chosen_clip(short, sh) for sh in short["shots"]}
    used = {"clips": {k: v["id"] for k, v in chosen.items()}, "voice": {} if no_voice else {k: v["id"] for k, v in voices.items()}}
    h = final_hash(short, tl, used)
    for it in media.items(short_id, store.FINAL, "final"):
        if it["status"] == "done" and it["meta"].get("input_hash") == h and it["file"]:
            return it
    it = media.add(short_id, store.FINAL, "final", 0, "running", {"input_hash": h})
    work = store.media_dir(short_id, f"work/{it['id']}")
    t0 = time.time()
    try:
        segs = []
        for i, t in enumerate(tl["shots"]):
            if progress:
                progress(i, len(tl["shots"]) + 2, f"cutting shot {i + 1} of {len(tl['shots'])}")
            seg = work / f"seg{i:03d}.mp4"
            encode_segment(media.path_of(chosen[t["id"]]), seg, t["frames"])
            segs.append(seg)
        if progress:
            progress(len(tl["shots"]), len(tl["shots"]) + 2, "joining the shots and the voice")
        silent = work / "silent.mp4"
        join_segments(segs, silent, work)
        voice_wav = None
        parts = []
        if not no_voice:
            for i, (b, t) in enumerate(zip(short["beats"], tl["beats"])):
                wav = work / f"v{i:02d}.wav"
                beat_audio(media.path_of(voices[b["id"]]), tl["tempo"], t["span"], wav)
                parts.append((wav, t))
            lst = work / "voice.txt"
            lst.write_text("".join(f"file '{p.name}'\n" for p, _ in parts), encoding="utf-8")
            voice_wav = work / "voice.wav"
            _ffmpeg(["-f", "concat", "-safe", "0", "-i", lst.name, "-c", "copy", str(voice_wav)], cwd=work)
        ass = None
        if not no_voice and short["settings"].get("captions", True) and avail["captions"]:
            ass = work / "captions.ass"
            write_ass(short_events(short, tl), ass)
        out = store.media_dir(short_id, "final") / f"short-a{it['attempt']}.mp4"
        notes = mix_and_mux(silent, voice_wav, [{"duration_s": t["span"]} for _, t in parts], ass, out, work, short["settings"], float(short["settings"].get("target_s") or models.TARGET_S))
        info = frames.info(out)
        media.update(it["id"], status="done", file=f"final/{out.name}", meta={"input_hash": h, "duration_s": round(info["duration_s"], 2), "used": used, "tempo": tl["tempo"],
                                                                              "shots": len(tl["shots"]), "seconds_taken": round(time.time() - t0, 1), **notes})
    except Exception as e:  # noqa: BLE001
        media.update(it["id"], status="failed", meta={"error": str(e)[:300]})
        raise
    short = store.get(short_id)
    short["status"] = "made"
    store.save(short)
    if progress:
        progress(len(tl["shots"]) + 2, len(tl["shots"]) + 2, "done")
    return media.get(it["id"])


def final_state(short_id: str) -> dict:
    its = media.items(short_id, store.FINAL, "final")
    short = store.get(short_id)
    cur = [i for i in its if i["status"] == "done"]
    last = cur[-1] if cur else None
    return {"attempts": [{"id": i["id"], "attempt": i["attempt"], "status": i["status"], "approved": i["approved"], "error": i["meta"].get("error", ""),
                          "url": f"/api/shorts/file/{short_id}/{i['file']}" if i["file"] else "", "duration_s": i["meta"].get("duration_s"), "bed": i["meta"].get("bed")} for i in its],
            "latest": last["id"] if last else None, "checklist": checklist(short) if short["pipeline"] != "remix" else None}
