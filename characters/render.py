"""Render styles for characters: how a character is drawn (photographic or one of the app's painted looks) and which LoRAs go with it. The style, the image model and the LoRA set are chosen
when a character is created and locked once its canon is approved: C0 showed that the same prompt and seed with a different LoRA gives a different person, and an edit keeps the look of
its source picture, so a later switch would not restyle the canon, it would only break the likeness (docs/PLAN_characters.md 4.2)."""
from story2 import styles

DEFAULT_MODEL = "qwen-image-2.1"
REALISM_LORA = "purelens-realism"
REALISM_STRENGTH = 0.7                               # the gateway advises 0.6-0.8 to keep some of the model's own style
TRIGGERS = {REALISM_LORA: "p3r4l4ns"}                # used when the gateway's listing cannot be read; the listing is the authority (studio.lora_listing)

PHOTOREAL = {
    "label": "Photographic realism",
    "look": ("Photograph taken with an 85mm lens, natural skin texture with pores, soft natural light, shallow depth of field, realistic proportions, true-to-life colour. "
             "Not a painting, not an illustration, not a 3D render."),
    "loras": [{"name": REALISM_LORA, "strength": REALISM_STRENGTH}],
}

STYLES: dict[str, dict] = {"photoreal": PHOTOREAL, **{k: {"label": v["label"], "look": v["look"], "loras": []} for k, v in styles.PRESETS.items()}}
DEFAULT_STYLE = "photoreal"


def default() -> dict:
    return {"style": DEFAULT_STYLE, "model": DEFAULT_MODEL, "loras": [dict(x) for x in PHOTOREAL["loras"]]}


def clean(render: dict | None) -> dict:
    """A render setting with every field present and valid in shape (the LoRA names are checked against the gateway where the gateway is asked)."""
    r = render or {}
    style = r.get("style") if r.get("style") in STYLES else DEFAULT_STYLE
    loras = []
    for x in (r["loras"] if "loras" in r else STYLES[style]["loras"]) or []:
        name = str(x.get("name") if isinstance(x, dict) else x).strip()
        strength = float(x.get("strength", 1.0)) if isinstance(x, dict) else 1.0
        if name and len(loras) < 4:                                   # the gateway takes at most four
            loras.append({"name": name, "strength": max(-2.0, min(2.0, round(strength, 2)))})
    return {"style": style, "model": str(r.get("model") or DEFAULT_MODEL), "loras": loras}


def look(render: dict) -> str:
    return STYLES[render["style"]]["look"]


def trigger_words(render: dict, listing: dict[str, dict] | None = None) -> str:
    """The trigger words of the chosen LoRAs, from the gateway's listing where known, else the built-in table; added to the prompt of every drawing."""
    out = []
    for x in render["loras"]:
        t = ((listing or {}).get(x["name"]) or {}).get("trigger") or TRIGGERS.get(x["name"], "")
        if t and t not in out:
            out.append(t)
    return " ".join(out)
