"""Batch C: compile a canonical scene into provider-specific image prompts, then check each prompt against the scene.

The canonical scene (story2.storyboard) stays the only source of truth. A prompt is always derived from it, carries the scene revision and a hash
of the inputs it was built from, and is reported stale when the scene changes. Compilers are deterministic templates: no model is called, so
compiling is free, repeatable and testable. Qwen gets an explicit labelled creative brief; FLUX gets natural prose with the camera and
materials near the end. Both preserve the same facts, continuity and exclusions."""
import hashlib
import json
import re

from . import describe, leak, mood, providers, styles
from .scene_schemas import NEEDS_ASSET
from .storyboard import fact_numbers

MAX_PROMPT_WORDS = 350             # the image models follow short prompts far better: past this, details get ignored (owner limit, 2026-10-26)
MAX_PROMPT_CHARS = 2400            # conservative: the gateway caps prompt length but does not publish the number
MAX_TEXT_WORDS = 8
# wording that asks the model for an effect without saying what is visible (brief: say the visible details instead)
VAGUE = ("several", "many", "a few", "various", "etc", "typical", "generic", "dramatic", "epic", "stunning", "viral", "intense", "tense", "tension", "powerful", "emotional", "masterpiece", "high quality",
         "breathtaking", "gripping", "haunting")
FLUX_STANDARD_NEGATIVE = styles.NEGATIVE
ADAPTERS = ("qwen", "flux")
# numbers that read as a factual claim: a percentage, a currency amount, a year or large figure, or a count of days, years, shares, dollars.
# Descriptive geometry ("45-degree angle", "3D", "2D") is not a claim.
_CLAIM_NUM = re.compile(r"(?:[$\u20b9\u00a3\u20ac]\s?(\d[\d,.]*)|\b(\d[\d,.]*)\s?%|\b(\d{4,})\b|\b(\d[\d,.]*)\s?-?\s?(?:percent|million|billion|crore|lakh|thousand|days?|weeks?|months?|years?|shares|dollars|rupees|points)\b)")
_STOP = set("a an the of and or to in on at with for from by is are was were be as it its this that his her their over under into out up down".split())
# public outdoor/transit locations where the background should feel naturally populated
_PUBLIC_RX = re.compile(
    r"\b(street|road|lane|chowk|bazaar|market|mela|ghat|square|plaza|crossing|intersection|"
    r"station|bus.?stand|bus.?stop|airport|terminal|platform|"
    r"stadium|ground|arena|"
    r"beach|shore|promenade|park|garden|fair)\b", re.I)


# ── helpers ─────────────────────────────────────────────────────────────────

_UNKNOWN = {"unknown", "n/a", "na", "none", "not specified", "unspecified", "tbd", "-", "not applicable"}


def _val(x) -> str:
    """A scene field as text, or "" when it only says it is unknown."""
    t = _s(x)
    return "" if t.lower() in _UNKNOWN else t


def _run(x, single: bool = False) -> str:
    """Lower-case the first letter of a sentence-case phrase ("Abstract void") so it reads inside a sentence, but keep names ("Knight Capital")."""
    t = _s(x)
    words = t.split()
    if (len(words) > 1 or single) and t[0].isupper() and words[0][1:].islower() and not any(w[0].isupper() for w in words[1:] if w):
        return t[0].lower() + t[1:]
    return t


def strip_negation(x: str) -> str:
    return re.sub(r"^(no|avoid|without|never show)\s+", "", _s(x), flags=re.I)


def _g(d: dict, *path, default=""):
    for k in path:
        d = d.get(k) if isinstance(d, dict) else None
        if d is None:
            return default
    return d if d != "" else default


def _s(x) -> str:
    return re.sub(r"\s+", " ", str(x or "")).strip().strip(".")


def _sent(*parts: str) -> str:
    return " ".join(p if p.endswith((".", "!", "?")) else p + "." for p in (x.strip() for x in parts) if p)


def _words(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", t.lower()) if w not in _STOP and len(w) > 1}


def covers(prompt: str, item: str, threshold: float = 0.6) -> bool:
    """Is the idea in `item` present in the prompt? Content-word overlap, so a re-phrased detail still counts."""
    need = _words(item)
    return not need or len(need & _words(prompt)) / len(need) >= threshold


def _aspect(fmt: str) -> str:
    return "tall vertical 9:16" if fmt == "9:16" else "wide horizontal 16:9"


def _safe_area(fmt: str) -> str:
    if fmt == "9:16":
        return ("Keep the key subject inside the central 80 percent of the frame, clear of the top 12 percent and the bottom 20 percent "
                "where captions and interface elements sit.")
    return "Keep the key subject inside the central 90 percent of the frame and leave the lowest 12 percent free of important detail for captions."


def source_hash(scene: dict, assets_used: list[dict], fmt: str, indian: bool = False, feeling: str = "") -> str:
    d = scene["data"]
    keep = {k: d.get(k) for k in ("visual_type", "subject", "action", "setting", "composition", "lighting", "palette", "atmosphere", "style",
                                  "layers", "text_on_screen", "facts", "exclusions", "feasibility", "narrative", "correction")}
    keep["assets"] = [(a["id"], a["rev"], a["data"].get("description"), a["data"].get("fixed"),
                       [r.get("id") for r in a["data"].get("reference_images", []) if r.get("approved")]) for a in assets_used]
    keep["fmt"] = fmt
    if indian:
        keep["indian"] = True
    if feeling:
        keep["feeling"] = feeling
    keep["shot"] = [(d.get("composition") or {}).get(k) for k in ("distance", "camera_angle", "perspective")]
    return hashlib.sha1(json.dumps(keep, sort_keys=True, default=str).encode()).hexdigest()[:12]


def assets_for(scene: dict, assets: list[dict]) -> list[dict]:
    ids = _g(scene["data"], "continuity", "assets", default=[])
    by_id = {a["id"]: a for a in assets}
    used = [by_id[i] for i in ids if i in by_id]
    style = [a for a in assets if a["kind"] == "style" and a not in used]
    return used + style[:1]                                    # the plan's look applies to every picture


def reference_plan(scene: dict, assets_used: list[dict], first_seen: dict[str, str]) -> dict:
    """Which registry assets would be sent as reference images (at most three) and in what role. An asset without an approved reference image
    yet is listed as `missing`: this scene creates it when it is the asset's first appearance.

    If `continuity.use_ref_assets` is set, only those asset IDs are eligible for reference images. This separates
    narrative continuity (asset is in the scene's world) from visual continuity (asset's reference sheet helps the image model).
    Key absent → include all refs (backwards compat for scenes made before this field existed)."""
    order = {"person": 0, "narrator": 0, "place": 1, "prop": 2, "style": 3}
    use_ids = _g(scene["data"], "continuity", "use_ref_assets", default=None)   # None = absent (old scene) → no filter
    refs, missing = [], []
    for a in sorted(assets_used, key=lambda x: order.get(x["kind"], 4)):
        # use_ids present → only listed IDs may contribute reference images (style assets always allowed)
        if use_ids is not None and a["kind"] != "style" and a["id"] not in use_ids:
            continue
        imgs = [r for r in a["data"].get("reference_images", []) if r.get("approved")]
        if imgs:
            refs.append({"asset_id": a["id"], "name": a["name"], "kind": a["kind"], "image_id": imgs[0].get("id"), "role": _role(a)})
        elif a["kind"] != "style":
            missing.append({"asset_id": a["id"], "name": a["name"], "kind": a["kind"],
                            "action": "create_reference" if first_seen.get(a["id"]) == scene["id"] else "needs_reference_before_this_scene"})
    return {"references": refs[:3], "dropped": [r["name"] for r in refs[3:]], "missing": missing}


def _role(a: dict) -> str:
    return {"person": "keep this person's face, build and clothing", "narrator": "keep this narrator's look", "place": "keep this place's layout and materials",
            "prop": "keep this object's shape and markings"}.get(a["kind"], "match this look")


def edit_instruction(change: str, keep: list[str], refs: list[dict]) -> str:
    """Edits are written as 'change X, keep Y' (the gateway has no masks). The first image is the one being edited; others say what they give."""
    parts = [f"Change only this: {_s(change)}."]
    if keep:
        parts.append("Keep unchanged: " + "; ".join(_s(k) for k in keep) + ".")
    for n, r in enumerate(refs[1:], 2):
        parts.append(f"Image {n}: {r['role']} ({r['name']}).")
    return " ".join(parts)


# ── shared pieces ───────────────────────────────────────────────────────────

def shot_distance(d: dict) -> str:
    return _s((d.get("composition") or {}).get("distance"))


def hidden_for(d: dict) -> set[str]:
    """Person slots (shoes, trousers, eyes, ...) the shot cannot show; see describe.hidden_slots."""
    return describe.hidden_slots(shot_distance(d), " ".join(_s(d.get(k)) for k in ("subject", "action")))


def feeling_texts(scene: dict, plan: dict | None) -> list[str]:
    """What names the scene's feeling: its own emotional_effect, then the director's emotion for its part of the video."""
    d = scene["data"]
    out = [_s((d.get("narrative") or {}).get("emotional_effect"))]
    by = ((plan or {}).get("settings") or {}).get("director", {}).get("by_segment", {})
    out += [_s(v.get("emotion")) for v in by.values() if v.get("segment_id") == scene.get("segment_id")]
    return [t for t in out if t]


def person_hide(a: dict, hide: set[str]) -> set[str]:
    """What the shot hides of this person: the shot's own list, plus the whole face for someone drawn only as a silhouette (a real person is never given a likeness).
    The prompt and the validator both use this, so the validator never demands a detail the prompt had to leave out."""
    return hide | ({"face", "eyes", "expression"} if a["data"].get("fictionalisation") == "real_person_no_likeness" else set())


def _ambient_hint(location: str, layers: dict) -> str:
    """One sentence added to the environment when the location is a public space but the background layers don't mention people or activity.
    Prevents scenes where a busy street has vehicles but no bystanders because the narration never named them."""
    if not location or not _PUBLIC_RX.search(location):
        return ""
    bg = _s(layers.get("background", ""))
    mid = _s(layers.get("middle", ""))
    if re.search(r"\b(people|person|crowd|pedestrians?|bystanders?|vendors?|passengers?|spectators?|activity|busy|commuters?|shoppers?)\b", bg + mid, re.I):
        return ""
    return "Background populated with bystanders, movement and activity natural to this kind of place."


def _subject_text(d: dict, people: list[dict], indian: bool = False, ref_index: dict[str, int] | None = None) -> str:
    out = [_s(d.get("subject"))]
    hide = hidden_for(d)
    ri = ref_index or {}
    for a in people:
        n = ri.get(a["id"])
        fic = a["data"].get("fictionalisation", "")
        if n is not None:
            # Reference image is being sent — use the image as the appearance source, not text, to avoid duplication.
            # Only keep fixed (must-be-visible) details that may not be obvious from the reference sheet angle.
            if a["kind"] in ("person", "narrator"):
                _det, fixed = describe.person_view(a, indian, person_hide(a, hide))
            else:
                fixed = a["data"].get("fixed", [])
            extra = "; ".join(_s(x) for x in fixed if _s(x))
            out.append(f"{a['name']}: refer to Image {n} for appearance")
            out.append(f"Always the same: {extra}" if extra else "")
        else:
            if a["kind"] in ("person", "narrator"):
                det, fixed = describe.person_view(a, indian, person_hide(a, hide))          # composed from the slots: what the frame hides is left out, the cast setting applies
                det = _s(det)
            else:
                det, fixed = _s(a["data"].get("description")), a["data"].get("fixed", [])
            extra = "; ".join(_s(x) for x in fixed if _s(x) and not covers(det, _s(x)))              # fixed details the description does not already say
            out.append(f"Appearance of {a['name']}: {det}" if det else "")
            out.append(f"Always the same: {extra}" if extra else "")
        if fic == "real_person_no_likeness" and a["kind"] == "person":
            out.append("Shown only as a silhouette, from behind or in deep shadow, with no recognisable face; no real person's likeness is implied")
    if set(describe.LOWER) <= hide and any(a["data"].get("appearance") for a in people if a["kind"] in ("person", "narrator")):
        out.append("The frame cuts the people off before the legs and feet: no shoes or trousers are visible")
    return _sent(*[x for x in out if x])


def _place_fixed(a: dict, d: dict) -> list[str]:
    """A place's fixed details, minus the ones a close shot cannot show (its layout, landmarks and crowd)."""
    hide = describe.hidden_place_slots(shot_distance(d)) | {"light"}                   # the scene has its own lighting line; a place's stored light would fight it
    return [x for x in a["data"].get("fixed", []) if not describe.is_hidden(_s(x), hide)] if a["kind"] == "place" else list(a["data"].get("fixed", []))


def _layers(d: dict) -> str:
    L = d.get("layers") or {}
    return " ".join(f"{k.capitalize()}: {_s(v)}." for k, v in (("foreground", L.get("foreground")), ("middle ground", L.get("middle")),
                                                              ("background", L.get("background"))) if _s(v))


def _positions(c: dict) -> str:
    return " ".join(f"{lbl}: {_s(c.get(k))}." for lbl, k in (("Left of frame", "left"), ("Centre of frame", "centre"), ("Right of frame", "right")) if _s(c.get(k)))


def _camera(c: dict) -> str:
    bits = [f"{_s(c.get('distance'))} shot" if _s(c.get("distance")) else "", f"{_s(c.get('camera_angle'))} angle" if _s(c.get("camera_angle")) else "",
            f"{_s(c.get('perspective'))} perspective" if _s(c.get("perspective")) else "", f"{_s(c.get('framing'))} framing" if _s(c.get("framing")) and _s(c.get("distance")).lower() not in _s(c.get("framing")).lower() else ""]
    return ", ".join(b for b in bits if b)


def latin_only(txt: str) -> bool:
    """On-screen text is English: Latin letters, digits and ordinary punctuation only (the models do not draw Devanagari reliably)."""
    return all(ord(ch) < 128 or ch in "\u2018\u2019\u201c\u201d\u2013\u2014\u2026\u00b0\u00b2\u00b3\u00b5\u20b9\u00a3\u20ac" for ch in txt)


def _exact_text(d: dict, notes: list[str]) -> tuple[str, list[dict]]:
    """Short English text written in quotes is drawn correctly by both image models (tested), on a sign, a headline or a screen, so it goes into the
    prompt exactly as written. Longer text, or text that is not English, is left to a later deterministic overlay: a long chart or document built by
    a model would look like evidence it is not."""
    shown, skipped = [], []
    for t in d.get("text_on_screen") or []:
        txt = _s(t.get("text"))
        if not txt:
            continue
        if len(txt.split()) > MAX_TEXT_WORDS or not latin_only(txt):
            skipped.append(t)
        else:
            shown.append(t)
    for t in skipped:
        why = "is not English" if not latin_only(_s(t["text"])) else "is too long to draw reliably"
        notes.append(f"text \"{_s(t['text'])}\" {why}; it is not drawn by the image model (add it as an overlay later)")
    if shown and any(len(x.get("text", "").split()) > 5 for x in shown):
        notes.append("long quoted text can repeat or drop a word, especially on FLUX; Qwen is the safer model for it")
    return shown, skipped


def _constraints(d: dict) -> tuple[list[str], list[str]]:
    must = [_s(x) for x in _g(d, "facts", "fixed", default=[]) if _s(x)]
    must += [f"{_s(p)}" for p in _g(d, "setting", "props", default=[]) if _s(p)]
    avoid = [_run(strip_negation(x)) for x in (d.get("exclusions") or []) if _s(x)]
    if _plate(d):
        must = []                                   # facts about the chart or document belong to the later overlay, not to the picture
    return list(dict.fromkeys(must)), list(dict.fromkeys(avoid))


_LEAD = {"the", "a", "an", "his", "her", "their", "its", "this", "these", "those", "one", "two", "three", "four", "five", "some", "each"}


def _lead_lower(t: str) -> str:
    """"The line rises" after "The single moment shown is": lower-case a leading function word, leave names alone."""
    t = _s(t)
    first = t.split(" ", 1)[0].lower()
    return t[0].lower() + t[1:] if first in _LEAD else t


def overlay_spec(d: dict) -> dict:
    """What a chart, document, map or screen must show, kept for the later deterministic build. Never sent to the image model."""
    return {"visual_type": d.get("visual_type"), "needs": _s(_g(d, "feasibility", "needs_asset")), "subject": _s(d.get("subject")), "shows": _s(d.get("action")),
            "text": [{"text": _s(t.get("text")), "placement": _s(t.get("placement"))} for t in d.get("text_on_screen") or [] if _s(t.get("text"))],
            "facts": [_s(x) for x in _g(d, "facts", "fixed", default=[]) if _s(x)]}


def _plate(d: dict) -> bool:
    return d.get("visual_type") in NEEDS_ASSET


# ── Qwen Image 2.1: explicit labelled brief, exclusions stated in the prompt (no negative field) ──

# What goes first when a prompt is over MAX_PROMPT_WORDS, in this order: wording that repeats the style, the framing line, the background layers (a shorter
# environment sentence replaces the long one), then the composition. Everything the picture is about stays.
_STEPS = (("drop", "colour"), ("drop", "framing"), ("swap", "environment"), ("swap", "setting"), ("drop", "composition"))


def _fit(sec: dict[str, str], sep: str, shorter: dict[str, str] | None = None) -> str:
    """Join the sections, trimming the least useful ones (in _STEPS) until the prompt is within MAX_PROMPT_WORDS."""
    def join() -> str:
        return sep.join(v.strip() for v in sec.values() if v.strip())
    for how, k in _STEPS:
        if len(join().split()) <= MAX_PROMPT_WORDS:
            break
        if how == "drop":
            sec.pop(k, None)
        elif shorter and k in shorter and k in sec:
            sec[k] = shorter[k]
    return join()


_LENS = (("extreme wide", "very wide-angle lens, deep focus, the people tiny in a vast place"), ("wide", "wide-angle lens, deep focus"),
         ("extreme close", "macro detail shot, very shallow depth of field"), ("close", "85mm portrait lens, shallow depth of field, background softly blurred"),
         ("medium", "50mm lens, natural perspective"))
_ANGLE = (("overhead", "camera directly overhead, looking straight down"), ("low", "camera low, looking up at the subject"), ("high", "camera high, looking down on the subject"),
          ("side", "side-on profile view"), ("over", "over the shoulder of a person in the foreground"), ("eye", "camera at eye level"))
NO_STRANGE = "no floating objects, platforms or symbols, no anime or cartoon faces, no extra people"


def shot_line(comp: dict) -> str:
    """The camera, written first and in the words a film crew uses: size, angle, lens. The picture model weights the opening of a prompt most."""
    dist, ang = _s(comp.get("distance")).lower(), _s(comp.get("camera_angle")).lower()
    if not dist and not ang:
        return ""
    lens = next((t for k, t in _LENS if k in dist), "")
    how = next((t for k, t in _ANGLE if k in ang), "")
    head = ", ".join(x for x in (f"{_s(comp.get('distance'))} shot" if dist else "", f"{_s(comp.get('camera_angle'))} angle" if ang else "") if x)
    return _sent("Shot: " + head, how, lens, f"{_s(comp.get('perspective'))} perspective" if _s(comp.get("perspective")) else "")


_ENV_LED = frozenset(("atmospheric", "metaphor", "transition"))   # visual types where the environment IS the subject


def compile_qwen(scene: dict, assets_used: list[dict], plan: dict, refs: dict) -> dict:
    d, cfg, notes = scene["data"], providers.get("qwen-image-2.1"), []
    fmt = plan["format"]
    w, h = d["output"]["width"], d["output"]["height"]
    plate = _plate(d)
    shown, _skipped = _exact_text(d, notes)
    must, avoid = _constraints(d)
    people = [a for a in assets_used if a["kind"] in ("person", "narrator")]
    indian = describe.indian_on(plan.get("settings"))
    look = styles.for_plan(plan.get("settings"))
    use_refs = bool(refs["references"]) and (plan.get("settings") or {}).get("scene_pictures", {}).get("mode") in ("edit", "auto")
    ref_index = {r["asset_id"]: i for i, r in enumerate(refs["references"], 1)} if use_refs else {}
    comp = d.get("composition") or {}

    # environment-led: atmospheric/metaphor/transition, or an establishing shot with no visible character.
    # These scenes lead with the world, not the person — promote environment/lighting/colour above subject/action.
    env_led = (d.get("visual_type") in _ENV_LED) or (d.get("visual_type") == "establishing" and not people and not plate)

    sec: dict[str, str] = {}
    sec["shot"] = shot_line(comp) or "Shot: a medium shot at eye level."                      # first: the opening words steer the whole picture
    style_line = look["look"]
    if env_led:
        boost = _s(look.get("atmosphere_boost", ""))
        if boost:
            style_line = style_line.rstrip(".") + f", {boost}."
    sec["style"] = "Visual style: " + _sent(style_line)
    if plate:
        notes.append("this visual needs a verified chart, document, screen, map or diagram: the picture is the illustrated scene around it; the exact content is added later")

    loc = _val(_g(d, "setting", "location"))
    env = "Environment: " + _sent(loc, f"Period: {_val(_g(d, 'setting', 'period'))}" if _val(_g(d, "setting", "period")) else "",
                                  f"Atmosphere: {_s(d.get('atmosphere'))}" if _s(d.get("atmosphere")) else "")
    ambient = "" if plate else _ambient_hint(loc, d.get("layers") or {})
    env_full = env + ("" if plate else " " + _layers(d)) + (f" {ambient}" if ambient else "")

    if env_led and not plate:
        # environment-led order: world first, subject/action after
        sec["environment"] = env_full
        sec["lighting"] = "Lighting: " + _sent(_s(d.get("lighting")) or "soft even light from a single clear direction")
        sec["colour"] = "Colour and mood: " + _sent(f"Palette: {_s(d.get('palette')) or look['palette']}", f"Mood shown through: {_s(d.get('atmosphere'))}" if _s(d.get("atmosphere")) else "")
        feel = mood.line(feeling_texts(scene, plan), hidden_for(d), bool(people))
        if feel:
            sec["feeling"] = feel
        sec["subject"] = "Main subject: " + _sent(_subject_text(d, people, indian, ref_index))
        sec["action"] = "Action and moment: " + _sent(f"The single moment shown is {_lead_lower(d.get('action'))}" if _s(d.get("action")) else
                                                      "A still, held moment with no competing action")
        sec["composition"] = "Composition: " + _sent(f"The subject sits {_s(comp.get('position'))}" if _s(comp.get("position")) else "", _positions(comp))
    else:
        # character-led / standard order: subject and action first
        if plate:
            sec["subject"] = "Main subject: " + _sent(_s(_g(d, "feasibility", "fallback")) or _subject_text(d, people, indian, ref_index),
                                                     ("Apart from the quoted words, any screen, paper or sign shows only abstract glowing light and shapes" if shown else
                                                      "Any screen, paper or sign in the scene shows only abstract glowing light and shapes, nothing readable"))
        else:
            sec["subject"] = "Main subject: " + _sent(_subject_text(d, people, indian, ref_index))
        sec["action"] = "Action and moment: " + _sent(f"The single moment shown is {_lead_lower(d.get('action'))}" if _s(d.get("action")) and not plate else
                                                      "A still, held moment with no competing action")
        sec["environment"] = env_full
        feel = "" if plate else mood.line(feeling_texts(scene, plan), hidden_for(d), bool(people))
        if feel:
            sec["feeling"] = feel
        sec["composition"] = "Composition: " + _sent(f"The subject sits {_s(comp.get('position'))}" if _s(comp.get("position")) else "", _positions(comp))
        sec["lighting"] = "Lighting: " + _sent(_s(d.get("lighting")) or "soft even light from a single clear direction")
        sec["colour"] = "Colour and mood: " + _sent(f"Palette: {_s(d.get('palette')) or look['palette']}", f"Mood shown through: {_s(d.get('atmosphere'))}" if _s(d.get("atmosphere")) else "")

    fixed_lines = [f"{a['name']}: {'; '.join(_s(x) for x in _place_fixed(a, d))}" for a in assets_used if _place_fixed(a, d) and a["kind"] not in ("style", "person", "narrator") and not plate]
    ref_lines = [f"Image {i}: {r['role']} ({r['name']})" for i, r in enumerate(refs["references"], 1)] if use_refs else []
    if fixed_lines or ref_lines:                                                              # reference images are named only when they are really sent
        sec["continuity"] = "Continuity: " + _sent(*(["Keep these the same as in the other pictures: " + "; ".join(fixed_lines)] if fixed_lines else []),
                                                   *(["Reference images: " + "; ".join(ref_lines)] if ref_lines else []))
    sec["framing"] = "Aspect ratio and framing: " + _sent(f"{w}x{h} pixels, {_aspect(fmt)}", _safe_area(fmt))
    if shown:
        sec["text"] = "Exact text: " + _sent("; ".join(f'the words "{_s(t["text"])}"' + (f" placed {_s(t['placement'])}" if _s(t.get("placement")) else "") for t in shown),
                                              "Written once in clear English letters, spelled exactly as quoted; no other text anywhere")
    else:
        sec["text"] = "Text: " + _sent("Every sign, shop front, notice board, poster, paper and screen is blank or turned away: no letters, words or marks anywhere in the picture")
    cons = []
    if must:
        cons.append("These must be clearly visible: " + "; ".join(must))
    if avoid:
        cons.append("These must not appear: " + "; ".join(avoid))
    if indian and not plate:
        cons.append("Any other person who appears is Indian too, with South Asian features and skin tone")
    cons.append("One clear focal point; " + NO_STRANGE)
    sec["constraints"] = "Constraints: " + _sent(*cons)
    prompt = _fit(sec, chr(10), {"environment": env})
    return _finish("qwen", "qwen-image-2.1", cfg, scene, prompt, "", sec, (w, h), refs, notes, plate, plan)


# ── FLUX.2 Klein: natural prose, exclusions as positive statements plus the supported negative_prompt ──

def compile_flux(scene: dict, assets_used: list[dict], plan: dict, refs: dict) -> dict:
    d, cfg, notes = scene["data"], providers.get("flux2-klein-9b"), []
    fmt = plan["format"]
    w, h = d["output"]["width"], d["output"]["height"]
    plate = _plate(d)
    shown, _skipped = _exact_text(d, notes)
    must, avoid = _constraints(d)
    people = [a for a in assets_used if a["kind"] in ("person", "narrator")]
    comp = d.get("composition") or {}
    indian = describe.indian_on(plan.get("settings"))
    look = styles.for_plan(plan.get("settings"))
    flux_cfg = providers.get("flux2-klein-9b")
    ref_index = {r["asset_id"]: i for i, r in enumerate(refs["references"], 1)} if (refs["references"] and flux_cfg["edits"]) else {}
    sec: dict[str, str] = {"style": _sent(look["look"])}
    if plate:
        notes.append("this visual needs a verified chart, document, screen, map or diagram: the picture is the illustrated scene around it; the exact content is added later")
    subject = _subject_text(d, people, indian, ref_index)
    sec["subject"] = _sent(_s(_g(d, "feasibility", "fallback")) or subject, "Any screen, paper or sign shows only abstract glowing light and shapes") if plate else _sent(subject)
    sec["action"] = "" if plate else _sent(f"{_s(d.get('action'))}" if _s(d.get("action")) else "The moment is still and held")
    loc = _val(_g(d, "setting", "location"))
    where = _sent(f"The scene is set in {_run(loc)}" if loc else "",
                  f"The period is {_run(_val(_g(d, 'setting', 'period')))}" if _val(_g(d, "setting", "period")) else "")
    ambient = "" if plate else _ambient_hint(loc, d.get("layers") or {})
    sec["setting"] = where + ("" if plate else " " + _layers(d)) + (f" {ambient}" if ambient else "")
    feel = "" if plate else mood.line(feeling_texts(scene, plan), hidden_for(d), bool(people))
    if feel:
        sec["feeling"] = feel
    pos = _positions(comp)
    sec["composition"] = _sent(f"The subject is placed {_run(comp.get('position'))}" if _s(comp.get("position")) and not plate else "") + " " + ("" if plate else pos)
    sec["lighting"] = _sent(f"{_s(d.get('lighting'))}" if _s(d.get("lighting")) else "Soft even light", f"The atmosphere is {_run(d.get('atmosphere'), True)}" if _s(d.get("atmosphere")) else "",
                            f"The palette is {_run(d.get('palette'), True)}" if _s(d.get("palette")) else "")
    mats = [] if plate else [_s(p) for p in _g(d, "setting", "props", default=[]) if _s(p)]
    sec["materials"] = _sent("Physical detail: " + ", ".join(mats)) if mats else ""
    style_asset = next((a for a in assets_used if a["kind"] == "style"), None)
    sec["treatment"] = _sent(f"Rendered as {look['short']}, {look['linework']}", styles.NOT_PHOTO)
    sec["camera"] = _sent(f"Camera: {_camera(comp)}" if _camera(comp) else "")
    fixed_lines = [f"{a['name']} ({'; '.join(_s(x) for x in _place_fixed(a, d))})" for a in assets_used if _place_fixed(a, d) and a["kind"] not in ("style", "person", "narrator") and not plate]
    sec["continuity"] = _sent("Consistent with the rest of the film: " + "; ".join(fixed_lines)) if fixed_lines else ""
    if refs["references"]:
        sec["references"] = _sent("; ".join(f"Image {i}: {r['role']} ({r['name']})" for i, r in enumerate(refs["references"], 1)))
    if shown:
        sec["text"] = _sent("The image contains exactly this text: " + "; ".join(f'"{_s(t["text"])}"' + (f" {_s(t['placement'])}" if _s(t.get("placement")) else "") for t in shown),
                            "Each text is written once, in clear English letters, spelled exactly as inside the quotes", "It contains no other writing")
    else:
        sec["text"] = _sent("Screens, papers and signs show no readable writing")
    if indian and not plate:
        sec["cast"] = _sent("Any other person who appears is Indian too, with South Asian features and skin tone")
    if must:
        sec["must"] = _sent("Clearly visible: " + "; ".join(must))
    if avoid:
        sec["avoid"] = _sent("The frame is free of " + ", ".join(avoid))        # positive-form statement; also sent as negative_prompt below
    sec["output"] = _sent(f"{w}x{h} pixels, {_aspect(fmt)} composition", _safe_area(fmt))
    prompt = _fit(sec, " ", {"setting": where})
    negative = ", ".join([*avoid, *FLUX_STANDARD_NEGATIVE.split(", ")]) if cfg["negative_prompt"] else ""
    return _finish("flux", "flux2-klein-9b", cfg, scene, prompt, negative, sec, (w, h), refs, notes, plate, plan)


def _finish(adapter: str, model: str, cfg: dict, scene: dict, prompt: str, negative: str, sections: dict, size: tuple[int, int],
            refs: dict, notes: list[str], plate: bool, plan: dict | None = None) -> dict:
    w, h, changed = providers.snap(size[0], size[1], cfg)
    if changed:
        notes.append(f"size {size[0]}x{size[1]} was snapped to {w}x{h} for this model")
    if refs["dropped"]:
        notes.append("only three reference images can be sent; left out: " + ", ".join(refs["dropped"]))
    d = scene["data"]
    corr = d.get("correction") or {}
    refs_ok = refs["references"][: cfg["max_references"]]
    mode = "edit" if (refs_ok and cfg["edits"]) else "generate"
    out = {"adapter": adapter, "model": model, "adapter_version": cfg["adapter_version"], "scene_rev": scene["rev"], "cast_indian": describe.indian_on((plan or {}).get("settings")), "feeling": mood.label(feeling_texts(scene, plan)),
           "mode": "overlay_plate" if plate and mode == "generate" else mode,
           "prompt": re.sub(r"[ \t]{2,}", " ", prompt).strip(), "negative_prompt": negative,
           "size": {"width": w, "height": h}, "references": refs_ok, "missing_references": refs["missing"],
           "params": {"steps": cfg["edit_steps"] if mode == "edit" else cfg["steps"], "cfg": cfg["edit_cfg"] if mode == "edit" else cfg["cfg"],
                      "note": "the gateway's own defaults are used; steps and cfg are shown, not overridden",
                      "style": styles.style_id((plan or {}).get("settings")), "lora": styles.loras_for(model, (plan or {}).get("settings"))},
           "sections": {k: v.strip() for k, v in sections.items() if v.strip()}, "notes": notes,
           "enhancer": {"used": False, "available": cfg["prompt_enhancer"]["available"], "original_prompt_kept": True}}
    if plate:
        out["overlay"] = overlay_spec(d)
    if corr.get("change"):
        out["edit_instruction"] = edit_instruction(corr["change"], list(corr.get("keep") or []), refs_ok)
    return out


COMPILERS = {"qwen": compile_qwen, "flux": compile_flux}


def compile_scene(scene: dict, assets: list[dict], plan: dict, first_seen: dict[str, str] | None = None) -> dict:
    """Both adapters, side by side, for one scene. Returns {"qwen": {...}, "flux": {...}} (each with its own validation)."""
    used = assets_for(scene, assets)
    refs = reference_plan(scene, used, first_seen or {})
    h = source_hash(scene, used, plan["format"], describe.indian_on(plan.get("settings")), mood.label(feeling_texts(scene, plan)))
    out = {}
    for name, fn in COMPILERS.items():
        c = fn(scene, used, plan, refs)
        c["source_hash"] = h
        out[name] = c
    return out


def first_appearances(scenes: list[dict]) -> dict[str, str]:
    seen: dict[str, str] = {}
    for sc in sorted(scenes, key=lambda x: (x["start_s"], x["seq"])):
        for a in _g(sc["data"], "continuity", "assets", default=[]):
            seen.setdefault(a, sc["id"])
    return seen


# ── validation: does the prompt still say what the scene says? ──────────────

def validate_prompt(c: dict, scene: dict, assets: list[dict], facts: str, prof: "leak.SourceProfile | None" = None) -> list[dict]:
    d, p = scene["data"], c["prompt"]
    both = p + " " + c.get("negative_prompt", "")
    issues: list[dict] = []

    def add(kind, text, level="error"):
        issues.append({"adapter": c["adapter"], "kind": kind, "text": text, "level": level})

    comp = d.get("composition") or {}
    plate = c["mode"] == "overlay_plate" or d.get("visual_type") in NEEDS_ASSET
    checks = [("location", _g(d, "setting", "location")), ("lighting", d.get("lighting")),
              ("camera distance", comp.get("distance")), ("camera angle", comp.get("camera_angle"))]
    if not plate:
        checks = [("subject", d.get("subject")), ("action", d.get("action"))] + checks
    for label, val in checks:
        if _s(val) and not covers(p, str(val)):
            add("missing", f"the {label} (“{_s(val)}”) is not in the prompt")
    if not _s(d.get("subject")):
        add("missing", "the scene has no subject")
    for f in ([] if plate else _g(d, "facts", "fixed", default=[])):
        if _s(f) and not covers(p, f):
            add("fact", f"fixed detail not in the prompt: {_s(f)}")
    used = assets_for(scene, assets)
    st = next((a for a in used if a["kind"] == "style"), None)
    if st and _s(st["data"].get("description")) and not covers(p, _s(st["data"]["description"]), 0.7):
        add("style", "the plan's visual style is not in the prompt")
    hide = hidden_for(d)
    for a in used:
        if a["kind"] == "style" or plate:
            continue
        fixed = describe.person_view(a, bool(c.get("cast_indian")), person_hide(a, hide))[1] if a["kind"] in ("person", "narrator") else _place_fixed(a, d)   # what the prompt really carries: the cast setting and the shot's view applied
        for fx in fixed:
            if _s(fx) and not covers(p, fx):
                add("continuity", f"{a['name']}: “{_s(fx)}” must stay the same but is not in the prompt")
    for ex in d.get("exclusions") or []:
        if _s(ex) and not covers(both, strip_negation(ex)):
            add("exclusion", f"exclusion not carried into the prompt: {_s(ex)}")
    for t in d.get("text_on_screen") or []:
        txt = _s(t.get("text"))
        if txt and not latin_only(txt):
            add("text", f"“{txt}” is not English; on-screen text must use English letters", "error")
        if txt and len(txt.split()) <= MAX_TEXT_WORDS and latin_only(txt) and f'"{txt}"' not in p:
            add("text", f"exact text “{txt}” is missing from the prompt")
    if d.get("visual_type") in NEEDS_ASSET and c["mode"] not in ("overlay_plate", "edit"):
        add("asset", "a chart, document or screen cannot be generated; the mode must be a background plate")
    known = fact_numbers(facts.lower()) | {str(c["size"]["width"]), str(c["size"]["height"]), "16", "9", "12", "20", "80", "90"}
    # an invented character's age or an object's count ("35 years old", "10 desks") is a design choice written in the registry, not a claim about the story
    for a_ in assets_for(scene, assets):
        known |= fact_numbers(" ".join([str(a_["data"].get("description") or ""), *map(str, a_["data"].get("fixed") or []), *map(str, (a_["data"].get("appearance") or {}).values())]).lower())
    for m in _CLAIM_NUM.finditer(p):
        n = next(g for g in m.groups() if g).strip(",.")
        if n and n not in known and n not in facts:
            add("number", f"the prompt states {n}, which is not in the story's facts")
    if len(p.split()) > MAX_PROMPT_WORDS:
        add("length", f"the prompt is {len(p.split())} words (limit {MAX_PROMPT_WORDS}); shorten the scene's details", "warn")
    if len(p) > MAX_PROMPT_CHARS:
        add("length", f"the prompt is {len(p)} characters (limit {MAX_PROMPT_CHARS}); shorten the scene's details", "warn")
    for w in VAGUE:
        if re.search(rf"\b{w}\b", p, re.I):
            add("vague", f"“{w}” asks for an effect without saying what is visible: describe the visible details instead", "warn")
    if not any(_s(comp.get(k)) for k in ("left", "centre", "right")) and d.get("visual_type") not in ("minimalist", "transition") and not plate:
        add("composition", "no left/centre/right description: the model decides the layout", "warn")
    if c["adapter"] == "qwen" and c.get("negative_prompt"):
        add("negative", "the Qwen endpoint ignores a negative prompt; none should be sent")
    if c["adapter"] == "flux" and not c.get("negative_prompt"):
        add("negative", "FLUX.2 Klein base honours a negative prompt but none was built", "warn")
    if len(c.get("references", [])) > providers.get(c["model"])["max_references"]:
        add("references", "more reference images than the endpoint accepts")
    for text in (p,):
        for f in leak.check(text, prof, scene=True) if prof else []:
            add("source_leak", f"{f.kind}: {f.text}")
    if c.get("source_hash") != source_hash(scene, used, scene["data"]["output"]["aspect_ratio"], bool(c.get("cast_indian")), c.get("feeling", "")):
        add("stale", "the scene changed after this prompt was compiled; compile again", "warn")
    lic = providers.get(c["model"])["licence"]
    if lic["status"] != "verified":
        add("licence", f"licence for {providers.get(c['model'])['label']} weights is {lic['status']}: {lic['note']}", "warn")
    return issues


# ── comparison ──────────────────────────────────────────────────────────────

def comparison(scene: dict, assets: list[dict], compiled: dict) -> dict:
    """The same scene through both compilers: which canonical elements each prompt carries, and how the settings differ."""
    d = scene["data"]
    comp = d.get("composition") or {}
    elements = [("subject", d.get("subject")), ("action", d.get("action")), ("location", _g(d, "setting", "location")), ("period", _g(d, "setting", "period")),
                ("camera distance", comp.get("distance")), ("camera angle", comp.get("camera_angle")), ("left of frame", comp.get("left")),
                ("centre of frame", comp.get("centre")), ("right of frame", comp.get("right")), ("lighting", d.get("lighting")), ("palette", d.get("palette")),
                ("style", d.get("style"))]
    elements += [("fixed fact", x) for x in _g(d, "facts", "fixed", default=[])] + [("exclusion", x) for x in d.get("exclusions") or []]
    rows = [{"element": k, "value": _s(v), **{a: covers(c["prompt"] + " " + c.get("negative_prompt", ""), str(v)) for a, c in compiled.items()}}
            for k, v in elements if _s(v)]
    models = {a: providers.public(c["model"]) for a, c in compiled.items()}
    return {
        "scene_id": scene["id"], "intent": d.get("generation_intent", ""), "coverage": rows,
        "settings": {a: {"model": c["model"], "adapter_version": c["adapter_version"], "mode": c["mode"], "size": c["size"], "steps": c["params"]["steps"],
                         "cfg": c["params"]["cfg"], "negative_prompt": bool(c["negative_prompt"]), "max_references": models[a]["max_references"],
                         "prompt_chars": len(c["prompt"])} for a, c in compiled.items()},
        "licence": {a: models[a]["licence"] for a in compiled},
        "evaluate_after_preview": ["composition adherence", "correct subjects and actions", "historical or factual consistency", "character and prop continuity",
                                   "clarity at the target aspect ratio", "prompt adherence", "correction passes needed", "latency and resource use",
                                   "licensing and intended-use fit"],
    }
