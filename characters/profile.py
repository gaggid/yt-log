"""Psychometric profile for a character: personality, interests, spaces, life settings.
Stored in chars.data['profile']. Life events are logged in char_life_events for audit/tuning."""
import hashlib
import time
import uuid

from story import db

DEFAULT_INTERESTS = {"books": "", "movies": "", "music": "", "food": "", "hobbies": ""}
DEFAULT_SPACES = [
    {"name": "Bedroom", "description": ""},
    {"name": "Living Room", "description": ""},
    {"name": "Kitchen", "description": ""},
]


def default_profile() -> dict:
    return {
        "core_character": "",
        "personality": "",
        "city": "",
        "phone": "",
        "fashion_taste": "",
        "chronotype": "",        # "early bird" / "night owl" / "balanced"
        "interests": dict(DEFAULT_INTERESTS),
        "spaces": [dict(s) for s in DEFAULT_SPACES],
        "current_context": "",
        "energy": 80,            # 0–100; drains through the day, restores during sleep
        "sleep_threshold": 20,   # energy below this → character sleeps (loop skips think+draw)
        "life_enabled": False,
        "life_interval_m": 60,
        "auto_draw": False,      # draw automatically when the character thinks the moment is worth a picture
        "shot_styles": ["third_person", "selfie", "pov"],   # parent camera categories the character may use
        "accessories": [],   # [{name, description, ref_image}] recurring props with optional ref photos
        "aspirations": [],   # [{id, text, surfaced_count, first_at, last_at, needs_goal_prompt}]
        "archived_interests": [],  # interests whose intensity hit 0 after long inactivity
        "skills": [],        # [{name, category, hours, level, started_at, last_practiced_at}]
    }


def get(char: dict) -> dict:
    """Return the character's profile (filled with defaults for missing keys)."""
    stored = char.get("profile") or {}
    base = default_profile()
    # merge stored over defaults so missing keys are always present
    merged = {**base, **stored}
    merged["interests"] = {**base["interests"], **(stored.get("interests") or {})}
    if not merged["spaces"]:
        merged["spaces"] = base["spaces"]
    return merged


def patch(char: dict, updates: dict) -> dict:
    """Merge updates into char['profile'] and return the merged profile (caller must call store.save)."""
    prof = dict(char.get("profile") or {})
    for k, v in updates.items():
        if v is None:
            prof.pop(k, None)
        elif k == "interests" and isinstance(v, dict):
            prof["interests"] = {**(prof.get("interests") or {}), **v}
        elif k == "spaces" and isinstance(v, list):
            prof["spaces"] = v
        else:
            prof[k] = v
    char["profile"] = prof
    return get(char)


# ── event log ────────────────────────────────────────────────────────────────

def _eid() -> str:
    return "evt-" + hashlib.sha1(str(time.time()).encode()).hexdigest()[:8]


def log_event(char_id: str, event_type: str, trigger: str, inputs: dict, outputs: dict, attempt: int = 1) -> dict:
    """Write one life event row and return it."""
    eid = _eid()
    db.ex(
        "INSERT INTO char_life_events(id,char_id,event_type,trigger,attempt,inputs,outputs,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (eid, char_id, event_type, trigger, attempt, db.jdump(inputs), db.jdump(outputs), db.now()),
    )
    return get_event(eid)


def get_event(event_id: str) -> dict | None:
    r = db.one("SELECT * FROM char_life_events WHERE id=?", (event_id,))
    if not r:
        return None
    return {**r, "inputs": db.jload(r["inputs"], {}), "outputs": db.jload(r["outputs"], {})}


def list_events(char_id: str, limit: int = 50, before: float | None = None) -> list[dict]:
    if before:
        rows = db.q(
            "SELECT * FROM char_life_events WHERE char_id=? AND created_at < ? ORDER BY created_at DESC LIMIT ?",
            (char_id, before, limit),
        )
    else:
        rows = db.q(
            "SELECT * FROM char_life_events WHERE char_id=? ORDER BY created_at DESC LIMIT ?",
            (char_id, limit),
        )
    return [{**r, "inputs": db.jload(r["inputs"], {}), "outputs": db.jload(r["outputs"], {})} for r in rows]


def list_events_range(char_id: str, start: float, end: float) -> list[dict]:
    rows = db.q(
        "SELECT * FROM char_life_events WHERE char_id=? AND created_at >= ? AND created_at <= ? ORDER BY created_at ASC",
        (char_id, start, end),
    )
    return [{**r, "inputs": db.jload(r["inputs"], {}), "outputs": db.jload(r["outputs"], {})} for r in rows]


def add_aspiration(char: dict, text: str) -> dict:
    """Record or increment a character aspiration. Returns the aspiration dict.
    Caller must call store.save(char) after.
    """
    text = text.strip()
    if not text:
        return {}
    prof = dict(char.get("profile") or {})
    aspirations = list(prof.get("aspirations") or [])
    # dedupe: match if 2+ keywords overlap
    text_words = {w.lower() for w in text.split() if len(w) >= 3}
    for asp in aspirations:
        asp_words = {w.lower() for w in asp["text"].split() if len(w) >= 3}
        if len(text_words & asp_words) >= 2:
            asp["surfaced_count"] += 1
            asp["last_at"] = time.time()
            asp["needs_goal_prompt"] = asp["surfaced_count"] >= 3
            prof["aspirations"] = aspirations
            char["profile"] = prof
            return asp
    new = {
        "id": "asp-" + uuid.uuid4().hex[:8],
        "text": text,
        "surfaced_count": 1,
        "first_at": time.time(),
        "last_at": time.time(),
        "needs_goal_prompt": False,
    }
    aspirations.append(new)
    prof["aspirations"] = aspirations
    char["profile"] = prof
    return new


def last_run_time(char_id: str) -> float | None:
    """Timestamp of the most recent think OR sleep event (sleep events also count toward the interval)."""
    r = db.one(
        "SELECT created_at FROM char_life_events WHERE char_id=? AND event_type IN ('think','sleep') ORDER BY created_at DESC LIMIT 1",
        (char_id,),
    )
    return r["created_at"] if r else None
