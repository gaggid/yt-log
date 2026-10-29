"""Where the story happens (docs/TASKS_quality_overhaul.md task 3.12; audit 14.4 and 14.5). A table in `data/regions.json` gives, for each region of India that matters to the
channel, what people wear, what moves on the road, what the street looks like, how the weather feels, the police uniform, and a pool of short cutaway pictures of ordinary life
there (the "world inserts"). The registry is told the region so places and people look like the place, and `story2/inserts.py` draws on the pool so the world feels bigger than the
few rooms of the plot.

The table is data: add a region or an insert to the JSON file and it is used; nothing else changes."""
import json
import re
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).parent / "data" / "regions.json"
GENERIC = "generic"


@lru_cache(maxsize=1)
def table() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def _text_of(plan: dict) -> str:
    """The words in which a region can be named: the Material Pack, the blueprint's cold open and the plan's own title."""
    from . import material
    pack = material.pack(plan) if material.has(plan) else {}
    bp = plan.get("blueprint") or {}
    bits = [it.get("detail", "") + " " + it.get("where", "") for it in pack.get("items", [])] + [bp.get("cold_open", ""), bp.get("viewer_promise", ""), bp.get("central_question", "")]
    bits += [str(plan.get("settings", {}).get("video_title", ""))]
    return " ".join(bits).lower()


def detect(plan: dict, extra: str = "") -> list[str]:
    """The regions of the story, most mentioned first, then `generic`. The editor's own choice (`audience.region`) comes first when it names a region of the table."""
    t = table()
    chosen = str(((plan.get("settings") or {}).get("audience") or {}).get("region") or "").lower().strip()
    found: list[str] = []
    if chosen:
        for rid, r in t.items():
            if rid != GENERIC and (chosen == rid or chosen == r["label"].lower() or any(k in chosen or chosen in k for k in r["keywords"])):
                found.append(rid)
    text = _text_of(plan) + " " + extra.lower()
    counts = {}
    for rid, r in t.items():
        if rid == GENERIC or rid in found:
            continue
        n = sum(len(re.findall(r"(?<![a-z])" + re.escape(k) + r"(?![a-z])", text)) for k in r["keywords"])
        if n:
            counts[rid] = n
    found += [rid for rid, _ in sorted(counts.items(), key=lambda kv: -kv[1])][:2]
    return found + [GENERIC]


def note(plan: dict, extra: str = "") -> str:
    """What the registry is told about the region(s): clothing, vehicles, street, weather, police. Empty when only the general India table applies and the story names no region."""
    ids = [r for r in detect(plan, extra) if r != GENERIC]
    if not ids:
        return ""
    t = table()
    out = ["REGION OF THIS STORY (draw people and places so they could only be here; do not give every man the same plain kurta):"]
    for rid in ids:
        c = t[rid]["cues"]
        out.append(f"- {t[rid]['label']}: people wear {c['clothing']}. On the road: {c['vehicles']}. Streets and buildings: {c['street']}. Weather and light: {c['weather']}. Police: {c['police']}.")
    return "\n".join(out)


def cue_text(plan: dict) -> str:
    """One short sentence of regional character for a picture prompt (not used for pure object shots)."""
    ids = [r for r in detect(plan) if r != GENERIC]
    return ("" if not ids else f"{table()[ids[0]]['label']} setting: " + table()[ids[0]]["cues"]["street"].split(",")[0])


def pool(plan: dict, used: list[str] = ()) -> list[dict]:
    """The cutaway pictures available to the film: the region's own first, then the general ones, never one already used."""
    t = table()
    out = []
    for rid in detect(plan):
        for ins in t[rid]["inserts"]:
            if ins["id"] not in used and ins["id"] not in {o["id"] for o in out}:
                out.append({**ins, "region": rid})
    return out
