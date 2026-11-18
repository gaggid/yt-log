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
I2V_STEPS = 10

# Time estimate: 1280x720 is the native resolution for Wan I2V 14B.
# Gateway docs give 0.59 s/frame/step at 480x832 (portrait shorts base).
# 1280x720 = 921,600 px vs 480x832 = 399,360 px → 2.3x pixels → 2.3x time.
# shorts/pipelines.py uses the 480p base + a 2.3x HD multiplier at call time;
# we bake the 720p cost in directly since we never run at 480p here.
I2V_S_PER_FRAME = 0.59 * 2.3 * I2V_STEPS   # ~13.6 s/frame at native 720p, 10 steps
OVERHEAD_S = 25                               # per request: load, queue, decode, download


def estimate_rain_s(frames: int) -> int:
    """Estimated gateway seconds for one rain clip at 1280x720."""
    return int(OVERHEAD_S + frames * I2V_S_PER_FRAME)

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
        "label": "Tokyo Rain Garden",
        "prompt": (
            "Traditional Japanese-style bedroom at night, wide sliding wooden door fully open to a "
            "lush private garden, low platform bed with clean white linen on a dark wood frame, "
            "a paper shoji lantern glowing warm amber inside, the garden outside lit by two stone "
            "lanterns half-hidden in moss, a small koi pond with rain hammering its surface into "
            "silver rings, ancient pine and maple trees with rain streaming off every branch, "
            "hanging Spanish moss swaying slightly, large flat stones glistening wet, dense green "
            "ferns at the base of every rock, rain falling in long silver threads through the dark "
            "canopy, deep mist behind the trees, the wooden floor just inside catching the glow. "
            "Photorealistic, cinematic, intimate and deeply calm, 8K detail. "
            "No people, no text, no logo."
        ),
    },
    "mountain_forest": {
        "label": "Scandinavian Forest Cabin",
        "prompt": (
            "Nordic pine cabin bedroom, floor-to-ceiling glass wall looking straight into a "
            "spruce and birch forest in heavy rain, rain running in sheets down the cold glass, "
            "the forest floor a carpet of dark wet moss and fallen needles, birch trunks white "
            "against the grey-green depths, mist threading between the trees and softening the "
            "distance, inside a low wooden bed with a thick cream wool blanket, a simple pine "
            "nightstand, a single white candle burning, warm amber glow on the pale timber walls, "
            "rain streaming off the sloped roof overhang just above the glass, pine branches dipping "
            "and shedding water in the wind. "
            "Photorealistic, Scandinavian minimalist, calm and cinematic. "
            "No people, no text, no logo."
        ),
    },
    "ocean": {
        "label": "Bali Jungle Villa",
        "prompt": (
            "Open-air Balinese villa bedroom, wide teak-wood pavilion with no wall on one side "
            "facing a lush terraced garden in tropical rain, giant banana leaves with water "
            "cascading off their tips in heavy silver drops, a lotus pond directly below with "
            "rain pocking its surface, tall coconut palms swaying in the warm rain wind, "
            "a distant misty volcanic ridge barely visible through the downpour, inside a "
            "four-poster bed draped in white linen, a rattan lamp casting warm honey light, "
            "dark teak floor with the rain just reaching the edge, tropical flowers on the "
            "low side table, the air thick with the smell of wet earth and frangipani. "
            "Photorealistic, Balinese tropical atmosphere, lush and cinematic. "
            "No people, no text, no logo."
        ),
    },
    "countryside": {
        "label": "Alpine Mountain Chalet",
        "prompt": (
            "Swiss alpine chalet bedroom, wide low window with thick stone sill looking out at "
            "a steep pine-covered mountain face in rain and low cloud, rain running in rivulets "
            "down the aged wooden shutters, pine trees dense and dark outside with rain dripping "
            "off every needle, a mountain stream barely audible through the glass, grey cloud "
            "hugging the cliff face just above the treeline, inside a heavy carved-wood bed with "
            "a thick feather duvet and checked wool blanket, an iron wall sconce with a warm "
            "amber bulb, old wooden plank ceiling and beams, a ceramic mug on the stone sill, "
            "the room built into the hillside like a shelter. "
            "Photorealistic, Alpine atmosphere, cosy and cinematic. "
            "No people, no text, no logo."
        ),
    },
    "forest": {
        "label": "Glass Treehouse Forest",
        "prompt": (
            "Elevated glass treehouse bedroom deep in an ancient temperate rainforest, three glass "
            "walls looking in every direction into the forest canopy at mid-height, enormous old-growth "
            "trees with thick twisted trunks and wide canopies, rain pouring off every leaf in "
            "curtains of water, the forest floor far below dark and wet, long hanging moss on every "
            "branch swaying in the warm rain, ferns at every level, the inside of the room dim "
            "and green-lit, a low bed with linen sheets, tiny warm fairy lights strung along the "
            "beams, the glass completely surrounded by wet leaves and rain, no sky visible — only "
            "layers of forest in every direction. "
            "Photorealistic, immersive ancient forest atmosphere, cinematic depth. "
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
        "note": "soft piano — clean, intimate, pairs with Tokyo rain garden",
    },
    "mountain_forest": {
        "caption": "English, ambient, sleep music, tranquil, serene, 58 BPM, flute, soft strings, instrumental, no vocals, no percussion, soft dynamics",
        "note": "flute — airy and natural, matches Scandinavian forest and mist",
    },
    "ocean": {
        "caption": "English, ambient, sleep music, tranquil, meditative, 56 BPM, cello, warm pad, instrumental, no vocals, no percussion, soft dynamics",
        "note": "cello — deep and resonant, pairs with Bali jungle warmth",
    },
    "countryside": {
        "caption": "English, ambient, sleep music, tranquil, pastoral, 60 BPM, nylon guitar, soft strings, instrumental, no vocals, no percussion, soft dynamics",
        "note": "nylon guitar — organic warmth, suits Alpine mountain chalet",
    },
    "forest": {
        "caption": "English, ambient, sleep music, tranquil, ethereal, 58 BPM, harp, warm pad, instrumental, no vocals, no percussion, soft dynamics",
        "note": "harp — crystalline and floating, matches glass treehouse canopy",
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
