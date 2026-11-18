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
        "label": "Night City",
        "prompt": (
            "Cozy bedroom at night, wide floor-to-ceiling window showing a wet city street below, "
            "neon sign reflections shimmering on the rain-slicked pavement, raindrops streaking down "
            "the glass in long silver lines, warm amber bedside lamp on, soft glow on the wooden "
            "floor and white duvet, a small reading nook in the corner with a steaming mug, "
            "curtains slightly open, deep navy sky outside. "
            "Photorealistic, cinematic, cozy atmosphere, 8K detail. "
            "No people, no text, no logo."
        ),
    },
    "mountain_forest": {
        "label": "Mountain Forest",
        "prompt": (
            "Cozy cabin living room, large panoramic window overlooking a dense pine forest and "
            "misty mountain peaks, heavy rain falling outside, droplets racing down the cold glass, "
            "soft green-grey light filtering through the fog, warm fireplace glow on the right, "
            "wooden beams on the ceiling, woollen throw on the armchair, a hot drink on the "
            "windowsill. "
            "Photorealistic, cinematic, calm and peaceful. "
            "No people, no text, no logo."
        ),
    },
    "ocean": {
        "label": "Ocean",
        "prompt": (
            "Seaside cottage living room, wide window looking out at a grey stormy ocean, waves "
            "rolling in slowly, rain falling on the dark water and the rocks below, droplets on the "
            "glass blurring the horizon slightly, warm cream-coloured interior, linen sofa, "
            "driftwood shelf, a single candle on the windowsill, soft natural light from outside. "
            "Photorealistic, moody coastal atmosphere, cinematic. "
            "No people, no text, no logo."
        ),
    },
    "countryside": {
        "label": "Countryside",
        "prompt": (
            "Farmhouse bedroom, small-paned window showing open green fields under a heavy rain sky, "
            "distant trees bending in the wind, rainwater running down the glass in rivulets, "
            "patchwork quilt on the iron bed, golden lantern on the nightstand, faded wooden "
            "floorboards, smell-of-earth atmosphere, overcast soft light outside. "
            "Photorealistic, rustic English countryside feel, cinematic. "
            "No people, no text, no logo."
        ),
    },
    "forest": {
        "label": "Forest",
        "prompt": (
            "Glass cabin treehouse bedroom, floor-to-ceiling window on three sides showing a dense "
            "rainforest canopy, rain pouring through the leaves and running down the glass, lush "
            "green and dark-teal tones outside, soft white fairy lights inside, minimalist bed with "
            "linen sheets, a single fern on the shelf, calm green light. "
            "Photorealistic, immersive forest atmosphere, cinematic. "
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

# Fixed ambient sleep music recipe — no model call needed.
SLEEP_MUSIC_RECIPE = {
    "genre": "ambient",
    "moods": ["dreamy", "calm"],
    "bpm": 60,
    "instruments": ["warm pad", "soft strings"],
    "caption": "English, ambient, dreamy, calm, 60 BPM, warm pad, soft strings, instrumental, no vocals, soft dynamics, steady",
}

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
