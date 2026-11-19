"""YouTube Data API v3 video upload (resumable multipart).

Requires the channel to be connected with the youtube.upload scope.
Existing connections that only have youtube.readonly must disconnect and reconnect.

Flow:
  1. POST to the resumable initiation endpoint with JSON metadata → Location URI
  2. PUT the video file to that URI in chunks (8 MB default)
  3. On completion YouTube returns the video id

The session's upload_uri is kept in the session row so a crash can resume from
the last acknowledged byte."""
import asyncio
from pathlib import Path

import httpx

from . import oauth

UPLOAD_API = "https://www.googleapis.com/upload/youtube/v3/videos"
CHUNK = 8 * 1024 * 1024    # 8 MB
UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
TIMEOUT_S = 120


class UploadError(Exception):
    pass


def _has_upload_scope(slot: str = "main") -> bool:
    """Check if the stored token of this slot has the upload scope."""
    return oauth.has_upload(slot)


async def _initiate(tok: str, metadata: dict, file_size: int) -> str:
    """POST to get the resumable upload URI."""
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as c:
        r = await c.post(
            UPLOAD_API,
            params={"uploadType": "resumable", "part": "snippet,status"},
            json=metadata,
            headers={
                "Authorization": f"Bearer {tok}",
                "Content-Type": "application/json",
                "X-Upload-Content-Type": "video/mp4",
                "X-Upload-Content-Length": str(file_size),
            },
        )
    if r.status_code not in (200, 201):
        raise UploadError(f"failed to start upload: {r.status_code} {r.text[:200]}")
    uri = r.headers.get("Location")
    if not uri:
        raise UploadError("YouTube did not return an upload URI")
    return uri


async def _resume_offset(uri: str, file_size: int) -> int:
    """Ask YouTube where to resume from (returns next expected byte offset)."""
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as c:
        r = await c.put(
            uri,
            headers={"Content-Range": f"bytes */{file_size}"},
            content=b"",
        )
    if r.status_code == 308:
        rng = r.headers.get("Range", "")
        if rng:
            return int(rng.split("-")[-1]) + 1
        return 0
    if r.status_code in (200, 201):
        return file_size   # already complete
    raise UploadError(f"resume check returned {r.status_code}")


async def upload_file(path: Path, metadata: dict, progress=None,
                      resume_uri: str | None = None, on_uri=None, slot: str = "main") -> str:
    """Upload a video file and return the YouTube video id.

    `metadata` is the YouTube resource body (snippet, status).
    `resume_uri` lets a previous attempt continue from where it left off.
    `on_uri(uri)` is called the moment the URI is known, so the caller can persist it.
    """
    if not _has_upload_scope(slot):
        raise UploadError(
            "The YouTube connection does not have upload permission. "
            "Disconnect and reconnect the channel to grant upload access."
        )

    tok = await oauth.access_token(slot)
    file_size = path.stat().st_size

    if resume_uri:
        offset = await _resume_offset(resume_uri, file_size)
        uri = resume_uri
        if offset >= file_size:
            raise UploadError("upload already completed but video id was not stored")
    else:
        uri = await _initiate(tok, metadata, file_size)
        if on_uri:
            on_uri(uri)
        offset = 0

    video_id: str = ""
    with path.open("rb") as f:
        f.seek(offset)
        sent = offset
        while sent < file_size:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            end = sent + len(chunk) - 1
            # access token may expire during a long upload; refresh before each chunk
            tok = await oauth.access_token(slot)
            async with httpx.AsyncClient(timeout=TIMEOUT_S) as c:
                r = await c.put(
                    uri,
                    content=chunk,
                    headers={
                        "Authorization": f"Bearer {tok}",
                        "Content-Type": "video/mp4",
                        "Content-Range": f"bytes {sent}-{end}/{file_size}",
                    },
                )
            if r.status_code in (200, 201):
                video_id = r.json().get("id", "")
                sent = file_size
            elif r.status_code == 308:
                rng = r.headers.get("Range", "")
                sent = int(rng.split("-")[-1]) + 1 if rng else sent + len(chunk)
            elif r.status_code == 503:
                await asyncio.sleep(5)
                continue
            else:
                raise UploadError(f"upload chunk failed: {r.status_code} {r.text[:200]}")

            if progress:
                progress(sent, file_size, f"uploading {sent / (1024 * 1024):.0f} / {file_size / (1024 * 1024):.0f} MB")

    if not video_id:
        raise UploadError("upload finished but YouTube returned no video id")
    return video_id


def build_metadata(publish: dict) -> dict:
    """The YouTube resource body from a session's publish dict.
    `selfDeclaredMadeForKids` is the writable field (`madeForKids` is output only). `containsSyntheticMedia` is the
    "altered or synthetic content" disclosure: the rain scenes are realistic AI pictures, so it is declared."""
    return {
        "snippet": {
            "title": (publish.get("title") or "")[:100],
            "description": (publish.get("description") or "")[:5000],
            "tags": (publish.get("tags") or [])[:15],
            "categoryId": str(publish.get("category_id") or "10"),
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,
            "embeddable": True,
            "publicStatsViewable": True,
        },
    }


THUMB_API = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"


async def upload_thumbnail(video_id: str, path: Path, slot: str = "main") -> None:
    """Set the custom thumbnail of an uploaded video (JPEG under 2 MB; the channel must be verified for custom thumbnails)."""
    tok = await oauth.access_token(slot)
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as c:
        r = await c.post(THUMB_API, params={"videoId": video_id, "uploadType": "media"}, content=path.read_bytes(),
                         headers={"Authorization": f"Bearer {tok}", "Content-Type": "image/jpeg"})
    if r.status_code not in (200, 201):
        raise UploadError(f"thumbnail not set: {r.status_code} {r.text[:200]}")
