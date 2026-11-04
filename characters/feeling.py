"""Feelings engine for Virtual Life.

A feeling is a persistent background emotional state that sits beneath the
in-the-moment mood. It updates after every think cycle via the brain's
feeling_update field, and is injected into every Stage-1 context.

Age shapes the probability distribution: a 23-year-old drifts toward
restless/ambitious/flirtatious far more than a 45-year-old.
"""
import random
import time

# ── vocabulary ────────────────────────────────────────────────────────────────

# Groups: calm, positive, charged, social, negative, complex, adult, physical
FEELINGS = {
    "calm": [
        "peaceful", "content", "grateful", "settled", "cosy", "satisfied",
        "serene", "still", "comfortable", "centred",
    ],
    "positive": [
        "excited", "hopeful", "proud", "inspired", "playful", "flirtatious",
        "amorous", "euphoric", "grateful", "radiant", "giddy", "elated",
    ],
    "charged": [
        "ambitious", "determined", "energised", "focused", "driven", "motivated",
        "purposeful", "competitive",
    ],
    "social": [
        "warm", "affectionate", "tender", "connected", "lonely", "left-out",
        "jealous", "competitive", "seen", "invisible", "needy",
    ],
    "negative": [
        "anxious", "irritable", "bored", "frustrated", "disappointed",
        "guilty", "embarrassed", "overwhelmed", "deflated", "insecure",
        "resentful", "drained",
    ],
    "complex": [
        "nostalgic", "conflicted", "restless", "melancholy", "wistful",
        "curious", "unsettled", "numb", "pensive", "bittersweet",
        "yearning", "detached",
    ],
    "adult": [
        "desirous", "longing", "aroused", "craving", "infatuated",
        "possessive", "hungry", "tempted", "charged",
    ],
    "physical": [
        "tired-but-happy", "drained-and-blank", "wound-up", "buzzing",
        "restless-energy", "heavy", "light",
    ],
}

# flat list for validation
ALL_FEELINGS = {f for grp in FEELINGS.values() for f in grp}

# ── age weights ───────────────────────────────────────────────────────────────
# Maps (age_lo, age_hi) → {group: weight}. Higher weight = more probable.
# Default weight for unlisted groups is 1.0.

_AGE_WEIGHTS = [
    ((16, 22), {"positive": 2.5, "social": 2.0, "adult": 1.5, "charged": 1.5, "negative": 1.5, "calm": 0.5}),
    ((22, 27), {"charged": 2.5, "complex": 2.0, "adult": 2.0, "social": 1.8, "positive": 1.5, "calm": 0.6}),
    ((27, 33), {"charged": 2.0, "complex": 1.8, "calm": 1.2, "adult": 1.5, "social": 1.5, "positive": 1.5}),
    ((33, 42), {"calm": 1.8, "complex": 1.5, "positive": 1.2, "adult": 1.2, "social": 1.0, "charged": 1.0}),
    ((42, 55), {"calm": 2.0, "complex": 2.0, "positive": 1.0, "adult": 0.8, "social": 1.2, "charged": 0.8}),
    ((55, 100), {"calm": 2.5, "complex": 1.5, "positive": 1.5, "adult": 0.4, "social": 1.0, "charged": 0.6}),
]


def _weights_for_age(age: int) -> dict[str, float]:
    for (lo, hi), weights in _AGE_WEIGHTS:
        if lo <= age < hi:
            return weights
    return {}   # default: all groups equal weight 1.0


def _pick_feeling(age: int) -> str:
    """Pick a random feeling weighted by age group."""
    weights = _weights_for_age(age)
    pool: list[tuple[str, float]] = []
    for group, feelings in FEELINGS.items():
        w = weights.get(group, 1.0)
        for f in feelings:
            pool.append((f, w))
    names = [f for f, _ in pool]
    wts = [w for _, w in pool]
    return random.choices(names, weights=wts, k=1)[0]


# ── public API ────────────────────────────────────────────────────────────────

def default_feeling(age: int = 25) -> dict:
    """Initial feeling for a new character."""
    return {
        "primary": _pick_feeling(age),
        "intensity": random.randint(4, 7),
        "secondary": _pick_feeling(age),
        "since_ts": time.time(),
    }


def validate(f: dict | None) -> bool:
    """True if the feeling dict is structurally valid."""
    if not isinstance(f, dict):
        return False
    primary = f.get("primary", "")
    return bool(primary and primary in ALL_FEELINGS)


def apply_update(current: dict, update: dict, age: int = 25) -> dict:
    """Merge a feeling_update from the brain into the current feeling.

    If the update is invalid or empty, drift the existing feeling slightly.
    'Drift' = 20% chance of a small intensity shift; rare feeling change.
    """
    if update and validate(update):
        new = dict(current)
        new["primary"] = update.get("primary", current.get("primary", _pick_feeling(age)))
        new["intensity"] = max(1, min(10, int(update.get("intensity", current.get("intensity", 5)))))
        sec = update.get("secondary", "")
        if sec and sec in ALL_FEELINGS:
            new["secondary"] = sec
        new["since_ts"] = time.time()
        return new

    # natural drift when no update or update is garbage
    new = dict(current)
    if random.random() < 0.2:
        # small intensity drift
        new["intensity"] = max(1, min(10, new.get("intensity", 5) + random.choice([-1, 0, 1])))
    if random.random() < 0.08:
        # rare feeling change — shift within same group or adjacent
        new["primary"] = _pick_feeling(age)
        new["since_ts"] = time.time()
    return new


def format_for_prompt(feeling: dict | None) -> str:
    """Short line injected into brain Stage-1 context."""
    if not feeling or not feeling.get("primary"):
        return ""
    primary = feeling["primary"]
    intensity = feeling.get("intensity", 5)
    secondary = feeling.get("secondary", "")
    s = f"Current feeling: {primary} ({intensity}/10)"
    if secondary and secondary != primary:
        s += f", with an undercurrent of {secondary}"
    s += "."
    return s
