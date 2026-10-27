"""Complete, literal descriptions for characters, places and objects. The image models draw exactly what is written and invent everything that is not,
so a description with a gap (no hair colour, no shoes, no materials) gives a different person or room in every scene. Each kind has a fixed list of
slots; the registry model must fill every one with concrete values (colours, materials, counts), the description sent to the image model is composed
from the slots, and any slot left empty or vague is reported so a person can fill it in."""

import re

SLOTS: dict[str, list[tuple[str, str]]] = {
    "person": [("ethnicity", "ethnic look, for example Indian (with region or community when the story names one)"), ("gender", "man, woman, boy or girl"), ("age", "age in years"), ("build", "height and build"), ("skin", "skin tone"),
               ("face", "face shape and distinctive features"), ("hair", "hair colour, length and style"), ("eyes", "eye colour"),
               ("top", "upper clothing, with colour"), ("bottom", "lower clothing, with colour"), ("footwear", "shoes, with colour"),
               ("accessories", "watch, glasses, bag, jewellery, or the word none"), ("expression", "usual expression")],
    "place": [("type", "what kind of place it is"),
              ("signature", "the 3 to 5 things that make this place recognisable as itself at a glance, with counts, specific to the story's world and period"),
              ("architecture", "structure and layout"), ("materials", "main materials and their colours"),
              ("light", "light sources, direction and time of day"), ("objects", "key furniture and objects, with counts"), ("size", "size and how crowded it is")],
    "prop": [("type", "what the object is"), ("shape", "shape and size"), ("material", "materials"), ("colour", "exact colours"),
             ("condition", "new, worn, damaged"), ("markings", "markings or lettering, or the word none")],
}
SLOTS["narrator"] = SLOTS["person"]

# words that say nothing a model can draw
VAGUE_VALUES = {"", "n/a", "na", "unknown", "tbd", "various", "typical", "generic", "standard", "normal", "regular", "usual", "appropriate", "nice", "good", "neutral",
                "average", "some", "etc", "and so on", "unspecified", "not specified", "casual", "formal", "professional", "business attire", "business casual"}
NONE_OK = {"accessories", "markings"}
OPTIONAL = {"ethnicity"}                                  # filled in by the plan's cast setting when the registry left it empty, so never a gap                     # "none" is a real answer for these


def clean(ap) -> dict[str, str]:
    return {str(k): " ".join(str(v).split()).strip(" .") for k, v in (ap or {}).items() if v is not None and str(v).strip()} if isinstance(ap, dict) else {}


def missing(kind: str, ap: dict | None) -> list[str]:
    """Slots that are empty or too vague to draw."""
    ap = clean(ap)
    out = []
    for key, _hint in SLOTS.get(kind, []):
        if key in OPTIONAL:
            continue
        v = ap.get(key, "").lower()
        if v in VAGUE_VALUES or (v == "none" and key not in NONE_OK) or any(w in v.split() for w in ("etc", "various", "typical")):
            out.append(key)
    return out


def hints(kind: str) -> dict[str, str]:
    return dict(SLOTS.get(kind, []))


LOWER = ("bottom", "footwear")
_SEATED = ("seated", "sitting", "sits ", "sat ", "behind a desk", "behind the desk", "at a desk", "at the desk", "at a table", "at the table", "behind a counter",
           "behind the counter", "behind the wheel", "in a chair", "in the chair", "on a chair", "on a sofa", "on the sofa", "leaning over", "waist-deep", "in the water")


_BEHIND = ("from behind", "seen from behind", "back to the camera", "back to camera", "backs to the camera", "silhouette", "turned away", "with his back", "with her back", "their backs")
_HANDS = ("close on the hands", "close-up of the hands", "close-up of hands", "only the hands", "hands only", "his hands", "her hands")
PLACE_CLOSE = ("signature", "architecture", "objects", "size")


def hidden_slots(distance: str, text: str = "") -> set[str]:
    """Person slots the camera cannot see in this shot, so the prompt must not mention them. A model told "brown loafers" draws brown loafers, even if it has to lift
    a foot to the man's shoulder to fit them in a waist-up frame. The same goes for every detail: legs and feet in close and medium shots (and for anyone seated behind
    something), the eyes and expression in a wide shot, the face of someone seen from behind or in silhouette, the face and hair when only the hands are in frame."""
    d = (distance or "").lower()
    t = (text or "").lower()
    hide: set[str] = set()
    if "extreme close" in d or "extreme-close" in d:
        hide |= {*LOWER, "top", "build"}
    elif "close" in d and "medium" not in d:
        hide |= set(LOWER)
    elif "medium close" in d or "medium-close" in d or "waist" in d or "bust" in d or "chest" in d:
        hide |= set(LOWER)
    elif "medium wide" in d or "medium-wide" in d or "cowboy" in d:
        hide |= {"footwear"}
    elif "medium" in d and "wide" not in d and "full" not in d:
        hide |= set(LOWER)
    if "wide" in d and "medium" not in d:
        hide |= {"eyes", "expression"}                                    # faces are a few pixels in a wide shot
        if "extreme" in d:
            hide |= {"face", "hair", "accessories"}
    if any(w in t for w in _SEATED):
        hide |= set(LOWER)
    if any(w in t for w in _BEHIND):
        hide |= {"face", "eyes", "expression"}
    if any(w in t for w in _HANDS):
        hide |= {"face", "eyes", "expression", "hair"}
    return hide


def hidden_place_slots(distance: str) -> set[str]:
    """A close shot shows a corner of a place, not its layout, its landmarks or how crowded it is."""
    d = (distance or "").lower()
    return set(PLACE_CLOSE) if "close" in d and "medium" not in d else set()


def describe(kind: str, ap: dict | None, hide: set[str] | frozenset = frozenset()) -> str:
    """One sentence of everything the slots say, in the order a reader would draw it. Slots in `hide` are left out (not visible in the shot)."""
    ap = clean(ap)
    ap = {k: v for k, v in ap.items() if k not in hide}
    if not ap:
        return ""
    g = lambda k: ap.get(k, "")
    if kind in ("person", "narrator"):
        bits = [", ".join(x for x in (f"{g('ethnicity')} {g('gender')}".strip(), (g("age") + " years old") if g("age") and g("age").isdigit() else g("age"), g("build")) if x)]
        bits += [f"{g('skin')} skin" if g("skin") else "", g("face"), g("hair") and f"hair: {g('hair')}", g("eyes") and f"{g('eyes')} eyes"]
        wear = ", ".join(x for x in (g("top"), g("bottom"), g("footwear")) if x)
        bits += [f"wearing {wear}" if wear else ""]
        if g("accessories") and g("accessories").lower() != "none":
            bits.append(f"with {g('accessories')}")
        if g("expression"):
            bits.append(f"usual expression: {g('expression')}")
    elif kind == "place":
        bits = [g("type"), g("signature") and f"recognisable by {g('signature')}", g("architecture"), g("materials") and f"materials and colours: {g('materials')}", g("light") and f"light: {g('light')}",
                g("objects") and f"contains {g('objects')}", g("size")]
    else:
        bits = [g("type"), g("shape"), g("material") and f"made of {g('material')}", g("colour") and f"colour: {g('colour')}", g("condition"),
                g("markings") and g("markings").lower() != "none" and f"marked {g('markings')}"]
    return ". ".join(b[0].upper() + b[1:] if isinstance(b, str) and b else "" for b in bits if b).strip() + "."


def is_hidden(fixed_line: str, hide) -> bool:
    """A fixed detail written as "footwear: brown loafers" whose slot is not visible."""
    return fixed_line.split(":", 1)[0].strip().lower() in hide


def fixed_from(kind: str, ap: dict | None) -> list[str]:
    """The details that must be identical in every scene, written out in full (a name of an attribute is not a detail)."""
    ap = clean(ap)
    keys = {"person": ("hair", "face", "top", "bottom", "footwear", "accessories"), "narrator": ("hair", "face", "top", "bottom"),
            "place": ("signature", "materials", "light", "objects"), "prop": ("shape", "material", "colour", "markings")}.get(kind, ())
    return [f"{k}: {ap[k]}" for k in keys if ap.get(k) and ap[k].lower() != "none"]


# ── the cast ────────────────────────────────────────────────────────────────

def cast_chosen(settings: dict | None) -> bool:
    """The editor has chosen who appears in the pictures (Indian cast or as the story says). A plan that has characters already counts as chosen: it was made before the choice was asked."""
    return "cast_indian" in (settings or {})


def indian_on(settings: dict | None) -> bool:
    """Characters are drawn as Indian people unless the plan switches it off (owner decision 2026-10-26: on by default for all plans)."""
    return bool((settings or {}).get("cast_indian", True))


_INDIAN = re.compile(r"\b(indian|desi|south asian|punjabi|gujarati|marathi|bengali|tamil|telugu|kannada|malayali|rajasthani|bihari|kashmiri|sindhi|hindu|sikh)\b", re.I)
_LIGHT_SKIN = re.compile(r"\b(pale|white|fair|light|pink|ruddy|freckled|porcelain|ivory|rosy|milky|pasty)\b", re.I)
_LIGHT_HAIR = re.compile(r"\b(blond|blonde|red|ginger|auburn|platinum|strawberry|sandy)\b", re.I)
_LIGHT_EYES = re.compile(r"\b(blue|green|grey|gray|hazel|violet)\b", re.I)


def indianise(ap: dict | None) -> dict:
    """The slots of a person drawn as an Indian person: ethnicity set, and colouring that cannot go with it (pale skin, blond hair, blue eyes) replaced. Anything the
    registry already wrote that fits (wheatish skin, black hair, an Indian region) is kept."""
    ap = dict(clean(ap))
    if not _INDIAN.search(ap.get("ethnicity", "")):
        ap["ethnicity"] = "Indian"
    if ap.get("skin") and _LIGHT_SKIN.search(ap["skin"]):
        ap["skin"] = "medium brown, wheatish"
    if ap.get("hair") and _LIGHT_HAIR.search(ap["hair"]):
        ap["hair"] = _LIGHT_HAIR.sub("black", ap["hair"])
    if ap.get("eyes") and _LIGHT_EYES.search(ap["eyes"]):
        ap["eyes"] = "dark brown"
    return ap


def indian_prefix(description: str) -> str:
    """For a person who has only a free-text description (no slots): put Indian in front of the first noun when it begins with man, woman, boy or girl."""
    d = (description or "").strip()
    if not d or _INDIAN.search(d):
        return d
    m = re.match(r"(?i)(an?\s+|the\s+)?(man|woman|boy|girl|male|female)\b", d)
    return f"Indian {d[0].lower() + d[1:]}" if m else f"Indian person: {d}"


def person_view(a: dict, indian: bool, hide=frozenset()) -> tuple[str, list[str]]:
    """The description and fixed details of a person as they go into a picture prompt: composed from the slots (so hidden ones are left out and the cast
    setting applies), or the stored text when the person has no slots."""
    d = a["data"]
    ap = d.get("appearance")
    if ap and (indian or hide):
        ap2 = indianise(ap) if indian else clean(ap)
        fixed = fixed_from(a["kind"], ap2) if indian else list(d.get("fixed", []))
        return describe(a["kind"], ap2, hide).strip(), [f for f in fixed if not is_hidden(f, hide)]
    text = (d.get("description") or "").strip()
    return (indian_prefix(text) if indian and a["kind"] in ("person", "narrator") else text), list(d.get("fixed", []))
