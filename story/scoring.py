"""Explainable story scoring. Story appeal (five weighted factors) and evidence quality are computed
separately; priority combines them so dramatic-but-thinly-supported stories do not rank high."""
import re

FACTORS = ("hook", "narrative", "payoff", "emotion", "standalone")
FACTOR_LABELS = {
    "hook": "Curiosity & hook", "narrative": "Narrative progression", "payoff": "Revelation / payoff",
    "emotion": "Emotional relevance", "standalone": "Standalone clarity",
}


def story_score(factors: dict[str, float], weights: dict[str, float]) -> float:
    """Weighted mean of 0-10 factor scores, scaled to 0-100."""
    total_w = sum(weights.get(f, 0) for f in FACTORS) or 1
    return round(sum(float(factors.get(f, 0)) * weights.get(f, 0) for f in FACTORS) / total_w * 10, 1)


def evidence_score(model_score: float, claims: list[dict], distinct_paras: int) -> tuple[float, dict]:
    """0-100. 50% the model's assessment, 30% share of claims whose quote was found in the cited text,
    20% breadth of supporting passages (3+ passages = full marks)."""
    quoted = [c for c in claims if c.get("quote_verified") is not None]
    verified = sum(1 for c in quoted if c["quote_verified"])
    frac = (verified / len(quoted)) if quoted else 0.0
    breadth = min(1.0, distinct_paras / 3)
    score = round(0.5 * model_score * 10 + 0.3 * frac * 100 + 0.2 * breadth * 100, 1)
    return score, {"model_assessment": round(model_score, 1), "quotes_checked": len(quoted),
                   "quotes_verified": verified, "claims": len(claims), "supporting_passages": distinct_paras}


def priority(story: float, evidence: float, influence: float, completeness: float | None = None,
             c_influence: float = 0.0) -> float:
    """story score scaled by evidence and by narrative completeness: influence=0 ignores a factor,
    influence=1 multiplies by factor/100. Completeness is separate from evidence: accurate quotes do not make a story whole."""
    p = story * (1 - influence + influence * evidence / 100)
    if completeness is not None:
        p *= 1 - c_influence + c_influence * completeness / 100
    return round(p, 1)


def _norm(t: str) -> str:
    t = t.lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-")
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def verify_quote(quote: str, texts: list[str]) -> bool | None:
    """True if the quoted words appear in the cited passages (ignoring case, punctuation, ellipses);
    None if there is no quote to check."""
    if not quote or not quote.strip():
        return None
    hay = " " + _norm(" ".join(texts)) + " "
    parts = [_norm(p) for p in re.split(r"\.{3}|…|\[\.\.\.\]", quote)]
    parts = [p for p in parts if len(p) >= 8] or [_norm(quote)]
    if not parts[0]:
        return False
    if all(p in hay for p in parts):
        return True
    flat = hay.replace(" ", "")                        # tolerate lost or extra spaces and hyphens from PDF extraction
    return all(p.replace(" ", "") in flat for p in parts)


def rescore(data: dict, weights: dict[str, float], influence: float, c_influence: float = 0.0) -> tuple[float, float, float]:
    """Recompute (story, evidence, priority) from stored factor scores - used when weights change."""
    f = {k: v["score"] for k, v in data.get("scores", {}).items()}
    s = story_score(f, weights)
    ev = data.get("evidence", {}).get("score_100", 0)
    comp = (data.get("completeness") or {}).get("score")
    return s, ev, priority(s, ev, influence, comp, c_influence)


# ── narrative completeness, nature and provenance checks (computed in code, never taken on the model's word) ──────

NATURE_CAP = {"story": 100, "anecdote": 60, "explainer": 40, "hypothetical": 30}
_HYPO = re.compile(r"\b(?:suppose|imagine|let'?s say|hypothetical(?:ly)?|for example|for instance|assume|say you|what if|would have)\b", re.I)
_MONTHS = ("january february march april may june july august september october november december "
           "jan feb mar apr jun jul aug sep sept oct nov dec").split()


def hypothetical_hits(texts: list[str]) -> int:
    return sum(len(_HYPO.findall(t)) for t in texts)


def date_basis(when: str, texts: list[str]) -> str:
    """'stated' if every number and month named in `when` appears in the cited text, else 'inferred'; '' when empty."""
    if not when.strip():
        return ""
    hay = " " + _norm(" ".join(texts)) + " "
    toks = re.findall(r"\d+(?:st|nd|rd|th)?|[A-Za-z]{3,}", when)
    need = [t.lower() for t in toks if t[0].isdigit() or t.lower() in _MONTHS]
    if not need:
        return "inferred"
    return "stated" if all(re.sub(r"(?:st|nd|rd|th)$", "", n) in hay for n in need) else "inferred"


def has_year(texts: list[str]) -> bool:
    return any(re.search(r"\b(?:1[5-9]|20)\d\d\b", t) for t in texts)


def completeness(d: dict, nature: str, page_span: int | None, story_type: str = "incident") -> tuple[float, dict]:
    """0-100: does the evidence contain a whole story? Separate from how accurate the quotes are.
    Parts present (turning point, outcome, conflict/stakes, a real chronology) plus how close the passages sit.
    The kind of piece caps it: an explainer can be perfectly quoted and still not be a story."""
    if story_type != "incident":
        return _completeness_other(d, nature, page_span, story_type)
    parts = {
        "turning_point": 25 if d.get("turning_point") else 0,
        "outcome": 25 if d.get("outcome") and not d.get("outcome_missing") else 0,
        "conflict_or_stakes": 15 if (d.get("conflict") or d.get("stakes")) else 0,
        "chronology": 15 if len([c for c in d.get("chronology", []) if c.get("basis") != "inferred"]) >= 3 else
        (7 if len(d.get("chronology", [])) >= 2 else 0),
    }
    if page_span is None:
        local = 10
    elif page_span <= 15:
        local = 20
    elif page_span >= 100:
        local = 0
    else:
        local = round(20 * (100 - page_span) / 85)
    parts["locality"] = local
    raw = sum(parts.values())
    cap = NATURE_CAP.get(nature, 100)
    return float(min(raw, cap)), {"parts": parts, "raw": raw, "cap": cap, "nature": nature, "page_span": page_span}


def _completeness_other(d: dict, nature: str, page_span: int | None, story_type: str) -> tuple[float, dict]:
    """The same 0-100 for the other types: what makes the material whole differs, and pages far apart are normal (a life, an argument, a list)."""
    chron = d.get("chronology") or []
    if story_type == "listicle":                                  # one item: a clear point with facts; no arc or outcome needed
        parts = {"point": 40 if (d.get("overview") or d.get("premise")) else 0, "facts": 40 if len(d.get("claims") or chron) >= 2 else 15,
                 "why_it_matters": 20 if d.get("audience_interest") or d.get("stakes") else 0}
    elif story_type == "explainer":
        parts = {"answer": 35 if d.get("turning_point") else 0, "steps": 35 if len(chron) >= 3 else (15 if len(chron) >= 2 else 0),
                 "misconception_or_stakes": 15 if (d.get("conflict") or d.get("stakes")) else 0, "context": 15 if d.get("overview") else 0}
    else:                                                          # biography, documentary
        parts = {"chronology": 30 if len(chron) >= 3 else (15 if len(chron) >= 2 else 0), "turning_point": 20 if d.get("turning_point") else 0,
                 "outcome": 20 if d.get("outcome") and not d.get("outcome_missing") else 0, "conflict_or_stakes": 15 if (d.get("conflict") or d.get("stakes")) else 0,
                 "overview": 15 if d.get("overview") else 0}
    raw = sum(parts.values())
    cap = NATURE_CAP.get(nature, 100)
    return float(min(raw, cap)), {"parts": parts, "raw": raw, "cap": cap, "nature": nature, "page_span": page_span, "story_type": story_type}


_GAP_KEEP = re.compile(r"\b(outcome|result|year|date|when|who|name|identity|cause|why|reason|how many|consequence|ended|what happened)\b", re.I)
_HEDGE = re.compile(r"\b(unlikely|not likely|however|but the|probably not|although|may be confused|could be confused)\b", re.I)


def important_gaps(gaps: list[str], has_outcome: bool, limit: int = 3) -> list[str]:
    """Keep the few gaps that matter (outcome, date, who, why); drop price-level nitpicks the model tends to list."""
    out = [g.rstrip(". ") for g in gaps if _GAP_KEEP.search(g) and not re.search(r"\b(exact|specific)\b.*\b(price|value|figure|level)\b", g, re.I)]
    if not has_outcome and not any(re.search(r"outcome|result|ended", g, re.I) for g in out):
        out.insert(0, "the outcome")
    return list(dict.fromkeys(out))[:limit]


def real_title_flags(flags: list[str]) -> list[str]:
    """A name-clash note must name a famous different thing; hedged or self-cancelling notes are noise."""
    return [f for f in flags if "=" in f and not _HEDGE.search(f)]


def final_nature(model_nature: str, raw_texts: list[str], chronology_n: int, has_outcome: bool,
                 stated_dates: int | None = None, arc: dict | None = None, story_type: str = "incident") -> tuple[str, list[str]]:
    """Reconcile the model's label with evidence. Only ever downgrades (story -> anecdote/hypothetical).
    A real story is anchored in time: at least one date or period must be stated in the cited passages."""
    notes: list[str] = []
    nat = model_nature or "story"
    if story_type != "incident":                    # the single-event rules (actor and decision, a stated date, an outcome) belong to incident stories only
        if nat in ("story", "anecdote") and hypothetical_hits(raw_texts) >= 3 and chronology_n <= 2:
            notes.append("Passages read like a hypothetical walkthrough, not a documented subject.")
            nat = "hypothetical"
        return nat, notes
    if nat == "story" and arc:
        if arc.get("form") == "concept":
            notes.append("It teaches a rule or concept; the example is an illustration, not the subject.")
            nat = "explainer"
        elif arc.get("form") == "setup_example":
            notes.append("A worked example of a repeatable pattern or trade setup, not a one-off event: treated as an anecdote.")
            nat = "anecdote"
        elif not (arc.get("actor") and arc.get("decision") and arc.get("consequence")):
            notes.append("No clear actor, decision and consequence: treated as an anecdote, not a story with an arc.")
            nat = "anecdote"
    if nat == "story" and stated_dates == 0:
        notes.append("No date or period for these events is stated in the cited passages: treated as an anecdote, not a documented story.")
        nat = "anecdote"
    if nat in ("story", "anecdote") and hypothetical_hits(raw_texts) >= 3 and chronology_n <= 2:
        notes.append("Passages read like a hypothetical walkthrough, not a documented event.")
        nat = "hypothetical"
    if nat == "story" and (chronology_n < 3 or not has_outcome):
        notes.append("Fewer than 3 dated or ordered events or no stated outcome: treated as an anecdote, not a full story.")
        nat = "anecdote"
    return nat, notes
