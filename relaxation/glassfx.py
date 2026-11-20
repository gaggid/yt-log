"""Drops of water on a window, drawn by code with numpy: each drop is a small lens.

Why this and not a pasted copy of the picture (owner, 2026-11-19, after comparing with the Codrops "Rain & Water Effect" demo): a real drop on glass bends light
by its shape. Every pixel inside it looks at the scene along a line bent by the drop's surface: the middle shows a flipped, shrunken copy of the scene that is
sharper than the foggy glass around it, the edges bend strongest, the top edge is a little darker and the bottom edge catches light. Here that is done per pixel from a
height field of the drop (a dome, narrower at the top like a teardrop), and the scene it looks at is the sharp picture, while the glass around it is fogged
(rainfx.glass_base). The code is our own; only the idea (a drop is a refracting height field over a fogged glass) comes from that demo.

`sprite` returns the RGBA picture of one drop; it needs the sharp picture as an array (`arr`)."""
import numpy as np
from PIL import Image


def arr(im: Image.Image) -> np.ndarray:
    return np.asarray(im.convert("RGB"), dtype=np.float32)


def _smooth(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def _bilinear(src: np.ndarray, sx: np.ndarray, sy: np.ndarray) -> np.ndarray:
    h, w, _ = src.shape
    sx = np.clip(sx, 0, w - 1.001)
    sy = np.clip(sy, 0, h - 1.001)
    x0, y0 = sx.astype(np.int32), sy.astype(np.int32)
    fx, fy = (sx - x0)[..., None], (sy - y0)[..., None]
    a = src[y0, x0] * (1 - fx) + src[y0, x0 + 1] * fx
    b = src[y0 + 1, x0] * (1 - fx) + src[y0 + 1, x0 + 1] * fx
    return a * (1 - fy) + b * fy


def sprite(src: np.ndarray, cx: float, cy: float, rx: float, ry: float, mag: float = 2.1, tear: float = 0.3, gain: float = 1.0, punch: float = 1.0, shade: float = 0.0):
    """One drop centred at (cx, cy) with radii (rx, ry) in pixels, seen against `src` (the sharp picture). Returns (RGBA uint8 array, left, top) or None when it is too small.
    `mag`: how much of the scene it shows (2 = twice the drop's own size, flipped); `tear`: how much narrower the top is (0 = an ellipse); `gain`: opacity (0 to 1); `punch`: contrast of the rims and the shine (a tiny drop far from the viewer needs more than a big one to read at all: 2 to 2.5); `shade`: how much darker the drop is where the picture behind it is bright (0 to 0.6): against a bright sky a clear lens has nothing to show, a darker one does."""
    h, w, _ = src.shape
    x0, x1 = int(np.floor(cx - rx)) - 2, int(np.ceil(cx + rx)) + 3
    y0, y1 = int(np.floor(cy - ry)) - 2, int(np.ceil(cy + ry)) + 3
    if x1 - x0 < 3 or y1 - y0 < 3 or x1 < 0 or y1 < 0 or x0 >= w or y0 >= h:
        return None
    X = np.arange(x0, x1, dtype=np.float32)[None, :] + 0.5
    Y = np.arange(y0, y1, dtype=np.float32)[:, None] + 0.5
    v = (Y - cy) / ry
    u = (X - cx) / rx
    u = u / (1.0 - tear * np.clip(-v, 0, 1))                               # narrower at the top: a teardrop
    d2 = u * u + v * v
    d = np.sqrt(d2)
    soft = 1.4 / max(2.0, min(rx, ry))                                      # about one and a half pixels of soft edge
    alpha = _smooth((1.0 - d) / soft)
    # the lens: look at the scene along the bent line; strongest bend at the rim
    bend = mag * (1.0 + 0.55 * d2)
    sx = cx - u * rx * bend * 0.62
    sy = cy - v * ry * bend * 0.62
    col = _bilinear(src, sx, sy)
    col = col * 1.10 + 6.0
    if shade:
        col = col * (1.0 - shade * float(np.clip((col.mean() - 90.0) / 150.0, 0.0, 1.0)))
    # the top edge is a little darker (the drop is thicker there and holds shadow), the bottom edge catches light (light is focused there)
    rim = _smooth((d - 0.62) / 0.34)
    dark = rim * np.clip(-v + 0.15, 0, 1) * 0.5 * min(punch, 1.5) + _smooth((d - 0.84) / 0.14) * 0.22 * punch            # and a thin dark outline all round, so a drop reads on a bright sky
    dark = np.minimum(dark, 0.85)
    light = rim * np.clip(v + 0.05, 0, 1) * 0.34 * punch
    col = col * (1.0 - dark[..., None]) + light[..., None] * 70.0
    spec = np.exp(-(((u + 0.38) ** 2 + (v + 0.5) ** 2) / 0.07)) * 0.16 * punch      # a faint broad shine, never a white dot
    col = col + spec[..., None] * 255.0
    out = np.empty((y1 - y0, x1 - x0, 4), dtype=np.uint8)
    out[..., :3] = np.clip(col, 0, 255).astype(np.uint8)
    out[..., 3] = np.clip(alpha * 232.0 * gain, 0, 255).astype(np.uint8)
    return out, x0, y0


def paste(im: Image.Image, spr) -> None:
    """Lay a drop (from `sprite`) on a picture."""
    if spr is None:
        return
    rgba, left, top = spr
    patch = Image.fromarray(rgba, "RGBA")
    im.paste(patch, (left, top), patch)
