"""Grade every video against the channel's own baseline.

Four components, each an index against the median of the reference shorts (1.0 = typical) turned into 0-100 by `100 * i / (i + 1)`, then weighted 40 / 30 / 15 / 15:
reach (views in the first 7 days), retention (average share of the video watched), engagement ((likes + comments + shares) per 1,000 views) and growth (subscribers gained per 1,000 views).
A component with no data is left out and the others renormalised (the grade is then `partial`). Medians, not averages: Shorts views are very uneven."""
import statistics
import time

from youtube import store as ytstore, sync

from . import features, store

WEIGHTS = {"reach": 0.40, "retention": 0.30, "engagement": 0.15, "growth": 0.15}
SHORT_MAX_S = 180
MIN_BASE = 5                        # reference videos needed before a baseline is trusted
LABEL_MIN = 8                       # graded videos before labels use percentiles
WINNER_ABS, FLOP_ABS = 62.0, 38.0   # labels before there are enough graded videos
WINNER_REACH = 3.0                  # a winner at or above this reach index earns sequels
MIN_VIEWS_RATE = 30                 # engagement and growth need this many views to mean anything


def video_metrics(v: dict, days: list[dict], now: float | None = None) -> dict:
    w = sync.windows(v, days, now)
    nv = sum(d["views"] for d in days)
    shares = sum(d["shares"] for d in days)
    has = bool(days) and nv > 0
    return {
        "views": v["views"], "v2": w["v2"], "v2_done": w["v2_done"], "v7": w["v7"], "v7_done": w["v7_done"], "v28": w["v28"], "v28_done": w["v28_done"], "has_days": bool(days),
        "pct": round(sum(d["avg_view_pct"] * d["views"] for d in days) / nv, 2) if has else None,
        "eng_k": round((v["likes"] + v["comments"] + shares) * 1000 / v["views"], 2) if v["views"] >= MIN_VIEWS_RATE else None,
        "growth_k": round(sum(d["subs"] for d in days) * 1000 / nv, 3) if has and v["views"] >= MIN_VIEWS_RATE else None,
    }


def _median(xs: list[float]) -> float:
    xs = [x for x in xs if x is not None]
    if not xs:
        return 0.0
    m = statistics.median(xs)
    return m if m > 0 else (statistics.fmean(xs) if xs else 0.0)


def reference_videos(now: float | None = None) -> list[tuple[dict, dict]]:
    """[(video, metrics)] for the channel's shorts that have daily numbers: the sample every baseline is a median of."""
    out = []
    for v in ytstore.videos():
        if v["duration_s"] and v["duration_s"] > SHORT_MAX_S:
            continue
        days = ytstore.days(v["video_id"])
        if days:
            out.append((v, video_metrics(v, days, now)))
    return out


def baseline(refs: list[tuple[dict, dict]] | None = None, now: float | None = None) -> dict:
    refs = refs if refs is not None else reference_videos(now)
    done = [m for _, m in refs if m["v7_done"]]
    return {"n": len(done), "reach": _median([m["v7"] for m in done]), "v2": _median([m["v2"] for _, m in refs if m["v2_done"]]), "retention": _median([m["pct"] for m in done]),
            "engagement": _median([m["eng_k"] for m in done]), "growth": _median([m["growth_k"] for m in done])}


def _score(value, base) -> float | None:
    if value is None or not base or base <= 0:
        return None
    i = value / base
    return 100.0 * i / (i + 1.0)


def grade(m: dict, base: dict) -> dict:
    """{grade, early_grade, partial, stage, reach_idx, parts}. `grade` needs the 7-day window; `early_grade` is reach alone from the 2-day window."""
    out = {"grade": None, "early_grade": None, "partial": False, "stage": "pending", "reach_idx": None, "parts": {}}
    if base["n"] < MIN_BASE:
        return out
    if m["v2_done"] and base["v2"] > 0:
        out["early_grade"] = round(_score(m["v2"], base["v2"]) or 0, 1)
        out["stage"] = "early"
    if not m["v7_done"]:
        return out
    parts = {"reach": _score(m["v7"], base["reach"]), "retention": _score(m["pct"], base["retention"]), "engagement": _score(m["eng_k"], base["engagement"]), "growth": _score(m["growth_k"], base["growth"])}
    have = {k: v for k, v in parts.items() if v is not None}
    if "reach" not in have:
        return out
    tot = sum(WEIGHTS[k] for k in have)
    out.update(grade=round(sum(WEIGHTS[k] * v for k, v in have.items()) / tot, 1), partial="retention" not in have, stage="final", parts={k: round(v, 1) for k, v in have.items()},
               reach_idx=round(m["v7"] / base["reach"], 2) if base["reach"] else None)
    return out


def distribution(base: dict, refs: list[tuple[dict, dict]]) -> list[float]:
    return sorted(g for g in (grade(m, base)["grade"] for _, m in refs) if g is not None)


def label(g: float | None, dist: list[float]) -> str:
    if g is None:
        return ""
    if len(dist) >= LABEL_MIN:
        hi, lo = dist[min(len(dist) - 1, int(len(dist) * 0.75))], dist[int(len(dist) * 0.25)]
        return "winner" if g >= hi and g > lo else "flop" if g <= lo and g < hi else "average"
    return "winner" if g >= WINNER_ABS else "flop" if g <= FLOP_ABS else "average"


def freeze_missing() -> int:
    """Freeze the features of every linked idea that has none yet (ideas made before the loop existed get today's settings of their short)."""
    from shorts import ideas as ideas_mod, store as sstore
    n = 0
    for l in ytstore.links():
        if not l["idea_id"] or store.outcome(l["idea_id"]):
            continue
        try:
            idea, short = ideas_mod.get(l["idea_id"]), sstore.get(l["short_id"])
        except (ValueError, sstore.ShortError):
            continue
        store.freeze_features(l["idea_id"], l["short_id"], features.freeze(idea, short, {"style": "unknown", "tone": "unknown"}))
        n += 1
    return n


def refresh(now: float | None = None) -> dict:
    """Recompute every grade and label from the numbers in the database. No model call."""
    now = now if now is not None else time.time()
    freeze_missing()
    refs = reference_videos(now)
    base = baseline(refs, now)
    dist = distribution(base, refs)
    vids = {v["video_id"]: v for v in ytstore.videos()}
    links = {l["idea_id"]: l for l in ytstore.links() if l["idea_id"]}
    graded = 0
    for o in store.outcomes():
        l = links.get(o["idea_id"])
        v = vids.get(l["video_id"]) if l else None
        if not v:
            continue
        m = video_metrics(v, ytstore.days(v["video_id"]), now)
        g = grade(m, base)
        graded += g["grade"] is not None
        store.save_grade(o["idea_id"], v["video_id"], {**m, "parts": g["parts"], "reach_idx": g["reach_idx"], "published_at": v["published_at"], "title": v["title"]},
                         g["grade"], g["early_grade"], g["partial"], label(g["grade"], dist), g["stage"])
    return {"baseline": base, "graded": graded, "reference": len(refs), "distribution": len(dist)}


def graded_rows(now: float | None = None) -> list[dict]:
    """Every graded short of the channel as one row: the app's ideas with their frozen features, and older videos with what the title tells."""
    now = now if now is not None else time.time()
    refs = reference_videos(now)
    base = baseline(refs, now)
    dist = distribution(base, refs)
    tags = store.video_tags()
    by_video = {o["video_id"]: o for o in store.outcomes() if o["video_id"]}
    rows = []
    for v, m in refs:
        g = grade(m, base)
        if g["grade"] is None:
            continue
        o = by_video.get(v["video_id"])
        f = dict(o["features"]) if o else {**features.title_features(v["title"]), "territory": tags.get(v["video_id"], "")}
        f.setdefault("territory", tags.get(v["video_id"], ""))
        f.update(hour=features.hour_band(v["published_at"]), weekday=features.weekday(v["published_at"]))
        rows.append({"video_id": v["video_id"], "idea_id": o["idea_id"] if o else "", "source": "app" if o else "history", "title": v["title"], "published_at": v["published_at"], "features": f,
                     "grade": g["grade"], "reach_idx": g["reach_idx"], "label": label(g["grade"], dist), "partial": g["partial"], "v7": m["v7"], "pct": m["pct"], "views": m["views"]})
    return rows
