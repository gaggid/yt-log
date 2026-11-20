"""Reads back the words that the image model drew into a thumbnail, so a misspelled or missing word never reaches YouTube (owner, 2026-11-20: the image model draws
the big words itself; in a test one picture lost its "3" and read "H OURS"). The vision model looks at the finished picture and says what it reads; plain code
compares that with the words that were asked for."""
import base64
import io
import re
from pathlib import Path

from PIL import Image

from story import llm
from story2.schemas import M, Str

MODEL = "qwen3.8-27b-Q3_S"          # the vision model the owner chose for this channel's picture work (relaxation/zones.py)

SYSTEM = """\
[TASK:rl_thumb_read]
You read the text written in a picture. Report every piece of text you can see, exactly as written (letters, numbers and spaces), in reading order from top to bottom, joined with
a single space. Do not correct spelling, do not guess missing letters, do not add words that are not visible. If there is no text, return an empty string.
Return ONLY a JSON object: {"text": "..."}"""


class ReadOut(M):
    text: Str = ""


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]+", " ", (s or "").upper())).strip()


def matches(expected: str, got: str) -> bool:
    """The picture holds the asked words, all of them spelled right, and at most two extra words (a stray mark read as a letter)."""
    e, g = norm(expected), norm(got)
    return bool(e) and e in g and len(g.split()) <= len(e.split()) + 2


def _data_url(path: Path, width: int = 1024) -> str:
    im = Image.open(path).convert("RGB")
    im = im.resize((width, max(1, int(width * im.height / im.width))))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


async def read(path: Path, s: dict, key: str) -> str | None:
    """The words in the picture, or None when they could not be read (no model, a scratch copy, a gateway error): the caller then accepts the picture."""
    try:
        be = llm.ChatBackend({**s, "model": MODEL}, key)
        res = await llm.JsonCaller(be, {**s, "model": MODEL}).call(SYSTEM, "What text is written in this picture?", ReadOut, images=[_data_url(path)])
        return res.value.text
    except Exception:  # noqa: BLE001 - a check that cannot run never stops a run
        return None
