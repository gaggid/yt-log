"""Web signals for idea discovery. The gateway's `web_search` tool (POST {base_url}/tools/web_search, DuckDuckGo behind it) is called by our code, one query at a time (the key allows one
request at a time), and the results are handed to the chat model as numbered signals. The model never calls a tool itself. When search is down the run goes on without signals (ungrounded)."""
import asyncio
import random
from datetime import datetime

import httpx

QUERY_TIMEOUT_S = 60
MAX_SIGNALS = 36
SNIPPET_CHARS = 220
QUERIES_PER_RUN = 6
CONCURRENCY_POLLS = 30

# Short queries work best (a long one can return nothing). {month} = "November", {year} = 2026, {day} = 8. The first two are always used, the rest are rotated.
ALWAYS = ["India news today", "on this day in history {month} {day}"]
BANK = [
    "trending science discovery {month} {year}",
    "India defence technology news {month} {year}",
    "India economy surprising facts {year}",
    "brain psychology study {year}",
    "space news {month} {year}",
    "India history anniversary {month}",
    "viral facts {year}",
    "engineering megaproject {year}",
    "health breakthrough {month} {year}",
    "geopolitics explained {month} {year}",
    "ancient India science {year}",
    "technology AI news {month} {year}",
]


def queries(now: datetime | None = None, rnd: random.Random | None = None) -> list[str]:
    now = now or datetime.now()
    rnd = rnd or random.Random()
    fill = {"month": now.strftime("%B"), "year": now.year, "day": now.day}
    picked = ALWAYS + rnd.sample(BANK, QUERIES_PER_RUN - len(ALWAYS))
    return [q.format(**fill) for q in picked]


async def _search(client: httpx.AsyncClient, base: str, key: str, query: str) -> list[dict]:
    for _ in range(CONCURRENCY_POLLS):                # another caller may hold the key (one request at a time): wait for it
        r = await client.post(f"{base.rstrip('/')}/tools/web_search", json={"query": query}, headers={"Authorization": f"Bearer {key}"}, timeout=QUERY_TIMEOUT_S)
        if r.status_code == 429 and "concurrency_limit" in r.text:
            await asyncio.sleep(10)
            continue
        break
    if r.status_code != 200:
        return []
    rows = ((r.json().get("data") or {}).get("results")) or []
    return [{"title": (x.get("title") or "").strip(), "url": (x.get("url") or "").strip(), "snippet": " ".join((x.get("snippet") or "").split())[:SNIPPET_CHARS], "query": query}
            for x in rows if x.get("title") and x.get("url")]


async def signals(s: dict, key: str, now: datetime | None = None, rnd: random.Random | None = None) -> list[dict]:
    """Numbered web signals [{n, title, url, snippet}]; [] when search is unavailable (a failed query is skipped, never raised)."""
    out: list[dict] = []
    seen: set[str] = set()
    async with httpx.AsyncClient() as client:
        for q in queries(now, rnd):
            try:
                rows = await _search(client, s["base_url"], key, q)
            except Exception as e:  # noqa: BLE001 - search is a bonus, never a reason to stop
                print(f"[ideas] search '{q}' failed: {e}", flush=True)
                continue
            for x in rows[:6]:
                if x["url"] not in seen:
                    seen.add(x["url"])
                    out.append(x)
    out = out[:MAX_SIGNALS]
    return [{"n": i + 1, **{k: x[k] for k in ("title", "url", "snippet")}} for i, x in enumerate(out)]


def block(sigs: list[dict]) -> str:
    """The signals as prompt text."""
    if not sigs:
        return ""
    lines = [f"{x['n']}. {x['title']} - {x['snippet']}" if x["snippet"] else f"{x['n']}. {x['title']}" for x in sigs]
    return ("WEB SIGNALS (real search results from today; the number is the signal id):\n" + "\n".join(lines) +
            "\n\nUse them: at least half of the ideas must be built on a signal (a current story, a new finding, or an anniversary or historical event the signals point to), and each such idea lists the "
            "signal ids it uses in \"sources\" (for example [3, 7]). Use only facts the signals or your own sure knowledge support; never invent a detail. The other ideas may be evergreen or historical, with \"sources\": [].")


def pick(sigs: list[dict], ids: list[int]) -> list[dict]:
    """The sources an idea cites: [{title, url}] for the valid ids."""
    by = {x["n"]: x for x in sigs}
    out, seen = [], set()
    for i in ids or []:
        x = by.get(int(i)) if str(i).lstrip("-").isdigit() else None
        if x and x["url"] not in seen:
            seen.add(x["url"])
            out.append({"title": x["title"], "url": x["url"]})
    return out
