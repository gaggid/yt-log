"""Narration language of a short (setting `language`). Maya, the voice engine that speaks them, reads 12 languages (`GET /v1/audio/voices?model=maya-tts`); Veena and Svara only do
Hinglish, so any other language needs Maya. `hinglish` is the old behaviour: Hindi in Devanagari mixed with English words in Latin letters, voiced as Hindi."""
import re

DEFAULT = "hinglish"
NEEDS_ENGINE = "maya-tts"

HINGLISH_RULE = ("Plain, spoken Hinglish in mixed script: Hindi words in Devanagari, English words in Latin letters, numbers written as words (never digits), no other script. End each sentence with the Devanagari danda (।), not a full stop (.).")


def _rule(name: str, script: str) -> str:
    return (f"Plain, spoken {name}, written in {script} script: natural everyday speech, not formal or bookish. Well-known English words (names of machines, brands, places) may stay in Latin "
            "letters. Numbers written as words (never digits). No other script.")


LANGUAGES: dict[str, dict] = {
    "hinglish": {"label": "Hinglish (Hindi + English, default)", "code": "hi", "rule": HINGLISH_RULE},
    "en": {"label": "English", "code": "en", "rule": "Plain, spoken English, natural everyday speech. Numbers written as words (never digits). Latin script only."},
    "hi": {"label": "Hindi (Devanagari)", "code": "hi", "rule": _rule("Hindi", "Devanagari")},
    "bn": {"label": "Bengali", "code": "bn", "rule": _rule("Bengali", "Bengali")},
    "ta": {"label": "Tamil", "code": "ta", "rule": _rule("Tamil", "Tamil")},
    "te": {"label": "Telugu", "code": "te", "rule": _rule("Telugu", "Telugu")},
    "mr": {"label": "Marathi", "code": "mr", "rule": _rule("Marathi", "Devanagari")},
    "gu": {"label": "Gujarati", "code": "gu", "rule": _rule("Gujarati", "Gujarati")},
    "kn": {"label": "Kannada", "code": "kn", "rule": _rule("Kannada", "Kannada")},
    "ml": {"label": "Malayalam", "code": "ml", "rule": _rule("Malayalam", "Malayalam")},
    "pa": {"label": "Punjabi", "code": "pa", "rule": _rule("Punjabi", "Gurmukhi")},
    "or": {"label": "Odia", "code": "or", "rule": _rule("Odia", "Odia")},
    "as": {"label": "Assamese (weakest voice quality)", "code": "as", "rule": _rule("Assamese", "Assamese")},
}


def of(settings: dict | None) -> str:
    lang = (settings or {}).get("language")
    return lang if lang in LANGUAGES else DEFAULT


def code(settings: dict | None) -> str:
    return LANGUAGES[of(settings)]["code"]


ADDRESS_AAP = ("Address the viewer respectfully as 'aap' (आप), always: aap, aapka, aapko, aapke, 'soch rahe honge', 'sochiye', 'dekhiye'. Never use tu, tum, tera, teri, tere, tujhe, tumhara, तू, तुम, तेरा, तुझे or तुम्हारा, "
               "and never switch between forms inside one script.")
HINDI_LIKE = ("hinglish", "hi")

_TU = (r"tu|tum|tera|teri|tere|tujhe|tujhko|tujhse|tumhara|tumhari|tumhare|tumhe|tumko|tumse|tuhara|tuhari|tuhare|"
       r"तू|तुम|तेरा|तेरी|तेरे|तुझे|तुझको|तुझसे|तुम्हारा|तुम्हारी|तुम्हारे|तुम्हें|तुमको|तुमसे|तुमने|तूने|तुहारा|तुहारी|तुहारे")
_TU_RE = re.compile(rf"(?<![\wऀ-ॿ])(?:{_TU})(?![\wऀ-ॿ])", re.I)


def address(settings: dict | None) -> str:
    """How the narrator addresses the viewer: `aap` (default, respectful) or `tu` (the producer's choice, no check)."""
    return "tu" if (settings or {}).get("address") == "tu" else "aap"


def address_hits(text: str) -> list[str]:
    """The familiar 'tu' forms found in a Hindi line (the narration must say 'aap')."""
    return list(dict.fromkeys(m.group(0).lower() for m in _TU_RE.finditer(text)))


def rule(settings: dict | None) -> str:
    base = LANGUAGES[of(settings)]["rule"]
    if of(settings) in HINDI_LIKE and address(settings) == "aap":
        return base + " " + ADDRESS_AAP
    return base


def problem(language: str, engine: str) -> str:
    """Why the voice engine cannot speak the language, or ''."""
    if language not in LANGUAGES:
        return f"language is one of: {', '.join(LANGUAGES)}"
    if language != DEFAULT and engine != NEEDS_ENGINE:
        return f"{LANGUAGES[language]['label']} needs the Maya voice; the {engine} voice only does Hinglish"
    return ""


def public() -> list[dict]:
    return [{"id": k, "label": v["label"], "maya_only": k != DEFAULT} for k, v in LANGUAGES.items()]
