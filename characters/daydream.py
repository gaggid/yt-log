"""Daydream sessions: when a character has a recurring experience aspiration
(travel, food, event) she imagines it in idle/relaxed moments — forming a
vivid wish memory without converting it to a goal.

Achievement-type aspirations (learn, build, become) are left for the goal-
nudge flow instead. Classification is keyword-based, no extra LLM call.
"""
import time

DAYDREAM_COOLDOWN = 86400   # once per aspiration per day
MIN_SURFS        = 2        # aspiration must have surfaced this many times
DREAMY_MOODS     = {
    "relaxed", "peaceful", "nostalgic", "bored", "dreamy",
    "content", "happy", "calm", "wistful", "pensive", "longing",
}

_EXPERIENCE_WORDS = {
    "visit", "go", "travel", "trip", "eat", "taste", "see", "watch", "attend",
    "hike", "climb", "drive", "fly", "swim", "dance", "experience", "feel",
    "explore", "tour", "try", "meet", "walk", "run", "ride", "trek", "discover",
    "celebrate", "enjoy", "savor",
}
_ACHIEVEMENT_WORDS = {
    "learn", "improve", "get", "build", "create", "write", "read", "practice",
    "become", "start", "finish", "complete", "achieve", "earn", "master",
    "study", "train", "develop", "grow", "launch", "publish", "make",
}


def classify(text: str) -> str:
    """Return 'experience' or 'achievement' based on keyword overlap."""
    words = set(text.lower().split())
    exp   = len(words & _EXPERIENCE_WORDS)
    ach   = len(words & _ACHIEVEMENT_WORDS)
    return "achievement" if ach > exp else "experience"


def _pick_aspiration(prof: dict) -> dict | None:
    """Return the best experience aspiration to daydream about, or None."""
    now        = time.time()
    candidates = []
    for asp in (prof.get("aspirations") or []):
        if asp.get("surfaced_count", 0) < MIN_SURFS:
            continue
        if classify(asp.get("text", "")) != "experience":
            continue
        if now - asp.get("last_daydream_at", 0) < DAYDREAM_COOLDOWN:
            continue
        candidates.append(asp)
    if not candidates:
        return None
    # most-surfaced first
    return sorted(candidates, key=lambda a: -a.get("surfaced_count", 0))[0]


def should_daydream(prof: dict) -> bool:
    """True when mood and aspiration conditions are met."""
    energy = int(prof.get("energy", 50) or 50)
    if energy < 20:
        return False
    mood = (prof.get("mood_now") or {}).get("feeling", "").lower()
    if mood and not any(m in mood for m in DREAMY_MOODS):
        return False
    return _pick_aspiration(prof) is not None


async def daydream_session(char: dict, backend) -> dict | None:
    """Generate a vivid daydream memory for the best ready experience aspiration.
    Returns summary dict or None if nothing to daydream about / LLM fails.
    """
    from . import memory as memory_mod, profile as profile_mod, store

    prof = profile_mod.get(char)
    asp  = _pick_aspiration(prof)
    if not asp:
        return None

    text  = asp.get("text", "")
    mood  = (prof.get("mood_now") or {}).get("feeling", "relaxed")
    space = prof.get("current_space") or "home"

    prompt = (
        f"The character is feeling {mood}. Her mind drifts to something she has been longing for: '{text}'.\n"
        f"Write 2-3 sentences in first person as a vivid imagination — sensory details, feelings, "
        f"what she sees or tastes or feels. Present tense, personal, specific. "
        f"No second person. No meta-commentary. Return only the daydream text."
    )
    try:
        result = await backend.complete(
            messages=[
                {"role": "system",
                 "content": "You write short vivid first-person daydreams for a virtual character. Sensory, emotional, specific."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=130,
        )
        daydream_text = (result.content or "").strip()
    except Exception:
        return None

    if not daydream_text:
        return None

    # Form a wish-category memory
    memory_mod.form(
        char["id"],
        {
            "activity": f"Daydreaming about {text}",
            "space":    space,
            "mood":     mood,
            "thought":  daydream_text,
        },
        category="wish",
        source="daydream",
    )

    # Update aspiration timestamps on the fresh char
    fresh = store.get(char["id"])
    prof2 = profile_mod.get(fresh)
    aspirations = list(prof2.get("aspirations") or [])
    for a in aspirations:
        if a.get("id") == asp.get("id"):
            a["last_daydream_at"] = time.time()
            a["daydream_count"]   = int(a.get("daydream_count", 0)) + 1
            break
    profile_mod.patch(fresh, {"aspirations": aspirations})
    store.save(fresh)

    return {"aspiration": text, "daydream": daydream_text}
