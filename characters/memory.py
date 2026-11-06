"""Episodic memory for a virtual character. Memories form automatically after each think
cycle and decay with age. Half-life = 7 days. Faded memories (strength < 0.04, ~40 days)
are not retrieved but kept in the DB for history."""
import hashlib
import itertools
import math
import re
import time
import uuid

from story import db

HALF_LIFE_DAYS = 7.0
FADE_THRESHOLD = 0.04   # strength below this → not retrieved (≈40 days at default decay)
MAX_RETRIEVE   = 7      # how many memories the brain gets per think (7 = episodic×3 + reflection×2 + achievement×1 + discovery×1)

# Phase M — experience taxonomy
CATEGORIES = {
    "episodic":     "Recent activity",
    "observation":  "Observations",
    "learning":     "Learnings",
    "achievement":  "Achievements",
    "discovery":    "Discoveries",
    "reflection":   "Reflections",
    "desire":       "Desires",
    "wish":         "Fashion & wardrobe wishes",
    "note":         "Notes & reminders",
    "manual":       "Notes & reminders",
}

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

def form(char_id: str, thought: dict, category: str = "episodic", source: str = "think") -> dict:
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
        "INSERT INTO char_memories(id,char_id,content,tags,category,base_strength,formed_at,last_accessed_at,source)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (mid, char_id, content, db.jdump(tags), category, 1.0, now, now, source),
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

    if top:
        ids = ",".join("?" * len(top))
        db.ex(f"UPDATE char_memories SET last_accessed_at=? WHERE id IN ({ids})",
              (now, *[m["id"] for m in top]))
        log_corecalls(char_id, [m["id"] for m in top])
    return top


def retrieve_by_categories(char_id: str, spec: dict[str, int], context: str = "") -> list[dict]:
    """Pull memories per category with per-category caps.

    spec example: {"episodic": 3, "reflection": 2, "achievement": 1, "discovery": 1}
    Returns combined list, deduped by id, in descending strength order.
    """
    rows = db.q("SELECT * FROM char_memories WHERE char_id=? ORDER BY formed_at DESC", (char_id,))
    now = time.time()

    by_cat: dict[str, list] = {cat: [] for cat in spec}
    for r in rows:
        m = _load(r)
        cat = m.get("category", "episodic")
        if cat not in spec:
            continue
        s = strength(m, now)
        if s < FADE_THRESHOLD:
            continue
        relevance = 1.0 + 0.6 * _keyword_overlap(m["content"], context)
        by_cat[cat].append((s * relevance, m))

    result = []
    seen = set()
    for cat, limit in spec.items():
        bucket = sorted(by_cat.get(cat, []), key=lambda x: x[0], reverse=True)
        for _, m in bucket[:limit]:
            if m["id"] not in seen:
                seen.add(m["id"])
                result.append(m)

    if result:
        ids = ",".join("?" * len(result))
        db.ex(f"UPDATE char_memories SET last_accessed_at=? WHERE id IN ({ids})",
              (now, *[m["id"] for m in result]))
        log_corecalls(char_id, [m["id"] for m in result])
    return result


def memories_prompt(mems: list[dict], at: float | None = None) -> str:
    """Short block for the brain's user prompt — grouped by category, oldest first within group."""
    if not mems:
        return ""
    now = at or time.time()

    def _fmt(m: dict) -> str:
        days = (now - m["formed_at"]) / 86400
        age  = "today" if days < 1 else (f"{int(days)}d ago" if days < 30 else f"{int(days/30)}mo ago")
        s    = strength(m, now)
        bar  = "█" * round(s * 5) + "░" * (5 - round(s * 5))
        return f"[{bar} {age}] {m['content']}"

    # group by category using CATEGORIES order; unknown → episodic bucket
    buckets: dict[str, list] = {cat: [] for cat in CATEGORIES}
    for m in sorted(mems, key=lambda x: x["formed_at"]):
        cat = m.get("category", "episodic")
        bucket = cat if cat in buckets else "episodic"
        buckets[bucket].append(m)

    parts = []
    for cat, label in CATEGORIES.items():
        if buckets[cat]:
            parts.append(label + ":\n" + "\n".join(_fmt(m) for m in buckets[cat]))
    return "\n\n".join(parts)


# ── list / delete (for UI) ────────────────────────────────────────────────────

def list_memories(char_id: str, limit: int = 40, category: str | None = None) -> list[dict]:
    if category:
        rows = db.q(
            "SELECT * FROM char_memories WHERE char_id=? AND category=? ORDER BY formed_at DESC LIMIT ?",
            (char_id, category, limit),
        )
    else:
        rows = db.q(
            "SELECT * FROM char_memories WHERE char_id=? ORDER BY formed_at DESC LIMIT ?",
            (char_id, limit),
        )
    now = time.time()
    return [{**_load(r), "current_strength": round(strength(_load(r), now), 3)} for r in rows]


def delete_memory(char_id: str, memory_id: str) -> None:
    db.ex("DELETE FROM char_memories WHERE id=? AND char_id=?", (memory_id, char_id))


def expire_wishes(char_id: str, garment_description: str) -> int:
    """Soft-expire wish memories whose content overlaps a newly added garment.

    Scores overlap by shared significant words (3+ chars). Any wish with
    score >= 2 matching words gets base_strength set to 0 (faded, not deleted).
    Returns count of expired wishes.
    """
    stop = {"a", "an", "the", "in", "for", "of", "with", "and", "or", "to", "my"}
    keywords = {w for w in garment_description.lower().split() if len(w) >= 3 and w not in stop}
    if not keywords:
        return 0
    rows = db.q("SELECT id, content FROM char_memories WHERE char_id=? AND category='wish'",
                  (char_id,))
    expired = 0
    for row in rows:
        content_words = {w for w in row["content"].lower().split() if len(w) >= 3 and w not in stop}
        if len(keywords & content_words) >= 2:
            db.ex("UPDATE char_memories SET base_strength=0 WHERE id=?", (row["id"],))
            expired += 1
    return expired


# ── memory bonds ─────────────────────────────────────────────────────────────

_BOND_CORECALL_BUMP  = 0.05   # strength gained per co-recall event
_BOND_DECAY_PER_DAY  = 0.01   # strength lost per idle day (much slower than memory decay)
_BOND_SEED_STRENGTH  = 0.10   # starting strength for tag-overlap seeds
_BOND_TAG_MIN        = 2      # minimum shared tags to seed a bond


def _bond_id(a: str, b: str) -> str:
    """Stable id regardless of argument order."""
    return "bnd-" + hashlib.sha1(("".join(sorted([a, b]))).encode()).hexdigest()[:10]


def log_corecalls(char_id: str, mem_ids: list[str]) -> None:
    """Record that these memory ids were retrieved together. Upserts bonds for every pair."""
    if len(mem_ids) < 2:
        return
    now = time.time()
    for a, b in itertools.combinations(sorted(mem_ids), 2):
        bid = _bond_id(a, b)
        existing = db.one("SELECT * FROM char_memory_bonds WHERE id=?", (bid,))
        if existing:
            new_str = min(1.0, existing["bond_strength"] + _BOND_CORECALL_BUMP)
            db.ex(
                "UPDATE char_memory_bonds SET co_recalls=co_recalls+1, bond_strength=?, last_corecall_at=? WHERE id=?",
                (new_str, now, bid),
            )
        else:
            db.ex(
                "INSERT INTO char_memory_bonds(id,char_id,mem_a,mem_b,co_recalls,bond_strength,last_corecall_at,formed_at)"
                " VALUES(?,?,?,?,1,?,?,?)",
                (bid, char_id, a, b, _BOND_SEED_STRENGTH, now, now),
            )


def seed_bonds(char_id: str) -> int:
    """One-time retroactive pass: seed weak bonds between memories that share ≥2 tags.
    Idempotent — skips pairs that already have a bond. Returns count of bonds seeded.
    """
    rows = db.q("SELECT id, tags FROM char_memories WHERE char_id=?", (char_id,))
    mems = [(r["id"], set(db.jload(r["tags"], []))) for r in rows if r["tags"]]
    now  = time.time()
    seeded = 0
    for (a_id, a_tags), (b_id, b_tags) in itertools.combinations(mems, 2):
        if len(a_tags & b_tags) < _BOND_TAG_MIN:
            continue
        bid = _bond_id(a_id, b_id)
        if db.one("SELECT id FROM char_memory_bonds WHERE id=?", (bid,)):
            continue
        db.ex(
            "INSERT INTO char_memory_bonds(id,char_id,mem_a,mem_b,co_recalls,bond_strength,last_corecall_at,formed_at)"
            " VALUES(?,?,?,?,0,?,?,?)",
            (bid, char_id, a_id, b_id, _BOND_SEED_STRENGTH, now, now),
        )
        seeded += 1
    return seeded


def decay_bonds(char_id: str) -> None:
    """Passive bond decay — called during sleep/consolidation, not every think cycle."""
    rows = db.q(
        "SELECT id, bond_strength, last_corecall_at FROM char_memory_bonds WHERE char_id=?",
        (char_id,),
    )
    now = time.time()
    for r in rows:
        days = (now - r["last_corecall_at"]) / 86400
        new_str = max(0.0, r["bond_strength"] - days * _BOND_DECAY_PER_DAY)
        if new_str == 0:
            db.ex("DELETE FROM char_memory_bonds WHERE id=?", (r["id"],))
        elif new_str != r["bond_strength"]:
            db.ex("UPDATE char_memory_bonds SET bond_strength=? WHERE id=?", (new_str, r["id"]))


def list_bonds(char_id: str, min_strength: float = 0.0) -> list[dict]:
    """Return all bonds for a character above a minimum strength threshold."""
    return db.q(
        "SELECT * FROM char_memory_bonds WHERE char_id=? AND bond_strength>=? ORDER BY bond_strength DESC",
        (char_id, min_strength),
    )


# ── sleep consolidation ───────────────────────────────────────────────────────

_CONSOLIDATE_MIN_MEMBERS  = 3     # cluster needs at least this many memories
_CONSOLIDATE_MIN_STRENGTH = 0.3   # every memory in the cluster must be at least this strong
_CONSOLIDATE_MIN_BOND_AVG = 0.2   # average bond_strength across cluster edges must meet this
_CONSOLIDATE_BOND_FLOOR   = 0.15  # ignore bonds weaker than this when building the graph
_CONSOLIDATE_MAX_CLUSTERS = 5     # max LLM calls per sleep event


def _find_clusters(char_id: str) -> list[list[dict]]:
    """Return qualifying memory clusters from the bond graph (BFS connected components)."""
    bonds = db.q(
        "SELECT mem_a, mem_b, bond_strength FROM char_memory_bonds WHERE char_id=? AND bond_strength>=?",
        (char_id, _CONSOLIDATE_BOND_FLOOR),
    )
    # adjacency list
    adj: dict[str, set] = {}
    bond_map: dict[tuple, float] = {}
    for b in bonds:
        adj.setdefault(b["mem_a"], set()).add(b["mem_b"])
        adj.setdefault(b["mem_b"], set()).add(b["mem_a"])
        key = tuple(sorted([b["mem_a"], b["mem_b"]]))
        bond_map[key] = b["bond_strength"]

    if not adj:
        return []

    # BFS to find connected components
    seen: set = set()
    components: list[list[str]] = []
    for start in adj:
        if start in seen:
            continue
        component, queue = [], [start]
        while queue:
            node = queue.pop()
            if node in seen:
                continue
            seen.add(node)
            component.append(node)
            queue.extend(adj.get(node, set()) - seen)
        if len(component) >= _CONSOLIDATE_MIN_MEMBERS:
            components.append(component)

    now = time.time()
    qualifying = []
    for comp in components:
        # fetch memory rows
        placeholders = ",".join("?" * len(comp))
        rows = db.q(f"SELECT * FROM char_memories WHERE id IN ({placeholders})", comp)
        mems = [_load(r) for r in rows if r]

        # filter: all memories above minimum strength
        if not all(strength(m, now) >= _CONSOLIDATE_MIN_STRENGTH for m in mems):
            continue

        # filter: average bond strength across all edges in cluster
        edges = [bond_map[tuple(sorted([a, b]))]
                 for a, b in itertools.combinations(comp, 2)
                 if tuple(sorted([a, b])) in bond_map]
        if not edges or (sum(edges) / len(edges)) < _CONSOLIDATE_MIN_BOND_AVG:
            continue

        qualifying.append(mems)

    return qualifying[:_CONSOLIDATE_MAX_CLUSTERS]


async def consolidate(char_id: str, backend) -> dict:
    """Sleep-time consolidation. Finds memory clusters, synthesises trait sentences,
    promotes stable traits. Returns a summary dict."""
    from characters import store as char_store

    decay_bonds(char_id)
    clusters = _find_clusters(char_id)
    if not clusters:
        return {"clusters_found": 0, "traits_formed": 0, "stable_promoted": 0}

    now      = time.time()
    formed   = 0
    promoted = 0

    for mems in clusters:
        # check if this cluster already contains a trait memory (second consolidation)
        existing_trait = next((m for m in mems if m.get("category") == "trait"), None)

        contents = "\n".join(f"- {m['content']}" for m in mems if m.get("category") != "trait")
        if not contents.strip():
            continue

        # one cheap LLM call — plain text, no JSON mode needed
        try:
            result = await backend.complete(
                messages=[
                    {"role": "system",
                     "content": "You find the single common thread running through a person's memories and express it as one plain sentence about who they are or what shapes them. No preamble, no quotation marks, no explanation."},
                    {"role": "user",
                     "content": f"These memories belong to the same person:\n{contents}\n\nWhat one-sentence pattern or trait emerges?"},
                ],
                max_tokens=80,
            )
            trait_text = result.content.strip().strip('"').strip("'")
        except Exception:
            continue  # failed synthesis — skip this cluster, never block sleep

        if not trait_text:
            continue

        if existing_trait:
            # second consolidation → mark it stable
            db.ex("UPDATE char_memories SET stable=1 WHERE id=?", (existing_trait["id"],))
            promoted += 1
        else:
            # first consolidation → create new trait memory
            all_tags = list({t for m in mems for t in (m.get("tags") or [])})[:12]
            mid = _mid()
            db.ex(
                "INSERT INTO char_memories(id,char_id,content,tags,category,base_strength,formed_at,last_accessed_at,source,stable)"
                " VALUES(?,?,?,?,?,?,?,?,?,0)",
                (mid, char_id, trait_text, db.jdump(all_tags), "trait", 1.5, now, now, "consolidation"),
            )
            formed += 1

    return {"clusters_found": len(clusters), "traits_formed": formed, "stable_promoted": promoted}


def active_traits(char_id: str) -> list[dict]:
    """Return trait memories above fade threshold, stable ones first."""
    rows = db.q(
        "SELECT * FROM char_memories WHERE char_id=? AND category='trait' ORDER BY stable DESC, base_strength DESC",
        (char_id,),
    )
    now = time.time()
    return [
        {**_load(r), "current_strength": round(strength(_load(r), now), 3)}
        for r in rows
        if strength(_load(r), now) >= FADE_THRESHOLD
    ]


def add_manual(char_id: str, content: str, tags: list[str] | None = None,
               category: str = "manual", dedup: bool = False) -> dict:
    """Let the owner inject a memory manually. dedup=True skips if identical content already exists."""
    if dedup:
        existing = db.one("SELECT id FROM char_memories WHERE char_id=? AND content=?",
                          (char_id, content.strip()))
        if existing:
            return _load(db.one("SELECT * FROM char_memories WHERE id=?", (existing["id"],)))
    mid = _mid()
    now = time.time()
    db.ex(
        "INSERT INTO char_memories(id,char_id,content,tags,category,base_strength,formed_at,last_accessed_at)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (mid, char_id, content.strip(), db.jdump(tags or []), category, 1.0, now, now),
    )
    return _load(db.one("SELECT * FROM char_memories WHERE id=?", (mid,)))
