"""Autonomous web surfing for Virtual Life characters.

Trigger: curiosity spark >= 3, or interest with no recent web memory, up to 2
auto-surfs per character per day. Owner can also push a manual surf via API.

Pipeline:
  1. pick_topic     — highest-spark curiosity or most-active interest
  2. ddg_search     — DuckDuckGo Lite HTML scrape → top 2 URLs
  3. fetch + strip  — fetch_url → plain text (strip HTML tags, limit 3000 chars)
  4. LLM extract    — 3-4 impressions the character would actually remember
  5. form memories  — learning memories with source "web:{url_hash}"
  6. bump           — curiosity +1.5 spark, may spawn a new curiosity
"""
import hashlib
import json
import re
import time

import httpx

from story import db
from story.ingest import fetch_url

SURF_MAX_PER_DAY    = 2      # auto-surfs capped here
IMPRESSION_N        = 3      # impressions to extract per page
SPARK_THRESHOLD     = 3.0    # curiosity spark needed to trigger auto-surf
DDG_TIMEOUT         = 8      # seconds for the DuckDuckGo search request
FETCH_CHAR_LIMIT    = 3000   # characters of page text sent to LLM

_STOP = {"the","and","for","she","her","was","are","with","that","this","have",
         "from","just","been","like","what","when","felt","then","they","were",
         "said","him","his","had","but","not","all","one","our","out","can","its"}


# ── topic selection ───────────────────────────────────────────────────────────

def pick_topic(prof: dict) -> tuple[str, str] | None:
    """Return (topic_text, category) or None. Prefers highest-spark curiosity,
    falls back to the most-active confirmed interest."""
    curiosities = sorted(
        [c for c in (prof.get("curiosities") or []) if c.get("spark", 0) >= SPARK_THRESHOLD],
        key=lambda x: -x["spark"],
    )
    if curiosities:
        c = curiosities[0]
        return c["name"], c.get("category", "general")

    # fallback: highest-intensity confirmed interest
    interests = prof.get("interests") or {}
    best, best_int = None, 0
    for cat, val in interests.items():
        intensity = val.get("intensity", 5) if isinstance(val, dict) else 5
        text      = val.get("text", "") if isinstance(val, dict) else str(val or "")
        if intensity > best_int and text.strip():
            best, best_int = (text.strip(), cat), intensity

    return best  # may be None


# ── DuckDuckGo HTML search ────────────────────────────────────────────────────

async def _ddg_urls(query: str) -> list[str]:
    """Scrape DuckDuckGo HTML endpoint for top result URLs (no API key needed)."""
    import urllib.parse
    encoded = query.replace(" ", "+")
    try:
        async with httpx.AsyncClient(
            timeout=DDG_TIMEOUT,
            follow_redirects=False,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            },
        ) as client:
            r = await client.get(f"https://html.duckduckgo.com/html/?q={encoded}")
        html = r.text
    except Exception:
        return []

    # DDG HTML: result links are redirect URLs containing uddg=ENCODED_REAL_URL
    uddg = re.findall(r'uddg=([^&"\'<\s]+)', html)
    urls = []
    for raw in uddg:
        try:
            u = urllib.parse.unquote(raw)
        except Exception:
            continue
        if not u.startswith("http"):
            continue
        urls.append(u)

    # deduplicate by domain
    seen, clean = set(), []
    for u in urls:
        domain = re.sub(r'^https?://(www\.)?', '', u).split('/')[0]
        if domain in seen:
            continue
        seen.add(domain)
        clean.append(u)
        if len(clean) >= 2:
            break
    return clean


# ── text extraction ───────────────────────────────────────────────────────────

def _strip_html(raw: bytes, ctype: str) -> str:
    """Very lightweight HTML → plain text. No external parser needed."""
    try:
        charset = "utf-8"
        m = re.search(r"charset=([\w-]+)", ctype, re.IGNORECASE)
        if m:
            charset = m.group(1)
        text = raw.decode(charset, errors="replace")
    except Exception:
        text = raw.decode("utf-8", errors="replace")

    # remove script / style blocks
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    # strip remaining tags
    text = re.sub(r"<[^>]+>", " ", text)
    # collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text[:FETCH_CHAR_LIMIT]


# ── LLM impression extraction ─────────────────────────────────────────────────

async def _extract_impressions(text: str, topic: str, backend) -> list[str]:
    """Ask the LLM for things the character would genuinely remember."""
    prompt = (
        f"The character was curious about '{topic}' and read this:\n\n"
        f"{text}\n\n"
        f"Write exactly {IMPRESSION_N} short sentences — things she would genuinely remember "
        f"after reading: a surprising fact, a useful insight, something that changed how she "
        f"thinks about '{topic}'. Each sentence stands alone, first-person is fine. "
        f"Return a JSON array of {IMPRESSION_N} strings."
    )
    try:
        result = await backend.complete(
            messages=[
                {"role": "system",
                 "content": "Extract memorable impressions from text. Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=250,
            params={"response_format": {"type": "json_object"}},
        )
        raw = json.loads(result.content)
        items = raw if isinstance(raw, list) else next((v for v in raw.values() if isinstance(v, list)), [])
        impressions = [str(x).strip() for x in items if str(x).strip()][:IMPRESSION_N]
        return impressions or [text[:100] + "…"]
    except Exception:
        # fallback: first meaningful sentence from the text
        sent = re.split(r"[.!?]", text)[0].strip()
        return [sent[:100] + "…"] if sent else []


# ── rate limit helpers ────────────────────────────────────────────────────────

def _surfs_today(char_id: str) -> int:
    today = __import__("datetime").date.today().isoformat()
    row = db.one(
        "SELECT web_surfs_today FROM char_profile_snapshots WHERE char_id=? AND snapshot_date=?",
        (char_id, today),
    )
    return int(row["web_surfs_today"]) if row else 0


def _inc_surfs(char_id: str) -> None:
    today = __import__("datetime").date.today().isoformat()
    db.ex(
        "UPDATE char_profile_snapshots SET web_surfs_today=web_surfs_today+1 "
        "WHERE char_id=? AND snapshot_date=?",
        (char_id, today),
    )


def should_surf(char_id: str, prof: dict) -> bool:
    """True when auto-surf conditions are met and daily cap not reached."""
    if _surfs_today(char_id) >= SURF_MAX_PER_DAY:
        return False
    return pick_topic(prof) is not None


# ── main surf session ─────────────────────────────────────────────────────────

async def surf_session(char: dict, backend, topic: str | None = None,
                       category: str = "general") -> dict | None:
    """Full surf pipeline. Returns summary or None on failure.
    Pass topic/category for a manual surf; leave None for auto-pick.
    """
    from . import memory as memory_mod, interests as interests_mod, profile as profile_mod, store

    prof = profile_mod.get(char)

    if topic is None:
        result = pick_topic(prof)
        if not result:
            return None
        topic, category = result

    urls = await _ddg_urls(topic)
    if not urls:
        return None

    all_impressions: list[str] = []
    sourced_urls: list[str] = []

    for url in urls:
        try:
            raw, ctype, final_url = await fetch_url(url)
            page_text = _strip_html(raw, ctype)
            if len(page_text) < 100:
                continue
            impressions = await _extract_impressions(page_text, topic, backend)
            if impressions:
                all_impressions.extend(impressions)
                sourced_urls.append(final_url)
        except Exception:
            continue  # failed fetch → skip silently

    if not all_impressions:
        return None

    # form memories
    url_hash  = hashlib.sha1(sourced_urls[0].encode()).hexdigest()[:8] if sourced_urls else "web"
    source    = f"web:{url_hash}"
    now       = time.time()
    for imp in all_impressions:
        if not imp.strip():
            continue
        tags = [w.lower() for w in re.findall(r"[a-zA-Z]{4,}", imp) if w.lower() not in _STOP][:8]
        memory_mod.form(
            char["id"],
            {"activity": f"Read about {topic} online", "space": "", "mood": "curious", "thought": imp},
            category="learning",
            source=source,
        )

    # bump curiosity spark for the topic
    fresh = store.get(char["id"])
    interests_mod.curiosity_bump_from_activity(fresh, topic + " " + " ".join(all_impressions))

    # check if the topic itself is a curiosity and bump directly
    curiosities = list((fresh.get("profile") or {}).get("curiosities") or [])
    for c in curiosities:
        if c["name"].lower() == topic.lower():
            c["spark"] = min(10.0, c["spark"] + 1.5)
            c["last_bumped_ts"] = now
    if curiosities != (fresh.get("profile") or {}).get("curiosities"):
        from . import profile as pm
        pm.patch(fresh, {"curiosities": curiosities})

    # spawn new curiosity from the impressions if something novel appears
    from . import interests as im
    all_text = " ".join(all_impressions)
    words = [w.lower() for w in re.findall(r"[a-zA-Z]{5,}", all_text) if w.lower() not in _STOP]
    freq: dict = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    known = {c["name"].lower() for c in curiosities}
    known |= {k.lower() for k in (fresh.get("profile") or {}).get("interests", {}).keys()}
    novel = [(w, cnt) for w, cnt in freq.items() if w not in known and cnt >= 2]
    if novel:
        new_word = sorted(novel, key=lambda x: -x[1])[0][0]
        im.curiosity_encounter(fresh, new_word.capitalize(), "web")

    store.save(fresh)

    # increment daily surf counter
    _inc_surfs(char["id"])

    return {
        "topic":       topic,
        "category":    category,
        "urls":        sourced_urls,
        "impressions": all_impressions,
        "memories_formed": len(all_impressions),
    }
