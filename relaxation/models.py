"""Constants and scene definitions for the relaxation channel.

Each session generates one 3-hour ambient rain video:
  Qwen room image -> Wan rain clip -> 2K upscale -> audio mix -> 3h loop -> YouTube
"""
import hashlib

# ── video geometry ────────────────────────────────────────────────────────────
IMAGE_SIZE = "2048x1152"     # the room picture (Qwen): the gateway allows 2359296 pixels for qwen-image-2.1, which is exactly 2048x1152 at 16:9
CLIP_SIZE = "1280x720"       # Wan I2V 14B at its ceiling: the gateway caps wan-2.2-i2v-a14b at max_pixels 921600 (= 1280x720); the 2K upscale step follows
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

# Time estimate. Measured in the gateway docs (RTX 4060 Ti 16 GB, 14B image-to-video, 10 steps, no speed
# LoRA): 480x640, 81 frames took 495 s, about 0.59 s per frame per step at 480x832-sized pictures. The
# cost grows faster than the pixel count (the 5B model took 3.2x the time per step for 2.26x the pixels
# at 1280x704), so the estimate scales with pixels ** 1.4. The first 1280x720 try used 145 frames and was
# dropped by the gateway ("ComfyUI request failed ... Read timed out") after 489 s, still on its first step.
I2V_S_PER_FRAME_480 = 0.59 * I2V_STEPS      # ~5.9 s/frame at 832x480, 10 steps
OVERHEAD_S = 25                               # per request: load, queue, decode, download


def estimate_rain_s(frames: int, size: str = "") -> int:
    """Estimated gateway seconds for one rain clip (default: the clip size above)."""
    w, h = (int(x) for x in (size or CLIP_SIZE).split("x"))
    return int(OVERHEAD_S + frames * I2V_S_PER_FRAME_480 * (w * h / (832 * 480)) ** 1.4)


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
            "Soft blue moonlit night, gently and evenly lit, every detail clearly visible, warm glow from the lamps, calm and inviting, not dark and not gloomy. "
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
            "Soft blue moonlit night, gently and evenly lit, every detail clearly visible, warm glow from the lamps, calm and inviting, not dark and not gloomy. "
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
            "Soft blue moonlit night, gently and evenly lit, every detail clearly visible, warm glow from the lamps, calm and inviting, not dark and not gloomy. "
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
            "Soft blue moonlit night, gently and evenly lit, every detail clearly visible, warm glow from the lamps, calm and inviting, not dark and not gloomy. "
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
            "Soft blue moonlit night, gently and evenly lit, every detail clearly visible, warm glow from the lamps, calm and inviting, not dark and not gloomy. "
            "No people, no text, no logo."
        ),
    },
}

DEFAULT_SCENE = "night_city"

# ── Wan rain motion prompt ────────────────────────────────────────────────────
# Applied to every scene. Describes only what MOVES: rain + light.
# No style words, no composition (the image already shows those).
RAIN_MOTION = (
    "Fine, thin rain falls fast and straight down in many long slender translucent streaks, "
    "the natural speed of real rain. Small bright splashes and rings appear where the drops land "
    "on water, wet ground and leaves, and the leaves tremble lightly under the drops. "
    "Everything else stays perfectly still: the room, the lamps, the trees, the light and the camera. "
    "The brightness never changes. Continuous natural motion, no scene cut."
)

RAIN_NEGATIVE = (
    "slime, goo, thick dripping liquid, blobs, globs, sticky strands, melting, wobbling water, "
    "slow motion, floating drops, huge drops, darkening, brightness change, fade, flicker, "
    "camera shake, camera movement, scene cut, jump cut, people, text, watermark, logo, morphing, "
    "blurry, pixelated, grainy"
)

# ── audio ─────────────────────────────────────────────────────────────────────
RAIN_ASSET = "rain.mp3"          # expected in relaxation/assets/; fallback = pink noise
RAIN_LUFS = -31.0                # rain BACKGROUND: felt, not noticed (11 LU under the music)
MUSIC_LUFS = -20.0               # ambient music FOREGROUND (the whole mix is then normalised to FINAL_LUFS)
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
