"""Google OAuth for the channel's read-only YouTube data (scopes: youtube.readonly, yt-analytics.readonly).

The client id, secret and redirect address come from `.env` (YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REDIRECT_URI). The refresh token is kept in the database (`yt_auth`); the short-lived access token
is renewed from it when needed. Nothing here can change or upload anything on the channel."""
import os
import secrets
import time
import urllib.parse

import httpx

import auth as app_auth
import config  # noqa: F401  (loads .env into the environment)
from . import store

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
SCOPES = ("https://www.googleapis.com/auth/youtube.readonly", "https://www.googleapis.com/auth/yt-analytics.readonly")
STATE_TTL_S = 600

TRANSPORT = None                                   # tests put an httpx.MockTransport here


class YTError(Exception):
    """A YouTube or Google call failed; the message is safe to show."""


class YTAuthError(YTError):
    """The connection is missing or no longer valid: connect again."""


def http() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=30, transport=TRANSPORT)


def client_id() -> str:
    return os.environ.get("YT_CLIENT_ID", "").strip()


def client_secret() -> str:
    return os.environ.get("YT_CLIENT_SECRET", "").strip()


def redirect_uri() -> str:
    return os.environ.get("YT_REDIRECT_URI", "").strip()


def configured() -> bool:
    return bool(client_id() and client_secret() and redirect_uri())


def make_state(now: float | None = None) -> str:
    """A signed, expiring value that comes back from Google unchanged, so a callback that this app did not start is refused."""
    ts = str(int(now if now is not None else time.time()))
    nonce = secrets.token_hex(6)
    return f"{ts}.{nonce}.{app_auth._sign(f'yt-oauth|{ts}|{nonce}')}"


def check_state(state: str, now: float | None = None) -> bool:
    try:
        ts, nonce, sig = (state or "").split(".", 2)
    except ValueError:
        return False
    fresh = ts.isdigit() and 0 <= (now if now is not None else time.time()) - int(ts) <= STATE_TTL_S
    return fresh and secrets.compare_digest(sig, app_auth._sign(f"yt-oauth|{ts}|{nonce}"))


def auth_url() -> str:
    if not configured():
        raise YTError("YT_CLIENT_ID, YT_CLIENT_SECRET and YT_REDIRECT_URI are not all set in .env")
    q = {"client_id": client_id(), "redirect_uri": redirect_uri(), "response_type": "code", "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent", "state": make_state()}
    return AUTH_URL + "?" + urllib.parse.urlencode(q)


def _problem(r: httpx.Response) -> str:
    try:
        j = r.json()
        err = j.get("error")
        return (j.get("error_description") or (err.get("message") if isinstance(err, dict) else err) or r.text)[:300]
    except ValueError:
        return r.text[:300] or f"HTTP {r.status_code}"


async def exchange(code: str) -> dict:
    """Trade the code from Google's redirect for tokens and keep them."""
    async with http() as c:
        r = await c.post(TOKEN_URL, data={"code": code, "client_id": client_id(), "client_secret": client_secret(), "redirect_uri": redirect_uri(), "grant_type": "authorization_code"})
    if r.status_code != 200:
        raise YTError("Google refused the sign-in: " + _problem(r))
    j = r.json()
    if not j.get("refresh_token"):
        raise YTError("Google gave no refresh token. Remove this app at myaccount.google.com/permissions and connect again.")
    cur = store.get_auth()
    cur.update({"refresh_token": j["refresh_token"], "access_token": j["access_token"], "expires_at": time.time() + int(j.get("expires_in", 3600)), "scope": j.get("scope", ""), "connected_at": time.time(), "broken": ""})
    store.set_auth(cur)
    return cur


async def access_token() -> str:
    a = store.get_auth()
    if not a.get("refresh_token"):
        raise YTAuthError("YouTube is not connected")
    if a.get("access_token") and a.get("expires_at", 0) > time.time() + 60:
        return a["access_token"]
    async with http() as c:
        r = await c.post(TOKEN_URL, data={"refresh_token": a["refresh_token"], "client_id": client_id(), "client_secret": client_secret(), "grant_type": "refresh_token"})
    if r.status_code != 200:
        msg = _problem(r)
        if "invalid_grant" in r.text:
            a["broken"] = "The connection was withdrawn or expired. Connect again."
            store.set_auth(a)
            raise YTAuthError(a["broken"])
        raise YTError("Could not renew the YouTube connection: " + msg)
    j = r.json()
    a.update({"access_token": j["access_token"], "expires_at": time.time() + int(j.get("expires_in", 3600))})
    store.set_auth(a)
    return a["access_token"]


async def revoke() -> None:
    """Disconnect: tell Google (best effort) and forget the tokens."""
    a = store.get_auth()
    tok = a.get("refresh_token")
    store.clear_auth()
    if tok:
        try:
            async with http() as c:
                await c.post(REVOKE_URL, data={"token": tok})
        except httpx.HTTPError:
            pass
