"""The bench: the same three stories, run again after every change, and the audit scorecard compared with the run before (docs/TASKS_quality_overhaul.md, task 0.2).

    python -m story2.bench --baseline                       # score the three stored films the audit was written about, save as data/bench/baseline-2026-10-29.json
    python -m story2.bench --run NAME [--until storyboard]  # make fresh plans for the three stories with the real model and score them
    python -m story2.bench --compare baseline-2026-10-29 NAME

`--until` is one of material, blueprint, narration, events, storyboard, prompts (pictures and voice are never made by the bench: they need the GPU for hours; the audit scores them on a real film).
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

import config
from story import db, llm, settings as settings_mod

from . import audit, events, imgplan, material, narrate2, planner, storyboard

STAGES = ("material", "blueprint", "narration", "events", "storyboard", "prompts")
# candidate ids of the three bench stories, and the stored plan made from each before the overhaul (the baseline)
BENCH = {
    "fugitive": {"candidate": "S-4a5dbc-001", "baseline": "pl-0b7cead5", "minutes": 8.0, "about": "a chase told over 35 years (crime, incident)"},
    "scam": {"candidate": "S-4ac1ce-002", "baseline": "pl-139b2f62", "minutes": 6.0, "about": "a fraud network traced from one victim (crime, mechanism)"},
    "science": {"candidate": "S-545aee-001", "baseline": "pl-eefc4e40", "minutes": 5.0, "about": "a physics result with big numbers (explainer)"},
}
# the numbers shown side by side; the full scorecard is stored in the snapshot
SHOWN = ("questions_share", "stock_phrases", "english_numbers_in_hindi", "last_line_not_hindi", "distinct_places", "top_place_share", "person_scene_share", "protagonist_share",
         "mean_scene_s", "max_scene_s", "prompt_words", "identical_prompt_share", "prompts_with_negation", "min_new_word_share", "drop_windows")


def bench_dir() -> Path:
    d = config.DATA_DIR / "bench"
    d.mkdir(parents=True, exist_ok=True)
    return d


def snapshot(plans: dict[str, str], with_audio: bool = False) -> dict:
    """The scorecard of each named plan."""
    return {"plans": {k: audit.scorecard(pid, with_audio) for k, pid in plans.items()}}


def save(name: str, snap: dict) -> Path:
    p = bench_dir() / f"{name}.json"
    p.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def load(name: str) -> dict:
    p = bench_dir() / f"{name}.json"
    if not p.is_file():
        raise FileNotFoundError(f"no bench run called {name!r} (looked for {p})")
    return json.loads(p.read_text(encoding="utf-8"))


def _value(card: dict, metric: str):
    for g in card["groups"].values():
        if metric in g:
            return g[metric]
    return None


def compare(a: dict, b: dict, a_name: str = "before", b_name: str = "after") -> str:
    """A table per story: each shown metric in both runs and whether it got better, worse or stayed."""
    out = []
    for story in b["plans"]:
        ca, cb = a["plans"].get(story), b["plans"][story]
        out.append(f"\n{story}: {cb['plan_id']}  ({a_name}: {ca['plan_id'] if ca else 'none'})")
        out.append(f"  {'metric':28} {a_name:>12} {b_name:>12}   target       result")
        for m in SHOWN:
            vb = _value(cb, m)
            va = _value(ca, m) if ca else None
            if vb is None:
                continue
            sa, sb = (va or {}).get("status", "na"), vb["status"]
            result = "better" if sa == "warn" and sb == "ok" else "worse" if sa == "ok" and sb == "warn" else "ok" if sb == "ok" else "to fix"
            out.append(f"  {m:28} {str((va or {}).get('value', '-')):>12} {str(vb['value']):>12}   {vb['target']:12} {result}")
    return "\n".join(out)


async def run_story(key: str, until: str, backend, s: dict | None = None, minutes: float | None = None, allow_unapproved: bool = True) -> str:
    """Make a fresh plan for one bench story and run it up to the stage `until`. Returns the plan id."""
    if until not in STAGES:
        raise ValueError(f"until must be one of {', '.join(STAGES)}")
    s = s or settings_mod.get()
    spec = BENCH[key]
    plan = planner.create_plan(spec["candidate"], minutes=minutes or spec["minutes"], allow_unapproved=allow_unapproved)
    pid = plan["id"]
    todo = STAGES[:STAGES.index(until) + 1]
    if "material" in todo:
        await material.make_material(pid, backend, s)
    if "blueprint" in todo:
        await planner.make_blueprint(pid, backend, s)
    if "narration" in todo:
        if material.has(planner.get_plan(pid)) and not narrate2.applies(planner.get_plan(pid)):
            raise RuntimeError(f"{pid}: the blueprint names no details of the story material, so narration would silently use the older one-call path")
        await planner.make_narration(pid, backend, s)
    if "events" in todo:
        await events.make_events(pid, backend, s)
    if "storyboard" in todo:
        await storyboard.make_registry(pid, backend, s)
        await storyboard.make_storyboard(pid, backend, s)
    if "prompts" in todo:
        imgplan.compile_plan(pid)
    return pid


async def run_all(name: str, until: str, backend, stories: list[str] | None = None, s: dict | None = None) -> dict:
    ids = {}
    for key in stories or list(BENCH):
        ids[key] = await run_story(key, until, backend, s)
    snap = snapshot(ids)
    snap["run"] = {"name": name, "until": until, "plans": ids}
    save(name, snap)
    return snap


def regressions(accepted: dict, run: dict) -> list[str]:
    """Metrics that were ok in the accepted run and are to fix in this one, per story (task 8.6)."""
    out = []
    for story, card in run["plans"].items():
        old = accepted["plans"].get(story)
        if not old:
            continue
        for m in SHOWN:
            a, b = _value(old, m), _value(card, m)
            if a and b and a["status"] == "ok" and b["status"] == "warn":
                out.append(f"{story}: {m} was {a['value']} and is now {b['value']} (target {b['target']})")
    return out


def baseline() -> dict:
    snap = snapshot({k: v["baseline"] for k, v in BENCH.items()})
    snap["run"] = {"name": "baseline-2026-10-29", "until": "video", "plans": {k: v["baseline"] for k, v in BENCH.items()}}
    save("baseline-2026-10-29", snap)
    return snap


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="story2.bench")
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--run", metavar="NAME")
    ap.add_argument("--until", default="storyboard", choices=STAGES)
    ap.add_argument("--stories", default="", help="comma list of: " + ", ".join(BENCH))
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"))
    ap.add_argument("--check", metavar="NAME", help="exit 1 when a run is worse than data/bench/accepted.json (or the baseline) on a metric that was ok")
    ap.add_argument("--accept", metavar="NAME", help="make a stored run the accepted one")
    a = ap.parse_args(argv)
    db.init()
    if a.baseline:
        snap = baseline()
        print(compare({"plans": {}}, snap, "-", "baseline"))
        return 0
    if a.accept:
        save("accepted", load(a.accept))
        print(f"{a.accept} is now the accepted run")
        return 0
    if a.check:
        ref = "accepted" if (bench_dir() / "accepted.json").is_file() else "baseline-2026-10-29"
        bad = regressions(load(ref), load(a.check))
        print("\n".join(bad) if bad else f"no regression against {ref}")
        return 1 if bad else 0
    if a.compare:
        print(compare(load(a.compare[0]), load(a.compare[1]), a.compare[0][:12], a.compare[1][:12]))
        return 0
    if a.run:
        s = settings_mod.get()
        snap = asyncio.run(run_all(a.run, a.until, llm.ChatBackend(s, settings_mod.api_key()), [x for x in a.stories.split(",") if x] or None, s))
        base = bench_dir() / "baseline-2026-10-29.json"
        print(compare(json.loads(base.read_text(encoding="utf-8")) if base.is_file() else {"plans": {}}, snap, "baseline", a.run[:12]))
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
