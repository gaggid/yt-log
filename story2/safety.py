"""Safety rules that run in code, not in a prompt (docs/AUDIT_2026-10-29.md section 3.3 and 14.5, owner decisions of 2026-10-29): a death or an injury is never given a
cheerful voice or a smiling face. Later tasks add attribution and name rules (1.6) and the cultural gate (8.9) to this module.
"""
import re

_D = "ऀ-ॣ०-ॿ"                                                    # the Devanagari block without the danda and double danda (a sentence ending in । must still end a word)
_W = lambda s: rf"(?<![{_D}\w])(?:{s})(?![{_D}\w])"             # a whole word, for Hindi and English alike

# a death, an injury, a violent act (Hindi and English). Whole words only: "मर" must not match "मरम्मत".
GRAVE = re.compile(_W(r"मार दिया|मार डाला|मारा|मारे|हत्या|कत्ल|क़त्ल|कातिल|क़ातिल|मर गया|मर गई|मर चुका|मर चुकी|मर चुके|मरा|मौत|मृत|चोट|घायल|ज़ख्म|ज़ख़्म|खून|लाश|शव|हमला|हादसा|दुर्घटना|बलात्कार|दम तोड़|"
                    r"kill(?:ed|ing|er)?|murder(?:ed|er)?|dead|death|died|dies|die|injur(?:ed|y|ies)|wound(?:ed)?|stab(?:bed)?|corpse|attack(?:ed)?|victim|accident"), re.I)
# a loss, as opposed to a danger: the voice is sad, not stern
LOSS = re.compile(_W(r"मौत|मृत|लाश|शव|मर गया|मर गई|मर चुका|मर चुकी|दम तोड़|हत्या|died|death|dead|killed|corpse|victim"), re.I)
BLOCKED_TAGS = ("happy", "cheerful", "excited", "laughs", "sarcastic")
SMILE = re.compile(r"\b(?:(?:an?|the)\s+)?(?:(?:slight|faint|small|gentle|soft|peaceful|warm|broad|wide|quiet|sad|steady|tight|half|knowing)[\s-]+)*"
                   r"(?:smiles?|smiling|smirk(?:s|ing)?|grin(?:s|ning)?|laugh(?:s|ing)?|beam(?:s|ing)?|cheerful(?:ly)?)\b", re.I)
STILL_FACE = "a still, unreadable face"


def grave(text: str) -> bool:
    return bool(GRAVE.search(text or ""))


def loss(text: str) -> bool:
    return bool(LOSS.search(text or ""))


def guard_tag(tag: str, *context: str) -> str:
    """The voice tag, replaced by a fitting one when it is cheerful and the sentence (or the one before it) is about a death or an injury."""
    if tag not in BLOCKED_TAGS:
        return tag
    ctx = " ".join(c for c in context if c)
    if not grave(ctx):
        return tag
    return "sad" if loss(ctx) else "serious"


def guard_tags(sentences: list[dict]) -> int:
    """Apply `guard_tag` to every sentence of a segment, in place (a sentence is judged with the one before it, because a tag lasts until the next one). Returns how many changed."""
    n = 0
    for i, s in enumerate(sentences):
        new = guard_tag(s.get("tag", ""), sentences[i - 1]["text"] if i else "", s.get("text", ""))
        if new != s.get("tag", ""):
            s["tag"] = new
            n += 1
    return n


def scrub_smiles(text: str) -> str:
    return SMILE.sub(STILL_FACE, text or "")


def scrub_scene(sc, narration: str) -> list[str]:
    """A scene drawn over narration about a death or an injury gets no smile, laugh or cheer in what it shows. `sc` is a SceneOut (or any object with the same string
    fields). Returns the names of the fields that were changed."""
    if not grave(narration):
        return []
    changed = []
    for f in ("subject", "action", "translation", "idea", "atmosphere", "emotional_effect", "lighting", "foreground", "middle", "background"):
        v = getattr(sc, f, None)
        if isinstance(v, str) and SMILE.search(v):
            setattr(sc, f, scrub_smiles(v))
            changed.append(f)
    return changed


# ── text on screen (task 3.10): a sign, a whiteboard or a wall shows words only when the story gives them ──────────────────────────────

REQUIRED_OBJECT = re.compile(r"name ?board|name ?plate|signboard|sign ?board|shop sign|street sign|headline|newspaper|bus board|destination board|station board|license plate|number plate|id card", re.I)
_WORD = re.compile(r"[A-Za-z0-9]+")


def scrub_text(sc, allowed: str) -> list[str]:
    """Remove from a scene's on-screen text every entry whose words the story does not give (an office wall that says FAKE, a whiteboard with a year the facts never state), unless
    the thing carrying the text is an object the story needs (a name board, a headline, a number plate). At most one text stays in a scene. `allowed` is the lower-case text of
    the facts, the story material and the event. Returns the texts removed."""
    entries = list(getattr(sc, "text_on_screen", []) or [])
    if not entries:
        return []
    ok = {w for w in _WORD.findall((allowed or "").lower())}
    carrier = " ".join(str(getattr(sc, f, "") or "") for f in ("subject", "action", "foreground", "middle", "background")) + " " + " ".join(getattr(sc, "props", []) or [])
    needed = bool(REQUIRED_OBJECT.search(carrier))
    keep, dropped = [], []
    for e in entries:
        words = [w.lower() for w in _WORD.findall(e.text)]
        known = all(w in ok or w in COMMON_SIGN_WORDS for w in words)
        (keep if (known or needed) and not keep else dropped).append(e)
    sc.text_on_screen = keep
    return [e.text for e in dropped]


COMMON_SIGN_WORDS = frozenset("the a an of and to in on at no entry exit open closed police station school hospital bank office market road street lane bus stop taxi stand hotel shop store".split())


# ── attribution and names (audit task 1.6; owner decisions of 2026-10-29) ─────────────────────────────────────

ATTRIBUTION_RULE = ("ATTRIBUTION (a legal and trust rule): until a court decision is among the facts, never state as plain fact that a named or described person committed a crime. "
                    "Say what the police say or allege: पुलिस के मुताबिक, पुलिस का आरोप है, आरोप है कि, बताया गया, कथित तौर पर. One attribution can cover the sentences that follow it, "
                    "but start each new accusation with one. Never call an offender a genius, a mastermind or a king.")
MARKERS = re.compile(_W(r"पुलिस के मुताबिक|पुलिस के अनुसार|पुलिस का कहना|पुलिस का आरोप|पुलिस ने बताया|आरोप है|आरोप लगा|आरोपी|कथित|कथित तौर पर|बताया गया|बताया जाता|माना जाता|"
                        r"police (?:say|said|allege|alleged|claim)|allegedly|alleged|accused|according to police|reportedly"), re.I)
CRIME_ACTS = re.compile(_W(r"मार दिया|मार डाला|हत्या की|कत्ल किया|क़त्ल किया|चुराया|चोरी की|ठगा|ठगी की|धोखा दिया|लूटा|लूट की|हमला किया|घायल किया|चोट पहुँचाई|चोट पहुंचाई|गायब कर दिए|"
                           r"kill(?:ed)?|murder(?:ed)?|stole|stolen|cheated|robbed|attacked|defrauded|siphoned|looted"), re.I)
_SENT = re.compile(r"(?<=[.!?।])\s+")


def accusations(texts: list[str]) -> list[str]:
    """Sentences that state a crime as fact: a crime act with no attribution in the same sentence or in the one before it."""
    out, prev_marked = [], False
    for t in texts:
        for sent in _SENT.split(t or ""):
            marked = bool(MARKERS.search(sent))
            if CRIME_ACTS.search(sent) and not marked and not prev_marked:
                out.append(sent.strip())
            prev_marked = marked                                                       # an attribution covers its own sentence and the one after it
    return out


VICTIM = re.compile(r"victim|deceased|killed|complainant|landlady|survivor|injured|minor|child|teenage|\bson\b|\bdaughter\b|retired", re.I)
SUSPECT = re.compile(r"suspect|accused|fugitive|offender|mastermind|arrested|culprit|scammer|fraudster|gang|handler|dropout", re.I)
STRONG_VICTIM = re.compile(r"victim|deceased|complainant|survivor|killed", re.I)
OFFICIAL = re.compile(r"police|inspector|constable|sub-?inspector|\bacp\b|\bdcp\b|\bsp\b|officer|judge|magistrate|minister|commissioner|investigator", re.I)
FEMALE = re.compile(r"landlady|mother|wife|woman|female|daughter|\bshe\b|\bher\b|girl|sister", re.I)
MALE = re.compile(r"\bson\b|\bman\b|\bmale\b|husband|father|\bhe\b|\bhis\b|\bboy\b|brother|dropout|fugitive", re.I)
NAMES_M = ("Rakesh", "Mahesh", "Anil", "Vijay", "Sanjay", "Dinesh", "Naveen", "Prakash", "Harish", "Lokesh")
NAMES_F = ("Sunita", "Kavita", "Rekha", "Meena", "Anita", "Shobha", "Pooja", "Neelam", "Usha", "Radha")
MODES = ("off", "victims", "victims_and_suspects")


def classify(person: dict) -> str:
    """victim, suspect, official or other, from the role words the story gives (an official is never renamed: they act in a public role)."""
    role = f"{person.get('role', '')}"
    if STRONG_VICTIM.search(role):
        return "victim"                                                          # "retired scientist and victim" is a private victim, whatever their job
    if SUSPECT.search(role):
        return "suspect"
    if OFFICIAL.search(role):
        return "official"
    if VICTIM.search(role):
        return "victim"
    return "other"


def suggest_name_map(public: dict, mode: str = "victims_and_suspects") -> dict[str, str]:
    """A name to use instead of the real one, for private victims (and, by default, people not yet convicted). Invented first names come from a fixed pool in a fixed order, so the
    same story always gets the same map; a person whose gender the role does not show gets a role label."""
    if mode not in MODES or mode == "off":
        return {}
    out, used_m, used_f = {}, 0, 0
    for p in public.get("people", []):
        kind = classify(p)
        if kind == "other" or kind == "official" or (kind == "suspect" and mode == "victims") or not p.get("name"):
            continue
        role = p.get("role", "")
        if FEMALE.search(role) and not MALE.search(role):
            out[p["name"]] = NAMES_F[used_f % len(NAMES_F)]
            used_f += 1
        elif MALE.search(role) and not FEMALE.search(role):
            out[p["name"]] = NAMES_M[used_m % len(NAMES_M)]
            used_m += 1
        else:
            out[p["name"]] = "the victim" if kind == "victim" else "the accused"
    return out


def _tokens(name: str) -> list[str]:
    return [t for t in re.split(r"\s+", name.strip()) if len(t) >= 4]


def apply_names(obj, name_map: dict[str, str]):
    """Replace real names by the mapped ones everywhere in a string, list or dict: the full name first, then each part of it (a first name or a surname on its own)."""
    if not name_map:
        return obj
    pairs = sorted(name_map.items(), key=lambda kv: -len(kv[0]))
    rules = []
    for real, new in pairs:
        rules.append((re.compile(_W(re.escape(real)), re.I), new))
    for real, new in pairs:
        for tok in _tokens(real):
            if tok.lower() != real.lower():
                rules.append((re.compile(_W(re.escape(tok)), re.I), new))

    def go(x):
        if isinstance(x, str):
            for rx, new in rules:
                x = rx.sub(new, x)
            return x
        if isinstance(x, list):
            return [go(v) for v in x]
        if isinstance(x, dict):
            return {k: go(v) for k, v in x.items()}
        return x
    return go(obj)


def real_names_in(texts: list[str], name_map: dict[str, str]) -> list[str]:
    """Real names (or parts of them) still present in any text: a leak of what the map hides."""
    found = []
    for real in name_map:
        for needle in [real] + _tokens(real):
            rx = re.compile(_W(re.escape(needle)), re.I)
            if any(rx.search(t or "") for t in texts) and needle not in found:
                found.append(needle)
    return found
