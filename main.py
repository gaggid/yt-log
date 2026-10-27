"""Source-to-Story app entry point. The older news/video pipeline lives in legacy/ and is no longer served."""
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

import auth
import config
from story import db
from story.api import router as story_router
from story2.api import router as plans_router
from story3.api import router as media_router
from story.pipeline import manager

STATIC = Path(__file__).with_name("static")
_STARTED_AT = datetime.now()


def _git_info() -> dict:
    try:
        r = subprocess.run(["git", "log", "-1", "--format=%h|%s"], capture_output=True, text=True,
                           encoding="utf-8", cwd=Path(__file__).parent)
        parts = r.stdout.strip().split("|", 1)
        return {"commit": parts[0], "subject": parts[1] if len(parts) > 1 else ""}
    except Exception:
        return {"commit": "unknown", "subject": ""}


_GIT = _git_info()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    resumed = manager.resume_interrupted()      # unfinished sources continue after a restart / auto-deploy
    if resumed:
        print(f"Resuming interrupted processing: {', '.join(resumed)}", flush=True)
    yield


app = FastAPI(title="Source-to-Story", lifespan=lifespan)
auth.install(app)
app.include_router(story_router)
app.include_router(plans_router)
app.include_router(media_router)


NO_STORE = {"Cache-Control": "no-store"}


@app.get("/")
async def root():
    """The page names plan.js with its file time, so a browser or a proxy in front (the tunnel) can never keep serving an older script after an update."""
    html = (STATIC / "index.html").read_text(encoding="utf-8").replace('src="/plan.js"', f'src="/plan.js?v={int((STATIC / "plan.js").stat().st_mtime)}"')
    return HTMLResponse(html, headers=NO_STORE)


@app.get("/plan.js")
async def plan_js():
    return FileResponse(STATIC / "plan.js", media_type="application/javascript", headers=NO_STORE)


@app.get("/style-samples/{name}")
async def style_sample(name: str):
    name = name.removesuffix(".jpg")
    f = STATIC / "style_samples" / (name + ".jpg")
    if name not in ("filmic", "gta", "noir", "concept") or not f.is_file():
        raise HTTPException(404, "no such sample")
    return FileResponse(f, headers={"Cache-Control": "max-age=86400"})


def _commits_behind() -> int:
    """How many commits on origin are not deployed here yet (watch.py fetches every minute; this only reads what it fetched). 0 when unknown."""
    try:
        r = subprocess.run(["git", "rev-list", "--count", "HEAD..origin/master"], capture_output=True, text=True, cwd=Path(__file__).parent, timeout=5)
        return int(r.stdout.strip() or 0)
    except Exception:
        return 0


@app.get("/health")
async def health():
    from story2 import jobs
    return {"started_at": _STARTED_AT.isoformat(), "uptime_s": (datetime.now() - _STARTED_AT).total_seconds(),
            "commit": _GIT["commit"], "subject": _GIT["subject"], "behind": _commits_behind(), "busy": manager.busy() or jobs.busy()}


@app.get("/internal/busy")
async def internal_busy():
    """For watch.py (auto-deploy): true while any source is being processed."""
    from story2 import jobs
    return {"busy": manager.busy() or jobs.busy()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.HOST, port=config.PORT)
