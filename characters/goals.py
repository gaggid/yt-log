"""Character goals: things she is working toward. Stored in profile['goals'].
The brain's prompt includes an active-goals summary so thoughts drift toward them."""
import hashlib
import time

CATEGORIES = ("career", "personal", "creative", "health", "social", "learning", "financial")
STATUSES   = ("active", "paused", "achieved")


def _gid() -> str:
    return "g-" + hashlib.sha1(str(time.time()).encode()).hexdigest()[:6]


def list_goals(char: dict) -> list[dict]:
    from . import profile as profile_mod
    return (profile_mod.get(char).get("goals") or [])


def add_goal(char: dict, title: str, category: str, description: str = "") -> dict:
    from . import profile as profile_mod, store
    if category not in CATEGORIES:
        raise ValueError(f"category is one of: {', '.join(CATEGORIES)}")
    goal = {"id": _gid(), "title": title.strip(), "category": category,
            "description": description.strip(), "status": "active",
            "created_at": time.time(), "progress_notes": []}
    prof = profile_mod.get(char)
    goals = list(prof.get("goals") or [])
    goals.append(goal)
    profile_mod.patch(char, {"goals": goals})
    store.save(char)
    return goal


def update_goal(char: dict, goal_id: str, **updates) -> dict:
    from . import profile as profile_mod, store
    prof = profile_mod.get(char)
    goals = list(prof.get("goals") or [])
    for g in goals:
        if g["id"] == goal_id:
            for k, v in updates.items():
                if k == "progress_notes" and isinstance(v, str) and v.strip():
                    g["progress_notes"] = g.get("progress_notes", []) + [v.strip()]
                elif k in ("title", "description", "status", "category"):
                    g[k] = v
            profile_mod.patch(char, {"goals": goals})
            store.save(char)
            return g
    raise ValueError(f"no goal {goal_id}")


def delete_goal(char: dict, goal_id: str) -> None:
    from . import profile as profile_mod, store
    prof = profile_mod.get(char)
    goals = [g for g in (prof.get("goals") or []) if g["id"] != goal_id]
    profile_mod.patch(char, {"goals": goals})
    store.save(char)


def active_summary(char: dict) -> str:
    """2-3 sentence block for the brain's system prompt."""
    active = [g for g in list_goals(char) if g.get("status") == "active"]
    if not active:
        return ""
    lines = []
    for g in active[:4]:
        note = g["progress_notes"][-1] if g.get("progress_notes") else ""
        line = f"- {g['title']} ({g['category']}): {g['description']}"
        if note:
            line += f" [latest: {note}]"
        lines.append(line)
    return "Active goals:\n" + "\n".join(lines)


def neglected_goals(char: dict, recent_thoughts: list[dict]) -> list[dict]:
    """Goals not mentioned in the last 3 thoughts — the brain gets nudged about these."""
    active = [g for g in list_goals(char) if g.get("status") == "active"]
    recent_text = " ".join(
        (t.get("outputs", {}).get("thought", "") + " " + t.get("outputs", {}).get("activity", "")).lower()
        for t in recent_thoughts[:3]
    )
    return [g for g in active if g["title"].lower().split()[0] not in recent_text]


def try_log_progress(char: dict, goal_progress: str, save: bool = True) -> bool:
    """If goal_progress from ThoughtOut matches an active goal title, append a note."""
    if not goal_progress.strip():
        return False
    from . import profile as profile_mod, store
    prof = profile_mod.get(char)
    goals = list(prof.get("goals") or [])
    gp_lower = goal_progress.lower()
    matched = False
    for g in goals:
        if g.get("status") == "active" and g["title"].lower().split()[0] in gp_lower:
            g["progress_notes"] = g.get("progress_notes", []) + [goal_progress.strip()]
            matched = True
    if matched:
        profile_mod.patch(char, {"goals": goals})
        if save:
            store.save(char)
    return matched
