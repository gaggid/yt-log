"""Phase D — idle auto-loop.

Wakes every CHECK_INTERVAL_S seconds. When the gateway has been quiet for
IDLE_AFTER_S with no running jobs, it runs think + draw for every character
that has life_enabled = true and whose interval has elapsed.

If the gateway is grabbed mid-cycle (JobBusy), it logs a retry event and
backs off for RETRY_DELAY_S before trying again. The user can disable the
whole loop per-character via the life_enabled toggle in the Virtual Life tab.
"""
import asyncio
import time
from datetime import datetime

CHECK_INTERVAL_S = 60        # how often the loop wakes to check conditions
IDLE_AFTER_S     = 5 * 60   # gateway must have been quiet this long before we fire
RETRY_DELAY_S    = 15 * 60  # wait after a JobBusy before retrying
SLEEP_HOURS      = (0, 6)    # pre-dawn: loop skips entirely, character is asleep

_task: asyncio.Task | None = None


async def _run_one(char: dict, s: dict, key: str) -> None:
    from . import brain as brain_mod, profile as profile_mod, store
    from story import llm
    from story2 import jobs

    cid = char["id"]
    backend = llm.ChatBackend(s, key)
    try:
        thought = await brain_mod.think(char, backend, s, trigger="auto")
    except jobs.JobBusy:
        profile_mod.log_event(cid, "retry", "auto",
                              {"reason": "key busy during think"},
                              {"retry_after_s": RETRY_DELAY_S})
        raise
    except Exception as e:
        print(f"[virtual-life] think failed for {cid}: {e}", flush=True)
        return

    # reload char after think (memory/goals may have been saved)
    try:
        char = store.get(cid)
    except Exception:
        pass

    if jobs.busy():
        return   # something else grabbed the key; skip draw this cycle

    try:
        await brain_mod.draw_thought(char, thought["event_id"], thought, s, key, trigger="auto")
    except jobs.JobBusy:
        profile_mod.log_event(cid, "retry", "auto",
                              {"reason": "key busy during draw"},
                              {"retry_after_s": RETRY_DELAY_S})
        raise
    except Exception as e:
        print(f"[virtual-life] draw failed for {cid}: {e}", flush=True)


async def run_forever(s: dict, key: str) -> None:
    """Background task: loop indefinitely, firing think+draw on idle characters."""
    from . import profile as profile_mod, store
    from story2 import jobs
    from story.pipeline import manager

    print("[virtual-life] idle loop started", flush=True)
    while True:
        await asyncio.sleep(CHECK_INTERVAL_S)

        # skip during sleep hours — character is asleep (pre-dawn 0–6 am)
        if SLEEP_HOURS[0] <= datetime.now().hour < SLEEP_HOURS[1]:
            continue

        # skip while any job is running
        if jobs.busy() or manager.busy():
            continue

        # skip if the gateway was used very recently
        idle_s = time.time() - jobs._last_activity
        if idle_s < IDLE_AFTER_S:
            continue

        chars = []
        try:
            chars = store.listing("person")
        except Exception:
            continue

        for char in chars:
            prof = profile_mod.get(char)
            if not prof.get("life_enabled"):
                continue

            interval_s = (prof.get("life_interval_m") or 60) * 60
            last_run = profile_mod.last_run_time(char["id"])
            if last_run and (time.time() - last_run) < interval_s:
                continue

            if jobs.busy() or manager.busy():
                break   # something started while iterating — abort this pass

            try:
                await _run_one(char, s, key)
            except jobs.JobBusy:
                print("[virtual-life] key grabbed mid-cycle — backing off 15 min", flush=True)
                await asyncio.sleep(RETRY_DELAY_S)
                break   # restart the outer loop after the delay


def start(s: dict, key: str) -> asyncio.Task:
    """Launch the loop as a background asyncio task. Call once from lifespan."""
    global _task
    _task = asyncio.get_event_loop().create_task(run_forever(s, key))
    return _task


def stop() -> None:
    global _task
    if _task and not _task.done():
        _task.cancel()
        _task = None
