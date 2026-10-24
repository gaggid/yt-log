"""Complete, literal descriptions for characters, places and objects. The image models draw exactly what is written and invent everything that is not,
so a description with a gap (no hair colour, no shoes, no materials) gives a different person or room in every scene. Each kind has a fixed list of
slots; the registry model must fill every one with concrete values (colours, materials, counts), the description sent to the image model is composed
from the slots, and any slot left empty or vague is reported so a person can fill it in."""

SLOTS: dict[str, list[tuple[str, str]]] = {
    "person": [("gender", "man, woman, boy or girl"), ("age", "age in years"), ("build", "height and build"), ("skin", "skin tone"),
               ("face", "face shape and distinctive features"), ("hair", "hair colour, length and style"), ("eyes", "eye colour"),
               ("top", "upper clothing, with colour"), ("bottom", "lower clothing, with colour"), ("footwear", "shoes, with colour"),
               ("accessories", "watch, glasses, bag, jewellery, or the word none"), ("expression", "usual expression")],
    "place": [("type", "what kind of place it is"), ("architecture", "structure and layout"), ("materials", "main materials and their colours"),
              ("light", "light sources, direction and time of day"), ("objects", "key furniture and objects, with counts"), ("size", "size and how crowded it is")],
    "prop": [("type", "what the object is"), ("shape", "shape and size"), ("material", "materials"), ("colour", "exact colours"),
             ("condition", "new, worn, damaged"), ("markings", "markings or lettering, or the word none")],
}
SLOTS["narrator"] = SLOTS["person"]

# words that say nothing a model can draw
VAGUE_VALUES = {"", "n/a", "na", "unknown", "tbd", "various", "typical", "generic", "standard", "normal", "regular", "usual", "appropriate", "nice", "good", "neutral",
                "average", "some", "etc", "and so on", "unspecified", "not specified", "casual", "formal", "professional", "business attire", "business casual"}
NONE_OK = {"accessories", "markings"}                     # "none" is a real answer for these


def clean(ap) -> dict[str, str]:
    return {str(k): " ".join(str(v).split()).strip(" .") for k, v in (ap or {}).items() if v is not None and str(v).strip()} if isinstance(ap, dict) else {}


def missing(kind: str, ap: dict | None) -> list[str]:
    """Slots that are empty or too vague to draw."""
    ap = clean(ap)
    out = []
    for key, _hint in SLOTS.get(kind, []):
        v = ap.get(key, "").lower()
        if v in VAGUE_VALUES or (v == "none" and key not in NONE_OK) or any(w in v.split() for w in ("etc", "various", "typical")):
            out.append(key)
    return out


def hints(kind: str) -> dict[str, str]:
    return dict(SLOTS.get(kind, []))


def describe(kind: str, ap: dict | None) -> str:
    """One sentence of everything the slots say, in the order a reader would draw it."""
    ap = clean(ap)
    if not ap:
        return ""
    g = lambda k: ap.get(k, "")
    if kind in ("person", "narrator"):
        bits = [", ".join(x for x in (g("gender"), (g("age") + " years old") if g("age") and g("age").isdigit() else g("age"), g("build")) if x)]
        bits += [f"{g('skin')} skin" if g("skin") else "", g("face"), g("hair") and f"hair: {g('hair')}", g("eyes") and f"{g('eyes')} eyes"]
        wear = ", ".join(x for x in (g("top"), g("bottom"), g("footwear")) if x)
        bits += [f"wearing {wear}" if wear else ""]
        if g("accessories") and g("accessories").lower() != "none":
            bits.append(f"with {g('accessories')}")
        if g("expression"):
            bits.append(f"usual expression: {g('expression')}")
    elif kind == "place":
        bits = [g("type"), g("architecture"), g("materials") and f"materials and colours: {g('materials')}", g("light") and f"light: {g('light')}",
                g("objects") and f"contains {g('objects')}", g("size")]
    else:
        bits = [g("type"), g("shape"), g("material") and f"made of {g('material')}", g("colour") and f"colour: {g('colour')}", g("condition"),
                g("markings") and g("markings").lower() != "none" and f"marked {g('markings')}"]
    return ". ".join(b[0].upper() + b[1:] if isinstance(b, str) and b else "" for b in bits if b).strip() + "."


def fixed_from(kind: str, ap: dict | None) -> list[str]:
    """The details that must be identical in every scene, written out in full (a name of an attribute is not a detail)."""
    ap = clean(ap)
    keys = {"person": ("hair", "face", "top", "bottom", "footwear", "accessories"), "narrator": ("hair", "face", "top", "bottom"),
            "place": ("materials", "light", "objects"), "prop": ("shape", "material", "colour", "markings")}.get(kind, ())
    return [f"{k}: {ap[k]}" for k in keys if ap.get(k) and ap[k].lower() != "none"]
