"""Batch C persistence and actions around the prompt compilers: compile a plan's scenes, validate the prompts, choose models, and run an
optional, explicit single-image preview. Compiling is deterministic and free; a preview is the only thing here that calls an image model,
and it only runs when the plan has previews switched on."""
import base64
import time

import httpx

import config
from story import db, settings as settings_mod

from . import imgprompts, intake, leak, planner, providers, store, storyboard


def _plan_ctx(plan_id: str):
    plan = planner.get_plan(plan_id)
    story = planner._story_for(plan)
    return plan, story, storyboard.get_scenes(plan_id), storyboard.get_assets(plan_id)


def compile_plan(plan_id: str) -> dict:
    """Compile every scene for both adapters and save the prompts on the scene. Scene content is never touched; approved and locked scenes
    keep their wording, only the derived prompts are refreshed."""
    plan, _story, scenes, assets = _plan_ctx(plan_id)
    if not scenes:
        raise planner.PlanError("design the storyboard first")
    first = imgprompts.first_appearances(scenes)
    for sc in scenes:
        comp = imgprompts.compile_scene(sc, assets, plan, first)
        data = sc["data"]
        data["prompts"] = comp
        data["adapters"] = {a: {"version": c["adapter_version"], "model": c["model"], "scene_rev": c["scene_rev"], "source_hash": c["source_hash"]}
                            for a, c in comp.items()}
        db.ex("UPDATE scenes SET data=?, updated_at=? WHERE id=?", (db.jdump(data), db.now(), sc["id"]))
    store.log(plan_id, "compile_prompts", {"scenes": len(scenes)})
    return validate_prompts(plan_id)


def validate_prompts(plan_id: str) -> dict:
    plan, story, scenes, assets = _plan_ctx(plan_id)
    prof = leak.profile(story["evidence"]["project_id"], story["evidence"]["passages"])
    facts = intake.facts_text(story["public"])
    st = providers.settings_for(plan["settings"])
    issues, compiled, used_models = [], 0, {st["default"]}
    for sc in scenes:
        prompts = sc["data"].get("prompts") or {}
        if not prompts:
            issues.append({"where": sc["id"], "adapter": "", "kind": "not_compiled", "text": "image prompts have not been compiled", "level": "warn"})
            continue
        model = providers.model_for(sc["data"], plan["settings"])
        used_models.add(model)
        chosen = providers.get(model)["adapter"]
        compiled += 1
        for adapter, c in prompts.items():
            for i in imgprompts.validate_prompt(c, sc, assets, facts, prof):
                # licence is reported once for the plan, not per scene; style notes matter only for the model that will be used
                if i["kind"] == "licence" or (adapter != chosen and i["kind"] in ("vague", "composition")):
                    continue
                issues.append({"where": sc["id"], **i})
    for mid in sorted(used_models):
        m = providers.get(mid)
        if m["licence"]["status"] != "verified" and not st["licence_checks"].get(mid):
            issues.append({"where": "plan", "adapter": m["adapter"], "kind": "licence_checklist", "level": "warn",
                           "text": f"{m['label']}: licence not confirmed by a person ({m['licence']['status']}). {m['licence']['note']}"})
    report = {"ok": not any(i["level"] == "error" for i in issues), "issues": issues, "scenes": len(scenes), "compiled": compiled, "models": st}
    db.ex("UPDATE plans SET validation=?, updated_at=? WHERE id=?", (db.jdump({**(plan["validation"] or {}), "prompts": report}), db.now(), plan_id))
    return report


def set_image_models(plan_id: str, patch: dict) -> dict:
    plan = planner.get_plan(plan_id)
    cur = providers.settings_for(plan["settings"])
    if "default" in patch:
        providers.get(patch["default"])
        cur["default"] = patch["default"]
    if "by_type" in patch:
        for v in (patch["by_type"] or {}).values():
            if v:
                providers.get(v)
        cur["by_type"] = {k: v for k, v in (patch["by_type"] or {}).items() if v}
    if "previews_enabled" in patch:
        cur["previews_enabled"] = bool(patch["previews_enabled"])
    if "licence_checks" in patch:
        cur["licence_checks"] = {k: bool(v) for k, v in (patch["licence_checks"] or {}).items() if k in providers.PROVIDERS}
    db.ex("UPDATE plans SET settings=?, updated_at=? WHERE id=?", (db.jdump({**plan["settings"], "image_models": cur}), db.now(), plan_id))
    store.log(plan_id, "image_models", dict(patch))
    return planner.get_plan(plan_id)


def preview_dir(plan_id: str):
    d = config.DATA_DIR / "plan_previews" / plan_id
    d.mkdir(parents=True, exist_ok=True)
    return d


async def preview(scene_id: str, adapter: str, seed: int | None = None, backend_settings: dict | None = None, key: str = "") -> dict:
    """ONE image for ONE scene from the saved prompt. Explicit action, off unless the plan enables previews. Records the exact model, prompt,
    parameters and result on the scene so two models can be compared side by side. Nothing else in the workflow depends on it."""
    sc = storyboard.get_scene(scene_id)
    plan = planner.get_plan(sc["plan_id"])
    if not providers.settings_for(plan["settings"])["previews_enabled"]:
        raise planner.PlanError("image previews are switched off for this plan; enable them first")
    c = (sc["data"].get("prompts") or {}).get(adapter)
    if not c:
        raise planner.PlanError("compile the image prompts first")
    if c["mode"] == "edit":
        raise planner.PlanError("this scene needs reference images (edit mode); previews support plain generation only")
    cfg = providers.get(c["model"])
    s = backend_settings or settings_mod.get()
    body = {"model": c["model"], "prompt": c["prompt"], "size": f"{c['size']['width']}x{c['size']['height']}", "n": 1, "response_format": "b64_json"}
    if c["negative_prompt"] and cfg["negative_prompt"]:
        body["negative_prompt"] = c["negative_prompt"]
    if seed is not None:
        body["seed"] = int(seed)
    t0 = time.time()
    async with httpx.AsyncClient(timeout=cfg["timeout_s"] + 120) as cl:
        r = await cl.post(s["base_url"].rstrip("/") + "/images/generations", json=body,
                          headers={"Authorization": f"Bearer {key or settings_mod.api_key()}"})
    if r.status_code != 200:
        raise planner.PlanError(f"image gateway answered {r.status_code}: {r.text[:200]}")
    img = r.json()["data"][0]
    sc = storyboard.get_scene(scene_id)
    n = len(sc["data"].get("previews", [])) + 1
    name = f"{scene_id}-{adapter}-{n}.png"
    (preview_dir(sc["plan_id"]) / name).write_bytes(base64.b64decode(img["b64_json"]))
    rec = {"id": f"{adapter}-{n}", "file": name, "model": c["model"], "adapter_version": c["adapter_version"], "adapter": adapter, "mode": c["mode"],
           "prompt": c["prompt"], "negative_prompt": body.get("negative_prompt", ""),
           "request": {k: v for k, v in body.items() if k not in ("prompt", "negative_prompt")},
           "seed": img.get("seed"), "width": img.get("width"), "height": img.get("height"), "revised_prompt": img.get("revised_prompt", ""),
           "seconds": round(time.time() - t0, 1), "created_at": db.now(), "source_hash": c["source_hash"], "rating": {}}
    sc["data"].setdefault("previews", []).append(rec)
    db.ex("UPDATE scenes SET data=?, updated_at=? WHERE id=?", (db.jdump(sc["data"]), db.now(), scene_id))
    store.log(sc["plan_id"], "preview", {"scene": scene_id, "model": c["model"], "file": name})
    return rec


def rate_preview(scene_id: str, preview_id: str, rating: dict) -> dict:
    sc = storyboard.get_scene(scene_id)
    keys = {"composition", "subjects", "factual", "continuity", "clarity", "prompt_adherence", "corrections", "note"}
    for p in sc["data"].get("previews", []):
        if p["id"] == preview_id:
            p["rating"] = {k: v for k, v in rating.items() if k in keys}
            db.ex("UPDATE scenes SET data=?, updated_at=? WHERE id=?", (db.jdump(sc["data"]), db.now(), scene_id))
            return p
    raise planner.PlanError("no such preview")
