"""Batch G-ext: scene motion clips. Wan 2.2 image-to-video animation of approved scene
pictures. One approved MP4 per opted-in scene; nothing is overwritten; approval picks
the one that counts. Off by default — the user enables the feature globally then toggles
per scene."""
import asyncio
import base64
import time

import httpx

from story import db, settings as settings_mod
from story2 import planner, storyboard, store as plan_store
from story2.scene_schemas import NEEDS_ASSET

from . import scenes, store
from .voice import MediaError

KIND = "clip"
DEFAULT_SECONDS = 60          # estimated wall time per clip (~40-60s observed)
MAX_DURATION = 5.0
MIN_DURATION = 2.0

CLIP_CAMERA = {
    "zoom_in":   "slow dolly-in",
    "zoom_out":  "slow dolly-out, drone pullback",
    "pan_right": "slow pan right",
    "pan_left":  "slow pan left",
    "pan_up":    "slow tilt upward",
    "pan_down":  "slow tilt downward",
    "drift":     "subtle camera drift, nearly static",
    "hold":      "static camera",
    "settle":    "static camera",
}

NEGATIVE = "flickering, face warp, warped hands, artifacts, blur, jumpcut, distortion"


# ── settings ─────────────────────────────────────────────────────────────────

def settings(plan: dict) -> dict:
    cur = plan["settings"].get("motion_clips") or {}
    return {"enabled": bool(cur.get("enabled", False))}


DEFAULT_BUDGET = 8                      # motion clips per film: the hook, each reveal and the climax (task 5.2)


def choose_scenes(plan_id: str, budget: int | None = None) -> list[str]:
    """Mark the scenes that deserve a moving clip: the first picture of the film, the pictures of reveal events, and the last picture before the end; at most `budget` (plan setting
    `clip_budget`), spread over the film, never a built card. Only when motion clips are switched on for the plan. Returns the scene ids marked."""
    from story2 import events as events_mod, storyboard
    plan = planner.get_plan(plan_id)
    if not settings(plan)["enabled"]:
        return []
    budget = int(budget or plan["settings"].get("clip_budget") or DEFAULT_BUDGET)
    scenes = [s for s in sorted(storyboard.get_scenes(plan_id), key=lambda x: (x["start_s"], x["seq"])) if s["data"].get("visual_type") not in NEEDS_ASSET and not s["locked"]]
    if not scenes:
        return []
    reveal = {e["id"] for e in events_mod.of(plan) if e.get("reveal")}
    want = [scenes[0]["id"]] + [s["id"] for s in scenes[1:-1] if s["data"].get("event") in reveal] + [scenes[-1]["id"]]
    if len(want) > budget:
        keep = {want[0], want[-1]}
        mid = want[1:-1]
        step = max(1, len(mid) // max(1, budget - 2))
        keep |= set(mid[::step][:max(0, budget - 2)])
        want = [w for w in want if w in keep]
    for s in scenes:
        d = dict(s["data"])
        if bool(d.get("motion_clip")) != (s["id"] in want):
            d["motion_clip"] = s["id"] in want
            db.ex("UPDATE scenes SET data=?, rev=rev+1, updated_at=? WHERE id=?", (db.jdump(d), db.now(), s["id"]))
    return want


def set_settings(plan_id: str, patch: dict) -> None:
    plan = planner.get_plan(plan_id)
    cur = {**(plan["settings"].get("motion_clips") or {})}
    if "enabled" in patch:
        cur["enabled"] = bool(patch["enabled"])
    db.ex("UPDATE plans SET settings=?, updated_at=? WHERE id=?",
          (db.jdump({**plan["settings"], "motion_clips": cur}), db.now(), plan_id))
    plan_store.log(plan_id, "motion_clips_settings", dict(patch))


# ── eligibility ───────────────────────────────────────────────────────────────

def eligible(scene: dict) -> bool:
    """True when the user opted this scene in AND it is not a card/asset type."""
    return bool(scene["data"].get("motion_clip")) and \
           scene["data"].get("visual_type") not in NEEDS_ASSET


# ── prompt construction ───────────────────────────────────────────────────────

def _clip_prompt(scene: dict) -> str:
    d = scene["data"]
    subject = (d.get("subject") or "").strip()
    action  = (d.get("action") or "").strip()
    move    = ((d.get("direction") or {}).get("move") or "").strip()
    cam     = CLIP_CAMERA.get(move, "slow camera movement")
    parts   = [p for p in [subject, action, cam] if p]
    return ". ".join(parts) + ". Slow motion, cinematic, preserve original look."


# ── image helper ──────────────────────────────────────────────────────────────

def _image_b64(plan_id: str, scene_id: str, item_id: str | None = None) -> str | None:
    """Base64 JPEG of a scene picture. Uses item_id if given, else latest done picture."""
    if item_id:
        it = store.get(item_id)
    else:
        done = [i for i in store.items(plan_id, scenes.KIND, scene_id)
                if i["status"] == "done" and i["file"]]
        it = done[-1] if done else None
    if not it or not it["file"]:
        return None
    p = store.path_of(it)
    return base64.b64encode(p.read_bytes()).decode() if p.is_file() else None


# ── state ─────────────────────────────────────────────────────────────────────

def state(plan_id: str) -> dict:
    """All opted-in scenes with their clip attempts, best, approved, and done flag."""
    plan    = planner.get_plan(plan_id)
    sc_list = storyboard.get_scenes(plan_id)
    opted   = [sc for sc in sc_list if eligible(sc)]
    rows    = []
    for sc in opted:
        its      = store.items(plan_id, KIND, sc["id"])
        done_its = [i for i in its if i["status"] == "done" and i["file"]]
        approved = next((i["id"] for i in its if i["approved"] and i["status"] == "done"), None)
        best     = done_its[-1]["id"] if done_its else None
        rows.append({
            "id": sc["id"],
            "seq": sc["seq"],
            "candidates": its,
            "best": best,
            "approved": approved,
            "approved_current": bool(approved),
        })
    total = len(rows)
    appr  = sum(1 for r in rows if r["approved_current"])
    return {
        "scenes": rows,
        "total": total,
        "have": sum(1 for r in rows if r["best"]),
        "approved": appr,
        "done": total > 0 and appr == total,
        "enabled": settings(plan)["enabled"],
    }


def approved_clips(plan_id: str) -> dict[str, dict]:
    """scene_id -> approved clip media row. Used by video.visual_choices()."""
    out = {}
    for row in state(plan_id)["scenes"]:
        if row["approved_current"]:
            it = store.get(row["approved"])
            if it:
                out[row["id"]] = it
    return out


# ── generation ────────────────────────────────────────────────────────────────

async def generate(plan_id: str, scene_ids: list[str] | None,
                   progress, s: dict | None = None, api_key: str = "") -> None:
    """Generate one clip per opted-in scene (auto-run path)."""
    s       = s or settings_mod.get()
    api_key = api_key or settings_mod.api_key()
    plan    = planner.get_plan(plan_id)
    if not settings(plan)["enabled"]:
        return
    sc_list = storyboard.get_scenes(plan_id)
    targets = [sc for sc in sc_list
               if eligible(sc) and (scene_ids is None or sc["id"] in scene_ids)]

    base_url = s.get("base_url", "http://127.0.0.1:8810/v1").rstrip("/")
    headers  = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    for n, sc in enumerate(targets):
        if progress:
            progress(n, len(targets),
                     f"clip {n + 1} of {len(targets)}: {sc['data'].get('subject', '')[:40]}")
        img_b64 = _image_b64(plan_id, sc["id"])
        if not img_b64:
            continue  # no picture yet — skip silently

        prompt   = _clip_prompt(sc)
        duration = max(MIN_DURATION, min(MAX_DURATION, float(sc.get("duration_s") or MAX_DURATION)))
        payload  = {
            "model": "wan-2.2-ti2v-5b",
            "image": f"data:image/jpeg;base64,{img_b64}",
            "prompt": prompt,
            "negative_prompt": NEGATIVE,
            "size": "832x480",
            "duration": round(duration, 1),
            "fps": 24,
            "steps": 25,
            "guidance": 6,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{base_url}/video/generations",
                                  headers=headers, json=payload)
        if r.status_code not in (200, 202):
            raise MediaError(
                f"clip job failed for scene {sc['id']}: HTTP {r.status_code}: {r.text[:200]}")

        job    = r.json()
        job_id = job.get("id") or job.get("job_id")
        if not job_id:
            raise MediaError(f"no job id in clip response: {r.text[:200]}")

        it     = store.add(plan_id, KIND, sc["id"],
                           meta={"job_id": job_id, "prompt": prompt})
        mp4_url = await _poll(job_id, base_url, headers)

        async with httpx.AsyncClient(timeout=120) as client:
            dl = await client.get(mp4_url)
        dl.raise_for_status()

        fname = f"clip/{sc['id']}-a{it['attempt']}.mp4"
        out   = store.media_dir(plan_id) / fname
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(dl.content)
        store.update(it["id"], status="done", file=fname,
                     meta={"job_id": job_id, "prompt": prompt,
                           "duration_s": duration, "source_scene": sc["id"]})


async def generate_scene(plan_id: str, scene_id: str, item_id: str | None,
                         progress, s: dict | None = None, api_key: str = "") -> None:
    """Generate a clip for one scene from a specific image (or latest done one). No enabled/eligible check — manual trigger."""
    s       = s or settings_mod.get()
    api_key = api_key or settings_mod.api_key()
    sc_list = storyboard.get_scenes(plan_id)
    sc      = next((sc for sc in sc_list if sc["id"] == scene_id), None)
    if not sc:
        raise MediaError(f"scene {scene_id} not found")
    img_b64 = _image_b64(plan_id, scene_id, item_id)
    if not img_b64:
        raise MediaError("no picture available for this scene yet")
    base_url = s.get("base_url", "http://127.0.0.1:8810/v1").rstrip("/")
    headers  = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if progress:
        progress(0, 1, f"animating: {sc['data'].get('subject', '')[:40]}")
    prompt   = _clip_prompt(sc)
    duration = max(MIN_DURATION, min(MAX_DURATION, float(sc.get("duration_s") or MAX_DURATION)))
    payload  = {
        "model": "wan-2.2-ti2v-5b",
        "image": f"data:image/jpeg;base64,{img_b64}",
        "prompt": prompt, "negative_prompt": NEGATIVE,
        "size": "832x480", "duration": round(duration, 1),
        "fps": 24, "steps": 25, "guidance": 6,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{base_url}/video/generations", headers=headers, json=payload)
    if r.status_code not in (200, 202):
        raise MediaError(f"clip job failed: HTTP {r.status_code}: {r.text[:200]}")
    job    = r.json()
    job_id = job.get("id") or job.get("job_id")
    if not job_id:
        raise MediaError(f"no job id in clip response: {r.text[:200]}")
    it      = store.add(plan_id, KIND, scene_id, meta={"job_id": job_id, "prompt": prompt, "source_item": item_id})
    mp4_url = await _poll(job_id, base_url, headers)
    async with httpx.AsyncClient(timeout=120) as client:
        dl = await client.get(mp4_url)
    dl.raise_for_status()
    fname = f"clip/{scene_id}-a{it['attempt']}.mp4"
    out   = store.media_dir(plan_id) / fname
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(dl.content)
    store.update(it["id"], status="done", file=fname,
                 meta={"job_id": job_id, "prompt": prompt,
                       "duration_s": duration, "source_scene": scene_id, "source_item": item_id})


async def _poll(job_id: str, base_url: str, headers: dict, timeout: int = 300) -> str:
    """Poll GET /v1/jobs/{job_id} until succeeded; return the video URL."""
    deadline = time.time() + timeout
    async with httpx.AsyncClient(timeout=15) as client:
        while time.time() < deadline:
            r = await client.get(f"{base_url}/jobs/{job_id}", headers=headers)
            r.raise_for_status()
            j      = r.json()
            status = j.get("status", "")
            if status == "succeeded":
                url = j.get("url") or (j.get("result") or {}).get("url")
                if not url:
                    raise MediaError(f"job {job_id} succeeded but no URL in response")
                return url
            if status in ("failed", "cancelled"):
                raise MediaError(f"clip job {job_id} {status}: {j.get('error', '')}")
            retry = float(r.headers.get("Retry-After", 5))
            await asyncio.sleep(retry)
    raise MediaError(f"clip job {job_id} timed out after {timeout}s")


# ── approval ──────────────────────────────────────────────────────────────────

def approve(item_id: str) -> dict:
    return store.approve(item_id, True)


def unapprove(item_id: str) -> dict:
    return store.approve(item_id, False)


def approve_best(plan_id: str) -> int:
    """Approve the latest done clip for every opted-in scene with no approved clip."""
    n = 0
    for row in state(plan_id)["scenes"]:
        if not row["approved_current"] and row["best"]:
            store.approve(row["best"], True)
            n += 1
    return n
