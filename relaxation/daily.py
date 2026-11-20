"""The scheduled rain video: on three days a week (Monday, Wednesday and Friday unless changed; owner 2026-11-20: fewer and more varied videos look less mass-produced to YouTube),
inside a quiet window of the night, make one new session and run it.

Off until the owner switches it on (a whole run keeps the gateway busy for about two hours). One attempt per day:
the day is marked before the run starts, so a failed run is not retried in a loop. It never starts while any other
job runs (the gateway key serves one request at a time), but keeps looking until the window closes. Nothing is
uploaded to YouTube; the finished video waits for the owner."""
import asyncio
import time

from story import db
from story.pipeline import manager
from story2 import jobs

from . import auto, store

TICK_S = 30
WINDOW_H = 5                                  # from `hour` until `hour` + 5 (01:00 to 06:00 by default)
DEFAULTS = {"enabled": False, "hour": 1, "minutes": 180, "days": [0, 2, 4], "last_date": "", "last_session": ""}       # days: 0 = Monday ... 6 = Sunday
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def get_config() -> dict:
    store.ensure()
    saved = db.jload((db.one("SELECT data FROM relaxation_config WHERE id=1") or {}).get("data"), {})
    return {**DEFAULTS, **saved}


def _save(cfg: dict) -> dict:
    store.ensure()
    with db.tx() as c:
        c.execute("INSERT INTO relaxation_config(id,data) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (db.jdump(cfg),))
    return cfg


def save_config(patch: dict) -> dict:
    cur = get_config()
    if "enabled" in patch:
        cur["enabled"] = bool(patch["enabled"])
    if "hour" in patch:
        cur["hour"] = max(0, min(18, int(patch["hour"])))
    if "minutes" in patch:
        cur["minutes"] = max(1, min(480, int(patch["minutes"])))
    if "days" in patch:
        days = sorted({int(d) for d in patch["days"] if 0 <= int(d) <= 6})
        if days:                                           # at least one day: no day at all is what the switch is for
            cur["days"] = days
    return _save(cur)


def today(now: float | None = None) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(now if now is not None else time.time()))


def is_day(cfg: dict, now: float) -> bool:
    return time.localtime(now).tm_wday in (cfg.get("days") or DEFAULTS["days"])


def in_window(cfg: dict, now: float) -> bool:
    h = time.localtime(now).tm_hour
    return cfg["hour"] <= h < cfg["hour"] + WINDOW_H


def start_session(minutes: int) -> dict:
    """Make a new session (theme, instrument and seed picked by relaxation/variety.py) and start the whole run."""
    s = store.create(minutes=minutes)

    async def work(progress):
        return await auto.run(s["id"], force=False, progress=progress)
    jobs.start(s["id"], "relaxation", work)
    return s


def tick(now: float | None = None) -> str | None:
    """One step; returns the new session id when it started the day's run."""
    now = now if now is not None else time.time()
    cfg = get_config()
    if not cfg["enabled"] or cfg["last_date"] == today(now) or not is_day(cfg, now) or not in_window(cfg, now):
        return None
    if jobs.busy() or manager.busy():
        return None
    cfg["last_date"] = today(now)                          # first: a failed run is not tried again today
    _save(cfg)
    s = start_session(int(cfg["minutes"]))
    cfg["last_session"] = s["id"]
    _save(cfg)
    return s["id"]


async def forever() -> None:
    """Started in main.py. Does nothing while the switch is off."""
    while True:
        await asyncio.sleep(TICK_S)
        try:
            tick()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - never stop the loop
            print(f"[relaxation] daily run failed: {e}", flush=True)
