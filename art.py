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


def compose(scene: dict, style: str, palette: str, rng: random.Random) -> str:
    """One natural-language prompt: scene, composition, style, palette, text clause."""
    parts = [scene["visual"].strip().rstrip(".") + ".",
             "Single full-bleed illustration filling the entire 16:9 frame edge to edge, "
             "no panels, no borders, no frame, no white margins, the background is filled with colour or scenery all the way to every edge, never a blank white backdrop.",
             f"Style: {STYLES.get(style, STYLES[DEFAULT_STYLE])}.",
             f"Colour palette: {PALETTES[palette]}.",
             "People appear only as small figures or silhouettes, never as close-up faces or hands."]
    if scene.get("text"):
        place = rng.choice(["top", "bottom"])
        parts.append(f'A short headline reading "{scene["text"]}" in bold clean lettering sits in the {place} third '
                     "of the frame, fully visible and not covering the main subject. "
                     "No other text, letters or numbers appear anywhere else in the image.")
    else:
        parts.append("The image contains no text, letters, numbers, logos or watermark.")
    return " ".join(parts)
