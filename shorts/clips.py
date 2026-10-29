"""Making the pictures and the clips of a short. One request at a time (the gateway serves one), each result saved as a numbered attempt the moment it arrives, a failed shot recorded
while the job goes on, Stop losing only the clip in flight. A clip is tied to a hash of its request (without the seed), so a shot whose prompt, picture or length changed shows "old"."""
import asyncio
import hashlib
import time

from story import settings as settings_mod
from story3 import store as media
from story3.voice import MediaError

from . import frames, models, pipelines as P, store, wan


def _fingerprint(path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()[:12]


def _jpeg_url(data: bytes, size: str) -> str:
    return wan.data_url(frames.crop_916(data, size), "image/jpeg")


# ── what a shot starts from ──────────────────────────────────────────────────

def keyframe_plan(short: dict, shot: dict) -> dict:
    """How the keyframe of a shot comes about: `source` upload/anchor (a picture of the user's, used as it is) or wan (made by the model), and its input hash."""
    src = P.start_source(short, shot)
    if src in ("upload", "anchor"):
        rel = short["images"]["shots"].get(shot["id"]) if src == "upload" else short["images"].get("anchor")
        path = store.image_path(short, rel)
        return {"source": src, "path": path, "hash": store.input_hash(src, _fingerprint(path))}
    return {"source": "wan", "path": None, "hash": P.req_hash(P.keyframe_request(short, shot, 1))}


def chosen_keyframe(short: dict, shot: dict) -> dict | None:
    return store.chosen(short["id"], store.KEY, shot["id"], keyframe_plan(short, shot)["hash"])


def clip_plan(short: dict, shot: dict) -> dict | None:
    """What the clip of a shot is made from: its request builder, its input hash and the picture it needs. None when the picture it needs does not exist yet."""
    size = short["settings"].get("size") or models.SIZE_PORTRAIT
    if short["pipeline"] == "keyframe":
        kf = chosen_keyframe(short, shot)
        if not kf:
            return None
        token = f"key:{kf['id']}"
        build = lambda attempt, image: P.animate_request(short, shot, attempt, image)            # noqa: E731
        load = lambda: wan.data_url(media.path_of(kf).read_bytes(), "image/jpeg")                # noqa: E731
        return {"token": token, "hash": P.req_hash(P.animate_request(short, shot, 1, token)), "build": build, "load": load, "source": "keyframe"}
    src = P.start_source(short, shot)
    if src in ("upload", "anchor"):
        path = store.image_path(short, short["images"]["shots"].get(shot["id"]) if src == "upload" else short["images"].get("anchor"))
        token = f"{src}:{_fingerprint(path)}"
        return {"token": token, "hash": P.req_hash(P.quick_request(short, shot, 1, token)), "build": lambda a, image: P.quick_request(short, shot, a, image),
                "load": lambda: _jpeg_url(path.read_bytes(), size), "source": src}
    if src == "prev":
        i = short["shots"].index(shot)
        prev = store.chosen(short["id"], store.CLIP, short["shots"][i - 1]["id"])
        if prev:
            token = f"prev:{prev['id']}"

            def load_prev() -> str:
                out = store.media_dir(short["id"], "frames") / f"{prev['id']}.jpg"
                if not out.is_file():
                    frames.last_frame(media.path_of(prev), out)
                return _jpeg_url(out.read_bytes(), size)
            return {"token": token, "hash": P.req_hash(P.quick_request(short, shot, 1, token)), "build": lambda a, image: P.quick_request(short, shot, a, image), "load": load_prev, "source": "prev"}
    return {"token": "", "hash": P.req_hash(P.quick_request(short, shot, 1)), "build": lambda a, image: P.quick_request(short, shot, a, None), "load": lambda: None, "source": "text"}


def chosen_clip(short: dict, shot: dict) -> dict | None:
    plan = clip_plan(short, shot)
    return store.chosen(short["id"], store.CLIP, shot["id"], plan["hash"]) if plan else None


# ── running requests ─────────────────────────────────────────────────────────

def _finish(short_id: str, it: dict, data: bytes, res: dict, sub: str, name: str, ext: str) -> dict:
    d = store.media_dir(short_id, sub)
    (d / f"{name}-a{it['attempt']}.{ext}").write_bytes(data)
    return media.update(it["id"], status="done", file=f"{sub}/{name}-a{it['attempt']}.{ext}",
                        meta={"width": res.get("width"), "height": res.get("height"), "frames": res.get("frames"), "fps": res.get("fps"), "duration_s": res.get("duration_s"),
                              "generation_s": res.get("generation_s"), "seed_used": res.get("seed")})


async def _adopt(short_id: str, kind: str, key: str, base: str, api_key: str) -> dict | None:
    """A request that was running when the app stopped: if the gateway still has the job, take its result; otherwise the attempt is closed as failed."""
    for it in media.items(short_id, kind, key):
        if it["status"] != "running":
            continue
        jid = it["meta"].get("job_id")
        if not jid:
            media.update(it["id"], status="failed", meta={"error": "stopped before it was sent"})
            continue
        try:
            data, res = await wan.resume(jid, base, api_key)
            return {"item": it, "data": data, "res": res}
        except wan.WanError as e:
            media.update(it["id"], status="failed", meta={"error": f"could not be picked up again: {e}"[:300]})
    return None


async def _request(short_id: str, kind: str, key: str, body: dict, h: str, base: str, api_key: str, extra: dict | None = None, limit_s: float = wan.JOB_LIMIT_S) -> tuple[dict, bytes, dict]:
    it = media.add(short_id, kind, key, 0, "running", {"input_hash": h, "seed": body["seed"], "model": body["model"], "prompt": body["prompt"][:700], "frames_asked": body.get("num_frames"),
                                                       "size": body.get("size"), "steps": body.get("steps"), **(extra or {})})
    t0 = time.time()
    try:
        data, res = await wan.run(body, base, api_key, on_job=lambda jid: media.update(it["id"], meta={"job_id": jid}), limit_s=limit_s)
    except asyncio.CancelledError:
        media.update(it["id"], status="failed", meta={"error": "stopped before it finished"})
        raise
    except wan.WanError as e:
        media.update(it["id"], status="failed", meta={"error": str(e)[:300], "seconds_taken": round(time.time() - t0, 1)})
        raise
    media.update(it["id"], meta={"seconds_taken": round(time.time() - t0, 1)})
    return it, data, res


def _ctx(s: dict | None, key: str) -> tuple[str, str]:
    s = s or settings_mod.get()
    return s["base_url"].rstrip("/"), key or settings_mod.api_key()


async def make_keyframes(short_id: str, shot_ids: list[str] | None = None, only_missing: bool = True, progress=None, s: dict | None = None, key: str = "") -> dict:
    """A still for every shot of a keyframe short. The user's pictures are used as they are (cropped to 9:16); the rest are made by Wan."""
    base, api_key = _ctx(s, key)
    short = store.get(short_id)
    todo = [sh for sh in short["shots"] if (not shot_ids or sh["id"] in shot_ids) and (not only_missing or not chosen_keyframe(short, sh))]
    made, failed = 0, []
    for i, sh in enumerate(todo):
        if progress:
            progress(i, len(todo), f"keyframe {i + 1} of {len(todo)}")
        plan = keyframe_plan(short, sh)
        try:
            if plan["source"] != "wan":
                it = media.add(short_id, store.KEY, sh["id"], 0, "running", {"input_hash": plan["hash"], "source": plan["source"]})
                (store.media_dir(short_id, "key") / f"{sh['id']}-a{it['attempt']}.jpg").write_bytes(frames.crop_916(plan["path"].read_bytes(), models.SIZE_PORTRAIT))
                media.update(it["id"], status="done", file=f"key/{sh['id']}-a{it['attempt']}.jpg")
            else:
                done = await _adopt(short_id, store.KEY, sh["id"], base, api_key)
                if done:
                    it, data, res = done["item"], done["data"], done["res"]
                else:
                    attempt = len(media.items(short_id, store.KEY, sh["id"])) + 1
                    it, data, res = await _request(short_id, store.KEY, sh["id"], P.keyframe_request(short, sh, attempt), plan["hash"], base, api_key, {"source": "wan"})
                tmp = store.media_dir(short_id, "key") / f"{sh['id']}-a{it['attempt']}.mp4"
                tmp.write_bytes(data)
                frames.last_frame(tmp, store.media_dir(short_id, "key") / f"{sh['id']}-a{it['attempt']}.jpg")
                tmp.unlink(missing_ok=True)
                media.update(it["id"], status="done", file=f"key/{sh['id']}-a{it['attempt']}.jpg", meta={"width": res.get("width"), "height": res.get("height")})
            made += 1
        except (wan.WanError, MediaError) as e:
            failed.append({"shot": sh["id"], "error": str(e)[:200]})
            if "not reachable" in str(e):
                break
    if progress:
        progress(len(todo), len(todo), "done")
    return {"made": made, "failed": failed}


async def make_clips(short_id: str, shot_ids: list[str] | None = None, only_missing: bool = True, progress=None, s: dict | None = None, key: str = "") -> dict:
    """One clip per shot, in order (a shot that continues from the one before needs that clip first)."""
    from . import planner
    base, api_key = _ctx(s, key)
    short = planner.sync_timing(short_id)
    todo = [sh for sh in short["shots"] if not shot_ids or sh["id"] in shot_ids]
    if only_missing:
        todo = [sh for sh in todo if not chosen_clip(short, sh)]
    made, failed, skipped = 0, [], []
    for i, sh in enumerate(todo):
        if progress:
            progress(i, len(todo), f"clip {i + 1} of {len(todo)}")
        plan = clip_plan(short, sh)
        if not plan:
            skipped.append({"shot": sh["id"], "error": "its keyframe is not made yet"})
            continue
        try:
            done = await _adopt(short_id, store.CLIP, sh["id"], base, api_key)
            if done:
                it, data, res = done["item"], done["data"], done["res"]
            else:
                attempt = len(media.items(short_id, store.CLIP, sh["id"])) + 1
                body = plan["build"](attempt, plan["load"]())
                it, data, res = await _request(short_id, store.CLIP, sh["id"], body, plan["hash"], base, api_key, {"start": plan["source"], "shot_seconds": sh["seconds"]})
            _finish(short_id, it, data, res, "clip", sh["id"], "mp4")
            made += 1
        except (wan.WanError, MediaError) as e:
            failed.append({"shot": sh["id"], "error": str(e)[:200]})
            if "not reachable" in str(e):
                break
    if progress:
        progress(len(todo), len(todo), "done")
    return {"made": made, "failed": failed, "skipped": skipped}


# ── what the screen shows ────────────────────────────────────────────────────

def _view(short_id: str, it: dict) -> dict:
    return {"id": it["id"], "attempt": it["attempt"], "status": it["status"], "approved": it["approved"], "url": f"/api/shorts/file/{short_id}/{it['file']}" if it["file"] else "",
            "error": it["meta"].get("error", ""), "seed": it["meta"].get("seed"), "seconds_taken": it["meta"].get("seconds_taken"), "source": it["meta"].get("source") or it["meta"].get("start", ""),
            "hash": it["meta"].get("input_hash")}


def shot_rows(short: dict) -> list[dict]:
    rows = []
    for sh in short["shots"]:
        kp = keyframe_plan(short, sh) if short["pipeline"] == "keyframe" else None
        cp = clip_plan(short, sh)
        keys = media.items(short["id"], store.KEY, sh["id"])
        clips = media.items(short["id"], store.CLIP, sh["id"])
        kch = chosen_keyframe(short, sh) if kp else None
        cch = store.chosen(short["id"], store.CLIP, sh["id"], cp["hash"]) if cp else None
        rows.append({"id": sh["id"], "beat": sh["beat"], "seconds": sh["seconds"], "begins": P.start_source(short, sh), "keyframes": [_view(short["id"], k) for k in keys],
                     "keyframe": kch["id"] if kch else None, "clips": [_view(short["id"], c) for c in clips], "clip": cch["id"] if cch else None,
                     "old_clip": bool(clips and not cch and any(c["status"] == "done" for c in clips))})
    return rows
