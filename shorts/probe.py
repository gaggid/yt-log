"""S0: measure what the gateway's Wan models really do on this machine, before the defaults are trusted.

    .venv\\Scripts\\python.exe -m shorts.probe                       # the text and picture models at 2.5 seconds each
    .venv\\Scripts\\python.exe -m shorts.probe --only ti2v,keyframe  # chosen tests
    .venv\\Scripts\\python.exe -m shorts.probe --hires               # also 704x1280 on the 5B and 720x1280 on the 14B (untested in the docs)
    .venv\\Scripts\\python.exe -m shorts.probe --image a.png --driving walk.mp4 [--animate-long]   # character animation

It lists the video models the key can use, makes the clips one at a time (the gateway serves one), saves them under data/shorts_probe/<time>/, prints seconds taken and what the
gateway returned (size, frames, whether the result URL is a path or a full address), and writes data/shorts_probe/timings.json: seconds per frame per model, which the Shorts
screen uses for its time estimates. Needs the gateway free for about an hour (more with --hires or --animate-long)."""
import argparse
import asyncio
import json
import time
from pathlib import Path

import config
from story import settings as settings_mod

from . import frames, models, pipelines as P, remix, wan

PROMPT = "A young Indian courier in a yellow jacket walks along a rainy street at dusk, neon shop lights reflecting in the puddles. Slow tracking shot, cinematic, shallow depth of field."
FRAMES_2_5S = {models.TI2V: 61, models.T2V: 41, models.I2V: 41}


def out_dir() -> Path:
    d = config.DATA_DIR / "shorts_probe" / time.strftime("%Y%m%d-%H%M%S")
    d.mkdir(parents=True, exist_ok=True)
    return d


async def one(name: str, body: dict, base: str, key: str, d: Path, report: list[dict]) -> bytes | None:
    t0 = time.time()
    print(f"[{name}] sending ({body.get('model')}, {body.get('size')}, {body.get('num_frames')} frames) ...", flush=True)
    try:
        data, res = await wan.run(body, base, key, limit_s=7200)
    except wan.WanError as e:
        print(f"[{name}] FAILED: {e}", flush=True)
        report.append({"name": name, "ok": False, "error": str(e)})
        return None
    secs = time.time() - t0
    (d / f"{name}.mp4").write_bytes(data)
    row = {"name": name, "ok": True, "model": body["model"], "seconds": round(secs, 1), "frames_asked": body.get("num_frames"), "frames": res.get("frames"), "size": f"{res.get('width')}x{res.get('height')}",
           "fps": res.get("fps"), "url": res.get("url"), "url_is_full_address": str(res.get("url", "")).startswith("http"), "generation_s": res.get("generation_s"), "bytes": len(data)}
    report.append(row)
    print(f"[{name}] done in {secs:.0f}s -> {row['size']}, {row['frames']} frames, url {'full' if row['url_is_full_address'] else 'path'}: {row['url']}", flush=True)
    return data


def save_timings(report: list[dict], models_seen: list[str]) -> None:
    path = config.DATA_DIR / "shorts_probe" / "timings.json"
    cur = {}
    try:
        cur = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    for r in report:
        if not r.get("ok") or not r.get("frames_asked") or "sharp" in r["name"] or "720" in r["name"] or r["name"].startswith("keyframe"):
            continue
        cur[r["model"]] = {"s_per_frame": round(r["seconds"] / r["frames_asked"], 3), "measured": time.strftime("%Y-%m-%d"), "from": r["name"]}
    kf = next((r for r in report if r.get("ok") and r["name"] == "keyframe"), None)
    if kf:
        cur["keyframe_request_s"] = kf["seconds"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cur, indent=1), encoding="utf-8")


async def main(args) -> None:
    s = settings_mod.get()
    base, key = s["base_url"].rstrip("/"), settings_mod.api_key()
    listed = await wan.models(base, key)
    ids = [m.get("id") for m in listed]
    print("video models the key can use:", ", ".join(ids) or "(none listed, or the gateway could not be asked)", flush=True)
    only = set(args.only.split(",")) if args.only else {"ti2v", "t2v", "keyframe", "i2v"}
    d = out_dir()
    report: list[dict] = []
    common = {"negative_prompt": P.NEGATIVE, "seed": 7, "response_format": "mp4"}
    if "ti2v" in only and models.TI2V in ids:
        await one("ti2v", {"model": models.TI2V, "prompt": PROMPT, "size": models.SIZE_PORTRAIT, "num_frames": FRAMES_2_5S[models.TI2V], "fps": 24, "steps": 20, **common}, base, key, d, report)
        if args.hires:
            await one("ti2v-sharp-704x1280", {"model": models.TI2V, "prompt": PROMPT, "size": models.SIZE_SHARP, "num_frames": FRAMES_2_5S[models.TI2V], "fps": 24, "steps": 20, **common}, base, key, d, report)
    if "t2v" in only and models.T2V in ids:
        await one("t2v", {"model": models.T2V, "prompt": PROMPT, "size": models.SIZE_PORTRAIT, "num_frames": FRAMES_2_5S[models.T2V], "fps": 16, "speed_lora": False, "steps": 20, **common}, base, key, d, report)
        if args.hires:
            await one("t2v-720x1280", {"model": models.T2V, "prompt": PROMPT, "size": "720x1280", "num_frames": FRAMES_2_5S[models.T2V], "fps": 16, "speed_lora": False, "steps": 20, **common}, base, key, d, report)
    key_jpg = None
    if "keyframe" in only and models.T2V in ids:
        data = await one("keyframe", {"model": models.T2V, "prompt": PROMPT, "size": models.SIZE_PORTRAIT, "num_frames": P.KEYFRAME_FRAMES, "fps": 16, "speed_lora": False, "steps": 20, **common}, base, key, d, report)
        if data:
            key_jpg = frames.last_frame(d / "keyframe.mp4", d / "keyframe.jpg")
    if "i2v" in only and models.I2V in ids:
        img = key_jpg or (Path(args.image) if args.image else None)
        if img:
            await one("i2v", {"model": models.I2V, "prompt": "The courier keeps walking, rain falling, slow push in.", "image": wan.data_url(frames.crop_916(Path(img).read_bytes()), "image/jpeg"),
                              "size": models.SIZE_PORTRAIT, "num_frames": FRAMES_2_5S[models.I2V], "fps": 16, "speed_lora": False, "steps": 10, **common}, base, key, d, report)
        else:
            print("[i2v] skipped: no keyframe was made and no --image was given", flush=True)
    if args.driving and args.image and models.ANIMATE in ids:
        drive = Path(args.driving)
        clip5 = d / "driving5.mp4"
        remix._encode(drive, 0.0, 5.0, "crop", clip5)
        await one("animate-5s", {"model": models.ANIMATE, "image": wan.data_url(frames.crop_916(Path(args.image).read_bytes(), remix.DRIVING_SIZE), "image/jpeg"), "driving_video": wan.data_url(clip5.read_bytes(), "video/mp4"),
                                 "prompt": "A character in plain clothes in a bright studio.", "size": remix.DRIVING_SIZE, "fps": remix.DRIVING_FPS, "duration": 5.0, "steps": 10, "keep_audio": False, **common}, base, key, d, report)
        if args.animate_long:
            clip30 = d / "driving30.mp4"
            remix._encode(drive, 0.0, 30.0, "crop", clip30)
            await one("animate-30s", {"model": models.ANIMATE, "image": wan.data_url(frames.crop_916(Path(args.image).read_bytes(), remix.DRIVING_SIZE), "image/jpeg"), "driving_video": wan.data_url(clip30.read_bytes(), "video/mp4"),
                                      "prompt": "A character in plain clothes in a bright studio.", "size": remix.DRIVING_SIZE, "fps": remix.DRIVING_FPS, "duration": 30.0, "steps": 10, "keep_audio": False, **common}, base, key, d, report)
    elif args.driving or args.image:
        print("[animate] skipped: it needs --image and --driving, and the gateway must list wan-2.2-animate-2", flush=True)
    (d / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    save_timings(report, ids)
    print("\nreport:", d / "report.json")
    for r in report:
        print(" ", r["name"], "-", (f"{r['seconds']}s, {r['size']}, {r['frames']} frames" if r["ok"] else "FAILED " + r["error"][:100]))
    print("timings written to", config.DATA_DIR / "shorts_probe" / "timings.json", "(the Shorts screen's time estimates now use them)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="comma list of: ti2v,t2v,keyframe,i2v")
    ap.add_argument("--hires", action="store_true")
    ap.add_argument("--image", help="a character picture (also the start picture for the i2v test when no keyframe was made)")
    ap.add_argument("--driving", help="a video for the character animation test")
    ap.add_argument("--animate-long", action="store_true", help="also animate 30 seconds in one request (about half an hour)")
    asyncio.run(main(ap.parse_args()))
