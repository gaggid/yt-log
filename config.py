import os

API_KEY = os.environ.get("TRIPFICK_API_KEY", "sk-local-je_Wq0LVo8f-VDGwaFGRY5AUwSgNAjjCM1SUhQIgC_w")
FFMPEG = os.environ.get("FFMPEG_PATH",
    r"C:\tripifk\remotion-studio\node_modules\@remotion\compositor-win32-x64-msvc\ffmpeg.exe")
BASE_URL = "https://llm.tripfick.com/v1"

CHAT_MODEL = "gemma4-12b-qat-uncensored-hauhaucs-balanced"
TTS_MODEL = "kokoro"
IMAGE_MODEL = "z-image-turbo"

DEFAULT_VOICE = "hf_alpha"       # Hindi female
DEFAULT_STYLE = "cinematic-poster"
DEFAULT_SEGMENTS = 8
MAX_CONCURRENCY = 1              # server limit
