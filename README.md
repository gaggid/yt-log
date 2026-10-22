# yt-log: Hindi podcast video generator

Topic -> web research -> Hindi script -> voice (kokoro) -> per-shot illustrations (2-5 s each) -> 1080p video
with camera moves (zoompan) and crossfades (xfade), all through the local OpenAI-style model gateway.

## Setup (Windows)
1. `pip install -r requirements.txt`; FFmpeg on PATH (or `FFMPEG_PATH`).
2. Copy `.env.example` to `.env`, set `TRIPFICK_API_KEY` (gateway on `127.0.0.1:8810`).
3. `start.bat` -> UI at http://127.0.0.1:8905

## Auto-deploy
`start.bat` runs `watch.py`: every 60 s it fetches `origin/master`; on new commits it waits until no job
is running, pulls (fast-forward only), reinstalls requirements if changed, and restarts the app.
Logs: `logs/deploy.log`, `logs/server.log`. Start at logon:

    schtasks /Create /TN YtLogServer /SC ONLOGON /TR "D:\yt-log\start.bat" /RL LIMITED

## Cloudflare tunnel
Point a public hostname at `http://127.0.0.1:8905`. The UI can spend GPU time, so put Cloudflare Access in front.
