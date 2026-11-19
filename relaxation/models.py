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
CLIP_S = 3.5                 # rain clip duration: 57 frames at 16 fps; the 0.5 s seam cross-fade (SEAM_S) leaves a loop of about 3 s
LOOP_HOURS = 3               # loop target
LOOP_S = LOOP_HOURS * 3600   # 10800 seconds

# ── gateway model ids ─────────────────────────────────────────────────────────
IMAGE_MODEL = "qwen-image-2.1"
IMAGE_STEPS = 35             # cleaner faces/details at 35 (same as characters)
I2V_MODEL = "wan-2.2-i2v-a14b"
I2V_FPS = 16
I2V_MAX_FRAMES = 161         # Wan I2V hard limit
I2V_STEPS = 10

# Time estimate, from what was measured on the RTX 4060 Ti 16 GB (14B image-to-video, 10 steps, no speed LoRA):
#   1280x720, 81 frames: 2930 s (about 272 s per step)      832x480, 49 frames: 360 s
# Attention cost grows faster than the number of tokens (latent frames x picture patches), so the
# time scales with tokens ** 1.5 from the 1280x720 / 81 frame measurement.
OVERHEAD_S = 60                               # per request: model load, queue, decode, download
_REF_S, _REF_FRAMES, _REF_PX = 2900.0, 81, 1280 * 720


def estimate_rain_s(frames: int, size: str = "") -> int:
    """Estimated gateway seconds for one rain clip (default: the clip size above)."""
    w, h = (int(x) for x in (size or CLIP_SIZE).split("x"))
    tokens = ((frames - 1) // 4 + 1) * (w * h) / (((_REF_FRAMES - 1) // 4 + 1) * _REF_PX)
    return int(OVERHEAD_S + _REF_S * tokens ** 1.5)


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
KIND_THUMB = "rl_thumb"      # the YouTube thumbnail (JPEG)
KIND_THUMB_PIC = "rl_thumbpic"   # the picture under the thumbnail's words: a happy person by the rainy window (Qwen), no words in it

# ── scene catalogue ───────────────────────────────────────────────────────────
# Each scene = a Qwen image prompt seen in the FIRST PERSON from the bed, looking out at the rain
# (never the building seen from outside: Qwen draws every word, so the building is never described).
# Prompt order: composition first (Qwen weights early tokens most), then lighting,
# then the window scene, then style. Positive words only — Qwen draws every word.
SCENES: dict[str, dict] = {
    "night_city": {
        "label": "Tokyo Rain Garden",
        "instruments": ["soft piano", "harp", "bamboo flute", "kalimba"],
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
        "flame": True,           # a real flame (candle, oil or butter lamp): it may flicker softly
        "instruments": ["flute", "soft piano", "nylon guitar"],
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
        "instruments": ["kalimba", "harp", "bamboo flute"],
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
        "instruments": ["nylon guitar", "soft piano", "harp"],
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
        "instruments": ["harp", "kalimba", "soft piano", "flute"],
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
    "himalayan_ridge": {
        "label": "Himalayan Mountain Lodge",
        "flame": True,           # a real flame (candle, oil or butter lamp): it may flicker softly
        "instruments": ["bamboo flute", "singing bowls", "soft piano"],
        "prompt": (
            "First-person point of view from a wooden bed beside a wide window in a Himalayan mountain "
            "lodge, looking straight out at a pine and rhododendron ridge with snow peaks half hidden in "
            "rain clouds, rain running down the window glass, the thick wool blanket across the lower "
            "foreground, a small oil lamp glowing warm amber on the sill at the edge of the frame, a "
            "strand of wet colourful prayer flags hanging still on the porch rail just outside, a deep "
            "valley below filled with drifting mist, rain falling in fine silver lines across the whole "
            "view. Photorealistic, Himalayan atmosphere, calm and cinematic. Soft blue pre-dawn light, "
            "gently and evenly lit, every detail clearly visible, calm and inviting, not dark and not "
            "gloomy. No people, no text, no logo."
        ),
    },
    "monastery_window": {
        "label": "Mountain Monastery Window",
        "flame": True,           # a real flame (candle, oil or butter lamp): it may flicker softly
        "instruments": ["singing bowls", "bamboo flute", "harp"],
        "prompt": (
            "First-person point of view sitting on a wide stone window seat with a folded saffron blanket "
            "inside a mountain monastery room, looking straight out through a deep arched stone window at "
            "a misty valley far below, terraced rooftops and white stupas in the rain, rain streaming off "
            "the carved wooden eaves, a brass butter lamp burning warm gold on the sill at the edge of "
            "the frame, dark wooden shutters folded open on both sides, distant peaks fading into "
            "grey-blue cloud, rain falling in long thin lines. Photorealistic, serene monastery "
            "atmosphere, calm and cinematic. Deep blue moonlit night with soft mist, a few warm lit windows glowing in the village far below, gently and evenly lit, every detail "
            "clearly visible, calm and inviting, not dark and not gloomy. No people, no text, no logo."
        ),
    },
    "courtyard": {
        "label": "Quiet Courtyard Veranda",
        "instruments": ["nylon guitar", "harp", "soft piano", "bamboo flute"],
        "prompt": (
            "First-person point of view from a cushioned wooden swing seat on the covered veranda of a "
            "traditional courtyard house, looking straight out at a quiet stone courtyard in steady rain, "
            "a lotus pond in the centre with rain rings spreading across it, a banyan tree with glossy "
            "wet leaves, terracotta roof tiles with rain pouring off the edge in a line of silver drops, "
            "carved wooden pillars framing the view on both sides, a brass hanging lamp glowing warm at "
            "the edge of the frame, wet stone floor reflecting the glow. Photorealistic, peaceful "
            "courtyard atmosphere, calm and cinematic. Soft golden-blue evening light, gently and evenly "
            "lit, every detail clearly visible, calm and inviting, not dark and not gloomy. No people, no "
            "text, no logo."
        ),
    },
    "old_town_lane": {
        "label": "Old Town Lane Balcony",
        "instruments": ["soft piano", "nylon guitar", "vibraphone"],
        "prompt": (
            "First-person point of view from a wooden balcony window on the first floor of an old town "
            "house, looking down a narrow cobblestone lane in steady night rain, warm glowing windows and "
            "hanging lanterns on old stone buildings on both sides, their light reflecting on the shining "
            "wet stones, rain falling in long silver lines through the lamplight, small puddles with rain "
            "rings, a wrought iron balcony rail and a pot of wet green plants in the lower foreground, a "
            "street lamp softly glowing at the far end of the lane. Photorealistic, romantic old town "
            "atmosphere, calm and cinematic. Soft blue night, gently and evenly lit, every detail clearly "
            "visible, calm and inviting, not dark and not gloomy. No people, no text, no logo."
        ),
    },
    "kerala_veranda": {
        "label": "Kerala Monsoon Veranda",
        "flame": True,           # a real flame (candle, oil or butter lamp): it may flicker softly
        "instruments": ["bamboo flute", "nylon guitar", "harp", "kalimba"],
        "prompt": (
            "First-person point of view from a cane reclining chair on the veranda of a traditional "
            "Kerala house, looking straight out at a lush monsoon garden, coconut palms and banana plants "
            "bending under heavy rain, the red clay tile roof edge pouring rain in strings of silver "
            "drops, a wet red earth path, carved wooden pillars framing the view, a brass oil lamp "
            "glowing warm at the edge of the frame, mist hanging over green rice fields in the distance. "
            "Photorealistic, tropical monsoon atmosphere, calm and cinematic. Soft grey-green early "
            "morning light, gently and evenly lit, every detail clearly visible, calm and inviting, not "
            "dark and not gloomy. No people, no text, no logo."
        ),
    },
    "lakeside_porch": {
        "label": "Misty Lakeside Porch",
        "instruments": ["nylon guitar", "soft piano", "flute"],
        "prompt": (
            "First-person point of view from a wooden rocking chair under the roof of a lakeside cabin "
            "porch, looking straight out at a calm misty mountain lake in steady rain, rain rings "
            "spreading across the whole water surface, pine-covered shores fading into mist, a wooden "
            "jetty reaching into the lake, a wool blanket over the chair arm in the lower foreground, a "
            "lantern glowing warm on the porch rail at the edge of the frame, rain streaming off the "
            "porch roof edge in silver lines. Photorealistic, quiet lakeside atmosphere, calm and "
            "cinematic. Soft blue-grey twilight, gently and evenly lit, every detail clearly visible, "
            "calm and inviting, not dark and not gloomy. No people, no text, no logo."
        ),
    },
    "bamboo_teahouse": {
        "label": "Bamboo Grove Tea House",
        "instruments": ["bamboo flute", "harp", "kalimba", "soft piano"],
        "prompt": (
            "First-person point of view from a tatami seat at a low wooden table in a Japanese tea house, "
            "looking straight out through an open sliding door at a bamboo grove and a moss garden in "
            "steady rain, a steaming iron teapot and a small clay cup on the table in the lower "
            "foreground, a stone water basin overflowing with rain, tall green bamboo dripping, a paper "
            "lantern glowing warm amber at the edge of the frame, wooden eaves dripping in a line of "
            "silver drops. Photorealistic, tranquil tea house atmosphere, calm and cinematic. Soft blue "
            "twilight, gently and evenly lit, every detail clearly visible, calm and inviting, not dark "
            "and not gloomy. No people, no text, no logo."
        ),
    },
}

# One cinematic sentence for every scene, added in code so the twelve prompts stay about their place. Qwen draws every
# word, so it is all positive wording: a wide lens, depth in layers, natural film colour, fine detail.
CINEMATIC = ("Cinematic wide-angle photograph with a natural film look, vast layered depth with soft atmospheric haze "
             "in the distance, rich but natural colour, crisp fine detail. ")
for _k, _v in SCENES.items():
    assert "No people, no text, no logo." in _v["prompt"], _k
    _v["prompt"] = _v["prompt"].replace("No people, no text, no logo.", CINEMATIC + "No people, no text, no logo.")

# The rain is drawn by code (relaxation/rainfx.py) over the picture, so the picture shows a WET scene with clear air: Wan keeps
# the streaks of its start picture where they are, so streaks in the picture could never be made to fall (docs/RUN_LOG.md, 2026-11-19).
# Every wording about rain in the air is swapped for water on the things (a pond, leaves, glass, stone) in code; a test checks that no
# scene still asks for falling rain.
WET = ("Just after heavy rain: every surface soaked and glistening, shining puddles, soft drifting mist, "
       "the air between the camera and the scenery clear and still. ")
_WET_SWAPS: dict[str, list[tuple[str, str]]] = {
    "night_city": [("in heavy rain, the door frame", "after heavy rain, the door frame"),
                   ("with rain hammering its surface into silver rings", "its dark surface glistening"),
                   ("with rain streaming off every branch", "with water dripping from every branch"),
                   ("rain falling in long silver threads through the dark canopy, deep mist", "deep mist")],
    "mountain_forest": [("forest in heavy rain", "forest just after heavy rain"), ("rain running in sheets down the cold glass", "beads of water on the cold glass"),
                        ("rain streaming off the roof overhang just above the glass", "water dripping from the roof overhang just above the glass")],
    "ocean": [("in tropical rain", "just after tropical rain"), ("with rain pocking its surface", "with a glistening surface"),
              ("in the warm rain wind", "in the warm wet wind")],
    "countryside": [("in rain and low cloud", "in low cloud after rain"),
                    ("rain running in rivulets down the aged wooden shutters and the window glass", "water beaded on the aged wooden shutters and the window glass"),
                    ("with rain dripping off every needle", "with water dripping off every needle")],
    "forest": [("covered in rain streaks", "covered in beads of water"), ("rain pouring off every leaf in curtains of water", "water dripping off every leaf"),
               ("in the warm rain", "in the warm wet air")],
    "himalayan_ridge": [("half hidden in rain clouds, rain running down the window glass", "half hidden in low rain clouds, the window glass beaded with water"),
                        ("rain falling in fine silver lines across the whole view", "wet and silver in the pre-dawn mist")],
    "monastery_window": [("in the rain", "after the rain"), ("rain streaming off the carved wooden eaves", "water dripping off the carved wooden eaves"),
                         ("rain falling in long thin lines", "mist hanging over the valley")],
    "courtyard": [("in steady rain", "after steady rain"), ("with rain rings spreading across it", "with a glistening surface"),
                  ("with rain pouring off the edge in a line of silver drops", "with water dripping off the edge in a line of silver drops")],
    "old_town_lane": [("in steady night rain", "after steady night rain"),
                      ("rain falling in long silver lines through the lamplight, small puddles with rain rings", "small shining puddles")],
    "kerala_veranda": [("bending under heavy rain", "heavy with rain water"), ("pouring rain in strings of silver drops", "dripping water in strings of silver drops")],
    "lakeside_porch": [("in steady rain", "after steady rain"), ("rain rings spreading across the whole water surface", "a glassy water surface"),
                       ("rain streaming off the porch roof edge in silver lines", "drops of water hanging along the porch roof edge")],
    "bamboo_teahouse": [("in steady rain", "after steady rain"), ("overflowing with rain", "overflowing with water")],
}
for _k, _v in SCENES.items():
    for _a, _b in _WET_SWAPS[_k]:
        assert _a in _v["prompt"], (_k, _a)
        _v["prompt"] = _v["prompt"].replace(_a, _b, 1)
    _v["prompt"] = WET + _v["prompt"]
# The thumbnail shows the FEELING of playing the music, not the place alone (owner, 2026-11-19): a happy young woman or man, cozy in a blanket
# with a warm mug and headphones, watching the rain from a window that shows the video's own theme. The person sits on the right so the words
# (laid on by code, on the left) never cover the face. The man/woman alternates by seed (`settings.thumb_person`).
THUMB_VIEWS = {
    "night_city": "a moss garden with stone lanterns and a koi pond",
    "mountain_forest": "a spruce and birch forest",
    "ocean": "a lush tropical garden with a lotus pond and palms",
    "countryside": "a steep pine-covered mountain face in low cloud",
    "forest": "an ancient rainforest canopy with hanging moss",
    "himalayan_ridge": "a pine ridge with snow peaks in rain clouds",
    "monastery_window": "terraced rooftops and white stupas in the mist",
    "courtyard": "a quiet stone courtyard with a lotus pond",
    "old_town_lane": "a narrow cobblestone lane with glowing lanterns",
    "kerala_veranda": "coconut palms and banana plants",
    "lakeside_porch": "a misty mountain lake",
    "bamboo_teahouse": "a bamboo grove and a moss garden",
}
THUMB_PROMPT = ("Cozy lo-fi atmosphere. A happy young {who} with a warm gentle smile sits by a large rain-streaked window, wrapped in a soft knit blanket, "
                "holding a steaming mug in both hands, headphones resting around the neck, relaxed and content, looking out at the rain. "
                "Seen in a three-quarter view from inside the room, the person on the right side of the frame, the window on the left and in the centre showing {view} in falling rain, "
                "raindrops running down the glass, warm golden lamp light inside against the cool blue rainy dusk outside, soft glowing bokeh lights, a small plant and a few books on the sill. "
                "Photorealistic, cinematic, shallow depth of field, rich warm colour, uplifting and peaceful mood. No text, no logo.")
THUMB_SIZE = "1280x720"


def thumb_person(seed: int) -> str:
    return "woman" if int(seed or 0) % 2 else "man"


def thumb_prompt(scene: str, who: str) -> str:
    return THUMB_PROMPT.format(who=who if who in ("woman", "man") else "woman", view=THUMB_VIEWS.get(scene) or THUMB_VIEWS[DEFAULT_SCENE])


YOUTUBE_SLOT = "rain"           # which YouTube connection (youtube/slots.py) this pipeline posts to
RAIN_ENGINE = "code"           # "code": rain drawn over the picture (relaxation/rainfx.py, default); "wan": the old Wan 2.2 image-to-video rain clip
OUT_4K = (3840, 2160)          # the video of a code-rain session: the effects are drawn at this size; YouTube then offers every quality up to 2160p
RAIN_GUIDANCE = 8.0            # (Wan engine) guidance for the rain clip (high and low noise experts)
RAIN_GUIDANCE_RETRY = 8.0       # (Wan engine) the one retry (another seed) when the first clip barely moves; guidance 10 gave paint-splatter streaks
SEAM_S = 0.5                    # (Wan engine) video.py cross-fades the end of the clip into its start for this long, so the loop has no brightness step

# Image LoRAs for the scene picture (names from GET /v1/images/loras on the gateway). Empty = none: only the detail fixer
# the gateway applies to every picture. A session may carry `image_loras` (a list of {name, strength}); trigger words are added to the prompt.
IMAGE_LORAS: list[dict] = []
LORA_TRIGGERS = {"purelens-realism": "p3r4l4ns"}
DEFAULT_SCENE = "night_city"

# ── Wan rain motion prompt ────────────────────────────────────────────────────
# Applied to every scene. Describes only what MOVES: rain + light.
# No style words, no composition (the image already shows those).
RAIN_MOTION_HEAD = (
    "Fine, thin rain falls fast and straight down in many long slender translucent streaks, "
    "the natural speed of real rain. Small bright splashes and rings appear where the drops land "
    "on water, wet ground and leaves, and the leaves tremble lightly under the drops. "
)
RAIN_MOTION_TAIL = "The overall brightness never changes. Continuous natural motion, no scene cut."


def rain_motion(scene: str = "") -> str:
    """The motion prompt for a theme: only the rain moves. A theme with a real flame (`flame`) also lets that flame flicker very softly."""
    if (SCENES.get(scene) or {}).get("flame"):
        return (RAIN_MOTION_HEAD + "The lamp flame flickers very softly in place and its small glow barely changes. "
                "Everything else stays perfectly still: the room, the trees, the other lights and the camera. " + RAIN_MOTION_TAIL)
    return (RAIN_MOTION_HEAD + "Everything else stays perfectly still: the room, the lamps, the trees, the light and the camera. "
            + RAIN_MOTION_TAIL)


RAIN_MOTION = rain_motion()          # the default (no flame)

RAIN_NEGATIVE = (
    "slime, goo, thick dripping liquid, blobs, globs, sticky strands, melting, wobbling water, "
    "slow motion, floating drops, huge drops, darkening, overall brightness change, fade, flashing light, "
    "camera shake, camera movement, scene cut, jump cut, people, text, watermark, logo, morphing, "
    "blurry, pixelated, grainy"
)

# ── audio ─────────────────────────────────────────────────────────────────────
RAIN_ASSET = "rain.mp3"          # expected in relaxation/assets/; fallback = pink noise
RAIN_LUFS = -31.0                # rain BACKGROUND: felt, not noticed (11 LU under the music)
MUSIC_LUFS = -20.0               # ambient music FOREGROUND (the whole mix is then normalised to FINAL_LUFS)
FINAL_LUFS = -14.0               # YouTube standard target for the final file

# Music: one YuE2 caption is built for every session (relaxation/variety.py picks the instrument, mood
# and tempo so no two videos in a row sound alike). YuE2 reads six to twelve comma-separated tags,
# language first; "no percussion" keeps drums out (caption-only control, no API flag exists) and
# "instrumental, no vocals" says it twice. Empty [verse]/[bridge] section tags make an instrumental
# passage; [Instrumental] is NOT a valid tag and gets sung as lyric text (see story3/music.py).
MUSIC_MOODS = ["peaceful", "serene", "meditative", "dreamy", "gentle", "warm", "ethereal", "pastoral"]
MUSIC_SECONDARY = ["warm pad", "soft strings", "low drone", "ambient pad"]
MUSIC_BPM = (64, 72)                # the first 54-62 felt slow once the takes were instrumental-only (owner heard 68 as right, 2026-11-19)
MUSIC_AVOID = ("cello",)           # heavy bass does not suit relaxing music (owner); a session that still names one gets another instrument
MUSIC_TAKES = 4                     # different tracks (seeds) chained for a long video, so one piece does not come round every two minutes
MUSIC_XFADE_S = 8.0                 # cross-fade between takes and at the loop seam
MUSIC_TRIM_S = 3.0                  # cut from the start of each take before joining
MUSIC_TRIM_END_S = 12.0             # and this much from its end: a take can end in a few seconds of wordless humming before it stops (heard on a guitar take)


def take_count(total_s: float) -> int:
    """Takes to make: one more for about every three minutes of video, up to MUSIC_TAKES (a 5 minute test makes 2)."""
    import math
    return max(1, min(MUSIC_TAKES, math.ceil(total_s / 180)))


def music_caption(instrument: str, secondary: str, mood: str, bpm: int) -> str:
    return (f"English, ambient, sleep music, tranquil, {mood}, {int(bpm)} BPM, {instrument}, {secondary}, "
            "instrumental, no vocals, no percussion, soft dynamics")       # melody words (gentle flowing melody, soft arpeggios) were tried 2026-11-19; the owner preferred this original wording


def music_recipe(scene: str, plan: dict | None = None) -> dict:
    """The music recipe dict (with a 'caption' key): the session's own plan when it has one, else the scene's first instrument."""
    if plan and plan.get("caption"):
        return {"caption": plan["caption"]}
    ins = (SCENES.get(scene) or SCENES[DEFAULT_SCENE])["instruments"][0]
    return {"caption": music_caption(ins, MUSIC_SECONDARY[0], MUSIC_MOODS[0], 58)}


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
    import uuid
    raw = f"rl-{time.time()}-{uuid.uuid4().hex}"
    return "rl-" + hashlib.sha1(raw.encode()).hexdigest()[:8]
