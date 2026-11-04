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
