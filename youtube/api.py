"""/api/youtube: connect the channel, sync it, link videos to shorts, and read how the ideas performed."""
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from . import oauth, store, sync

router = APIRouter(prefix="/api/youtube", tags=["youtube"])


def _status() -> dict:
    a = store.get_auth()
    return {"configured": oauth.configured(), "connected": bool(a.get("refresh_token")) and not a.get("broken"), "broken": a.get("broken", ""), "channel": a.get("channel_title", ""),
            "redirect_uri": oauth.redirect_uri(), "sync": sync.state()}


@router.get("/status")
async def status():
    return _status()


@router.get("/connect")
async def connect():
    """Send the browser to Google's consent screen. Open it from the same address the app is used on (the login cookie must come back with the callback)."""
    try:
        return RedirectResponse(oauth.auth_url())
    except oauth.YTError as e:
        raise HTTPException(400, str(e))


@router.get("/callback")
async def callback(code: str = "", state: str = "", error: str = Query("")):
    if error:
        return RedirectResponse(f"/#/youtube?error={quote(error)}")
    if not oauth.check_state(state):
        return RedirectResponse("/#/youtube?error=" + quote("the sign-in did not start here or took too long; try Connect again"))
    try:
        await oauth.exchange(code)
    except oauth.YTError as e:
        return RedirectResponse("/#/youtube?error=" + quote(str(e)))
    sync.start()
    return RedirectResponse("/#/youtube?connected=1")


@router.post("/disconnect")
async def disconnect():
    await oauth.revoke()
    return _status()


@router.post("/sync")
async def sync_now():
    if not _status()["connected"]:
        raise HTTPException(400, "YouTube is not connected")
    sync.start()
    return _status()


@router.get("/performance")
async def performance():
    return {**sync.performance(), "unlinked": sync.unlinked(), "targets": sync.link_targets(), "status": _status()}


class _LinkReq(BaseModel):
    short_id: str
    video: str


@router.post("/link")
async def link(body: _LinkReq):
    try:
        vid = sync.link_by_hand(body.short_id, body.video)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001 - an unknown short
        raise HTTPException(404, str(e))
    if _status()["connected"] and not store.video(vid):
        sync.start()                                    # the video is not in the local copy yet
    return {"video_id": vid}


@router.delete("/link/{video_id}")
async def unlink(video_id: str):
    store.remove_link(video_id)
    return {"ok": True}
