"""The kinds of video a source can become. One type per project (owner decision 2026-10-27); to get another type from the same source, import it again.

The type is chosen once on the project, copied to each plan (`plan.settings.story_type`) and read through `of_plan` / `of_project` so a project or plan from before this
setting behaves as `incident`. Everything that differs by type (prompts, scoring, shot mix, graphics) reads the type through here, never from the raw setting."""
from __future__ import annotations

DEFAULT = "incident"

STORY_TYPES: dict[str, dict] = {
    "incident": {"label": "Incident story", "short": "one event with a turning point and an outcome",
                 "about": "A single documented event told as a story: setup, conflict, turning point, outcome."},
    "biography": {"label": "Biography", "short": "one person's life, phase by phase",
                  "about": "One subject followed through the phases and turning points of their life, in order."},
    "documentary": {"label": "Documentary", "short": "one thesis, argued from evidence",
                    "about": "A claim examined with evidence, a counterpoint and a conclusion."},
    "explainer": {"label": "Explainer", "short": "one question, answered step by step",
                  "about": "A concept or process explained simply, then in detail, then the common misconception."},
    "listicle": {"label": "Listicle", "short": "a numbered list of items",
                 "about": "A counted list of items from the source, each with its own short segment."},
}


def valid(t: str | None) -> bool:
    return t in STORY_TYPES


def clean(t: str | None) -> str:
    return t if valid(t) else DEFAULT


def of_plan(plan: dict | None) -> str:
    return clean(((plan or {}).get("settings") or {}).get("story_type"))


def of_project(project: dict | None) -> str:
    return clean(((project or {}).get("meta") or {}).get("story_type"))


def public() -> list[dict]:
    return [{"id": k, **v} for k, v in STORY_TYPES.items()]


def for_pid(pid: str) -> str:
    """The type of a project by id, read straight from the database (used where a whole project record is not at hand)."""
    from . import db
    r = db.one("SELECT meta FROM projects WHERE id=?", (pid,))
    return of_project({"meta": db.jload(r["meta"], {}) if r else {}})


# What changes in Phase 1 for a type other than `incident`. The model keeps the same labels, so every screen and filter still works: for these types,
# `nature: "story"` means "a good fit for this type" and the incident-only downgrade rules (single actor and decision, a date, an outcome) do not apply.
_FIT = ('For this project a good fit for the type is labelled nature "story" (use "anecdote" only for a passing mention, "hypothetical" for an imagined scenario, '
        'and "explainer" only when the passage teaches something unrelated to the type). ')

DISCOVER_NOTE = {
    "biography": "\n\nPROJECT TYPE: BIOGRAPHY. The video follows ONE person through their life, so a lead is a phase of that life or a turning point in it "
                 "(origins, a breakthrough, a failure, a late chapter), told in order. Pick the leads that together cover the person's arc; a lead needs the "
                 "person, a period and what changed for them. " + _FIT,
    "documentary": "\n\nPROJECT TYPE: DOCUMENTARY. The video examines ONE thesis with evidence, so a lead is a claim, the evidence for it, a counterpoint or a "
                   "consequence. Prefer leads with specific, checkable facts (numbers, records, named sources) and leads that disagree with each other. " + _FIT,
    "explainer": "\n\nPROJECT TYPE: EXPLAINER. The video answers ONE question step by step, so a lead is a concept, a mechanism, a step of a process, or a common "
                 "misconception. A lead needs a clear question it answers and the facts that answer it; teaching is wanted here. " + _FIT,
    "listicle": "\n\nPROJECT TYPE: LISTICLE. The video is a numbered list, so a lead is ONE list item: a self-contained example, reason, rule or case that "
                "can stand alone in about a minute. Prefer items of similar weight that a viewer can count. " + _FIT,
}

DRAFT_NOTE = {
    "biography": "\n\nPROJECT TYPE: BIOGRAPHY. Write the record about the person across the period these passages cover. Chronology is the spine: give the "
                 "phases in order with their dates as stated. Conflict, turning_point and outcome describe this phase of the life (what changed, what it led to); "
                 "leave them empty if the passages do not say.",
    "documentary": "\n\nPROJECT TYPE: DOCUMENTARY. Write the record around one claim. Put the claim in premise, the evidence in claims (with exact quotes), the "
                   "counterpoint or opposing account in conflict and uncertainties, and what follows in outcome. Weak or single-source support must score low on evidence.",
    "explainer": "\n\nPROJECT TYPE: EXPLAINER. Write the record around the question being answered. Put the question in curiosity_question, the answer in "
                 "turning_point, the steps in chronology (in the order a learner needs them, dates not required), and the usual misunderstanding in conflict.",
    "listicle": "\n\nPROJECT TYPE: LISTICLE. Write the record for ONE list item: premise states the item in a sentence, claims carry its facts, curiosity_question "
                "says why a viewer should care. No overall arc is needed.",
}


def discover_note(t: str) -> str:
    return DISCOVER_NOTE.get(t, "")


def draft_note(t: str) -> str:
    return DRAFT_NOTE.get(t, "")


# ── Phase 2: the same three prompts (blueprint, narration, director) with a note per type ─────────────────────────────────────────────────────────────────
# `incident` has no note: the prompts are written for it. Each note names the structure to choose (schemas.STRUCTURES) so the blueprint never falls back to cold_open.

STRUCTURE = {"biography": "life_arc", "documentary": "evidence_case", "explainer": "question_journey", "listicle": "numbered_list"}

BLUEPRINT_NOTE = {
    "biography": "\n\nPROJECT TYPE: BIOGRAPHY. This video tells ONE person's life, not one incident. Use structure \"life_arc\": a hook from the most striking moment of the "
                 "life, then the phases in order (origins, rise, the turning points, setbacks, the late chapter), ending on what the person left behind. Each beat is a phase "
                 "or a turning point and names its period as the facts state it. Suspense comes from the question \"how did this person get here\" and from what each phase "
                 "costs them; never invent an outcome, a date or a feeling the facts do not give.",
    "documentary": "\n\nPROJECT TYPE: DOCUMENTARY. This video examines ONE thesis with evidence. Use structure \"evidence_case\": a hook that states the puzzle or claim, "
                   "then the evidence in order of strength, the strongest counterpoint, what the evidence does and does not prove, and a conclusion that says what is still unknown. "
                   "Every beat carries checkable facts; say how sure the facts are. The central_question is the thesis put as a question.",
    "explainer": "\n\nPROJECT TYPE: EXPLAINER. This video answers ONE question. Use structure \"question_journey\" (or \"problem_mechanism\"): the question first, a simple "
                 "picture of the answer, then the steps or parts in the order a learner needs them, the common misconception, and the answer again in one line. Each beat teaches one "
                 "thing and ends on the question the next beat answers. People and events are only examples.",
    "listicle": "\n\nPROJECT TYPE: LISTICLE. This video is a numbered list. Use structure \"numbered_list\": a hook that says what the list is and why it is worth the time, then "
                "one beat per item (name the number in the beat name, for example \"3. The quiet fix\"), then a closing beat that ties the items together. Order the items so "
                "interest rises; hold the strongest for last. Each beat stands alone in about a minute.",
}

NARRATE_NOTE = {
    "biography": "\n\nPROJECT TYPE: BIOGRAPHY. The narrator speaks about one person across their life. Name the period each time the story moves on (only as the facts state it). "
                 "Keep the person human: what they wanted, what it cost. Do not invent thoughts, quotes or scenes; say \"शायद\" only when the facts are uncertain.",
    "documentary": "\n\nPROJECT TYPE: DOCUMENTARY. The narrator lays out evidence calmly and fairly. Say where a fact is firm and where it is only reported. Give the counterpoint its due. "
                   "Numbers are spoken as words and always with what they measure.",
    "explainer": "\n\nPROJECT TYPE: EXPLAINER. The narrator teaches: one idea per sentence, an everyday comparison before the technical term, the term given in English once. "
                 "Check the viewer's understanding with a question before the answer. No drama that the facts do not have.",
    "listicle": "\n\nPROJECT TYPE: LISTICLE. The narrator counts. Each item beat starts by saying its number and name, then explains it with its strongest fact, then hands over to the next. "
                "Keep items equal in length. The closing beat names the pattern across the items.",
}

# Notes for the three-pass narration (draft and edit): what each kind of film needs from the telling, over the details of the Material Pack.
TELL_NOTE = {
    "incident": "\n\nThis is a story of an incident. Tell the chain of discovery in order: what was found first, what it led to, what each clue made the people do. Each clue is given before it is explained.",
    "biography": "\n\nThis is a life. Name the period each time the telling moves on, as the details give it; show who the person was at that age (what they wanted, what it cost). Keep them human, never a monument.",
    "documentary": "\n\nThis is a documentary. Lay out the evidence calmly: what is firm, what is only reported, then the other side with its due. Every number comes with what it measures.",
    "explainer": "\n\nThis is an explainer. One everyday comparison that stays with the viewer, used again and again, before the technical term; the term is said once. One idea per sentence.",
    "listicle": "\n\nThis is a numbered list. Each item starts with its number and name, gives its strongest detail and one vivid example, then hands over to the next.",
}

POLISH_NOTE = {
    "incident": "\n\nKeep the order of discovery; do not move the answer earlier than the part that tells it.",
    "biography": "\n\nKeep the period markers; never invent a thought or a quote for the person.",
    "documentary": "\n\nKeep every hedge (reportedly, according to, the study found); never turn a claim into a fact.",
    "explainer": "\n\nKeep the comparison the same all through; cut a second comparison that competes with it.",
    "listicle": "\n\nKeep the item number at the start of its part; keep the items equal in length.",
}


def tell_note(t: str) -> str:
    return TELL_NOTE.get(t, "")


def polish_note(t: str) -> str:
    return POLISH_NOTE.get(t, "")


DIRECTOR_NOTE = {
    "biography": "\n\nPROJECT TYPE: BIOGRAPHY. Show the person in each phase (age, place and clothes change with the period) and the places that shaped them. Use establishing shots at every "
                 "change of period. A person with a real name is only ever drawn as the registry describes them.",
    "documentary": "\n\nPROJECT TYPE: DOCUMENTARY. Favour places, objects, documents-as-shown-on-a-desk and wide establishing shots over faces; the evidence is the subject. "
                   "Plan a data moment (kind object or establishing) where the narration quotes numbers; the numbers themselves are added later as a built graphic. "
                   "VISUAL DEVICE TOOLKIT — when the blueprint beat has an unfilmable concept, plan one of these devices (name it in the shot focus): "
                   "scale plate (a real place or object shown at the concept's scale — a galaxy dwarfing a city, a virus beside a red blood cell); "
                   "graphic overlay on a real desk or wall (a chart or diagram printed and lying on a surface); "
                   "object metaphor (a physical stand-in that makes scale or probability concrete, e.g. a single grain of sand in a handful); "
                   "before/after of the same place. Never place a microscopic or cosmic object at human scale unless the blueprint's visual_device says so.",
    "explainer": "\n\nPROJECT TYPE: EXPLAINER. Show the thing being explained in a real setting where it happens (a workshop, a lab, a street), close on the parts a learner must see. "
                 "Keep one steady place per idea; move the camera to show size and relation (a pull back for the whole, a push in for the detail). "
                 "VISUAL DEVICE TOOLKIT — when the blueprint beat has an unfilmable concept, plan one of these devices (name it in the shot focus): "
                 "scale plate (the concept shown at its true scale beside something familiar); "
                 "close detail (extreme close of the real object where the mechanism lives, e.g. a transistor gate under magnification); "
                 "diagram on a real surface (a hand-drawn or printed diagram lying on a desk or whiteboard, shot as an object in a real place); "
                 "step reveal (a wide shot of the system, then a push-in to the part that changes). Never place a microscopic or cosmic object at human scale unless the blueprint's visual_device says so.",
    "listicle": "\n\nPROJECT TYPE: LISTICLE. Give each item its own place and look so the items feel separate; begin each item with an establishing shot of where it happens. "
                "The number card for each item is added later as a built graphic.",
}


def blueprint_note(t: str) -> str:
    return BLUEPRINT_NOTE.get(t, "")


def narrate_note(t: str) -> str:
    return NARRATE_NOTE.get(t, "")


def director_note(t: str) -> str:
    return DIRECTOR_NOTE.get(t, "")


# ── Phase 2/3: built graphics asked for by the scene designer ────────────────────────────────────────────────────────────────────────────────────────────
# `story3/graphics.py` already builds a timeline (visual_type map_timeline, from the story's dated events), a chart or stat card (data_chart, from verified numbers) and a text card
# (diagram with text_on_screen). The scene designer is told when each type wants one, so these cards exist in the storyboard and `graphics.build` makes them.

SCENES_NOTE = {
    "biography": "\n\nPROJECT TYPE: BIOGRAPHY. Where the narration moves to a new period of the person's life and the facts give at least two dated events, make that scene "
                 "visual_type \"map_timeline\" (it is built later as a timeline from the story's dated events; do not draw it). All other scenes are pictures of the person's world.",
    "documentary": "\n\nPROJECT TYPE: DOCUMENTARY. Where the narration states two or more numbers that are in the story facts, make ONE scene visual_type \"data_chart\" with each number "
                   "and what it measures in facts.fixed (for example \"41 percent of readings were above the limit\"); it is built later as a chart from those facts. Never invent a number.",
    "explainer": "\n\nPROJECT TYPE: EXPLAINER. Show the thing being explained in its real setting. When a figure in the story facts is the point of a step, one scene may be "
                 "visual_type \"data_chart\" built from it later.",
    "listicle": "\n\nPROJECT TYPE: LISTICLE. The FIRST scene of every list item is a number card: visual_type \"diagram\", text_on_screen with ONE entry whose text is the item "
                "number and a short name in plain English letters (for example \"3. The quiet fix\", at most 8 words), nothing else drawn (the card is built later). "
                "The other scenes of the item are pictures of the item itself.",
}


def scenes_note(t: str) -> str:
    return SCENES_NOTE.get(t, "")
