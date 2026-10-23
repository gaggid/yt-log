"""Svara TTS text format, as documented by the gateway:
  * emotion goes at the END of a sentence:  "आज बहुत अच्छा दिन है! <happy>"  (a tag always beats the request-level emotion)
  * silence is  [pause:1.2s]  or  [pause:400ms]  (up to 10 s each) and is never spoken
  * emotions: neutral, happy, sad, anger, fear, clear   (clear = precise delivery for technical text and rare names)
Emotion is stored as structured data (per sentence) and only serialised into tags here, so the spoken text stays clean.
"""
import re

EMOTIONS = ("neutral", "happy", "sad", "anger", "fear", "clear")
_ALIAS = {"angry": "anger", "mad": "anger", "furious": "anger", "afraid": "fear", "scared": "fear", "anxious": "fear",
          "tense": "fear", "joy": "happy", "joyful": "happy", "excited": "happy", "calm": "neutral", "flat": "neutral",
          "serious": "neutral", "precise": "clear", "technical": "clear", "sorrow": "sad", "grief": "sad", "regret": "sad",
          "surprise": "happy", "curious": "neutral", "uncertain": "neutral"}
MAX_PAUSE_S = 10.0

TAG_RE = re.compile(r"<(" + "|".join(EMOTIONS) + r")>")
PAUSE_RE = re.compile(r"\[pause:(\d+(?:\.\d+)?)(s|ms)\]")
_ANY_ANGLE = re.compile(r"<[^<>]{1,20}>")
_ANY_BRACKET = re.compile(r"\[[^\[\]]{1,20}\]")


def norm_emotion(v) -> str:
    v = str(v or "").strip().lower()
    v = _ALIAS.get(v, v)
    return v if v in EMOTIONS else "neutral"


def pause_tag(seconds: float) -> str:
    s = max(0.0, min(MAX_PAUSE_S, float(seconds)))
    return f"[pause:{s:g}s]" if s else ""


def serialise(sentences: list[dict]) -> str:
    """sentences: [{text, emotion, pause_after_s}] -> one Svara input string. Every sentence carries its own tag."""
    out = []
    for s in sentences:
        t = plain_text(s["text"]).strip()
        if not t:
            continue
        out.append(f"{t} <{norm_emotion(s.get('emotion'))}>")
        p = pause_tag(s.get("pause_after_s") or 0)
        if p:
            out.append(p)
    return " ".join(out)


def plain_text(annotated: str) -> str:
    """The words that are actually spoken: tags and pauses removed."""
    t = PAUSE_RE.sub(" ", TAG_RE.sub(" ", annotated))
    return re.sub(r"\s{2,}", " ", t).strip()


def validate(annotated: str) -> list[str]:
    """Problems that would make Svara read a tag aloud or reject the request. Empty list = valid."""
    problems = []
    for m in PAUSE_RE.finditer(annotated):
        secs = float(m.group(1)) / (1000 if m.group(2) == "ms" else 1)
        if secs > MAX_PAUSE_S:
            problems.append(f"pause of {secs:g}s is longer than the {MAX_PAUSE_S:g}s limit")
    rest = PAUSE_RE.sub("", TAG_RE.sub("", annotated))
    for m in _ANY_ANGLE.finditer(rest):
        problems.append(f"unknown emotion tag {m.group(0)} (use {', '.join(EMOTIONS)})")
    for m in _ANY_BRACKET.finditer(rest):
        problems.append(f"unknown bracket tag {m.group(0)}; only [pause:Ns] is supported")
    return problems


_ALLOWED = re.compile(r"[ऀ-ॿ\s.,!?;:'\"\-–—…()]")


def foreign_chars(text: str) -> list[str]:
    """Characters that a Hindi voice should not be given: Latin or other scripts and ASCII digits. They get mispronounced or
    skipped (a stray Cyrillic fragment inside a word is a typical small-model slip)."""
    return sorted({c for c in plain_text(text) if not _ALLOWED.match(c)})


def spoken_seconds(plain: str, wpm: float = 125.0, pause_s: float = 0.0) -> float:
    """Rough duration of Hindi speech: words / pace plus pauses. Corrected later from real previews."""
    words = len(re.findall(r"\S+", plain))
    return round(words / (wpm / 60.0) + pause_s, 1)
