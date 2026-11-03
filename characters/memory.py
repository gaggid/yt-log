"""Episodic memory for a virtual character. Memories form automatically after each think
cycle and decay with age. Half-life = 7 days. Faded memories (strength < 0.04, ~40 days)
are not retrieved but kept in the DB for history."""
import hashlib
import math
import re
import time

from story import db

HALF_LIFE_DAYS = 7.0
FADE_THRESHOLD = 0.04   # strength below this → not retrieved (≈40 days at default decay)
MAX_RETRIEVE   = 6      # how many memories the brain gets per think

_STOP = {"the", "and", "for", "she", "her", "was", "are", "with", "that", "this",
         "have", "from", "just", "been", "like", "what", "when", "felt", "then"}


def _mid() -> str:
    return "mem-" + hashlib.sha1(str(time.time()).encode()).hexdigest()[:8]


# ── strength / decay ──────────────────────────────────────────────────────────

def strength(mem: dict, at: float | None = None) -> float:
    """Current strength of a memory (0.0–1.0), decaying with a 7-day half-life."""
    days = ((at or time.time()) - mem["formed_at"]) / 86400
    return mem["base_strength"] * (0.5 ** (days / HALF_LIFE_DAYS))


# ── tag extraction ────────────────────────────────────────────────────────────

def _extract_tags(thought: dict) -> list[str]:
    text = " ".join([
        thought.get("activity", ""),
        thought.get("space", ""),
        thought.get("mood", ""),
        thought.get("thought", ""),
    ])
    words = [w.lower() for w in re.findall(r"[a-zA-Z]+", text) if len(w) > 3]
    seen, tags = set(), []
    for w in words:
        if w not in _STOP and w not in seen:
            seen.add(w)
            tags.append(w)
        if len(tags) >= 12:
            break
    return tags


# ── form ──────────────────────────────────────────────────────────────────────

def form(char_id: str, thought: dict, category: str = "episodic") -> dict:
    """Create and persist one memory from a ThoughtOut dict. Returns the memory row."""
    activity = thought.get("activity", "").strip()
    space    = thought.get("space", "").strip()
    mood     = thought.get("mood", "").strip()
    thought_text = thought.get("thought", "").strip()

    content = f"{activity} at {space}.{(' Mood: ' + mood + '.') if mood else ''} {thought_text}".strip()
    tags    = _extract_tags(thought)
    mid     = _mid()
    now     = time.time()

    db.ex(
        "INSERT INTO char_memories(id,char_id,content,tags,category,base_strength,formed_at,last_accessed_at)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (mid, char_id, content, db.jdump(tags), category, 1.0, now, now),
    )
    return _load(db.one("SELECT * FROM char_memories WHERE id=?", (mid,)))


# ── retrieve ──────────────────────────────────────────────────────────────────

def _load(r: dict) -> dict:
    if r is None:
        return {}
    return {**r, "tags": db.jload(r["tags"], [])}


def _keyword_overlap(content: str, context: str) -> float:
    """Fraction of context keywords present in content (0–1)."""
    cwords = {w.lower() for w in re.findall(r"[a-zA-Z]+", context) if len(w) > 3 and w.lower() not in _STOP}
    if not cwords:
        return 0.0
    mwords = {w.lower() for w in re.findall(r"[a-zA-Z]+", content)}
    return len(cwords & mwords) / len(cwords)


def retrieve(char_id: str, context: str = "", n: int = MAX_RETRIEVE) -> list[dict]:
    """Top n memories by (strength × relevance). Skips faded memories."""
    rows = db.q("SELECT * FROM char_memories WHERE char_id=? ORDER BY formed_at DESC", (char_id,))
    now = time.time()
    scored = []
    for r in rows:
        m = _load(r)
        s = strength(m, now)
        if s < FADE_THRESHOLD:
            continue
        relevance = 1.0 + 0.6 * _keyword_overlap(m["content"], context)
        scored.append((s * relevance, m))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = [m for _, m in scored[:n]]

    # mark accessed
    if top:
        ids = ",".join("?" * len(top))
        db.ex(f"UPDATE char_memories SET last_accessed_at=? WHERE id IN ({ids})",
              (now, *[m["id"] for m in top]))
    return top


def memories_prompt(mems: list[dict], at: float | None = None) -> str:
    """Short block for the brain's user prompt — oldest first so timeline reads naturally."""
    if not mems:
        return ""
    now = at or time.time()
    # sort oldest→newest so reading order is chronological
    ordered = sorted(mems, key=lambda m: m["formed_at"])
    lines = []
    for m in ordered:
        days = (now - m["formed_at"]) / 86400
        age = "today" if days < 1 else (f"{int(days)}d ago" if days < 30 else f"{int(days/30)}mo ago")
        s = strength(m, now)
        bar = "█" * round(s * 5) + "░" * (5 - round(s * 5))   # e.g. "███░░"
        lines.append(f"[{bar} {age}] {m['content']}")
    return "Your memories (freshest feel strongest):\n" + "\n".join(lines)


# ── list / delete (for UI) ────────────────────────────────────────────────────

def list_memories(char_id: str, limit: int = 40) -> list[dict]:
    rows = db.q(
        "SELECT * FROM char_memories WHERE char_id=? ORDER BY formed_at DESC LIMIT ?",
        (char_id, limit),
    )
    now = time.time()
    return [{**_load(r), "current_strength": round(strength(_load(r), now), 3)} for r in rows]


def delete_memory(char_id: str, memory_id: str) -> None:
    db.ex("DELETE FROM char_memories WHERE id=? AND char_id=?", (memory_id, char_id))


def add_manual(char_id: str, content: str, tags: list[str] | None = None) -> dict:
    """Let the owner inject a memory manually."""
    mid = _mid()
    now = time.time()
    db.ex(
        "INSERT INTO char_memories(id,char_id,content,tags,category,base_strength,formed_at,last_accessed_at)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (mid, char_id, content.strip(), db.jdump(tags or []), "manual", 1.0, now, now),
    )
    return _load(db.one("SELECT * FROM char_memories WHERE id=?", (mid,)))
