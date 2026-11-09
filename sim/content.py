"""How freely a story may go: language, cruelty, crime. The owner's model is unrestricted, and the story is private adult fiction, so the default is no limits from the narrator; each story can be turned down
(docs/PLAN_simulation.md). The text is put in every chapter packet and in the setup calls, so the planner, writer and option writer all know it."""

LEVELS = ("clean", "mature", "unfiltered")
LABELS = {"clean": "clean (mild language, violence off the page)", "mature": "mature (strong language and violence when the scene needs them)",
          "unfiltered": "unfiltered (anything the story calls for)"}

TEXT = {
    "clean": "Keep the language clean and the violence mostly off the page. Characters can still be flawed and make bad choices.",
    "mature": "Adult story. Characters may swear, threaten and fight, and dark things can happen on the page when the scene calls for them.",
    "unfiltered": ("Private adult fiction with no limits set by the narrator. People talk and act as such people really would: they swear, insult and abuse each other in strong, explicit words, lie, steal, betray, "
                   "hurt and kill, and take unconventional, ruthless or illegal steps to get what they want. Do not soften, censor or moralise: no disclaimers, no lessons, no author's judgement, and do not make anyone "
                   "turn good to please the reader. Wrongdoing is part of this world and has consequences inside it (people react, enemies and the law respond, things go wrong), "
                   "decided by the rules and the dice, not by what is nice."),
}


def level(settings: dict) -> str:
    v = (settings or {}).get("content", "unfiltered")
    return v if v in LEVELS else "unfiltered"


def text(settings: dict) -> str:
    return TEXT[level(settings)]
