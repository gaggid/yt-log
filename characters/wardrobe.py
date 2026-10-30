"""The wardrobe: pictures of garments (a flat lay, a photo of clothes, a photo of someone wearing them) kept once and reused on any character. Rows of the `media` table under the plan id
`wardrobe` (kind `garment`, one key per garment). A garment picture carries the same rights basis as any upload; it only ever serves as a reference for a try-on edit."""
import hashlib
import io
import time

from PIL import Image

from story import db
from story3 import store as media

from . import store

OWNER = "wardrobe"
KIND = "garment"


def add(raw: bytes, name: str, basis: str, tags: list[str] | None = None, worn: bool = False, source: str = "") -> dict:
    if basis not in store.RIGHTS:
        raise store.CharError("say whose picture it is: " + ", ".join(store.RIGHTS))
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    im.thumbnail((1536, 1536))
    gid = "g-" + hashlib.sha1(f"{name}{time.time()}".encode()).hexdigest()[:8]
    it = media.add(OWNER, KIND, gid, 0, "running", {"name": name.strip() or "Garment", "basis": basis, "tags": [t.strip() for t in (tags or []) if t.strip()], "worn": bool(worn), "source": source})
    rel = f"{KIND}/{gid}.jpg"
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=93)
    (store.media_dir(OWNER, KIND) / f"{gid}.jpg").write_bytes(buf.getvalue())
    return view(media.update(it["id"], status="done", file=rel))


def view(it: dict) -> dict:
    return {"id": it["key"], "name": it["meta"].get("name", ""), "basis": it["meta"].get("basis", ""), "tags": it["meta"].get("tags", []), "worn": bool(it["meta"].get("worn")), "source": it["meta"].get("source", ""),
            "flat": next((i["key"] for i in media.items(OWNER, KIND) if i["meta"].get("source") == it["key"] and i["status"] == "done"), ""), "url": f"/api/characters/wardrobe/file/{it['file']}"}


def listing() -> list[dict]:
    return [view(i) for i in media.items(OWNER, KIND) if i["status"] == "done" and i["file"]]


def get(gid: str) -> dict:
    its = [i for i in media.items(OWNER, KIND, gid) if i["status"] == "done"]
    if not its:
        raise store.CharError("no such garment")
    return its[-1]


def usable(gid: str) -> dict:
    """The garment picture a try-on should use: the flat lay made from a worn photo when there is one (no person in it at all), else the picture itself. Returns {id, path, worn}."""
    it = get(gid)
    flat = next((i for i in media.items(OWNER, KIND) if i["meta"].get("source") == gid and i["status"] == "done" and i["file"]), None)
    pick = flat or it
    return {"id": pick["key"], "path": media.path_of(pick), "worn": bool(pick["meta"].get("worn"))}


def path(gid: str):
    return media.path_of(get(gid))


def delete(gid: str) -> None:
    it = get(gid)
    media.path_of(it).unlink(missing_ok=True)
    db.ex("DELETE FROM media WHERE plan_id=? AND kind=? AND key=?", (OWNER, KIND, gid))
