"""Real-world context for the character brain: weather for her city and news headlines
relevant to her interests. Both are optional — failures are silent. Results cached 30 min.
Also provides the 24-hour day arc: time band, energy, appropriate/avoid activities, day type,
and what the character has already done today (so she never repeats herself)."""
import asyncio
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime

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
    (3, 5):   "spring",
    (6, 9):   "monsoon season",
    (10, 11): "post-monsoon season",
    (12, 2):  "winter",
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
    elif b.get("season"):
        # only fall back to season name when real weather unavailable
        parts.append(b["season"])
    if b.get("news"):
        parts.append("Trending: " + " · ".join(b["news"][:3]))
    return " | ".join(parts) if parts else ""


# ── 24-hour day arc ────────────────────────────────────────────────────────────

# (start_h, end_h, name, energy 0-3, appropriate[], never[])
_BANDS = [
    ( 0,  6, "pre-dawn",  0,
      ["sleep", "late-night reflection", "insomnia scrolling"],
      ["exercise", "social outings", "work calls", "cooking full meals"]),
    ( 6, 10, "morning",   2,
      ["morning routine", "chai", "breakfast", "workout", "planning the day", "commute"],
      ["heavy social events", "late-night content"]),
    (10, 14, "midday",    3,
      ["focused work", "study", "errands", "lunch", "skill practice", "calls"],
      ["wind-down", "passive TV watching", "napping (unless very tired)"]),
    (14, 18, "afternoon", 2,
      ["creative work", "casual social", "snack", "light practice", "browsing", "short nap"],
      ["heavy decisions", "intense workouts late in this band"]),
    (18, 22, "evening",   3,
      ["dinner", "friends", "outings", "phone calls", "hobbies", "cooking", "watching something"],
      ["focused deep work", "studying", "starting new projects"]),
    (22, 24, "night",     1,
      ["wind-down", "reading", "reflection", "journalling", "skincare routine"],
      ["exercise", "social outings", "starting meals", "intense screen time"]),
]


def _current_band() -> dict:
    h = datetime.now().hour
    for start, end, name, energy, appropriate, never in _BANDS:
        if start <= h < end:
            return {"name": name, "hours": f"{start:02d}–{end:02d}",
                    "energy": energy, "appropriate": appropriate, "never": never}
    return _BANDS[-1]  # fallback


def _day_type() -> dict:
    dt  = datetime.now()
    dow = dt.weekday()   # 0=Mon … 6=Sun
    if dow == 6:
        kind = "Sunday — rest and reflection; good for introspection and week-prep"
    elif dow == 5:
        kind = "Saturday — free day; high energy for outings, social and creative experiments"
    else:
        kind = "weekday — work or study obligations; goal-directed activities more likely"
    month_start = dt.day == 1
    return {"kind": kind, "month_start": month_start}


def _done_today(char_id: str) -> list[str]:
    """Activities already logged in think events since midnight today. Fail-silent."""
    try:
        from story import db
        midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        rows = db.q(
            "SELECT outputs FROM char_life_events WHERE char_id=? AND event_type='think' AND created_at >= ?",
            (char_id, midnight),
        )
        done = []
        for r in rows:
            out = db.jload(r["outputs"], {})
            a = out.get("activity", "").strip()
            if a:
                done.append(a)
        return done
    except Exception:
        return []


_MEAL_KEYWORDS = {
    "breakfast": ["breakfast", "morning meal", "poha", "paratha", "idli", "upma", "toast"],
    "lunch":     ["lunch", "midday meal", "dal rice", "roti sabzi", "thali"],
    "dinner":    ["dinner", "evening meal", "supper", "night meal"],
    "snack":     ["snack", "snacking", "chai snack", "evening snack"],
}


def _meals_done(activities: list[str]) -> list[str]:
    """Which meal slots are already filled today based on activity descriptions."""
    text = " ".join(activities).lower()
    return [meal for meal, kw in _MEAL_KEYWORDS.items() if any(k in text for k in kw)]


def day_arc(char: dict) -> dict:
    """Full day-arc context: band, day type, already-done-today list."""
    band = _current_band()
    dtype = _day_type()
    done = _done_today(char["id"])
    return {**band, **dtype, "done_today": done, "meals_done": _meals_done(done)}


def format_day_arc(arc: dict) -> str:
    """Multi-line block injected into stage-1 context."""
    lines = [
        f"Time band: {arc['name']} ({arc['hours']}), energy {arc['energy']}/3.",
        f"Good activities now: {', '.join(arc['appropriate'][:4])}.",
        f"Not appropriate now: {', '.join(arc['never'][:3])}.",
        f"Day type: {arc['kind']}.",
    ]
    if arc.get("done_today"):
        activities = ", ".join(arc["done_today"][:6])
        lines.append(f"You have already done today: {activities}. Do not repeat these — pick something different.")
    if arc.get("meals_done"):
        lines.append(f"Meals already eaten today: {', '.join(arc['meals_done'])}. You only eat each meal once — do not eat this again.")
    if arc.get("month_start"):
        lines.append("It is the first of the month — a natural moment to reflect on the past month and review your goals.")
    return "\n".join(lines)
