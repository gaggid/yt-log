"""Skills and mastery tracking for a virtual character.

Skills grow from: activity keyword matches, learning memories, and owner-seeded levels.
Level thresholds (cumulative practice hours):
  L1 Beginner   0h+
  L2 Dabbling   5h+
  L3 Consistent 20h+
  L4 Practiced  60h+
  L5 Fluent     150h+
"""
import time

LEVELS = [
    (0,   "L1", "Beginner"),
    (5,   "L2", "Dabbling"),
    (20,  "L3", "Consistent"),
    (60,  "L4", "Practiced"),
    (150, "L5", "Fluent"),
]

_ACTIVITY_KEYWORDS: dict[str, list[str]] = {
    "bhangra":      ["bhangra", "dance", "giddha", "footwork", "dhol"],
    "yoga":         ["yoga", "asana", "pranayam", "meditation", "stretching"],
    "cooking":      ["cook", "cooking", "baking", "recipe", "kitchen", "dal", "sabzi", "roti"],
    "reading":      ["read", "reading", "book", "chapter", "fiction", "novel"],
    "music":        ["guitar", "sitar", "tabla", "singing", "veena", "piano", "practice"],
    "writing":      ["write", "writing", "journal", "blog", "script", "story"],
    "photography":  ["photo", "shoot", "camera", "edit", "lightroom"],
    "fitness":      ["workout", "gym", "run", "jog", "exercise", "walk"],
    "art":          ["sketch", "draw", "paint", "canvas", "watercolour"],
    "coding":       ["code", "coding", "program", "debug", "build", "app"],
}


def level_for(hours: float) -> tuple[str, str]:
    """Return (code, label) for a given practice hour count."""
    lv = LEVELS[0]
    for threshold, code, label in LEVELS:
        if hours >= threshold:
            lv = (code, label)
    return lv


def bump_hours(char: dict, activity_text: str, increment: float = 0.25) -> list[str]:
    """Keyword-match activity against known skills; bump hours; return levelled-up skill names."""
    prof = char.get("profile") or {}
    skills: list[dict] = list(prof.get("skills") or [])
    if not skills:
        return []

    act = activity_text.lower()
    levelled_up = []
    changed = False

    for sk in skills:
        name = sk.get("name", "").lower()
        # match on skill name or its keyword list
        keywords = _ACTIVITY_KEYWORDS.get(name, [name])
        if any(kw in act for kw in keywords):
            old_code, _ = level_for(sk.get("hours", 0.0))
            sk["hours"] = round(sk.get("hours", 0.0) + increment, 2)
            sk["last_practiced_at"] = time.time()
            new_code, new_label = level_for(sk["hours"])
            sk["level"] = new_code
            if new_code != old_code:
                levelled_up.append(sk["name"])
            changed = True

    if changed:
        prof["skills"] = skills
        char["profile"] = prof
    return levelled_up


def inject_line(prof: dict) -> str:
    """Return a skills context line for the brain prompt, or empty string if no skills."""
    skills: list[dict] = prof.get("skills") or []
    if not skills:
        return ""
    parts = []
    for sk in skills:
        code, label = level_for(sk.get("hours", 0.0))
        h = sk.get("hours", 0.0)
        parts.append(f"{sk['name']} ({code} — {label}, {h:.0f}h)")
    return "Your skills: " + "; ".join(parts) + "."


def add_skill(char: dict, name: str, category: str = "", seed_hours: float = 0.0) -> dict:
    """Owner adds a skill; returns the new skill dict. Caller must store.save(char)."""
    prof = char.get("profile") or {}
    skills: list[dict] = list(prof.get("skills") or [])
    # dedup by name (case-insensitive)
    if any(s["name"].lower() == name.lower() for s in skills):
        return next(s for s in skills if s["name"].lower() == name.lower())
    code, label = level_for(seed_hours)
    sk = {
        "name": name,
        "category": category,
        "hours": seed_hours,
        "level": code,
        "started_at": time.time(),
        "last_practiced_at": time.time() if seed_hours > 0 else None,
    }
    skills.append(sk)
    prof["skills"] = skills
    char["profile"] = prof
    return sk


def remove_skill(char: dict, name: str) -> bool:
    """Remove a skill by name. Returns True if removed. Caller must store.save(char)."""
    prof = char.get("profile") or {}
    skills: list[dict] = list(prof.get("skills") or [])
    before = len(skills)
    skills = [s for s in skills if s["name"].lower() != name.lower()]
    prof["skills"] = skills
    char["profile"] = prof
    return len(skills) < before
