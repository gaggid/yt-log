"""R1 spike (docs/PLAN_architect.md): the Story Architect on the REAL gateway with a premise like the owner's inspiration (a student locked in a school during an outbreak, told day by day): write the plan, then play a few
chapters and record the backbone, the beats and the chapters so they can be read against the video. Uses a scratch database, never the app's.

    .venv\\Scripts\\python.exe -m sim.spike_architect [scratch_dir] [chapters]
"""
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

import config
from story import db, llm, settings as settings_mod

from . import engine, health, seed, store, templates
from .spike import Timed

IDEA = ("You are the last student in detention at a high school at 3:40 in the afternoon when something goes wrong in the building. The vice principal comes over the speaker and says: stay in your rooms, lock your doors, "
        "do not open them for anyone, even if you know them. We follow you day by day through 30 days locked inside the school during a zombie outbreak.")


async def main_async(chapters: int, out: dict) -> None:
    s = {**settings_mod.get(), "retry_backoff_s": 2}
    backend = Timed(llm.ChatBackend(s, settings_mod.api_key()))
    pid = store.create_project(IDEA, template_id="tp-film")["id"]
    templates.apply(pid, "tp-film")
    t0 = time.time()
    await seed.seed_all(pid, backend, s)
    bible = store.bible(pid)
    out.update({"idea": IDEA, "seed_s": round(time.time() - t0, 1), "world": store.world(pid), "cast": [(e["name"], e.get("role")) for e in store.entities(pid)], "bible": bible,
                "trackers": [(t["kind"], t["name"]) for t in store.trackers(pid)], "chapters": []})
    (Path(out["_dir"]) / "architect.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"plan ready in {out['seed_s']}s: {len(bible.get('beats', []))} beats, secret: {bible.get('secret', {}).get('truth', '')[:80]}", flush=True)
    for i in range(chapters):
        head = store.path(pid)[-1] if store.path(pid) else None
        action = await engine.pick_option(pid, backend, s, head) if head else {"kind": "start"}
        t1 = time.time()
        ch = await engine.run_chapter(pid, backend, s, parent_id=head["id"] if head else "", action=action)
        rep = health.report(pid)
        out["chapters"].append({"idx": ch["idx"], "seconds": round(time.time() - t1, 1), "title": ch["title"], "time": ch["story_time"], "words": len(ch["prose"].split()), "beat": ch["flags"].get("beat"),
                                "referee": ch["flags"].get("referee"), "rolls": [(r["kind"], r["tier"]) for r in ch["rolls"]], "options": [(o["who"], o["label"], o.get("cost")) for o in ch["options"]],
                                "verdicts": [v["text"] for v in rep["verdicts"]], "plan_row": (rep.get("plan") or {}).get("beats", [])[-1:], "prose": ch["prose"]})
        print(f"chapter {ch['idx']}: {out['chapters'][-1]['seconds']}s, {out['chapters'][-1]['words']} words, referee {ch['flags'].get('referee')}, beat hit {out['chapters'][-1]['plan_row']}", flush=True)
        (Path(out["_dir"]) / "architect.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")


def main() -> None:
    scratch = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="sim_arch_"))
    chapters = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    scratch.mkdir(parents=True, exist_ok=True)
    config.DATA_DIR = scratch
    db.init(scratch / "arch.db")
    settings_mod.update({"retry_backoff_s": 2})
    out: dict = {"_dir": str(scratch)}
    try:
        asyncio.run(main_async(chapters, out))
    except Exception as e:  # noqa: BLE001 - the report keeps what was learned before the failure
        out["error"] = f"{type(e).__name__}: {e}"
        print("FAILED:", e, flush=True)
    (scratch / "architect.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print("report:", scratch / "architect.json")


if __name__ == "__main__":
    main()
