"""Where the rain goes in a scene picture: the vision model looks at the picture (with a labelled grid) and gives boxes.

view  = the outdoors seen through the window or open door, or the whole picture when it is open air (the room's own foreground, frame, lamp and
        blanket stay dry), water = surfaces that ripple (pond, puddles, wet street), hard = stone, wood and roofs where drops burst.
All as fractions of the picture, [x0, y0, x1, y1]. A failed call gives the safe fallback: rain over most of the picture, no splashes."""
import base64
import io
from pathlib import Path

from pydantic import BaseModel

from PIL import Image, ImageDraw

from story import llm

SYSTEM = """[TASK:rl_zones]
You look at one picture of a calm rainy scene seen from inside a room (or from a porch). The picture has a thin grid; the numbers on the top edge are the horizontal position and the numbers on the left edge the vertical position, from 0.0 (left, top) to 1.0 (right, bottom).
Return boxes as [x0, y0, x1, y1] using those numbers:
- view: the one box around the OUTDOORS you see through the window or open door (the garden, street, valley, sky). Leave out the room's own parts: the window or door frame, the walls, a lamp, the blanket, the floor and the sill. When there is no frame and the whole picture is outdoors (open porch, veranda), give the area a little inside the picture's edges.
- water: up to 3 boxes around surfaces where a falling drop would make a ripple: ponds, puddles, a wet street or courtyard, a lake. Only what is inside view.
- hard: up to 4 boxes around stone, rocks, a wet cobbled street, wooden rails or roofs where drops would burst into small splashes. Only what is inside view.
Be exact: a box must tightly contain what it names. An empty list when there is none.
Return ONLY JSON of this shape: {"view": [0.1, 0.05, 0.9, 0.85], "water": [[0.3, 0.6, 0.8, 0.85]], "hard": [[0.2, 0.5, 0.4, 0.7]]}"""

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["view", "water", "hard"],
          "properties": {"view": {"type": "array", "items": {"type": "number"}},
                         "water": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}},
                         "hard": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}}}}
RESPONSE_FORMAT = {"type": "json_schema", "json_schema": {"name": "rain_zones", "strict": True, "schema": SCHEMA}}

MODEL = "qwen3.8-27b-Q3_S"          # the owner chose this gateway model for the picture work, not the default chat model

FALLBACK = {"view": [0.05, 0.04, 0.95, 0.88], "water": [], "hard": [], "source": "fallback"}


class ZonesOut(BaseModel):
    view: list[float]
    water: list[list[float]] = []
    hard: list[list[float]] = []


def gridded(path: Path, width: int = 1280) -> str:
    """The picture with a labelled grid every 0.1, as a data URL."""
    im = Image.open(path).convert("RGB")
    im = im.resize((width, int(width * im.height / im.width)))
    d = ImageDraw.Draw(im)
    w, h = im.size
    for i in range(1, 10):
        x, y = int(w * i / 10), int(h * i / 10)
        d.line([(x, 0), (x, h)], fill=(255, 255, 0), width=1)
        d.line([(0, y), (w, y)], fill=(255, 255, 0), width=1)
        d.text((x + 3, 3), f"0.{i}", fill=(255, 255, 0))
        d.text((3, y + 3), f"0.{i}", fill=(255, 255, 0))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _box(b, lo=0.04):
    try:
        x0, y0, x1, y1 = [min(1.0, max(0.0, float(v))) for v in b]
    except (TypeError, ValueError):
        return None
    x0, x1, y0, y1 = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)
    return [round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)] if x1 - x0 >= lo and y1 - y0 >= lo else None


def clean(out: ZonesOut) -> dict:
    """Plain-code checks of the model's boxes: a view smaller than a sixth of the picture is not believed; splash boxes are cut to the view."""
    view = _box(out.view)
    if not view or (view[2] - view[0]) * (view[3] - view[1]) < 1 / 6:
        return dict(FALLBACK)

    ground = view[1] + 0.45 * (view[3] - view[1])         # drops make splashes on the ground, never in the sky or the treetops

    def inside(b):
        b = _box(b)
        if not b:
            return None
        b = [max(b[0], view[0]), max(b[1], view[1], ground), min(b[2], view[2]), min(b[3], view[3])]
        if b[2] <= b[0] or b[3] <= b[1]:                      # nothing of it is left on the ground (the box would flip)
            return None
        return _box(b, 0.03)
    return {"view": view, "water": [b for b in map(inside, out.water[:3]) if b], "hard": [b for b in map(inside, out.hard[:4]) if b], "source": "vision"}


async def find(path: Path, backend, s: dict) -> dict:
    """The zones of one picture. Never raises: a failed call gives FALLBACK."""
    s = {**s, "model": MODEL}
    try:
        res = await llm.JsonCaller(backend, s).call(SYSTEM, "Find the zones in this picture.", ZonesOut, images=[gridded(path)])
    except llm.LLMError:
        return dict(FALLBACK)
    return clean(res.value)
