"""The drama director (docs/PLAN_drama.md part B): where the story is in its arc and how tense this chapter should be, what has been neglected, how hard the risky acts should be after a run of easy chapters,
and the guarantee that a failed act costs something. Code decides; the planner is told. Nothing here names a genre."""
import math
import re

from . import health, state as S

PHASE_TEXT = {
    "setup":        "Set up: show what the people want, what stands in their way and what is at stake. Plant one question the reader wants answered. Pressure starts low but is already present.",
    "rising":       "Rising: complications. Each choice costs something, plans meet resistance, a small thing goes wrong, the opposition grows. Nobody gets what they want cleanly.",
    "midpoint":     "Midpoint: a reveal or a reversal that changes what the people believe, want or fear. After it the story cannot go back to how it was.",
    "crisis":       "Crisis: the pressure peaks. Failures hurt and last, allies are lost or divided, time runs short, a hard choice between two things the people care about.",
    "all_is_lost":  "All is lost: the protagonist loses the main tool, plan or advantage they have been relying on. The situation is worse than when the story began. This is the low point before the final push — do not resolve the pressure, deepen it.",
    "climax":       "Climax: the decisive confrontation or decision. Everything planted before is used. The people win, lose or change.",
    "resolution":   "Resolution: the consequences, shown. Close the main question; end on a final image, not a cliffhanger.",
    "release":      "Release: a pause after the peak, with a cost counted and a new question opened.",
    "complication": "A new complication: the situation changes or a new pressure arrives that the people did not expect.",
}

# Tension targets per phase per ending shape. The all-is-lost valley before the climax is the most
# important structural law: tension briefly drops before the highest peak so the climax feels earned.
TARGET = {"setup": 3, "rising": 5, "midpoint": 6, "crisis": 8, "all_is_lost": 4, "climax": 9, "resolution": 4, "release": 4, "complication": 5}
CURVES = {
    "triumph":     {"setup": 3, "rising": 5, "midpoint": 6, "crisis": 8, "all_is_lost": 4, "climax": 10, "resolution": 3, "release": 4, "complication": 5},
    "tragedy":     {"setup": 4, "rising": 7, "midpoint": 10, "crisis": 7, "all_is_lost": 5, "climax": 5, "resolution": 1, "release": 5, "complication": 6},
    "bittersweet": {"setup": 3, "rising": 5, "midpoint": 8, "crisis": 6, "all_is_lost": 4, "climax": 9, "resolution": 5, "release": 4, "complication": 5},
    "open":        {"setup": 3, "rising": 5, "midpoint": 6, "crisis": 7, "all_is_lost": 5, "climax": 8, "resolution": 6, "release": 4, "complication": 5},
}

LENGTHS = (0, 6, 8, 12, 16, 24, 36, 48)
WAVE = 6
FINALE_AFTER = WAVE * 2          # open-ended stories enter a one-time finale arc after this many chapters
NEGLECT_AFTER = 3
THREAD_AFTER = 3
MAX_NEGLECTED = 4


def phase(idx: int, length: int) -> str:
    """The part of the arc chapter `idx` (1-based) belongs to. A planned length gives one arc; an open-ended story repeats a wave of six chapters then enters a finale arc."""
    if length and length > 0:
        if idx >= length:
            return "resolution"
        if idx == 1:
            return "setup"
        if idx == length - 1 and length >= 4:
            return "climax"
        if idx == max(2, round(length * 0.5)):
            return "midpoint"
        r = idx / length
        if r <= 0.2:   return "setup"
        if r <= 0.5:   return "rising"
        if r <= 0.72:  return "crisis"
        if r <= 0.82:  return "all_is_lost"
        return "climax"
    # open-ended: wave-based until FINALE_AFTER, then one closing arc
    if idx > FINALE_AFTER:
        return {1: "crisis", 2: "all_is_lost", 3: "climax"}.get(idx - FINALE_AFTER, "resolution")
    pos = (idx - 1) % WAVE + 1
    if pos == 1:
        return "setup" if idx == 1 else "complication"
    return {2: "rising", 3: "rising", 4: "midpoint", 5: "crisis", 6: "release"}[pos]


def target(idx: int, length: int, ending_shape: str = "") -> int:
    curve = CURVES.get(ending_shape, TARGET)
    ph = phase(idx, length)
    t = curve.get(ph, 5)
    if length and ph in ("rising", "crisis"):                                  # climbs a little inside a phase
        t += min(1, idx % 2)
    return t


def arc(idx: int, length: int, intensities: list[int], ending_shape: str = "") -> dict:
    ph = phase(idx, length)
    tgt = target(idx, length, ending_shape)
    last = intensities[-3:]
    note = ""
    if last and tgt > max(last):
        note = f"The last chapters reached {', '.join(str(x) for x in last)} out of 10; this one must reach about {tgt}: raise the pressure or the cost."
    elif last and tgt < min(last) - 1:
        note = f"The last chapters reached {', '.join(str(x) for x in last)} out of 10; this one can let the pressure ease a little (about {tgt})."
    left = (length - idx) if length else None
    return {"phase": ph, "target": tgt, "text": PHASE_TEXT[ph], "note": note, "last": last, "chapters_left": left}


_ENDING_NOTES = {
    "tragedy":    "This story ends in tragedy: costs must not reverse; each chapter from here deepens the loss rather than offering hope.",
    "triumph":    "This story ends in triumph: the people must earn it through real setbacks; the climax needs a genuine reversal before the win.",
    "bittersweet":"This story ends bittersweet: something must be won and something lost — both must land with equal weight.",
    "open":       "This story ends open: close the immediate pressure but leave the larger question unanswered.",
}


def arc_block(a: dict, idx: int, length: int, ending_shape: str = "") -> str:
    where = f"chapter {idx} of {length}" if length else f"chapter {idx} (an open-ended story)"
    shape_note = ""
    if ending_shape in _ENDING_NOTES and a["phase"] in ("crisis", "all_is_lost", "climax", "resolution"):
        shape_note = " " + _ENDING_NOTES[ending_shape]
    return f"## ARC AND PACING\n{where}, phase: {a['phase'].upper()}. {a['text']}\nTarget tension for this chapter: {a['target']} out of 10. {a['note']}{shape_note}".strip()


def all_is_lost_block() -> str:
    return ("## ALL IS LOST\n"
            "This chapter is the story's lowest point. The focus character must lose the main tool, plan or "
            "advantage they have been relying on. Their situation at the end of this chapter must be concretely "
            "worse than it was at the opening. Do not resolve the pressure — deepen it. The next chapter is the climax.")


def archive_phase_block(arc_phase: str, pressure: list[dict]) -> str:
    """Injected into the archive user message; narrows option count and forces finality at key phases."""
    clock_full = any(p.get("kind") == "clock_full" for p in pressure)
    if arc_phase == "climax" or clock_full:
        suffix = " and the deadline has passed" if clock_full else ""
        return (f"## OPTIONS RULE\nThis is the climax{suffix}. Write 1 or 2 options only. "
                "Each is a final, irreversible decision — no information-gathering, no waiting, no safe path. "
                "The story cannot continue without committing to one of them.")
    if arc_phase == "all_is_lost":
        return ("## OPTIONS RULE\nThe protagonist has just lost their main advantage. Write 1 or 2 options only. "
                "Both start from a position of loss. The person must decide what to try with nothing left.")
    if arc_phase == "resolution":
        return ("## OPTIONS RULE\nThe climax is past. Write 1 or 2 options that close the story: show the "
                "consequence, pay off a planted detail, or deliver the final image. Do not open new threads.")
    if arc_phase == "crisis":
        return ("## OPTIONS RULE\nThe pressure is peaking. Write 2 or 3 options. Each has a real cost; "
                "at least one burns something permanently — a resource, a relationship, an advantage. No safe path.")
    return ""


# ── what has been neglected ───────────────────────────────────────────────────

def neglected(rep: dict) -> list[dict]:
    """People not in the story for a while, goals, fears and secrets not used, threads left open: from the health numbers. Each has `keys`, the words a plan that deals with it would contain."""
    n = rep.get("chapters", 0)
    if n < NEGLECT_AFTER:
        return []
    out: list[dict] = []
    for name, s in (rep.get("spotlight") or {}).items():
        if s["away"] >= NEGLECT_AFTER:
            out.append({"text": f"{name} has not been in the story for {s['away']} chapters", "keys": {name.lower()}})
    order = {"secret": 0, "goal": 1, "fear": 2}
    for m in sorted([m for m in rep.get("material", []) if m["age"] >= NEGLECT_AFTER], key=lambda m: (order.get(m["kind"], 3), -m["age"]))[:3]:
        out.append({"text": f"{m['who']}'s {m['kind']} has not surfaced for {m['age']} chapters: {m['text']}", "keys": {m["who"].lower()} | health.keywords(m["text"])})
    for t in [t for t in rep.get("threads", []) if t["age"] >= THREAD_AFTER][:2]:
        out.append({"text": f"open thread for {t['age']} chapters: {t['text']}", "keys": health.keywords(t["text"])})
    return out[:MAX_NEGLECTED]


def neglected_block(items: list[dict]) -> str:
    return ("## NEGLECTED (move at least one of these this chapter)\n" + "\n".join(f"- {x['text']}" for x in items)) if items else ""


def plan_touches(items: list[dict], text: str) -> bool:
    words = set(health.words(text))
    return any(it["keys"] & words for it in items)


# ── risk calibration ──────────────────────────────────────────────────────────

STEPS = ("easy", "normal", "hard")


def calibrate(risks: list[dict], rep: dict, tgt: int) -> list[str]:
    """After a run of chapters without a failed act or a cost the riskiest planned act is made one step harder; after punishing chapters well above the target, the hardest one step easier. Changes the
    risks in place and returns what it did (kept on the chapter)."""
    if not risks or not rep.get("chapters"):
        return []
    free = (rep.get("dice") or {}).get("free_streak", 0)
    inten = rep.get("intensity") or []
    notes = []

    def pick(rs, hardest):
        key = lambda r: STEPS.index(r.get("difficulty", "normal")) if r.get("difficulty") in STEPS else 1
        return (max if hardest else min)(rs, key=key)

    if free >= 2:
        r = pick(risks, False)
        i = STEPS.index(r["difficulty"]) if r.get("difficulty") in STEPS else 1
        if i < 2:
            r["difficulty"], r["calibrated"] = STEPS[i + 1], "harder"
            notes.append(f"made harder after {free} chapters without a failed act or a cost: {r['act']}")
    elif len(inten) >= 2 and min(inten[-2:]) >= tgt + 2:
        r = pick(risks, True)
        i = STEPS.index(r["difficulty"]) if r.get("difficulty") in STEPS else 1
        if i > 0:
            r["difficulty"], r["calibrated"] = STEPS[i - 1], "easier"
            notes.append(f"made easier after punishing chapters: {r['act']}")
    return notes


# ── a failed act always costs ─────────────────────────────────────────────────

COST_PERCENT = {"partial": 0.10, "fail": 0.15, "disaster": 0.25}


def ensure_cost(rolls: list[dict], before: dict, after: dict, trackers: list[dict]) -> tuple[dict, list[dict]]:
    """When an act failed or went partial and the changes show no real cost for the people, one is added: the actor's own meter, else the group's, falls (or a danger meter rises); else the first clock moves.
    Returns the (possibly changed) state and the changes to list."""
    bad = [r for r in rolls if r.get("tier") in COST_PERCENT]
    if not bad:
        return after, []
    real = [x for x in health.diff_costs(before, after, trackers) if int(x.split("|")[0]) >= 2 or "lost" in x or "damaged" in x or "died" in x or "trust" in x or "tension" in x]
    if real:
        return after, []
    r = max(bad, key=lambda r: COST_PERCENT[r["tier"]])
    st = {**after, "trackers": {k: (dict(v) if isinstance(v, dict) else v) for k, v in after["trackers"].items()}}
    meters = [t for t in trackers if t["kind"] == "meter"]

    def room(t):
        """How far a meter still is from its bad end, 0 to 1 (a meter already at the bottom cannot pay a cost)."""
        span = max(1.0, float(t["max"]) - float(t["min"]))
        cur = float(st["trackers"][t["id"]])
        high_bad = t.get("danger_above") is not None and t.get("danger_below") is None
        return (float(t["max"]) - cur if high_bad else cur - float(t["min"])) / span

    own = [t for t in meters if S.norm(t.get("owner", "")) == S.norm(r.get("who", ""))]
    group = [t for t in meters if S.norm(t.get("owner", "")) == "group"]
    pool = [t for t in (own or group or meters) if room(t) > 0.1] or [t for t in meters if room(t) > 0.1]
    if pool:
        t = max(pool, key=room)
        span = float(t["max"]) - float(t["min"])
        step = max(1.0, round(span * COST_PERCENT[r["tier"]]))
        cur = float(st["trackers"][t["id"]])
        high_bad = t.get("danger_above") is not None and t.get("danger_below") is None
        new = max(float(t["min"]), min(float(t["max"]), cur + step if high_bad else cur - step))
        st["trackers"][t["id"]] = new
        text = f"cost of the {r['tier']} act ({r['act']}): {t['name']} {cur:g} -> {new:g}"
    else:
        clocks = [t for t in trackers if t["kind"] == "clock"]
        if not clocks:
            return after, []
        t = clocks[0]
        cur = int(st["trackers"][t["id"]])
        st["trackers"][t["id"]] = min(int(t["max"]), cur + 1)
        text = f"cost of the {r['tier']} act ({r['act']}): {t['name']} {cur}/{t['max']} -> {min(int(t['max']), cur + 1)}/{t['max']}"
    return st, [{"op": "cost", "text": text, "why": "a failed or partial act always costs something"}]
