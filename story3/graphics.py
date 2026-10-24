"""Batch H: built graphics. A scene whose visual is a chart, document, screen, map or diagram (`NEEDS_ASSET`) cannot be drawn truthfully by an image
model, so a card is built by code (Pillow) from the numbers and dates in the story's own facts. Rules that never bend:

- a number goes on a card only if it appears in the story's facts (checked against `intake.facts_text`); an unverified number is left out and said so;
- a line or bar chart needs every point from the facts (three or more labelled numbers); with fewer, the scene gets a stat card or a comparison and the
  screen says why; nothing is ever estimated, smoothed or invented;
- text is English (Latin letters); colours come from the plan's visual style.

Output is a 1920x1080 still plus an animation hint for the assembly batch (count up, line draw, grow, reveal in order, fade in). A graphic is stored like a
picture (`kind graphic`, one approved per scene) and is stale when the scene, the facts or the style change."""
import hashlib
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from story import db
from story2 import imgprompts, intake, planner, storyboard, store as plan_store, styles
from story2.scene_schemas import NEEDS_ASSET

from . import store
from .voice import MediaError

KIND = "graphic"
SIZE = (1920, 1080)
FONTS = {"regular": ["segoeui.ttf", "arial.ttf"], "bold": ["segoeuib.ttf", "arialbd.ttf"], "semi": ["seguisb.ttf", "segoeuib.ttf", "arialbd.ttf"]}
COLOURS = {                                                                      # background, panel, text, muted, accent, second accent
    "gta": {"bg": (14, 18, 34), "bg2": (30, 22, 52), "panel": (28, 34, 60), "text": (248, 246, 240), "muted": (160, 170, 200), "accent": (255, 176, 40), "accent2": (40, 190, 210)},
    "noir": {"bg": (8, 10, 18), "bg2": (20, 22, 36), "panel": (24, 28, 44), "text": (240, 236, 226), "muted": (150, 150, 160), "accent": (226, 168, 52), "accent2": (200, 60, 50)},
    "concept": {"bg": (14, 26, 32), "bg2": (30, 44, 50), "panel": (30, 46, 54), "text": (240, 236, 224), "muted": (150, 170, 172), "accent": (232, 172, 84), "accent2": (84, 176, 170)},
}
NUM = re.compile(r"(?<![\w.])([₹$£€]?)(\d[\d,]*(?:\.\d+)?)\s?(%|percent|per cent|crore|lakh|million|billion|bn|k)?(?![\w])", re.I)
YEAR_LABEL = re.compile(r"^(?:\d{4}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*(?:\s+\d{1,4})?|q[1-4]\s*\d{2,4}|day \d+|week \d+|\d{1,2}:\d{2}\s?(?:am|pm)?)$", re.I)
STOP = {"the", "a", "an", "of", "and", "to", "in", "on", "at", "for", "was", "were", "is", "it", "its", "his", "her", "their", "that", "this", "with", "by", "from", "as", "had", "has"}
ANIM = {"stat": "count_up", "compare": "count_up", "bar": "grow", "line": "line_draw", "timeline": "reveal_in_order", "text": "fade_in"}


def _s(x) -> str:
    return imgprompts._s(x)


# ── facts ───────────────────────────────────────────────────────────────────

def _digits(tok: str) -> str:
    return tok.replace(",", "").rstrip(".")


def figures(line: str) -> list[dict]:
    """Numbers in one line of text: the display text (with its sign or unit), the digits, and the line without it (the label)."""
    out = []
    for m in NUM.finditer(line):
        cur, num, unit = m.group(1), m.group(2), (m.group(3) or "")
        shown = f"{cur}{num}" + (("" if unit == "%" else " ") + unit.replace("per cent", "percent") if unit else "")
        label = (line[:m.start()] + " " + line[m.end():]).strip(" ,;:-–—()[]\"'")
        label = re.sub(r"\s+", " ", label)
        out.append({"shown": shown.strip(), "digits": _digits(num), "value": float(_digits(num) or 0), "label": label, "line": line})
    return out


def pick(line: str) -> dict | None:
    """The one figure a line is about. A number with a unit or currency wins ("fell 17%"); in "2011: 150" the year is the label and 150 the value."""
    figs = figures(line)
    if not figs:
        return None
    with_unit = [f for f in figs if re.search(r"[%₹$£€]|percent|crore|lakh|million|billion|bn|k", f["shown"], re.I)]
    if with_unit:
        return with_unit[0]
    if len(figs) > 1 and re.fullmatch(r"\d{4}", figs[0]["digits"]):
        last = figs[-1]
        return {**last, "label": figs[0]["shown"]}
    return figs[0]


def verified(fig: dict, known: set[str]) -> bool:
    """The number must be one the facts state, compared whole (17 is not found inside 2017)."""
    return fig["digits"] in known


def scene_lines(scene: dict) -> list[str]:
    d = scene["data"]
    lines = [_s(x) for x in (d.get("facts") or {}).get("fixed", []) if _s(x)]
    lines += [_s(t.get("text")) for t in d.get("text_on_screen") or [] if _s(t.get("text"))]
    return list(dict.fromkeys(lines))


def short_label(label: str, n: int = 6) -> str:
    w = label.split()
    return " ".join(w[:n]) + ("…" if len(w) > n else "")


def _words(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", t.lower()) if w not in STOP}


def timeline_events(scene: dict, pub: dict) -> list[dict]:
    """Events from the story's chronology that have a stated date and share words with the scene, in the story's order."""
    d = scene["data"]
    mine = _words(" ".join([_s(d.get("subject")), _s(d.get("action")), *scene_lines(scene), *[_s(x) for x in (d.get("facts") or {}).get("fixed", [])]]))
    out = []
    for e in pub.get("chronology", []):
        when, what = _s(e.get("when")), _s(e.get("what"))
        if when and what and len(_words(what) & mine) >= 1:
            out.append({"when": when, "what": what})
    return out


def facts_ctx(plan: dict) -> dict:
    story = planner._story_for(plan)
    text = intake.facts_text(story["public"])
    return {"text": text, "lower": text.lower(), "known": {x.replace(",", "") for x in storyboard.fact_numbers(text)}, "pub": story["public"]}


# ── choosing what to build ──────────────────────────────────────────────────

def spec_for(scene: dict, ctx: dict) -> dict:
    """Decide the template and the content from the facts. Returns {template, items/events/text, dropped, fallback, wanted}."""
    d = scene["data"]
    vt = d.get("visual_type")
    wanted = {"data_chart": "a chart", "map_timeline": "a timeline or map", "document_archival": "a document", "screen_interface": "a screen", "diagram": "a diagram"}.get(vt, "a graphic")
    figs, dropped = [], []
    for line in scene_lines(scene):
        f = pick(line)
        if not f:
            continue
        bad = [x["shown"] for x in [f, *figures(f["label"])] if not verified(x, ctx["known"])]
        if bad:
            dropped.append(f"{bad[0]} is not in the story's facts, so it is left out")
        else:
            figs.append(f)
    seen, uniq = set(), []
    for f in figs:                                                        # the same number from two lines is one number
        k = (f["digits"], f["label"].lower())
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    figs = uniq
    labelled = [f for f in figs if f["label"]]
    events = timeline_events(scene, ctx["pub"])
    series_ok = len(labelled) >= 3 and len({f["label"].lower() for f in labelled}) == len(labelled)
    base = {"wanted": wanted, "dropped": dropped, "fallback": ""}
    order = (["timeline", "series", "compare", "stat"] if vt == "map_timeline" else ["series", "compare", "stat", "timeline"])
    for t in order:
        if t == "timeline" and len(events) >= 2:
            ev = events[:6]
            return {**base, "template": "timeline", "events": ev}
        if t == "series" and series_ok:
            pts = [{"label": short_label(f["label"], 3), "shown": f["shown"], "value": f["value"]} for f in labelled[:8]]
            dated = all(YEAR_LABEL.match(p["label"]) for p in pts)
            return {**base, "template": "line" if dated and vt == "data_chart" else "bar", "points": pts}
        if t == "compare" and len(figs) >= 2:
            a, b = figs[0], figs[1]
            return {**base, "template": "compare", "items": [{"label": short_label(x["label"], 5) or "", "shown": x["shown"], "value": x["value"]} for x in (a, b)]}
        if t == "stat" and figs:
            f = figs[0]
            return {**base, "template": "stat", "items": [{"label": short_label(f["label"], 9), "shown": f["shown"], "value": f["value"]}]}
    texts = []
    for t in d.get("text_on_screen") or []:
        txt = _s(t.get("text"))
        if txt and imgprompts.latin_only(txt) and len(txt.split()) <= 8:
            texts.append(txt)
    title = texts[0] if texts else short_label(_s(d.get("subject")), 8)
    return {**base, "template": "text", "title": title}


def explain(spec: dict, scene: dict) -> str:
    """Why the card is not what the scene wanted, in plain words. Empty when it is."""
    t, w, vt = spec["template"], spec["wanted"], scene["data"].get("visual_type")
    if vt == "data_chart" and t not in ("line", "bar"):
        return {"stat": "a chart was wanted but the facts give only one number, so this is a stat card", "compare": "a chart was wanted but the facts give two numbers, so this compares them",
                "timeline": "a chart was wanted but the facts give dates, not a series of numbers, so this is a timeline", "text": "a chart was wanted but the facts give no number for it"}.get(t, "")
    if t == "text" and vt in NEEDS_ASSET:
        return f"{w} was wanted but the facts give no verified number or dated event for this scene, so this is a title card"
    if vt == "map_timeline" and t != "timeline":
        return "a timeline was wanted but fewer than two dated events match this scene"
    return ""


def spec_hash(spec: dict, plan: dict) -> str:
    key = repr(sorted((k, v) for k, v in spec.items() if k not in ("wanted",))) + styles.style_id(plan["settings"])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


# ── drawing ─────────────────────────────────────────────────────────────────

_FONT_CACHE: dict = {}


def font(kind: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    k = (kind, size)
    if k not in _FONT_CACHE:
        for name in FONTS[kind]:
            for root in (Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/dejavu")):
                f = root / name
                if f.is_file():
                    _FONT_CACHE[k] = ImageFont.truetype(str(f), size)
                    break
            if k in _FONT_CACHE:
                break
        else:
            _FONT_CACHE[k] = ImageFont.load_default()
    return _FONT_CACHE[k]


def text_w(draw: ImageDraw.ImageDraw, t: str, f) -> int:
    b = draw.textbbox((0, 0), t, font=f)
    return b[2] - b[0]


def wrap(draw: ImageDraw.ImageDraw, t: str, f, max_w: int) -> list[str]:
    lines, cur = [], ""
    for w in t.split():
        trial = (cur + " " + w).strip()
        if text_w(draw, trial, f) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    return lines + ([cur] if cur else [])


def fitted(draw, t: str, kind: str, max_w: int, max_h: int, start: int, floor: int = 22, lines_max: int = 4):
    """Largest font size at which the text, wrapped, fits the box. Returns (font, lines, line_height)."""
    for size in range(start, floor - 1, -2):
        f = font(kind, size)
        ls = wrap(draw, t, f, max_w)
        lh = int(size * 1.22)
        if len(ls) <= lines_max and len(ls) * lh <= max_h and all(text_w(draw, x, f) <= max_w for x in ls):
            return f, ls, lh
    f = font(kind, floor)
    return f, wrap(draw, t, f, max_w)[:lines_max], int(floor * 1.22)


def centred(draw, lines, f, lh, cx, y, fill):
    for ln in lines:
        draw.text((cx - text_w(draw, ln, f) / 2, y), ln, font=f, fill=fill)
        y += lh
    return y


def canvas(style: str) -> tuple[Image.Image, ImageDraw.ImageDraw, dict]:
    c = COLOURS[style]
    im = Image.new("RGB", SIZE, c["bg"])
    px = ImageDraw.Draw(im)
    for y in range(SIZE[1]):                                             # a soft vertical gradient so the card is not flat
        k = y / SIZE[1]
        px.line([(0, y), (SIZE[0], y)], fill=tuple(int(c["bg"][i] * (1 - k) + c["bg2"][i] * k) for i in range(3)))
    px.rectangle((0, 0, 14, SIZE[1]), fill=c["accent"])
    return im, px, c


def draw_stat(spec: dict, style: str) -> Image.Image:
    im, d, c = canvas(style)
    it = spec["items"][0]
    f, ls, lh = fitted(d, it["shown"], "bold", 1500, 360, 300, 90, 1)
    y = 250
    y = centred(d, ls, f, lh, SIZE[0] / 2, y, c["accent"])
    d.rectangle((SIZE[0] / 2 - 120, y + 20, SIZE[0] / 2 + 120, y + 28), fill=c["accent2"])
    if it["label"]:
        f2, l2, h2 = fitted(d, it["label"], "semi", 1400, 260, 72, 30, 3)
        centred(d, l2, f2, h2, SIZE[0] / 2, y + 70, c["text"])
    return im


def draw_compare(spec: dict, style: str) -> Image.Image:
    im, d, c = canvas(style)
    a, b = spec["items"]
    cols = [(SIZE[0] * 0.27, a, c["accent"]), (SIZE[0] * 0.73, b, c["accent2"])]
    top = 190
    vals = [max(a["value"], 0), max(b["value"], 0)]
    top_v = max(vals) or 1
    for cx, it, col in cols:
        f, ls, lh = fitted(d, it["shown"], "bold", 640, 220, 190, 70, 1)
        centred(d, ls, f, lh, cx, top, col)
        if it["label"]:
            f2, l2, h2 = fitted(d, it["label"], "semi", 700, 170, 54, 26, 3)
            centred(d, l2, f2, h2, cx, top + 250, c["text"])
        h = int(360 * (max(it["value"], 0) / top_v)) if vals[0] != vals[1] or top_v else 360          # bars in proportion to the numbers (same scale for both)
        d.rectangle((cx - 110, 980 - h, cx + 110, 980), fill=col)
    f = font("bold", 80)
    d.text((SIZE[0] / 2 - text_w(d, "vs", f) / 2, 440), "vs", font=f, fill=c["muted"])
    return im


def draw_bar(spec: dict, style: str) -> Image.Image:
    im, d, c = canvas(style)
    pts = spec["points"]
    x0, x1, y0, y1 = 190, SIZE[0] - 120, 150, 880
    top = max(p["value"] for p in pts) or 1
    d.line((x0, y1, x1, y1), fill=c["muted"], width=3)
    slot = (x1 - x0) / len(pts)
    for i, p in enumerate(pts):
        h = int((y1 - y0 - 60) * p["value"] / top)
        cx = x0 + slot * (i + 0.5)
        w = min(slot * 0.6, 220)
        d.rectangle((cx - w / 2, y1 - h, cx + w / 2, y1), fill=c["accent"] if i % 2 == 0 else c["accent2"])
        f, ls, lh = fitted(d, p["shown"], "bold", int(slot - 10), 70, 54, 24, 1)
        centred(d, ls, f, lh, cx, y1 - h - lh - 8, c["text"])
        f2, l2, h2 = fitted(d, p["label"], "regular", int(slot - 16), 110, 38, 20, 2)
        centred(d, l2, f2, h2, cx, y1 + 18, c["muted"])
    return im


def draw_line(spec: dict, style: str) -> Image.Image:
    im, d, c = canvas(style)
    pts = spec["points"]
    x0, x1, y0, y1 = 220, SIZE[0] - 160, 170, 860
    lo, hi = min(0, min(p["value"] for p in pts)), max(p["value"] for p in pts)
    span = (hi - lo) or 1
    xs = [x0 + 70 + (x1 - x0 - 140) * i / max(len(pts) - 1, 1) for i in range(len(pts))]
    ys = [y1 - (y1 - y0) * (p["value"] - lo) / span for p in pts]
    d.line((x0, y1, x1, y1), fill=c["muted"], width=3)
    d.line((x0, y0, x0, y1), fill=c["muted"], width=3)
    d.line(list(zip(xs, ys)), fill=c["accent"], width=10, joint="curve")
    for (x, y), p in zip(zip(xs, ys), pts):
        d.ellipse((x - 16, y - 16, x + 16, y + 16), fill=c["accent2"], outline=c["bg"], width=4)
        f = font("bold", 48)
        d.text((x - text_w(d, p["shown"], f) / 2, y - 80), p["shown"], font=f, fill=c["text"])
        f2 = font("regular", 36)
        d.text((x - text_w(d, p["label"], f2) / 2, y1 + 20), p["label"], font=f2, fill=c["muted"])
    return im


def draw_timeline(spec: dict, style: str) -> Image.Image:
    im, d, c = canvas(style)
    ev = spec["events"]
    n = len(ev)
    x0, x1, y = 160, SIZE[0] - 160, 520
    d.line((x0, y, x1, y), fill=c["muted"], width=6)
    slot = (x1 - x0) / n
    for i, e in enumerate(ev):
        cx = x0 + slot * (i + 0.5)
        d.ellipse((cx - 22, y - 22, cx + 22, y + 22), fill=c["accent"] if i % 2 == 0 else c["accent2"], outline=c["bg"], width=5)
        fw, lw, hw = fitted(d, e["when"], "bold", int(slot - 24), 120, 56, 26, 2)
        centred(d, lw, fw, hw, cx, y - 60 - len(lw) * hw, c["accent"])
        fb, lb, hb = fitted(d, e["what"], "regular", int(slot - 30), 330, 40, 22, 6)
        centred(d, lb, fb, hb, cx, y + 56, c["text"])
    return im


def draw_text(spec: dict, style: str) -> Image.Image:
    im, d, c = canvas(style)
    f, ls, lh = fitted(d, spec["title"], "bold", 1500, 560, 130, 48, 4)
    centred(d, ls, f, lh, SIZE[0] / 2, SIZE[1] / 2 - len(ls) * lh / 2, c["text"])
    d.rectangle((SIZE[0] / 2 - 160, SIZE[1] / 2 + len(ls) * lh / 2 + 24, SIZE[0] / 2 + 160, SIZE[1] / 2 + len(ls) * lh / 2 + 32), fill=c["accent"])
    return im


DRAW = {"stat": draw_stat, "compare": draw_compare, "bar": draw_bar, "line": draw_line, "timeline": draw_timeline, "text": draw_text}


def numbers_on_card(spec: dict) -> list[str]:
    """Every number the card shows (digits only), for the check that each one is in the facts."""
    t = spec["template"]
    shown = [x["shown"] for x in spec.get("items", [])] + [x["shown"] for x in spec.get("points", [])]
    shown += [x["label"] for x in spec.get("items", []) + spec.get("points", [])]
    if t == "timeline":
        shown += [e["when"] + " " + e["what"] for e in spec["events"]]
    return [_digits(m.group(2)) for s in shown for m in NUM.finditer(s)]


# ── actions ─────────────────────────────────────────────────────────────────

def graphic_scenes(plan_id: str) -> list[dict]:
    return [sc for sc in sorted(storyboard.get_scenes(plan_id), key=lambda x: (x["start_s"], x["seq"])) if sc["data"].get("visual_type") in NEEDS_ASSET]


def build(plan_id: str, scene_ids: list[str] | None = None, force: bool = False) -> dict:
    """Build a card for every scene that needs one (or the ones named). A scene whose card is already current is left alone unless forced."""
    plan = planner.get_plan(plan_id)
    scenes = [sc for sc in graphic_scenes(plan_id) if not scene_ids or sc["id"] in scene_ids]
    if not storyboard.get_scenes(plan_id):
        raise MediaError("design the storyboard first")
    ctx = facts_ctx(plan)
    style = styles.style_id(plan["settings"])
    out_dir = store.media_dir(plan_id, "graphics")
    made, kept = 0, 0
    for sc in scenes:
        spec = spec_for(sc, ctx)
        h = spec_hash(spec, plan)
        have = [i for i in store.items(plan_id, KIND, sc["id"]) if i["status"] == "done" and i["meta"].get("spec_hash") == h]
        if have and not force:
            kept += 1
            continue
        im = DRAW[spec["template"]](spec, style)
        it = store.add(plan_id, KIND, sc["id"], 0, "running", {})
        name = f"graphics/{sc['id']}-a{it['attempt']}.png"
        im.save(out_dir / f"{sc['id']}-a{it['attempt']}.png")
        fb = explain(spec, sc)
        store.update(it["id"], status="done", file=name, meta={"template": spec["template"], "spec": {k: v for k, v in spec.items() if k not in ("dropped", "wanted", "fallback")},
                                                               "spec_hash": h, "style": style, "fallback": fb, "dropped": spec["dropped"], "wanted": spec["wanted"],
                                                               "numbers": numbers_on_card(spec), "animation": ANIM[spec["template"]], "width": SIZE[0], "height": SIZE[1]})
        made += 1
    plan_store.log(plan_id, "graphics", {"made": made, "kept": kept})
    return {"made": made, "kept": kept, "state": state(plan_id)}


def approve(item_id: str, on: bool = True) -> dict:
    it = store.get(item_id)
    if not it or it["kind"] != KIND:
        raise MediaError("not a graphic")
    if on and it["status"] != "done":
        raise MediaError("only a finished graphic can be approved")
    store.approve(item_id, on)
    plan_store.log(it["plan_id"], "graphic_approved" if on else "graphic_unapproved", {"scene": it["key"], "item": item_id})
    return state(it["plan_id"])


def approve_all(plan_id: str, include_fallbacks: bool = False) -> dict:
    """Approve the current graphic of every scene still open. Cards that are not what the scene wanted (a fallback) are left for a person unless asked for."""
    st = state(plan_id)
    n, left = 0, []
    for r in st["scenes"]:
        if r["approved"] or not r["current_item"]:
            continue
        if r["fallback"] and not include_fallbacks:
            left.append({"scene": r["id"], "why": r["fallback"]})
            continue
        store.approve(r["current_item"]["id"], True)
        n += 1
    plan_store.log(plan_id, "graphics_approved", {"approved": n})
    return {"approved": n, "left": left, "state": state(plan_id)}


def state(plan_id: str) -> dict:
    plan = planner.get_plan(plan_id)
    rows = []
    try:
        ctx = facts_ctx(plan)
    except Exception:  # noqa: BLE001 - the screen still lists the scenes
        ctx = None
    for sc in graphic_scenes(plan_id):
        spec = spec_for(sc, ctx) if ctx else None
        h = spec_hash(spec, plan) if spec else ""
        items = store.items(plan_id, KIND, sc["id"])
        cur = [i for i in items if i["status"] == "done" and i["meta"].get("spec_hash") == h]
        ok = next((i for i in items if i["approved"] and i["status"] == "done"), None)
        item = cur[-1] if cur else None

        def view(i):
            return {"id": i["id"], "attempt": i["attempt"], "url": f"/api/media/file/{plan_id}/{i['file']}", "approved": i["approved"], "template": i["meta"].get("template"),
                    "current": i["meta"].get("spec_hash") == h, "animation": i["meta"].get("animation"), "numbers": i["meta"].get("numbers", [])}
        rows.append({"id": sc["id"], "start_s": sc["start_s"], "duration_s": sc["duration_s"], "subject": _s(sc["data"].get("subject")), "visual_type": sc["data"].get("visual_type"),
                     "wanted": spec["wanted"] if spec else "", "template": spec["template"] if spec else "", "fallback": explain(spec, sc) if spec else "",
                     "dropped": spec["dropped"] if spec else [], "approved": ok["id"] if ok and ok["meta"].get("spec_hash") == h else None,
                     "current_item": view(item) if item else None, "items": [view(i) for i in items if i["status"] == "done"],
                     "status": "approved" if ok and ok["meta"].get("spec_hash") == h else "needs_choice" if item else "needs_build"})
    total = len(rows)
    approved = sum(1 for r in rows if r["status"] == "approved")
    return {"total": total, "approved": approved, "needs_build": sum(1 for r in rows if r["status"] == "needs_build"), "needs_choice": sum(1 for r in rows if r["status"] == "needs_choice"),
            "fallbacks": sum(1 for r in rows if r["fallback"]), "done": bool(total) and approved == total, "scenes": rows}
