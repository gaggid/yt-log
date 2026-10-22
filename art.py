"""Image art direction for z-image-turbo, built from its published prompting guidance:
natural-language sentences (not tag lists), 30-120 words, every constraint stated POSITIVELY (the turbo model has no
negative prompt), text in quotes with a placement, no "masterpiece" boilerplate.
We do not use the gateway's server-side style: its graphic-novel preset forces one orange/black palette."""
import random

STYLES = {
    "graphic-novel": ("bold black ink linework with crosshatching and subtle halftone texture, "
                      "graphic-novel illustration, hand-drawn, every object is an ink drawing"),
    "flat-vector": "clean flat vector editorial illustration, simple geometric shapes, bold flat colour fills, subtle paper grain",
    "ink-wash": "expressive ink and watercolour wash illustration, soft gradients, visible brush texture, hand-painted",
    "retro-poster": "retro screen-printed poster illustration, layered inks, bold simple shapes, vintage paper grain",
    "paper-cut": "layered paper-cut collage illustration, soft shadows between layers, handcrafted tactile texture",
}
DEFAULT_STYLE = "graphic-novel"

PALETTES = {
    "teal-amber":       "deep teal and midnight blue shadows with warm amber highlights",
    "indigo-coral":     "rich indigo and violet shadows with coral and peach highlights",
    "forest-gold":      "dark forest green and olive tones with golden yellow highlights",
    "crimson-charcoal": "deep charcoal and rich crimson with dark moody background and cream highlights",
    "slate-ice":        "slate grey and steel blue with icy cyan highlights",
    "sunset":           "warm magenta, orange and soft yellow tones with deep purple shadows",
    "mint-navy":        "navy blue with fresh mint green and soft cream highlights",
    "sand-terracotta":  "sand beige, terracotta red and deep brown with turquoise accents",
}
# Mood of the segment decides the colour family; consecutive segments never share a palette.
EMOTION_PALETTES = {
    "dramatic":  ["crimson-charcoal", "sunset", "indigo-coral"],
    "serious":   ["slate-ice", "teal-amber", "crimson-charcoal"],
    "calm":      ["mint-navy", "forest-gold", "sand-terracotta"],
    "excited":   ["sunset", "indigo-coral", "teal-amber"],
    "concerned": ["indigo-coral", "slate-ice", "teal-amber"],
    "amused":    ["mint-navy", "sand-terracotta", "forest-gold"],
}


def segment_palettes(emotions: list[str], rng: random.Random) -> list[str]:
    out: list[str] = []
    for e in emotions:
        pool = [p for p in EMOTION_PALETTES.get(e, list(PALETTES)) if not out or p != out[-1]] or list(PALETTES)
        out.append(rng.choice(pool))
    return out


_MOOD_LINES = {
    "dramatic":     "The composition is high-contrast with strong diagonal tension.",
    "serious":      "The scene is still and weighty with minimal movement.",
    "calm":         "The scene is open and spacious with soft diffuse light.",
    "excited":      "The layout is dynamic with energetic implied motion.",
    "concerned":    "The atmosphere is heavy and uncertain.",
}

# When the scene's per-beat mood conflicts with the segment palette's warmth, nudge the light.
_WARM_PALETTES = {"forest-gold", "sunset", "sand-terracotta", "indigo-coral"}
_COOL_PALETTES  = {"slate-ice", "teal-amber", "mint-navy"}


def compose(scene: dict, style: str, palette: str, rng: random.Random, emotion: str = "neutral") -> str:
    """One natural-language prompt: scene, composition, style, palette, mood, text clause."""
    parts = [scene["visual"].strip().rstrip(".") + ".",
             "Full-bleed 16:9 illustration, background fills every edge, no panels, no borders, no white margins.",
             f"Style: {STYLES.get(style, STYLES[DEFAULT_STYLE])}.",
             f"Colour palette: {PALETTES[palette]}."]

    # mood line: per-beat mood takes priority, fall back to segment emotion
    beat_mood = scene.get("mood", "")
    if beat_mood == "warm" and palette in _COOL_PALETTES:
        parts.append("Warm the light: amber and cream tones catch the edges.")
    elif beat_mood == "cool" and palette in _WARM_PALETTES:
        parts.append("Cool the light: blue and silver tones settle over the scene.")
    mood_line = _MOOD_LINES.get(emotion, "")
    if mood_line:
        parts.append(mood_line)

    parts.append("People appear only as small figures or silhouettes, never as close-up faces or hands.")

    if scene.get("text"):
        place = rng.choice(["top", "bottom"])
        parts.append(f'A short label reading "{scene["text"]}" in bold Latin letters and digits sits in the {place} '
                     "third of the frame, fully legible, not covering the main subject. "
                     "No other text, letters, numbers or logos anywhere else in the image.")
    else:
        parts.append("The image contains no text, letters, numbers, logos or watermarks.")
    return " ".join(parts)
