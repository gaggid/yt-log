"""Pictures of a story (docs/PLAN_simulation.md section 12): cinematic painted illustrations drawn from text by the gateway image model. Not photographs, not from Character Studio. A character or place gets
one reference painting from its `look` text; panels are made by edit from those references (so faces and places stay alike) and fall back to the text alone when no reference can be used.
Image requests are built only here. Captions are lettered by code (the image model never draws text)."""
import hashlib
import io
import json
import re
from pathlib import Path

from story import settings as settings_mod
from story2 import providers
from story3 import store as media

from . import models as m, prompts as P, store
from .engine import Stopped, _json

STYLE = "cinematic digital painting, dramatic lighting, painterly brushwork, rich colour grading, film-still composition, concept-art quality"
KEEP_OUT = "An original painted illustration, not a photograph. No text, no letters, no numbers, no logo, no watermark, no collage, no split screen."
SIZES = {"wide": "1280x720", "tall": "720x1280"}
REF_SIZE = "1024x1024"
SHOTS = {"wide": "A wide establishing view:", "medium": "A medium shot:", "close": "A close-up:", "detail": "A close detail shot:", "over-shoulder": "An over-the-shoulder shot:"}
MAX_PANELS = 5
NEGATIVE = re.compile(r"\b(no|not|without|never|nothing|none|isn't|aren't|doesn't)\b", re.I)


def model_of(cfg: dict) -> str:
    return cfg.get("image_model") or providers.DEFAULT_MODEL


def _h(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:12]


def _seed(cfg: dict, *parts) -> int:
    return int(_h(cfg["seed"], *parts), 16) % (2 ** 32)


# ── reference paintings ───────────────────────────────────────────────────────

def look_of(e: dict) -> str:
    return (e.get("look") or e.get("description") or e["name"]).strip()


def ref_hash(e: dict, cfg: dict) -> str:
    return _h(look_of(e), e["name"], STYLE, model_of(cfg), e["kind"])


def ref_request(e: dict, cfg: dict) -> dict:
    if e["kind"] == "character":
        text = f"{STYLE}. A portrait of {e['name']}: {look_of(e)} Head and shoulders, three-quarter view, a simple softly lit painted background. {KEEP_OUT}"
    else:
        text = f"{STYLE}. An establishing view of {e['name']}: {look_of(e)} {KEEP_OUT}"
    body = {"model": model_of(cfg), "prompt": text[:3900], "size": REF_SIZE, "n": 1, "seed": _seed(cfg, "ref", e["id"]), "response_format": "b64_json"}
    return {"how": "draw", "body": body, "refs": [], "hash": ref_hash(e, cfg)}


def latest_ref(pid: str, eid: str) -> dict | None:
    """The newest finished reference painting of a character or place."""
    rows = [r for r in media.items(pid, "sim_ref", eid) if r["status"] == "done" and r["file"]]
    return rows[-1] if rows else None


def ref_is_old(pid: str, e: dict, cfg: dict) -> bool:
    r = latest_ref(pid, e["id"])
    return bool(r) and r["meta"].get("hash") != ref_hash(e, cfg)


# ── panels ────────────────────────────────────────────────────────────────────

def panel_hash(p: dict, ents: dict, cfg: dict) -> str:
    looks = {n: look_of(ents[n]) for n in [*p.get("who", []), p.get("place", "")] if n in ents}
    return _h(p.get("shot"), p.get("action"), p.get("mood"), p.get("who"), p.get("place"), p.get("prompt_override", ""), looks, STYLE, model_of(cfg), cfg["panel_shape"])


def _positive(text: str) -> str:
    return text.strip().rstrip(".") + "."


def panel_request(pid: str, p: dict, ents: dict, cfg: dict, chapter_idx: int, n: int) -> dict:
    """An edit from the reference paintings of the people in the picture (at most two) and the place, or a plain drawing from their look texts."""
    size = SIZES[cfg["panel_shape"]]
    seed = _seed(cfg, "panel", chapter_idx, n)
    who = [ents[x] for x in p.get("who", []) if x in ents and ents[x]["kind"] == "character"][:2]
    place = ents.get(p.get("place", ""))
    shot = SHOTS.get(p.get("shot"), SHOTS["medium"])
    scene = p.get("prompt_override") or _positive(p["action"])
    mood = f" Light and mood: {p['mood'].strip().rstrip('.')}." if p.get("mood") else ""
    refs, names = [], []
    for e in who + ([place] if place else []):
        r = latest_ref(pid, e["id"])
        if r:
            refs.append(media.path_of(r))
            names.append((e, r))
    if refs:
        parts = []
        for i, (e, r) in enumerate(names, 1):
            parts.append(f"Picture {i} shows {e['name']}." if e["kind"] == "character" else f"Picture {i} shows the place.")
        text = (f"{' '.join(parts)} Create a new painted illustration in the same painted style. {shot} {scene}{mood} The people look exactly as in their pictures. {STYLE}. {KEEP_OUT}")[:3900]
        return {"how": "edit", "body": {"model": model_of(cfg), "prompt": text, "size": size, "n": 1, "seed": seed, "response_format": "b64_json"}, "refs": refs, "ref_ids": [r["id"] for _, r in names]}
    looks = " ".join(f"{e['name']}: {look_of(e)}" for e in who)
    setting = f" The setting: {look_of(place)}" if place else ""
    text = f"{STYLE}. {shot} {scene}{mood} {looks}{setting} {KEEP_OUT}"[:3900]
    return {"how": "draw", "body": {"model": model_of(cfg), "prompt": text, "size": size, "n": 1, "seed": seed, "response_format": "b64_json"}, "refs": [], "ref_ids": []}


async def plan_panels(pid: str, cid: str, backend, s: dict) -> list[dict]:
    """3 to 5 pictures for a chapter, checked by code: known names, at most two people, positive wording, short captions."""
    ch = store.chapter(cid)
    ents = store.entities(pid)
    chars = {e["name"].lower(): e["name"] for e in ents if e["kind"] == "character"}
    places = {e["name"].lower(): e["name"] for e in ents if e["kind"] == "place"}

    def v(o: m.PanelsOut, caller):
        out = []
        for x in o.panels[:MAX_PANELS]:
            x.who = [chars[w.lower()] for w in x.who if w.lower() in chars][:2]
            x.place = places.get(x.place.lower(), "")
            x.shot = x.shot if x.shot in SHOTS else "medium"
            x.caption = " ".join(x.caption.split()[:12])
            if NEGATIVE.search(x.action) and not caller.last_attempt:
                raise ValueError("say what is seen in positive words; do not use no/not/without in an action")
            if x.action.strip():
                out.append(x)
        if len(out) < 3 and not caller.last_attempt:
            raise ValueError("write 3 to 5 pictures")
        o.panels = out

    user = (f"CHAPTER {ch['idx']}: {ch['title']} ({ch['story_time']})\n{ch['prose']}\n\nCHARACTERS: {', '.join(chars.values())}\nPLACES: {', '.join(places.values())}\n\nPlan the pictures now.")
    o = await _json(backend, s, P.PANELS, user, m.PanelsOut, v)
    return [{"n": i, "shot": x.shot, "who": x.who, "place": x.place, "action": _positive(x.action), "mood": x.mood, "caption": x.caption, "file": "", "capfile": "", "media_id": "", "hash": "", "old": False}
            for i, x in enumerate(o.panels, 1)]


# ── caption strip ─────────────────────────────────────────────────────────────

def _font(size: int):
    from PIL import ImageFont
    for root in (Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/dejavu")):
        for name in ("georgia.ttf", "arial.ttf", "DejaVuSerif.ttf", "DejaVuSans.ttf"):
            f = root / name
            if f.is_file():
                return ImageFont.truetype(str(f), size)
    return ImageFont.load_default()


def with_caption(png: bytes, caption: str) -> bytes:
    from PIL import Image, ImageDraw
    img = Image.open(io.BytesIO(png)).convert("RGBA")
    w, h = img.size
    size = max(18, h // 26)
    font = _font(size)
    draw = ImageDraw.Draw(img)
    lines, cur = [], ""
    for word in caption.split():
        t = (cur + " " + word).strip()
        if draw.textlength(t, font=font) > w * 0.9 and cur:
            lines.append(cur)
            cur = word
        else:
            cur = t
    if cur:
        lines.append(cur)
    bar_h = int(len(lines) * size * 1.35 + size)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rectangle([0, h - bar_h, w, h], fill=(0, 0, 0, 165))
    y = h - bar_h + size // 2
    for line in lines:
        d.text(((w - d.textlength(line, font=font)) / 2, y), line, font=font, fill=(255, 255, 255, 255))
        y += int(size * 1.35)
    out = io.BytesIO()
    Image.alpha_composite(img, layer).convert("RGB").save(out, "PNG")
    return out.getvalue()


# ── drawing ───────────────────────────────────────────────────────────────────

async def _send(req: dict, base: str, key: str) -> bytes:
    from shorts import stills
    try:
        return await stills.send(req, base, key)
    except Exception:
        if req["how"] != "edit":
            raise
        return await stills.send({"how": "draw", "body": req["body"], "refs": []}, base, key)       # the edit failed: the text alone still makes a picture


def _save(pid: str, sub: str, name: str, data: bytes) -> str:
    d = media.media_dir(pid, sub)
    (d / name).write_bytes(data)
    return f"{sub}/{name}"


async def paint_ref(pid: str, e: dict, cfg: dict, s: dict, key: str, send=None) -> dict:
    req = ref_request(e, cfg)
    item = media.add(pid, "sim_ref", e["id"], meta={"hash": req["hash"], "prompt": req["body"]["prompt"], "name": e["name"]})
    try:
        png = await (send or _send)(req, s["base_url"], key)
        rel = _save(pid, "refs", f"{e['id']}-{item['attempt']}.png", png)
        return media.update(item["id"], status="done", file=rel)
    except Exception as ex:  # noqa: BLE001
        media.update(item["id"], status="failed", meta={"error": str(ex)[:300]})
        raise


async def paint_panel(pid: str, cid: str, n: int, cfg: dict, s: dict, key: str, send=None) -> dict:
    ch = store.chapter(cid)
    ents = {e["name"]: e for e in store.entities(pid)}
    panels = ch["panels"]
    p = next(x for x in panels if x["n"] == n)
    req = panel_request(pid, p, ents, cfg, ch["idx"], n)
    item = media.add(pid, "sim_panel", f"{cid}:{n}", meta={"prompt": req["body"]["prompt"], "how": req["how"], "refs": req["ref_ids"]})
    try:
        png = await (send or _send)(req, s["base_url"], key)
        rel = _save(pid, "panels", f"{cid}-{n}-{item['attempt']}.png", png)
        capfile = ""
        if cfg["captions"] and p.get("caption"):
            capfile = _save(pid, "panels", f"{cid}-{n}-{item['attempt']}-cap.png", with_caption(png, p["caption"]))
        media.update(item["id"], status="done", file=rel)
    except Exception as ex:  # noqa: BLE001
        media.update(item["id"], status="failed", meta={"error": str(ex)[:300]})
        raise
    ch = store.chapter(cid)
    for x in ch["panels"]:
        if x["n"] == n:
            x.update(file=rel, capfile=capfile, media_id=item["id"], hash=panel_hash(x, ents, cfg), old=False)
    store.update_chapter(cid, panels=ch["panels"])
    return item


async def paint_chapter(pid: str, cid: str, backend, s: dict, key: str, progress=None, cancel=lambda: False, only: list[int] | None = None, send=None) -> str:
    """Plan the pictures when the chapter has none, paint the reference paintings that are missing or old, then the panels (all, or `only` these numbers)."""
    progress = progress or (lambda *a: None)
    cfg = store.project(pid)["settings"]
    ch = store.chapter(cid)
    if not ch["panels"] or (only is None and any(p.get("old") for p in ch["panels"])):
        progress(0, 1, "planning the pictures")
        panels = await plan_panels(pid, cid, backend, s)
        store.update_chapter(cid, panels=panels)
        ch = store.chapter(cid)
    ents = {e["name"]: e for e in store.entities(pid)}
    need: list[dict] = []
    for p in ch["panels"]:
        for nm in [*p["who"][:2], p["place"]]:
            e = ents.get(nm)
            if e and e not in need and (not latest_ref(pid, e["id"]) or ref_is_old(pid, e, cfg)):
                need.append(e)
    todo = [p["n"] for p in ch["panels"] if only is None or p["n"] in only]
    total = len(need) + len(todo)
    done, failed = 0, 0
    for e in need:
        if cancel():
            raise Stopped()
        progress(done, total, f"painting {e['name']}")
        try:
            await paint_ref(pid, e, cfg, s, key, send)
        except Exception:  # noqa: BLE001 - panels can still be drawn from the text
            failed += 1
        done += 1
    for n in todo:
        if cancel():
            raise Stopped()
        progress(done, total, f"painting picture {n} of {len(ch['panels'])}")
        try:
            await paint_panel(pid, cid, n, cfg, s, key, send)
        except Exception:  # noqa: BLE001
            failed += 1
        done += 1
    progress(total, total, "pictures done")
    return f"{len(todo)} pictures painted" + (f"; {failed} failed, try again" if failed else "")


def mark_old(pid: str, cid: str | None = None) -> None:
    """Panels whose inputs changed since they were drawn (the look of someone in them, the picture plan, style or model) are flagged `old`."""
    cfg = store.project(pid)["settings"]
    ents = {e["name"]: e for e in store.entities(pid)}
    for c in ([store.chapter(cid)] if cid else store.chapters(pid)):
        changed = False
        for p in c["panels"]:
            if p.get("file") and p.get("hash") and p["hash"] != panel_hash(p, ents, cfg) and not p.get("old"):
                p["old"], changed = True, True
        if changed:
            store.update_chapter(c["id"], panels=c["panels"])
