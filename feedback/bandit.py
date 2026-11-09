"""Choosing territory, picture style and tone with the channel's results in mind, and still trying new things.

Each choice is explore or exploit. An explore pick (a share of `explore`, 30 to 40 %, set by the owner) takes the least-tried arm, so new things get a chance. An exploit pick draws an arm
at random weighted by how well it did (its mean grade, pulled towards 50 for few videos). An arm with four or more flops and no winner rests for 14 days. Everything here runs only while an
approved Playbook is in use (`playbook.enabled()`); otherwise the callers keep their old behaviour. The way each choice was made is saved with the idea, so the page can compare explore with exploit."""
import math
import random
import time

from . import features, outcomes, playbook, store

COOL_DAYS = 14
COOL_FLOPS = 4
PRIOR, PRIOR_N, TEMP = 50.0, 3, 10.0
REPEAT_PENALTY = 1.5


def _explore_share() -> float:
    from shorts import ideas as ideas_mod
    return float(ideas_mod.get_config()["explore"])


def arm_stats(factor: str, rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in rows:
        f = r["features"]
        if factor == "territory":
            arm = f.get("territory")
        elif r["source"] != "app":
            continue
        else:
            arm = f.get(factor)
        if not arm:
            continue
        a = out.setdefault(arm, {"n": 0, "sum": 0.0, "flops": 0, "winners": 0, "last_flop": 0.0})
        a["n"] += 1
        a["sum"] += r["grade"]
        a["flops"] += r["label"] == "flop"
        a["winners"] += r["label"] == "winner"
        if r["label"] == "flop":
            a["last_flop"] = max(a["last_flop"], r["published_at"])
    return out


def cooled(a: dict, now: float) -> bool:
    return a["flops"] >= COOL_FLOPS and a["winners"] == 0 and now - a["last_flop"] < COOL_DAYS * 86400


def choose(factor: str, arms: list[str], rows: list[dict], rng: random.Random | None = None, used: dict | None = None, explore: float | None = None, now: float | None = None) -> tuple[str, str]:
    rng = rng or random.Random()
    now = now if now is not None else time.time()
    explore = _explore_share() if explore is None else explore
    used = used if used is not None else {}
    st = arm_stats(factor, rows)
    n_of = lambda x: st.get(x, {"n": 0})["n"] + used.get(x, 0)
    if rng.random() < explore:
        fewest = min(n_of(x) for x in arms)
        return rng.choice([x for x in arms if n_of(x) == fewest]), "explore"
    pool = [x for x in arms if not (x in st and cooled(st[x], now))] or list(arms)
    w = []
    for x in pool:
        a = st.get(x)
        score = (a["sum"] + PRIOR * PRIOR_N) / (a["n"] + PRIOR_N) if a else PRIOR
        w.append(math.exp((score - PRIOR) / TEMP) / (1 + REPEAT_PENALTY * used.get(x, 0)))
    return rng.choices(pool, weights=w, k=1)[0], "exploit"


def choose_style(allowed: list[str], rng: random.Random | None = None) -> tuple[str, str] | None:
    """(style, source) or None (no approved Playbook, or no graded video made by the app yet: the caller rotates as before)."""
    if not playbook.enabled():
        return None
    rows = outcomes.graded_rows()
    if not any(r["source"] == "app" and r["features"].get("style") for r in rows):
        return None
    return choose("style", list(allowed), rows, rng)


def choose_tone(default: str, rng: random.Random | None = None) -> tuple[str, str]:
    """The tone of a short: the one that fits the idea, except on an explore roll, when the least-tried tone arm is used instead."""
    if not playbook.enabled():
        return default, "idea"
    from shorts import ideas as ideas_mod
    arms = ideas_mod.get_config()["tone_arms"]
    rng = rng or random.Random()
    if not arms or rng.random() >= _explore_share():
        return default, "idea"
    st = arm_stats("tone", outcomes.graded_rows())
    fewest = min(st.get(x, {"n": 0})["n"] for x in arms)
    return rng.choice([x for x in arms if st.get(x, {"n": 0})["n"] == fewest]), "explore"


def territory_plan(n: int, rng: random.Random | None = None) -> list[tuple[str, str]]:
    rows = outcomes.graded_rows()
    used: dict[str, int] = {}
    plan = []
    for _ in range(n):
        t, src = choose("territory", features.TERRITORIES, rows, rng, used)
        used[t] = used.get(t, 0) + 1
        plan.append((t, src))
    return plan


def territory_block(n: int, lenses: bool = False) -> str:
    """The batch's slots for the generator. The plan is remembered so the ideas written can be matched to their slot (`assign_sources`). With perspective lenses (diverse mode) the plan is a preference, not a fixed order."""
    plan = territory_plan(n)
    store.set_kv("last_plan", [list(p) for p in plan])
    lines = [f"  {i}. {t} ({features.TERRITORY_HELP[t]})" for i, (t, _) in enumerate(plan, 1)]
    how = ("prefer these territories, using one that fits your perspective and a different one for each idea of the batch" if lenses
           else "write idea 1 in the first territory, idea 2 in the second, and so on")
    return f"TERRITORY PLAN for this batch (the channel's results steer which subjects get tried; {how}; keep every idea a different event or question):\n" + "\n".join(lines)


def assign_sources(idea_ids: list[str]) -> None:
    """Match the written ideas to the slots of the last plan by territory and save how each territory was chosen (`explore` or `exploit`; `model` when the idea matches no slot)."""
    from story import db
    plan = [tuple(p) for p in (store.kv("last_plan", []) or [])]
    if not plan:
        return
    left = list(plan)
    for iid in idea_ids:
        row = db.one("SELECT territory FROM short_ideas WHERE id=?", (iid,))
        t = (row or {}).get("territory", "")
        src = "model"
        for p in left:
            if p[0] == t:
                src = p[1]
                left.remove(p)
                break
        db.ex("UPDATE short_ideas SET territory_src=? WHERE id=?", (src, iid))
    store.set_kv("last_plan", [])
