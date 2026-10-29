"""The evidence-card library (docs/TASKS_quality_overhaul.md tasks 3.15 and 3.9; audit 14.2 and 14.3). The image model never draws a chat, an SMS, a call list, an FIR, a news
cutting, an ID card, a ledger, a phone screen or a map: this module builds them as cards from the story's own details (the Material Pack and the facts), in the film's palette.
Every word and every number on a card comes from those details; a number that is not among them is left off. Nothing on a card names an app, a bank or a brand.

`plan` turns a few event scenes into card scenes (visual type `screen_interface`, `document_archival` or `map_timeline`, with `data.card`), `spec` writes what the card shows, and
`DRAW` draws it. `story3/graphics.py` uses `spec`/`DRAW` for any scene that has `data.card`, so approval, the video and the animation hints work as for charts."""
import re

from PIL import Image, ImageDraw

from story import db
from story2 import events as events_mod, material, planner, storyboard, store as plan_store

from . import graphics as G

TYPES = {
    "chat": ("screen_interface", "reveal_in_order"), "sms": ("screen_interface", "fade_in"), "call_log": ("screen_interface", "reveal_in_order"), "phone_pov": ("screen_interface", "fade_in"),
    "fir": ("document_archival", "reveal_in_order"), "news_clip": ("document_archival", "fade_in"), "id_card": ("document_archival", "fade_in"), "ledger": ("document_archival", "reveal_in_order"),
    "route_map": ("map_timeline", "line_draw"), "counter": ("data_chart", "count_up"), "year_card": ("diagram", "fade_in"),
}
BRANDS = re.compile(r"whatsapp|telegram|facebook|instagram|google|paytm|phonepe|gpay|sbi|hdfc|icici|axis bank|amazon|flipkart|truecaller|youtube|twitter|signal|upi", re.I)
# which words in an event point to which card
HINTS = (("chat", r"chat|message thread|texts? him|texts? her|group chat|conversation"), ("sms", r"sms|text message|bank alert|alert|otp|debit"), ("call_log", r"call log|missed call|calls? from|phone calls|rang|ringing"),
         ("fir", r"fir\b|police complaint|complaint|charge ?sheet|case file|police report"), ("news_clip", r"newspaper|headline|news report|press|clipping"), ("id_card", r"id card|identity|aadhaar|passport|licence|license|photo id"),
         ("ledger", r"ledger|accounts? book|bank statement|transactions?|payments? list|receipts?"), ("phone_pov", r"phone|screen|mobile"), ("route_map", r"route|journey|travelled|fled|moved from|train from|bus from"))
CITIES = {"delhi": (28.6, 77.2), "mumbai": (19.1, 72.9), "kolkata": (22.6, 88.4), "chennai": (13.1, 80.3), "bengaluru": (13.0, 77.6), "bangalore": (13.0, 77.6), "hyderabad": (17.4, 78.5),
          "ahmedabad": (23.0, 72.6), "surat": (21.2, 72.8), "pune": (18.5, 73.9), "jaipur": (26.9, 75.8), "lucknow": (26.8, 80.9), "kanpur": (26.4, 80.3), "patna": (25.6, 85.1),
          "bhopal": (23.3, 77.4), "indore": (22.7, 75.9), "nagpur": (21.1, 79.1), "ludhiana": (30.9, 75.9), "amritsar": (31.6, 74.9), "chandigarh": (30.7, 76.8), "jalandhar": (31.3, 75.6),
          "varanasi": (25.3, 83.0), "ranchi": (23.3, 85.3), "guwahati": (26.1, 91.7), "bhubaneswar": (20.3, 85.8), "kochi": (9.9, 76.3), "thiruvananthapuram": (8.5, 77.0), "goa": (15.5, 73.8),
          "panaji": (15.5, 73.8), "visakhapatnam": (17.7, 83.2), "coimbatore": (11.0, 77.0), "madurai": (9.9, 78.1), "jamtara": (24.0, 86.8), "sultanpur": (26.3, 82.1), "dharavi": (19.04, 72.85),
          "agra": (27.2, 78.0), "meerut": (29.0, 77.7), "gurugram": (28.5, 77.0), "gurgaon": (28.5, 77.0), "noida": (28.5, 77.4), "srinagar": (34.1, 74.8), "shimla": (31.1, 77.2),
          "dehradun": (30.3, 78.0), "raipur": (21.3, 81.6), "vadodara": (22.3, 73.2), "rajkot": (22.3, 70.8), "nashik": (20.0, 73.8), "thane": (19.2, 73.0), "jodhpur": (26.3, 73.0),
          "udaipur": (24.6, 73.7), "kota": (25.2, 75.8), "allahabad": (25.4, 81.8), "prayagraj": (25.4, 81.8), "gorakhpur": (26.8, 83.4), "bareilly": (28.4, 79.4), "mysuru": (12.3, 76.6)}
# a coarse outline of India as (longitude, latitude); a schematic for a route card, not a survey
OUTLINE = [(74.3, 34.8), (77.8, 35.5), (79.5, 34.0), (78.8, 32.4), (80.0, 30.5), (80.2, 28.9), (84.2, 27.4), (88.0, 26.5), (88.7, 27.4), (89.0, 26.5), (92.0, 26.8), (95.2, 27.9),
           (97.3, 28.3), (96.0, 26.5), (94.5, 24.2), (93.4, 22.9), (92.3, 23.6), (91.5, 24.1), (90.4, 25.1), (89.0, 25.3), (88.3, 24.5), (88.9, 22.8), (89.0, 21.7), (87.0, 21.5),
           (86.7, 20.2), (85.0, 19.3), (82.3, 16.5), (80.2, 15.5), (80.2, 13.4), (79.9, 11.5), (79.3, 10.3), (78.2, 8.9), (77.5, 8.1), (76.5, 8.8), (75.3, 11.7), (74.5, 14.0),
           (73.4, 16.5), (72.8, 19.0), (72.8, 21.0), (72.5, 22.3), (70.5, 20.9), (69.0, 22.3), (68.2, 23.7), (69.5, 24.3), (70.5, 24.2), (70.0, 26.5), (71.0, 27.8), (72.5, 29.3),
           (74.0, 30.0), (74.6, 31.5), (74.0, 32.8)]


# ── what a card says ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def short(text: str, n: int = 10) -> str:
    words = [w for w in re.sub(r"\s+", " ", text or "").strip().split(" ") if w]
    cut = " ".join(words[:n]).rstrip(",;:- ")
    return cut + ("…" if len(words) > n else "")


def pick_type(ev: dict) -> str:
    """The card an event calls for, or "" when it needs none. The event's kind decides first, then the words of what happens."""
    text = f"{ev.get('key_object', '')} {ev.get('doing', '')} {ev.get('where', '')}".lower()
    for ct, rx in HINTS:
        if re.search(rx, text):
            return ct
    return {"document": "fir", "map": "route_map", "phone": "phone_pov"}.get(str(ev.get("kind", "")), "")


def _items(plan: dict, card: dict) -> list[dict]:
    pk = material.pack(plan) if material.has(plan) else {"items": []}
    by = {i["id"]: i for i in pk["items"]}
    ids = card.get("items") or []
    got = [by[i] for i in ids if i in by]
    return got or [i for i in pk["items"] if i.get("kind") in ("clue", "number", "object")][:4]


def _clean(text: str) -> str:
    return BRANDS.sub("", text or "").strip()


def stops(plan: dict, ev: dict | None, items: list[dict]) -> list[str]:
    """Cities named by the details of the card, in the order they come in the story."""
    text = " ".join(f"{i.get('where', '')} {i.get('detail', '')}" for i in items) + " " + (f"{ev.get('where', '')} {ev.get('doing', '')}" if ev else "")
    found = [(m.start(), m.group().lower()) for m in re.finditer("|".join(sorted(map(re.escape, CITIES), key=len, reverse=True)), text.lower())]
    out = []
    for _, c in sorted(found):
        c = {"dharavi": "mumbai", "bangalore": "bengaluru", "gurgaon": "gurugram", "panaji": "goa"}.get(c, c)
        if c not in out:
            out.append(c)
    return out


def spec(scene: dict, plan: dict, ctx: dict) -> dict:
    """What the card shows, as a spec the drawing functions and the number check understand. Only details of the story (and numbers that are in them) are used."""
    card = scene["data"].get("card") or {}
    ct = card.get("type", "")
    items = _items(plan, card)
    ev = next((e for e in events_mod.of(plan) if e["id"] == card.get("event")), None)
    known = set(ctx["known"]) | {G._digits(m.group(2)) for i in items for m in G.NUM.finditer(i.get("detail", ""))}
    dropped, texts = [], []

    def ok(t: str) -> str:
        for m in G.NUM.finditer(t):
            if G._digits(m.group(2)) not in known and G._digits(m.group(2)) not in (ctx["lower"]):
                dropped.append(f"{m.group()} is not in the story's details, so the line is left out")
                return ""
        return _clean(t)
    base = {"template": ct, "wanted": ct, "dropped": dropped, "fallback": "", "card": ct}
    lines = [ok(short(i.get("detail", ""), 12)) for i in items]
    lines = [x for x in lines if x]
    if ct == "chat":
        sp = {"title": "Messages", "bubbles": [{"side": "right" if k % 2 else "left", "text": t} for k, t in enumerate(lines[:4])]}
        texts = [b["text"] for b in sp["bubbles"]]
    elif ct == "sms":
        t = lines[0] if lines else ""
        sp = {"sender": "ALERT", "text": t}
        texts = [t]
    elif ct == "call_log":
        rows = [{"who": "Unknown number" if k % 3 == 0 else "Missed call", "when": short(i.get("when", ""), 3)} for k, i in enumerate(items[:6])]
        sp = {"title": "Recent calls", "rows": rows, "mark": 0}
        texts = [r["when"] for r in rows]
    elif ct == "fir":
        sp = {"title": "FIRST INFORMATION REPORT", "lines": lines[:3], "blanks": 3}
        texts = sp["lines"]
    elif ct == "news_clip":
        year = next((m.group() for i in items for m in [re.search(r"\b(19|20)\d\d\b", f"{i.get('when', '')} {i.get('detail', '')}")] if m), "")
        sp = {"headline": short(items[0]["detail"], 9) if items else "", "year": year}
        texts = [sp["headline"], year]
    elif ct == "id_card":
        names = material.pack(plan).get("names", []) if material.has(plan) else []
        sp = {"name": (names[0]["name"] if names else "Name withheld"), "lines": lines[:3]}
        texts = [sp["name"], *sp["lines"]]
    elif ct == "ledger":
        rows = []
        for i in items:
            for f in G.figures(i.get("detail", "")):
                if G.verified(f, known):
                    rows.append({"label": short(f["label"] or i["detail"], 4), "shown": f["shown"]})
        sp = {"title": "ACCOUNT", "rows": rows[:6]}
        texts = [x["label"] + " " + x["shown"] for x in sp["rows"]]
    elif ct == "phone_pov":
        sp = {"line": lines[0] if lines else ""}
        texts = [sp["line"]]
    elif ct == "route_map":
        sp = {"stops": stops(plan, ev, items)[:6]}
        texts = []
    elif ct == "counter":
        f = next((f for i in items for f in G.figures(i.get("detail", "")) if G.verified(f, known)), None)
        sp = {"shown": f["shown"] if f else "", "label": short(f["label"], 6) if f else ""}
        texts = [sp["shown"], sp["label"]]
    elif ct == "year_card":
        sp = {"year": str(card.get("year", ""))}
        texts = [sp["year"]]
    else:
        return {**base, "template": "text", "title": short(scene["data"].get("subject", ""), 8)}
    sp["texts"] = texts
    return {**base, **sp}


# ── drawing ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _paper(style: str, tilt: bool = False) -> tuple[Image.Image, ImageDraw.ImageDraw, dict]:
    im, d, c = G.canvas(style)
    return im, d, c


def draw_chat(sp: dict, style: str) -> Image.Image:
    im, d, c = G.canvas(style)
    x0, x1, y = 560, G.SIZE[0] - 560, 120
    d.rounded_rectangle((x0 - 30, 60, x1 + 30, G.SIZE[1] - 60), 36, fill=(24, 28, 30), outline=c["muted"], width=4)
    d.rectangle((x0 - 26, 64, x1 + 26, 150), fill=(40, 54, 50))
    d.text((x0 + 20, 84), sp.get("title", "Messages"), font=G.font("bold", 40), fill=c["text"])
    y = 190
    for b in sp["bubbles"]:
        f, ls, lh = G.fitted(d, b["text"], "regular", 560, 220, 40, 26, 4)
        w = max(G.text_w(d, ln, f) for ln in ls) + 56
        h = len(ls) * lh + 40
        bx = x1 - w - 20 if b["side"] == "right" else x0 + 20
        d.rounded_rectangle((bx, y, bx + w, y + h), 28, fill=(48, 92, 74) if b["side"] == "right" else (52, 56, 60))
        for k, ln in enumerate(ls):
            d.text((bx + 28, y + 20 + k * lh), ln, font=f, fill=c["text"])
        y += h + 26
    return im


def draw_sms(sp: dict, style: str) -> Image.Image:
    im, d, c = G.canvas(style)
    x0, x1 = 360, G.SIZE[0] - 360
    d.rounded_rectangle((x0, 280, x1, 800), 30, fill=(236, 238, 234))
    d.text((x0 + 50, 320), sp.get("sender", "ALERT"), font=G.font("bold", 40), fill=(60, 80, 70))
    f, ls, lh = G.fitted(d, sp.get("text", ""), "regular", x1 - x0 - 100, 360, 56, 30, 6)
    for k, ln in enumerate(ls):
        d.text((x0 + 50, 410 + k * lh), ln, font=f, fill=(30, 34, 34))
    d.rectangle((x0 + 50, 380, x0 + 330, 386), fill=c["accent"])
    return im


def draw_call_log(sp: dict, style: str) -> Image.Image:
    im, d, c = G.canvas(style)
    x0, x1, y = 400, G.SIZE[0] - 400, 140
    d.text((x0, y), sp.get("title", "Recent calls"), font=G.font("bold", 54), fill=c["text"])
    y += 120
    for k, r in enumerate(sp["rows"]):
        hot = k == sp.get("mark", 0)
        d.rounded_rectangle((x0, y, x1, y + 100), 18, fill=(70, 38, 38) if hot else c["panel"], outline=c["accent2"] if hot else None, width=3)
        d.text((x0 + 30, y + 24), r["who"], font=G.font("semi", 42), fill=c["text"])
        d.text((x1 - 30 - G.text_w(d, r["when"], G.font("regular", 36)), y + 28), r["when"], font=G.font("regular", 36), fill=c["muted"])
        y += 124
    return im


def draw_fir(sp: dict, style: str) -> Image.Image:
    im, d, c = G.canvas(style)
    x0, x1 = 420, G.SIZE[0] - 420
    d.rectangle((x0, 80, x1, G.SIZE[1] - 80), fill=(232, 226, 208))
    d.text((x0 + 60, 120), sp.get("title", "REPORT"), font=G.font("bold", 46), fill=(40, 36, 30))
    d.rectangle((x0 + 60, 190, x1 - 60, 194), fill=(40, 36, 30))
    y = 250
    for ln in sp["lines"]:
        f, ls, lh = G.fitted(d, ln, "regular", x1 - x0 - 140, 150, 40, 26, 3)
        for t in ls:
            d.text((x0 + 70, y), t, font=f, fill=(34, 32, 28))
            y += lh
        y += 40
    for _ in range(sp.get("blanks", 3)):
        d.rectangle((x0 + 70, y, x1 - 90 - (y % 7) * 24, y + 30), fill=(40, 36, 30))
        y += 70
    return im


def draw_news(sp: dict, style: str) -> Image.Image:
    im, d, c = G.canvas(style)
    x0, x1 = 360, G.SIZE[0] - 360
    d.rectangle((x0, 100, x1, G.SIZE[1] - 100), fill=(226, 220, 200))
    f, ls, lh = G.fitted(d, sp.get("headline", ""), "bold", x1 - x0 - 120, 360, 84, 40, 4)
    for k, t in enumerate(ls):
        d.text((x0 + 60, 180 + k * lh), t, font=f, fill=(24, 22, 20))
    y = 200 + len(ls) * lh
    d.rectangle((x0 + 60, y, x1 - 60, y + 4), fill=(24, 22, 20))
    for k in range(7):
        d.rectangle((x0 + 60, y + 50 + k * 54, x1 - 60 - (k % 3) * 90, y + 70 + k * 54), fill=(150, 144, 130))
    if sp.get("year"):
        d.text((x1 - 60 - G.text_w(d, sp["year"], G.font("bold", 44)), 120), sp["year"], font=G.font("bold", 44), fill=(80, 60, 40))
    return im


def draw_id(sp: dict, style: str) -> Image.Image:
    im, d, c = G.canvas(style)
    x0, x1, y0 = 460, G.SIZE[0] - 460, 260
    d.rounded_rectangle((x0, y0, x1, y0 + 540), 28, fill=(226, 232, 238))
    d.rectangle((x0, y0, x1, y0 + 90), fill=(60, 90, 140))
    d.rectangle((x0 + 50, y0 + 150, x0 + 330, y0 + 480), fill=(150, 160, 172))
    d.ellipse((x0 + 130, y0 + 190, x0 + 250, y0 + 310), fill=(190, 198, 208))
    f, ls, lh = G.fitted(d, sp.get("name", ""), "bold", x1 - x0 - 450, 100, 52, 30, 2)
    for k, t in enumerate(ls):
        d.text((x0 + 380, y0 + 150 + k * lh), t, font=f, fill=(24, 30, 40))
    for k, t in enumerate(sp.get("lines", [])):
        ff, ll, h2 = G.fitted(d, t, "regular", x1 - x0 - 450, 90, 32, 22, 2)
        for j, tt in enumerate(ll):
            d.text((x0 + 380, y0 + 290 + k * 62 + j * h2), tt, font=ff, fill=(52, 60, 70))
    return im


def draw_ledger(sp: dict, style: str) -> Image.Image:
    im, d, c = G.canvas(style)
    x0, x1, y = 400, G.SIZE[0] - 400, 130
    d.rectangle((x0, y - 30, x1, G.SIZE[1] - 100), fill=(230, 226, 210))
    d.text((x0 + 50, y), sp.get("title", "ACCOUNT"), font=G.font("bold", 46), fill=(40, 36, 30))
    y += 100
    for r in sp["rows"]:
        d.rectangle((x0 + 50, y + 70, x1 - 50, y + 73), fill=(150, 142, 120))
        d.text((x0 + 60, y + 14), r["label"], font=G.font("regular", 40), fill=(34, 32, 28))
        d.text((x1 - 60 - G.text_w(d, r["shown"], G.font("bold", 44)), y + 10), r["shown"], font=G.font("bold", 44), fill=(120, 40, 30))
        y += 100
    return im


def draw_phone(sp: dict, style: str) -> Image.Image:
    im, d, c = G.canvas(style)
    x0, x1 = 700, G.SIZE[0] - 700
    d.rounded_rectangle((x0, 60, x1, G.SIZE[1] - 20), 60, fill=(12, 14, 16), outline=(70, 74, 80), width=8)
    d.rounded_rectangle((x0 + 24, 100, x1 - 24, G.SIZE[1] - 60), 40, fill=(196, 226, 244))
    f, ls, lh = G.fitted(d, sp.get("line", ""), "bold", x1 - x0 - 120, 420, 56, 30, 6)
    y = G.SIZE[1] / 2 - len(ls) * lh / 2
    G.centred(d, ls, f, lh, G.SIZE[0] / 2, y, (22, 34, 44))
    d.ellipse((x0 + 60, 140, x0 + 90, 170), fill=(30, 40, 50))
    return im


def draw_counter(sp: dict, style: str) -> Image.Image:
    return G.draw_stat({"items": [{"shown": sp.get("shown", ""), "label": sp.get("label", ""), "value": 0}], "template": "stat"}, style)


def draw_year(sp: dict, style: str) -> Image.Image:
    return G.draw_text({"title": sp.get("year", ""), "template": "text"}, style)


def _xy(lat: float, lon: float, box: tuple[int, int, int, int]) -> tuple[float, float]:
    x0, y0, x1, y1 = box
    return x0 + (lon - 68.0) / (97.5 - 68.0) * (x1 - x0), y0 + (36.0 - lat) / (36.0 - 6.5) * (y1 - y0)


def draw_route(sp: dict, style: str) -> Image.Image:
    im, d, c = G.canvas(style)
    box = (560, 80, G.SIZE[0] - 560, G.SIZE[1] - 80)
    pts = [_xy(lat, lon, box) for lon, lat in OUTLINE]
    d.polygon(pts, fill=c["panel"], outline=c["muted"])
    route = [(s, _xy(*CITIES[s], box)) for s in sp["stops"] if s in CITIES]
    for (a, pa), (b, pb) in zip(route, route[1:]):
        d.line((pa, pb), fill=c["accent"], width=7)
    f = G.font("semi", 38)
    for k, (s, p) in enumerate(route):
        d.ellipse((p[0] - 16, p[1] - 16, p[0] + 16, p[1] + 16), fill=c["accent2"] if k else c["accent"], outline=c["bg"], width=4)
        name = s.title()
        d.text((p[0] + 24, p[1] - 22), name, font=f, fill=c["text"])
    return im


DRAW = {"chat": draw_chat, "sms": draw_sms, "call_log": draw_call_log, "fir": draw_fir, "news_clip": draw_news, "id_card": draw_id, "ledger": draw_ledger, "phone_pov": draw_phone,
        "route_map": draw_route, "counter": draw_counter, "year_card": draw_year}


# ── choosing which scenes become cards ────────────────────────────────────────────────────────────────────────────────────────────────────────

MAX_CARDS = 6
MIN_CARDS = 2


def plan(plan_id: str) -> int:
    """Turn event scenes into card scenes: those whose event is about a chat, an SMS, calls, a report, a cutting, an ID, accounts, a phone or a route, and have details to put on the
    card. At most MAX_CARDS, spread over the film, never the first scene. Returns how many were changed; running it again first undoes the earlier cards."""
    p = planner.get_plan(plan_id)
    undo(plan_id)
    if not events_mod.current(p) or not material.has(p):
        return 0
    scenes = sorted(storyboard.get_scenes(plan_id), key=lambda s: (s["start_s"], s["seq"]))
    evs = {e["id"]: e for e in events_mod.of(p)}
    cands = []
    for s in scenes[1:]:
        e = evs.get(s["data"].get("event", ""))
        if not e or s["locked"] or s["data"].get("insert") or s["data"].get("variant_of"):
            continue
        ct = pick_type(e)
        if ct and (e.get("ledger_ids") or ct == "route_map"):
            cands.append((s, e, ct))
    if not cands:
        return 0
    step = max(1, len(cands) // MAX_CARDS)
    chosen, seen = [], set()
    for s, e, ct in cands[::step]:
        if len(chosen) >= MAX_CARDS or (ct in seen and len(cands) > MIN_CARDS * 2):
            continue
        seen.add(ct)
        chosen.append((s, e, ct))
    for s, e, ct in chosen:
        d = dict(s["data"])
        d["card"] = {"type": ct, "event": e["id"], "items": list(e.get("ledger_ids") or []), "was": d.get("visual_type", "")}
        d["visual_type"] = TYPES[ct][0]
        d["prompts"], d["adapters"] = {}, {}
        db.ex("UPDATE scenes SET data=?, rev=rev+1, updated_at=? WHERE id=?", (db.jdump(d), db.now(), s["id"]))
    plan_store.log(plan_id, "cards", {"cards": [c[2] for c in chosen]})
    return len(chosen)


def undo(plan_id: str) -> int:
    n = 0
    for s in storyboard.get_scenes(plan_id):
        card = s["data"].get("card")
        if card and not s["locked"]:
            d = {k: v for k, v in s["data"].items() if k != "card"}
            d["visual_type"] = card.get("was") or "atmospheric"
            d["prompts"], d["adapters"] = {}, {}
            db.ex("UPDATE scenes SET data=?, rev=rev+1, updated_at=? WHERE id=?", (db.jdump(d), db.now(), s["id"]))
            n += 1
    return n
