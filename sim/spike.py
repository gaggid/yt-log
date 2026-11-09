"""S0 spike (docs/PLAN_simulation.md section 19): run two unlike stories for a few chapters on the REAL gateway and record how long each step takes, how many proposed changes the rules refuse, how long the
chapters are and what the referee catches. Uses a scratch database, never the app's.

    .venv\\Scripts\\python.exe -m sim.spike [scratch_dir] [chapters]
"""
import asyncio
import json
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

import config
from story import db, llm, settings as settings_mod

from . import engine, seed, store

IDEAS = {
    "supermarket": "A night-shift salesman is alone in a supermarket when a zombie outbreak begins outside. He has to survive until dawn using only what the store holds.",
    "courtroom": "A junior defence lawyer takes over a murder trial the night before it starts, against a famous prosecutor, with one witness who may be lying.",
}


class Timed:
    def __init__(self, inner):
        self.inner, self.times, self.calls = inner, defaultdict(list), 0

    async def complete(self, messages, max_tokens, params=None):
        import re
        task = re.match(r"\[TASK:(\w+)\]", messages[0]["content"]).group(1)
        t0 = time.time()
        r = await self.inner.complete(messages, max_tokens, params)
        self.times[task].append(round(time.time() - t0, 1))
        self.calls += 1
        return r


async def story(name: str, idea: str, chapters: int, out: dict) -> None:
    s = {**settings_mod.get(), "retry_backoff_s": 2}
    backend = Timed(llm.ChatBackend(s, settings_mod.api_key()))
    p = store.create_project(idea)
    pid = p["id"]
    t0 = time.time()
    await seed.seed_all(pid, backend, s)
    rec = {"idea": idea, "seed_s": round(time.time() - t0, 1), "cast": [e["name"] for e in store.entities(pid)], "trackers": [(t["kind"], t["name"]) for t in store.trackers(pid)],
           "rules": [g["text"] for g in store.guidelines(pid)], "chapters": []}
    out[name] = rec
    for i in range(chapters):
        head = store.path(pid)[-1] if store.path(pid) else None
        action = await engine.pick_option(pid, backend, s, head) if head else {"kind": "start"}
        t1 = time.time()
        ch = await engine.run_chapter(pid, backend, s, parent_id=head["id"] if head else "", action=action)
        rec["chapters"].append({"idx": ch["idx"], "seconds": round(time.time() - t1, 1), "words": len(ch["prose"].split()), "title": ch["title"], "beat": ch["plan"].get("beat"),
                                "rolls": [(r["act"], r["tier"]) for r in ch["rolls"]], "applied": len(ch["delta"]["applied"]), "dropped": [(d["op"], d["target"], d["why"]) for d in ch["delta"]["dropped"]],
                                "referee": ch["flags"].get("referee"), "rule_break": ch["flags"].get("rule_break"), "options": [o["label"] for o in ch["options"]], "prose": ch["prose"]})
        print(f"[{name}] chapter {ch['idx']}: {rec['chapters'][-1]['seconds']}s, {rec['chapters'][-1]['words']} words, referee {ch['flags'].get('referee')}", flush=True)
    rec["calls"], rec["step_seconds"] = backend.calls, {k: round(sum(v) / len(v), 1) for k, v in backend.times.items()}


def main() -> None:
    scratch = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="sim_spike_"))
    chapters = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    scratch.mkdir(parents=True, exist_ok=True)
    config.DATA_DIR = scratch
    db.init(scratch / "spike.db")
    settings_mod.update({"retry_backoff_s": 2})
    out: dict = {}
    for name, idea in IDEAS.items():
        try:
            asyncio.run(story(name, idea, chapters, out))
        except Exception as e:  # noqa: BLE001 - the report keeps what was learned before the failure
            out.setdefault(name, {})["error"] = f"{type(e).__name__}: {e}"
            print(f"[{name}] FAILED: {e}", flush=True)
    (scratch / "spike.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print("report:", scratch / "spike.json")


if __name__ == "__main__":
    main()
