"""Words and phrases the narration must not lean on. The list is data: it grows from audit results (docs/AUDIT_2026-10-29.md, sections 3.3 and 14). Matching is
done here in code and the model is only told which ones it used, never given the whole list (a small model copies what it is shown)."""
import re

# stock phrases that every film of the audit used again and again (Hindi in Devanagari, English in Latin letters)
STOCK_PHRASES = (
    "सोचिए", "सोच सकते हैं", "अंदाज़ा लगा", "अंदाजा लगा", "यहाँ मुझे सबसे", "यहाँ मैं देख सकता", "मैं आपको", "चलिए मैं", "मैं चाहता हूँ कि आप",
    "पर यहाँ एक", "यहाँ एक बहुत बड़ा सवाल", "बहुत बड़ा सच", "एक बहुत ही",
)
# cliché nouns and filler adjectives that glamourise or pad
CLICHES = ("ghost", "mastermind", "genius", "empire", "iceberg", "mystery", "twist", "journey", "interesting", "massive", "amazing", "invisible",
           "जाल बिछा", "साम्राज्य", "परछाईं")
BANNED = STOCK_PHRASES + CLICHES

_SPACE = re.compile(r"\s+")


def norm(text: str) -> str:
    return _SPACE.sub(" ", (text or "").lower().replace("‍", "").replace("‌", "")).strip()


def hits(text: str, extra: tuple[str, ...] = ()) -> list[str]:
    """Banned items found in one text, each listed once, in the order of the list."""
    t = norm(text)
    out: list[str] = []
    for b in BANNED + tuple(extra):
        k = norm(b)
        if k and k in t and b not in out:
            out.append(b)
    return out


def count(texts: list[str]) -> int:
    """How many banned-phrase uses there are in a list of sentences (a sentence with two items counts twice)."""
    return sum(len(hits(t)) for t in texts)


# ── audience language profiles (audit section 14.5; task 2.15) ─────────────────────────────────────────────

PROFILES = {
    "metro_hinglish": {"label": "Metro Hinglish", "english_max": 0.30, "hindi_numbers": False, "jargon": True,
                       "note": "Natural urban Hinglish. English words are fine when people really say them. Numbers are written as words; an English number word is allowed only right before an English unit (thirty-five years)."},
    "hindi_first": {"label": "Hindi first", "english_max": 0.15, "hindi_numbers": True, "jargon": True,
                    "note": "Hindi first: use Hindi words wherever a Hindi speaker would, English only for common words everyone says (phone, police, bank, court). Write every number and year as Hindi number words (पैंतीस साल, उन्नीस सौ इक्यानवे)."},
    "senior_friendly": {"label": "Easy Hindi", "english_max": 0.08, "hindi_numbers": True, "jargon": True,
                        "note": "Easy Hindi for an older listener: short sentences, Hindi words and Hindi number words everywhere (पैंतीस साल, पाँच लाख रुपये), no English technical terms; say what a thing is in plain Hindi. English only for names."},
}
DEFAULT_PROFILE = "metro_hinglish"
# English words everyone says; anything else in Latin letters (apart from names) counts against a Hindi-first profile
COMMON_ENGLISH = frozenset("""phone mobile police bank court case number photo video message app call team office station hotel school college doctor hospital train bus car taxi road market shop
    mall card online account password email internet video news report file list video camera police station help sir madam sorry ok okay time minute second hour day week month year percent
    lakh crore rupees dollar paper note book pen tv radio fan light bulb ticket cash pin sim network software computer laptop screen link click video""".split())
JARGON = {"proclaimed offender": "ऐसा आदमी जिसे अदालत ने फ़रार घोषित कर दिया हो", "digital forensic": "फ़ोन और कंप्यूटर के डेटा की जाँच", "malicious": "नुकसान पहुँचाने वाला", "apk": "फ़ोन में डाली जाने वाली ऐप की फ़ाइल",
          "otp": "बैंक का एक बार चलने वाला कोड", "fir": "पुलिस में दर्ज पहली रिपोर्ट", "sigma": "विज्ञान में किसी नतीजे के पक्के होने का पैमाना", "algorithm": "कंप्यूटर के काम करने का तरीका",
          "forensic": "जाँच के लिए वैज्ञानिक तरीका", "syndicate": "अपराधियों का संगठित गिरोह", "inter-state cell": "कई राज्यों का मामला देखने वाली टीम", "crime branch": "दिल्ली पुलिस की अपराध शाखा"}
_EXPLAINS = re.compile(r"मतलब|यानी|यानि|अर्थात|मतलब यह|यह वह|को कहते हैं|कहलाता|means|that is|i\.e\.", re.I)
_UNIT = re.compile(r"^(?:years?|months?|days?|hours?|minutes?|seconds?|percent|lakh|crore|rupees?|km|kg|times|weeks?|people)\b", re.I)
_NUMBER_WORD = re.compile(r"\b(?:(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:-(?:one|two|three|four|five|six|seven|eight|nine))?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
                          r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|hundred|thousand|lakh|crore)\b", re.I)


def profile_of(settings: dict | None) -> str:
    p = ((settings or {}).get("audience") or {}).get("profile") or DEFAULT_PROFILE
    return p if p in PROFILES else DEFAULT_PROFILE


def profile_note(profile: str) -> str:
    return "AUDIENCE LANGUAGE: " + PROFILES.get(profile, PROFILES[DEFAULT_PROFILE])["note"]


def profile_problems(sentences: list[str], profile: str, said_before: list[str] = ()) -> list[str]:
    """What breaks the audience profile: too many English words, English number words where the profile wants Hindi ones, a technical term used without being explained."""
    cfg = PROFILES.get(profile, PROFILES[DEFAULT_PROFILE])
    out = []
    words = [w for s in sentences for w in re.findall(r"[ऀ-ॿ]+|[A-Za-z][A-Za-z'\-]*", s)]
    latin = [w for w in words if re.match(r"[A-Za-z]", w)]
    foreign = [w for w in latin if w.lower() not in COMMON_ENGLISH and not w[0].isupper()]                 # a capitalised word is a name
    if words and len(latin) / len(words) > cfg["english_max"] and len(latin) >= 4:
        out.append(f"Too many English words ({round(100 * len(latin) / len(words))}% against a limit of {round(100 * cfg['english_max'])}% for this audience); use Hindi words for: "
                   + ", ".join(sorted({w.lower() for w in foreign})[:10]))
    bad_nums = []
    for s in sentences:
        if not re.search(r"[ऀ-ॿ]", s):
            continue
        toks = s.split()
        for i, tok in enumerate(toks):
            if _NUMBER_WORD.fullmatch(re.sub(r"[^A-Za-z\-]", "", tok)):
                nxt = re.sub(r"[^A-Za-z]", "", " ".join(toks[i + 1:i + 2]))
                if cfg["hindi_numbers"] or not _UNIT.match(nxt or ""):
                    bad_nums.append(tok.strip(".,।?!"))
    if bad_nums:
        out.append(("Write numbers as Hindi number words, not English ones (e.g. पैंतीस साल): " if cfg["hindi_numbers"] else "Write a number as an English word only right before an English unit (thirty-five years); otherwise use Hindi number words: ")
                   + ", ".join(dict.fromkeys(bad_nums)))
    if cfg["jargon"]:
        text = " ".join(sentences)
        before = " ".join(said_before).lower()
        for term, plain in JARGON.items():
            if re.search(rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])", text, re.I) and term not in before:
                i = next((k for k, s in enumerate(sentences) if re.search(re.escape(term), s, re.I)), 0)
                near = " ".join(sentences[i:i + 2])
                if not _EXPLAINS.search(near):
                    out.append(f'The term "{term}" is used without being explained: say in plain Hindi what it is the first time (for example: {plain}).')
    return out
