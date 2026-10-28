"""Maya TTS (`maya-tts`) text format, as documented by the gateway (docs#speech-maya):
  * tags go inline in square brackets BEFORE the words they colour:  "[whispers] Come closer."
  * style tags colour everything after them until another style tag; sound tags ([laughs] [sighs] [clears throat]) are a single sound at that point
  * silence is [pause:1s] (up to 10 s each), never a tag
  * input is at most 1500 characters per request; longer text is split here and the style is carried into the next piece
Tags are best effort: few, short, and only where a person would change tone. Tags are stored as structured data (per sentence, `tag`) and
only serialised here, so the plain wording stays clean. The storyboard suggests one tag per scene (`scene.data.voice_tag`); it is copied onto
the scene's sentences. Tags are outside the content hash on purpose: they change how a line is spoken, not what was approved.
"""
import re

from . import svara

STYLE_TAGS = ("whispers", "softly", "loudly", "shouting", "sad", "crying", "excited", "happy", "cheerful", "angry", "frustrated", "annoyed",
              "sarcastic", "curious", "confused", "nervous", "scared", "fearful", "worried", "panicked", "calm", "serious", "surprised",
              "amazed", "tired", "sleepy", "disgusted")
SOUND_TAGS = ("laughs", "sighs", "clears throat")
NEUTRAL = "neutral"                                   # "no tag, and do not fall back to the sentence's Svara emotion"
MAX_CHARS = 1400                                      # the gateway refuses more than 1500 per request
RESET = "calm"                                        # style tags last, so going back to plain speech needs a tag of its own
GAP_S = 0.15

_ALIAS = {"whisper": "whispers", "soft": "softly", "loud": "loudly", "shout": "shouting", "laugh": "laughs", "sigh": "sighs", "afraid": "scared",
          "fear": "fearful", "anger": "angry", "mad": "angry", "joy": "happy", "joyful": "happy", "grief": "sad", "sorrow": "sad", "tense": "nervous",
          "anxious": "nervous", "tension": "nervous", "shock": "surprised", "shocked": "surprised", "wonder": "amazed", "awe": "amazed", "grave": "serious",
          "somber": "serious", "sombre": "serious", "suspense": "nervous", "dread": "fearful", "relief": "calm", "flat": NEUTRAL, "none": NEUTRAL, "clear": NEUTRAL}
# a sentence written for Svara carries one of its six emotions; this is how it sounds in Maya when nothing more specific was chosen
FROM_SVARA = {"sad": "sad", "fear": "fearful", "anger": "angry", "happy": "cheerful"}
_ALL = set(STYLE_TAGS) | set(SOUND_TAGS)
_TAG_RE = re.compile(r"\[(" + "|".join(re.escape(t) for t in sorted(_ALL, key=len, reverse=True)) + r")\]")
_END = re.compile(r"[.!?।…]$")


def norm_tag(v) -> str:
    """A tag word the voice knows, `neutral` for none-on-purpose, or "" (not chosen)."""
    v = re.sub(r"[\[\]]", "", str(v or "")).strip().lower()
    v = _ALIAS.get(v, v)
    return v if v in _ALL or v == NEUTRAL else ""


def plain_text(text: str) -> str:
    """The words that are spoken: Maya tags and pauses removed."""
    return svara.plain_text(_TAG_RE.sub(" ", text))


def validate(text: str) -> list[str]:
    """Bracketed words the voice would pass through unchanged (and may read aloud)."""
    rest = svara.PAUSE_RE.sub("", _TAG_RE.sub("", text))
    return [f"unknown bracket tag {m.group(0)}" for m in svara._ANY_BRACKET.finditer(rest)]


def _tag_for(s: dict) -> str:
    t = norm_tag(s.get("tag"))
    return t or FROM_SVARA.get(svara.norm_emotion(s.get("emotion")), "")


def chunks(sentences: list[dict], limit: int = MAX_CHARS) -> list[str]:
    """The request inputs for one narration segment (nearly always one)."""
    out: list[str] = []
    cur, active = "", ""
    for s in sentences:
        t = svara.plain_text(s["text"]).strip()
        if not t:
            continue
        t = t if _END.search(t) else t + ("।" if re.search(r"[ऀ-ॿ]$", t) else ".")
        tag = _tag_for(s)
        piece = ""
        if tag in STYLE_TAGS:
            if tag != active:
                piece, active = f"[{tag}] ", tag
        elif tag in SOUND_TAGS:
            piece = f"[{tag}] "
        elif active:
            piece, active = f"[{RESET}] ", ""
        piece += t
        p = svara.pause_tag(s.get("pause_after_s") or 0)
        if p:
            piece += " " + p
        if cur and len(cur) + 1 + len(piece) > limit:
            out.append(cur)
            cur = f"[{active}] " if active and not piece.startswith(f"[{active}]") else ""
        cur = f"{cur} {piece}" if cur and not cur.endswith("] ") else cur + piece
    if cur:
        out.append(cur)
    return out


def join_wavs(parts: list[bytes]) -> bytes:
    """Several wav files of one format as one, with a short gap between them (the gateway does the same inside a long request)."""
    import io
    import wave
    if len(parts) == 1:
        return parts[0]
    frames, params = [], None
    for b in parts:
        with wave.open(io.BytesIO(b)) as w:
            params = params or w.getparams()
            if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (params.framerate, params.nchannels, params.sampwidth):
                raise ValueError("voice pieces have different audio formats")
            frames.append(w.readframes(w.getnframes()))
    gap = b"\x00" * (int(params.framerate * GAP_S) * params.nchannels * params.sampwidth)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setparams(params)
        w.writeframes(gap.join(frames))
    return buf.getvalue()
