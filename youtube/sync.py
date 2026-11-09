"""Pull the channel's numbers, tie each video to the short (and idea) it came from, and work out how each idea performed.

Linking: a video whose title matches the upload title written for a finished short (`short["publish"]["title"]`, or the short's own title) is linked by itself; a link typed in by the person
always wins and is never replaced by the matching. The numbers of a window (first 2, 7 and 28 days) only count as complete once the day after the window has passed, because YouTube
reports a day or two late."""
import asyncio
import difflib
import re
import time
from datetime import datetime, timedelta, timezone

from . import client, oauth, store

UPLOADS_MAX = 200                 # the newest videos kept in sync
ANALYTICS_MAX = 60                # daily numbers for this many videos, linked ones first
ANALYTICS_DAYS = 120              # ... published within this many days
MATCH_MIN = 0.92                  # title similarity that links a video to a short by itself
WINDOWS = (2, 7, 28)
LAG_DAYS = 2                      # a window is complete this many days after it ends
EVERY_S = 3 * 3600

_state = {"running": False, "error": "", "note": "", "at": 0.0}
_task: asyncio.Task | None = None


def norm(t: str) -> str:
    return " ".join(re.findall(r"[a-z0-9ऀ-ॿ]+", (t or "").lower()))


def video_id_of(text: str) -> str:
    """The 11-character id in a YouTube link (watch, youtu.be, shorts, embed) or the id itself."""
    t = (text or "").strip()
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([\w-]{11})", t)
    if m:
        return m.group(1)
    return t if re.fullmatch(r"[\w-]{11}", t) else ""


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def _finished_shorts() -> list[dict]:
    """[{short_id, idea_id, titles, created_at}] for every idea whose short exists."""
    from shorts import ideas as ideas_mod, store as sstore
    out = []
    for i in ideas_mod.listing():
        if not i.get("short_id") or i["status"] not in ("queued", "done"):
            continue
        try:
            sh = sstore.get(i["short_id"])
        except sstore.ShortError:
            continue
        titles = [t for t in ((sh.get("publish") or {}).get("title", ""), sh.get("title", "")) if norm(t)]
        out.append({"short_id": sh["id"], "idea_id": i["id"], "titles": titles, "created_at": sh.get("created_at") or 0})
    return out


def auto_link() -> list[tuple[str, str]]:
    """Link unlinked videos to unlinked shorts by title. Returns [(video_id, short_id)] made now."""
    taken_v = {l["video_id"] for l in store.links()}
    taken_s = {l["short_id"] for l in store.links()}
    cands = [c for c in _finished_shorts() if c["short_id"] not in taken_s]
    made = []
    for v in store.videos():
        if v["video_id"] in taken_v:
            continue
        best, best_r = None, MATCH_MIN
        for c in cands:
            if c["short_id"] in taken_s or v["published_at"] < c["created_at"] - 60:
                continue
            r = max((difflib.SequenceMatcher(None, norm(v["title"]), norm(t)).ratio() for t in c["titles"]), default=0)
            if r >= best_r:
                best, best_r = c, r
        if best:
            store.set_link(v["video_id"], best["short_id"], best["idea_id"], "title")
            taken_s.add(best["short_id"])
            made.append((v["video_id"], best["short_id"]))
    return made


def link_by_hand(short_id: str, video: str) -> str:
    from shorts import ideas as ideas_mod, store as sstore
    vid = video_id_of(video)
    if not vid:
        raise ValueError("that is not a YouTube link or video id")
    sstore.get(short_id)
    idea = next((i for i in ideas_mod.listing() if i.get("short_id") == short_id), None)
    store.set_link(vid, short_id, idea["id"] if idea else "", "manual")
    return vid


async def run() -> dict:
    """One full sync. Raises on a failed sign-in; a video whose daily numbers fail is counted and skipped."""
    ch = await client.my_channel()
    a = store.get_auth()
    a.update({"channel_id": ch["id"], "channel_title": ch["title"]})
    store.set_auth(a)
    ids = await client.upload_ids(ch["uploads"], UPLOADS_MAX)
    store.save_videos(await client.videos(ids))
    auto_link()
    linked = {l["video_id"] for l in store.links()}
    today = _day(time.time())
    recent = [v for v in store.videos() if time.time() - v["published_at"] < ANALYTICS_DAYS * 86400]
    todo = sorted(recent, key=lambda v: (v["video_id"] not in linked, -v["published_at"]))[:ANALYTICS_MAX]
    failed = 0
    first_error = ""
    for v in todo:
        try:
            store.save_days(v["video_id"], await client.daily(v["video_id"], _day(v["published_at"]), today))
        except oauth.YTAuthError:
            raise
        except oauth.YTError as e:
            failed += 1
            first_error = first_error or str(e)
    await _comments()
    store.set_kv("last_sync", {"at": time.time(), "videos": len(ids), "analytics": len(todo) - failed, "analytics_failed": failed, "analytics_error": first_error})
    return store.kv("last_sync")


COMMENT_VIDEOS = 8               # the public comments of this many best videos are read (1 quota unit each)


async def _comments() -> None:
    """Top public comments of the best shorts, kept for the idea factory. A video with comments off, or any failure here, is skipped."""
    from feedback import store as fbstore
    best = sorted((v for v in store.videos() if not v["duration_s"] or v["duration_s"] <= 180), key=lambda v: -v["views"])[:COMMENT_VIDEOS]
    for v in best:
        try:
            fbstore.save_comments(v["video_id"], await client.comments(v["video_id"]))
        except oauth.YTAuthError:
            raise
        except oauth.YTError:
            continue


async def _job() -> None:
    _state.update(running=True, error="", note="Reading the channel…")
    try:
        r = await run()
        _grade()
        _state["note"] = f"{r['videos']} videos, daily numbers for {r['analytics']}" + (f" ({r['analytics_failed']} failed: {r['analytics_error']})" if r["analytics_failed"] else "")
    except oauth.YTError as e:
        _state["error"] = str(e)
    except Exception as e:  # noqa: BLE001 - shown on the screen, never stops the app
        _state["error"] = f"{type(e).__name__}: {e}"
    finally:
        _state.update(running=False, at=time.time())


def _grade() -> None:
    """New numbers are in: regrade the videos (no model call)."""
    try:
        from feedback import outcomes
        outcomes.refresh()
    except Exception as e:  # noqa: BLE001 - grading must never fail a sync
        print(f"[feedback] grading failed: {e}", flush=True)


def start() -> bool:
    """Begin a sync in the background; False when one is already running."""
    global _task
    if _state["running"]:
        return False
    _state["running"] = True
    _task = asyncio.get_running_loop().create_task(_job())
    return True


def state() -> dict:
    return {**_state, "last": store.kv("last_sync", None)}


async def forever() -> None:
    """The background loop (started in main.py): sync every few hours while connected."""
    while True:
        await asyncio.sleep(300)
        try:
            if store.get_auth().get("refresh_token") and not store.get_auth().get("broken") and oauth.configured():
                last = (store.kv("last_sync", None) or {}).get("at", 0)
                if time.time() - last > EVERY_S and time.time() - _state["at"] > EVERY_S:
                    start()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            print(f"[youtube] loop failed: {e}", flush=True)


# ── results ───────────────────────────────────────────────────────────────────

def windows(v: dict, days: list[dict], now: float | None = None) -> dict:
    """Views in the first 2, 7 and 28 days after publishing, and whether each window is complete."""
    now = now if now is not None else time.time()
    pub = datetime.fromtimestamp(v["published_at"], timezone.utc).date()
    today = datetime.fromtimestamp(now, timezone.utc).date()
    out = {}
    for n in WINDOWS:
        end = pub + timedelta(days=n)
        out[f"v{n}"] = sum(d["views"] for d in days if d["day"] < end.isoformat())
        out[f"v{n}_done"] = (today - pub).days >= n + LAG_DAYS
    return out


def band(score) -> str:
    s = score or 0
    return "no score" if not s else "9 and up" if s >= 9 else "8 to 9" if s >= 8 else "7 to 8" if s >= 7 else "under 7"


def performance(now: float | None = None) -> dict:
    from shorts import ideas as ideas_mod, store as sstore
    vids = {v["video_id"]: v for v in store.videos()}
    rows = []
    for l in store.links():
        v = vids.get(l["video_id"])
        if not v:
            continue
        try:
            sh = sstore.get(l["short_id"])
        except sstore.ShortError:
            continue
        try:
            idea = ideas_mod.get(l["idea_id"]) if l["idea_id"] else None
        except ValueError:
            idea = None
        days = store.days(v["video_id"])
        w = windows(v, days, now)
        tot_min = sum(d["minutes"] for d in days)
        wt = sum(d["avg_view_pct"] * d["views"] for d in days)
        nv = sum(d["views"] for d in days)
        rows.append({
            "video_id": v["video_id"], "short_id": l["short_id"], "idea_id": l["idea_id"], "how": l["how"], "title": v["title"], "hook": (idea or {}).get("hook", ""), "published_at": v["published_at"],
            "score": (idea or {}).get("engagement_score") or 0, "mechanisms": (idea or {}).get("mechanisms", []),
            "style": sh.get("settings", {}).get("visual_style") or (idea or {}).get("style", ""), "tone": sh.get("settings", {}).get("tone_id", ""),
            "views": v["views"], "likes": v["likes"], "comments": v["comments"], "watch_min": round(tot_min, 1), "avg_view_pct": round(wt / nv, 1) if nv else 0,
            "subs": sum(d["subs"] for d in days), "shares": sum(d["shares"] for d in days), "has_days": bool(days), **w})
    rows.sort(key=lambda r: -r["published_at"])
    return {"rows": rows, "groups": groups(rows), "linked": len(rows), "videos": len(vids), "views": sum(r["views"] for r in rows)}


def groups(rows: list[dict]) -> dict:
    """Average views in the first 7 days by picture style, tone, idea score band and attention mechanism (only videos whose 7 days are complete)."""
    done = [r for r in rows if r["v7_done"]]

    def of(keys):
        acc: dict[str, list[int]] = {}
        for r in done:
            for k in keys(r):
                if k:
                    acc.setdefault(k, []).append(r["v7"])
        return sorted(({"key": k, "n": len(v), "avg_v7": round(sum(v) / len(v))} for k, v in acc.items()), key=lambda x: -x["avg_v7"])

    return {"style": of(lambda r: [r["style"]]), "tone": of(lambda r: [r["tone"]]), "score": of(lambda r: [band(r["score"])]), "mechanism": of(lambda r: r["mechanisms"]), "n": len(done)}


def unlinked(limit: int = 40) -> list[dict]:
    have = {l["video_id"] for l in store.links()}
    return [{"video_id": v["video_id"], "title": v["title"], "views": v["views"], "published_at": v["published_at"]} for v in store.videos() if v["video_id"] not in have][:limit]


def link_targets() -> list[dict]:
    """Shorts a video can still be tied to (made from an idea, not linked yet)."""
    taken = {l["short_id"] for l in store.links()}
    return [{"short_id": c["short_id"], "title": (c["titles"] or [""])[0]} for c in _finished_shorts() if c["short_id"] not in taken]
