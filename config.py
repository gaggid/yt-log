import os
import shutil
from pathlib import Path


def _load_env_file():
    """Read KEY=VALUE lines from .env next to this file (gitignored; real env vars win)."""
    p = Path(__file__).with_name(".env")
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env_file()


def _ensure_password() -> str:
    """No APP_PASSWORD set: generate one and store it in .env so the login never runs open."""
    pw = os.environ.get("APP_PASSWORD")
    if pw:
        return pw
    import secrets
    pw = secrets.token_urlsafe(12)
    with open(Path(__file__).with_name(".env"), "a", encoding="utf-8") as f:
        f.write(f"\nAPP_PASSWORD={pw}\n")
    os.environ["APP_PASSWORD"] = pw
    return pw


APP_USER = os.environ.get("APP_USER", "admin")
APP_PASSWORD = _ensure_password()

API_KEY = os.environ.get("TRIPFICK_API_KEY", "")
# Local gateway by default: no Cloudflare 100s request limit on slow model loads.
BASE_URL = os.environ.get("TRIPFICK_BASE_URL", "http://127.0.0.1:8810/v1")
FFMPEG = (os.environ.get("FFMPEG_PATH") or shutil.which("ffmpeg")
          or r"C:\Ffmpeg\bin\ffmpeg.exe")

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8905"))

CHAT_MODEL = "gemma4-12b-qat-uncensored-hauhaucs-balanced"
TTS_MODEL = "kokoro"
IMAGE_MODEL = "z-image-turbo"
VISION_MODEL = "qwen3.5-9b"       # multimodal; reads on-image text for QA

DEFAULT_VOICE = "hm_omega"       # Hindi male
DEFAULT_STYLE = "graphic-novel"  # illustrated look hides AI face/anatomy errors
DEFAULT_SEGMENTS = 8
DEFAULT_CAMERA = "auto"
MAX_CONCURRENCY = 1              # server limit

# Shot timing: every image stays on screen SHOT_MIN..SHOT_MAX seconds.
SHOT_MIN = 2.0
SHOT_MAX = 5.0
SHOT_TARGET = 3.5
XFADE = 0.35                     # transition overlap, seconds
VIDEO_W, VIDEO_H, VIDEO_FPS = 1920, 1080, 30
