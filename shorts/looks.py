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

# Shorts-only looks that are popular on reels: positive wording only, one clear medium each.
TRENDING = {
    "pixar3d": {
        "label": "3D animated movie (Pixar-style)",
        "description": "Big-eyed, soft-featured characters with smooth stylised 3D shapes, warm glowing light and rich colour, like a family animated feature.",
        "look": ("Stylised 3D animated feature-film frame, appealing characters with big expressive eyes, smooth rounded shapes and soft subsurface-lit skin, detailed fabric and hair, "
                 "warm cinematic lighting with glowing rim light, rich saturated colour, shallow depth of field, polished studio-render finish. Computer-animated, not a photograph, not a painting."),
        "motion": 'Springy, appealing character animation: small squash and stretch on quick actions, eyes and brows lead each expression, soft follow-through of hair and cloth, smooth camera moves.',
        "allow": [],
    },
    "tinyworld": {
        "label": "Tiny world (miniature diorama)",
        "description": "Everything looks like a handmade miniature model seen through a macro lens: tilt-shift blur, tiny figures, toy-like detail.",
        "look": ("Miniature diorama look, the whole scene is a tiny handcrafted model with small figures, toy-like textures of clay, felt and painted wood, tilt-shift macro lens with strong "
                 "soft focus falloff, bright soft studio light, cheerful saturated colour, clean tabletop setting. Miniature model, not a full-size real place, not a painting."),
        "motion": 'Small, gentle movements of tiny figures and toy-like parts; slow macro camera moves such as a slow slide or a slow push in; the soft tilt-shift focus stays as it is.',
        "allow": ['blurry'],
    },
    "anime": {
        "label": "Anime film",
        "description": "Hand-drawn Japanese animation look: clean line art, painted skies, soft glow and emotional lighting.",
        "look": ("Japanese animated feature film frame, clean fine line art, flat cel colour with soft gradients, lush hand-painted background with detailed clouds and sky, "
                 "gentle bloom and lens glow, emotional golden-hour light, expressive eyes. Hand-drawn animation, not a photograph, not a 3D render."),
        "motion": 'Limited-animation rhythm: hair, cloth, leaves and clouds drift; the face and body stay mostly steady with small eye, brow and mouth changes; slow pans and push ins over the painted background.',
        "allow": [],
    },
    "claymation": {
        "label": "Claymation (stop-motion)",
        "description": "Soft clay characters with visible fingerprints and handmade sets, like a stop-motion short film.",
        "look": ("Stop-motion clay animation frame, characters sculpted from soft plasticine with visible fingerprint texture and slight imperfections, handmade miniature sets of card and fabric, "
                 "warm practical studio lights, shallow depth of field, charming handcrafted feel. Clay puppets, not a photograph, not a smooth digital render."),
        "motion": 'Stop-motion rhythm: movements go in small distinct steps like handmade puppet poses, slightly uneven and bouncy, never smooth fluid blur; clay shapes keep their sculpted form.',
        "allow": ['grainy', 'noisy', 'film grain', 'noise'],
    },
    "papercut": {
        "label": "Paper cut-out layers",
        "description": "Layered coloured paper shapes with soft shadows between the layers, like a handmade paper-craft scene.",
        "look": ("Layered paper-craft scene, shapes cut from coloured card stacked in depth, soft drop shadows between the layers, visible paper grain and torn edges, "
                 "warm tabletop light, harmonious limited colour palette. Paper cut-out artwork, not a photograph, not a 3D render."),
        "motion": 'Layers slide sideways against each other at different speeds for depth; paper pieces tilt, swing and slide rigidly like cut card, never bending like cloth or melting; the camera drifts slowly across the layers.',
        "allow": ['grainy', 'noisy', 'film grain', 'noise'],
    },
    "ghibli": {
        "label": "Soft watercolour storybook",
        "description": "Gentle hand-painted watercolour scenes with green nature, soft clouds and a warm nostalgic mood, like a classic animated fairy tale.",
        "look": ("Soft hand-painted watercolour storybook frame, gentle pencil outlines, luminous washes of colour, lush green nature, billowing clouds, warm nostalgic daylight, "
                 "calm and charming mood, painted paper texture. Hand-painted, not a photograph, not a 3D render."),
        "motion": 'Gentle, calm movement: grass, leaves, hair and clouds sway in a soft breeze; characters move slowly and naturally; slow drifting camera.',
        "allow": [],
    },
    "lowpoly": {
        "label": "Isometric 3D game world",
        "description": "Clean isometric miniature scenes with smooth pastel 3D blocks, like a cosy puzzle-game level.",
        "look": ("Cosy isometric 3D game-world scene, smooth chunky shapes in pastel colours, clean geometric buildings and soft ambient-occlusion shadows, "
                 "bright gentle light, tidy composition, simple stylised textures. Stylised 3D render, not a photograph, not a painting."),
        "motion": 'Simple, tidy, loop-like movements of small figures and vehicles; a slow smooth camera orbit or slide around the scene; steady light.',
        "allow": [],
    },
    "cyberpunk": {
        "label": "Neon cyberpunk night",
        "description": "Rainy night streets lit by pink and cyan neon, glossy reflections and futuristic city glow.",
        "look": ("Cinematic neon cyberpunk night scene, wet reflective streets, strong magenta and cyan neon light against deep blue shadow, glowing signs without readable text, "
                 "atmospheric haze, high contrast, sharp detail, moody futuristic city. Digital cinematic art, not a daylight scene."),
        "motion": 'Rain falls, steam and haze drift, neon signs glow steadily and reflections ripple on wet ground; the subject moves slowly and deliberately; slow push in or slide of the camera.',
        "allow": ['flicker'],
    },
}


def presets() -> dict[str, dict]:
    return {"realism": REALISM, **TRENDING, **{k: {"label": p["label"], "description": p["description"], "look": p["look"]} for k, p in styles.PRESETS.items()}}


def motion_hint(short: dict) -> str:
    """How the chosen style moves (for the motion writer); empty for styles without one."""
    sid = style_id(short)
    return presets()[sid].get("motion", "") if sid else ""


def negative(short: dict, base: str) -> str:
    """`base` (the Wan negative prompt) without the words the chosen style needs (tilt-shift blur, clay grain, neon flicker)."""
    allowed = {w.lower() for w in (presets()[style_id(short)].get("allow", []) if style_id(short) else [])}
    return ", ".join(w for w in base.split(", ") if w.lower() not in allowed)


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
