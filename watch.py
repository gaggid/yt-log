"""Auto-deploy supervisor for the Windows machine.

Runs the app, polls origin every POLL_S seconds; when new commits land it waits for running jobs to
finish, `git pull --ff-only`, reinstalls requirements if they changed, and restarts the app.
Restarts the app if it crashes. Stdlib only. Start with start.bat (or a scheduled task at logon).
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
BRANCH = os.environ.get("DEPLOY_BRANCH", "master")
POLL_S = int(os.environ.get("DEPLOY_POLL_S", "60"))
PORT = int(os.environ.get("PORT", "8905"))
LOGS = ROOT / "logs"
LOGS.mkdir(exist_ok=True)


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOGS / "deploy.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def git(*args: str) -> str:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def start_app() -> subprocess.Popen:
    out = open(LOGS / "server.log", "a", encoding="utf-8")
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    log("starting app")
    return subprocess.Popen([sys.executable, "main.py"], cwd=ROOT, stdout=out,
                            stderr=subprocess.STDOUT, env=env)


def busy() -> bool:
    """True while any job is queued/running (don't restart under it). Unreachable app = not busy."""
    try:
        import auth
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/internal/busy",
                                     headers={"X-Internal": auth.internal_token()})
        with urllib.request.urlopen(req, timeout=5) as r:
            return bool(json.load(r).get("busy"))
    except Exception:
        return False


def stop_app(p: subprocess.Popen) -> None:
    if p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            p.kill()


def main() -> None:
    proc = start_app()
    while True:
        time.sleep(POLL_S)
        if proc.poll() is not None:
            log(f"app exited with code {proc.returncode}; restarting")
            proc = start_app()
            continue
        try:
            git("fetch", "origin", BRANCH)
            local, remote = git("rev-parse", "HEAD"), git("rev-parse", f"origin/{BRANCH}")
            if local == remote or busy():
                continue
            log(f"deploying {local[:7]} -> {remote[:7]}")
            reqs_changed = "requirements.txt" in git("diff", "--name-only", "HEAD", f"origin/{BRANCH}").splitlines()
            git("pull", "--ff-only", "origin", BRANCH)
            if reqs_changed:
                log("requirements changed: pip install")
                subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
                               cwd=ROOT, check=True)
            stop_app(proc)
            proc = start_app()
            log(f"deployed {git('log', '-1', '--format=%h %s')}")
        except Exception as e:                       # network down, dirty tree, merge conflict: keep running
            log(f"deploy check failed: {e}")


if __name__ == "__main__":
    main()
