"""Starter scenarios (data only, docs/PLAN_simulation.md section 10). A template pre-fills hints, rules and settings; the idea text still decides what the story is. The owner's own templates
live in table `sim_templates` and have the same shape."""
from . import store

BUILTIN: list[dict] = [
    {"id": "tp-survival", "name": "Survival", "blurb": "People trapped with limited supplies and a growing threat.",
     "hint": "Survival story. Track supplies, injuries, noise or exposure, a threat clock and how the group holds together. Resources are scarce and every choice costs something.",
     "tone": "tense, grounded", "pacing": "minutes to hours per chapter", "settings": {"difficulty": "fair", "dice": True, "carry_limit": 8}, "craft": "Makeshift tools and barricades from what is at hand; nothing that needs a factory or a power grid.",
     "rules": [("hard", "Only items that exist in this place or that a character already carries may be used."), ("world", "Noise and light draw the threat; being quiet and hidden is safer."),
               ("tone", "Keep it grounded: fear, fatigue and hard choices matter more than action set pieces."), ("craft", "Things are made only from parts that are at hand, and crude work breaks quickly.")],
     "trackers": [("clock", "Threat closing in", "rises with noise, time and mistakes"), ("meter", "Group morale", "falls with losses and fear"), ("items", "Supplies", "what the group has and where")]},
    {"id": "tp-mystery", "name": "Mystery", "blurb": "A hidden truth, suspects with secrets, clues that must be found and understood.",
     "hint": "Mystery. Track who knows which secret, relationships between suspects, and a clock until the truth is lost or a deadline passes.",
     "tone": "quiet suspense", "pacing": "hours to days per chapter", "settings": {"difficulty": "fair", "dice": False, "carry_limit": 0}, "craft": "Clues, documents and statements can be found and pieced together; nothing is invented to fit the solution.",
     "rules": [("hard", "A character can only act on what they have actually seen, heard or been told."), ("world", "Every clue found must be consistent with the true solution."),
               ("tone", "Reveal slowly; each chapter adds one clue or one lie exposed."), ("craft", "A clue can only be found where someone could really have left it.")],
     "trackers": [("knowledge", "Secrets", "who knows what"), ("clock", "Time until the trail goes cold", "rises each day"), ("relation", "Trust between the lead and the main suspect", "")]},
    {"id": "tp-courtroom", "name": "Courtroom or politics", "blurb": "Arguments, alliances, evidence and a decision day.",
     "hint": "Courtroom or political drama. Track evidence, witnesses, alliances, public support and the date of the decision. Conflict is argued, not fought.",
     "tone": "sharp, formal, tense", "pacing": "a session or a day per chapter", "settings": {"difficulty": "fair", "dice": True, "carry_limit": 0}, "craft": "Evidence, statements and motions can be found, prepared and filed; they must exist in the record or be gathered by someone with access.",
     "rules": [("hard", "Only evidence already introduced may be used in argument."), ("world", "Procedure matters: objections, deadlines and rules of the room are respected."),
               ("tone", "Persuasion and timing win; nobody wins by speeches alone."), ("craft", "Evidence only counts once it has been properly obtained and introduced.")],
     "trackers": [("meter", "Public support", ""), ("clock", "Days to the decision", ""), ("knowledge", "Evidence known to each side", "")]},
    {"id": "tp-business", "name": "Business", "blurb": "A company or project with money, people and a market.",
     "hint": "Business story. Track cash, runway, customers or reputation, team morale and competitors. Decisions trade short-term gain for long-term risk.",
     "tone": "pressured, realistic", "pacing": "a week or a month per chapter", "settings": {"difficulty": "fair", "dice": True, "carry_limit": 0}, "craft": "Products, contracts and deals can be made or found if the company has the money, people and time for them.",
     "rules": [("hard", "Money cannot be spent that the company does not have; debts are tracked."), ("world", "Customers, rivals and regulators react to what the company does."),
               ("tone", "Show the human cost of each decision."), ("craft", "Nothing is built or bought without the money and people to do it.")],
     "trackers": [("meter", "Cash", "money available"), ("meter", "Reputation", ""), ("clock", "Months of runway", ""), ("relation", "Trust between founders", "")]},
    {"id": "tp-heist", "name": "Heist", "blurb": "A crew, a target, a plan, and what goes wrong.",
     "hint": "Heist. Track the crew's tools, the alarm or guard attention, the time window and loyalty inside the crew.",
     "tone": "clever, tense, a little playful", "pacing": "minutes per chapter during the job", "settings": {"difficulty": "fair", "dice": True, "carry_limit": 8}, "craft": "Gadgets and disguises can be improvised from tools and parts the crew gathered; nothing high-tech appears from nowhere.",
     "rules": [("hard", "The crew can only use the tools and information they gathered."), ("world", "Security reacts logically to what it notices."), ("tone", "Plans meet reality: something always goes off script.")],
     "trackers": [("clock", "Alarm level", ""), ("clock", "Time window", ""), ("items", "Tools", ""), ("relation", "Crew loyalty", "")]},
    {"id": "tp-history", "name": "Historical what-if", "blurb": "A real period where one decision goes differently.",
     "hint": "Historical what-if. Keep the period accurate: customs, technology, politics and speech fit the time. Track power, supplies or support, and a looming event.",
     "tone": "grounded, period-true", "pacing": "days to months per chapter", "settings": {"difficulty": "fair", "dice": True, "carry_limit": 8}, "craft": "Only what the period could make: its materials, tools and know-how.",
     "rules": [("hard", "Nothing may appear that did not exist in this period."), ("world", "Historical forces and rivals react in period-appropriate ways."), ("style", "Avoid modern phrasing in dialogue.")],
     "trackers": [("meter", "Support", ""), ("clock", "The coming event", ""), ("relation", "Alliance with the main ally", "")]},
    {"id": "tp-drama", "name": "Relationship drama", "blurb": "People, secrets and choices that change how they feel about each other.",
     "hint": "Relationship drama. Track trust and tension between key pairs, secrets and who knows them, and one clock for a deadline or event that forces a choice.",
     "tone": "intimate, emotional", "pacing": "a day or an evening per chapter", "settings": {"difficulty": "gentle", "dice": False, "carry_limit": 0}, "craft": "Letters, gifts and keepsakes can be found or made; they matter for what they mean.",
     "rules": [("hard", "A character cannot know a secret nobody told them or they did not witness."), ("tone", "Small gestures and silences carry weight."), ("style", "Dialogue should sound like real people, not speeches.")],
     "trackers": [("relation", "Trust between the two leads", ""), ("knowledge", "Secrets", ""), ("clock", "The event that forces a choice", "")]},
    {"id": "tp-film", "name": "Day-by-day film", "blurb": "A short film told to \"you\": one tight situation, one scene per day, a hidden truth, rules you discover, a twist.",
     "hint": "A short story that could be filmed in ten minutes, told to the reader as \"you\" in the present tense. One tight situation and one person. A concrete problem in every scene, solved with real-world knowledge and numbers. The person discovers named rules. "
             "Something recurring marks time (a sound, a ritual). A hidden truth is planted from the first scene and revealed late; every setup is paid off; the ending turns the beginning around.",
     "tone": "tense, dry humor, concrete", "pacing": "a day or a few days per scene, with time jumps", "settings": {"difficulty": "fair", "dice": True, "carry_limit": 0, "length": 12, "chapter_words": 160, "plan": True, "polish": True, "signposts": True},
     "craft": "What the person can make or do comes from real knowledge and what is in the room; nothing high-tech appears from nowhere.",
     "rules": [("style", "Tell it in second person, present tense, short sentences, with real numbers (hours, days, amounts)."), ("tone", "Dry humor is allowed; fear is shown by what the person notices, not by adjectives."),
               ("hard", "Every scene ends on a turn or a hook, never on a list of choices."), ("world", "The hidden truth is never stated before the scene that reveals it."), ("craft", "A solution uses a real fact or an item the person already has.")],
     "trackers": [("clock", "Pressure that closes in", "rises with time and mistakes; when full something bad happens"), ("meter", "Supplies", "water, food or whatever the person lives on"), ("items", "What the person has", "")]},
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
    if t.get("craft"):
        bits.append(f"What can be made or found here (use it for the world card's craft field): {t['craft']}")
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
