"""Real-world context for the character brain: weather for her city and news headlines
relevant to her interests. Both are optional — failures are silent. Results cached 30 min."""
import asyncio
import re
import time
import xml.etree.ElementTree as ET

import httpx

CACHE: dict = {}
CACHE_TTL_S = 1800   # 30 min

_INTEREST_NEWS_TERMS = {
    "books":   "book review literature",
    "movies":  "bollywood film movies",
    "music":   "music concert artist",
    "food":    "food recipe restaurant",
    "hobbies": "",   # too generic — skip
}

_SEASONS = {
    (3, 5):   "spring (March–May), warm and dry",
    (6, 9):   "monsoon season, humid and rainy",
    (10, 11): "post-monsoon, pleasant weather",
    (12, 2):  "winter (December–February), cool nights",
}


def _season() -> str:
    m = time.localtime().tm_mon
    for (lo, hi), label in _SEASONS.items():
        if lo <= m <= hi or (lo > hi and (m >= lo or m <= hi)):
            return label
    return ""


def _cached(key: str):
    entry = CACHE.get(key)
    if entry and time.time() - entry[0] < CACHE_TTL_S:
        return entry[1]
    return None


def _cache(key: str, value):
    CACHE[key] = (time.time(), value)
    return value


async def _weather(city: str) -> str:
    key = f"weather:{city}"
    if cached := _cached(key):
        return cached
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"https://wttr.in/{city}?format=3")
        text = r.text.strip()
        return _cache(key, text)
    except Exception:
        return ""


async def _news_for_term(client: httpx.AsyncClient, term: str) -> list[str]:
    """Fetch up to 3 headlines from Google News RSS for a search term."""
    url = f"https://news.google.com/rss/search?q={term}+India&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        r = await client.get(url, timeout=8)
        root = ET.fromstring(r.text)
        titles = []
        for item in root.iter("item"):
            t = item.find("title")
            if t is not None and t.text:
                # strip " - Source Name" suffix Google adds
                clean = re.sub(r"\s+-\s+[^-]+$", "", t.text).strip()
                if clean:
                    titles.append(clean)
            if len(titles) >= 3:
                break
        return titles
    except Exception:
        return []


async def _news(interests: dict) -> list[str]:
    key = "news:" + ":".join(sorted(str(v) for v in interests.values()))
    if cached := _cached(key):
        return cached
    terms = [_INTEREST_NEWS_TERMS[k] for k in interests if k in _INTEREST_NEWS_TERMS and interests[k] and _INTEREST_NEWS_TERMS[k]]
    # always include general India headlines
    terms = (terms[:2] or []) + ["India trending today"]
    headlines: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            results = await asyncio.gather(*[_news_for_term(client, t) for t in terms], return_exceptions=True)
        seen: set[str] = set()
        for r in results:
            if isinstance(r, list):
                for h in r:
                    if h not in seen:
                        seen.add(h)
                        headlines.append(h)
            if len(headlines) >= 5:
                break
    except Exception:
        pass
    return _cache(key, headlines[:5])


async def brief(char: dict) -> dict:
    """Return {weather, news, season} — all optional, fail silently."""
    from . import profile as profile_mod
    prof = profile_mod.get(char)
    city = prof.get("city") or "Mumbai"
    interests = prof.get("interests") or {}

    weather, news = await asyncio.gather(
        _weather(city),
        _news(interests),
        return_exceptions=True,
    )
    return {
        "weather": weather if isinstance(weather, str) else "",
        "news": news if isinstance(news, list) else [],
        "season": _season(),
        "city": city,
    }


def format_for_prompt(b: dict) -> str:
    """One-line world context string for the brain's system prompt."""
    parts = []
    if b.get("weather"):
        parts.append(b["weather"])
    if b.get("season"):
        parts.append(b["season"])
    if b.get("news"):
        parts.append("Trending: " + " · ".join(b["news"][:3]))
    return " | ".join(parts) if parts else ""
