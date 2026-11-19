"""Constants and scene definitions for the relaxation channel.

Each session generates one 3-hour ambient rain video:
  Qwen room image -> Wan rain clip -> 2K upscale -> audio mix -> 3h loop -> YouTube
"""
import hashlib

# ── video geometry ────────────────────────────────────────────────────────────
IMAGE_SIZE = "1280x720"      # the room picture (Qwen)
CLIP_SIZE = "832x480"        # Wan I2V request size: the same 480p base the shorts use (480x832 turned); the 2K upscale step does the rest
OUT_W, OUT_H = 1920, 1080    # final video resolution (1080p 16:9)
OUT_FPS = 30
CLIP_S = 5.0                 # rain clip duration: 81 frames at 16 fps; video.py loops it
LOOP_HOURS = 3               # loop target
LOOP_S = LOOP_HOURS * 3600   # 10800 seconds

# ── gateway model ids ─────────────────────────────────────────────────────────
IMAGE_MODEL = "qwen-image-2.1"
IMAGE_STEPS = 35             # cleaner faces/details at 35 (same as characters)
I2V_MODEL = "wan-2.2-i2v-a14b"
I2V_FPS = 16
I2V_MAX_FRAMES = 161         # Wan I2V hard limit
I2V_STEPS = 10

# Time estimate: the gateway docs give 0.59 s/frame/step at 480x832 (the shorts base), and 832x480
# has the same pixel count. A first try at 1280x720 and 145 frames (2.3x the pixels, 1.8x the frames)
# ran for 8 minutes without finishing one step with the 16 GB card's VRAM full, and the gateway
# dropped the job ("ComfyUI request failed ... Read timed out"); the shorts never ask for more than
# about 3 s at 480p.
I2V_S_PER_FRAME = 0.59 * I2V_STEPS         # ~5.9 s/frame at 832x480, 10 steps
OVERHEAD_S = 25                               # per request: load, queue, decode, download


def estimate_rain_s(frames: int) -> int:
    """Estimated gateway seconds for one rain clip at 832x480."""
    return int(OVERHEAD_S + frames * I2V_S_PER_FRAME)


def total_s(settings: dict) -> float:
    """Length of the finished video in seconds: `minutes` when set (test runs), else `hours`."""
    if settings.get("minutes"):
        return float(settings["minutes"]) * 60
    return float(settings.get("hours") or LOOP_HOURS) * 3600


def duration_label(settings: dict) -> str:
    """'5 minutes' or '3 hours', for titles and messages."""
    t = total_s(settings)
    if t < 3600:
        n = round(t / 60)
        return f"{n} minute{'s' if n != 1 else ''}"
    h = t / 3600
    h = int(h) if abs(h - round(h)) < 0.01 else round(h, 1)
    return f"{h} hour{'s' if h != 1 else ''}"

# ── media row kinds ───────────────────────────────────────────────────────────
KIND_SCENE = "rl_scene"      # Qwen room image
KIND_RAIN = "rl_rain"        # Wan rain clip (MP4)
KIND_AUDIO = "rl_audio"      # mixed rain + music (WAV then AAC embedded)
KIND_FINAL = "rl_final"      # 3-hour MP4

# ── scene catalogue ───────────────────────────────────────────────────────────
# Each scene = a Qwen image prompt seen in the FIRST PERSON from the bed, looking out at the rain
# (never the building seen from outside: Qwen draws every word, so the building is never described).
# Prompt order: composition first (Qwen weights early tokens most), then lighting,
# then the window scene, then style. Positive words only — Qwen draws every word.
SCENES: dict[str, dict] = {
    "night_city": {
        "label": "Tokyo Rain Garden",
        "prompt": (
            "First-person point of view from a low platform bed inside a Japanese bedroom at night, "
            "looking straight out through a wide open sliding wooden door at a private moss garden in "
            "heavy rain, the door frame and the dark wooden floor edge framing the view, the soft edge "
            "of a white linen blanket in the lower foreground, a paper shoji lantern glowing warm amber "
            "at one side of the frame, outside two stone lanterns half-hidden in moss, a small koi pond "
            "with rain hammering its surface into silver rings, ancient pine and maple trees with rain "
            "streaming off every branch, large flat stones glistening wet, dense green ferns at the base "
            "of every rock, rain falling in long silver threads through the dark canopy, deep mist "
            "behind the trees. "
            "Photorealistic, cinematic, intimate and deeply calm, 8K detail. "
            "No people, no text, no logo."
        ),
    },
    "mountain_forest": {
        "label": "Scandinavian Forest Cabin",
        "prompt": (
            "First-person point of view from a cosy wooden bed inside a Nordic cabin bedroom, "
            "looking straight out through a floor-to-ceiling glass wall at a spruce and birch forest "
            "in heavy rain, rain running in sheets down the cold glass, the thick cream wool blanket "
            "across the lower foreground, a single white candle burning on a pine nightstand at the "
            "edge of the frame, warm amber glow on the pale timber window frame, outside the forest "
            "floor a carpet of dark wet moss and fallen needles, birch trunks white against the "
            "grey-green depths, mist threading between the trees and softening the distance, pine "
            "branches dipping and shedding water, rain streaming off the roof overhang just above the "
            "glass. "
            "Photorealistic, Scandinavian minimalist, calm and cinematic. "
            "No people, no text, no logo."
        ),
    },
    "ocean": {
        "label": "Bali Jungle Villa",
        "prompt": (
            "First-person point of view from a four-poster bed draped in white linen inside an open-air "
            "Balinese villa pavilion, looking straight out past the bed curtains at a lush terraced "
            "garden in tropical rain, the carved teak pillars and the edge of the roof framing the "
            "view, giant banana leaves with water cascading off their tips in heavy silver drops, a "
            "lotus pond just beyond the dark teak floor with rain pocking its surface, tall coconut "
            "palms swaying in the warm rain wind, a distant misty volcanic ridge barely visible through "
            "the downpour, a rattan lamp casting warm honey light at the edge of the frame, tropical "
            "flowers on a low side table. "
            "Photorealistic, Balinese tropical atmosphere, lush and cinematic. "
            "No people, no text, no logo."
        ),
    },
    "countryside": {
        "label": "Alpine Mountain Chalet",
        "prompt": (
            "First-person point of view from a heavy carved-wood bed inside a Swiss alpine chalet "
            "bedroom, looking out through a wide low window with a thick stone sill at a steep "
            "pine-covered mountain face in rain and low cloud, the checked wool blanket and feather "
            "duvet in the lower foreground, rain running in rivulets down the aged wooden shutters and "
            "the window glass, an iron wall sconce with a warm amber bulb and old wooden beams at the "
            "edge of the frame, a ceramic mug on the stone sill, outside the pine trees dense and dark "
            "with rain dripping off every needle, grey cloud hugging the cliff face just above the "
            "treeline. "
            "Photorealistic, Alpine atmosphere, cosy and cinematic. "
            "No people, no text, no logo."
        ),
    },
    "forest": {
        "label": "Glass Treehouse Forest",
        "prompt": (
            "First-person point of view from a low bed with linen sheets in a dim green-lit room high "
            "among the branches, looking straight out through floor-to-ceiling glass covered in rain "
            "streaks at an ancient temperate rainforest canopy at eye level, the glass filling the "
            "whole frame, tiny warm fairy lights along a wooden beam at the top edge, outside enormous "
            "old-growth trees with thick twisted trunks and wide canopies, rain pouring off every leaf "
            "in curtains of water, long hanging moss swaying in the warm rain, ferns at every level, "
            "layers of misty forest in every direction, the forest floor far below dark and wet. "
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
    "Rain falls steadily through the view outside in long thin vertical streaks. "
    "Water drips from the leaves and edges, and rivulets run down any glass in front. "
    "The light on the wet surfaces shimmers gently as rain stirs it, and a light mist drifts slowly. "
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
