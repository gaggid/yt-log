"""Batch F: reference images. A recurring person, place or prop is drawn once, the editor approves one picture, and every later scene that shows
it is conditioned on that picture (edit mode, at most three references) so it looks the same each time. Candidates are numbered attempts; nothing is
overwritten. The prompt is built from the asset's approved description and fixed details and the plan's style asset, never from the story source."""
import asyncio
import base64
import hashlib
import time

import httpx

from story import db, settings as settings_mod
from story2 import imgplan, imgprompts, intake, leak, planner, providers, storyboard, store as plan_store

from . import refscore, store
from .voice import MediaError

RETRIES = 1
DEFAULT_CANDIDATES = 2
DEFAULT_SECONDS = 60                    # until the first picture has been timed on this machine
MIN_SCENES = 2                          # an asset shown once needs no reference: its one scene creates it
SIZES = {"person": (1024, 1344), "narrator": (1024, 1344), "place": (1344, 768), "prop": (1024, 1024)}
KINDS = ("person", "place", "prop")

KIND_FRAME = {
    "person": "Character reference picture for an animated explainer. One figure, whole body visible, standing in a relaxed neutral pose, plain soft grey studio backdrop with even lighting.",
    "place": "Location reference picture for an animated explainer. An establishing view that shows the layout and main materials clearly, empty of people, even readable lighting.",
    "prop": "Object reference picture for an animated explainer. One object, whole object visible and centred with generous margin, isolated on a plain soft grey studio backdrop, even lighting.",
}
NO_TEXT = "No text, letters, numbers, labels, logos or watermarks anywhere in the picture."
NEGATIVE = "text, letters, numbers, labels, logo, watermark, caption, blurry, low quality, extra limbs, deformed hands, duplicate subject, cropped subject"


def _s(x) -> str:
    return imgprompts._s(x)


def targets(plan_id: str) -> list[dict]:
    """Assets that need a reference: person, place or prop shown in at least MIN_SCENES scenes, with how often and where they first appear."""
    scenes = storyboard.get_scenes(plan_id)
    use: dict[str, list[dict]] = {}
    for sc in sorted(scenes, key=lambda x: (x["start_s"], x["seq"])):
        for a in sc["data"].get("continuity", {}).get("assets", []):
            use.setdefault(a, []).append(sc)
    out = []
    for a in storyboard.get_assets(plan_id):
        if a["kind"] in KINDS and len(use.get(a["id"], [])) >= MIN_SCENES:
            out.append({"asset": a, "scenes": use[a["id"]]})
    out.sort(key=lambda t: (-len(t["scenes"]), t["asset"]["name"]))
    return out


def style_text(plan_id: str) -> str:
    st = next((a for a in storyboard.get_assets(plan_id) if a["kind"] == "style"), None)
    return _s(st["data"].get("description")) if st else ""


def _anonymous(a: dict) -> bool:
    d = a["data"]
    return d.get("fictionalisation") == "real_person_no_likeness" or "anonymous" in _s(d.get("description")).lower()


def build_prompt(a: dict, style: str, model: str) -> dict:
    """The reference prompt for one asset, in the wording the chosen model works best with. Exclusions are stated in the prompt for Qwen (its
    negative field has no effect) and sent as a negative prompt for FLUX."""
    d = a["data"]
    kind = a["kind"]
    parts = [KIND_FRAME[kind], f"Subject: {_s(a['name'])}. {_s(d.get('description'))}".strip()]
    if _s(d.get("period")):
        parts.append(f"Period: {_s(d['period'])}.")
    fixed = [_s(x) for x in d.get("fixed", []) if _s(x)]
    if fixed:
        parts.append("Always the same, so show clearly: " + "; ".join(fixed) + ".")
    if kind == "person" and _anonymous(a):
        parts.append("Keep the person anonymous: seen from behind or in profile, no recognisable face.")
    if style:
        parts.append(f"Visual style: {style}")
    cfg = providers.get(model)
    if cfg["negative_prompt"]:
        parts.append(NO_TEXT)
        neg = NEGATIVE
    else:
        parts.append(NO_TEXT + " Sharp, clean, uncluttered, no duplicate subject.")
        neg = ""
    w, h = SIZES[kind]
    w, h, _ = providers.snap(w, h, cfg)
    prompt = " ".join(p if p.endswith((".", "!", "?")) else p + "." for p in (x.strip() for x in parts) if p)
    return {"prompt": prompt, "negative_prompt": neg, "width": w, "height": h, "model": model}


def asset_hash(a: dict, style: str, model: str) -> str:
    """What a picture was made from. If the asset's description or fixed details, the style or the model change, older pictures stop counting as current."""
    d = a["data"]
    key = "|".join([model, _s(a["name"]), _s(d.get("description")), ";".join(map(_s, d.get("fixed", []))), _s(d.get("period")), d.get("fictionalisation", ""), style])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def seed_for(asset_id: str, attempt: int) -> int:
    return int(hashlib.sha1(asset_id.encode()).hexdigest()[:6], 16) % 90000 + 1009 * (attempt - 1)


def skipped(plan: dict) -> set[str]:
    return set((plan["settings"].get("reference_skips") or []))


def set_skip(plan_id: str, asset_id: str, on: bool) -> dict:
    plan = planner.get_plan(plan_id)
    if not any(t["asset"]["id"] == asset_id for t in targets(plan_id)):
        raise MediaError("that asset does not need a reference image")
    cur = skipped(plan)
    cur.add(asset_id) if on else cur.discard(asset_id)
    db.ex("UPDATE plans SET settings=?, updated_at=? WHERE id=?", (db.jdump({**plan["settings"], "reference_skips": sorted(cur)}), db.now(), plan_id))
    plan_store.log(plan_id, "reference_skip", {"asset": asset_id, "skip": on})
    return state(plan_id)


def current_done(plan_id: str, a: dict, style: str, model: str) -> list[dict]:
    want = asset_hash(a, style, model)
    return [i for i in store.items(plan_id, "reference", a["id"]) if i["status"] == "done" and i["meta"].get("asset_hash") == want]


async def _draw(client: httpx.AsyncClient, base: str, key: str, body: dict) -> dict:
    last = ""
    for n in range(RETRIES + 1):
        try:
            r = await client.post(base.rstrip("/") + "/images/generations", json=body, headers={"Authorization": f"Bearer {key}"})
        except (httpx.TransportError, httpx.TimeoutException) as e:
            last = f"{type(e).__name__}: {e}"
            if isinstance(e, httpx.ConnectError):
                raise MediaError(f"the model server is not reachable ({last})") from e
        else:
            if r.status_code == 200:
                return r.json()["data"][0]
            last = f"{r.status_code} {r.text[:160]}"
            if r.status_code not in (429, 500, 502, 503, 504):
                break
        await asyncio.sleep(4 * (n + 1))
    raise MediaError(last or "no answer from the model server")


async def generate(plan_id: str, asset_ids: list[str] | None = None, candidates: int = DEFAULT_CANDIDATES, only_missing: bool = True,
                   model: str | None = None, progress=None, s: dict | None = None, key: str = "", score: bool = True) -> dict:
    """Make `candidates` pictures for each chosen asset. only_missing skips assets that already have an approved or current picture. When `score`
    is on, each new picture is then measured and looked at (the chat model takes over from the image model once all pictures are drawn)."""
    s = s or settings_mod.get()
    key = key or settings_mod.api_key()
    plan = planner.get_plan(plan_id)
    if not storyboard.get_scenes(plan_id):
        raise MediaError("design the storyboard first: references are made for the people, places and objects it uses")
    model = model or providers.settings_for(plan["settings"])["default"]
    cfg = providers.get(model)
    style = style_text(plan_id)
    story = planner._story_for(plan)
    prof = leak.profile(story["evidence"]["project_id"], story["evidence"]["passages"])
    todo = [t for t in targets(plan_id) if (not asset_ids or t["asset"]["id"] in asset_ids) and t["asset"]["id"] not in skipped(plan)]
    if only_missing:
        todo = [t for t in todo if not current_done(plan_id, t["asset"], style, model)
                and not any(r.get("approved") for r in t["asset"]["data"].get("reference_images", []))]
    candidates = max(1, min(int(candidates), 4))
    jobs = [(t, n) for t in todo for n in range(candidates)]
    made, failed, new_ids = 0, [], []
    exp = None
    try:
        from story2 import export
        ex = export.list_exports(plan_id)
        exp = ex[0]["rev"] if ex else 0
    except Exception:  # noqa: BLE001 - the export only labels the file
        exp = 0
    async with httpx.AsyncClient(timeout=cfg["timeout_s"] + 120) as client:
        for i, (t, _n) in enumerate(jobs):
            a = t["asset"]
            if progress:
                progress(i, len(jobs), f"picture {i + 1} of {len(jobs)}: {a['name']}")
            built = build_prompt(a, style, model)
            it = store.add(plan_id, "reference", a["id"], exp, "running", {"model": model, "asset_hash": asset_hash(a, style, model), "prompt": built["prompt"],
                                                                         "negative_prompt": built["negative_prompt"], "asset_name": a["name"], "asset_kind": a["kind"]})
            hits = leak.check_many([(a["id"], built["prompt"])], prof)
            if hits:
                err = "the prompt would carry source wording: " + "; ".join(str(h.get("text") or h)[:80] for h in hits[:2])
                store.update(it["id"], status="failed", meta={"error": err})
                failed.append({"asset": a["id"], "error": err})
                continue
            seed = seed_for(a["id"], it["attempt"])
            body = {"model": model, "prompt": built["prompt"], "size": f"{built['width']}x{built['height']}", "n": 1, "seed": seed, "response_format": "b64_json"}
            if built["negative_prompt"]:
                body["negative_prompt"] = built["negative_prompt"]
            t0 = time.time()
            try:
                img = await _draw(client, s["base_url"], key, body)
                name = f"refs/{a['id']}-a{it['attempt']}.png"
                (store.media_dir(plan_id, "refs") / f"{a['id']}-a{it['attempt']}.png").write_bytes(base64.b64decode(img["b64_json"]))
                store.update(it["id"], status="done", file=name, meta={"seed": img.get("seed", seed), "width": img.get("width"), "height": img.get("height"),
                                                                       "seconds_taken": round(time.time() - t0, 1), "request": {k: v for k, v in body.items() if k not in ("prompt", "negative_prompt")}})
                made += 1
                new_ids.append(it["id"])
            except asyncio.CancelledError:
                store.update(it["id"], status="failed", meta={"error": "stopped before it finished"})
                raise
            except MediaError as e:
                store.update(it["id"], status="failed", meta={"error": str(e)[:300], "seconds_taken": round(time.time() - t0, 1)})
                failed.append({"asset": a["id"], "error": str(e)[:200]})
                if "not reachable" in str(e):
                    break
    scored = 0
    if score and new_ids:
        scored = (await score_items(plan_id, new_ids, progress, s, key))["scored"]
    if progress:
        progress(len(jobs), len(jobs), "done")
    plan_store.log(plan_id, "references", {"made": made, "failed": len(failed), "model": model, "scored": scored})
    return {"made": made, "failed": failed, "assets": len(todo), "scored": scored}


async def score_items(plan_id: str, item_ids: list[str] | None = None, progress=None, s: dict | None = None, key: str = "") -> dict:
    """Measure and look at finished pictures that have no score yet (or the ones named). A failed vision check keeps the measured score and says so."""
    s = s or settings_mod.get()
    style = style_text(plan_id)
    by_id = {t["asset"]["id"]: t["asset"] for t in targets(plan_id)}
    todo = [i for i in store.items(plan_id, "reference") if i["status"] == "done" and i["key"] in by_id
            and (i["id"] in item_ids if item_ids else not i["meta"].get("score"))]
    done, vision_down = 0, False
    for n, it in enumerate(todo):
        if progress:
            progress(n, len(todo), f"checking picture {n + 1} of {len(todo)}")
        a = by_id[it["key"]]
        asked = (it["meta"].get("request") or {}).get("size")
        auto = refscore.measure(store.path_of(it), a["kind"], tuple(int(v) for v in asked.split("x")) if asked else None)
        seen, note = None, ""
        if not vision_down:
            try:
                seen = await refscore.look(store.path_of(it), {"name": a["name"], "kind": a["kind"], "description": _s(a["data"].get("description")), "fixed": a["data"].get("fixed", [])}, style, s, key)
            except Exception as e:  # noqa: BLE001 - reported on the picture; scoring continues with measured facts only
                vision_down, note = True, f"vision check unavailable: {str(e)[:120]}"
        else:
            note = "vision check unavailable"
        sc = refscore.combine(auto, seen)
        sc["note"] = note
        store.update(it["id"], meta={"score": sc, "scored_at": db.now()})
        done += 1
    return {"scored": done}


def best(plan_id: str, row_candidates: list[dict]) -> dict | None:
    """The best current finished picture of one item: highest total, then fewest flags, then the earlier attempt."""
    cands = [c for c in row_candidates if c["status"] == "done" and c["current"] and c.get("score")]
    return min(cands, key=lambda c: (-c["score"]["total"], len(c["score"]["flags"]), c["attempt"])) if cands else None


def approve_best(plan_id: str, min_score: int = refscore.AUTO_APPROVE_MIN) -> dict:
    """Approve, for every item still open, its best picture, but only when it scores at least `min_score` and has no hard problem. The rest are
    left for a person. Prompts are recompiled once at the end."""
    st = state(plan_id)
    chosen, left = [], []
    for r in st["assets"]:
        if r["approved"] or r["skipped"]:
            continue
        b = best(plan_id, r["candidates"])
        if b and b["score"]["total"] >= min_score and not b["score"]["hard"]:
            chosen.append((r["asset_id"], b["id"]))
        else:
            left.append({"asset": r["name"], "why": "no picture scored yet" if not b else "best picture has a problem" if b["score"]["hard"] else f"best score {b['score']['total']} is under {min_score}"})
    for aid, iid in chosen:
        store.approve(iid, True)
        it = store.get(iid)
        _write_asset(aid, [{"id": it["id"], "file": it["file"], "approved": True, "note": f"attempt {it['attempt']}, seed {it['meta'].get('seed')}, score {it['meta']['score']['total']}"}])
        plan_store.log(plan_id, "reference_approved", {"asset": aid, "item": iid, "bulk": True})
    if chosen:
        imgplan.compile_plan(plan_id)
    return {"approved": len(chosen), "left": left, "state": state(plan_id)}


def _write_asset(asset_id: str, entries: list[dict]) -> None:
    a = db.one("SELECT * FROM assets WHERE id=?", (asset_id,))
    data = db.jload(a["data"], {})
    data["reference_images"] = entries
    db.ex("UPDATE assets SET data=?, rev=rev+1, updated_at=? WHERE id=?", (db.jdump(data), db.now(), asset_id))


def approve(item_id: str, on: bool = True) -> dict:
    """Approve a picture as its asset's reference (or take the approval away). The asset record gets the picture and the image prompts are
    recompiled, so the scenes showing the asset switch to reference-conditioned edit mode. Scene wording is never touched."""
    it = store.get(item_id)
    if not it or it["kind"] != "reference":
        raise MediaError("not a reference picture")
    if on and it["status"] != "done":
        raise MediaError("only a finished picture can be approved")
    store.approve(item_id, on)
    _write_asset(it["key"], [{"id": it["id"], "file": it["file"], "approved": True, "note": f"attempt {it['attempt']}, seed {it['meta'].get('seed')}"}] if on else [])
    plan_store.log(it["plan_id"], "reference_approved" if on else "reference_unapproved", {"asset": it["key"], "item": item_id})
    imgplan.compile_plan(it["plan_id"])
    return state(it["plan_id"])


def state(plan_id: str) -> dict:
    plan = planner.get_plan(plan_id)
    style = style_text(plan_id)
    model = providers.settings_for(plan["settings"])["default"]
    skips = skipped(plan)
    rows, secs = [], []
    for t in targets(plan_id):
        a = t["asset"]
        want = asset_hash(a, style, model)
        att = store.items(plan_id, "reference", a["id"])
        ok = [i for i in att if i["approved"] and i["status"] == "done"]
        built = build_prompt(a, style, model)
        for i in att:
            if i["status"] == "done" and i["meta"].get("seconds_taken"):
                secs.append(i["meta"]["seconds_taken"])
        rows.append({"asset_id": a["id"], "name": a["name"], "kind": a["kind"], "description": _s(a["data"].get("description")),
                     "fixed": a["data"].get("fixed", []), "fictionalisation": a["data"].get("fictionalisation", ""),
                     "scenes": len(t["scenes"]), "first_scene": t["scenes"][0]["id"], "skipped": a["id"] in skips,
                     "approved": ok[0]["id"] if ok else None, "prompt": built["prompt"], "negative_prompt": built["negative_prompt"],
                     "size": f"{built['width']}x{built['height']}",
                     "candidates": [{"id": i["id"], "attempt": i["attempt"], "status": i["status"], "approved": i["approved"],
                                     "url": f"/api/media/file/{plan_id}/{i['file']}" if i["file"] else "", "current": i["meta"].get("asset_hash") == want,
                                     "model": i["meta"].get("model"), "seed": i["meta"].get("seed"), "seconds_taken": i["meta"].get("seconds_taken"),
                                     "error": i["meta"].get("error", ""), "score": i["meta"].get("score")} for i in att]})
    for r in rows:
        b = best(plan_id, r["candidates"])
        r["best"] = b["id"] if b else None
    per = sum(secs) / len(secs) if secs else DEFAULT_SECONDS
    open_rows = [r for r in rows if not r["approved"] and not r["skipped"]]
    need_pics = [r for r in open_rows if not any(c["status"] == "done" and c["current"] for c in r["candidates"])]
    edit_scenes = sum(1 for sc in storyboard.get_scenes(plan_id) if any((c or {}).get("mode") == "edit" for c in (sc["data"].get("prompts") or {}).values()))
    return {"model": model, "assets": rows, "total": len(rows), "approved": sum(1 for r in rows if r["approved"]), "skipped": sum(1 for r in rows if r["skipped"]),
            "open": len(open_rows), "unscored": sum(1 for r in rows for c in r["candidates"] if c["status"] == "done" and not c.get("score")),
            "bulk_ready": sum(1 for r in open_rows if (lambda b: b and b["score"]["total"] >= refscore.AUTO_APPROVE_MIN and not b["score"]["hard"])(best(plan_id, r["candidates"]))),
            "min_score": refscore.AUTO_APPROVE_MIN, "without_pictures": len(need_pics), "seconds_per_picture": round(per), "default_candidates": DEFAULT_CANDIDATES,
            "eta_missing_s": round(len(need_pics) * DEFAULT_CANDIDATES * per), "scenes_using_references": edit_scenes,
            "done": bool(rows) and not open_rows, "style": style}
