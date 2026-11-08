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
RETRY_EMPTY_S = 2.0
PAGES_PER_RUN = 4                 # full pages read with fetch_url (the first result of the first queries)
PAGE_CHARS = 1400                 # asked of fetch_url
DETAIL_CHARS = 700                # kept per page for the prompt
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
    rows = ((await _post_tool(client, base, key, "web_search", {"query": query})).get("data") or {}).get("results") or []
    return [{"title": (x.get("title") or "").strip(), "url": (x.get("url") or "").strip(), "snippet": " ".join((x.get("snippet") or "").split())[:SNIPPET_CHARS], "query": query}
            for x in rows if x.get("title") and x.get("url")]


async def _post_tool(client: httpx.AsyncClient, base: str, key: str, name: str, body: dict) -> dict:
    """POST {base}/tools/{name}; waits while another caller holds the one-request-at-a-time key. Returns the JSON answer, {} on any failure."""
    r = None
    for _ in range(CONCURRENCY_POLLS):
        r = await client.post(f"{base.rstrip('/')}/tools/{name}", json=body, headers={"Authorization": f"Bearer {key}"}, timeout=QUERY_TIMEOUT_S)
        if r.status_code == 429 and "concurrency_limit" in r.text:
            await asyncio.sleep(10)
            continue
        break
    return r.json() if r is not None and r.status_code == 200 else {}


async def today(s: dict, key: str) -> datetime:
    """The date in India from the gateway's `now` tool (the server clock when the tool is unavailable)."""
    try:
        async with httpx.AsyncClient() as client:
            iso = ((await _post_tool(client, s["base_url"], key, "now", {"timezone": "Asia/Kolkata"})).get("data") or {}).get("iso")
        if iso:
            return datetime.fromisoformat(iso).replace(tzinfo=None)
    except Exception as e:  # noqa: BLE001
        print(f"[ideas] now tool failed: {e}", flush=True)
    return datetime.now()


def _page_text(res: dict) -> str:
    """The readable part of a fetch_url answer: its text without the Title/URL header lines."""
    text = str(res.get("result") or "")
    lines = [ln for ln in text.split("\n") if ln.strip() and not ln.startswith(("Title:", "URL:"))]
    return " ".join(" ".join(lines).split())[:DETAIL_CHARS]


async def _read_pages(client: httpx.AsyncClient, base: str, key: str, sigs: list[dict], first_of: list[str]) -> None:
    """Add `detail` (the start of the page) to the first result of each of the first queries, so the ideas rest on more than a snippet."""
    done = 0
    for q in first_of:
        if done >= PAGES_PER_RUN:
            break
        x = next((v for v in sigs if v.get("query") == q), None)
        if not x:
            continue
        try:
            res = await _post_tool(client, base, key, "fetch_url", {"url": x["url"], "max_chars": PAGE_CHARS})
        except Exception as e:  # noqa: BLE001 - a page that cannot be read is skipped
            print(f"[ideas] fetch '{x['url']}' failed: {e}", flush=True)
            continue
        text = _page_text(res)
        if len(text) > 120:
            x["detail"] = text
            done += 1


async def signals(s: dict, key: str, now: datetime | None = None, rnd: random.Random | None = None) -> list[dict]:
    """Numbered web signals [{n, title, url, snippet, detail?}]; [] when search is unavailable (a failed query is skipped, never raised)."""
    out: list[dict] = []
    seen: set[str] = set()
    now = now or await today(s, key)
    qs = queries(now, rnd)
    async with httpx.AsyncClient() as client:
        for q in qs:
            try:
                rows = await _search(client, s["base_url"], key, q)
                if not rows:                                       # the search engine sometimes answers nothing at once; one more try
                    await asyncio.sleep(RETRY_EMPTY_S)
                    rows = await _search(client, s["base_url"], key, q)
            except Exception as e:  # noqa: BLE001 - search is a bonus, never a reason to stop
                print(f"[ideas] search '{q}' failed: {e}", flush=True)
                continue
            for x in rows[:6]:
                if x["url"] not in seen:
                    seen.add(x["url"])
                    out.append(x)
        out = out[:MAX_SIGNALS]
        await _read_pages(client, s["base_url"], key, out, qs)
    return [{"n": i + 1, **{k: x[k] for k in ("title", "url", "snippet", "detail") if x.get(k)}} for i, x in enumerate(out)]


def block(sigs: list[dict]) -> str:
    """The signals as prompt text."""
    if not sigs:
        return ""
    lines = [(f"{x['n']}. {x['title']} - {x['snippet']}" if x.get("snippet") else f"{x['n']}. {x['title']}") + (f"\n   page: {x['detail']}" if x.get("detail") else "") for x in sigs]
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
