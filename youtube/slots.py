"""YouTube connection slots: one sign-in per channel, so each pipeline posts to its own channel.

`main` is the original connection (long-form videos, shorts, analytics, Learn). Every other slot is an upload channel: it asks Google for
the upload permission and the read permission that gives the channel's name, and nothing is synced or analysed for it. A pipeline names its
slot in its settings (`relaxation.models.YOUTUBE_SLOT`), and an upload never falls back to another slot's sign-in.
To add a channel: add a line here, then connect it on the YouTube page."""
import re

MAIN = "main"
SLOTS: dict[str, str] = {
    "main": "Main channel (long-form, shorts, analytics)",
    "rain": "Rain channel (rain videos)",
}
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,23}$")


def valid(slot: str) -> bool:
    return bool(_NAME.match(slot or "")) and slot in SLOTS


def label(slot: str) -> str:
    return SLOTS.get(slot, slot)


def upload_slots() -> list[str]:
    """The slots that only upload (everything but main)."""
    return [s for s in SLOTS if s != MAIN]
