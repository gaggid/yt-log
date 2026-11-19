"""Rain drawn by code over the scene picture, as a perfect loop.

Wan 2.2 keeps the streaks of its start picture where they are (they shimmer, they do not fall), so the picture is drawn WITHOUT rain in the
air and the rain is added here: falling streaks in three depth layers, ripples on water and small bursts on stone, only inside the area
where the picture looks outdoors. Pure Pillow (no numpy): a frame at 2560x1440 takes well under a second.

The loop is exact: every drop falls a whole number of times per loop (its speed is that number), and each pass of a drop or a splash has its
own position, brightness and size, so nothing repeats at the loop's period that the eye can follow. Gusts (a slow change of slant and density)
use whole cycles per loop too.

`zones` (from relaxation/zones.py): {"view": [x0, y0, x1, y1], "water": [[box], ...], "hard": [[box], ...]}, all as fractions of the picture."""
import math
import random
import subprocess
from pathlib import Path

import config
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from . import glassfx

FPS = 30                     # the video's frame rate (models.OUT_FPS): the loop is stream-copied, so it is drawn at the final rate
LOOP_S = 10.0               # a drizzle: the same whole passes per loop in a loop twice as long as the 5 s version, so the rain falls half as fast (4 s -> 5 s -> 10 s, each owner-requested)
TINT = (208, 224, 255)

# (drops per million pixels of view, length range px at 1280 wide, width at 1280, brightness range, passes per loop to choose from)
LAYERS = [
    (1500, (30, 70), 1.0, (0.10, 0.24), (3, 4)),          # far: fine, faint, slower
    (900, (70, 140), 1.2, (0.20, 0.38), (4, 5)),          # middle
    (230, (160, 300), 2.2, (0.32, 0.52), (5, 6, 7)),       # near: long, bright, fast
]
GAIN = 0.9
STREAKS = False             # falling streaks look sub-standard (owner, 2026-11-19): the scene is glass drops, mist, bokeh, ripples and splashes only
STREAK_DENSITY = 0.10        # drizzle, not downpour (owner): 1.0 was the first version, 0.67, then 0.20, now 0.10. Splashes unchanged.


def _box(frac: list, w: int, h: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = frac
    return int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h)


def _clean(zones: dict | None) -> dict:
    """Boxes as four fractions in order, inside the picture; with no usable view the whole picture is the view."""
    z = zones or {}

    def ok(b):
        try:
            x0, y0, x1, y1 = [min(1.0, max(0.0, float(v))) for v in b]
        except (TypeError, ValueError):
            return None
        return [x0, y0, x1, y1] if x1 - x0 >= 0.04 and y1 - y0 >= 0.04 else None
    view = ok(z.get("view") or [0, 0, 1, 1]) or [0, 0, 1, 1]
    return {"view": view, "water": [b for b in map(ok, z.get("water") or []) if b], "hard": [b for b in map(ok, z.get("hard") or []) if b]}


class _Streaks:
    """Falling drops: (x per pass, start offset, length, width, brightness per pass, passes per loop, slant offset)."""

    def __init__(self, rng: random.Random, w: int, h: int, view: tuple, n_frames: int):
        s = w / 1280
        x0, y0, x1, y1 = view
        area_m = (x1 - x0) * (y1 - y0) / 1e6
        self.h, self.n = h, n_frames
        self.view = view
        self.drops = []
        for per_m, (lo, hi), width, (b0, b1), ks in LAYERS:
            for _ in range(max(8, int(per_m * area_m / (s * s) * STREAK_DENSITY))):
                k = rng.choice(ks)
                length = rng.uniform(lo, hi) * s
                length = max(length, (h + length) * k / n_frames * 1.1)          # a streak is at least as long as one frame's fall, so it reads as a line
                self.drops.append(([rng.uniform(x0 - 30 * s, x1 + 30 * s) for _ in range(k)], rng.uniform(0, h + length), length,
                                   max(1, round(width * s * rng.uniform(0.8, 1.2))), [rng.uniform(b0, b1) for _ in range(k)], k, rng.uniform(-0.02, 0.02)))
        self.ph = [rng.uniform(0, 2 * math.pi) for _ in range(3)]

    def draw(self, d: ImageDraw.ImageDraw, f: int):
        t = 2 * math.pi * f / self.n
        slant_g = 0.07 + 0.035 * math.sin(2 * t + self.ph[0])          # a gust leans the whole rain, a whole number of times per loop
        dens_g = 0.80 + 0.20 * math.sin(t + self.ph[1])                # and thickens and thins it
        for xs, y0, length, width, br, k, ds in self.drops:
            cyc = self.h + length
            u = y0 + cyc * k * f / self.n
            j = int(u // cyc) % k
            y = u % cyc - length
            a = br[j] * dens_g
            if a < 0.04:
                continue
            sl = slant_g + ds
            x = xs[j]
            d.line([(x + sl * y, y), (x + sl * (y + length), y + length)], fill=min(255, int(255 * a)), width=width)


class _Splashes:
    """Ripples on water and bursts on hard surfaces. An event has several passes per loop; each pass lands somewhere else."""

    def __init__(self, rng: random.Random, w: int, h: int, zones: dict, n_frames: int):
        self.n, self.rng_seed = n_frames, rng.random()
        s = w / 1280
        self.ripples, self.bursts = [], []
        for b in (zones["water"] if RIPPLES else []):
            x0, y0, x1, y1 = _box(b, w, h)
            n = max(3, int((x1 - x0) * (y1 - y0) / (2500 * s * s)))
            for _ in range(min(n, 220)):
                self.ripples.append(self._event(rng, (x0, y0, x1, y1), s, 3, (14, 26), 'ripple'))
        for b in (zones["hard"] if ROCK_BURSTS else []):
            x0, y0, x1, y1 = _box(b, w, h)
            n = max(3, int((x1 - x0) * (y1 - y0) / (4000 * s * s)))
            for _ in range(min(n, 220)):
                self.bursts.append(self._event(rng, (x0, y0, x1, y1), s, 3, (8, 13), 'burst'))

    def _event(self, rng, box, s, passes, dur, kind):
        x0, y0, x1, y1 = box
        m = rng.choice((2, 3, 4)) if passes else 1
        f0 = rng.uniform(0, self.n)
        spots = [(rng.uniform(x0, x1), rng.uniform(y0, y1)) for _ in range(m)]
        # nearer (lower) spots look bigger
        out = []
        for j, (x, y) in enumerate(spots):
            depth = 0.55 + 0.9 * (y - y0) / max(1, y1 - y0)
            out.append({"t": (f0 + j * self.n / m + rng.uniform(-3, 3)) % self.n, "x": x, "y": y, "size": rng.uniform(0.6, 1.3) * depth * s,
                        "dur": rng.uniform(*dur) * FPS / 24, "bright": rng.uniform(0.45, 0.95), "seed": rng.random()})
        return out

    def draw(self, d: ImageDraw.ImageDraw, f: int):
        for ev in self.ripples:
            for p in ev:
                age = ((f - p["t"]) % self.n) / p["dur"]
                if age >= 1:
                    continue
                r = (6 + 30 * p["size"]) * (1 - (1 - age) ** 2)
                fade = (1 - age) ** 1.4 * p["bright"]
                sq = 0.33
                for ring, dly in ((1.0, 0.0), (0.6, 0.18)):
                    a2 = age - dly
                    if a2 < 0:
                        continue
                    rr = (3 + 17 * p["size"]) * ring * (1 - (1 - min(1, a2)) ** 2)
                    c = int(255 * fade * (1 - dly))
                    if c < 10 or rr < 1:
                        continue
                    d.ellipse([p["x"] - rr, p["y"] - rr * sq, p["x"] + rr, p["y"] + rr * sq], outline=c, width=max(1, int(1.4 * p["size"] + 0.5)))
                if age < 0.18:
                    rr = max(1.0, 2.2 * p["size"])
                    d.ellipse([p["x"] - rr, p["y"] - rr * 0.5, p["x"] + rr, p["y"] + rr * 0.5], fill=int(255 * p["bright"]))
        for ev in self.bursts:
            for p in ev:
                age = ((f - p["t"]) % self.n) / p["dur"]
                if age >= 1:
                    continue
                rng = random.Random(p["seed"])
                fade = (1 - age) ** 1.2 * p["bright"]
                t = age * p["dur"]
                for _ in range(rng.randint(4, 7)):
                    ang = rng.uniform(-math.pi * 0.9, -math.pi * 0.1)               # up and out
                    v = rng.uniform(1.8, 4.2) * p["size"]
                    vx, vy = math.cos(ang) * v, math.sin(ang) * v
                    x = p["x"] + vx * t
                    y = p["y"] + vy * t + 0.22 * p["size"] * t * t                    # gravity
                    x2, y2 = x - vx * 0.8, y - (vy + 0.44 * p["size"] * t) * 0.8
                    d.line([(x2, y2), (x, y)], fill=int(255 * fade), width=max(1, int(p["size"] + 0.5)))
                if age < 0.3:
                    rr = 3.5 * p["size"] * (0.4 + age * 2)
                    d.ellipse([p["x"] - rr, p["y"] - rr * 0.35, p["x"] + rr, p["y"] + rr * 0.35], outline=int(255 * (1 - age / 0.3) * p["bright"]))


# ── the window glass: smudges that turn lights into bokeh, beads of water, and a few drops that slide down ─────────────────────────────────
GLASS = True
SMUDGE = 0.60                # how strongly the smudged patches blur the view (0 to 1)
BOKEH = 0.55                 # brightness of the soft discs the lights turn into inside the smudges
RIPPLES = False              # ripples on water: off (owner, 2026-11-20: only the drops on the glass, nothing falling and no ripples)
ROCK_BURSTS = False          # droplet bursts on stones and other hard surfaces: off (owner, 2026-11-19); ripples on water stay
FOG = 0.38                   # how foggy the whole window glass is (0 = clear): the scene is a little soft and the drops and wiped trails show it sharp
DRIZZLE = 240               # tiny drops standing on the glass (per view of 1280x720)
MIST = 0.12                  # soft haze over the view, thicker in the distance (top), so the outside looks misty (0 = none)
BEADS = (95, 14)            # small and large beads of water standing on the glass (per view of 1280x720); the first version had (380, 55), which distorted the picture too much (owner: at least 70 % fewer)
RUNNERS = 45                 # drops that creep down the glass (per view of 1280x720): 14, 18, 27, now 45 (owner 2026-11-20: more, and faster)


def _lum_peaks(base, view, limit=40):
    """The brightest spots of the picture inside the view: [(x, y, (r, g, b))] (at the picture's size), strongest first."""
    w, h = base.size
    cell = 8
    small = base.resize((w // cell, h // cell), Image.BOX)
    lum = small.convert("L")
    sw, sh = small.size
    px, cols = lum.load(), small.load()
    x0, y0, x1, y1 = [int(v / cell) for v in view]
    peaks = []
    for y in range(max(1, y0), min(sh - 1, y1)):
        for x in range(max(1, x0), min(sw - 1, x1)):
            v = px[x, y]
            if v < 95:
                continue
            ring = [px[min(sw - 1, max(0, x + dx)), min(sh - 1, max(0, y + dy))] for dx in (-3, 0, 3) for dy in (-3, 0, 3) if dx or dy]
            if v - sum(ring) / len(ring) < 40:                          # a lamp stands out from what is around it; a bright sky does not
                continue
            if all(px[x + dx, y + dy] <= v for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
                peaks.append((v, x * cell + cell // 2, y * cell + cell // 2, cols[x, y]))
    peaks.sort(reverse=True)
    return [(x, y, c) for _v, x, y, c in peaks[:limit]]


def inside_view(view, w, h):
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rectangle(view, fill=255)
    return m.filter(ImageFilter.GaussianBlur(max(2, int(w * 0.006))))


def glass_base(base, view, rng):
    """The picture seen through a dirty, wet window: (picture with smudges, bokeh and standing beads, strongly blurred copy for the sliding drops)."""
    w, h = base.size
    s = w / 1280
    vx0, vy0, vx1, vy1 = view
    vw, vh = vx1 - vx0, vy1 - vy0
    blur = base.filter(ImageFilter.GaussianBlur(14 * s))
    # smudges: soft blobs and a few wiped strokes, only inside the view
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    for _ in range(9):
        cx, cy = rng.uniform(vx0, vx1), rng.uniform(vy0, vy1)
        rx, ry = rng.uniform(0.06, 0.17) * vw, rng.uniform(0.07, 0.20) * vh
        d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=rng.randint(110, 255))
    for _ in range(3):
        x, y = rng.uniform(vx0, vx1), rng.uniform(vy0, vy1)
        ang = rng.uniform(-0.6, 0.6)
        d.line([(x, y), (x + 0.3 * vw * math.cos(ang), y + 0.3 * vw * math.sin(ang))], fill=170, width=max(6, int(0.05 * vh)))
    m = m.filter(ImageFilter.GaussianBlur(0.045 * w))
    inside = Image.new("L", (w, h), 0)
    ImageDraw.Draw(inside).rectangle(view, fill=255)
    inside = inside.filter(ImageFilter.GaussianBlur(max(2, int(w * 0.006))))
    m = ImageChops.multiply(m, inside).point(lambda v: int(v * SMUDGE))
    out = Image.composite(blur, base, m)
    if FOG > 0:                                                # the whole glass is a little fogged; drops and wiped trails stay sharp
        soft = base.filter(ImageFilter.GaussianBlur(3.2 * s))
        out = Image.composite(soft, out, inside.point(lambda v: int(v * FOG)))
    if MIST > 0:
        haze = blur.filter(ImageFilter.GaussianBlur(10 * s)).point(lambda v: min(255, int(v * 0.8 + 62)))      # a pale, lifted, very soft copy
        grad = Image.linear_gradient("L").rotate(180).resize((w, h))                  # 255 at the top of the picture, 0 at the bottom
        grad = ImageChops.multiply(grad, inside_view(view, w, h)).point(lambda v: int(MIST * (0.35 * 255 + 0.65 * v)))
        out = Image.composite(haze, out, ImageChops.multiply(grad, Image.new("L", (w, h), 255)))
    # bokeh: every light inside a smudge becomes a soft disc
    discs = Image.new("RGB", (w, h), (0, 0, 0))
    dd = ImageDraw.Draw(discs)
    for x, y, col in _lum_peaks(base, view):
        r = rng.uniform(9, 20) * s
        dd.ellipse([x - r, y - r, x + r, y + r], fill=tuple(min(255, int(v * 1.5)) for v in col),
                   outline=tuple(min(255, int(v * 1.9)) for v in col), width=max(1, int(s)))
    discs = discs.filter(ImageFilter.GaussianBlur(1.4 * s))
    gate = m.point(lambda v: min(255, int(v * BOKEH / SMUDGE)))
    out = ImageChops.screen(out, Image.composite(discs, Image.new("RGB", (w, h), (0, 0, 0)), gate))
    # drops of water standing on the glass: tiny ones (drizzle), small and larger beads; each is a lens that shows the sharp scene flipped (relaxation/glassfx.py)
    src = glassfx.arr(base)
    area = vw * vh / (1280 * 720)
    for kind, n, (lo, hi), mag in (("drizzle", int(DRIZZLE * area), (1.0, 2.2), 1.7), ("small", int(BEADS[0] * area), (1.8, 3.8), 2.0), ("big", int(BEADS[1] * area), (5.0, 9.5), 2.2)):
        for _ in range(n):
            r = rng.uniform(lo, hi) * s
            x, y = rng.uniform(vx0, vx1), rng.uniform(vy0, vy1)
            glassfx.paste(out, glassfx.sprite(src, x, y, r * rng.uniform(0.85, 1.1), r * rng.uniform(0.95, 1.3), mag=mag, tear=0.12 if kind != "big" else 0.2, gain=0.85 if kind == "drizzle" else 1.0))
    return out, blur


class _Runners:
    """A few larger drops that creep down the glass: a short slide, a long pause, another slide (a drop on glass sticks, gathers water, then runs),
    with a thin wet trail behind them. Each makes one such journey per loop, faded in and out at its ends so the loop's start and end meet unseen."""

    def __init__(self, rng, w, h, view, n_frames, base):
        s = w / 1280
        x0, y0, x1, y1 = view
        self.n, self.s, self.src = n_frames, s, glassfx.arr(base)          # `base`: the sharp picture the drops look at
        self.items = []
        for _ in range(max(3, int(RUNNERS * (x1 - x0) * (y1 - y0) / (1280 * 720)))):
            r = rng.uniform(4.5, 8.5) * s
            travel = rng.uniform(0.09, 0.19) * (y1 - y0)                     # a longer run in the same time: faster (owner: faster)
            self.items.append({"x": rng.uniform(x0 + 10 * s, x1 - 10 * s), "y": rng.uniform(y0, y1 - travel), "travel": travel, "r": r,
                               "ph": rng.randrange(n_frames), "knots": self._knots(rng)})

    @staticmethod
    def _knots(rng):
        """The journey as [(u, share of the travel done)] knots: pause, slide, pause, slide ... Times are fractions of the loop (they add up to 1),
        a slide takes about 1.5 to 3 s of a 10 s loop and each pause about 1 to 2.5 s; the slides' lengths differ."""
        moves = rng.choice((2, 3, 3, 4))
        parts = [("hold", rng.uniform(0.02, 0.07))]
        for _ in range(moves):
            parts += [("move", rng.uniform(0.10, 0.20), rng.uniform(0.5, 1.5)), ("hold", rng.uniform(0.03, 0.09))]
        total = sum(p[1] for p in parts)
        dist = sum(p[2] for p in parts if p[0] == "move")
        knots, u, d = [(0.0, 0.0)], 0.0, 0.0
        for p in parts:
            u += p[1] / total
            if p[0] == "move":
                d += p[2] / dist
            knots.append((min(1.0, u), min(1.0, d)))
        return knots

    def _pos(self, it, f):
        u = ((f - it["ph"]) % self.n) / self.n
        k = it["knots"]
        share = 1.0
        for (u0, d0), (u1, d1) in zip(k, k[1:]):
            if u0 <= u <= u1:
                if d1 == d0 or u1 == u0:
                    share = d0                                     # a pause: the drop stands still
                else:
                    x = (u - u0) / (u1 - u0)
                    share = d0 + (d1 - d0) * x * x * (3 - 2 * x)    # a slide: it gathers speed and slows down
                break
        return u, it["y"] + it["travel"] * share

    @staticmethod
    def _alpha(u):
        return min(1.0, 12 * u, 12 * (1 - u))

    def trails(self, d, f):
        """A wet trail behind each drop: the fog is wiped away along its path (drawn as a mask; the sharp picture shows through it), strongest at the drop and fading above."""
        for it in self.items:
            u, y = self._pos(it, f)
            al = self._alpha(u)
            if al > 0.02:
                wd = max(2, int(it["r"] * 0.55))
                d.line([(it["x"], it["y"]), (it["x"], y)], fill=int(120 * al), width=wd + 2)
                d.line([(it["x"], it["y"]), (it["x"], y)], fill=int(215 * al), width=wd)

    def drops(self, im, f):
        for it in self.items:
            u, y = self._pos(it, f)
            al = self._alpha(u)
            if al < 0.05:
                continue
            r, x = it["r"], it["x"]
            glassfx.paste(im, glassfx.sprite(self.src, x, y, r * 0.8, r * 1.25, mag=2.2, tear=0.3, gain=al))


# ── lamps: a soft glow around every bright light, in the room and outside; a real flame also flickers a little ─────────────────────────────
BLOOM = 0.60                 # strength of the glow around lamps (0 = off)
BLOOM_FROM = 185             # brightness (0-255) from which a pixel counts as a light
FLICKER = 0.07               # how much a flame's glow rises and falls (whole cycles per loop, so the loop stays seamless)


def lamp_glow(base, hot_from=235):
    """(base with a soft glow added around its lights, glow of only the brightest cores for a flame to flicker). Colour of the glow = colour of the light."""
    w, h = base.size
    s = w / 1280
    lum = base.convert("L")

    def lights(lo):
        m = lum.point(lambda v: 0 if v < lo else min(255, (v - lo) * 6))
        return Image.composite(base, Image.new("RGB", (w, h), (0, 0, 0)), m)
    src = lights(BLOOM_FROM)
    glow = ImageChops.add(src.filter(ImageFilter.GaussianBlur(5 * s)), src.filter(ImageFilter.GaussianBlur(20 * s)))
    glow = ImageChops.add(glow, src.filter(ImageFilter.GaussianBlur(55 * s)).point(lambda v: min(255, int(v * 1.6))))
    glow = glow.point(lambda v: int(v * BLOOM))
    hot = lights(hot_from).filter(ImageFilter.GaussianBlur(9 * s)).point(lambda v: min(255, int(v * 1.4 * BLOOM)))
    return ImageChops.screen(base, glow), hot


def render(picture: Path, zones: dict | None, out: Path, size: tuple[int, int] = (2560, 1440), seed: int = 7, loop_s: float = LOOP_S,
           flame: bool = False) -> Path:
    """Write a `loop_s` second loop of the picture with rain in `zones` to `out` (H.264). Returns `out`. `flame`: the scene has a real flame (candle, oil lamp), whose glow flickers."""
    w, h = size
    n = int(round(FPS * loop_s))
    z = _clean(zones)
    base = Image.open(picture).convert("RGB").resize((w, h), Image.LANCZOS)
    view = _box(z["view"], w, h)
    soft = max(2, int(w * 0.006))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rectangle(view, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(soft))
    rng = random.Random(seed)
    runners = None
    sharp = base                                              # the picture as drawn: what the drops and the wiped trails show
    sharp_glow = lamp_glow(sharp)[0] if BLOOM > 0 else sharp
    if GLASS:
        base, blur = glass_base(sharp, view, random.Random(seed + 1))
        runners = _Runners(random.Random(seed + 2), w, h, view, n, sharp_glow)
    hot = None
    if BLOOM > 0:
        base, hot = lamp_glow(base)
    ph = [rng.uniform(0, 6.28) for _ in range(2)]
    streaks = _Streaks(rng, w, h, view, n)
    splashes = _Splashes(rng, w, h, z, n)
    tint = Image.new("RGB", (w, h), TINT)
    cmd = [config.FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(FPS), "-i", "-",
           "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for f in range(n):
            a = Image.new("L", (w, h), 0)
            if STREAKS:
                streaks.draw(ImageDraw.Draw(a), f)
            glass = base
            if runners:                                        # the fog is wiped along the path of every running drop: the sharp picture shows through
                tr = Image.new("L", (w, h), 0)
                runners.trails(ImageDraw.Draw(tr), f)
                glass = Image.composite(sharp_glow, base, ImageChops.multiply(tr, mask))
            b = Image.new("L", (w, h), 0)
            splashes.draw(ImageDraw.Draw(b), f)
            b = b.filter(ImageFilter.GaussianBlur(max(0.6, 0.8 * w / 1280))).point(lambda v: int(v * 0.85))       # soft, not drawn circles
            a = ImageChops.multiply(ImageChops.lighter(a, b), mask).point(lambda v: int(v * GAIN))
            frame = Image.composite(tint, glass, a)
            if flame and hot is not None:
                g = 0.55 + FLICKER * 3 * (math.sin(2 * math.pi * 3 * f / n + ph[0]) * 0.6 + math.sin(2 * math.pi * 7 * f / n + ph[1]) * 0.4)
                frame = ImageChops.screen(frame, hot.point(lambda v, g=g: min(255, int(v * g))))
            if runners:
                runners.drops(frame, f)
            p.stdin.write(frame.tobytes())
    finally:
        p.stdin.close()
        err = p.stderr.read().decode("utf-8", "replace")
        p.wait()
    if p.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + err[-300:])
    return out
