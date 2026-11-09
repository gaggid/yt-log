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
    named: set[str] = set()
    for ref in risk.get("stats", []):
        t = S.find_tracker(trackers, ref, ("meter", "relation"))
        if t and t not in found:
            found.append(t)
        if t:
            named.add(t["id"])
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
            if t["id"] not in named:                                                          # the person's own meters count when they hurt; a bonus only comes from what the plan named
                m = min(0, m)
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


STEP = 4                      # one step of difficulty (easy 8, normal 12, hard 16)


def _have(state: dict, trackers: list[dict]) -> dict:
    out = {}
    for t in trackers:
        if t["kind"] == "items":
            for n, e in (state["trackers"].get(t["id"]) or {}).items():
                out[S.norm(n)] = e
    return out


def things_effects(risk: dict, state: dict, trackers: list[dict]) -> tuple[int, int, list[str], bool]:
    """What skills, tools, a known recipe and the relation add to an act of making, persuading or taking: (modifier, target change, reasons, improvised)."""
    kind = risk.get("kind", "other")
    who = risk.get("who", "")
    craft = risk.get("craft") or {}
    mod, tgt, why, improvised = 0, 0, [], False
    if kind == "make":
        want = craft.get("skill") or risk.get("skill") or ""
        mine = (state["entities"].get(who) or {}).get("skills", [])
        if want:
            if any(S._same(sk, want) or (S._words(sk) & S._words(want)) for sk in mine):
                mod += 2
                why.append(f"skilled in {want} +2")
            else:
                tgt += 2
                improvised = True
                why.append(f"improvised ({want}) target +2")
        have = _have(state, trackers)
        tools = [S.norm(x) for x in craft.get("tools", [])]
        if tools and all(x in have for x in tools):
            mod += 1
            why.append("right tools +1")
            if any((have[x].get("props") or {}).get("condition") in ("damaged", "crude") for x in tools):
                mod -= 1
                why.append("worn tools -1")
        makes = craft.get("makes", "")
        if makes and any(S.norm(k) == S.norm(makes) or S._same(k, makes) for k in (state.get("recipes") or {})):
            tgt -= STEP
            why.append("known recipe: easier")
    elif kind in ("persuade", "take") and risk.get("target"):
        for t in trackers:
            if t["kind"] == "relation" and {S.norm(t.get("a")), S.norm(t.get("b"))} == {S.norm(who), S.norm(risk["target"])}:
                v = state["trackers"][t["id"]]
                m = (v["trust"] // 2 - v["tension"] // 2) if kind == "persuade" else -max(0, v["tension"]) // 2
                m = max(-3, min(3, m))
                if m:
                    mod += m
                    why.append(f"{'trust and tension' if kind == 'persuade' else 'their guard'} {m:+d}")
    return mod, tgt, why, improvised


def roll(risk: dict, state: dict, trackers: list[dict], seed, chapter_idx: int, n: int, difficulty: str, salt: str = "") -> dict:
    rng = random.Random(f"{seed}:{chapter_idx}:{n}:{salt}")
    d = rng.randint(1, 20)
    mod, why = modifier(risk, state, trackers)
    extra, tgt, more, improvised = things_effects(risk, state, trackers)
    mod = max(-6, min(6, mod + extra))
    why = why + more
    target = TARGET.get(risk.get("difficulty", "normal"), 12) + SHIFT.get(difficulty, 0) + tgt
    total = d + mod
    margin = total - target
    tier = "disaster" if d == 1 else "great" if d == 20 or margin >= 5 else "success" if margin >= 0 else "partial" if margin >= -5 else "fail"
    return {"n": n, "who": risk.get("who", ""), "act": risk["act"], "die": d, "mod": mod, "why": why, "target": target, "total": total, "tier": tier, "text": TIER_TEXT[tier],
            "kind": risk.get("kind", "other"), "makes": (risk.get("craft") or {}).get("makes", ""), "improvised": improvised}


def free(risk: dict, n: int) -> dict:
    """With dice off every act works."""
    return {"n": n, "who": risk.get("who", ""), "act": risk["act"], "die": 0, "mod": 0, "why": [], "target": 0, "total": 0, "tier": "success", "text": TIER_TEXT["success"], "dice_off": True,
            "kind": risk.get("kind", "other"), "makes": (risk.get("craft") or {}).get("makes", ""), "improvised": False}
