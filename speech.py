"""Pronunciation prep. The script is written in Roman Hinglish (easy to read and edit), but the Hindi TTS voice only
reads Devanagari well: Latin text gets mangled ("ChatGPT" -> "चात G.P.T"). So before TTS every narration is rewritten
in Devanagari, Hindi words in proper spelling and English words as phonetics, the way an Indian speaker says them
(AI -> ए आई, ChatGPT -> चैट जी पी टी, model -> मॉडल). The Roman script stays for display."""
import json
import re
from pathlib import Path

LETTERS = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", [
    "ए", "बी", "सी", "डी", "ई", "एफ", "जी", "एच", "आई", "जे", "के", "एल", "एम",
    "एन", "ओ", "पी", "क्यू", "आर", "एस", "टी", "यू", "वी", "डब्ल्यू", "एक्स", "वाई", "ज़ेड"]))

# Fixed pronunciations passed to the LLM as hints (and used to patch any Latin word it leaves behind).
LEXICON = {
    "ai": "ए आई", "chatgpt": "चैट जी पी टी", "gpt": "जी पी टी", "openai": "ओपन ए आई",
    "llm": "एल एल एम", "agi": "ए जी आई", "api": "ए पी आई", "gpu": "जी पी यू", "cpu": "सी पी यू",
    "isro": "इसरो", "nasa": "नासा", "upi": "यू पी आई", "ipl": "आई पी एल", "gdp": "जी डी पी",
    "rbi": "आर बी आई", "sebi": "सेबी", "iit": "आई आई टी", "ev": "ई वी", "evs": "ई वीज़",
    "model": "मॉडल", "models": "मॉडल्स", "google": "गूगल", "youtube": "यूट्यूब", "meta": "मेटा",
    "microsoft": "माइक्रोसॉफ्ट", "apple": "ऐपल", "amazon": "अमेज़न", "tesla": "टेस्ला",
    "elon": "इलॉन", "musk": "मस्क", "nvidia": "एनवीडिया", "gemini": "जेमिनी", "claude": "क्लॉड",
    "podcast": "पॉडकास्ट", "comment": "कमेंट", "comments": "कमेंट्स", "like": "लाइक",
    "subscribe": "सब्सक्राइब", "share": "शेयर", "video": "वीडियो", "channel": "चैनल",
    "startup": "स्टार्टअप", "startups": "स्टार्टअप्स", "data": "डेटा", "software": "सॉफ्टवेयर",
    "technology": "टेक्नोलॉजी", "tech": "टेक", "internet": "इंटरनेट", "online": "ऑनलाइन",
    "app": "ऐप", "apps": "ऐप्स", "robot": "रोबोट", "robots": "रोबोट्स", "chip": "चिप", "chips": "चिप्स",
    "billion": "बिलियन", "million": "मिलियन", "trillion": "ट्रिलियन", "percent": "परसेंट",
    "dollar": "डॉलर", "dollars": "डॉलर्स", "ok": "ओके", "okay": "ओके",
    "india": "इंडिया", "indian": "इंडियन", "usa": "यू एस ए", "uk": "यू के", "china": "चाइना",
}

def _load_overrides() -> None:
    """pronunciations.json (committed, edit it to fix a word that sounds awkward): {"word": "देवनागरी"}."""
    p = Path(__file__).with_name("pronunciations.json")
    try:
        for k, v in json.loads(p.read_text(encoding="utf-8")).items():
            if not k.startswith("_") and isinstance(v, str) and v.strip():
                LEXICON[k.lower()] = v.strip()
    except (OSError, json.JSONDecodeError):
        pass


_load_overrides()

_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9&'’\-\.]*[A-Za-z0-9]|[A-Za-z]")
_ACRONYM = re.compile(r"^[A-Z]{2,6}s?$")
_SENT = re.compile(r"[^।.?!]+[।.?!]*")


def _spell(word: str) -> str:
    return " ".join(LETTERS.get(c.upper(), c) for c in word if c.isalpha())


def _known(word: str, extra: dict) -> str | None:
    w = word.lower().rstrip(".")
    if w in extra:
        return extra[w]
    if w in LEXICON:
        return LEXICON[w]
    if _ACRONYM.match(word):                       # unknown ALL-CAPS token -> spell the letters
        return _spell(word.rstrip("s"))
    return None


def latin_words(text: str) -> set[str]:
    return set(_LATIN.findall(text))


def _sentences(text: str) -> list[str]:
    return [x.strip() for x in _SENT.findall(text) if x.strip()]


def apply(text: str, extra: dict) -> str:
    """Replace Latin words we can resolve (lexicon, acronyms, extra map); everything else is left untouched."""
    return _LATIN.sub(lambda m: _known(m.group(), extra) or m.group(), text)


async def transliterate_unknown(chat, words: list[str]) -> dict[str, str]:
    """Fallback for Latin words the main conversion left behind: {word: devanagari phonetics}."""
    if not words:
        return {}
    prompt = ("Write each English/Latin word below in Devanagari so a Hindi text-to-speech voice pronounces it the way "
              "an educated Indian says the English word (Gemini -> जेमिनी, quantum -> क्वांटम). "
              "Return ONLY a JSON object mapping each word exactly as given to its Devanagari form.\n"
              f"Words: {json.dumps(sorted(words), ensure_ascii=False)}")
    try:
        m = re.search(r"\{.*\}", await chat(prompt), re.DOTALL)
        data = json.loads(m.group()) if m else {}
        return {k.lower(): v.strip() for k, v in data.items() if isinstance(v, str) and v.strip() and k in words}
    except Exception:
        return {}


async def _convert(chat, text: str, hints: dict) -> str:
    hint_lines = "\n".join(f"{k} -> {v}" for k, v in hints.items())
    prompt = (
        "Convert this Hinglish narration (Roman-script Hindi mixed with English) into text for a HINDI text-to-speech "
        "voice that can only read Devanagari.\n"
        "Rules:\n"
        "- Hindi words: correct Devanagari spelling (hai -> है, nahi -> नहीं, kya -> क्या, zaroorat -> ज़रूरत).\n"
        "- English words: Devanagari phonetics exactly as an educated Indian says the English word "
        "(model -> मॉडल, calculator -> कैलकुलेटर, process -> प्रोसेस, hallucination -> हैलूसिनेशन).\n"
        "- Acronyms and letters are spelled out (AI -> ए आई, GDP -> जी डी पी).\n"
        "- Numbers, percentages and symbols written as spoken words (30% -> तीस परसेंट, 1-on-1 -> वन ऑन वन, 2 -> दो).\n"
        "- Tokens like @@1@@ are fixed words: copy them unchanged, exactly where they are.\n"
        "- Keep the same sentences in the same order with the same punctuation (। ? ,). Do not add, remove or "
        "rephrase anything. No Latin letters in the output.\n"
        + (f"Fixed pronunciations:\n{hint_lines}\n" if hint_lines else "")
        + f"\nNarration:\n{text}\n\nOutput ONLY the converted text.")
    return (await chat(prompt)).strip().strip('"')




def _hints(text: str) -> dict:
    return {w: LEXICON[w.lower()] for w in latin_words(text) if w.lower() in LEXICON}


_TOKEN = re.compile(r"@@\s*(\d+)\s*@@")


def _protect(text: str) -> tuple[str, dict[int, str]]:
    """Swap lexicon words for @@n@@ tokens so their pronunciation is exactly what we chose, not what the LLM guesses."""
    fixed: dict[int, str] = {}

    def sub(m: re.Match) -> str:
        w = m.group().lower().rstrip(".")
        if w in LEXICON:
            n = len(fixed) + 1
            fixed[n] = LEXICON[w]
            return f"@@{n}@@"
        return m.group()
    return _LATIN.sub(sub, text), fixed


async def to_speech(chat, text: str) -> str:
    """Hinglish narration -> Devanagari-phonetic TTS text. Falls back sentence by sentence if the LLM drifts."""
    protected, fixed = _protect(text)
    out = await _convert(chat, protected, {})
    src = _sentences(text)
    if len(_sentences(out)) != len(src) or {int(n) for n in _TOKEN.findall(out)} != set(fixed):
        parts = []                                  # LLM drifted or lost a token: go sentence by sentence
        for s in src:
            ps, fx = _protect(s)
            o = await _convert(chat, ps, {})
            if {int(n) for n in _TOKEN.findall(o)} != set(fx):      # still broken: use plain hint mode
                o, fx = await _convert(chat, s, _hints(s)), {}
            parts.append(_TOKEN.sub(lambda m: fx.get(int(m.group(1)), ""), o))
        out = " ".join(parts)
    else:
        out = _TOKEN.sub(lambda m: fixed.get(int(m.group(1)), ""), out)
    leftover = {w for w in latin_words(out) if _known(w, {}) is None}
    return apply(out, await transliterate_unknown(chat, sorted(leftover)))


async def prepare(chat, texts: list[str]) -> list[str]:
    return [await to_speech(chat, t) for t in texts]
