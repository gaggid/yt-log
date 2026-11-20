"""Drops that run down a window glass, with the physics that make the Codrops "Rain & Water Effect" look real (owner, 2026-11-20: "much better graphics and physics").
The code is our own; the rules come from watching that demo's behaviour:

* a drop sits, then gathers water and RUNS: it gets a push (bigger drops get pushed more often), friction stops it again, so it goes stop, go, stop, go;
* a running drop leaves small round drops behind it on the glass (trail drops) and loses a little water for each;
* a running drop wipes the standing drizzle that lies in its way, and eats the trail drops of other drops it passes;
* when a bigger running drop meets a smaller one, the smaller one is taken in and the bigger one grows;
* a new drop first lands as a flat splat and settles into a teardrop.

The loop has to be exact (rainfx copies one 10 s clip over and over), and a real drop simulation is not periodic. So every drop is a stand-alone story: its spawn frame, path and trail drops come
from its own random numbers, it lives at most `LIFE_MAX` frames (less than the loop), and its place at frame f is path[(f - spawn) % n]. The only interactions (being taken in, wiping drizzle,
eating a trail drop) are decided once, from the whole ensemble taken modulo the loop and with the larger drop always the one that survives, so what happens at the end of the loop is
exactly what happens at its start. Drawing is `glassfx.sprite` (a refracting lens per drop); the wet path a drop leaves in the fog is a mask drawn by `trails`.
"""
import math
import random

import numpy as np

from . import glassfx

MIN_R, MAX_R = 2.2, 6.5          # radius of a running drop, in pixels of a 1280 px wide picture: the window is far from the viewer (owner, 2026-11-20: not drops on a TV screen)
SPEED = 0.6                     # a far window shows the same physical speed as fewer pixels per frame
DRIZZLE_R = (0.9, 2.0)          # the frost: very many tiny drops
LIFE_MAX = 255                  # frames (8.5 s at 30 fps): every drop is gone before the 10 s loop ends
FADE_IN, FADE_OUT = 6, 14
RUNNING = 60                    # running drops per view of 1280x720
DRIZZLE = 700                   # tiny standing drops per view of 1280x720 (some are wiped by passing drops and grow back)
REGROW = (70, 150)              # frames after a wipe: nothing, then the drizzle drop grows back


class Sim:
    def __init__(self, rng: random.Random, view: tuple, n_frames: int, s: float, running: int | None = None, drizzle: int | None = None):
        x0, y0, x1, y1 = view
        self.n, self.s, self.view = n_frames, s, view
        area = (x1 - x0) * (y1 - y0) / (s * s) / (1280 * 720)
        self.bigs: list[dict] = []
        for _ in range(max(4, int((RUNNING if running is None else running) * area))):
            r = MIN_R + (MAX_R - MIN_R) * rng.random() ** 2.4
            self.bigs.append(self._simulate(random.Random(rng.getrandbits(32)), rng.uniform(x0 + 8 * s, x1 - 8 * s), rng.uniform(y0, y0 + 0.7 * (y1 - y0)), r, rng.randrange(n_frames), y1))
        self._frames = np.arange(n_frames)
        self._build()
        self._absorb_bigs()
        self._trails()
        self._drizzle(rng, int((DRIZZLE if drizzle is None else drizzle) * area))

    # â”€â”€ one drop's own story â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _simulate(self, rng, x, y, r_u, t0, y_end):
        s = self.s
        r = r_u * s
        v = s * SPEED * rng.uniform(1.0, 2.6) * (0.55 + r_u / MAX_R)
        kick_p = 0.006 + 0.07 * (r_u - MIN_R) / (MAX_R - MIN_R)                    # a bigger drop gets pushed more often
        since, nxt = 0.0, self._spacing(rng, r_u, v)
        px, py, pv, pr, trails = [], [], [], [], []
        for k in range(LIFE_MAX):
            if rng.random() < kick_p:
                v += s * SPEED * rng.uniform(0.9, 2.2) * (0.5 + r_u / MAX_R)
            y += v
            x += rng.gauss(0, 0.04) * v
            since += v
            if since >= nxt and r > MIN_R * 0.7 * s:
                tr = r * rng.uniform(0.22, 0.45)
                trails.append({"k": k, "x": x + rng.uniform(-0.12, 0.12) * r, "y": y - 0.7 * r, "r": tr, "life": rng.randint(70, 190)})
                r *= 0.985
                since, nxt = 0.0, self._spacing(rng, r / s, v)
            v = max(0.0, v - s * SPEED * 0.05 * max(1.0, 3.0 - v / (s * SPEED)))                      # friction: the slower the drop, the harder it stops
            px.append(x), py.append(y), pv.append(v), pr.append(r)
            if y > y_end - r or r < MIN_R * 0.55 * s:
                break
        return {"t0": t0, "r0": r_u * s, "x": np.array(px, np.float32), "y": np.array(py, np.float32), "v": np.array(pv, np.float32), "r": np.array(pr, np.float32),
                "life": len(px), "fade_out": FADE_OUT, "trails": trails, "boosts": [], "dead_by": None}

    def _spacing(self, rng, r_u, v):
        return max(4.0, self.s * (rng.uniform(MIN_R, MAX_R) * 2.0 + (MAX_R - r_u) * 1.5) - 2 * v)

    # â”€â”€ the whole ensemble modulo the loop â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _build(self):
        n = self.n
        nb = len(self.bigs)
        self.PX, self.PY = np.full((nb, n), np.nan, np.float32), np.full((nb, n), np.nan, np.float32)
        self.PV, self.PR = np.zeros((nb, n), np.float32), np.full((nb, n), np.nan, np.float32)
        for i in range(nb):
            self._row(i)

    def _row(self, i):
        b = self.bigs[i]
        rel = (self._frames - b["t0"]) % self.n
        al = rel < b["life"]
        r = b["r"].copy()
        for rel_hit, gain in b["boosts"]:                                          # a drop that took another in is bigger from then on
            r[rel_hit:] *= 1 + gain
        for arr, src in ((self.PX, b["x"]), (self.PY, b["y"]), (self.PV, b["v"]), (self.PR, r)):
            arr[i, :] = np.nan if arr is not self.PV else 0
            arr[i, al] = src[rel[al]]

    def _absorb_bigs(self):
        """A bigger running drop that meets a smaller one takes it in: the smaller one is gone from that frame, the bigger one grows. Larger drops are decided first, so
        the outcome never depends on the order of the loop."""
        n, s = self.n, self.s
        order = sorted(range(len(self.bigs)), key=lambda i: -self.bigs[i]["r0"])
        done: list[int] = []
        for bi in order:
            if done:
                B = self.bigs[bi]
                rel = (self._frames - B["t0"]) % n
                A = np.array(done)
                d = np.hypot(self.PX[A] - self.PX[bi][None, :], self.PY[A] - self.PY[bi][None, :])
                thr = 0.75 * (self.PR[A] + self.PR[bi][None, :])
                with np.errstate(invalid="ignore"):
                    hit = (d < thr) & (self.PV[A] > 0.18 * s) & (rel < B["life"])[None, :]
                if hit.any():
                    cols = np.where(hit.any(axis=0))[0]
                    f_hit = int(cols[rel[cols].argmin()])
                    a = int(A[hit[:, f_hit].argmax()])
                    rel_hit = int(rel[f_hit])
                    B["life"], B["fade_out"], B["dead_by"] = max(10, rel_hit + 1), 5, a
                    B["trails"] = [t for t in B["trails"] if t["k"] < B["life"]]
                    ra = (f_hit - self.bigs[a]["t0"]) % n
                    self.bigs[a]["boosts"].append((ra, 0.35 * (B["r0"] / self.bigs[a]["r0"]) ** 1.5))
                    self._row(bi)
            done.append(bi)
        for i in done:
            self._row(i)

    def _trails(self):
        """The small drops a running drop leaves behind: static, they shrink a little and fade; another running drop that passes over one takes it in."""
        n, s = self.n, self.s
        self.trail_drops: list[dict] = []
        for bi, b in enumerate(self.bigs):
            for t in b["trails"]:
                life = min(t["life"], n - 1)
                tb = (b["t0"] + t["k"]) % n
                fr = (tb + np.arange(life)) % n
                d = np.hypot(self.PX[:, fr] - t["x"], self.PY[:, fr] - t["y"])
                thr = 0.8 * (self.PR[:, fr] + t["r"])
                with np.errstate(invalid="ignore"):
                    hit = (d < thr) & (self.PV[:, fr] > 0.18 * s)
                hit[bi, :] = False
                if hit.any():
                    life = max(4, int(np.where(hit.any(axis=0))[0][0]))
                    fade = 4
                else:
                    fade = FADE_OUT
                self.trail_drops.append({"x": t["x"], "y": t["y"], "r": t["r"], "tb": tb, "life": life, "fade": fade})

    def _drizzle(self, rng, count):
        x0, y0, x1, y1 = self.view
        s, n = self.s, self.n
        self.static_drizzle: list[tuple] = []
        self.dyn_drizzle: list[dict] = []
        pts = [(rng.uniform(x0, x1), rng.uniform(y0, y1), rng.uniform(*DRIZZLE_R) * s * rng.uniform(0.85, 1.1)) for _ in range(count)]
        dx = np.array([p[0] for p in pts])
        dy = np.array([p[1] for p in pts])
        dr = np.array([p[2] for p in pts])
        wipes: list[list[int]] = [[] for _ in pts]
        for f in range(n):
            ok = ~np.isnan(self.PX[:, f]) & (self.PV[:, f] > 0.18 * s)
            if not ok.any() or not pts:
                continue
            d = np.hypot(self.PX[ok, f][:, None] - dx[None, :], self.PY[ok, f][:, None] - dy[None, :])
            near = d < (0.55 * self.PR[ok, f])[:, None] + dr[None, :]
            for j in np.where(near.any(axis=0))[0]:
                wipes[j].append(f)
        for j, p in enumerate(pts):
            if wipes[j]:
                self.dyn_drizzle.append({"x": p[0], "y": p[1], "r": p[2], "wipes": np.array(wipes[j])})
            else:
                self.static_drizzle.append(p)

    # â”€â”€ what to draw at frame f â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def trails(self, draw, f):
        """The wet path each running drop leaves in the fog: one short line segment per drop per frame (the caller keeps the picture of them and lets it dry)."""
        for b in self.bigs:
            rel = (f - b["t0"]) % self.n
            if 1 <= rel < b["life"] and b["v"][rel] > 0.05 * self.s:
                a = min(1.0, rel / FADE_IN, (b["life"] - rel) / b["fade_out"])
                r = float(b["r"][rel])
                wd = max(2, int(r * 0.55))
                p0, p1 = (float(b["x"][rel - 1]), float(b["y"][rel - 1] - 0.5 * r)), (float(b["x"][rel]), float(b["y"][rel]))
                draw.line([p0, p1], fill=int(120 * a), width=wd + 2)
                draw.line([p0, p1], fill=int(215 * a), width=wd)

    def sprites(self, f) -> list[tuple]:
        """[(x, y, rx, ry, gain, mag, tear, punch, shade)] of every drop alive at frame f: running drops, the trail drops they left, and the drizzle drops that grew back."""
        n, s = self.n, self.s
        f %= n
        out = []
        for i, b in enumerate(self.bigs):
            rel = (f - b["t0"]) % n
            if rel >= b["life"]:
                continue
            gain = min(1.0, (rel + 1) / FADE_IN, (b["life"] - rel) / b["fade_out"])
            if gain <= 0.04:
                continue
            r = float(self.PR[i, f])
            v = float(b["v"][rel]) / s
            sx, sy = 1.5 * 0.4 ** rel, 1.5 * 0.7 ** rel                           # the splat of a new drop, settling
            out.append((float(b["x"][rel]), float(b["y"][rel]), r * 0.8 * (1 - 0.03 * min(v, 4)) * (1 + 0.25 * sx), r * 1.25 * (1 + 0.07 * min(v, 4)) * (1 + 0.25 * sy), gain, 2.2, 0.3, 1.5, 0.25))
        for t in self.trail_drops:
            rel = (f - t["tb"]) % n
            if rel >= t["life"]:
                continue
            gain = min(1.0, (rel + 1) / 5, (t["life"] - rel) / t["fade"])
            if gain <= 0.04:
                continue
            r = t["r"] * (1 - 0.35 * rel / max(1, t["life"]))
            out.append((t["x"], t["y"], r * 0.9, r * 1.1, gain, 1.9, 0.15, 1.9, 0.4))
        for dz in self.dyn_drizzle:
            age = (f - dz["wipes"]) % n
            a = int(age.min())
            if a < REGROW[0]:
                continue
            k = min(1.0, (a - REGROW[0]) / (REGROW[1] - REGROW[0]))
            out.append((dz["x"], dz["y"], dz["r"] * k, dz["r"] * 1.15 * k, 0.9 * k, 1.7, 0.12, 2.4, 0.55))
        return out

    def paste(self, im, src, f):
        for x, y, rx, ry, gain, mag, tear, punch, shade in self.sprites(f):
            if rx > 0.6 and ry > 0.6:
                glassfx.paste(im, glassfx.sprite(src, x, y, rx, ry, mag=mag, tear=tear, gain=gain, punch=punch, shade=shade))
