"""What each Wan 2.2 model is, and the arithmetic that follows from it (docs: https://llm.tripfick.com/docs, Wan 2.2 section). One place, so the planner, the checks and
the request builders agree on frames, sizes and speeds."""
import math

TARGET_S = 30.0                       # the contract: a short is this long
TOLERANCE_S = 0.5
OUT_FPS = 30
OUT_SIZE = (1080, 1920)
MAX_SHOT_S = 3.0                      # owner rule: no shot is on screen longer than this
HOOK_MAX_S = 2.0                      # the first shot is shorter still
MIN_SHOT_S = 1.2
SIZE_PORTRAIT = "480x832"             # every pipeline asks for 9:16; the 5B can also do the sharper size below
SIZE_SHARP = "704x1280"

T2V, I2V, TI2V, S2V, ANIMATE = "wan-2.2-t2v-a14b", "wan-2.2-i2v-a14b", "wan-2.2-ti2v-5b", "wan-2.2-s2v-14b", "wan-2.2-animate-2"

MODELS: dict[str, dict] = {
    TI2V: {"label": "Wan 2.2 5B (text or picture)", "fps": 24, "max_frames": 241, "image": "optional", "mode": "image-to-video"},
    T2V: {"label": "Wan 2.2 text to video 14B", "fps": 16, "max_frames": 161, "image": "none", "mode": "text-to-video"},
    I2V: {"label": "Wan 2.2 picture to video 14B", "fps": 16, "max_frames": 161, "image": "required", "mode": "image-to-video"},
    S2V: {"label": "Wan 2.2 speech to video 14B", "fps": 16, "max_frames": 481, "image": "required", "mode": "speech-to-video"},
    ANIMATE: {"label": "Wan 2.2 character animation", "fps": 30, "max_frames": 481, "image": "required", "mode": "character-animation"},
}
ALIASES = {"wan": TI2V, "wan2.2": TI2V, "wan-t2v": T2V, "wan-i2v": I2V, "wan-s2v": S2V, "wan-animate": ANIMATE}


def canon(model: str) -> str:
    m = ALIASES.get(model, model)
    if m not in MODELS:
        raise ValueError(f"unknown video model '{model}'")
    return m


def need_frames(seconds: float, fps: int) -> int:
    """Frames of footage that cover `seconds` (never fewer than the 5 the models accept)."""
    return max(5, math.ceil(seconds * fps - 1e-6))


def gen_frames(seconds: float, model: str) -> int:
    """The frame count to ask for: the smallest 4n+1 that covers `seconds`. The extra frames are cut off when the short is put together."""
    cfg = MODELS[canon(model)]
    n = need_frames(seconds, cfg["fps"])
    g = 4 * math.ceil((n - 1) / 4) + 1
    if g > cfg["max_frames"]:
        raise ValueError(f"{seconds:.1f}s needs {g} frames; {canon(model)} stops at {cfg['max_frames']}")
    return g


def out_frames(seconds: float) -> int:
    """Frames of the finished 30 fps short that one shot of `seconds` occupies."""
    return max(1, round(seconds * OUT_FPS))


def size_of(s: str) -> tuple[int, int]:
    w, h = s.lower().split("x")
    return int(w), int(h)
