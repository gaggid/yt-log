"""Picture style of a short (setting `visual_style`). The four painted looks are the long-form presets (story2/styles.py); `realism` is only for shorts. Empty = the planner writes the look
(the old behaviour). A chosen style replaces the plan's look in every start-picture prompt and every Wan prompt, so the whole short is drawn one way."""
from story2 import styles

REALISM = {
    "label": "Realism (photographic)",
    "description": "Real photograph look: natural skin and light, real lens depth of field, true-to-life colour. Like a phone or cinema camera, not a painting.",
    "look": ("Photorealistic, shot on a full-frame cinema camera, 35mm lens, natural skin texture, true-to-life colour, soft natural light, shallow depth of field, "
             "clean sharp detail, smooth noise-free image. Real photograph, not a painting, not an illustration, not a 3D render, not anime."),
}
NONE = ""


def presets() -> dict[str, dict]:
    return {"realism": REALISM, **{k: {"label": p["label"], "description": p["description"], "look": p["look"]} for k, p in styles.PRESETS.items()}}


def public() -> list[dict]:
    return [{"id": NONE, "label": "Let the planner choose", "description": "The story planner writes one line of look."}] + [{"id": k, "label": p["label"], "description": p["description"]} for k, p in presets().items()]


def style_id(short: dict) -> str:
    sid = short["settings"].get("visual_style") or NONE
    return sid if sid in presets() else NONE


def of(short: dict, fallback: str = "") -> str:
    """The look sentence for prompts: the chosen style, else `fallback` (the plan's own look)."""
    sid = style_id(short)
    return presets()[sid]["look"] if sid else fallback


def painted(short: dict) -> bool:
    """True when the chosen style is a drawing, not a photograph."""
    return style_id(short) not in (NONE, "realism")
