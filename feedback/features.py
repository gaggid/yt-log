"""The features of an idea and its video that the feedback loop compares: hook shape, subject territory, mechanisms, look, tone, length, upload time. Pure code, no model."""
import re
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

TERRITORIES = [
    "history", "science", "mind_behaviour", "money_economics", "war_geopolitics", "technology_engineering", "nature_animals",
    "space", "india_culture", "health_body", "mystery_unexplained", "society_crime", "food_everyday",
]
TERRITORY_HELP = {
    "history": "past events, civilisations, forgotten stories", "science": "physics, chemistry, how things work", "mind_behaviour": "psychology, habits, decisions, the brain",
    "money_economics": "money, markets, business, prices", "war_geopolitics": "wars, armies, borders, power", "technology_engineering": "machines, buildings, software, infrastructure",
    "nature_animals": "animals, plants, earth, weather", "space": "space, planets, the universe", "india_culture": "Indian places, traditions, festivals, people",
    "health_body": "the body, medicine, sleep, food and health", "mystery_unexplained": "unsolved cases, odd places, strange events", "society_crime": "crime, law, society, scams", "food_everyday": "everyday objects, food, habits, home",
}


def territory_of(value: str) -> str:
    v = re.sub(r"[^a-z_]", "", (value or "").strip().lower().replace(" ", "_").replace("&", "_"))
    return v if v in TERRITORIES else ""


def hook_type(text: str) -> str:
    t = (text or "").strip()
    low = t.lower()
    if re.search(r"\bwhat if\b|\bimagine\b", low):
        return "what_if"
    if t.endswith("?") or re.match(r"(why|how|what|who|when|where|is|are|can|could|do|does|did|will|would)\b", low):
        return "question"
    return "shock"


def has_number(text: str) -> str:
    return "number" if re.search(r"\d", text or "") else "no number"


def words(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


def hook_len_band(text: str) -> str:
    n = words(text)
    return "up to 8 words" if n <= 8 else "9 to 12 words" if n <= 12 else "13 or more words"


def length_band(target_s) -> str:
    n = float(target_s or 0)
    return "up to 20 s" if n <= 20 else "21 to 35 s" if n <= 35 else "over 35 s"


def score_band(score) -> str:
    s = score or 0
    return "no score" if not s else "9 and up" if s >= 9 else "8 to 9" if s >= 8 else "7 to 8" if s >= 7 else "under 7"


def ist(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, timezone.utc).astimezone(IST)


def hour_band(ts: float) -> str:
    h = ist(ts).hour
    return "night (0-5)" if h < 6 else "morning (6-11)" if h < 12 else "afternoon (12-17)" if h < 18 else "evening (18-21)" if h < 22 else "late (22-23)"


def weekday(ts: float) -> str:
    return ist(ts).strftime("%A")


def mech_pair(mechanisms: list) -> str:
    m = [x for x in (mechanisms or []) if x]
    return " + ".join(sorted(m[:2])) if len(m) >= 2 else (m[0] if m else "")


def title_features(title: str) -> dict:
    """What a title alone tells (used for channel videos the app did not make)."""
    return {"hook_type": hook_type(title), "has_number": has_number(title), "hook_len": hook_len_band(title)}


def freeze(idea: dict, short: dict, choices: dict | None = None) -> dict:
    """The features of an idea as it was made (kept in `idea_outcomes`, so later edits do not blur the picture)."""
    st = (short or {}).get("settings", {}) or {}
    sb = idea.get("score_breakdown") or {}
    choices = dict(choices or {})
    pb = int(choices.pop("playbook", 0) or 0)                                  # the Playbook version in use when the short was queued (0 = none)
    return {
        "playbook": pb,
        "mechanisms": list(idea.get("mechanisms") or []), "mech_pair": mech_pair(idea.get("mechanisms")), **title_features(idea.get("hook", "")), "hook": idea.get("hook", ""),
        "territory": territory_of(idea.get("territory", "")), "style": st.get("visual_style") or idea.get("style", ""), "tone": st.get("tone_id", ""),
        "target_s": st.get("target_s") or 0, "length": length_band(st.get("target_s")), "language": st.get("language", ""), "score": idea.get("engagement_score") or 0,
        "score_band": score_band(idea.get("engagement_score")), "subscores": {k: sb[k] for k in ("hook_strength", "mechanism_count", "emotional_intensity", "completion_rate", "novelty", "progressive_revelation", "shareability") if k in sb},
        "origin": idea.get("origin", "") or "generated", "choices": {"territory": idea.get("territory_src") or "model", **(choices or {})},
    }
