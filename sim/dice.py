"""Dice in code (docs/PLAN_simulation.md section 5.4). The model never decides whether a risky act works: it only writes what the roll says."""
import random

from . import state as S

TARGET = {"easy": 8, "normal": 12, "hard": 16}
SHIFT = {"gentle": -2, "fair": 0, "brutal": 2}
TIERS = ("disaster", "fail", "partial", "success", "great")
TIER_TEXT = {"disaster": "it goes badly wrong, with a real cost", "fail": "it fails", "partial": "it works only in part, or at a price",
             "success": "it works", "great": "it works better than hoped"}


def modifier(risk: dict, state: dict, trackers: list[dict]) -> tuple[int, list[str]]:
    """Up to three contributions taken from the trackers the plan linked to the act: a meter above or below its middle, items in use, relationship trust, a danger zone."""
    parts: list[tuple[int, str]] = []
    found: list[dict] = []
    for ref in risk.get("stats", []):
        t = S.find_tracker(trackers, ref, ("meter", "relation"))
        if t and t not in found:
            found.append(t)
    if risk.get("who"):                                    # what the acting person is carrying in a meter of their own (fatigue, health, nerve) always counts
        for t in trackers:
            if t["kind"] == "meter" and S.norm(t.get("owner", "")) == S.norm(risk["who"]) and t not in found:
                found.append(t)
    for t in found:
        v = state["trackers"].get(t["id"])
        if t["kind"] == "meter":
            lo, hi = float(t["min"]), float(t["max"])
            m = round((float(v) - (lo + hi) / 2) / ((hi - lo) / 10))
            if t.get("danger_above") is not None and t.get("danger_below") is None:          # a meter that is only dangerous when high (fatigue, noise): high hurts
                m = -m
            parts.append((max(-3, min(3, m)), f"{t['name']} {float(v):g}"))
            if (t.get("danger_below") is not None and float(v) <= float(t["danger_below"])) or (t.get("danger_above") is not None and float(v) >= float(t["danger_above"])):
                parts.append((-2, f"{t['name']} in danger"))
        elif t["kind"] == "relation":
            parts.append((max(-1, min(1, int(v["trust"]) // 2)), f"trust {t['name']}"))
    have = set()
    for t in trackers:
        if t["kind"] == "items":
            have |= {S.norm(n) for n in state["trackers"].get(t["id"], {})}
    used = [i for i in risk.get("items", []) if S.norm(i) in have]
    if used:
        parts.append((min(3, len(used)), "using " + ", ".join(used[:3])))
    total = sum(p[0] for p in parts[:6])
    return max(-6, min(6, total)), [f"{p[1]} {p[0]:+d}" for p in parts[:6]]


def roll(risk: dict, state: dict, trackers: list[dict], seed, chapter_idx: int, n: int, difficulty: str, salt: str = "") -> dict:
    rng = random.Random(f"{seed}:{chapter_idx}:{n}:{salt}")
    d = rng.randint(1, 20)
    mod, why = modifier(risk, state, trackers)
    target = TARGET.get(risk.get("difficulty", "normal"), 12) + SHIFT.get(difficulty, 0)
    total = d + mod
    margin = total - target
    tier = "disaster" if d == 1 else "great" if d == 20 or margin >= 5 else "success" if margin >= 0 else "partial" if margin >= -5 else "fail"
    return {"n": n, "who": risk.get("who", ""), "act": risk["act"], "die": d, "mod": mod, "why": why, "target": target, "total": total, "tier": tier, "text": TIER_TEXT[tier]}


def free(risk: dict, n: int) -> dict:
    """With dice off every act works."""
    return {"n": n, "who": risk.get("who", ""), "act": risk["act"], "die": 0, "mod": 0, "why": [], "target": 0, "total": 0, "tier": "success", "text": TIER_TEXT["success"], "dice_off": True}
