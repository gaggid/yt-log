"""Starter scenarios (data only, docs/PLAN_simulation.md section 10). A template pre-fills hints, rules and settings; the idea text still decides what the story is. The owner's own templates
live in table `sim_templates` and have the same shape."""
from . import store

BUILTIN: list[dict] = [
    {"id": "tp-survival", "name": "Survival", "blurb": "People trapped with limited supplies and a growing threat.",
     "hint": "Survival story. Track supplies, injuries, noise or exposure, a threat clock and how the group holds together. Resources are scarce and every choice costs something.",
     "tone": "tense, grounded", "pacing": "minutes to hours per chapter", "settings": {"difficulty": "fair", "dice": True},
     "rules": [("hard", "Only items that exist in this place or that a character already carries may be used."), ("world", "Noise and light draw the threat; being quiet and hidden is safer."),
               ("tone", "Keep it grounded: fear, fatigue and hard choices matter more than action set pieces.")],
     "trackers": [("clock", "Threat closing in", "rises with noise, time and mistakes"), ("meter", "Group morale", "falls with losses and fear"), ("items", "Supplies", "what the group has and where")]},
    {"id": "tp-mystery", "name": "Mystery", "blurb": "A hidden truth, suspects with secrets, clues that must be found and understood.",
     "hint": "Mystery. Track who knows which secret, relationships between suspects, and a clock until the truth is lost or a deadline passes.",
     "tone": "quiet suspense", "pacing": "hours to days per chapter", "settings": {"difficulty": "fair", "dice": False},
     "rules": [("hard", "A character can only act on what they have actually seen, heard or been told."), ("world", "Every clue found must be consistent with the true solution."),
               ("tone", "Reveal slowly; each chapter adds one clue or one lie exposed.")],
     "trackers": [("knowledge", "Secrets", "who knows what"), ("clock", "Time until the trail goes cold", "rises each day"), ("relation", "Trust between the lead and the main suspect", "")]},
    {"id": "tp-courtroom", "name": "Courtroom or politics", "blurb": "Arguments, alliances, evidence and a decision day.",
     "hint": "Courtroom or political drama. Track evidence, witnesses, alliances, public support and the date of the decision. Conflict is argued, not fought.",
     "tone": "sharp, formal, tense", "pacing": "a session or a day per chapter", "settings": {"difficulty": "fair", "dice": True},
     "rules": [("hard", "Only evidence already introduced may be used in argument."), ("world", "Procedure matters: objections, deadlines and rules of the room are respected."),
               ("tone", "Persuasion and timing win; nobody wins by speeches alone.")],
     "trackers": [("meter", "Public support", ""), ("clock", "Days to the decision", ""), ("knowledge", "Evidence known to each side", "")]},
    {"id": "tp-business", "name": "Business", "blurb": "A company or project with money, people and a market.",
     "hint": "Business story. Track cash, runway, customers or reputation, team morale and competitors. Decisions trade short-term gain for long-term risk.",
     "tone": "pressured, realistic", "pacing": "a week or a month per chapter", "settings": {"difficulty": "fair", "dice": True},
     "rules": [("hard", "Money cannot be spent that the company does not have; debts are tracked."), ("world", "Customers, rivals and regulators react to what the company does."),
               ("tone", "Show the human cost of each decision.")],
     "trackers": [("meter", "Cash", "money available"), ("meter", "Reputation", ""), ("clock", "Months of runway", ""), ("relation", "Trust between founders", "")]},
    {"id": "tp-heist", "name": "Heist", "blurb": "A crew, a target, a plan, and what goes wrong.",
     "hint": "Heist. Track the crew's tools, the alarm or guard attention, the time window and loyalty inside the crew.",
     "tone": "clever, tense, a little playful", "pacing": "minutes per chapter during the job", "settings": {"difficulty": "fair", "dice": True},
     "rules": [("hard", "The crew can only use the tools and information they gathered."), ("world", "Security reacts logically to what it notices."), ("tone", "Plans meet reality: something always goes off script.")],
     "trackers": [("clock", "Alarm level", ""), ("clock", "Time window", ""), ("items", "Tools", ""), ("relation", "Crew loyalty", "")]},
    {"id": "tp-history", "name": "Historical what-if", "blurb": "A real period where one decision goes differently.",
     "hint": "Historical what-if. Keep the period accurate: customs, technology, politics and speech fit the time. Track power, supplies or support, and a looming event.",
     "tone": "grounded, period-true", "pacing": "days to months per chapter", "settings": {"difficulty": "fair", "dice": True},
     "rules": [("hard", "Nothing may appear that did not exist in this period."), ("world", "Historical forces and rivals react in period-appropriate ways."), ("style", "Avoid modern phrasing in dialogue.")],
     "trackers": [("meter", "Support", ""), ("clock", "The coming event", ""), ("relation", "Alliance with the main ally", "")]},
    {"id": "tp-drama", "name": "Relationship drama", "blurb": "People, secrets and choices that change how they feel about each other.",
     "hint": "Relationship drama. Track trust and tension between key pairs, secrets and who knows them, and one clock for a deadline or event that forces a choice.",
     "tone": "intimate, emotional", "pacing": "a day or an evening per chapter", "settings": {"difficulty": "gentle", "dice": False},
     "rules": [("hard", "A character cannot know a secret nobody told them or they did not witness."), ("tone", "Small gestures and silences carry weight."), ("style", "Dialogue should sound like real people, not speeches.")],
     "trackers": [("relation", "Trust between the two leads", ""), ("knowledge", "Secrets", ""), ("clock", "The event that forces a choice", "")]},
    {"id": "tp-free", "name": "Free (no template)", "blurb": "Start from the idea alone.", "hint": "", "tone": "", "pacing": "", "settings": {}, "rules": [], "trackers": []},
]


def all_templates() -> list[dict]:
    return BUILTIN + [{"id": t["id"], "name": t["name"], "blurb": "Saved by you", "builtin": False, **t["data"]} for t in store.templates()]


def get(tid: str) -> dict | None:
    return next((t for t in all_templates() if t["id"] == tid), None)


def hint_text(t: dict | None) -> str:
    if not t or not (t.get("hint") or t.get("trackers")):
        return ""
    bits = [f"TEMPLATE ({t['name']}): {t.get('hint', '')}"]
    if t.get("tone"):
        bits.append(f"Suggested tone: {t['tone']}. Pacing: {t.get('pacing', '')}.")
    if t.get("trackers"):
        bits.append("Suggested trackers (adapt them to this story, drop what does not fit): " + "; ".join(f"{k} '{n}'" + (f" ({d})" if d else "") for k, n, d in [tuple(x) + ("",) * (3 - len(x)) for x in t["trackers"]]))
    return "\n".join(bits)


def apply(pid: str, tid: str) -> None:
    """Copy the template's settings and rules into a new story."""
    t = get(tid)
    if not t:
        return
    if t.get("settings"):
        store.save_project(pid, settings=dict(t["settings"]))
    w = store.world(pid)
    if t.get("tone") and not w.get("tone"):
        store.set_world(pid, {**w, "tone": t["tone"], "pacing": t.get("pacing", "")})
    for grp, text in t.get("rules", []):
        store.save_guideline(pid, {"grp": grp, "text": text, "origin": "owner"})
