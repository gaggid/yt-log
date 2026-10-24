"""Batch C: compile a canonical scene into provider-specific image prompts, then check each prompt against the scene.

The canonical scene (story2.storyboard) stays the only source of truth. A prompt is always derived from it, carries the scene revision and a hash
of the inputs it was built from, and is reported stale when the scene changes. Compilers are deterministic templates: no model is called, so
compiling is free, repeatable and testable. Qwen gets an explicit labelled creative brief; FLUX gets natural prose with the camera and
materials near the end. Both preserve the same facts, continuity and exclusions."""
import hashlib
import json
import re

from . import leak, providers, styles
from .scene_schemas import NEEDS_ASSET
from .storyboard import fact_numbers

MAX_PROMPT_CHARS = 2400            # conservative: the gateway caps prompt length but does not publish the number
MAX_TEXT_WORDS = 8
# wording that asks the model for an effect without saying what is visible (brief: say the visible details instead)
VAGUE = ("dramatic", "epic", "stunning", "viral", "intense", "tense", "tension", "powerful", "emotional", "masterpiece", "high quality",
         "breathtaking", "gripping", "haunting")
FLUX_STANDARD_NEGATIVE = styles.NEGATIVE
ADAPTERS = ("qwen", "flux")
# numbers that read as a factual claim: a percentage, a currency amount, a year or large figure, or a count of days, years, shares, dollars.
# Descriptive geometry ("45-degree angle", "3D", "2D") is not a claim.
_CLAIM_NUM = re.compile(r"(?:[$\u20b9\u00a3\u20ac]\s?(\d[\d,.]*)|\b(\d[\d,.]*)\s?%|\b(\d{4,})\b|\b(\d[\d,.]*)\s?-?\s?(?:percent|million|billion|crore|lakh|thousand|days?|weeks?|months?|years?|shares|dollars|rupees|points)\b)")
_STOP = set("a an the of and or to in on at with for from by is are was were be as it its this that his her their over under into out up down".split())


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


def source_hash(scene: dict, assets_used: list[dict], fmt: str) -> str:
    d = scene["data"]
    keep = {k: d.get(k) for k in ("visual_type", "subject", "action", "setting", "composition", "lighting", "palette", "atmosphere", "style",
                                  "layers", "text_on_screen", "facts", "exclusions", "feasibility", "narrative", "correction")}
    keep["assets"] = [(a["id"], a["rev"], a["data"].get("description"), a["data"].get("fixed"),
                       [r.get("id") for r in a["data"].get("reference_images", []) if r.get("approved")]) for a in assets_used]
    keep["fmt"] = fmt
    return hashlib.sha1(json.dumps(keep, sort_keys=True, default=str).encode()).hexdigest()[:12]


def assets_for(scene: dict, assets: list[dict]) -> list[dict]:
    ids = _g(scene["data"], "continuity", "assets", default=[])
    by_id = {a["id"]: a for a in assets}
    used = [by_id[i] for i in ids if i in by_id]
    style = [a for a in assets if a["kind"] == "style" and a not in used]
    return used + style[:1]                                    # the plan's look applies to every picture


def reference_plan(scene: dict, assets_used: list[dict], first_seen: dict[str, str]) -> dict:
    """Which registry assets would be sent as reference images (at most three) and in what role. An asset without an approved reference image
    yet is listed as `missing`: this scene creates it when it is the asset's first appearance."""
    order = {"person": 0, "narrator": 0, "place": 1, "prop": 2, "style": 3}
    refs, missing = [], []
    for a in sorted(assets_used, key=lambda x: order.get(x["kind"], 4)):
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

def _subject_text(d: dict, people: list[dict]) -> str:
    out = [_s(d.get("subject"))]
    for a in people:
        det = _s(a["data"].get("description"))
        fixed = "; ".join(_s(x) for x in a["data"].get("fixed", []))
        fic = a["data"].get("fictionalisation", "")
        out.append(f"Appearance of {a['name']}: {det}" if det else "")
        out.append(f"Always the same: {fixed}" if fixed else "")
        if fic == "real_person_no_likeness" and a["kind"] == "person":
            out.append("Shown only as a silhouette, from behind or in deep shadow, with no recognisable face; no real person's likeness is implied")
    return _sent(*[x for x in out if x])


def _layers(d: dict) -> str:
    L = d.get("layers") or {}
    return " ".join(f"{k.capitalize()}: {_s(v)}." for k, v in (("foreground", L.get("foreground")), ("middle ground", L.get("middle")),
                                                              ("background", L.get("background"))) if _s(v))


def _positions(c: dict) -> str:
    return " ".join(f"{lbl}: {_s(c.get(k))}." for lbl, k in (("Left of frame", "left"), ("Centre of frame", "centre"), ("Right of frame", "right")) if _s(c.get(k)))


def _camera(c: dict) -> str:
    bits = [f"{_s(c.get('distance'))} shot" if _s(c.get("distance")) else "", f"{_s(c.get('camera_angle'))} angle" if _s(c.get("camera_angle")) else "",
            f"{_s(c.get('perspective'))} perspective" if _s(c.get("perspective")) else "", f"{_s(c.get('framing'))} framing" if _s(c.get("framing")) else ""]
    return ", ".join(b for b in bits if b)


def _exact_text(d: dict, notes: list[str]) -> tuple[str, list[dict]]:
    """Exact on-screen text goes into the image only when it is short and the scene is not a chart, document or screen. Everything else is
    left to a later deterministic overlay: image models misspell, and a fabricated chart or document would look like evidence."""
    shown, skipped = [], []
    for t in d.get("text_on_screen") or []:
        txt = _s(t.get("text"))
        if not txt:
            continue
        if d.get("visual_type") in NEEDS_ASSET or len(txt.split()) > MAX_TEXT_WORDS:
            skipped.append(t)
        else:
            shown.append(t)
    for t in skipped:
        notes.append(f"text \"{_s(t['text'])}\" is not drawn by the image model; add it as an overlay later")
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

def compile_qwen(scene: dict, assets_used: list[dict], plan: dict, refs: dict) -> dict:
    d, cfg, notes = scene["data"], providers.get("qwen-image-2.1"), []
    fmt = plan["format"]
    w, h = d["output"]["width"], d["output"]["height"]
    plate = _plate(d)
    shown, _skipped = _exact_text(d, notes)
    must, avoid = _constraints(d)
    people = [a for a in assets_used if a["kind"] in ("person", "narrator")]
    nar = d.get("narrative") or {}
    look = styles.for_plan(plan.get("settings"))
    sec: dict[str, str] = {"style": "Visual style: " + _sent(look["look"])}                    # first: the opening words steer the whole picture
    if plate:
        notes.append("this visual needs a verified chart, document, screen, map or diagram: the picture is the illustrated scene around it; the exact content is added later")
    sec["objective"] = "Image objective: " + _sent(f"Create a {_aspect(fmt)} {look['short']} for a story-driven video. Its role in the story: {_s(nar.get('purpose'))}",
                                                   f"The viewer should come away with this: {_s(nar.get('new_information') or nar.get('takeaway'))}" if _s(nar.get("new_information") or nar.get("takeaway")) else "")
    if plate:
        sec["subject"] = "Main subject: " + _sent(_s(_g(d, "feasibility", "fallback")) or _subject_text(d, people),
                                                 "Any screen, paper or sign in the scene shows only abstract glowing light and shapes, nothing readable")
    else:
        sec["subject"] = "Main subject: " + _sent(_subject_text(d, people))
    sec["action"] = "Action and moment: " + _sent(f"The single moment shown is {_lead_lower(d.get('action'))}" if _s(d.get("action")) and not plate else
                                                  "A still, held moment with no competing action")
    sec["environment"] = "Environment: " + _sent(_val(_g(d, "setting", "location")), f"Period: {_val(_g(d, 'setting', 'period'))}" if _val(_g(d, "setting", "period")) else "",
                                                 f"Atmosphere: {_s(d.get('atmosphere'))}" if _s(d.get("atmosphere")) else "") + ("" if plate else " " + _layers(d))
    comp = d.get("composition") or {}
    sec["composition"] = "Composition: " + _sent(f"The subject sits {_s(comp.get('position'))}" if _s(comp.get("position")) else "", _positions(comp), f"Camera: {_camera(comp)}" if _camera(comp) else "")
    sec["lighting"] = "Lighting: " + _sent(_s(d.get("lighting")) or "soft even light from a single clear direction")
    style_asset = next((a for a in assets_used if a["kind"] == "style"), None)
    sec["treatment"] = "Visual treatment: " + _sent(f"{look['short']}, {look['linework']}", styles.NOT_PHOTO)
    sec["colour"] = "Colour and mood: " + _sent(f"Palette: {_s(d.get('palette')) or look['palette']}", f"Mood shown through: {_s(d.get('atmosphere'))}" if _s(d.get("atmosphere")) else "")
    fixed_lines = [f"{a['name']}: {'; '.join(_s(x) for x in a['data'].get('fixed', []))}" for a in assets_used if a["data"].get("fixed") and a["kind"] != "style" and not plate]
    ref_lines = [f"Image {i}: {r['role']} ({r['name']})" for i, r in enumerate(refs["references"], 1)]
    sec["continuity"] = "Continuity: " + _sent(*(["Keep these exactly the same as in the other pictures: " + "; ".join(fixed_lines)] if fixed_lines else ["No recurring people or objects in this picture"]),
                                               *(["Reference images: " + "; ".join(ref_lines)] if ref_lines else []))
    sec["framing"] = "Aspect ratio and framing: " + _sent(f"{w}x{h} pixels, {_aspect(fmt)}", _safe_area(fmt))
    if shown:
        sec["text"] = "Exact text: " + _sent("; ".join(f'the words "{_s(t["text"])}"' + (f" placed {_s(t['placement'])}" if _s(t.get("placement")) else "") for t in shown),
                                              "No other text appears anywhere in the image")
    else:
        sec["text"] = "Text: " + _sent("Screens show only abstract glowing light and shapes; papers, signs and labels carry no readable letters or numbers")
    cons = []
    if must:
        cons.append("These must be clearly visible: " + "; ".join(must))
    if avoid:
        cons.append("These must not appear: " + "; ".join(avoid))
    cons.append("One clear focal point; no extra people or objects beyond those described")
    sec["constraints"] = "Constraints: " + _sent(*cons)
    prompt = "\n".join(v.strip() for v in sec.values() if v.strip())
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
    look = styles.for_plan(plan.get("settings"))
    sec: dict[str, str] = {"style": _sent(look["look"])}
    if plate:
        notes.append("this visual needs a verified chart, document, screen, map or diagram: the picture is the illustrated scene around it; the exact content is added later")
    subject = _subject_text(d, people)
    sec["subject"] = _sent(_s(_g(d, "feasibility", "fallback")) or subject, "Any screen, paper or sign shows only abstract glowing light and shapes") if plate else _sent(subject)
    sec["action"] = "" if plate else _sent(f"{_s(d.get('action'))}" if _s(d.get("action")) else "The moment is still and held")
    where = _sent(f"The scene is set in {_run(_val(_g(d, 'setting', 'location')))}" if _val(_g(d, "setting", "location")) else "",
                  f"The period is {_run(_val(_g(d, 'setting', 'period')))}" if _val(_g(d, "setting", "period")) else "")
    sec["setting"] = where + ("" if plate else " " + _layers(d))
    pos = _positions(comp)
    sec["composition"] = _sent(f"The subject is placed {_run(comp.get('position'))}" if _s(comp.get("position")) and not plate else "") + " " + ("" if plate else pos)
    sec["lighting"] = _sent(f"{_s(d.get('lighting'))}" if _s(d.get("lighting")) else "Soft even light", f"The atmosphere is {_run(d.get('atmosphere'), True)}" if _s(d.get("atmosphere")) else "",
                            f"The palette is {_run(d.get('palette'), True)}" if _s(d.get("palette")) else "")
    mats = [] if plate else [_s(p) for p in _g(d, "setting", "props", default=[]) if _s(p)]
    sec["materials"] = _sent("Physical detail: " + ", ".join(mats)) if mats else ""
    style_asset = next((a for a in assets_used if a["kind"] == "style"), None)
    sec["treatment"] = _sent(f"Rendered as {look['short']}, {look['linework']}", styles.NOT_PHOTO)
    sec["camera"] = _sent(f"Camera: {_camera(comp)}" if _camera(comp) else "")
    fixed_lines = [f"{a['name']} ({'; '.join(_s(x) for x in a['data'].get('fixed', []))})" for a in assets_used if a["data"].get("fixed") and a["kind"] != "style" and not plate]
    sec["continuity"] = _sent("Consistent with the rest of the film: " + "; ".join(fixed_lines)) if fixed_lines else ""
    if refs["references"]:
        sec["references"] = _sent("; ".join(f"Image {i}: {r['role']} ({r['name']})" for i, r in enumerate(refs["references"], 1)))
    if shown:
        sec["text"] = _sent("The image contains exactly this text: " + "; ".join(f'"{_s(t["text"])}"' + (f" {_s(t['placement'])}" if _s(t.get("placement")) else "") for t in shown),
                            "It contains no other writing")
    else:
        sec["text"] = _sent("Screens show only abstract glowing light and shapes; papers and signs carry no readable letters or numbers")
    if must:
        sec["must"] = _sent("Clearly visible: " + "; ".join(must))
    if avoid:
        sec["avoid"] = _sent("The frame is free of " + ", ".join(avoid))        # positive-form statement; also sent as negative_prompt below
    sec["output"] = _sent(f"{w}x{h} pixels, {_aspect(fmt)} composition", _safe_area(fmt))
    prompt = " ".join(v.strip() for v in sec.values() if v.strip())
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
    out = {"adapter": adapter, "model": model, "adapter_version": cfg["adapter_version"], "scene_rev": scene["rev"],
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
    h = source_hash(scene, used, plan["format"])
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
    for a in used:
        if a["kind"] == "style" or plate:
            continue
        for fx in a["data"].get("fixed", []):
            if _s(fx) and not covers(p, fx):
                add("continuity", f"{a['name']}: “{_s(fx)}” must stay the same but is not in the prompt")
    for ex in d.get("exclusions") or []:
        if _s(ex) and not covers(both, strip_negation(ex)):
            add("exclusion", f"exclusion not carried into the prompt: {_s(ex)}")
    for t in d.get("text_on_screen") or []:
        txt = _s(t.get("text"))
        if txt and f'"{txt}"' in p and d.get("visual_type") in NEEDS_ASSET:
            add("text", f"“{txt}” must not be drawn by the image model on a chart, document or screen")
        if txt and len(txt.split()) <= MAX_TEXT_WORDS and d.get("visual_type") not in NEEDS_ASSET and f'"{txt}"' not in p:
            add("text", f"exact text “{txt}” is missing from the prompt")
    if d.get("visual_type") in NEEDS_ASSET and c["mode"] not in ("overlay_plate", "edit"):
        add("asset", "a chart, document or screen cannot be generated; the mode must be a background plate")
    known = fact_numbers(facts.lower()) | {str(c["size"]["width"]), str(c["size"]["height"]), "16", "9", "12", "20", "80", "90"}
    for m in _CLAIM_NUM.finditer(p):
        n = next(g for g in m.groups() if g).strip(",.")
        if n and n not in known and n not in facts:
            add("number", f"the prompt states {n}, which is not in the story's facts")
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
    if c.get("source_hash") != source_hash(scene, used, scene["data"]["output"]["aspect_ratio"]):
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
