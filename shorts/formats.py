"""The format of a short: how the facts are told. A dramatised story follows one person through a turning point; an article of facts and numbers does not need an invented person, it needs
its real subjects shown clearly. The plan call decides the format from the facts (setting `format` = "auto") or the producer chooses one; the choice is stored in plan["format"] and steers
the narration prompt, the shot prompt and whether an invented main character is allowed."""

AUTO = "auto"

FORMATS: dict[str, dict] = {
    "story": {
        "label": "Story (dramatised)",
        "about": "An event with people, a turning point and an outcome, told as a scene we live through.",
        "plan": "Dramatise it. Follow one main person (or the real people in the facts) through a turning point; show feeling, a scene, a payoff. The beats are an arc.",
        "shots": "Show the people and the moment as a scene: faces, reactions, places. The main person may appear in a few shots.",
        "character": True,
    },
    "documentary": {
        "label": "Documentary",
        "about": "A real subject explained over footage of the real thing: places, machines, people, events.",
        "plan": "Tell it as a documentary: the narrator is an authority explaining over real-looking footage of the actual subjects. No invented main person, no acting. Vivid, concrete, calm.",
        "shots": "Show the real subjects and places as footage would: establishing views, machines or people at work, close details. Nobody acts to the camera.",
        "character": False,
    },
    "explainer": {
        "label": "Explainer (facts)",
        "about": "Facts, numbers and cause and effect explained clearly; an article, a report, a how it works.",
        "plan": "Explain it. One clear question, then the facts in order of importance, each point with its number or cause, and an answer at the end. No invented main person; curiosity, not drama.",
        "shots": "Show the thing each point is about, clearly and one at a time: the machine, the place, the process, the difference. A clean picture per fact.",
        "character": False,
    },
    "comparison": {
        "label": "Comparison (side by side)",
        "about": "Two or more sides set against each other, such as two countries, products or methods.",
        "plan": "Set the sides against each other. Alternate between them point by point, give each side the same kind of fact, and end on what decides it. No invented main person.",
        "shots": "Alternate the sides shot by shot and draw each side the same way every time (its colours, markings, setting) so the viewer always knows which is which.",
        "character": False,
    },
}


def valid(f: str) -> bool:
    return f in FORMATS


def allows_character(f: str) -> bool:
    return FORMATS.get(f, FORMATS["story"])["character"]


def plan_section(choice: str) -> str:
    """The format paragraph of the plan prompt: the four formats to pick from (auto), or the one the producer chose."""
    if valid(choice):
        f = FORMATS[choice]
        return f'The producer chose the format "{choice}" ({f["label"]}). Set "format" to "{choice}". {f["plan"]}'
    lines = "\n".join(f'  - "{k}" ({v["label"]}): {v["about"]} {v["plan"]}' for k, v in FORMATS.items())
    return ('Decide the format from the facts and set "format" to one of these. Facts, numbers or a comparison are NOT a story to dramatise: use explainer, comparison or documentary for them; '
            "use story only when the facts are an event with people and a turning point.\n" + lines)


def shot_rule(f: str) -> str:
    return FORMATS.get(f, FORMATS["story"])["shots"]
