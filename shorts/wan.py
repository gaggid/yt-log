"""The one client for the gateway's video endpoint (`POST /v1/video/generations`, then `GET /v1/jobs/{id}`). A request answers 202 with a job id; the clip takes minutes,
so the id is handed to `on_job` the moment it is known and stored with the attempt: a restart can pick the job up again with `resume` (the gateway keeps a finished result
for about an hour and the file for about a day).

Errors the docs call temporary (429, 502, 503) are retried; a bad request (400) never is."""
import asyncio
import base64
import json
import time
from urllib.parse import urlsplit

import httpx

RETRIES = 2                                   # extra tries after a failed or refused request (docs: "retry once or twice")
POLL_S = 5
JOB_LIMIT_S = 3600                            # the slowest single clip in the docs is about 23 minutes; one hour leaves room for a queue
BODY_LIMIT = 24 * 1024 * 1024                 # the gateway refuses a JSON body over 25 MB
SUBMIT_TIMEOUT_S = 60
DOWNLOAD_TIMEOUT_S = 300


class WanError(Exception):
    def __init__(self, msg: str, lost: bool = False):
        super().__init__(msg)
        self.lost = lost                       # the job is gone from the gateway (expired): the attempt must be made again


def _client(timeout: float) -> httpx.AsyncClient:      # one place to swap in a test gateway
    return httpx.AsyncClient(timeout=timeout)


def _headers(key: str, background: bool = False) -> dict:
    h = {"Authorization": f"Bearer {key}"}
    if background:
        h["X-Priority"] = "background"
    return h


def origin(base: str) -> str:
    u = urlsplit(base)
    return f"{u.scheme}://{u.netloc}"


def data_url(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def _error_text(r: httpx.Response) -> str:
    try:
        j = r.json()
        e = j.get("error", j)
        if isinstance(e, dict):
            return f"{e.get('code', r.status_code)}: {e.get('message', '')}"[:300]
        return str(e)[:300]
    except ValueError:
        return f"{r.status_code} {r.text[:200]}"


def body_size(body: dict) -> int:
    return len(json.dumps(body))


async def submit(body: dict, base: str, key: str, background: bool = False) -> dict:
    """Send the request. Returns the gateway's answer: {"id": ...} for a queued job, or a finished result when the gateway answered at once."""
    if body_size(body) > BODY_LIMIT:
        raise WanError(f"the request is {body_size(body) // 1048576} MB; the gateway takes at most 25 MB (use smaller pictures or a shorter, smaller driving video)")
    last = ""
    url = base.rstrip("/") + "/video/generations"
    for n in range(RETRIES + 1):
        try:
            async with _client(SUBMIT_TIMEOUT_S) as c:
                r = await c.post(url, json=body, headers=_headers(key, background))
        except httpx.ConnectError as e:
            raise WanError(f"the model server is not reachable ({e})") from e
        except (httpx.TransportError, httpx.TimeoutException) as e:
            last = f"{type(e).__name__}: {e}"
        else:
            if r.status_code in (200, 202):
                return r.json()
            last = _error_text(r)
            if r.status_code not in (429, 502, 503):
                raise WanError(f"the model server refused the request ({r.status_code}): {last}")
            wait_s = float(r.headers.get("Retry-After") or 5 * (n + 1))
            await asyncio.sleep(min(wait_s, 120))
            continue
        await asyncio.sleep(5 * (n + 1))
    raise WanError(f"the model server did not take the request: {last}")


def _result(j: dict) -> dict:
    res = j.get("result")
    return res if isinstance(res, dict) else j


async def wait(job_id: str, base: str, key: str, limit_s: float = JOB_LIMIT_S, progress=None) -> dict:
    """Poll the job until it has succeeded; returns its result dict (`url`, `width`, `height`, `frames`, `fps`, `duration_s`, `seed`, ...)."""
    url = base.rstrip("/") + "/jobs/" + job_id
    t0 = time.time()
    misses = 0
    while time.time() - t0 < limit_s:
        try:
            async with _client(30) as c:
                r = await c.get(url, headers=_headers(key))
        except (httpx.TransportError, httpx.TimeoutException):
            misses += 1
            if misses > 20:
                raise WanError("lost touch with the model server while a clip was being made")
            await asyncio.sleep(POLL_S)
            continue
        misses = 0
        if r.status_code == 404:
            raise WanError("the gateway no longer has this job (results are kept for about an hour); make the shot again", lost=True)
        if r.status_code != 200:
            raise WanError(f"job check failed: {r.status_code} {r.text[:120]}")
        j = r.json()
        st = j.get("status")
        if st == "succeeded":
            return _result(j)
        if st in ("failed", "cancelled", "canceled", "error"):
            e = j.get("error")
            raise WanError(f"video job {st}: {(e.get('message') if isinstance(e, dict) else e) or j.get('http_status') or ''}"[:300])
        if progress:
            progress(time.time() - t0)
        await asyncio.sleep(POLL_S)
    raise WanError(f"the clip did not finish within {int(limit_s // 60)} minutes", lost=True)


async def fetch(result: dict, base: str, key: str) -> bytes:
    """The clip's bytes. The result's url may be a path on the gateway's host (`/video/{token}.mp4`) or sit under the API path; both are tried."""
    if result.get("video_b64"):
        return base64.b64decode(result["video_b64"])
    u = result.get("url") or ""
    if not u:
        raise WanError("the video job finished without a file")
    cands = [u] if u.startswith("http") else [origin(base) + "/" + u.lstrip("/"), base.rstrip("/") + "/" + u.lstrip("/")]
    last = ""
    async with _client(DOWNLOAD_TIMEOUT_S) as c:
        for cu in cands:
            try:
                r = await c.get(cu, headers=_headers(key))
            except (httpx.TransportError, httpx.TimeoutException) as e:
                last = f"{type(e).__name__}: {e}"
                continue
            if r.status_code == 200 and r.content:
                return r.content
            last = f"{r.status_code}"
    raise WanError(f"the finished clip could not be downloaded ({last})", lost=True)


async def run(body: dict, base: str, key: str, on_job=None, limit_s: float = JOB_LIMIT_S, background: bool = False) -> tuple[bytes, dict]:
    """Submit, wait, download. A job that fails on the gateway's side is submitted again (up to RETRIES times). Returns (mp4 bytes, result dict)."""
    last: WanError | None = None
    for _ in range(RETRIES + 1):
        ans = await submit(body, base, key, background)
        if ans.get("id") and ans.get("status") != "succeeded":
            if on_job:
                on_job(ans["id"])
            try:
                res = await wait(ans["id"], base, key, limit_s)
            except WanError as e:
                if e.lost:
                    raise
                last = e
                continue
        else:
            res = _result(ans)
        return await fetch(res, base, key), res
    raise last or WanError("the clip could not be made")


async def resume(job_id: str, base: str, key: str, limit_s: float = JOB_LIMIT_S) -> tuple[bytes, dict]:
    """Pick up a job that was running when the app stopped."""
    res = await wait(job_id, base, key, limit_s)
    return await fetch(res, base, key), res


async def models(base: str, key: str) -> list[dict]:
    """The video models the key can use (`GET /v1/models`, type video). Empty list when the gateway cannot be asked."""
    try:
        async with _client(15) as c:
            r = await c.get(base.rstrip("/") + "/models", headers=_headers(key))
        r.raise_for_status()
        return [m for m in r.json().get("data", []) if m.get("type") == "video"]
    except (httpx.HTTPError, ValueError):
        return []
