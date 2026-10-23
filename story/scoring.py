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


def priority(story: float, evidence: float, influence: float) -> float:
    """story score scaled by evidence: influence=0 ignores evidence, influence=1 multiplies by evidence/100."""
    return round(story * (1 - influence + influence * evidence / 100), 1)


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
    return bool(parts[0]) and all(p in hay for p in parts)


def rescore(data: dict, weights: dict[str, float], influence: float) -> tuple[float, float, float]:
    """Recompute (story, evidence, priority) from stored factor scores - used when weights change."""
    f = {k: v["score"] for k, v in data.get("scores", {}).items()}
    s = story_score(f, weights)
    ev = data.get("evidence", {}).get("score_100", 0)
    return s, ev, priority(s, ev, influence)
