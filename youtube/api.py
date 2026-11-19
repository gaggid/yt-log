"""/api/youtube: connect the channel, sync it, link videos to shorts, and read how the ideas performed."""
import asyncio
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from . import client, oauth, slots, store, sync

router = APIRouter(prefix="/api/youtube", tags=["youtube"])


def slot_status(slot: str) -> dict:
    """One connection slot: connected, the channel's name, and whether it may upload."""
    a = store.get_auth(slot)
    return {"slot": slot, "label": slots.label(slot), "connected": bool(a.get("refresh_token")) and not a.get("broken"), "broken": a.get("broken", ""),
            "channel": a.get("channel_title", ""), "upload": oauth.has_upload(slot)}


def _status() -> dict:
    a = store.get_auth()
    return {"configured": oauth.configured(), "connected": bool(a.get("refresh_token")) and not a.get("broken"), "broken": a.get("broken", ""), "channel": a.get("channel_title", ""),
            "redirect_uri": oauth.redirect_uri(), "sync": sync.state(), "slots": [slot_status(s) for s in slots.upload_slots()]}


def _slot(name: str) -> str:
    if not slots.valid(name):
        raise HTTPException(400, "unknown YouTube channel slot: " + name)
    return name


@router.get("/status")
async def status():
    return _status()


@router.get("/connect")
async def connect(slot: str = Query("main")):
    """Send the browser to Google's consent screen. Open it from the same address the app is used on (the login cookie must come back with the callback).
    `slot` picks the channel connection: `main` (analytics) or an upload channel such as `rain`."""
    try:
        return RedirectResponse(oauth.auth_url(_slot(slot)))
    except oauth.YTError as e:
        raise HTTPException(400, str(e))


@router.get("/callback")
async def callback(code: str = "", state: str = "", error: str = Query("")):
    if error:
        return RedirectResponse(f"/#/youtube?error={quote(error)}")
    if not oauth.check_state(state):
        return RedirectResponse("/#/youtube?error=" + quote("the sign-in did not start here or took too long; try Connect again"))
    slot = oauth.state_slot(state)
    if not slots.valid(slot):
        return RedirectResponse("/#/youtube?error=" + quote("unknown channel slot"))
    try:
        await oauth.exchange(code, slot)
        if slot != slots.MAIN:                                   # an upload channel is not synced: just learn its name
            ch = await client.my_channel(slot)
            a = store.get_auth(slot)
            a.update({"channel_id": ch["id"], "channel_title": ch["title"]})
            store.set_auth(a, slot)
    except oauth.YTError as e:
        return RedirectResponse("/#/youtube?error=" + quote(str(e)))
    if slot == slots.MAIN:
        sync.start()
    return RedirectResponse(f"/#/youtube?connected=1&slot={slot}")


@router.post("/disconnect")
async def disconnect(slot: str = Query("main")):
    await oauth.revoke(_slot(slot))
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


# ── upload a relaxation session video ────────────────────────────────────────

class _UploadReq(BaseModel):
    session_id: str


@router.post("/upload-video")
async def upload_video(body: _UploadReq):
    """Upload a finished relaxation video to the connected YouTube channel."""
    from story2 import jobs
    from story.pipeline import manager
    from story3 import store as media
    from relaxation import models as RM, store as rstore
    from relaxation.store import SessionError
    from . import upload as yt_upload

    try:
        session = rstore.get(body.session_id)
    except SessionError as e:
        raise HTTPException(404, str(e))
    slot = (session.get("settings") or {}).get("youtube_slot") or RM.YOUTUBE_SLOT          # this pipeline's own channel; never another slot's sign-in
    if not slots.valid(slot):
        raise HTTPException(400, "unknown YouTube channel slot: " + slot)
    st = slot_status(slot)
    if not st["connected"]:
        raise HTTPException(400, f"The {slots.label(slot)} is not connected. Connect it on the YouTube page first.")
    if not st["upload"]:
        raise HTTPException(400, f"The {slots.label(slot)} has no upload permission. Disconnect it and connect it again on the YouTube page.")

    final_item = rstore.chosen(body.session_id, RM.KIND_FINAL)
    if not final_item:
        raise HTTPException(400, "final video not ready yet")

    video_path = media.path_of(final_item)
    if not video_path.is_file():
        raise HTTPException(400, "video file missing on disk")

    pub = session.get("publish") or {}
    if not pub.get("title"):
        raise HTTPException(400, "generate publish metadata first (POST /api/relaxation/{id}/publish)")

    if manager.busy():
        raise HTTPException(409, "another job is running; wait")

    async def work(progress):
        def on_uri(uri):
            s = rstore.get(body.session_id)
            s["upload_uri"] = uri
            s["status"] = rstore.UPLOADING
            rstore.save(s)

        try:
            vid_id = await yt_upload.upload_file(
                video_path,
                yt_upload.build_metadata(pub),
                progress=progress,
                resume_uri=(session.get("upload_uri") or None),
                on_uri=on_uri,
                slot=slot,
            )
            s = rstore.get(body.session_id)
            s["youtube_video_id"] = vid_id
            s["youtube_channel"] = st["channel"]
            s["status"] = rstore.UPLOADED
            s["upload_uri"] = ""
            th = rstore.chosen(body.session_id, RM.KIND_THUMB)
            s["thumbnail_set"] = False
            if th and media.path_of(th).is_file():
                try:
                    await yt_upload.upload_thumbnail(vid_id, media.path_of(th), slot=slot)
                    s["thumbnail_set"] = True
                except yt_upload.UploadError as e:
                    s["thumbnail_error"] = str(e)[:300]        # the video is up; the thumbnail can be set again in Studio
            rstore.save(s)
            freed = await asyncio.to_thread(rstore.drop_after_upload, body.session_id)     # the video is on YouTube: free the disk
            if slot == slots.MAIN:
                sync.start()     # pull the new video into the local stats table (only the main channel is synced)
            return f"Uploaded: https://youtu.be/{vid_id}" + (f" (local video removed, {freed / 1e9:.1f} GB freed)" if freed else "")
        except yt_upload.UploadError as e:
            rstore.set_error(body.session_id, str(e))
            raise HTTPException(400, str(e))

    return jobs.start(body.session_id + ":upload", "yt_upload", work)
