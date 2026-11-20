"""The YouTube thumbnail of a rain video, 1280x720, JPEG under 2 MB (the upload limit).

Since 2026-11-20 the image model draws the big words INTO the picture (huge, bold, the length and the instrument: "3 HOURS BAMBOO FLUTE"), from a prompt that the art model
wrote (relaxation/director.py `plan_thumb`). A vision model reads the words back (relaxation/thumbcheck.py) and the picture is drawn again when a word is wrong; after three
wrong tries the picture is drawn without words and the words are laid on by code (relaxation/thumbrender.py), so the letters are always right in the end."""
import base64
import io
from pathlib import Path

import httpx

from story3 import store as media
from story3.voice import MediaError

from . import models as M, store, thumbcheck, thumbrender

SIZE = thumbrender.SIZE
MAX_BYTES = thumbrender.MAX_BYTES


def _length_words(settings: dict) -> str:
    return M.duration_label(settings).upper()                  # '3 HOURS', '5 MINUTES'


def render(scene_path: Path, length_words: str, spec: dict | None = None) -> bytes:
    """The thumbnail JPEG: the picture with the words laid on by code (relaxation/thumbrender.py: layout, font, colours and words differ per video)."""
    return thumbrender.render(scene_path, length_words, spec)


def reroll(session_id: str, person: str = "") -> dict:
    """New thumbnail seeds for a session (what is shown, who, the layout, the font, the colours, the words), avoiding what the last videos used. `person` = "woman" or
    "man" forces a person of that kind. Saved in the session; returns the seeds."""
    import random
    from . import looks, variety
    session = store.get(session_id)
    st = session.setdefault("settings", {})
    scene = st.get("scene") or M.DEFAULT_SCENE
    angle = st.get("angle") if st.get("angle") in looks.ANGLES else "calm"
    hist = [h for h in variety.history() if h.get("id") != session_id]
    rng = random.Random()
    t = looks.pick_thumb(angle, scene, hist, rng)
    if person in ("woman", "man", "person"):                 # "person": a person at the window, either kind
        who = person if person in looks.WHO else rng.choice(looks.WHO)
        t.update(subject="person", who=who, hair=rng.choice(looks.HAIR[who]))
    ang = looks.ANGLES[angle]
    t["headline"], t["subline"] = rng.choice(ang["headlines"]), ang["tail"]
    instrument = (st.get("music_plan") or {}).get("instrument", "")
    st["thumb"], st["thumb_person"], st["thumb_prompt"] = t, t["who"], looks.thumb_prompt(scene, t, instrument)
    store.save(session)
    return t                                                 # the caller then has the art model write the real prompt (director.plan_thumb)


async def _draw(session_id: str, s: dict, key: str, prompt: str, seed: int, meta: dict) -> dict:
    """One picture from the image model as a numbered attempt (kind rl_thumbpic). Raises MediaError when the gateway fails."""
    it = media.add(session_id, M.KIND_THUMB_PIC, "thumbpic", 0, "running", {**meta, "seed": seed})
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
        return media.update(it["id"], status="done", file=f"thumb/{name}", meta={**meta, "seed": seed, "w": 1280, "h": 720})
    except (MediaError, httpx.HTTPError, KeyError, ValueError, OSError) as e:
        media.update(it["id"], status="failed", meta={**meta, "error": str(e)[:300]})
        raise MediaError(f"thumbnail picture failed: {e}") from e


async def picture(session_id: str, s: dict | None = None, key: str = "", force: bool = False, person: str = "") -> dict:
    """The thumbnail's picture (Qwen, 1280x720). With the big words drawn into it when the art model wrote the prompt (`settings.thumb.text_in_picture`): the words are read
    back and the picture is drawn again (three tries) when they are wrong; then it is drawn without words and thumb.make lays them on. `person` = "woman" / "man" / "" (the
    session's own) makes a person picture with no words in it. Returns the media row. Raises MediaError when the gateway fails; the caller falls back to the scene picture."""
    from story import settings as settings_mod
    s = s or settings_mod.get()
    key = key or settings_mod.api_key()
    if not force:
        have = store.chosen(session_id, M.KIND_THUMB_PIC)
        if have:
            return have
    session = store.get(session_id)
    st = session.setdefault("settings", {})
    from . import looks
    scene = st.get("scene") or M.DEFAULT_SCENE
    instrument = (st.get("music_plan") or {}).get("instrument", "")
    t = dict(st.get("thumb") or {})
    who = person or st.get("thumb_person") or t.get("who") or M.thumb_person(st.get("seed"))
    if person and (person != t.get("who") or t.get("subject") != "person"):
        t = {**(t if t.get("layout") else looks.pick_thumb(st.get("angle") or "calm", scene, [], __import__("random").Random(int(st.get("seed") or 1)))), "subject": "person", "who": person,
             "text_in_picture": False}
        st["thumb"], st["thumb_person"], st["thumb_prompt"] = t, person, looks.thumb_prompt(scene, t, instrument)
        store.save(session)
    if st.get("thumb_prompt"):
        prompt = st["thumb_prompt"]                      # written for this video (relaxation/director.py), or built from its seeds
    elif t.get("layout"):
        prompt = looks.thumb_prompt(scene, t, instrument)
    else:
        prompt = M.thumb_prompt(scene, who)
    seed = int(st.get("seed") or 7) + 3
    meta = {"person": who, "subject": t.get("subject", "person")}
    expected = t.get("text", "")
    if not (t.get("text_in_picture") and expected):
        return await _draw(session_id, s, key, prompt, seed, meta)
    for _ in range(3):
        row = await _draw(session_id, s, key, prompt, seed, {**meta, "text": expected})
        got = await thumbcheck.read(media.path_of(row), s, key)
        if got is None or thumbcheck.matches(expected, got):                 # None: the check could not run, the picture is accepted
            return media.update(row["id"], meta={**row["meta"], "text_read": got})
        media.update(row["id"], status="failed", meta={**row["meta"], "error": f"the words are wrong in the picture: read '{got}', wanted '{expected}'"})
    session = store.get(session_id)                         # three wrong tries: a picture with no words, and the words are laid on by code
    st = session["settings"]
    st["thumb"] = {**st.get("thumb", {}), "text_in_picture": False}
    st["thumb_prompt"] = looks.thumb_prompt(scene, st["thumb"], instrument)
    store.save(session)
    return await _draw(session_id, s, key, st["thumb_prompt"], seed, {**meta, "text": "", "words_by_code": True})


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
    spec = dict(settings.get("thumb") or {})
    drawn = bool(pic_item and spec.get("text_in_picture") and (pic_item.get("meta") or {}).get("text"))        # the picture already carries the big words
    if not pic_item:
        spec["side"] = "right"                               # the scene picture has no subject to keep clear: the words go to the left
    it = media.add(session_id, M.KIND_THUMB, "thumb", 0, "running", {"layout": spec.get("layout", ""), "headline": spec.get("headline", "")})
    try:
        data = thumbrender.plain(src) if drawn else render(src, _length_words(settings), spec)
        name = f"thumb-a{it['attempt']}.jpg"
        (media.media_dir(session_id, "thumb") / name).write_bytes(data)
        return media.update(it["id"], status="done", file=f"thumb/{name}", meta={"w": SIZE[0], "h": SIZE[1], "bytes": len(data), "source": "person" if pic_item else "scene", "words": "picture" if drawn else "code"})
    except OSError as e:
        media.update(it["id"], status="failed", meta={"error": str(e)[:300]})
        raise MediaError(f"thumbnail failed: {e}") from e
