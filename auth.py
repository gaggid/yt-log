"""Single-user login (cookie session) for the whole app. Install with auth.install(app)."""
import hashlib
import hmac
import time
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

import config

COOKIE = "yt_session"
TTL_S = 7 * 24 * 3600
OPEN_PATHS = {"/login", "/logout", "/favicon.ico"}
_fails: dict[str, list[float]] = {}          # ip -> recent failure timestamps


def _key() -> bytes:
    # Changing the password invalidates every session.
    return hashlib.sha256(f"yt-log|{config.APP_USER}|{config.APP_PASSWORD}".encode()).digest()


def _sign(msg: str) -> str:
    return hmac.new(_key(), msg.encode(), hashlib.sha256).hexdigest()


def make_token() -> str:
    exp = str(int(time.time()) + TTL_S)
    return f"{exp}.{_sign(exp)}"


def valid_token(tok: str | None) -> bool:
    if not tok or "." not in tok:
        return False
    exp, sig = tok.split(".", 1)
    return exp.isdigit() and int(exp) > time.time() and hmac.compare_digest(sig, _sign(exp))


def internal_token() -> str:
    """Header value for local tooling (watch.py) to query /internal/busy without a browser session."""
    return _sign("internal")


def _ip(request: Request) -> str:
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")


def _locked(ip: str) -> bool:
    now = time.time()
    _fails[ip] = [t for t in _fails.get(ip, []) if now - t < 300]
    return len(_fails[ip]) >= 5


def _is_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


def install(app: FastAPI) -> None:
    page = Path(__file__).with_name("static") / "login.html"

    @app.middleware("http")
    async def gate(request: Request, call_next):
        path = request.url.path
        if path in OPEN_PATHS:
            return await call_next(request)
        if path == "/internal/busy":
            ok = hmac.compare_digest(request.headers.get("x-internal", ""), internal_token())
            return await call_next(request) if ok else JSONResponse({"detail": "unauthorized"}, status_code=401)
        if valid_token(request.cookies.get(COOKIE)):
            return await call_next(request)
        if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
            return RedirectResponse("/login", status_code=302)
        return JSONResponse({"detail": "login required"}, status_code=401)

    @app.get("/login")
    async def login_page(request: Request):
        if valid_token(request.cookies.get(COOKIE)):
            return RedirectResponse("/", status_code=302)
        return FileResponse(page)

    @app.post("/login")
    async def login(request: Request, username: str = Form(""), password: str = Form("")):
        ip = _ip(request)
        if _locked(ip):
            return JSONResponse({"detail": "Too many attempts. Try again in a few minutes."}, status_code=429)
        ok = (hmac.compare_digest(username.encode(), config.APP_USER.encode())
              & hmac.compare_digest(password.encode(), config.APP_PASSWORD.encode()))
        if not ok:
            _fails.setdefault(ip, []).append(time.time())
            return JSONResponse({"detail": "Wrong username or password."}, status_code=401)
        resp = JSONResponse({"ok": True})
        resp.set_cookie(COOKIE, make_token(), max_age=TTL_S, httponly=True, samesite="lax",
                        secure=_is_https(request), path="/")
        return resp

    @app.post("/logout")
    async def logout():
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE, path="/")
        return resp
