"""Google OAuth for YouTube data and upload (scopes: youtube.readonly, yt-analytics.readonly, youtube.upload).

The client id, secret and redirect address come from `.env` (YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REDIRECT_URI). The refresh token is kept in the database (`yt_auth`); the short-lived access token
is renewed from it when needed. Existing connections made before the youtube.upload scope was added must disconnect and reconnect to gain upload access."""
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
SCOPES = (
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.upload",
)
UPLOAD_SLOT_SCOPES = (                              # an upload channel: its name (read) and the upload; no analytics
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.upload",
)
UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
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


def make_state(now: float | None = None, slot: str = "main") -> str:
    """A signed, expiring value that comes back from Google unchanged, so a callback that this app did not start is refused.
    It also carries the slot the sign-in is for (slot `main` keeps the original three-part form)."""
    ts = str(int(now if now is not None else time.time()))
    nonce = secrets.token_hex(6)
    if slot == "main":
        return f"{ts}.{nonce}.{app_auth._sign(f'yt-oauth|{ts}|{nonce}')}"
    return f"{ts}.{nonce}.{slot}.{app_auth._sign(f'yt-oauth|{ts}|{nonce}|{slot}')}"


def _parse_state(state: str) -> tuple[str, str, str, str] | None:
    parts = (state or "").split(".")
    if len(parts) == 3:
        return parts[0], parts[1], "main", parts[2]
    if len(parts) == 4:
        return parts[0], parts[1], parts[2], parts[3]
    return None


def check_state(state: str, now: float | None = None) -> bool:
    p = _parse_state(state)
    if not p:
        return False
    ts, nonce, slot, sig = p
    signed = f"yt-oauth|{ts}|{nonce}" if slot == "main" else f"yt-oauth|{ts}|{nonce}|{slot}"
    fresh = ts.isdigit() and 0 <= (now if now is not None else time.time()) - int(ts) <= STATE_TTL_S
    return fresh and secrets.compare_digest(sig, app_auth._sign(signed))


def state_slot(state: str) -> str:
    """The slot a checked state was made for."""
    p = _parse_state(state)
    return p[2] if p else "main"


def auth_url(slot: str = "main") -> str:
    if not configured():
        raise YTError("YT_CLIENT_ID, YT_CLIENT_SECRET and YT_REDIRECT_URI are not all set in .env")
    scopes = SCOPES if slot == "main" else UPLOAD_SLOT_SCOPES
    # an upload channel asks Google to show the account and channel chooser, so it is not silently the account that is already signed in
    q = {"client_id": client_id(), "redirect_uri": redirect_uri(), "response_type": "code", "scope": " ".join(scopes), "access_type": "offline",
         "prompt": "consent" if slot == "main" else "consent select_account", "state": make_state(slot=slot)}
    return AUTH_URL + "?" + urllib.parse.urlencode(q)


def _problem(r: httpx.Response) -> str:
    try:
        j = r.json()
        err = j.get("error")
        return (j.get("error_description") or (err.get("message") if isinstance(err, dict) else err) or r.text)[:300]
    except ValueError:
        return r.text[:300] or f"HTTP {r.status_code}"


async def exchange(code: str, slot: str = "main") -> dict:
    """Trade the code from Google's redirect for tokens and keep them."""
    async with http() as c:
        r = await c.post(TOKEN_URL, data={"code": code, "client_id": client_id(), "client_secret": client_secret(), "redirect_uri": redirect_uri(), "grant_type": "authorization_code"})
    if r.status_code != 200:
        raise YTError("Google refused the sign-in: " + _problem(r))
    j = r.json()
    if not j.get("refresh_token"):
        raise YTError("Google gave no refresh token. Remove this app at myaccount.google.com/permissions and connect again.")
    cur = store.get_auth(slot)
    cur.update({"refresh_token": j["refresh_token"], "access_token": j["access_token"], "expires_at": time.time() + int(j.get("expires_in", 3600)), "scope": j.get("scope", ""), "connected_at": time.time(), "broken": ""})
    store.set_auth(cur, slot)
    return cur


async def access_token(slot: str = "main") -> str:
    a = store.get_auth(slot)
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
            store.set_auth(a, slot)
            raise YTAuthError(a["broken"])
        raise YTError("Could not renew the YouTube connection: " + msg)
    j = r.json()
    a.update({"access_token": j["access_token"], "expires_at": time.time() + int(j.get("expires_in", 3600))})
    store.set_auth(a, slot)
    return a["access_token"]


def has_upload(slot: str = "main") -> bool:
    """The saved sign-in of this slot may upload videos."""
    return UPLOAD_SCOPE in (store.get_auth(slot).get("scope") or "")


async def revoke(slot: str = "main") -> None:
    """Disconnect: tell Google (best effort) and forget the tokens."""
    a = store.get_auth(slot)
    tok = a.get("refresh_token")
    store.clear_auth(slot)
    if tok:
        try:
            async with http() as c:
                await c.post(REVOKE_URL, data={"token": tok})
        except httpx.HTTPError:
            pass
