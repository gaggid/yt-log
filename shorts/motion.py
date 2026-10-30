"""Single-shot Animate: a short reference clip (an uploaded file, a YouTube or Instagram link) drives the movement of ONE shot of a normal short. The shot's start picture (which shows a library
character) is the reference character, the window of the reference video is the driving clip, and `wan-2.2-animate-2` makes the shot. There is no 30-second minimum: a 5-second reel is enough
for a shot of up to 3 seconds. The reference video is only the motion guide; it stays under data/media/<short>/motion/, is never exported or uploaded, and its rights box must be ticked."""
import subprocess
from pathlib import Path

from story3.voice import MediaError

from . import frames, models, remix, store

DRIVE_FPS = remix.DRIVING_FPS                    # 16 fps, like the whole-short remix
DRIVE_S = 3.4                                    # the window cut out of the reference: a little more than the longest shot (3.0 s)
MIN_SOURCE_S = 1.0


def of(shot: dict) -> dict | None:
    m = shot.get("motion")
    return m if isinstance(m, dict) and m.get("file") else None


def _dir(short_id: str) -> Path:
    return store.media_dir(short_id, "motion")


def prepare(short_id: str, shot_id: str, source: Path, start: float, title: str = "", url: str = "", rights: bool = False) -> dict:
    """Cut the window out of the reference video, encode it for the model (9:16, 16 fps, silent, small) and record it on the shot."""
    short = store.get(short_id)
    shot = store.shot_by_id(short, shot_id)
    dur = float(frames.info(source)["duration_s"])
    if dur < MIN_SOURCE_S:
        raise MediaError(f"the reference video is {dur:.1f} seconds long; use one of at least {MIN_SOURCE_S:g} second")
    start = max(0.0, min(float(start), max(0.0, dur - 0.5)))
    length = min(DRIVE_S, dur - start)
    out = _dir(short_id) / f"{shot_id}.mp4"
    remix._encode(source, start, length, "crop", out)
    shot["motion"] = {"file": f"motion/{out.name}", "start": round(start, 2), "length": round(length, 2), "title": title[:120], "url": url, "rights": bool(rights), "source_s": round(dur, 1)}
    store.save(short)
    return shot["motion"]


def fetch_link(short_id: str, shot_id: str, url: str, start: float, rights: bool, progress=None) -> dict:
    """Download a YouTube or Instagram link and cut the window. Blocking (run in a thread)."""
    url = remix.check_url(url)
    if progress:
        progress(0, 2, "reading the link")
    info = remix.fetch_info(url)
    if progress:
        progress(1, 2, "downloading the video")
    src = remix.download(url, _dir(short_id))
    m = prepare(short_id, shot_id, src, start, info.get("title", ""), url, rights)
    src.unlink(missing_ok=True)                      # only the cut window is kept
    if progress:
        progress(2, 2, "done")
    return m


def clear(short_id: str, shot_id: str) -> None:
    short = store.get(short_id)
    shot = store.shot_by_id(short, shot_id)
    m = of(shot)
    if m:
        (store.media_dir(short_id) / m["file"]).unlink(missing_ok=True)
    shot.pop("motion", None)
    store.save(short)


def drive_path(short: dict, shot: dict) -> Path | None:
    m = of(shot)
    return store.image_path(short, m["file"]) if m else None


def request(short: dict, shot: dict, attempt: int, image: str, drive: str) -> dict:
    """An Animate clip of one shot: the start picture is the character, the window drives the movement; the prompt describes the character and the place, never the action."""
    from . import pipelines as P
    return {"model": models.ANIMATE, "image": image, "driving_video": drive, "prompt": P.compose(short, shot, True), "size": models.SIZE_PORTRAIT, "fps": DRIVE_FPS,
            "duration": round(shot["seconds"] + 0.2, 2), "steps": int(short["settings"].get("steps") or P.DEFAULT_STEPS[models.ANIMATE]), "pose_strength": 1.0, "keep_audio": False,
            "seed": P.seed_for(short, shot, attempt), "response_format": "mp4"}


def problems(short: dict) -> list[dict]:
    out = []
    for sh in short["shots"]:
        m = of(sh)
        if not m:
            continue
        n = short["shots"].index(sh) + 1
        if not m.get("rights"):
            out.append({"level": "block", "code": "motion_rights", "shot": sh["id"], "text": f"Shot {n} takes its movement from a video: confirm that you have the right to use it."})
        if not drive_path(short, sh):
            out.append({"level": "block", "code": "motion_file", "shot": sh["id"], "text": f"Shot {n}: the reference clip is missing; choose it again."})
        if not sh.get("cast"):
            out.append({"level": "warn", "code": "motion_cast", "shot": sh["id"], "text": f"Shot {n} moves like the reference video but has no library character in it: the person drawn in its start picture performs the movement."})
    return out
