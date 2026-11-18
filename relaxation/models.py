"""Constants and scene definitions for the relaxation channel.

Each session generates one 3-hour ambient rain video:
  Qwen room image -> Wan rain clip -> 2K upscale -> audio mix -> 3h loop -> YouTube
"""
import hashlib

# ── video geometry ────────────────────────────────────────────────────────────
CLIP_SIZE = "1280x720"       # landscape 16:9 Wan I2V request size
OUT_W, OUT_H = 1920, 1080    # final video resolution (1080p 16:9)
OUT_FPS = 30
CLIP_S = 9.0                 # target rain clip duration (Wan I2V at 16fps, max ~10s)
LOOP_HOURS = 3               # loop target
LOOP_S = LOOP_HOURS * 3600   # 10800 seconds

# ── gateway model ids ─────────────────────────────────────────────────────────
IMAGE_MODEL = "qwen-image-2.1"
IMAGE_STEPS = 35             # cleaner faces/details at 35 (same as characters)
I2V_MODEL = "wan-2.2-i2v-a14b"
I2V_FPS = 16
I2V_MAX_FRAMES = 161         # Wan I2V hard limit

# ── media row kinds ───────────────────────────────────────────────────────────
KIND_SCENE = "rl_scene"      # Qwen room image
KIND_RAIN = "rl_rain"        # Wan rain clip (MP4)
KIND_AUDIO = "rl_audio"      # mixed rain + music (WAV then AAC embedded)
KIND_FINAL = "rl_final"      # 3-hour MP4

# ── scene catalogue ───────────────────────────────────────────────────────────
# Each scene = a Qwen image prompt for a cozy indoor room with that view outside.
# Prompt order: composition first (Qwen weights early tokens most), then lighting,
# then the window scene, then style. Positive words only — Qwen draws every word.
SCENES: dict[str, dict] = {
    "night_city": {
        "label": "Mumbai Monsoon Night",
        "prompt": (
            "Modern Mumbai apartment bedroom, high floor, wide floor-to-ceiling glass window, "
            "heavy monsoon rain sheeting down the glass in thick silver streaks, the city far below "
            "blurred into smeared amber and white lights through the downpour, dark navy monsoon sky, "
            "low teak-wood bed with crisp white linen, a brass bedside lamp casting a warm amber cone, "
            "a steaming cup of chai on the windowsill, rain rivulets merging and racing to the bottom "
            "of the glass, distant buildings and flyovers barely visible through the curtain of rain. "
            "Photorealistic, cinematic, intimate and warm against the storm outside, 8K detail. "
            "No people, no text, no logo."
        ),
    },
    "mountain_forest": {
        "label": "Kerala Forest Cottage",
        "prompt": (
            "Old Kerala wooden cottage bedroom, wide teak-framed open window looking out into a "
            "dense tropical garden in heavy monsoon rain, giant banana leaves and jackfruit trees "
            "catching the downpour, water streaming in silver ropes off every broad leaf, a moss-covered "
            "stone path outside glistening wet, small brass oil lamp on the sill glowing amber, "
            "carved wooden bed with a hand-woven cotton bedspread in deep indigo, old wooden floorboards, "
            "the garden a wall of deep green and grey rain mist, smell of petrichor and wet earth. "
            "Photorealistic, lush Kerala monsoon atmosphere, cinematic depth. "
            "No people, no text, no logo."
        ),
    },
    "ocean": {
        "label": "Himalayan Pine Lodge",
        "prompt": (
            "Mountain lodge bedroom in the Himalayas, thick deodar-pine walls and heavy exposed beams, "
            "wide wood-framed window looking into a dense pine forest in monsoon mist, rain falling "
            "in long silver threads through the dark canopy, the forest floor a mat of wet pine needles, "
            "distant ridgelines fading into grey cloud, warm amber glow from a hanging wrought-iron "
            "lantern inside, a woollen Kullu shawl folded on a solid-wood bed with white cotton quilts, "
            "a tin mug of ginger tea steaming on the sill, pine branches outside catching and dripping "
            "the rain in a steady curtain. "
            "Photorealistic, misty Himalayan atmosphere, cinematic. "
            "No people, no text, no logo."
        ),
    },
    "countryside": {
        "label": "Rajasthani Haveli Courtyard",
        "prompt": (
            "Old Rajasthani haveli bedroom, ornate hand-carved wooden jharokha window opening onto "
            "an inner stone courtyard two floors below, heavy monsoon rain falling on ancient pink "
            "sandstone, water streaming down carved columns and pooling on the cobblestones, "
            "a neem tree in the corner with rain hammering its small leaves, marigold petals from "
            "a broken garland floating in a puddle, a brass diya flickering inside on a low carved "
            "wooden shelf, old embroidered cotton quilt on a wide charpai, the sandstone walls "
            "below glistening dark in the rain, the smell of wet ancient stone. "
            "Photorealistic, heritage Rajasthani atmosphere, warm and ancient, cinematic. "
            "No people, no text, no logo."
        ),
    },
    "forest": {
        "label": "Goa Monsoon Villa",
        "prompt": (
            "Old Portuguese-style Goa villa bedroom, wide arched wood-frame window open to a "
            "lush tropical garden in full monsoon rain, an ancient mango tree with broad dark "
            "canopy shedding sheets of water, giant ferns and bougainvillea heavy with rain, "
            "terracotta garden tiles streaming with water, a glimpse of dark grey Arabian Sea "
            "between swaying coconut palms at the far end, warm rattan pendant lamp inside "
            "casting soft yellow light on whitewashed walls, white cotton curtains lifting gently "
            "in the wet breeze, four-poster bed with a thin linen coverlet, old red oxide flooring. "
            "Photorealistic, Goan monsoon atmosphere, lush and cinematic. "
            "No people, no text, no logo."
        ),
    },
}

DEFAULT_SCENE = "night_city"

# ── Wan rain motion prompt ────────────────────────────────────────────────────
# Applied to every scene. Describes only what MOVES: rain + light.
# No style words, no composition (the image already shows those).
RAIN_MOTION = (
    "Raindrops fall steadily outside the window, streaking down the glass in long vertical lines. "
    "Rivulets of water merge and run to the bottom of the pane. "
    "The light on the wet surface outside shimmers gently as rain stirs it. "
    "The scene holds still; only the rain moves. "
    "Continuous smooth motion, no camera shake, no scene cut."
)

RAIN_NEGATIVE = (
    "camera shake, sudden light change, scene cut, jump cut, people appearing, text, watermark, "
    "logo, flicker, morphing, blurry, pixelated, grainy"
)

# ── audio ─────────────────────────────────────────────────────────────────────
RAIN_ASSET = "rain.mp3"          # expected in relaxation/assets/; fallback = pink noise
RAIN_LUFS = -18.0                # rain foreground target loudness
MUSIC_LUFS = -34.0               # ambient music bed loudness (ducked well below rain)
FINAL_LUFS = -14.0               # YouTube standard target for the final file

# Per-scene YuE2 music recipes.
# Caption rules: 8-12 comma-separated tags, language first, BPM explicit,
# "no percussion" keeps drums out (caption-only control — no API flag exists),
# "no vocals" + "instrumental" doubly enforce silence.
# Instrument is the differentiator: each scene gets one that fits its mood.
# Empty [verse]/[bridge] section tags = instrumental passage; [Instrumental]
# is NOT a valid tag and gets sung as lyric text (see story3/music.py note).
SCENE_MUSIC: dict[str, dict] = {
    "night_city": {
        "caption": "English, ambient, sleep music, tranquil, peaceful, 60 BPM, soft piano, warm pad, instrumental, no vocals, no percussion, soft dynamics",
        "note": "soft piano — clean, intimate, pairs with Mumbai monsoon night",
    },
    "mountain_forest": {
        "caption": "English, ambient, sleep music, tranquil, serene, 58 BPM, flute, soft strings, instrumental, no vocals, no percussion, soft dynamics",
        "note": "flute — airy and natural, matches forest and mist",
    },
    "ocean": {
        "caption": "English, ambient, sleep music, tranquil, meditative, 56 BPM, cello, warm pad, instrumental, no vocals, no percussion, soft dynamics",
        "note": "cello — deep and resonant, moves like waves",
    },
    "countryside": {
        "caption": "English, ambient, sleep music, tranquil, pastoral, 60 BPM, nylon guitar, soft strings, instrumental, no vocals, no percussion, soft dynamics",
        "note": "nylon guitar — organic warmth, suits open fields",
    },
    "forest": {
        "caption": "English, ambient, sleep music, tranquil, ethereal, 58 BPM, harp, warm pad, instrumental, no vocals, no percussion, soft dynamics",
        "note": "harp — crystalline and floating, matches forest canopy",
    },
}

# Fallback used when the scene has no entry above
SLEEP_MUSIC_RECIPE = {
    "caption": "English, ambient, sleep music, tranquil, peaceful, 60 BPM, soft piano, warm pad, instrumental, no vocals, no percussion, soft dynamics",
}


def music_recipe(scene: str) -> dict:
    """Return the music recipe dict (with 'caption' key) for a given scene."""
    return SCENE_MUSIC.get(scene) or SLEEP_MUSIC_RECIPE

# ── default session settings ──────────────────────────────────────────────────
DEFAULT_SETTINGS = {
    "scene": DEFAULT_SCENE,
    "hours": LOOP_HOURS,
    "music_enabled": True,
    "music_level": MUSIC_LUFS,
    "rain_level": RAIN_LUFS,
    "image_model": IMAGE_MODEL,
    "upscale": "2k",
    "seed": 7,
}

# ── YouTube upload ────────────────────────────────────────────────────────────
YT_CATEGORY_MUSIC = "10"         # YouTube category: Music
UPLOAD_CHUNK = 8 * 1024 * 1024   # 8 MB upload chunks


def session_id() -> str:
    import time
    raw = f"rl-{time.time()}"
    return "rl-" + hashlib.sha1(raw.encode()).hexdigest()[:8]
