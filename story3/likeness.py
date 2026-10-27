"""Named people (B8, docs/PLAN_story_types.md). A real, public person in a biography or documentary can be drawn to look like them, in the plan's painted style.

How it works, step by step, with the editor deciding each one:
  1. The editor marks a person in the character list as a public figure and chooses how they appear: `silhouette` (the default and the old rule), `researched`
     (a painted character made from a photo the editor approved) or `stylised` (a near-likeness written from a description, no photo).
  2. For `researched`, photos come from a web search of Wikimedia Commons (free images with their licence and author recorded) or from a file the editor uploads.
     Nothing is used until the editor approves one photo; any photo can be rejected; the person can go back to silhouette at any time.
  3. `refs.generate` then sends the approved photo to the image model's edit endpoint as the reference and paints the character sheet in the plan's style. The photo is
     only ever a reference: it is never put in a scene, a graphic, the video or the export; the export's evidence half records where it came from.
When no photo is found or approved, `stylised` is the fallback. The photo files live under the plan's media folder (`likeness/`) and the list of photos in the
asset record (`likeness_photos`, outside the content hash, like `reference_images`)."""
import io
import uuid
from urllib.parse import urlparse

import httpx
from PIL import Image

from story import db
from story2 import imgplan, planner, storyboard, store as plan_store

from . import store
from .voice import MediaError

COMMONS = "https://commons.wikimedia.org/w/api.php"
UA = "source-to-story/1.0 (editorial research; https://podcast.tripfick.com)"
MAX_BYTES = 8 * 1024 * 1024
MAX_PHOTOS = 6
MODES = {"silhouette": "real_person_no_likeness", "researched": "real_person_likeness", "stylised": "real_person_stylised"}
REAL = tuple(MODES.values())


def mode_of(asset: dict) -> str:
    fic = asset["data"].get("fictionalisation")
    return next((m for m, f in MODES.items() if f == fic), "")


def _asset(plan_id: str, asset_id: str) -> dict:
    a = next((x for x in storyboard.get_assets(plan_id) if x["id"] == asset_id), None)
    if not a or a["kind"] != "person":
        raise MediaError("choose a person from the character list")
    return a


def _save(asset_id: str, data: dict) -> None:
    db.ex("UPDATE assets SET data=?, rev=rev+1, updated_at=? WHERE id=?", (db.jdump(data), db.now(), asset_id))


def photos(asset: dict) -> list[dict]:
    return asset["data"].get("likeness_photos") or []


def approved_photo(asset: dict) -> dict | None:
    return next((p for p in photos(asset) if p.get("approved") and p.get("status") != "rejected"), None)


def approved_path(plan_id: str, asset: dict):
    p = approved_photo(asset)
    f = store.media_dir(plan_id, "likeness") / p["file"].split("/")[-1] if p else None
    return f if f and f.is_file() else None


# ── the choice ──────────────────────────────────────────────────────────────

def set_mode(plan_id: str, asset_id: str, mode: str, public_figure: bool | None = None) -> dict:
    """Choose how a person appears. `researched` and `stylised` need the editor to confirm the person is a public figure; `silhouette` needs nothing."""
    a = _asset(plan_id, asset_id)
    if mode not in MODES:
        raise MediaError("the choices are silhouette, researched or stylised")
    data = dict(a["data"])
    if public_figure is not None:
        data["public_figure"] = bool(public_figure)
    if mode != "silhouette" and not data.get("public_figure"):
        raise MediaError("confirm that this is a public figure first: a likeness is only made for public figures, never for private individuals")
    data["fictionalisation"] = MODES[mode]
    if mode != "researched":
        data["likeness_photos"] = [{**p, "approved": False} for p in photos(a)]                        # the photo is not used any more; it is kept in the list
    _save(asset_id, data)
    plan_store.log(plan_id, "likeness_mode", {"asset": asset_id, "mode": mode})
    if storyboard.get_scenes(plan_id):
        imgplan.compile_plan(plan_id)                                                                  # silhouette hides the face in prompts; the other two do not
    return state(plan_id)


# ── finding photos ──────────────────────────────────────────────────────────

def search(name: str, limit: int = MAX_PHOTOS) -> list[dict]:
    """Photos of a person from Wikimedia Commons: each with its licence, author and page, so the editor can judge and the export can record it."""
    params = {"action": "query", "format": "json", "generator": "search", "gsrsearch": f"{name} filetype:bitmap", "gsrnamespace": 6, "gsrlimit": limit * 2,
              "prop": "imageinfo", "iiprop": "url|extmetadata|size|mime", "iiurlwidth": 900}
    try:
        r = httpx.get(COMMONS, params=params, headers={"User-Agent": UA}, timeout=20)
        r.raise_for_status()
        pages = (r.json().get("query") or {}).get("pages") or {}
    except (httpx.HTTPError, ValueError) as e:
        raise MediaError(f"the photo search did not answer ({type(e).__name__}); try again or upload a photo") from e
    out = []
    for pg in sorted(pages.values(), key=lambda x: x.get("index", 0)):
        ii = (pg.get("imageinfo") or [{}])[0]
        if ii.get("mime") not in ("image/jpeg", "image/png") or not ii.get("thumburl") or (ii.get("width") or 0) < 300:
            continue
        meta = ii.get("extmetadata") or {}
        out.append({"title": pg.get("title", ""), "url": ii["thumburl"], "page": ii.get("descriptionurl", ""),
                    "licence": (meta.get("LicenseShortName") or {}).get("value", ""), "author": _plain((meta.get("Artist") or {}).get("value", "")),
                    "width": ii.get("width"), "height": ii.get("height")})
        if len(out) >= limit:
            break
    return out


def _plain(html: str) -> str:
    import re
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html or "")).strip()[:160]


def _download(url: str) -> bytes:
    from story import ingest
    u = urlparse(url)
    if u.scheme != "https" or not u.hostname:
        raise MediaError("only https photo links can be used")
    try:
        ingest._check_public(u.hostname)
    except ingest.IngestError as e:
        raise MediaError(str(e)) from e
    try:
        with httpx.stream("GET", url, headers={"User-Agent": UA}, timeout=30, follow_redirects=False) as r:
            if r.status_code != 200:
                raise MediaError(f"the photo link answered HTTP {r.status_code}")
            buf = bytearray()
            for chunk in r.iter_bytes():
                buf.extend(chunk)
                if len(buf) > MAX_BYTES:
                    raise MediaError("the photo is larger than 8 MB")
            return bytes(buf)
    except httpx.HTTPError as e:
        raise MediaError(f"the photo could not be downloaded ({type(e).__name__})") from e


def _as_png(raw: bytes) -> bytes:
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
    except Exception as e:  # noqa: BLE001 - any decoding failure means it is not a usable picture
        raise MediaError("that file is not a readable picture (use a JPEG or PNG)") from e
    if min(im.size) < 200:
        raise MediaError("the photo is too small to be a useful reference (shortest side under 200 pixels)")
    im = im.convert("RGB")
    im.thumbnail((1600, 1600))
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue()


def add_photo(plan_id: str, asset_id: str, raw: bytes, source: dict) -> dict:
    """Keep one candidate photo for a person. `source` says where it came from: {origin: search|upload, url, page, licence, author}."""
    a = _asset(plan_id, asset_id)
    if len(photos(a)) >= MAX_PHOTOS * 2:
        raise MediaError("this person already has many photos; reject some first")
    png = _as_png(raw)
    pid = "ph-" + uuid.uuid4().hex[:8]
    (store.media_dir(plan_id, "likeness") / f"{pid}.png").write_bytes(png)
    data = dict(a["data"])
    data["likeness_photos"] = photos(a) + [{"id": pid, "file": f"likeness/{pid}.png", "approved": False, "status": "candidate", "added_at": db.now(),
                                            **{k: str(source.get(k) or "")[:300] for k in ("origin", "url", "page", "licence", "author")}}]
    _save(asset_id, data)
    return data["likeness_photos"][-1]


def find_photos(plan_id: str, asset_id: str, limit: int = 4) -> dict:
    """Search the web for the person by name and keep the best candidates for the editor to look at."""
    a = _asset(plan_id, asset_id)
    if not a["data"].get("public_figure"):
        raise MediaError("confirm that this is a public figure first")
    known = {p.get("url") for p in photos(a)}
    added, skipped = [], []
    for hit in search(a["name"], limit + len(known)):
        if hit["url"] in known:
            continue
        try:
            added.append(add_photo(plan_id, asset_id, _download(hit["url"]), {"origin": "search", **hit}))
        except MediaError as e:
            skipped.append(str(e)[:100])
        if len(added) >= limit:
            break
    plan_store.log(plan_id, "likeness_search", {"asset": asset_id, "found": len(added)})
    return {"added": len(added), "skipped": skipped, "state": state(plan_id)}


def approve_photo(plan_id: str, asset_id: str, photo_id: str, on: bool = True) -> dict:
    """The editor picks the one photo the character is made from (the others are un-approved). Needs the person to be a confirmed public figure."""
    a = _asset(plan_id, asset_id)
    if on and not a["data"].get("public_figure"):
        raise MediaError("confirm that this is a public figure first")
    if not any(p["id"] == photo_id for p in photos(a)):
        raise MediaError("photo not found")
    data = dict(a["data"])
    data["likeness_photos"] = [{**p, "approved": bool(on and p["id"] == photo_id), **({"approved_at": db.now()} if on and p["id"] == photo_id else {})} for p in photos(a)]
    if on:
        data["fictionalisation"] = MODES["researched"]
    _save(asset_id, data)
    plan_store.log(plan_id, "likeness_photo", {"asset": asset_id, "photo": photo_id, "approved": bool(on)})
    if storyboard.get_scenes(plan_id):
        imgplan.compile_plan(plan_id)
    return state(plan_id)


def reject_photo(plan_id: str, asset_id: str, photo_id: str) -> dict:
    a = _asset(plan_id, asset_id)
    data = dict(a["data"])
    data["likeness_photos"] = [{**p, "approved": False, "status": "rejected"} if p["id"] == photo_id else p for p in photos(a)]
    if not approved_photo({"data": data}) and data.get("fictionalisation") == MODES["researched"]:
        data["fictionalisation"] = MODES["stylised"]                                                   # no approved photo left: fall back to the near-likeness
    _save(asset_id, data)
    return state(plan_id)


def people(plan_id: str) -> list[dict]:
    return [a for a in storyboard.get_assets(plan_id) if a["kind"] == "person"]


def state(plan_id: str) -> dict:
    planner.get_plan(plan_id)
    return {"people": [{"id": a["id"], "name": a["name"], "mode": mode_of(a) or "silhouette" if a["data"].get("fictionalisation") in REAL else "", "public_figure": bool(a["data"].get("public_figure")),
                        "photos": [{k: p.get(k) for k in ("id", "file", "approved", "status", "origin", "url", "page", "licence", "author")} for p in photos(a)],
                        "has_photo": bool(approved_photo(a))} for a in people(plan_id)]}


def evidence(plan_id: str) -> list[dict]:
    """For the export's evidence half: where each used photo came from and that it was used only as a reference."""
    out = []
    for a in people(plan_id):
        p = approved_photo(a)
        if p and a["data"].get("fictionalisation") == MODES["researched"]:
            out.append({"asset": a["id"], "name": a["name"], "photo": {k: p.get(k) for k in ("origin", "url", "page", "licence", "author", "approved_at")},
                        "use": "reference for a painted character only; the photo itself is not published"})
    return out
