"""The YouTube thumbnail of a rain video: the scene picture at 1280x720 with a short bold line of words laid on by code
(never drawn by the image model, so the letters are always right). The picture does the work; the words say what it is
("RAIN SOUNDS", the length) in a size that still reads on a phone. JPEG under 2 MB, as the thumbnail upload requires."""
import base64
import io
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

from story3 import store as media
from story3.voice import MediaError

from . import models as M, store

SIZE = (1280, 720)
FONTS = ["impact.ttf", "arialbd.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf"]
MAX_BYTES = 1_900_000


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit(draw: ImageDraw.ImageDraw, text: str, size: int, max_w: int):
    while size > 24:
        f = _font(size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 4
    return _font(24)


def _length_words(settings: dict) -> str:
    return M.duration_label(settings).upper()                  # '3 HOURS', '5 MINUTES'


def render(scene_path: Path, length_words: str) -> bytes:
    im = Image.open(scene_path).convert("RGB")
    w, h = im.size
    k = max(SIZE[0] / w, SIZE[1] / h)                         # cover
    im = im.resize((round(w * k), round(h * k)), Image.LANCZOS)
    l, t = (im.width - SIZE[0]) // 2, (im.height - SIZE[1]) // 2
    im = im.crop((l, t, l + SIZE[0], t + SIZE[1]))

    # a soft dark wash on the left so the words read on any picture
    wash = Image.new("L", SIZE, 0)
    px = wash.load()
    for x in range(SIZE[0]):
        a = int(max(0, 1 - x / (SIZE[0] * 0.62)) ** 1.4 * 190)
        for y in range(SIZE[1]):
            px[x, y] = a
    im = Image.composite(Image.new("RGB", SIZE, (6, 10, 18)), im, wash)

    d = ImageDraw.Draw(im)
    x0, max_w = 56, int(SIZE[0] * 0.5)
    lines = [("RAIN SOUNDS", 118, (255, 255, 255)), (length_words, 150, (255, 214, 130)), ("SLEEP  ·  STUDY  ·  RELAX", 40, (214, 226, 240))]
    heights = []
    for text, size, _ in lines:
        f = _fit(d, text, size, max_w if size > 60 else int(SIZE[0] * 0.46))
        bb = d.textbbox((0, 0), text, font=f)
        heights.append((f, bb[3] - bb[1]))
    total = sum(hh for _, hh in heights) + 26 * (len(lines) - 1)
    y = (SIZE[1] - total) // 2
    for (text, _, color), (f, hh) in zip(lines, heights):
        d.text((x0 + 3, y + 3), text, font=f, fill=(0, 0, 0))             # a hard shadow for contrast
        d.text((x0, y), text, font=f, fill=color)
        y += hh + 26
    for q in (90, 84, 78, 70):
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=q, optimize=True)
        if buf.tell() <= MAX_BYTES:
            break
    return buf.getvalue()


async def picture(session_id: str, s: dict | None = None, key: str = "", force: bool = False, person: str = "") -> dict:
    """The picture under the thumbnail's words: a happy person by the rainy window (Qwen, 1280x720). `person` = "woman" / "man" / "" (the session's own).
    Returns the media row (kind rl_thumbpic). Raises MediaError when the gateway fails; the caller falls back to the scene picture."""
    from story import settings as settings_mod
    s = s or settings_mod.get()
    key = key or settings_mod.api_key()
    if not force:
        have = store.chosen(session_id, M.KIND_THUMB_PIC)
        if have:
            return have
    session = store.get(session_id)
    st = session.setdefault("settings", {})
    who = person or st.get("thumb_person") or M.thumb_person(st.get("seed"))
    if person and person != st.get("thumb_person"):
        st["thumb_person"] = person
        store.save(session)
    prompt = M.thumb_prompt(st.get("scene") or M.DEFAULT_SCENE, who)
    seed = int(st.get("seed") or 7) + 3
    it = media.add(session_id, M.KIND_THUMB_PIC, "thumbpic", 0, "running", {"person": who, "seed": seed})
    try:
        async with httpx.AsyncClient(timeout=900) as c:
            r = await c.post(s["base_url"].rstrip("/") + "/images/generations", headers={"Authorization": f"Bearer {key}"},
                             json={"model": s.get("image_model") or M.IMAGE_MODEL, "prompt": prompt, "size": M.THUMB_SIZE, "n": 1, "steps": M.IMAGE_STEPS,
                                   "response_format": "b64_json", "seed": seed + (len(media.items(session_id, M.KIND_THUMB_PIC, "thumbpic")) - 1) * 7})
        if r.status_code != 200:
            raise MediaError(f"image gateway returned {r.status_code}: {r.text[:200]}")
        data = base64.b64decode(r.json()["data"][0]["b64_json"])
        name = f"pic-a{it['attempt']}.jpg"
        (media.media_dir(session_id, "thumb") / name).write_bytes(data)
        return media.update(it["id"], status="done", file=f"thumb/{name}", meta={"person": who, "seed": seed, "w": 1280, "h": 720})
    except (MediaError, httpx.HTTPError, KeyError, ValueError, OSError) as e:
        media.update(it["id"], status="failed", meta={"error": str(e)[:300]})
        raise MediaError(f"thumbnail picture failed: {e}") from e


def make(session_id: str, force: bool = False) -> dict:
    """The thumbnail media row (kind rl_thumb). Uses the person picture when there is one, else the scene picture."""
    if not force:
        have = store.chosen(session_id, M.KIND_THUMB)
        if have:
            return have
    pic_item = store.chosen(session_id, M.KIND_THUMB_PIC)
    scene_item = pic_item or store.chosen(session_id, M.KIND_SCENE)
    if not scene_item:
        raise MediaError("scene image not generated yet")
    src = media.path_of(scene_item)
    if not src.is_file():
        raise MediaError("scene image file missing")
    settings = (store.get(session_id).get("settings") or {})
    it = media.add(session_id, M.KIND_THUMB, "thumb", 0, "running", {})
    try:
        data = render(src, _length_words(settings))
        name = f"thumb-a{it['attempt']}.jpg"
        (media.media_dir(session_id, "thumb") / name).write_bytes(data)
        return media.update(it["id"], status="done", file=f"thumb/{name}", meta={"w": SIZE[0], "h": SIZE[1], "bytes": len(data), "source": "person" if pic_item else "scene"})
    except OSError as e:
        media.update(it["id"], status="failed", meta={"error": str(e)[:300]})
        raise MediaError(f"thumbnail failed: {e}") from e
