"""The optional 2K step (setting `upscale` = "2k"). The gateway's upscaler (`POST /v1/video/upscale`, model `video-upscale`) takes one clip and returns it larger with the same frames; every
frame goes through a full ESRGAN pass, so a job takes minutes. It is capped at 300 frames and 3,686,400 pixels (1440x2560 is exactly that), so the whole short (900 frames) could never
go in: each clip is upscaled on its own and `stitch.build` then cuts the upscaled clips like any others, at 1440x2560.
An upscaled clip is a file next to the short's media (`up/<clip id>-2k.mp4`), made again whenever it is missing; it needs no row of its own because the clip it comes from is the record."""
from pathlib import Path

from story import settings as settings_mod
from story3 import store as media

from . import clips, store, wan

RESOLUTION = {"2k": "2k"}
LIMIT_S = 1800                               # one clip: the docs say minutes per job


def wanted(short: dict) -> bool:
    return (short.get("settings") or {}).get("upscale") in RESOLUTION and short.get("pipeline") != "remix"


def path_for(short: dict, clip: dict) -> Path:
    return store.media_dir(short["id"], "up") / f"{clip['id']}-{short['settings']['upscale']}.mp4"


def missing(short: dict) -> list[dict]:
    """The shots whose chosen clip has no upscaled file yet."""
    if not wanted(short):
        return []
    return [sh for sh in short["shots"] if (c := clips.chosen_clip(short, sh)) and not path_for(short, c).is_file()]


def source_for(short: dict, sh: dict) -> Path:
    """The file the final cut should use for a shot: the upscaled clip when the short asks for one, else the clip as made."""
    c = clips.chosen_clip(short, sh)
    if wanted(short):
        p = path_for(short, c)
        if p.is_file():
            return p
    return media.path_of(c)


def request(short: dict, clip_file: Path) -> dict:
    return {"model": "video-upscale", "video": wan.data_url(clip_file.read_bytes(), "video/mp4"), "resolution": RESOLUTION[short["settings"]["upscale"]], "response_format": "mp4", "crf": 16}


async def make(short_id: str, progress=None, s: dict | None = None, key: str = "") -> dict:
    """Upscale every chosen clip that has no upscaled file. One request at a time. Returns {"made", "failed": [{"shot", "error"}]}; what is finished is kept."""
    s = s or settings_mod.get()
    base, api_key = s["base_url"].rstrip("/"), key or settings_mod.api_key()
    short = store.get(short_id)
    todo = missing(short)
    made, failed = 0, []
    for i, sh in enumerate(todo):
        if progress:
            progress(i, len(todo), f"upscaling shot {i + 1} of {len(todo)}")
        c = clips.chosen_clip(short, sh)
        out = path_for(short, c)
        try:
            data, res = await wan.run(request(short, media.path_of(c)), base, api_key, limit_s=LIMIT_S, path="/video/upscale")
            if res.get("output_width") and res.get("input_width") and res["output_width"] <= res["input_width"]:
                raise wan.WanError(f"the upscaler returned {res['output_width']}x{res.get('output_height')}, not larger")
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(out)
            made += 1
        except (wan.WanError, OSError) as e:
            failed.append({"shot": sh["id"], "error": str(e)[:300]})
            break                                                       # a refused or lost upscale is not retried shot by shot: the person sees the first reason
    if progress:
        progress(len(todo), len(todo), "done")
    return {"made": made, "failed": failed}

