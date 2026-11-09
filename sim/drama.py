"""The drama director (docs/PLAN_drama.md part B): where the story is in its arc and how tense this chapter should be, what has been neglected, how hard the risky acts should be after a run of easy chapters,
and the guarantee that a failed act costs something. Code decides; the planner is told. Nothing here names a genre."""
import math
import re

from . import health, state as S

PHASE_TEXT = {
    "setup": "Set up: show what the people want, what stands in their way and what is at stake. Plant one question the reader wants answered. Pressure starts low but is already present.",
    "rising": "Rising: complications. Each choice costs something, plans meet resistance, a small thing goes wrong, the opposition grows. Nobody gets what they want cleanly.",
    "midpoint": "Midpoint: a reveal or a reversal that changes what the people believe, want or fear. After it the story cannot go back to how it was.",
    "crisis": "Crisis: the pressure peaks. Failures hurt and last, allies are lost or divided, time runs short, a hard choice between two things the people care about.",
    "climax": "Climax: the decisive confrontation or decision. Everything planted before is used. The people win, lose or change.",
    "resolution": "Resolution: the consequences, shown. Close the main question; end on a final image, not a cliffhanger.",
    "release": "Release: a pause after the peak, with a cost counted and a new question opened.",
    "complication": "A new complication: the situation changes or a new pressure arrives that the people did not expect.",
}
TARGET = {"setup": 3, "rising": 5, "midpoint": 6, "crisis": 8, "climax": 9, "resolution": 4, "release": 4, "complication": 5}
LENGTHS = (0, 6, 8, 12, 16, 24, 36, 48)
WAVE = 6
NEGLECT_AFTER = 3
THREAD_AFTER = 4
MAX_NEGLECTED = 4


def phase(idx: int, length: int) -> str:
    """The part of the arc chapter `idx` (1-based) belongs to. A planned length gives one arc; an open-ended story repeats a wave of six chapters."""
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
        return "setup" if r <= 0.2 else "rising" if r <= 0.5 else "crisis" if r <= 0.8 else "climax"
    pos = (idx - 1) % WAVE + 1
    if pos == 1:
        return "setup" if idx == 1 else "complication"
    return {2: "rising", 3: "rising", 4: "midpoint", 5: "crisis", 6: "release"}[pos]


def target(idx: int, length: int) -> int:
    ph = phase(idx, length)
    t = TARGET[ph]
    if length and ph in ("rising", "crisis"):                                  # climbs a little inside a phase
        t += min(1, idx % 2)
    return t


def arc(idx: int, length: int, intensities: list[int]) -> dict:
    ph = phase(idx, length)
    tgt = target(idx, length)
    last = intensities[-3:]
    note = ""
    if last and tgt > max(last):
        note = f"The last chapters reached {', '.join(str(x) for x in last)} out of 10; this one must reach about {tgt}: raise the pressure or the cost."
    elif last and tgt < min(last) - 1:
        note = f"The last chapters reached {', '.join(str(x) for x in last)} out of 10; this one can let the pressure ease a little (about {tgt})."
    left = (length - idx) if length else None
    return {"phase": ph, "target": tgt, "text": PHASE_TEXT[ph], "note": note, "last": last, "chapters_left": left}


def arc_block(a: dict, idx: int, length: int) -> str:
    where = f"chapter {idx} of {length}" if length else f"chapter {idx} (an open-ended story)"
    return f"## ARC AND PACING\n{where}, phase: {a['phase'].upper()}. {a['text']}\nTarget tension for this chapter: {a['target']} out of 10. {a['note']}".strip()


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
    own = [t for t in meters if S.norm(t.get("owner", "")) == S.norm(r.get("who", ""))]
    pool = own or [t for t in meters if S.norm(t.get("owner", "")) == "group"] or meters
    if pool:
        t = pool[0]
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
