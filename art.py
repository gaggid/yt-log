"""Image art direction for z-image-turbo.
Two modes:
  - Illustrated styles (graphic-novel, flat-vector, etc.): metaphor/symbol-based, abstract figures.
  - Cinematic style: photorealistic, character-driven, shot-list-based — uses the rich scene schema
    (shot, angle, lighting, subject, environment, layers) from the scene planner.
"""
import random

STYLES = {
    "graphic-novel": ("bold black ink linework with crosshatching and subtle halftone texture, "
                      "graphic-novel illustration, hand-drawn, every object is an ink drawing"),
    "flat-vector": "clean flat vector editorial illustration, simple geometric shapes, bold flat colour fills, subtle paper grain",
    "ink-wash": "expressive ink and watercolour wash illustration, soft gradients, visible brush texture, hand-painted",
    "retro-poster": "retro screen-printed poster illustration, layered inks, bold simple shapes, vintage paper grain",
    "paper-cut": "layered paper-cut collage illustration, soft shadows between layers, handcrafted tactile texture",
    "cinematic": "photorealistic cinematic still, 35mm lens, shallow depth of field, professional colour grade, high production value, no illustrations, no artwork, no cartoon",
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

# For cinematic style, palette → colour grade description instead of illustration palette
_CINEMATIC_GRADE = {
    "teal-amber":       "teal-and-orange colour grade, cool shadows with warm amber highlights",
    "indigo-coral":     "deep indigo shadows with warm coral accent light, rich colour grade",
    "forest-gold":      "dark green shadows with golden hour warm highlights, lush colour grade",
    "crimson-charcoal": "desaturated charcoal base with deep crimson accent light, moody grade",
    "slate-ice":        "cool steel blue colour grade, desaturated shadows, icy cyan highlights",
    "sunset":           "warm orange and magenta sunset colour grade, glowing backlight",
    "mint-navy":        "navy blue colour grade, fresh mint green practicals, clean and modern",
    "sand-terracotta":  "warm sand and terracotta colour grade, golden diffuse light, earthy tones",
}

EMOTION_PALETTES = {
    "dramatic":  ["crimson-charcoal", "sunset", "indigo-coral"],
    "serious":   ["slate-ice", "teal-amber", "crimson-charcoal"],
    "calm":      ["mint-navy", "forest-gold", "sand-terracotta"],
    "excited":   ["sunset", "indigo-coral", "teal-amber"],
    "concerned": ["indigo-coral", "slate-ice", "teal-amber"],
    "amused":    ["mint-navy", "sand-terracotta", "forest-gold"],
}

_MOOD_LINES = {
    "dramatic":     "The composition is high-contrast with strong diagonal tension.",
    "serious":      "The scene is still and weighty with minimal movement.",
    "calm":         "The scene is open and spacious with soft diffuse light.",
    "excited":      "The layout is dynamic with energetic implied motion.",
    "concerned":    "The atmosphere is heavy and uncertain.",
}

_WARM_PALETTES = {"forest-gold", "sunset", "sand-terracotta", "indigo-coral"}
_COOL_PALETTES  = {"slate-ice", "teal-amber", "mint-navy"}


def segment_palettes(emotions: list[str], rng: random.Random) -> list[str]:
    out: list[str] = []
    for e in emotions:
        pool = [p for p in EMOTION_PALETTES.get(e, list(PALETTES)) if not out or p != out[-1]] or list(PALETTES)
        out.append(rng.choice(pool))
    return out


def _cinematic_compose(scene: dict, palette: str, rng: random.Random, emotion: str) -> str:
    """Build a cinematographer's shot description from the rich scene schema."""
    parts = []

    # 1. Shot language
    shot  = scene.get("shot", "MS").upper()
    angle = scene.get("angle", "eye-level")
    parts.append(f"{shot}, {angle}.")

    # 2. Environment + lighting
    env      = (scene.get("environment") or "").strip().rstrip(".")
    lighting = (scene.get("lighting") or "").strip().rstrip(".")
    if env:
        parts.append(f"{env}.")
    if lighting:
        parts.append(f"{lighting}.")

    # 3. Foreground / midground / background layers
    layers = (scene.get("layers") or "").strip().rstrip(".")
    if layers:
        parts.append(f"{layers}.")

    # 4. Subject (protagonist + action + expression)
    subject = (scene.get("subject") or "").strip().rstrip(".")
    if subject:
        parts.append(f"{subject}.")

    # 5. Colour grade from palette
    grade = _CINEMATIC_GRADE.get(palette, "neutral cinematic colour grade")
    parts.append(f"Colour grade: {grade}.")

    # 6. Mood line from segment emotion
    mood_line = _MOOD_LINES.get(emotion, "")
    if mood_line:
        parts.append(mood_line)

    # 7. Technical spec
    parts.append("Full-bleed 16:9 frame, no borders, no panels.")
    parts.append(STYLES["cinematic"] + ".")

    # 8. Text overlay
    if scene.get("text"):
        place = rng.choice(["top", "bottom"])
        parts.append(
            f'Bold subtitle text "{scene["text"]}" in the {place} third of frame, '
            "Latin letters and digits only, fully legible against background. "
            "No other text, logos or watermarks."
        )
    else:
        parts.append("No text, subtitles, logos or watermarks.")

    return " ".join(parts)


def _illustrated_compose(scene: dict, style: str, palette: str, rng: random.Random, emotion: str) -> str:
    """Original illustrated-style prompt builder."""
    parts = [scene["visual"].strip().rstrip(".") + ".",
             "Full-bleed 16:9 illustration, background fills every edge, no panels, no borders, no white margins.",
             f"Style: {STYLES.get(style, STYLES[DEFAULT_STYLE])}.",
             f"Colour palette: {PALETTES[palette]}."]

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
        parts.append(
            f'A short label reading "{scene["text"]}" in bold Latin letters and digits sits in the {place} '
            "third of the frame, fully legible, not covering the main subject. "
            "No other text, letters, numbers or logos anywhere else in the image."
        )
    else:
        parts.append("The image contains no text, letters, numbers, logos or watermarks.")
    return " ".join(parts)


def compose(scene: dict, style: str, palette: str, rng: random.Random, emotion: str = "neutral") -> str:
    if style == "cinematic":
        return _cinematic_compose(scene, palette, rng, emotion)
    return _illustrated_compose(scene, style, palette, rng, emotion)


def character_reference_prompts(bible: dict) -> list[str]:
    """Three prompts to generate a character reference sheet: face close-up, half-body, full-body."""
    desc = bible.get("protagonist", {}).get("description", "Indian professional, early 30s")
    base = (f"{desc} "
            "Plain white studio background, clean neutral studio lighting, "
            "photorealistic, sharp focus, high production value.")
    return [
        f"Portrait close-up. {base} Calm neutral expression, looking directly at camera.",
        f"Half-body shot, slight three-quarter turn. {base} Relaxed confident posture.",
        f"Full body standing, arms relaxed at sides. {base} Confident stance.",
    ]
