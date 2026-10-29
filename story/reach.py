"""Phase 1 extra scores (docs/TASKS_quality_overhaul.md tasks 7.1 and 7.7): what a story can become on screen and for an Indian audience, read from the story's own data with plain
rules (no model call, so they are free and run on every story card). They are shown as chips and never remove a story or change its priority.

  visual       how much there is to film: dated events, people, places and things (0 to 100)
  packaging    whether a curiosity title can be written from the facts: a turn, a conflict, stakes, a number (0 to 100)
  safety       flags a careful editor would look at: minors, sexual violence, graphic violence, suicide, a named private victim, a case that is still in court
  region       the regions of India the story names, and whether the region table (story2/data/regions.json) covers them
  sensitivity  community, caste or religion terms in the story
  practical    a lesson an ordinary viewer can use (money, family, safety, fraud words); an estimate"""
import json
import re
from pathlib import Path

REGIONS = Path(__file__).resolve().parent.parent / "story2" / "data" / "regions.json"
_SAFETY = (
    ("minor", r"\b(child|children|minor|boy aged|girl aged|teenager|student|school ?girl|school ?boy|toddler|infant|years? old boy|years? old girl)\b"),
    ("sexual violence", r"\b(rape|raped|sexual assault|molest|gang-?rape)\b"),
    ("graphic violence", r"\b(behead|mutilat|dismember|torture|hacked|slit|cleaver|stabbed|burnt alive|lynch)\w*"),
    ("suicide", r"\b(suicide|killed himself|killed herself|took his own life|took her own life)\b"),
    ("not yet convicted", r"\b(alleged|allegedly|accused|suspect|under trial|trial is pending|awaiting trial|chargesheet|has not been convicted|denies)\b"),
)
_PRACTICAL = re.compile(r"\b(scam|fraud|cheat|loan|bank|upi|otp|money|savings|insurance|job|salary|property|land|safety|police|complaint|family|health|doctor|medicine|app|phone|password)\b", re.I)
_COMMUNITY = re.compile(r"\b(hindu|muslim|sikh|christian|jain|buddhist|dalit|brahmin|rajput|jat|yadav|bania|adivasi|caste|community|religion|communal)\b", re.I)


def _text(d: dict, title: str = "") -> str:
    bits = [title, str(d.get("premise", "")), str(d.get("overview", "")), str(d.get("conflict", "")), str(d.get("stakes", "")), str(d.get("turning_point", "")), str(d.get("outcome", ""))]
    bits += [str(c.get("what", "")) for c in d.get("chronology", []) if isinstance(c, dict)]
    bits += [f"{p.get('name', '')} {p.get('role', '')}" for p in d.get("people", []) if isinstance(p, dict)]
    bits += [str(x) for x in d.get("claims", [])]
    return " ".join(bits)


def _regions() -> dict:
    try:
        return json.loads(REGIONS.read_text(encoding="utf-8"))
    except OSError:
        return {}


def regions_in(text: str) -> list[str]:
    low = text.lower()
    out = []
    for rid, r in _regions().items():
        if rid != "generic" and any(re.search(r"(?<![a-z])" + re.escape(k) + r"(?![a-z])", low) for k in r.get("keywords", [])):
            out.append(rid)
    return out


def scores(d: dict, title: str = "") -> dict:
    text = _text(d, title)
    chron = [c for c in d.get("chronology", []) if isinstance(c, dict)]
    people = [p for p in d.get("people", []) if isinstance(p, dict)]
    places = len(set(re.findall(r"\b(?:in|at|near|from|to)\s+([A-Z][a-z]{3,})", text)))
    visual = min(100, 10 * len(chron) + 6 * len(people) + 5 * min(places, 8) + (10 if re.search(r"\b(phone|train|knife|car|letter|bag|lorry|truck|house|shop)\b", text, re.I) else 0))
    packaging = (25 if d.get("turning_point") else 0) + (20 if d.get("conflict") else 0) + (20 if d.get("stakes") else 0) + (15 if re.search(r"\d", text) else 0) \
        + (10 if d.get("outcome") else 0) + (10 if re.search(r"\b(35|years?|decades?|first|never|only|secret|hidden)\b", text, re.I) else 0)
    flags = [name for name, rx in _SAFETY if re.search(rx, text, re.I)]
    victims = [p.get("name", "") for p in people if re.search(r"victim|deceased|murdered|killed|survivor", str(p.get("role", "")), re.I)]
    if victims:
        flags.append("named victim: use a role or an invented name")
    regs = regions_in(text)
    comm = sorted({m.group().lower() for m in _COMMUNITY.finditer(text)})
    return {
        "visual": min(100, visual), "packaging": min(100, packaging),
        "safety": {"flags": flags, "level": "high" if {"sexual violence", "minor", "suicide"} & set(flags) else "check" if flags else "ok"},
        "region": {"ids": regs, "covered": bool(regs), "note": "" if regs else "no region named: add region cues or choose one on the plan"},
        "sensitivity": {"terms": comm, "level": "check" if comm else "ok"},
        "practical": min(100, 15 * len(set(m.group().lower() for m in _PRACTICAL.finditer(text)))),
    }
