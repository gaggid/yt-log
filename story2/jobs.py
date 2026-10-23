"""Background jobs for Phase 2 model steps. One at a time (the gateway serves one request at a time), with progress the screen can
poll. Results are saved step by step by the planner, so a restart loses at most the step in flight."""
import asyncio
import time
import traceback

_jobs: dict[str, dict] = {}
_current: dict = {"task": None, "plan_id": None}


def busy() -> bool:
    t = _current["task"]
    return bool(t and not t.done())


def status(plan_id: str) -> dict:
    j = _jobs.get(plan_id)
    if not j:
        return {"state": "idle"}
    out = {k: v for k, v in j.items() if k != "task"}
    out["elapsed_s"] = round((j.get("finished") or time.time()) - j["started"], 1)
    done, total = j.get("done", 0), j.get("total", 0)
    if j["state"] == "running" and done > 0 and total > done:
        out["eta_s"] = round(out["elapsed_s"] / done * (total - done))
    return out


class JobBusy(Exception):
    pass


def start(plan_id: str, kind: str, work) -> dict:
    """work(progress) is an async callable; progress(done, total, label) records where it is."""
    if busy():
        raise JobBusy(f"another planning job is running ({_current['plan_id']}); wait for it to finish")
    job = {"state": "running", "kind": kind, "started": time.time(), "done": 0, "total": 0, "label": "starting", "error": ""}
    _jobs[plan_id] = job

    def progress(done: int, total: int, label: str = "") -> None:
        job.update(done=done, total=total, label=label)

    async def run() -> None:
        try:
            await work(progress)
            job.update(state="done", label="done", finished=time.time())
        except asyncio.CancelledError:
            job.update(state="cancelled", finished=time.time())
            raise
        except Exception as e:  # noqa: BLE001 - reported to the screen, never crashes the server
            job.update(state="error", error=f"{type(e).__name__}: {e}"[:500], finished=time.time())
            traceback.print_exc()

    t = asyncio.get_running_loop().create_task(run())
    _current.update(task=t, plan_id=plan_id)
    return status(plan_id)


def cancel(plan_id: str) -> bool:
    t = _current["task"]
    if busy() and _current["plan_id"] == plan_id:
        t.cancel()
        return True
    return False
