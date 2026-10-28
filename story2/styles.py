"""Visual styles for the whole video. A style is chosen once per plan and then used everywhere the same way: the style asset in the continuity
registry, every scene prompt (both image models), the reference pictures, and the instructions the storyboard model receives. The wording was
tested on the real image models (see docs/phase3_plan.md, "Visual direction"); change it there first, then here.

A preset is plain, positive wording ("hand-illustrated, bold outlines"), because the image models follow what is described much more
reliably than what is forbidden. Negative wording is kept apart and sent only where the model honours a negative prompt."""

DEFAULT = "filmic"
# Bumped when the way scenes and characters are designed changes; a plan whose registry or storyboard was made under an older direction is told so.
DIRECTION = "illustrated-2"

CHARACTER_RULE = ("Characters are invented composite people, each with a distinct face, hair, build and clothing right for the period, shown with clear emotion and body language. "
                  "A real, named person is never given an invented likeness: show such a person as a silhouette, from behind, in shadow or only by their hands.")

PRESETS: dict[str, dict] = {
    "filmic": {
        "label": "Cinematic film still (painted)",
        "description": "Painted realism that looks like a still from a feature film: natural colour grade, grounded light, shallow depth of field, real-looking people and places. No anime, no game art.",
        "short": "cinematic painted film still",
        "look": ("Cinematic painted film still, realistic proportions and natural faces, grounded motivated light, shallow depth of field, subtle film grain, muted natural colour grade. "
                 "Hand-painted, not a photograph, not a 3D render, not anime or cartoon. No logos or lettering."),
        "object_look": ("Cinematic painted film still, realistic materials, grounded motivated light, shallow depth of field, subtle film grain, muted natural colour grade. "
                        "Hand-painted, not a photograph, not a 3D render, not anime or cartoon. No logos or lettering."),
        "palette": "muted natural colour, one warm light source against cool shadow",
        "linework": "soft painted edges, no outlines",
        # appended to the style section for atmospheric/establishing/metaphor/transition scenes only — boosts immersive quality
        "atmosphere_boost": "anamorphic lens, volumetric light rays, deep focus with soft foreground bokeh, fine cinematic grain, rich tonal depth",
    },
    "gta": {
        "label": "Game-art illustration (GTA-style)",
        "description": "Bold outlines, cel-shaded colour with painterly gradients, saturated cinematic colour and strong rim light, like a GTA V loading-screen painting. Expressive faces, rich detailed settings.",
        "short": "open-world game loading-screen illustration",
        "look": ("Stylised digital illustration in the style of premium open-world action-game loading-screen key art, painted and graphic: confident bold outlines, cel-shaded colour with painterly soft gradients, "
                 "saturated cinematic colour with warm and cool contrast, strong rim light, semi-realistic characters with expressive faces and dynamic poses, "
                 "richly detailed environment, slightly gritty poster finish. Hand-illustrated, not a photograph and not a 3D render. No logos, emblems or lettering anywhere."),
        "object_look": ("Stylised digital illustration in premium action-game key-art style, painted and graphic: confident bold outlines, cel-shaded colour with painterly soft gradients, "
                        "saturated cinematic colour, strong rim light, richly detailed materials, slightly gritty finish. Hand-illustrated, not a photograph and not a 3D render. No logos, emblems or lettering anywhere."),
        "palette": "saturated cinematic colour, warm highlights against cool shadows",
        "linework": "confident bold outlines",
        "atmosphere_boost": "dramatic wide establishing composition, saturated atmospheric haze, strong rim lighting, deep shadow pools, richly textured environment detail",
    },
    "noir": {
        "label": "Noir graphic novel",
        "description": "Heavy black ink linework, crosshatching and halftone dots, flat colour washes in deep blue, red and amber, hard chiaroscuro. Gritty and mature.",
        "short": "noir graphic-novel panel",
        "look": ("A graphic-novel page panel drawn in heavy black ink linework with crosshatching and halftone dots, flat colour washes with a limited palette of deep blue, red and amber, "
                 "dramatic chiaroscuro, gritty mature noir tone, detailed faces and environment. Hand-inked, not a photograph and not a 3D render."),
        "object_look": "A graphic-novel illustration drawn in heavy black ink linework with crosshatching and halftone dots, flat colour washes in deep blue, red and amber, gritty noir tone. Hand-inked, not a photograph and not a 3D render. No logos or lettering.",
        "palette": "deep blue, red and amber on black",
        "linework": "heavy black ink with crosshatching",
        "atmosphere_boost": "extreme chiaroscuro, deep black voids, single hard light source cutting through darkness, heavy crosshatch texture, dense atmospheric shadow",
    },
    "concept": {
        "label": "Painterly game concept art",
        "description": "Soft painterly brushwork, moody cinematic lighting and atmospheric depth, like story-driven game key art. Less graphic, more filmic.",
        "short": "painterly game concept art",
        "look": ("Painterly video-game concept art illustration, detailed semi-realistic characters, moody cinematic lighting, rich atmospheric depth, visible brush texture, "
                 "in the manner of story-driven AAA game key art. Hand-painted, not a photograph and not a 3D render."),
        "object_look": "Painterly video-game concept art illustration, moody cinematic lighting, visible brush texture, richly detailed materials. Hand-painted, not a photograph and not a 3D render. No logos or lettering.",
        "palette": "muted teal and amber with deep shadows",
        "linework": "soft painted edges",
        "atmosphere_boost": "sweeping painterly environment, layered atmospheric haze, dramatic backlighting, visible loose brushwork on the sky and distance, sense of vast scale",
    },
}

# What the picture must not become. Sent as the negative prompt where the model honours one, and stated as "not ..." in the prompt where it does not.
NEGATIVE = ("anime, cartoon, floating platform, floating objects, photograph, photorealistic, 3D render, plain white background, empty background, flat vector icon, infographic, stock chart diagram, "
            "text, letters, numbers, watermark, logo, blurry, low quality, deformed hands, extra fingers, duplicate subject")
NOT_PHOTO = "Not a photograph, not a 3D render, not a flat diagram."

# LoRAs the gateway should apply for a style, per image model: {"qwen-image-2.1": {"lora-name": strength}}. Empty: the base models already
# render all three looks (checked 2026-10-24). To add one, attach the file to the model in the gateway console, then name it here.
LORAS: dict[str, dict[str, dict[str, float]]] = {"filmic": {}, "gta": {}, "noir": {}, "concept": {}}


class StyleError(ValueError):
    pass


def get(style_id: str) -> dict:
    if style_id not in PRESETS:
        raise StyleError(f"unknown visual style '{style_id}' (known: {', '.join(PRESETS)})")
    return {"id": style_id, **PRESETS[style_id]}


def style_id(plan_settings: dict | None) -> str:
    sid = (plan_settings or {}).get("visual_style")
    return sid if sid in PRESETS else DEFAULT


def for_plan(plan_settings: dict | None) -> dict:
    return get(style_id(plan_settings))


def loras_for(model: str, plan_settings: dict | None) -> dict[str, float]:
    return dict(LORAS.get(style_id(plan_settings), {}).get(model, {}))


def style_asset_data(plan_settings: dict | None) -> dict:
    """The registry's style asset, written from the preset instead of being left to the model, so every plan in a style looks the same."""
    p = for_plan(plan_settings)
    return {"name": "style", "kind": "style", "description": p["look"], "fixed": [p["linework"], "colour palette: " + p["palette"], "same rendering in every scene"],
            "flexible": ["time of day", "weather"], "period": "", "fictionalisation": "fictional", "evidence_note": f"visual style chosen for the video: {p['label']}",
            "preset": p["id"]}


def public() -> list[dict]:
    return [{"id": k, **{x: v for x, v in p.items() if x in ("label", "description", "short")}} for k, p in PRESETS.items()]
