"""Narration tones and personas of a short (settings `tone_id`, `edge`). A tone is how the narrator sounds and writes: energy, a suggested speed, the voice tags to lean on and the writing rules that go into the plan
prompt. The personas are archetypes taken from how well-known kinds of speakers talk (founders, politicians, teachers, investigators), written from published analyses and commentary (see docs/PLAN_shorts.md);
they never quote a real person and the voice does not imitate anyone. `edge` is how rough the language may get when the script calls for it.
Speeds are values of the speed menu (0.85, 0.92, 1.0, 1.08, 1.15). Tags must be Maya style tags (story2/maya.py), a test checks."""
DEFAULT = "bigbro"             # the mid-energy one that works anywhere
DEFAULT_EDGE = "clean"

TONES: dict[str, dict] = {
    # generic tones
    "storyteller": {"group": "Tones", "label": "Calm storyteller", "energy": 1, "speed": 0.85, "tags": ["whispers", "curious", "calm"],
                    "sound": "Soft, low, slow, with pauses", "best": "Mysteries, true stories, history",
                    "writing": "Short sentences. Use '...' before a reveal. Slow, atmospheric, nothing shouted."},
    "soothing": {"group": "Tones", "label": "Soothing explainer", "energy": 1, "speed": 0.92, "tags": ["happy", "curious", "calm"],
                 "sound": "Warm, steady, reassuring", "best": "Health, learning, money basics",
                 "writing": "Simple words, one idea at a time, reassuring and patient. Never alarming."},
    "documentary": {"group": "Tones", "label": "Documentary narrator", "energy": 2, "speed": 1.0, "tags": ["serious", "calm"],
                    "sound": "Even, authoritative, no hype", "best": "Science, facts, events",
                    "writing": "Plain facts in a neutral, authoritative voice. Numbers as words. No slang, no hype, no jokes."},
    "bigbro": {"group": "Tones", "label": "Friendly big brother / didi (default)", "energy": 3, "speed": 1.0, "tags": ["happy", "curious", "cheerful"],
               "sound": "Casual, warm, chatty", "best": "Advice, everyday tips, life hacks, almost anything",
               "writing": "Talk like a relatable friend: direct 'tu/aap', everyday words, small jokes, never preachy."},
    "explorer": {"group": "Tones", "label": "Curious explorer", "energy": 3, "speed": 1.08, "tags": ["curious", "excited", "amazed", "surprised"],
                 "sound": "Rising pitch, wonder", "best": "Facts, 'did you know', tech",
                 "writing": "Ask real questions the viewer would ask. 'But here is the twist.' Wonder, not hype."},
    "thriller": {"group": "Tones", "label": "Dramatic thriller", "energy": 3, "speed": 1.0, "tags": ["nervous", "scared", "whispers", "serious"],
                 "sound": "Tense, building, sharp beats", "best": "Crime, incidents, disasters",
                 "writing": "A long sentence, then a blunt one. Build tension, hold the reveal, end on a sting."},
    "roaster": {"group": "Tones", "label": "Sarcastic roaster", "energy": 3, "speed": 1.08, "tags": ["sarcastic", "frustrated", "annoyed"],
                "sound": "Dry, mocking, deadpan", "best": "Comparisons, mistakes, 'what went wrong'",
                "writing": "Dry punchlines, rhetorical questions, understatement. Mock the idea or the mistake, never the viewer."},
    "motivator": {"group": "Tones", "label": "Hype motivator", "energy": 4, "speed": 1.15, "tags": ["excited", "loudly", "shouting"],
                  "sound": "Loud, fast, rising", "best": "Motivation, fitness, business",
                  "writing": "Commands, short bursts, repetition, a rising push to the last line."},
    "viral": {"group": "Tones", "label": "Fast viral hook", "energy": 4, "speed": 1.15, "tags": ["excited", "surprised"],
              "sound": "Quick, punchy, no pauses", "best": "News, trending topics, lists",
              "writing": "A hook of seven words or fewer, then a new fact every few seconds. No filler, no greeting."},
    "intense": {"group": "Tones", "label": "Intense / aggressive", "energy": 5, "speed": 1.15, "tags": ["angry", "shouting", "frustrated", "loudly"],
                "sound": "Hard, urgent, shouting", "best": "Exposes, outrage, warnings, rants",
                "writing": "Accusing, blunt, no softening, short hard sentences, build anger toward the last line."},
    # story personas: who is telling the story, and from where
    "survivor": {"group": "Story personas", "label": "Survivor (first person)", "energy": 3, "speed": 1.0, "tags": ["nervous", "scared", "whispers"], "pov": "first, the narrator is a named person who lived it",
                 "sound": "Low, shaken, close to the ear", "best": "Horror, thrillers, true-crime told by someone who was there",
                 "writing": "'I' tells it, as a named person who was there; the name is said once, by someone else in the story. Say what the body felt and what the mind refused to believe. Never explain more than the narrator knew at that moment."},
    "campfire": {"group": "Story personas", "label": "Campfire storyteller (third person)", "energy": 2, "speed": 0.92, "tags": ["whispers", "curious", "calm"], "pov": "third, a teller who knows the people by name",
                 "sound": "Warm, slow, knowing, a half-smile", "best": "Folk tales, ghost stories, mysteries, legends",
                 "writing": "The teller addresses the listener once, in the opening line only ('suno'), names every person at once and tells what they did and said. Plain, rhythmic, one image per line; the teller may hint at what comes without spoiling it."},
    "investigator": {"group": "Story personas", "label": "Cold investigator (third person)", "energy": 2, "speed": 0.92, "tags": ["serious", "calm"], "pov": "third, a detached observer who names everyone",
                     "sound": "Flat, exact, unhurried", "best": "Crimes, disappearances, real incidents",
                     "writing": "Name each person with their role, then the time, the place and what they did. Facts in the order they were found. Let one cold detail do the frightening; never raise the voice."},
    "memoir": {"group": "Story personas", "label": "Memoir voice (first person)", "energy": 2, "speed": 0.92, "tags": ["calm", "serious", "happy"], "pov": "first, the narrator is a named person looking back",
               "sound": "Reflective, warm, a little rueful", "best": "Biographies, personal stories, turning points",
               "writing": "'I' looks back and knows how it ended: small honest details, the names of the people who mattered, one regret. A line of hindsight is allowed, a lecture is not."},
    # personas
    "founder_first": {"group": "Personas", "label": "First-principles founder", "energy": 3, "speed": 1.08, "tags": ["curious", "serious"],
                      "sound": "Fast, thinking aloud, short pauses before hard points", "best": "Tech, engineering, big-bet stories",
                      "writing": "Reason from the basics out loud: 'what is it really made of'. Let a sentence restart itself once or twice, like a person thinking. Matter-of-fact about huge numbers."},
    "ceo_empathy": {"group": "Personas", "label": "Empathetic CEO", "energy": 2, "speed": 0.92, "tags": ["happy", "calm", "serious"],
                    "sound": "Measured, warm, purposeful", "best": "Leadership, change, culture, tech for people",
                    "writing": "Start from people and purpose, not the product. A learn-it-all framing: 'we were wrong, we learned'. One plain, substantive sentence instead of buzzwords."},
    "operator_blunt": {"group": "Personas", "label": "Blunt startup operator", "energy": 4, "speed": 1.08, "tags": ["frustrated", "sarcastic", "serious"],
                       "sound": "Direct, brisk, a dry laugh at himself", "best": "Business breakdowns, pitches, startup lessons",
                       "writing": "Give the verdict first, then the reason. Blunt, dry humour, a self-deprecating aside. Clarity of vision matters more than polish."},
    "orator_rally": {"group": "Personas", "label": "Rally orator", "energy": 4, "speed": 1.08, "tags": ["loudly", "excited", "shouting"],
                     "sound": "Soft opening, building louder and faster", "best": "Speeches, movements, history with a crowd feel",
                     "writing": "Open soft and personal, then build. Ask the audience direct questions ('bolo, sahi hai ya nahi?'). Use a symbol or a story from the epics to carry the point. Repeat the key line."},
    "debater_erudite": {"group": "Personas", "label": "Erudite debater", "energy": 3, "speed": 1.0, "tags": ["sarcastic", "curious", "serious"],
                        "sound": "Polished, witty, precise", "best": "Politics, history, argument, culture",
                        "writing": "Longer balanced sentences, a precise rare word now and then, a dry wit. Concede one point, then take it apart."},
    "teacher_energy": {"group": "Personas", "label": "High-energy teacher", "energy": 4, "speed": 1.08, "tags": ["excited", "cheerful", "loudly"],
                       "sound": "Loud, friendly, classroom energy", "best": "Exam topics, science, how things work",
                       "writing": "Explain with an everyday analogy in Hindi-English. Recap in one line. Check the class: 'samajh aaya?'. Make it fun without losing the concept."},
    "educator_measured": {"group": "Personas", "label": "Measured educator", "energy": 2, "speed": 0.92, "tags": ["calm", "serious"],
                          "sound": "Calm, unhurried, deep", "best": "Concepts, civics, long-form reasoning",
                          "writing": "Reason step by step, show why before what. Calm depth, little spectacle, one idea fully finished before the next."},
    "osint": {"group": "Personas", "label": "Open-source intelligence analyst", "energy": 2, "speed": 0.92, "tags": ["serious", "calm"],
              "sound": "Flat, careful, factual", "best": "Investigations, verification, conflicts, fake-news checks",
              "writing": "Say how it was checked. Keep what was verified apart from what could not be verified, in plain words. State confidence. No guesses presented as facts."},
    "explainer_claim": {"group": "Personas", "label": "Claim-evidence explainer", "energy": 3, "speed": 1.08, "tags": ["serious", "sarcastic", "frustrated"],
                        "sound": "Brisk, confident, with a conflict edge", "best": "Politics, economy, controversies",
                        "writing": "Make a claim, show the proof, draw the conclusion. Point at the numbers and the contradiction. Keep the edge on the argument, not on invented facts."},
}

EDGES: dict[str, dict] = {
    "clean": {"label": "Clean", "rule": "No swearing and no insults. Sarcasm is fine."},
    "spicy": {"label": "Spicy (sarcasm, mild swearing)", "rule": ("Where the script's content calls for it, the narrator may be sarcastic, rude and use mild everyday swear words "
                                                                   "(for example 'bakwaas', 'faltu', 'damn', 'hell'), the way real creators do. Never in every sentence.")},
    "savage": {"label": "Savage (harsh, abusive tone)", "rule": ("Where the script's content calls for it, the narrator may be harsh, abusive in tone and use strong everyday swear words, "
                                                                   "like an angry creator ranting. Aim it at ideas, companies, systems and situations. Never use slurs or hate against any group, "
                                                                   "never abuse a real named person, and never state an invented claim about a real person as fact.")},
}


def of(settings: dict | None) -> str:
    t = (settings or {}).get("tone_id")
    return t if t in TONES else DEFAULT


def edge_of(settings: dict | None) -> str:
    e = (settings or {}).get("edge")
    return e if e in EDGES else DEFAULT_EDGE


def prompt_text(settings: dict | None) -> str:
    """The lines that go into the plan prompt."""
    t, e = TONES[of(settings)], EDGES[edge_of(settings)]
    return (f"\nNarration tone: {t['label'].split(' (')[0]} (energy {t['energy']} of 5; sounds {t['sound'].lower()}). Writing rules: {t['writing']} "
            f"\nLanguage edge: {e['rule']}")


def speed_of(settings: dict | None) -> float:
    return TONES[of(settings)]["speed"]


def public() -> dict:
    return {"tones": [{"id": k, **{x: v[x] for x in ("group", "label", "energy", "speed", "sound", "best")}} for k, v in TONES.items()],
            "edges": [{"id": k, "label": v["label"]} for k, v in EDGES.items()], "default": DEFAULT}
