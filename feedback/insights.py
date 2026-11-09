"""What separates the winners from the flops: lifts by feature, the calibration of the idea score against real grades, and advice on thresholds. Pure code, no model.

Lift = median reach index of a group over the median of all graded shorts, pulled towards 1.0 on the log scale by n / (n + K) so a handful of videos cannot claim a big effect. A group under MIN_N is not reported."""
import math
import statistics

from . import outcomes

K = 4
MIN_N = 3
APP_DIMS = {
    "mechanism": lambda f: f.get("mechanisms") or [], "mech_pair": lambda f: [f.get("mech_pair")], "style": lambda f: [f.get("style")], "tone": lambda f: [f.get("tone")],
    "score_band": lambda f: [f.get("score_band")], "length": lambda f: [f.get("length")], "origin": lambda f: [f.get("origin")],
}
ALL_DIMS = {
    "hook_type": lambda f: [f.get("hook_type")], "has_number": lambda f: [f.get("has_number")], "hook_len": lambda f: [f.get("hook_len")], "territory": lambda f: [f.get("territory")],
    "hour": lambda f: [f.get("hour")], "weekday": lambda f: [f.get("weekday")],
}
SUBSCORES = ("hook_strength", "mechanism_count", "emotional_intensity", "completion_rate", "novelty", "progressive_revelation", "shareability")


def shrunk(raw: float, n: int) -> float:
    return math.exp(math.log(max(raw, 0.05)) * n / (n + K))


def lifts(rows: list[dict]) -> dict:
    ridx = [r["reach_idx"] for r in rows if r["reach_idx"] is not None]
    overall = statistics.median(ridx) if ridx else 0
    out: dict[str, list[dict]] = {}
    for dims, only_app in ((APP_DIMS, True), (ALL_DIMS, False)):
        for dim, getter in dims.items():
            groups: dict[str, list[dict]] = {}
            for r in rows:
                if only_app and r["source"] != "app":
                    continue
                for val in getter(r["features"]):
                    if val:
                        groups.setdefault(str(val), []).append(r)
            items = []
            for key, g in groups.items():
                gi = [x["reach_idx"] for x in g if x["reach_idx"] is not None]
                if len(g) < MIN_N or not gi or overall <= 0:
                    continue
                raw = statistics.median(gi) / overall
                items.append({"key": key, "n": len(g), "lift": round(shrunk(raw, len(g)), 2), "raw_lift": round(raw, 2), "median_grade": round(statistics.median(x["grade"] for x in g), 1),
                              "win_rate": round(sum(x["label"] == "winner" for x in g) / len(g), 2), "flop_rate": round(sum(x["label"] == "flop" for x in g) / len(g), 2),
                              "source": "app" if only_app else "all", "videos": [x["video_id"] for x in g][:12]})
            if items:
                out[dim] = sorted(items, key=lambda x: -x["lift"])
    return out


def best_hours(lf: dict) -> dict:
    return {"hour": lf.get("hour", []), "weekday": lf.get("weekday", [])}


def ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 5 or len(set(a)) < 2 or len(set(b)) < 2:
        return None
    ra, rb = ranks(a), ranks(b)
    ma, mb = statistics.fmean(ra), statistics.fmean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return round(num / den, 2) if den else None


def calibration(rows: list[dict]) -> dict:
    """Does the idea score predict the real grade? Rank correlation of the total and each sub-score with the grade, and the score line that best separates good from poor results."""
    app = [r for r in rows if r["source"] == "app" and r["features"].get("score")]
    out = {"n": len(app), "total": spearman([r["features"]["score"] for r in app], [r["grade"] for r in app]), "parts": {}, "advice": None}
    for k in SUBSCORES:
        pairs = [(r["features"]["subscores"][k], r["grade"]) for r in app if k in (r["features"].get("subscores") or {})]
        out["parts"][k] = spearman([p[0] for p in pairs], [p[1] for p in pairs]) if len(pairs) >= 5 else None
    best = None
    for t in (6.0, 6.5, 7.0, 7.5, 8.0, 8.5, 9.0):
        hi = [r["grade"] for r in app if r["features"]["score"] >= t]
        lo = [r["grade"] for r in app if r["features"]["score"] < t]
        if len(hi) >= 3 and len(lo) >= 3:
            gap = statistics.median(hi) - statistics.median(lo)
            if best is None or gap > best[0]:
                best = (gap, t, len(hi), len(lo))
    if best and best[0] >= 8:
        out["advice"] = {"threshold": best[1], "gap": round(best[0], 1), "n_above": best[2], "n_below": best[3],
                         "text": f"Ideas scoring {best[1]:g}+ graded {best[0]:.0f} points higher than the rest ({best[2]} against {best[3]} videos)."}
    return out


def experiments(rows: list[dict]) -> dict:
    """Exploit against explore per factor, from the labelled choices."""
    out = {}
    for factor in ("style", "tone", "territory"):
        groups: dict[str, list[float]] = {}
        for r in rows:
            src = (r["features"].get("choices") or {}).get(factor)
            if src in ("exploit", "explore", "idea", "model", "rotation"):
                groups.setdefault(src, []).append(r["grade"])
        if groups:
            out[factor] = {k: {"n": len(v), "median_grade": round(statistics.median(v), 1)} for k, v in groups.items()}
    return out


def overview() -> dict:
    rows = outcomes.graded_rows()
    lf = lifts(rows)
    return {"rows": [{k: v for k, v in r.items() if k != "features"} | {"features": r["features"]} for r in rows], "lifts": lf, "best_hours": best_hours(lf), "calibration": calibration(rows),
            "experiments": experiments(rows), "n_app": sum(r["source"] == "app" for r in rows), "n_history": sum(r["source"] == "history" for r in rows),
            "winners": sum(r["label"] == "winner" for r in rows), "flops": sum(r["label"] == "flop" for r in rows)}
