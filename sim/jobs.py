"""Background jobs of the simulator. The gateway serves one request at a time, so every model step goes through the app's one-job lock (story2/jobs.py), keyed by the story id; a second job is refused.
A cooperative Stop is checked at stage boundaries."""
from story2 import jobs

from . import store, think

_stop: set[str] = set()


class Busy(Exception):
    pass


def busy() -> bool:
    return jobs.busy()


def start(pid: str, kind: str, work) -> dict:
    _stop.discard(pid)

    async def wrapped(progress):
        try:
            think.mode.set(store.project(pid)["settings"].get("thinking", "balanced"))        # this job's own context: the story's thinking setting
            return await work(progress)
        finally:
            _stop.discard(pid)

    try:
        return jobs.start(pid, kind, wrapped)
    except jobs.JobBusy as e:
        raise Busy(str(e))


def status(pid: str) -> dict:
    return jobs.status(pid)


def request_stop(pid: str) -> bool:
    if jobs.status(pid).get("state") == "running":
        _stop.add(pid)
        return True
    return False


def cancelled(pid: str):
    return lambda: pid in _stop
