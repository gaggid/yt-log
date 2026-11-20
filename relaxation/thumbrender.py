"""The words on a thumbnail, laid on the picture by code (never drawn by the image model, so the letters are always right).

Five layouts (side, bottom, top, badge, stack), seven fonts and six colour pairs, chosen per video (relaxation/looks.py), so the channel page is not a wall of one
design. The length of the video ("3 HOURS") is always shown, as a pill, a circle or the biggest word. JPEG under 2 MB, as the thumbnail upload requires."""
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZE = (1280, 720)
FALLBACK_FONTS = ["arialbd.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf"]
MAX_BYTES = 1_900_000
DEFAULT_SPEC = {"layout": "side", "side": "right", "font": "impact.ttf", "palette": 0, "headline": "RAIN SOUNDS", "subline": "SLEEP  ·  STUDY  ·  RELAX"}


def font(size: int, name: str = "") -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for n in ([name] if name else []) + FALLBACK_FONTS:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default()


def fit(draw: ImageDraw.ImageDraw, text: str, size: int, max_w: int, name: str = ""):
    while size > 24:
        f = font(size, name)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 4
    return font(24, name)


def wash(size, side: str, strength: int = 190, reach: float = 0.62) -> Image.Image:
    """A soft dark gradient from one edge ('left', 'right', 'top', 'bottom'), so words read on any picture."""
    w, h = size
    horiz = side in ("left", "right")
    n = w if horiz else h
    line = Image.new("L", (n, 1), 0)
    px = line.load()
    for i in range(n):
        d = i / n if side in ("left", "top") else 1 - i / n
        px[i, 0] = int(max(0.0, 1 - d / reach) ** 1.4 * strength)
    if horiz:
        return line.resize((w, h))
    return line.rotate(-90, expand=True).resize((w, h))             # a column of n values, stretched across


def lines(draw, text: str, size: int, max_w: int, name: str):
    """The text on one line when it fits at `size`, else balanced over two lines at the largest size that fits. [(text, font, height)]"""
    words = text.split()
    cands = [[text]] + ([[" ".join(words[:k]), " ".join(words[k:])] for k in range(1, len(words))] if len(words) > 1 else [])
    best = None
    for c in cands:
        s = size
        while s > 28:
            f = font(s, name)
            if all(draw.textlength(x, font=f) <= max_w for x in c):
                break
            s -= 4
        if best is None or s > best[0]:
            best = (s, c)
        if s == size:
            break
    s, c = best
    f = font(s, name)
    return [(x, f, draw.textbbox((0, 0), x, font=f)[3] - draw.textbbox((0, 0), x, font=f)[1]) for x in c]


def text(d, xy, s, f, fill, shadow=3):
    x, y = xy
    d.text((x + shadow, y + shadow), s, font=f, fill=(0, 0, 0))             # a hard shadow for contrast
    d.text((x, y), s, font=f, fill=fill)


def pill(d, xy, s, f, bg, fg=(20, 20, 28), pad=(22, 10)):
    bb = d.textbbox((0, 0), s, font=f)
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    x, y = xy
    d.rounded_rectangle([x, y, x + w + 2 * pad[0], y + h + 2 * pad[1]], radius=(h + 2 * pad[1]) // 2, fill=bg)
    d.text((x + pad[0] - bb[0], y + pad[1] - bb[1]), s, font=f, fill=fg)
    return w + 2 * pad[0], h + 2 * pad[1]


def render(scene_path: Path, length_words: str, spec: dict | None = None) -> bytes:
    """The thumbnail as JPEG bytes. `spec`: layout, side (where the subject of the picture is), font, palette, headline, subline."""
    from . import looks
    sp = {**DEFAULT_SPEC, **{k: v for k, v in (spec or {}).items() if v not in (None, "")}}
    im = Image.open(scene_path).convert("RGB")
    w, h = im.size
    k = max(SIZE[0] / w, SIZE[1] / h)                         # cover
    im = im.resize((round(w * k), round(h * k)), Image.LANCZOS)
    left, top = (im.width - SIZE[0]) // 2, (im.height - SIZE[1]) // 2
    im = im.crop((left, top, left + SIZE[0], top + SIZE[1]))
    main, accent = looks.PALETTES[int(sp.get("palette") or 0) % len(looks.PALETTES)]
    name = sp["font"]
    layout = sp["layout"] if sp["layout"] in looks.LAYOUTS else "side"
    text_side = "left" if sp.get("side", "right") == "right" else "right"          # the words go to the side the subject is not on
    if sp.get("side") == "centre" and layout in ("side", "stack", "badge"):
        layout = "bottom"
    head, sub = sp["headline"], sp.get("subline", "")
    W, H = SIZE

    def lay(side, strength=190, reach=0.62):
        nonlocal im
        im = Image.composite(Image.new("RGB", SIZE, (6, 10, 18)), im, wash(SIZE, side, strength, reach))

    if layout == "side":
        lay(text_side)
        d = ImageDraw.Draw(im)
        x0, max_w = (56 if text_side == "left" else int(W * 0.48)), int(W * 0.46)
        blocks = lines(d, head, 118, max_w, name)
        pf = font(64, name)
        pill_h = 96
        sf = fit(d, sub, 40, max_w, name) if sub else None
        total = sum(b[2] for b in blocks) + 14 * len(blocks) + pill_h + (60 if sub else 0)
        y = (H - total) // 2
        for s, f, hh in blocks:
            text(d, (x0, y), s, f, main)
            y += hh + 14
        y += 10
        pill(d, (x0, y), length_words, pf, accent)
        if sf:
            text(d, (x0, y + pill_h + 14), sub, sf, (214, 226, 240), 2)
    elif layout == "bottom":
        lay("bottom", 215, 0.55)
        d = ImageDraw.Draw(im)
        blocks = lines(d, head, 112, int(W * 0.86), name)
        sf = font(44, name)
        total = sum(b[2] for b in blocks) + 10 * len(blocks) + (60 if sub else 0)
        y = H - total - 44
        for s, f, hh in blocks:
            text(d, ((W - d.textlength(s, font=f)) / 2, y), s, f, main)
            y += hh + 10
        if sub:
            text(d, ((W - d.textlength(sub, font=sf)) / 2, y + 6), sub, sf, accent, 2)
        pill(d, (40, 36), length_words, font(46, name), accent)
    elif layout == "top":
        lay("top", 205, 0.5)
        d = ImageDraw.Draw(im)
        blocks = lines(d, head, 104, int(W * 0.9), name)
        y = 34
        for s, f, hh in blocks:
            text(d, (48, y), s, f, main)
            y += hh + 8
        if sub:
            text(d, (52, y + 12), sub, font(40, name), accent, 2)
        pf = font(60, name)
        bw = d.textlength(length_words, font=pf) + 48
        pill(d, (W - bw - 40, H - 112), length_words, pf, accent)
    elif layout == "badge":
        lay(text_side, 120, 0.5)
        d = ImageDraw.Draw(im)
        x0, max_w = (48 if text_side == "left" else int(W * 0.5)), int(W * 0.42)
        blocks = lines(d, head, 84, max_w, name)
        y = 52
        for s, f, hh in blocks:
            text(d, (x0, y), s, f, main)
            y += hh + 10
        if sub:
            text(d, (x0 + 3, y + 14), sub, font(36, name), accent, 2)
        r = 120
        cx = (r + 48) if text_side == "left" else (W - r - 48)
        cy = H - r - 40
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=accent)
        num, unit = (length_words.split() + [""])[:2]
        nf, bf = font(110, name), font(50, name)
        d.text((cx - d.textlength(num, font=nf) / 2, cy - 88), num, font=nf, fill=(20, 20, 28))
        d.text((cx - d.textlength(unit, font=bf) / 2, cy + 22), unit, font=bf, fill=(20, 20, 28))
    else:                                                      # stack: the length is the biggest word
        lay(text_side, 200, 0.6)
        d = ImageDraw.Draw(im)
        x0, max_w = (56 if text_side == "left" else int(W * 0.5)), int(W * 0.42)
        num, unit = (length_words.split() + [""])[:2]
        nf, uf = font(220, name), font(70, name)
        nb = d.textbbox((0, 0), num, font=nf)
        hl = lines(d, head, 62, max_w, name)
        total = (nb[3] - nb[1]) + 14 + 90 + sum(b[2] + 8 for b in hl)
        y = max(30, (H - total) // 2)
        text(d, (x0 - nb[0], y - nb[1]), num, nf, accent, 4)
        y += nb[3] - nb[1] + 14
        text(d, (x0, y), unit, uf, main)
        y += 90
        for s, f, hh in hl:
            text(d, (x0, y), s, f, (230, 238, 248), 2)
            y += hh + 8
    for q in (90, 84, 78, 70):
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=q, optimize=True)
        if buf.tell() <= MAX_BYTES:
            break
    return buf.getvalue()


def plain(picture_path: Path) -> bytes:
    """The picture as the thumbnail JPEG, with nothing laid on it: the image model drew the big words into it (relaxation/thumbcheck.py read them back)."""
    im = Image.open(picture_path).convert("RGB").resize(SIZE, Image.LANCZOS)
    for q in (92, 88, 84, 78, 70):
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=q, optimize=True)
        if buf.tell() <= MAX_BYTES:
            break
    return buf.getvalue()
