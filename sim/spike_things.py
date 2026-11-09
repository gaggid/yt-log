"""D9 spike (docs/PLAN_discoveries.md section 14): run two unlike stories for three chapters on the REAL gateway, with actions that ask for a find, a make and a give, and record what the rules accepted and
refused. Uses a scratch database, never the app's.

    .venv\\Scripts\\python.exe -m sim.spike_things [scratch_dir]
"""
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

import config
from story import db, llm, settings as settings_mod

from . import engine, seed, store, things
from .spike import IDEAS, Timed

ACTIONS = {
    "supermarket": [("Ravi", "Ravi searches the hardware aisle shelves for something that could hold the loading bay shutter closed"),
                    ("Meera", "Meera makes a noise alarm from rope and tins so they hear anything that reaches the door"),
                    ("Ravi", "Ravi hands the best tool he has to Dev and asks him to guard the loading bay")],
    "courtroom": [("Maya", "Maya searches the case file for something the prosecution overlooked"),
                  ("Maya", "Maya drafts a short motion from the witness statement and the police report she holds"),
                  ("Maya", "Maya persuades the court clerk to hand over the evidence log")],
}


async def story(name: str, idea: str, out: dict) -> None:
    s = {**settings_mod.get(), "retry_backoff_s": 2}
    backend = Timed(llm.ChatBackend(s, settings_mod.api_key()))
    pid = store.create_project(idea)["id"]
    t0 = time.time()
    await seed.seed_all(pid, backend, s)
    ents = store.entities(pid)
    chars = [e["name"] for e in ents if e["kind"] == "character"]
    rec = {"idea": idea, "seed_s": round(time.time() - t0, 1), "cast": [(e["name"], e.get("skills")) for e in ents if e["kind"] == "character"], "craft": store.world(pid).get("craft"),
           "craft_rules": [g["text"] for g in store.guidelines(pid) if g["grp"] == "craft"], "items": [(t["name"], list((t.get("start") or {}))) for t in store.trackers(pid) if t["kind"] == "items"], "chapters": []}
    out[name] = rec
    for i, (who, text) in enumerate(ACTIONS[name]):
        who = who if who in chars else chars[0]
        head = store.path(pid)[-1] if store.path(pid) else None
        t1 = time.time()
        ch = await engine.run_chapter(pid, backend, s, parent_id=head["id"] if head else "", action={"kind": "text", "text": text.replace(ACTIONS[name][i][0], who), "who": who})
        d = ch["delta"]
        rec["chapters"].append({"idx": ch["idx"], "seconds": round(time.time() - t1, 1), "words": len(ch["prose"].split()), "title": ch["title"], "action": text,
                                "risks": [(r["who"], r.get("kind"), r["act"], (r.get("craft") or {}).get("reasoning", "")) for r in ch["plan"]["risks"]], "rolls": [(r["act"], r.get("kind"), r["tier"]) for r in ch["rolls"]],
                                "applied": [a["text"] for a in d["applied"]], "dropped": [(x["op"], x["target"], x["why"]) for x in d["dropped"]], "referee": ch["flags"].get("referee"),
                                "rule_break": ch["flags"].get("rule_break"), "prose": ch["prose"]})
        print(f"[{name}] chapter {ch['idx']}: {rec['chapters'][-1]['seconds']}s, applied {len(d['applied'])}, dropped {len(d['dropped'])}, referee {ch['flags'].get('referee')}", flush=True)
        if i == 1:                                                # after the second chapter: bind one thing to its holder, so the third chapter can meet a refusal
            cur = store.chapter(ch["id"])
            st = cur["state_after"]
            for t in store.trackers(pid):
                if t["kind"] == "items":
                    for n, e in (st["trackers"].get(t["id"]) or {}).items():
                        if e.get("at") in chars:
                            e["bound_to"] = e["at"]
                            rec["bound"] = f"{n} -> {e['at']}"
                            break
            store.update_chapter(ch["id"], state_after=st)
    rec["calls"], rec["step_seconds"] = backend.calls, {k: round(sum(v) / len(v), 1) for k, v in backend.times.items()}


def main() -> None:
    scratch = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="sim_things_"))
    scratch.mkdir(parents=True, exist_ok=True)
    config.DATA_DIR = scratch
    db.init(scratch / "things.db")
    settings_mod.update({"retry_backoff_s": 2})
    out: dict = {}
    for name, idea in IDEAS.items():
        try:
            asyncio.run(story(name, idea, out))
        except Exception as e:  # noqa: BLE001 - the report keeps what was learned before the failure
            out.setdefault(name, {})["error"] = f"{type(e).__name__}: {e}"
            print(f"[{name}] FAILED: {e}", flush=True)
        (scratch / "things.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print("report:", scratch / "things.json")


if __name__ == "__main__":
    main()
