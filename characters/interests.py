"""Dynamic interests engine for Virtual Life.

Interests have an intensity (1-10) that climbs when engaged and atrophies
when ignored. The brain can propose new interests; they sit as pending life
events until the owner approves them.

Storage: profile["interests"] stays a dict keyed by category, but values
are now dicts instead of plain strings. Plain-string values (legacy) are
normalised on first write.
"""
import time

_STOP = {"a", "an", "the", "in", "to", "for", "of", "on", "at", "my", "get",
         "do", "is", "it", "be", "as", "or", "and", "with", "that", "this",
         "are", "was", "has", "not", "but"}

_ATROPHY_AFTER_DAYS = 14   # no engagement for this long → start decaying
_ATROPHY_PER_WEEK   = 1    # lose this much intensity per week of inactivity
_ARCHIVE_AFTER_DAYS = 30   # intensity=0 for this long → archived
_INTENSITY_MIN      = 1
_INTENSITY_MAX      = 10


def _now() -> float:
    return time.time()


def _keywords(text: str) -> set[str]:
    return {w for w in text.lower().split() if len(w) >= 3 and w not in _STOP}


def _normalise(value) -> dict:
    """Convert a legacy string interest or partial dict into a full interest dict."""
    if isinstance(value, str):
        return {
            "text": value,
            "intensity": 5,
            "last_engaged_ts": _now(),
            "added_by": "owner",
        }
    return {
        "text":             value.get("text", ""),
        "intensity":        int(value.get("intensity", 5)),
        "last_engaged_ts":  float(value.get("last_engaged_ts") or _now()),
        "added_by":         value.get("added_by", "owner"),
    }


def all_interests(prof: dict) -> dict[str, dict]:
    """Return all interests as {category: normalised_dict}."""
    raw = prof.get("interests") or {}
    return {cat: _normalise(val) for cat, val in raw.items() if val}


def bump(char: dict, activity_text: str) -> None:
    """Increase intensity of interests whose keywords appear in the activity text.
    Caller must call store.save(char) after.
    """
    from . import profile as profile_mod
    prof = profile_mod.get(char)
    interests = all_interests(prof)
    act_kw = _keywords(activity_text)
    if not act_kw:
        return

    changed = False
    for cat, idata in interests.items():
        int_kw = _keywords(idata["text"])
        if int_kw & act_kw:
            idata["intensity"] = min(_INTENSITY_MAX, idata["intensity"] + 1)
            idata["last_engaged_ts"] = _now()
            interests[cat] = idata
            changed = True

    if changed:
        raw = dict(char.get("profile") or {}).get("interests") or {}
        for cat, idata in interests.items():
            raw[cat] = idata
        profile_mod.patch(char, {"interests": raw})


def tick(char: dict) -> None:
    """Atrophy inactive interests; archive dead ones. Caller must store.save(char)."""
    from . import profile as profile_mod
    prof = profile_mod.get(char)
    interests = all_interests(prof)
    now = _now()
    raw = dict((char.get("profile") or {}).get("interests") or {})
    archived = list(char.get("profile", {}).get("archived_interests") or [])

    for cat, idata in interests.items():
        days_idle = (now - idata["last_engaged_ts"]) / 86400
        if days_idle > _ARCHIVE_AFTER_DAYS and idata["intensity"] <= _INTENSITY_MIN:
            archived.append({"category": cat, **idata, "archived_at": now})
            raw.pop(cat, None)
        elif days_idle > _ATROPHY_AFTER_DAYS:
            weeks_over = (days_idle - _ATROPHY_AFTER_DAYS) / 7
            new_intensity = max(_INTENSITY_MIN, idata["intensity"] - int(weeks_over * _ATROPHY_PER_WEEK))
            if new_intensity != idata["intensity"]:
                idata["intensity"] = new_intensity
                raw[cat] = idata

    profile_mod.patch(char, {"interests": raw, "archived_interests": archived})


def inject_line(prof: dict) -> str:
    """Short prompt line listing interests with their current intensities."""
    interests = all_interests(prof)
    if not interests:
        return ""
    parts = []
    for cat, idata in sorted(interests.items(), key=lambda x: -x[1]["intensity"]):
        text = idata["text"].strip()
        if text:
            parts.append(f"{text} ({idata['intensity']}/10)")
    if not parts:
        return ""
    return "Your interests (intensity 1-10, higher = more active/passionate): " + "; ".join(parts) + "."


def add_character_interest(char: dict, name: str, category: str) -> None:
    """Add an owner-approved character-proposed interest. Caller must store.save(char)."""
    from . import profile as profile_mod
    prof = profile_mod.get(char)
    raw = dict((char.get("profile") or {}).get("interests") or {})
    key = category.lower().strip() or name.lower().strip()[:20]
    if key not in raw:
        raw[key] = {
            "text": name,
            "intensity": 3,
            "last_engaged_ts": _now(),
            "added_by": "character",
        }
        profile_mod.patch(char, {"interests": raw})


# ── curiosity pool ─────────────────────────────────────────────────────────────
# Self-discovered sparks of interest. No manual gate — they form, grow, and
# either promote into real interests or fade away on their own.

_CURIOSITY_DECAY_PER_DAY = 0.5   # spark lost per idle day
_CURIOSITY_MATCH_BUMP    = 2.0   # spark gained when activity touches this curiosity
_CURIOSITY_NEW_BUMP      = 1.0   # spark gained on a fresh encounter
_CURIOSITY_PROMOTE_AT    = 5.0   # auto-promote to confirmed interest at this threshold


def _curiosity_key(name: str) -> str:
    return name.lower().strip()[:40]


def _promote_ready(char: dict) -> None:
    """Promote any curiosity that hit the threshold into a confirmed interest (in-place)."""
    prof = char.get("profile") or {}
    curiosities = list(prof.get("curiosities") or [])
    raw_interests = dict(prof.get("interests") or {})
    remaining = []
    for c in curiosities:
        if c["spark"] >= _CURIOSITY_PROMOTE_AT:
            cat = c["category"]
            if cat not in raw_interests:
                raw_interests[cat] = {
                    "text": c["name"],
                    "intensity": 3,
                    "last_engaged_ts": _now(),
                    "added_by": "character",
                }
        else:
            remaining.append(c)
    prof["curiosities"] = remaining
    prof["interests"]   = raw_interests
    char["profile"]     = prof


def curiosity_encounter(char: dict, name: str, category: str) -> None:
    """Record a self-discovered curiosity or bump its spark. No approval needed.
    Caller must store.save(char) after.
    """
    name = name.strip()
    if not name:
        return
    prof = char.get("profile") or {}
    curiosities = list(prof.get("curiosities") or [])
    key = _curiosity_key(name)
    for c in curiosities:
        if _curiosity_key(c["name"]) == key:
            c["spark"] = min(10.0, c["spark"] + _CURIOSITY_NEW_BUMP)
            c["last_bumped_ts"] = _now()
            break
    else:
        curiosities.append({
            "name":           name,
            "category":       category.lower().strip() or "general",
            "spark":          _CURIOSITY_NEW_BUMP,
            "first_seen_ts":  _now(),
            "last_bumped_ts": _now(),
        })
    prof["curiosities"] = curiosities
    char["profile"]     = prof
    _promote_ready(char)


def curiosity_bump_from_activity(char: dict, activity_text: str) -> None:
    """Bump curiosities whose name keywords match the activity. Caller must store.save(char)."""
    prof = char.get("profile") or {}
    curiosities = list(prof.get("curiosities") or [])
    if not curiosities:
        return
    act_kw = _keywords(activity_text)
    if not act_kw:
        return
    changed = False
    for c in curiosities:
        if _keywords(c["name"]) & act_kw:
            c["spark"] = min(10.0, c["spark"] + _CURIOSITY_MATCH_BUMP)
            c["last_bumped_ts"] = _now()
            changed = True
    if changed:
        prof["curiosities"] = curiosities
        char["profile"]     = prof
        _promote_ready(char)


def curiosity_tick(char: dict) -> None:
    """Decay all curiosities; silently drop dead ones. Caller must store.save(char)."""
    prof = char.get("profile") or {}
    curiosities = list(prof.get("curiosities") or [])
    if not curiosities:
        return
    now = _now()
    alive = []
    for c in curiosities:
        days_idle = (now - c["last_bumped_ts"]) / 86400
        c["spark"] = max(0.0, c["spark"] - days_idle * _CURIOSITY_DECAY_PER_DAY)
        if c["spark"] > 0:
            alive.append(c)
    prof["curiosities"] = alive
    char["profile"]     = prof


def curiosity_inject_line(prof: dict) -> str:
    """Prompt line listing active curiosities so they can shape behaviour."""
    curiosities = [c for c in (prof.get("curiosities") or []) if c.get("spark", 0) > 0]
    if not curiosities:
        return ""
    names = [c["name"] for c in sorted(curiosities, key=lambda x: -x["spark"])]
    return ("Things you've recently noticed or become curious about (not full interests yet, "
            "but on your mind): " + ", ".join(names) + ".")
