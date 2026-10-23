"""Image providers: what each deployed model can do. Facts come from the gateway's own configuration and docs (audited, with the
source named), overlaid with the live /v1/models listing. Nothing here is guessed from a model's family name, and licence status
is never inferred: it starts as "unverified" and only a person changes it."""
import httpx

from story import llm

CONFIG_SOURCE = "MiniMaxH3/serve_models.yaml and the gateway's /docs page (audited 2026-10-23)"

# One adapter version per compiler; bump when a compiler's output format changes so stored prompts can be told apart.
PROVIDERS: dict[str, dict] = {
    "qwen-image-2.1": {
        "label": "Qwen Image 2.1", "adapter": "qwen", "adapter_version": "1.0", "default": True,
        "variant": "int8 (convrot) diffusion model, Qwen3-VL 8B int8 text encoder, detail-fix LoRA on by default",
        "workflow": "qwen_image", "steps": 25, "cfg": 1.0, "edit_steps": 35, "edit_cfg": 2.5,
        "max_pixels": 2359296, "size_multiple": 16, "timeout_s": 300,
        # cfg 1 = guidance-free sampling: a negative prompt has no effect on text-to-image, so exclusions go into the prompt as plain statements
        "negative_prompt": False,
        "edits": True, "max_references": 3, "masks": False,
        "reliable_text": False, "transparency": "not exposed by the gateway",
        "prompt_enhancer": {"available": False, "reason": "no enhancer model or workflow is configured on the gateway"},
        "licence": {"weights": "Qwen Image 2.1 weights (comfy-org mirror)", "status": "unverified",
                    "note": "no licence file ships with the weights on this machine; read the model card and the licence for the exact files before publishing"},
    },
    "flux2-klein-9b": {
        "label": "FLUX.2 Klein 9B", "adapter": "flux", "adapter_version": "1.0", "default": False,
        "variant": "9B base, FP8 diffusion model, Qwen3-8B fp4-mixed text encoder (non-distilled)",
        "workflow": "flux2", "steps": 28, "cfg": 4.0, "edit_steps": 20, "edit_cfg": 5.0,
        "max_pixels": 2359296, "size_multiple": 16, "timeout_s": 600,
        # base model with cfg 4: the gateway honours negative_prompt, and has a default one configured for text artefacts
        "negative_prompt": True,
        "edits": True, "max_references": 3, "masks": False,
        "reliable_text": False, "transparency": "not exposed by the gateway",
        "prompt_enhancer": {"available": False, "reason": "none configured"},
        "licence": {"weights": "FLUX.2 klein 9B base (FP8)", "status": "restricted",
                    "note": "the gateway's own description says FLUX Non-Commercial License. Do not use for monetised output until a person has read the licence "
                            "for these exact weights and confirmed the intended use is allowed"},
    },
}
IMAGE_MODELS = tuple(PROVIDERS)
DEFAULT_MODEL = next(k for k, v in PROVIDERS.items() if v["default"])


class ProviderError(Exception):
    pass


def get(model: str) -> dict:
    if model not in PROVIDERS:
        raise ProviderError(f"unknown image model '{model}' (known: {', '.join(PROVIDERS)})")
    return PROVIDERS[model]


def public(model: str) -> dict:
    return {"id": model, **{k: v for k, v in get(model).items()}}


def probe(s: dict, key: str) -> dict:
    """Read-only check against the live gateway (GET /v1/models; no generation). Reports, per provider, whether it is listed, whether the
    capabilities we rely on are advertised, and what differs from our audited configuration."""
    out: dict = {"source": CONFIG_SOURCE, "reachable": False, "providers": {}}
    try:
        r = httpx.get(s["base_url"].rstrip("/") + "/models", headers={"Authorization": f"Bearer {key}"}, timeout=15)
        r.raise_for_status()
        listed = {m["id"]: m for m in r.json().get("data", [])}
        out["reachable"] = True
    except Exception as e:  # noqa: BLE001 - reported to the screen
        out["error"] = f"{type(e).__name__}: {e}"
        listed = {}
    for mid, cfg in PROVIDERS.items():
        m = listed.get(mid)
        caps = (m or {}).get("capabilities", [])
        diffs = []
        if m is None:
            diffs.append("not listed by the gateway")
        else:
            if "images.generations" not in caps:
                diffs.append("images.generations not advertised")
            if cfg["edits"] and "images.edits" not in caps:
                diffs.append("images.edits not advertised (our audit says edits work)")
        out["providers"][mid] = {"listed": m is not None, "loaded": bool((m or {}).get("loaded")), "capabilities": caps, "differences": diffs,
                                 "negative_prompt": cfg["negative_prompt"], "max_references": cfg["max_references"],
                                 "licence_status": cfg["licence"]["status"]}
    return out


def settings_for(plan_settings: dict) -> dict:
    """Plan-level model choices: a default model and an optional model per visual type. Defaults to Qwen everywhere; nothing is picked by a
    quality ranking."""
    im = (plan_settings or {}).get("image_models") or {}
    return {"default": im.get("default") if im.get("default") in PROVIDERS else DEFAULT_MODEL,
            "by_type": {k: v for k, v in (im.get("by_type") or {}).items() if v in PROVIDERS},
            "previews_enabled": bool(im.get("previews_enabled", False)),
            "licence_checks": im.get("licence_checks") or {}}


def model_for(scene_data: dict, plan_settings: dict) -> str:
    """Scene override first, then the plan's per-type choice, then the plan default."""
    st = settings_for(plan_settings)
    m = scene_data.get("model")
    if m in PROVIDERS:
        return m
    return st["by_type"].get(scene_data.get("visual_type", ""), st["default"])


def snap(w: int, h: int, cfg: dict) -> tuple[int, int, bool]:
    """Fit a size to the model: multiples of 16 and inside the pixel budget, kept in proportion. Returns (w, h, changed)."""
    m = cfg["size_multiple"]
    scale = min(1.0, (cfg["max_pixels"] / (w * h)) ** 0.5)
    w2, h2 = max(m, int(w * scale) // m * m), max(m, int(h * scale) // m * m)
    return w2, h2, (w2, h2) != (w, h)
