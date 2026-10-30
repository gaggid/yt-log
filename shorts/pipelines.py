"""The pipelines and the video requests they send. A pipeline is a way of getting one clip per shot out of Wan:

* quick     - Wan 2.2 5B (`wan-2.2-ti2v-5b`). Each shot starts from a still picture (Qwen Image, or the user's), looked at first, unless image mode is "wan" (text only; a shot marked "continues" then starts from the last frame of the one before).
* keyframe  - a still per shot first (the user's picture, or the image model's (Qwen Image) from the shot's `still` prompt; with image mode "wan", a 5-frame text-to-video request whose last frame is kept), looked at by a person, then each still is
              animated with `wan-2.2-i2v-a14b` at full quality. Every shot starts from its own picture, so nothing drifts.
* remix     - `wan-2.2-animate-2`: a YouTube video's motion, performed by the character in the user's picture (shorts/remix.py).

"Always final": the speed LoRA is off on the 14B models. The request defaults come from the docs (https://llm.tripfick.com/docs) and the timings from shorts/probe.py when it has been run."""
import hashlib
import json

import config

from . import models, store

PIPELINES = {
    "quick": {"label": "Quick (Wan 5B)", "models": [models.TI2V],
              "about": "One model for text or pictures. The fastest way to see the idea (about 20 minutes)."},
    "keyframe": {"label": "Keyframes, then animate (Wan 14B)", "models": [models.T2V, models.I2V],
                 "about": "A picture for every shot first, which you check, then each is animated at full quality. The best look (about an hour)."},
    "remix": {"label": "Remix a YouTube video (Wan Animate)", "models": [models.ANIMATE],
              "about": "Your character performs the motion of a video you link. The video's own background is not kept."},
}
NEGATIVE = "blurry, low quality, static, deformed, disfigured, extra fingers, poorly drawn hands, jpeg artifacts, text, watermark, logo, subtitles, signature"
KEYFRAME_FRAMES = 5
DEFAULT_STEPS = {models.TI2V: 20, models.T2V: 20, models.I2V: 10, models.ANIMATE: 10, models.TALK: 6}
# seconds of work per generated frame at 480x832, from the docs' timings (RTX 4060 Ti 16 GB); shorts/probe.py writes measured values over these
SEC_PER_FRAME = {models.TI2V: 1.75, models.T2V: 0.84 * 20, models.I2V: 0.59 * 10, models.ANIMATE: 66 / 16, models.TALK: 6.0}      # TALK: a guess until the first measured run (G2)
STILL_S = 60                              # one picture from the image model, with the swap of models
OVERHEAD_S = 25                           # per request: queueing, loading, decoding, the download


def pipeline(short: dict) -> dict:
    p = PIPELINES.get(short["pipeline"])
    if not p:
        raise store.ShortError(f"unknown pipeline '{short['pipeline']}'")
    return p


# ── how a shot starts ────────────────────────────────────────────────────────

def start_source(short: dict, shot: dict) -> str:
    """`upload` (the user gave a picture for this shot), `anchor` (the user's picture of the main character, for shots that show them), `prev` (the last frame of the shot before, quick
    pipeline only), `qwen` (the image model draws the start picture) or `text` (Wan decides)."""
    imgs = short["images"]
    if store.image_path(short, imgs["shots"].get(shot["id"], "")):
        return "upload"
    if short["settings"]["image_mode"] != "wan" and shot.get("character") and store.image_path(short, imgs.get("anchor", "")):
        return "anchor"
    if keyframes_on(short):
        return "qwen" if short["settings"]["image_mode"] != "wan" else "text"
    if short["pipeline"] == "quick" and short["settings"].get("chain") and shot.get("continues") and short["shots"] and short["shots"][0]["id"] != shot["id"]:
        return "prev"
    return "text"


def keyframes_on(short: dict) -> bool:
    """Whether every shot gets a start picture first, looked at by a person before the long wait: always in the keyframe pipeline, and in the quick one unless Wan is asked to decide."""
    return short["pipeline"] == "keyframe" or (short["pipeline"] == "quick" and short["settings"]["image_mode"] != "wan")


def compose(short: dict, shot: dict, with_picture: bool = False) -> str:
    """The Wan prompt: the shot, then the character and the place the plan fixed (words are not left to the model to repeat), the camera and the look. A shot that starts from a picture
    does not describe what the picture already shows."""
    plan = short["plan"]
    parts = []
    if shot.get("character") and plan.get("character") and not with_picture:
        parts.append(plan["character"].rstrip(". ") + ".")
    parts.append(shot["prompt"].strip())
    if not with_picture:
        setting = shot.get("setting") or plan.get("place")
        if setting:
            parts.append(f"Setting: {setting.rstrip('. ')}.")
    if shot.get("camera"):
        parts.append(f"Camera: {shot['camera'].rstrip('. ')}.")
    if plan.get("look"):
        parts.append(plan["look"].rstrip(". ") + ".")
    return " ".join(parts)[:3900]


def seed_for(short: dict, shot: dict, attempt: int) -> int:
    idx = next((i for i, s in enumerate(short["shots"]) if s["id"] == shot["id"]), 0)
    return (int(short["settings"].get("seed", 7)) + 17 * idx + 101 * (attempt - 1)) % (2 ** 32)


def steps_of(short: dict, model: str) -> int:
    return int(short["settings"].get("steps") or DEFAULT_STEPS[model])


# ── requests ─────────────────────────────────────────────────────────────────

def quick_request(short: dict, shot: dict, attempt: int, image: str | None = None) -> dict:
    """Wan 5B, text or picture. `image` is a data URL."""
    body = {"model": models.TI2V, "prompt": compose(short, shot, bool(image)), "negative_prompt": NEGATIVE, "size": short["settings"].get("size") or models.SIZE_PORTRAIT,
            "num_frames": models.gen_frames(shot["seconds"], models.TI2V), "fps": models.MODELS[models.TI2V]["fps"], "steps": steps_of(short, models.TI2V),
            "seed": seed_for(short, shot, attempt), "response_format": "mp4"}
    if image:
        body["image"] = image
    return body


def keyframe_request(short: dict, shot: dict, attempt: int) -> dict:
    """A still from Wan: the 14B text-to-video model asked for the fewest frames it takes, full quality; the last frame is the keyframe."""
    return {"model": models.T2V, "prompt": compose(short, shot), "negative_prompt": NEGATIVE, "size": models.SIZE_PORTRAIT, "num_frames": KEYFRAME_FRAMES, "fps": models.MODELS[models.T2V]["fps"],
            "speed_lora": False, "steps": DEFAULT_STEPS[models.T2V], "seed": seed_for(short, shot, attempt), "response_format": "mp4"}


def animate_request(short: dict, shot: dict, attempt: int, image: str) -> dict:
    """Picture to video at full quality (speed LoRA off). The prompt describes the motion; the picture already shows the subject."""
    return {"model": models.I2V, "prompt": compose(short, shot, True), "negative_prompt": NEGATIVE, "image": image, "size": models.SIZE_PORTRAIT,
            "num_frames": models.gen_frames(shot["seconds"], models.I2V), "fps": models.MODELS[models.I2V]["fps"], "speed_lora": False, "steps": steps_of(short, models.I2V),
            "seed": seed_for(short, shot, attempt), "response_format": "mp4"}


def avatar_request(short: dict, shot: dict, attempt: int, image: str, audio: str) -> dict:
    """A talking avatar shot: the start picture speaks the shot's slice of the voice (InfiniteTalk). `audio` is a wav data URL. The speed LoRA is the gateway's default for this model: the
    4-step version is what makes it practical, and unlike Wan S2V it keeps the lip movement."""
    return {"model": models.TALK, "prompt": compose(short, shot, True), "negative_prompt": NEGATIVE, "image": image, "audio": audio, "size": models.SIZE_PORTRAIT,
            "duration": round(shot["seconds"] + 0.2, 2), "fps": models.MODELS[models.TALK]["fps"], "steps": steps_of(short, models.TALK), "seed": seed_for(short, shot, attempt), "response_format": "mp4"}


def req_hash(body: dict) -> str:
    """What a clip was made from, without the seed (a new seed is the same input made again) and with the picture reduced to a fingerprint."""
    b = {k: v for k, v in body.items() if k not in ("seed",)}
    for k in ("image", "end_image", "driving_video", "audio"):
        if k in b:
            b[k] = hashlib.sha1(str(b[k]).encode()).hexdigest()[:12]
    return store.input_hash(json.dumps(b, sort_keys=True, ensure_ascii=False))


# ── time ─────────────────────────────────────────────────────────────────────

def _measured() -> dict:
    try:
        return json.loads((config.DATA_DIR / "shorts_probe" / "timings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def request_seconds(model: str, frames: int, short: dict | None = None) -> float:
    """Estimated gateway time of one request: seconds per frame (measured by the probe, else the docs) scaled for steps and picture size."""
    spf = float(_measured().get(model, {}).get("s_per_frame") or SEC_PER_FRAME[model])
    if short is not None:
        spf *= steps_of(short, model) / DEFAULT_STEPS[model] if model in (models.TI2V, models.I2V) else 1
        if model == models.TI2V and (short["settings"].get("size") == models.SIZE_SHARP):
            spf *= 2.9                                         # 1280x704 took about 10 minutes against 3.5 for 832x480
    return OVERHEAD_S + frames * spf


def estimate_s(short: dict) -> int:
    """Gateway time to make every clip of a short, from the shots as planned. For remix see shorts/remix.py."""
    if short["pipeline"] == "remix":
        from . import remix
        return remix.estimate_s(short)
    total = 0.0
    for sh in short["shots"]:
        secs = sh.get("seconds") or models.MAX_SHOT_S
        if start_source(short, sh) == "qwen":
            total += STILL_S
        if sh.get("avatar"):
            total += request_seconds(models.TALK, models.gen_frames(secs + 0.2, models.TALK), short)
        elif short["pipeline"] == "quick":
            total += request_seconds(models.TI2V, models.gen_frames(secs, models.TI2V), short)
        else:
            if start_source(short, sh) == "text":
                total += request_seconds(models.T2V, KEYFRAME_FRAMES, short)
            total += request_seconds(models.I2V, models.gen_frames(secs, models.I2V), short)
    return int(total)
