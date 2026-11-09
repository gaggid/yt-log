"""R2 spike (docs/PLAN_drama.md section 2): run two unlike stories for a few chapters on the REAL gateway with a planned length, letting the AI pick the options, and record the health numbers chapter by chapter
(tension against the target, failed acts and their costs, opposition, neglected material, how chapters end, options with costs). Uses a scratch database, never the app's.

    .venv\\Scripts\\python.exe -m sim.spike_drama [scratch_dir] [chapters] [length]
"""
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

import config
from story import db, llm, settings as settings_mod

from . import engine, health, seed, store
from .spike import Timed

IDEAS = {
    "supermarket": ("A night shift employee of a massive supermarket starts his shift while a virus outbreak in the city is turning people into zombies. He sets himself to survive till dawn. He is an intelligent guy, "
                    "knows the supermarket very well and the products in it, also the storage and entries of the market. The supermarket has a big parking lot and strong gates."),
    "courtroom": "A junior defence lawyer takes over a murder trial the night before it starts, against a famous prosecutor, with one witness who may be lying.",
}


async def story(name: str, idea: str, chapters: int, length: int, out: dict) -> None:
    s = {**settings_mod.get(), "retry_backoff_s": 2}
    backend = Timed(llm.ChatBackend(s, settings_mod.api_key()))
    pid = store.create_project(idea)["id"]
    store.save_project(pid, settings={"length": length})
    t0 = time.time()
    await seed.seed_all(pid, backend, s)
    rec = {"idea": idea, "seed_s": round(time.time() - t0, 1), "goal": store.world(pid).get("goal"), "trackers": [(t["kind"], t["name"]) for t in store.trackers(pid)], "chapters": []}
    out[name] = rec
    for i in range(chapters):
        head = store.path(pid)[-1] if store.path(pid) else None
        action = await engine.pick_option(pid, backend, s, head) if head else {"kind": "start"}
        t1 = time.time()
        ch = await engine.run_chapter(pid, backend, s, parent_id=head["id"] if head else "", action=action)
        rep = health.report(pid)
        pc = rep["per_chapter"][-1]
        d = ch["delta"]
        rec["chapters"].append({"idx": ch["idx"], "seconds": round(time.time() - t1, 1), "words": len(ch["prose"].split()), "title": ch["title"], "arc": ch["flags"].get("arc"), "neglected": ch["flags"].get("neglected"),
                                "opposition": ch["plan"].get("opposition"), "calibration": ch["plan"].get("calibration"), "rolls": [(r["act"][:60], r.get("kind"), r["tier"], r["mod"], r["target"]) for r in ch["rolls"]],
                                "applied": [a["text"] for a in d["applied"]], "dropped": [(x["op"], x["why"][:60]) for x in d["dropped"]], "tension": pc["intensity"], "costs": pc["costs"], "ending": pc["ending"],
                                "referee": ch["flags"].get("referee"), "options": [(o["who"], o["label"], o.get("hint"), o.get("cost"), o["risk"]) for o in ch["options"]], "verdicts": [v["text"] for v in rep["verdicts"]],
                                "prose": ch["prose"]})
        print(f"[{name}] chapter {ch['idx']}: {rec['chapters'][-1]['seconds']}s, tension {pc['intensity']} (target {ch['flags'].get('arc', {}).get('target')}), ends {pc['ending']}, referee {ch['flags'].get('referee')}", flush=True)
    rec["health"] = health.report(pid)


def main() -> None:
    scratch = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="sim_drama_"))
    chapters = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    length = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    scratch.mkdir(parents=True, exist_ok=True)
    config.DATA_DIR = scratch
    db.init(scratch / "drama.db")
    settings_mod.update({"retry_backoff_s": 2})
    out: dict = {}
    for name, idea in IDEAS.items():
        try:
            asyncio.run(story(name, idea, chapters, length, out))
        except Exception as e:  # noqa: BLE001 - the report keeps what was learned before the failure
            out.setdefault(name, {})["error"] = f"{type(e).__name__}: {e}"
            print(f"[{name}] FAILED: {e}", flush=True)
        (scratch / "drama.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print("report:", scratch / "drama.json")


if __name__ == "__main__":
    main()
