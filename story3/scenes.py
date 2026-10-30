"""Batch G: scene pictures. One approved picture per scene, drawn from the scene's compiled prompt (plain generation) or from that prompt plus the
approved reference sheets (edit mode, up to three references). Which of the two keeps the characters identical is settled by a three-scene trial
that draws both ways on both models; the editor's choice is stored on the plan and used for the full run. Pictures are numbered attempts, nothing
is overwritten, and an approved picture is never replaced by "draw all"."""
import asyncio
import base64
import hashlib
import time

import httpx

from story import db, settings as settings_mod
from story2 import imgprompts, leak, planner, providers, storyboard, store as plan_store

from . import refscore, store
from .voice import MediaError

KIND = "scene_image"
RETRIES = 1
DEFAULT_SECONDS = {"qwen-image-2.1": 40, "flux2-klein-9b": 120}
MODES = ("generate", "edit", "auto")                    # auto: edit when the scene has approved reference sheets, else generate
TRIAL_SCENES = 3


def _s(x) -> str:
    return imgprompts._s(x)


# ── what a scene needs ──────────────────────────────────────────────────────

def settings(plan: dict) -> dict:
    cur = (plan["settings"].get("scene_pictures") or {})
    return {"mode": cur.get("mode") if cur.get("mode") in MODES else "generate",
            "model": cur.get("model") if cur.get("model") in providers.PROVIDERS else None,
            "candidates": max(1, min(int(cur.get("candidates") or 1), 4)),
            "chosen": bool(cur.get("chosen")), "trial": list(cur.get("trial") or []),
            "per_scene": {k: {"model": v.get("model") if v.get("model") in providers.PROVIDERS else None, "mode": v.get("mode") if v.get("mode") in ("generate", "edit") else None}
                          for k, v in (cur.get("per_scene") or {}).items() if isinstance(v, dict)}}


def set_settings(plan_id: str, patch: dict) -> dict:
    plan = planner.get_plan(plan_id)
    cur = {**(plan["settings"].get("scene_pictures") or {})}
    if "mode" in patch:
        if patch["mode"] not in MODES:
            raise MediaError("mode must be generate, edit or auto")
        cur["mode"] = patch["mode"]
    if "model" in patch:
        if patch["model"]:
            _known(patch["model"])
        cur["model"] = patch["model"] or None
    if "candidates" in patch:
        cur["candidates"] = max(1, min(int(patch["candidates"]), 4))
    if "chosen" in patch:
        cur["chosen"] = bool(patch["chosen"])
    if "trial" in patch:
        cur["trial"] = list(patch["trial"])
    db.ex("UPDATE plans SET settings=?, updated_at=? WHERE id=?", (db.jdump({**plan["settings"], "scene_pictures": cur}), db.now(), plan_id))
    plan_store.log(plan_id, "scene_picture_settings", dict(patch))
    return state(plan_id)


def _known(model: str) -> None:
    if model not in providers.PROVIDERS:
        raise MediaError(f"unknown image model '{model}' (known: {', '.join(providers.PROVIDERS)})")


def model_for(scene: dict, plan: dict) -> str:
    """The model chosen for this scene by a person, else the plan's scene-picture model, else the scene's own or the plan's image model."""
    st = settings(plan)
    return (st["per_scene"].get(scene["id"]) or {}).get("model") or st["model"] or providers.model_for(scene["data"], plan["settings"])


def mode_for(scene: dict, plan: dict) -> str:
    """plain (generate) or from the reference sheets (edit/auto) for this scene: its own choice first, then the plan's."""
    st = settings(plan)
    return (st["per_scene"].get(scene["id"]) or {}).get("mode") or st["mode"]


def remember_choice(plan_id: str, scene_id: str, model: str | None, mode: str | None) -> None:
    plan = planner.get_plan(plan_id)
    cur = {**(plan["settings"].get("scene_pictures") or {})}
    per = {**(cur.get("per_scene") or {})}
    per[scene_id] = {"model": model, "mode": mode}
    cur["per_scene"] = per
    db.ex("UPDATE plans SET settings=?, updated_at=? WHERE id=?", (db.jdump({**plan["settings"], "scene_pictures": cur}), db.now(), plan_id))


def compiled(scene: dict, model: str) -> dict | None:
    return (scene["data"].get("prompts") or {}).get(providers.get(model)["adapter"])


def quoted_texts(scene: dict) -> list[str]:
    shown, _ = imgprompts._exact_text(scene["data"], [])
    return [_s(t["text"]) for t in shown]


def resolve_mode(mode: str, c: dict) -> str:
    """The mode a picture is really drawn in. Edit needs references; without any it falls back to plain generation."""
    if mode == "generate" or not c.get("references"):
        return "generate"
    return "edit"


def reference_files(c: dict) -> list:
    """Approved reference sheets in the order the compiled prompt names them (Image 1, Image 2, ...)."""
    out = []
    for r in c.get("references", []):
        it = store.get(r.get("image_id") or "")
        if it and it["status"] == "done" and it["file"] and store.path_of(it).is_file():
            out.append((r, store.path_of(it)))
    return out


def seed_for(scene_id: str, attempt: int) -> int:
    return int(hashlib.sha1(scene_id.encode()).hexdigest()[:6], 16) % 90000 + 1013 * (attempt - 1)


def story_context(plan_id: str) -> str:
    """What the whole video is about, in our own words, so the check can tell a picture that belongs to this story from a generic one."""
    plan = planner.get_plan(plan_id)
    pub = planner._story_for(plan)["public"]
    era = sorted({_s(a["data"].get("period")) for a in storyboard.get_assets(plan_id) if _s(a["data"].get("period"))})
    return " ".join(x for x in [f"STORY: {_s(pub.get('premise'))}", f"Period: {', '.join(era)}." if era else ""] if x.strip())


def narration_for(scene: dict, plan: dict) -> str:
    seg = next((s_ for s_ in plan["segments"] if s_["id"] == scene["segment_id"]), None)
    if not seg:
        return ""
    sents = [x["text"] for x in seg["sentences"]][max(0, scene["s_from"] - 1):scene["s_to"]]
    return " ".join(_s(x) for x in sents)


def brief(scene: dict, assets: list[dict], style: str, context: str = "", narration: str = "") -> str:
    d = scene["data"]
    people = [a for a in imgprompts.assets_for(scene, assets) if a["kind"] in ("person", "narrator", "place", "prop")]
    who = "; ".join(f"{a['name']}: {_s(a['data'].get('description'))}" for a in people)
    q = quoted_texts(scene)
    ev = d.get("event")
    moment = " ".join(x for x in (_s(d.get("action")), (f"key object: {_s(d['layers'].get('foreground'))}" if (d.get("layers") or {}).get("foreground") else "")) if x) if ev else ""
    return " ".join(x for x in [
        context, f"Narration for this moment: {narration}" if narration else "", f"Subject: {_s(d.get('subject'))}.", f"Action: {_s(d.get('action'))}." if _s(d.get("action")) else "",
        f"Setting: {_val(d, 'setting', 'location')}. Period: {_val(d, 'setting', 'period')}." if _val(d, "setting", "location") else "",
        f"Lighting: {_s(d.get('lighting'))}." if _s(d.get("lighting")) else "", f"People, places and objects that may appear: {who}." if who else "No recurring people or objects.",
        f"The moment to show: {moment}." if moment else "",
        ("The picture must contain exactly these words and no other text: " + "; ".join(f'"{t}"' for t in q) + ".") if q else "The picture must contain no readable text, letters or numbers.",
        f"Style: {style}" if style else ""] if x)


def _val(d: dict, *path) -> str:
    return _s(imgprompts._g(d, *path))


# ── the request ─────────────────────────────────────────────────────────────

async def _post(client: httpx.AsyncClient, url: str, key: str, **kw) -> dict:
    last = ""
    for n in range(RETRIES + 1):
        try:
            r = await client.post(url, headers={"Authorization": f"Bearer {key}"}, **kw)
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


def _form(model: str, prompt: str, size: str, seed: int, files: list, steps: int | None = None, lora: list | None = None) -> tuple[dict, list]:
    """Edit request: multipart, the first image is the one that is edited, then the other references. Every image goes in the field `image`."""
    import json as _json
    w, h = size.split("x")
    data = {"model": model, "prompt": prompt, "size": size, "width": w, "height": h, "seed": str(seed), "n": "1", "response_format": "b64_json"}
    if steps:
        data["steps"] = str(steps)
    if lora:
        data["lora"] = _json.dumps(lora)
    return data, [("image", (p.name, p.read_bytes(), "image/png")) for p in files]


async def draw(client: httpx.AsyncClient, s: dict, key: str, model: str, c: dict, mode: str, seed: int, plan: dict, extra_files: list | None = None,
               prompt: str | None = None) -> tuple[dict, dict]:
    """One picture. Returns (gateway answer, the request that was sent without prompt text). `extra_files` go first (the picture being corrected)."""
    size = f"{c['size']['width']}x{c['size']['height']}"
    base = s["base_url"].rstrip("/")
    refs = [p for _r, p in reference_files(c)] if mode == "edit" else []
    files = list(extra_files or []) + refs
    text = prompt or c["prompt"]
    if files:
        data, parts = _form(model, text, size, seed, files[:3])
        req = {k: v for k, v in data.items() if k not in ("prompt",)} | {"images": len(parts)}
        return await _post(client, base + "/images/edits", key, data=data, files=parts), req
    body = {"model": model, "prompt": text, "size": size, "n": 1, "seed": seed, "response_format": "b64_json"}
    if c.get("negative_prompt") and providers.get(model)["negative_prompt"]:
        body["negative_prompt"] = c["negative_prompt"]
    lo = styles_loras(model, plan)
    if lo:
        body["lora"] = lo
    return await _post(client, base + "/images/generations", key, json=body), {k: v for k, v in body.items() if k not in ("prompt", "negative_prompt")}


def styles_loras(model: str, plan: dict):
    from story2 import styles
    return styles.loras_for(model, plan["settings"])


def _eta(model: str, items: list[dict]) -> float:
    secs = [i["meta"]["seconds_taken"] for i in items if i["status"] == "done" and i["meta"].get("model") == model and i["meta"].get("seconds_taken")]
    return sum(secs) / len(secs) if secs else DEFAULT_SECONDS.get(model, 60)


def _export_rev(plan_id: str) -> int:
    try:
        from story2 import export
        ex = export.list_exports(plan_id)
        return ex[0]["rev"] if ex else 0
    except Exception:  # noqa: BLE001 - the export only labels the file
        return 0


def _current(it: dict, c: dict | None) -> bool:
    return bool(c and it["meta"].get("source_hash") == c["source_hash"])


def done_current(plan_id: str, scene: dict, c: dict | None) -> list[dict]:
    return [i for i in store.items(plan_id, KIND, scene["id"]) if i["status"] == "done" and _current(i, c)]


# ── drawing ─────────────────────────────────────────────────────────────────

SECOND_ANGLE = ("Image 1 is the same moment seen from another distance and angle: keep the same people, their clothes, the place, the objects and the light exactly as in Image 1, "
                "and change only the camera as described next. ")


def variant_base(plan_id: str, scene: dict):
    """The picture a second-angle scene continues (task 3.5): the best finished picture of the scene it is a variant of, as a file, or None (the scene is then drawn from its own prompt)."""
    base = (scene["data"] or {}).get("variant_of")
    if not base:
        return None
    done = [i for i in store.items(plan_id, KIND, base) if i["status"] == "done" and i["file"] and store.path_of(i).is_file()]
    done.sort(key=lambda i: (bool(i["approved"]), i["attempt"]), reverse=True)
    return store.path_of(done[0]) if done else None


async def generate(plan_id: str, scene_ids: list[str] | None = None, candidates: int | None = None, only_missing: bool = True, model: str | None = None,
                   mode: str | None = None, progress=None, s: dict | None = None, key: str = "", score: bool = True, variants: list[dict] | None = None) -> dict:
    """Draw pictures for the chosen scenes (all scenes by default). only_missing leaves scenes that are approved or already have a current picture
    alone. `variants` (the trial) is a list of {model, mode}: each scene is drawn once per variant. Requests are grouped by model to limit swaps."""
    s = s or settings_mod.get()
    key = key or settings_mod.api_key()
    plan = planner.get_plan(plan_id)
    st = settings(plan)
    scenes = storyboard.get_scenes(plan_id)
    if not scenes or not all(sc["data"].get("prompts") for sc in scenes):
        raise MediaError("write the image prompts first: pictures are drawn from them")
    assets = storyboard.get_assets(plan_id)
    style = next((_s(a["data"].get("description")) for a in assets if a["kind"] == "style"), "")
    candidates = max(1, min(int(candidates or st["candidates"]), 4))
    mode_unset = not mode
    mode = mode or st["mode"]
    chosen = [sc for sc in sorted(scenes, key=lambda x: (x["start_s"], x["seq"])) if not scene_ids or sc["id"] in scene_ids]
    jobs = []                                                           # (scene, model, mode)
    for sc in chosen:
        for v in variants or [{"model": model or model_for(sc, plan), "mode": mode_for(sc, plan) if mode_unset else mode}]:
            m = v["model"]
            c = compiled(sc, m)
            if not c:
                continue
            if only_missing and not variants and (any(i["approved"] and i["status"] == "done" and _current(i, c) for i in store.items(plan_id, KIND, sc["id"]))
                                                  or done_current(plan_id, sc, c)):
                continue
            for _ in range(1 if variants else candidates):
                jobs.append((sc, m, resolve_mode(v["mode"], c)))
    order = {m: n for n, m in enumerate(dict.fromkeys(m for _sc, m, _mo in jobs))}           # one model after the other
    jobs.sort(key=lambda j: order[j[1]])
    story = planner._story_for(plan)
    prof = leak.profile(story["evidence"]["project_id"], story["evidence"]["passages"])
    exp = _export_rev(plan_id)
    made, failed, new_ids = 0, [], []
    out_dir = store.media_dir(plan_id, "scenes")
    async with httpx.AsyncClient(timeout=700) as client:
        for n, (sc, m, mo) in enumerate(jobs):
            if progress:
                progress(n, len(jobs), f"picture {n + 1} of {len(jobs)}: scene at {int(sc['start_s'] // 60)}:{int(sc['start_s'] % 60):02d} ({providers.get(m)['label']})")
            c = compiled(sc, m)
            it = store.add(plan_id, KIND, sc["id"], exp, "running", {"model": m, "mode": mo, "source_hash": c["source_hash"], "prompt": c["prompt"],
                                                                       "references": [r["name"] for r, _p in reference_files(c)] if mo == "edit" else [],
                                                                       "trial": bool(variants)})
            hits = leak.check_many([(sc["id"], c["prompt"])], prof)
            if hits:
                err = "the prompt would carry source wording: " + "; ".join(str(h.get("text") or h)[:80] for h in hits[:2])
                store.update(it["id"], status="failed", meta={"error": err})
                failed.append({"scene": sc["id"], "error": err})
                continue
            seed = seed_for(sc["id"], it["attempt"])
            t0 = time.time()
            try:
                base_pic = variant_base(plan_id, sc)
                extra, prompt = ([base_pic], SECOND_ANGLE + c["prompt"]) if base_pic else (None, None)
                img, req = await draw(client, s, key, m, c, mo, seed, plan, extra, prompt)
                if base_pic:
                    req = {**req, "second_angle_of": sc["data"]["variant_of"]}
                name = f"scenes/{sc['id']}-a{it['attempt']}.png"
                (out_dir / f"{sc['id']}-a{it['attempt']}.png").write_bytes(base64.b64decode(img["b64_json"]))
                store.update(it["id"], status="done", file=name, meta={"seed": img.get("seed", seed), "width": img.get("width"), "height": img.get("height"),
                                                                     "seconds_taken": round(time.time() - t0, 1), "request": req})
                made += 1
                new_ids.append(it["id"])
            except asyncio.CancelledError:
                store.update(it["id"], status="failed", meta={"error": "stopped before it finished"})
                raise
            except MediaError as e:
                store.update(it["id"], status="failed", meta={"error": str(e)[:300], "seconds_taken": round(time.time() - t0, 1)})
                failed.append({"scene": sc["id"], "error": str(e)[:200]})
                if "not reachable" in str(e):
                    break
    scored = 0
    if score and new_ids:
        scored = (await score_items(plan_id, new_ids, progress, s, key))["scored"]
    if progress:
        progress(len(jobs), len(jobs), "done")
    plan_store.log(plan_id, "scene_pictures", {"made": made, "failed": len(failed), "scored": scored, "trial": bool(variants)})
    return {"made": made, "failed": failed, "scenes": len(chosen), "scored": scored}


def options(plan_id: str, scene_id: str) -> dict:
    """What the redraw panel offers for one scene: every image model with the prompt that model would be sent, whether it can use the reference sheets, and
    the scene's current choice."""
    plan = planner.get_plan(plan_id)
    sc = storyboard.get_scene(scene_id)
    if not sc or sc["plan_id"] != plan_id:
        raise MediaError("no such scene")
    out = {}
    for m in providers.PROVIDERS:
        c = compiled(sc, m)
        if not c:
            continue
        refs = [r["name"] for r in c.get("references", []) if (store.get(r.get("image_id") or "") or {}).get("file")]
        out[m] = {"label": providers.get(m)["label"], "prompt": c["prompt"], "negative_prompt": c.get("negative_prompt", "") if providers.get(m)["negative_prompt"] else "",
                  "negative_used": providers.get(m)["negative_prompt"], "edits": providers.get(m)["edits"], "references": refs,
                  "can_edit": bool(refs) and providers.get(m)["edits"], "size": f"{c['size']['width']}x{c['size']['height']}"}
    st = settings(plan)
    cur = model_for(sc, plan)
    return {"scene_id": scene_id, "models": out, "model": cur, "mode": resolve_mode(mode_for(sc, plan), compiled(sc, cur) or {}),
            "default_model": providers.DEFAULT_MODEL, "remembered": scene_id in st["per_scene"]}


async def redraw(plan_id: str, scene_id: str, model: str, mode: str = "generate", prompt: str | None = None, negative_prompt: str | None = None,
                 candidates: int = 1, remember: bool = False, progress=None, s: dict | None = None, key: str = "", score: bool = True) -> dict:
    """Draw a scene again with the model, mode and prompt a person chose. `prompt` replaces the compiled prompt for these pictures only (the scene's wording
    and its compiled prompts stay as they are); each picture is a new numbered attempt and nothing is overwritten. Mode "edit" sends the scene's approved
    reference sheets and is refused (not silently turned into plain drawing) when the model cannot edit or the scene has none."""
    s = s or settings_mod.get()
    key = key or settings_mod.api_key()
    _known(model)
    if mode not in ("generate", "edit"):
        raise MediaError("mode must be generate (plain) or edit (from the reference sheets)")
    plan = planner.get_plan(plan_id)
    sc = storyboard.get_scene(scene_id)
    if not sc or sc["plan_id"] != plan_id:
        raise MediaError("no such scene")
    c = compiled(sc, model)
    if not c:
        raise MediaError("write the image prompts first")
    if mode == "edit":
        if not providers.get(model)["edits"]:
            raise MediaError(f"{providers.get(model)['label']} cannot use reference pictures; draw plain with it or choose another model")
        if not reference_files(c):
            raise MediaError("this scene has no approved reference sheet: approve one first, or draw plain")
    text = prompt.strip() if prompt and prompt.strip() else c["prompt"]
    custom = text != c["prompt"]
    c = {**c, "negative_prompt": negative_prompt if negative_prompt is not None else c.get("negative_prompt", "")}
    story = planner._story_for(plan)
    prof = leak.profile(story["evidence"]["project_id"], story["evidence"]["passages"])
    hits = leak.check_many([(scene_id, text + " " + c["negative_prompt"])], prof)
    if hits:
        raise MediaError("the prompt would carry source wording: " + "; ".join(str(h.get("text") or h)[:80] for h in hits[:2]))
    if remember:
        remember_choice(plan_id, scene_id, model, mode)
    exp = _export_rev(plan_id)
    out_dir = store.media_dir(plan_id, "scenes")
    n_pics = max(1, min(int(candidates), 4))
    made, failed, new_ids = 0, [], []
    async with httpx.AsyncClient(timeout=700) as client:
        for n in range(n_pics):
            if progress:
                progress(n, n_pics, f"picture {n + 1} of {n_pics} ({providers.get(model)['label']}, {'from the reference sheets' if mode == 'edit' else 'plain'})")
            it = store.add(plan_id, KIND, scene_id, exp, "running", {"model": model, "mode": mode, "source_hash": c["source_hash"], "prompt": text, "custom_prompt": custom,
                                                                       "negative_prompt": c["negative_prompt"], "redraw": True,
                                                                       "references": [r["name"] for r, _p in reference_files(c)] if mode == "edit" else []})
            seed = seed_for(scene_id, it["attempt"])
            t0 = time.time()
            try:
                img, req = await draw(client, s, key, model, c, mode, seed, plan, prompt=text)
                name = f"scenes/{scene_id}-a{it['attempt']}.png"
                (out_dir / f"{scene_id}-a{it['attempt']}.png").write_bytes(base64.b64decode(img["b64_json"]))
                store.update(it["id"], status="done", file=name, meta={"seed": img.get("seed", seed), "width": img.get("width"), "height": img.get("height"),
                                                                     "seconds_taken": round(time.time() - t0, 1), "request": req})
                made += 1
                new_ids.append(it["id"])
            except asyncio.CancelledError:
                store.update(it["id"], status="failed", meta={"error": "stopped before it finished"})
                raise
            except MediaError as e:
                store.update(it["id"], status="failed", meta={"error": str(e)[:300], "seconds_taken": round(time.time() - t0, 1)})
                failed.append({"scene": scene_id, "error": str(e)[:200]})
                if "not reachable" in str(e):
                    break
    scored = (await score_items(plan_id, new_ids, progress, s, key))["scored"] if score and new_ids else 0
    plan_store.log(plan_id, "scene_picture_redrawn", {"scene": scene_id, "model": model, "mode": mode, "custom": custom, "made": made})
    if progress:
        progress(n_pics, n_pics, "done")
    return {"made": made, "failed": failed, "scored": scored, "items": new_ids}


def change_for(row: dict, note: str = "") -> str:
    """What to ask a correction for, from the judge's own words about the best picture so far (task 4.6): remove what the brief did not ask for, fix the defects it saw, and
    change the picture if it duplicates another. Empty when the picture has nothing to correct."""
    best = row.get("best_item") or {}
    sc = best.get("score") or {}
    flags = [f for f in sc.get("flags", []) if not f.startswith("a stray letter")]
    extras = [f[len("not in the brief: "):] for f in flags if f.startswith("not in the brief: ")]
    bad = [f[len("looks wrong: "):] for f in flags if f.startswith("looks wrong: ")]
    other = [f for f in flags if not f.startswith(("not in the brief: ", "looks wrong: "))]
    parts = []
    if extras:
        parts.append("remove " + ", ".join(extras[:3]))
    if bad:
        parts.append("fix " + "; ".join(bad[:3]))
    if other:
        parts.append(other[0])
    if note:
        parts.append(note)
    return ". ".join(parts)


MAX_FIXES = 2                         # corrections per picture in auto-run
GOOD_ENOUGH = 75                      # the judge's event_fit at which a picture is left alone


async def correct(plan_id: str, scene_id: str, change: str, keep: list[str] | None = None, base_item: str | None = None, progress=None,
                  s: dict | None = None, key: str = "", score: bool = True) -> dict:
    """"Correct this": an edit of an existing picture that says what to change and what to keep (no masks). The picture being corrected goes first,
    the scene's reference sheets follow (three images at most). Makes a new attempt; the old picture stays."""
    s = s or settings_mod.get()
    key = key or settings_mod.api_key()
    if not _s(change):
        raise MediaError("say what to change")
    plan = planner.get_plan(plan_id)
    sc = storyboard.get_scene(scene_id)
    base = store.get(base_item) if base_item else None
    if base is None:
        pics = [i for i in store.items(plan_id, KIND, scene_id) if i["status"] == "done"]
        base = next((i for i in pics if i["approved"]), pics[-1] if pics else None)
    if not base or base["key"] != scene_id or base["status"] != "done":
        raise MediaError("there is no finished picture of this scene to correct")
    m = base["meta"].get("model") or model_for(sc, plan)
    c = compiled(sc, m)
    if not c:
        raise MediaError("write the image prompts first")
    refs = [{"name": "the picture being corrected", "role": "this is the picture to change"}] + [r for r, _p in reference_files(c)][:2]
    prompt = imgprompts.edit_instruction(change, [_s(k) for k in (keep or [])] or ["the people, setting, composition, lighting and style"], refs)
    exp = _export_rev(plan_id)
    it = store.add(plan_id, KIND, scene_id, exp, "running", {"model": m, "mode": "correct", "source_hash": c["source_hash"], "prompt": prompt, "corrects": base["id"],
                                                              "change": _s(change), "keep": list(keep or []), "references": [r["name"] for r in refs[1:]]})
    seed = seed_for(scene_id, it["attempt"])
    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=700) as client:
            if progress:
                progress(0, 1, "correcting the picture")
            img, req = await draw(client, s, key, m, c, "edit", seed, plan, extra_files=[store.path_of(base)], prompt=prompt)
        name = f"scenes/{scene_id}-a{it['attempt']}.png"
        (store.media_dir(plan_id, "scenes") / f"{scene_id}-a{it['attempt']}.png").write_bytes(base64.b64decode(img["b64_json"]))
        store.update(it["id"], status="done", file=name, meta={"seed": img.get("seed", seed), "width": img.get("width"), "height": img.get("height"),
                                                             "seconds_taken": round(time.time() - t0, 1), "request": req})
    except asyncio.CancelledError:
        store.update(it["id"], status="failed", meta={"error": "stopped before it finished"})
        raise
    except MediaError as e:
        store.update(it["id"], status="failed", meta={"error": str(e)[:300]})
        raise
    if score:
        await score_items(plan_id, [it["id"]], progress, s, key)
    plan_store.log(plan_id, "scene_picture_corrected", {"scene": scene_id, "item": it["id"], "from": base["id"]})
    if progress:
        progress(1, 1, "done")
    return {"item": store.get(it["id"])}


# ── scoring ─────────────────────────────────────────────────────────────────

async def score_items(plan_id: str, item_ids: list[str] | None = None, progress=None, s: dict | None = None, key: str = "") -> dict:
    """Measure and look at finished scene pictures that have no score yet (or the ones named). A failed vision check keeps the measured score."""
    s = s or settings_mod.get()
    assets = storyboard.get_assets(plan_id)
    style = next((_s(a["data"].get("description")) for a in assets if a["kind"] == "style"), "")
    by_id = {sc["id"]: sc for sc in storyboard.get_scenes(plan_id)}
    context = story_context(plan_id)
    plan_now = planner.get_plan(plan_id)
    todo = [i for i in store.items(plan_id, KIND) if i["status"] == "done" and i["key"] in by_id and (i["id"] in item_ids if item_ids else not i["meta"].get("score"))]
    done, vision_down = 0, False
    for n, it in enumerate(todo):
        if progress:
            progress(n, len(todo), f"checking picture {n + 1} of {len(todo)}")
        sc = by_id[it["key"]]
        asked = (it["meta"].get("request") or {}).get("size")
        auto = refscore.measure(store.path_of(it), "scene", tuple(int(v) for v in asked.split("x")) if asked else None)
        seen, note = None, ""
        if not vision_down:
            try:
                seen = await refscore.look(store.path_of(it), {"kind": "scene", "name": "", "brief": brief(sc, assets, style, context, narration_for(sc, plan_now))}, style, s, key)
            except Exception as e:  # noqa: BLE001 - reported on the picture; scoring continues with measured facts only
                vision_down, note = True, f"vision check unavailable: {str(e)[:120]}"
        else:
            note = "vision check unavailable"
        sc_ = refscore.combine_scene(auto, seen, quoted_texts(sc), bool(it["meta"].get("references")))
        sc_["note"] = note
        if seen:
            sc_["text_read"] = seen.get("text_read", "")
        store.update(it["id"], meta={"score": sc_, "scored_at": db.now()})
        done += 1
    return {"scored": done}


def best(candidates: list[dict]) -> dict | None:
    cands = [c for c in candidates if c["status"] == "done" and c["current"] and c.get("score")]
    return min(cands, key=lambda c: (-c["score"]["total"], len(c["score"]["flags"]), c["attempt"])) if cands else None


def approve(item_id: str, on: bool = True) -> dict:
    it = store.get(item_id)
    if not it or it["kind"] != KIND:
        raise MediaError("not a scene picture")
    if on and it["status"] != "done":
        raise MediaError("only a finished picture can be approved")
    store.approve(item_id, on)
    plan_store.log(it["plan_id"], "scene_picture_approved" if on else "scene_picture_unapproved", {"scene": it["key"], "item": item_id})
    return state(it["plan_id"])


def approve_best(plan_id: str, min_score: int = refscore.AUTO_APPROVE_MIN) -> dict:
    """Approve, for every scene still open, its best current picture, but only when it scores at least `min_score` and has no hard problem."""
    st = state(plan_id)
    chosen, left = [], []
    for r in st["scenes"]:
        if r["approved"]:
            continue
        b = r["best_item"]
        sc = b["score"] if b else None
        if b and sc and sc.get("total", 0) >= min_score and not sc.get("hard"):
            chosen.append(b["id"])
        elif r["candidates_done"]:
            why = "not scored yet" if not sc else ("has a hard problem" if sc.get("hard") else f"score {sc.get('total', 0)} < {min_score}")
            left.append({"scene": r["id"], "at": r["start_s"], "why": why})
    for iid in chosen:
        store.approve(iid, True)
        plan_store.log(plan_id, "scene_picture_approved", {"item": iid, "bulk": True})
    return {"approved": len(chosen), "left": left, "state": state(plan_id)}


def approve_all(plan_id: str) -> dict:
    """Approve the best available picture for every open scene, regardless of score.
    Falls back to the latest done candidate when no scored picture exists."""
    st = state(plan_id)
    chosen = []
    for r in st["scenes"]:
        if r["approved"]:
            continue
        pick = r["best_item"]
        if not pick:
            # no scored candidate — use the latest done one
            done = [c for c in r["candidates"] if c["status"] == "done"]
            pick = done[-1] if done else None
        if pick:
            chosen.append(pick["id"])
    for iid in chosen:
        store.approve(iid, True)
        plan_store.log(plan_id, "scene_picture_approved", {"item": iid, "bulk": True})
    return {"approved": len(chosen), "state": state(plan_id)}


# ── the trial ───────────────────────────────────────────────────────────────

def trial_scenes(plan_id: str) -> list[dict]:
    """Three scenes that show different things: an opening, a scene with an approved character reference, and a scene with quoted text. Any
    kind that is missing is replaced by the next scene in time order, so there are always three (or fewer scenes if the plan is shorter)."""
    scenes = sorted(storyboard.get_scenes(plan_id), key=lambda x: (x["start_s"], x["seq"]))
    plan = planner.get_plan(plan_id)
    picked: list[dict] = []

    def take(sc):
        if sc and sc not in picked:
            picked.append(sc)
    if scenes:
        take(scenes[0])
    take(next((sc for sc in scenes if sc not in picked and (compiled(sc, model_for(sc, plan)) or {}).get("references")), None))
    take(next((sc for sc in scenes if sc not in picked and quoted_texts(sc)), None))
    for sc in scenes:
        if len(picked) >= TRIAL_SCENES:
            break
        take(sc)
    return sorted(picked[:TRIAL_SCENES], key=lambda x: x["start_s"])


def trial_variants(plan_id: str) -> list[dict]:
    """Both models, plain generation and (where the scene has references) edit mode."""
    return [{"model": m, "mode": mo} for m in providers.PROVIDERS for mo in ("generate", "edit")]


async def run_trial(plan_id: str, progress=None, s: dict | None = None, key: str = "", score: bool = True) -> dict:
    sel = trial_scenes(plan_id)
    if not sel:
        raise MediaError("design the storyboard and write the image prompts first")
    plan = planner.get_plan(plan_id)
    set_settings(plan_id, {"trial": [sc["id"] for sc in sel]})
    variants = trial_variants(plan_id)
    out = {"made": 0, "failed": [], "scored": 0, "scenes": len(sel)}
    for v in variants:                                                 # one scene at a time per variant keeps each model loaded for its whole batch
        keep = [sc["id"] for sc in sel if resolve_mode(v["mode"], compiled(sc, v["model"]) or {}) == v["mode"]]
        if not keep:
            continue
        r = await generate(plan_id, keep, only_missing=False, progress=progress, s=s, key=key, score=score, variants=[v])
        out["made"] += r["made"]
        out["failed"] += r["failed"]
        out["scored"] += r["scored"]
    return out


def choose(plan_id: str, model: str, mode: str) -> dict:
    _known(model)
    if mode not in ("generate", "edit", "auto"):
        raise MediaError("mode must be generate, edit or auto")
    return set_settings(plan_id, {"model": model, "mode": mode, "chosen": True})


# ── state for the screen ────────────────────────────────────────────────────

def state(plan_id: str) -> dict:
    plan = planner.get_plan(plan_id)
    st = settings(plan)
    scenes = sorted(storyboard.get_scenes(plan_id), key=lambda x: (x["start_s"], x["seq"]))
    allitems = store.items(plan_id, KIND)
    by_scene: dict[str, list[dict]] = {}
    for i in allitems:
        by_scene.setdefault(i["key"], []).append(i)
    ready = bool(scenes) and all(sc["data"].get("prompts") for sc in scenes)
    rows, counts = [], {"approved": 0, "needs_choice": 0, "needs_picture": 0}
    est = 0.0
    for sc in scenes:
        m = model_for(sc, plan)
        c = compiled(sc, m) or {}
        cands = []
        for i in by_scene.get(sc["id"], []):
            cands.append({"id": i["id"], "attempt": i["attempt"], "status": i["status"], "approved": i["approved"], "current": _current(i, c),
                          "url": f"/api/media/file/{plan_id}/{i['file']}" if i["file"] else "", "model": i["meta"].get("model"), "mode": i["meta"].get("mode"),
                          "seed": i["meta"].get("seed"), "seconds_taken": i["meta"].get("seconds_taken"), "error": i["meta"].get("error", ""), "score": i["meta"].get("score"),
                          "references": i["meta"].get("references", []), "trial": bool(i["meta"].get("trial")), "custom": bool(i["meta"].get("custom_prompt")),
                          "prompt": i["meta"].get("prompt", "") if i["meta"].get("custom_prompt") else "", "change": i["meta"].get("change", ""), "corrects": i["meta"].get("corrects", "")})
        good = [x for x in cands if x["status"] == "done" and x["current"]]
        ok = next((x for x in cands if x["approved"] and x["status"] == "done"), None)
        b = best(cands)
        if ok and ok["current"]:
            counts["approved"] += 1
        elif good:
            counts["needs_choice"] += 1
        else:
            counts["needs_picture"] += 1
            est += _eta(m, allitems) * st["candidates"]
        rows.append({"id": sc["id"], "start_s": sc["start_s"], "duration_s": sc["duration_s"], "subject": _s(sc["data"].get("subject")), "visual_type": sc["data"].get("visual_type"),
                     "model": m, "mode": resolve_mode(mode_for(sc, plan), c) if c else "generate", "chosen_here": sc["id"] in st["per_scene"],
                     "plain_fallback": bool(c) and mode_for(sc, plan) != "generate" and resolve_mode(mode_for(sc, plan), c) == "generate" and bool(c.get("missing_references")),
                     "can_edit": bool(c.get("references")) and providers.get(m)["edits"], "references": [r["name"] for r in c.get("references", [])],
                     "quoted": quoted_texts(sc), "prompt": c.get("prompt", ""), "has_prompt": bool(c), "approved": ok["id"] if ok else None, "approved_current": bool(ok and ok["current"]),
                     "candidates": cands, "candidates_done": len(good), "best": b["id"] if b else None, "best_item": b,
                     "motion_clip": bool(sc["data"].get("motion_clip")),
                     "status": "approved" if ok and ok["current"] else "needs_choice" if good else "needs_picture"})
    unscored = sum(1 for i in allitems if i["status"] == "done" and not i["meta"].get("score"))
    bulk = sum(1 for r in rows if not r["approved"] and r["best_item"] and r["best_item"]["score"]["total"] >= refscore.AUTO_APPROVE_MIN and not r["best_item"]["score"]["hard"])
    trial = [r for r in rows if r["id"] in st["trial"]]
    return {"ready": ready, "settings": st, "scenes": rows, "total": len(rows), **counts, "plain_fallback": sum(1 for r in rows if r["plain_fallback"]), "unscored": unscored, "bulk_ready": bulk, "min_score": refscore.AUTO_APPROVE_MIN,
            "eta_missing_s": round(est), "done": bool(rows) and counts["approved"] == len(rows), "trial": [r["id"] for r in trial],
            "trial_done": bool(trial) and all(any(c["trial"] and c["status"] == "done" for c in r["candidates"]) for r in trial),
            "models": {m: providers.get(m)["label"] for m in providers.PROVIDERS},
            "model_info": {m: {"label": providers.get(m)["label"], "edits": providers.get(m)["edits"], "negative_prompt": providers.get(m)["negative_prompt"],
                               "discovered": bool(providers.get(m).get("discovered")), "default": m == providers.DEFAULT_MODEL} for m in providers.PROVIDERS},
            "seconds_per_picture": {m: round(_eta(m, allitems)) for m in providers.PROVIDERS}}
