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
IMAGE_MODEL = "z-image-turbo"

TTS_MODEL        = os.environ.get("TTS_MODEL", "hindi-podcast")
TTS_SPEED        = float(os.environ.get("TTS_SPEED", "1.0"))
TTS_CFG_WEIGHT   = float(os.environ.get("TTS_CFG_WEIGHT", "0.3"))   # lower = cleaner, less echo
TTS_EXAGGERATION = float(os.environ.get("TTS_EXAGGERATION", "0.65")) # expressiveness
DEFAULT_VOICE = os.environ.get("DEFAULT_VOICE", "anchor_m")
DEFAULT_STYLE = "graphic-novel"  # illustrated look hides AI face/anatomy errors
DEFAULT_SEGMENTS = 8
DEFAULT_CAMERA = "auto"
MAX_CONCURRENCY = 1              # server limit

# Shot timing: every image stays on screen SHOT_MIN..SHOT_MAX seconds.
SHOT_MIN = 2.0
SHOT_MAX = 5.0
SHOT_TARGET = 5.0
XFADE = 0.35                     # transition overlap, seconds
VIDEO_W, VIDEO_H, VIDEO_FPS = 2560, 1440, 30
