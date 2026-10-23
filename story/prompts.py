"""Prompts. Each begins with a [TASK:name] tag (also lets test doubles route requests deterministically).
Paragraph labels like [P12] are the only way the model may point at source text."""

ANALYZE = """[TASK:analyze_chunk]
You are a careful research analyst reading ONE portion of a larger source (a book or an article).
Extract what the text actually says. Never add outside knowledge and never invent details.
Every paragraph is labelled [P<number>]. Paragraphs under "CONTEXT" repeat the end of the previous portion
for continuity only; you may cite them but focus on the MAIN TEXT.

Return ONLY one JSON object in exactly this shape:
{
  "summary": "faithful 5-10 sentence summary that keeps names, dates, numbers and the order of events",
  "events": [{"what": "what happened", "when": "date/period exactly as the text states it, or empty. Never guess a year", "who": ["people/orgs involved"], "para_ids": [12, 13]}],
  "entities": [{"name": "person/place/organisation/thing", "role": "who or what it is in this text", "para_ids": [12]}],
  "facts": [{"claim": "specific checkable statement, including numbers", "caveat": "uncertainty, dispute or attribution, or empty", "para_ids": [14]}],
  "open_questions": ["things the text raises but leaves unresolved"],
  "story_seeds": [{"title": "working title", "premise": "one sentence", "para_ids": [12, 13, 14]}]
}
Rules:
- para_ids may only use numbers from the [P..] labels you were given.
- Keep every significant event, date, number, cause and consequence; do not compress into vague generalities.
- List events in the order the text presents them.
- Never write paragraph labels such as [P12] inside any text field; only inside para_ids.
- A story seed is a self-contained incident, case study, surprising fact with its explanation, or chain of decisions and consequences. Use [] if there is none. Do not write narration or a script."""

ROLLUP = """[TASK:chapter_rollup]
You are consolidating notes about one chapter or section of a source. You receive faithful notes for each part
of it (summaries and key events). Write a single faithful chapter record.
Return ONLY this JSON object:
{
  "summary": "8-14 sentence summary of the whole chapter that preserves names, dates, numbers, cause and effect, and the order of events",
  "themes": ["short theme", "..."],
  "threads": ["storylines or arguments that run through the chapter, one sentence each"]
}
Use only the notes provided. Do not invent anything."""

INDEX = """[TASK:book_index]
You are building the top-level index of a source from its chapter records.
Return ONLY this JSON object:
{
  "overview": "6-10 sentence overview of the whole source: what it is about, its arc, its main people and events",
  "themes": ["major theme", "..."],
  "threads": [{"title": "cross-chapter storyline or argument", "description": "one or two sentences", "chapter_idxs": [1, 4, 7]}]
}
chapter_idxs must be chapter numbers from the records given. Use only the information provided."""

DISCOVER = """[TASK:discover]
You are an editorial researcher looking for individual STORIES inside a source, from faithful chapter notes.
A story is a self-contained incident, a documented case study, a surprising fact with its explanation, a
complete sequence of decisions and consequences, or an event explained by several passages. One chapter may
hold several stories, and one story may span several chapters. Do not assume one chapter = one story.
Pick stories that a curious general audience would find compelling AND that the notes support with specifics.
Prefer concrete people, stakes, turning points and outcomes over general topics or summaries.
Every "story seed noticed" in the notes is a raw lead from the original reading: judge each one, and also look for events
in the notes that no seed mentions. Do not drop a concrete, specific event just because a broader theme exists.

nature (be strict, judge only from the notes):
- "story": a documented, specific event or sequence with named people or organisations, a time, a turning point AND an outcome.
- "anecdote": a brief real example or one-paragraph episode; it lacks a full arc.
- "explainer": teaches a concept, rule or method; examples are only illustrations.
- "hypothetical": an invented or imagined scenario ("suppose", "imagine"), not something that happened.

Return ONLY this JSON object:
{"candidates": [{
  "title": "working title",
  "premise": "one sentence",
  "why": "why this is a story worth telling and what makes it stand alone",
  "nature": "story | anecdote | explainer | hypothetical",
  "kind": "incident | multi_passage | multi_chapter | case_study | surprising_fact | decision_sequence",
  "potential": 7,
  "para_ids": [12, 13, 40]
}]}
Rules:
- para_ids list the passages that carry the story; use ONLY ids that appear in the notes (e.g. P12).
- potential is 0-10: how strong the story looks from these notes.
- Return at most {max_items} candidates; fewer is fine. If nothing qualifies return {"candidates": []}.
- These are research leads, not scripts: write no narration."""

DISCOVER_GLOBAL = """[TASK:discover_global]
You are an editorial researcher. Stories have already been found chapter by chapter (listed below), along with
the source's cross-chapter threads. Now look for ADDITIONAL stories that only emerge across several chapters or
sections: a decision in one place whose consequences land in another, a case explained by scattered passages,
a development that unfolds over the whole source. Do not repeat or lightly reword the existing stories.

Return ONLY this JSON object:
{"candidates": [{"title": "...", "premise": "one sentence", "why": "...", "nature": "story | anecdote | explainer | hypothetical", "kind": "multi_chapter | multi_passage | decision_sequence | case_study", "potential": 7, "para_ids": [12, 120, 340]}]}
Rules: use ONLY para ids appearing in the material below; at most {max_items} candidates; return
{"candidates": []} if there is nothing new. No narration or scripts.
Nature means: story = documented specific event with a turning point and outcome; anecdote = short real example;
explainer = teaches a concept; hypothetical = imagined scenario."""

DRAFT = """[TASK:draft_story]
You are writing an EDITORIAL RESEARCH RECORD (not a script) for one story found in a source.
Use ONLY the passages provided. Passages marked RAW are verbatim source text; lines under NOTES are
second-hand summaries of passages that did not fit. Do not add outside knowledge. Where the passages do not
support something, leave the field empty or list it under uncertainties. Never invent names, dates or numbers.

Return ONLY this JSON object:
{
  "title": "working title",
  "premise": "one sentence",
  "nature": "story | anecdote | explainer | hypothetical (judge from the passages: does a documented event with a turning point and an outcome actually appear?)",
  "arc": {"actor": "the specific person, company or group whose actions drive it, or empty", "decision": "what that actor chose or did, or empty", "consequence": "what happened because of it, beyond the mere price move, or empty", "form": "event = something that happened once to specific actors at a specific time; setup_example = a worked example of a repeatable pattern or trade setup; concept = teaches a rule"},
  "curiosity_question": "the central question that makes a reader want the answer",
  "opening_hook": "a possible opening line or situation (an idea, not narration)",
  "overview": "short factual overview, 5-9 sentences",
  "people": [{"name": "...", "role": "..."}],
  "chronology": [{"when": "date or period exactly as stated, or empty (never guess a year)", "when_basis": "stated | inferred", "what": "event", "basis": "quoted | summarised | inferred", "para_ids": [12]}],
  "conflict": "the central conflict or tension, or empty if the text does not support one",
  "stakes": "what was at stake, or empty",
  "turning_point": "the decisive moment, or empty",
  "outcome": "how it ended or what followed, or empty",
  "audience_interest": "why a general audience might care",
  "context_needed": ["background someone must know to follow the story"],
  "claims": [{"claim": "key factual claim", "basis": "quoted | summarised | inferred", "quote": "short EXACT quote (under 30 words) from a RAW passage that supports it, or empty", "para_ids": [12], "support": "strong | moderate | weak"}],
  "uncertainties": ["conflicting accounts, missing information, unverified claims"],
  "gaps": ["at most 3 important things a viewer would expect but the passages do not say: the outcome, the year, who the people were, why it happened. Skip exact prices and minor figures"],
  "title_flags": ["rare. Only when the title or key name is the same as a FAMOUS, different event or person a viewer would likely think of; write: <name> = <the famous thing>. Leave empty for ordinary company or product names"],
  "research_questions": ["what to check or find out next"],
  "scores": {
    "hook":       {"score": 0-10, "reason": "curiosity and hook potential"},
    "narrative":  {"score": 0-10, "reason": "does it progress: setup, escalation, turn, outcome"},
    "payoff":     {"score": 0-10, "reason": "revelation or explanatory payoff"},
    "emotion":    {"score": 0-10, "reason": "emotional relevance to a general audience"},
    "standalone": {"score": 0-10, "reason": "understandable without reading the rest of the source"}
  },
  "evidence": {"score": 0-10, "reason": "how well the passages support the claims: specific, sourced, corroborated vs. thin, hearsay, single-source or sensational"}
}
Rules:
- quote must be copied word for word from a RAW passage, or left empty. Never paraphrase inside quote.
- para_ids may only use ids shown with the passages.
- Never write paragraph labels such as [P12] inside any text field; only inside para_ids.
- basis: "quoted" = stated word for word in a RAW passage; "summarised" = the passages state it in other words; "inferred" = you connected or concluded it. When unsure choose "inferred".
- Do not fill gaps: if the passages do not state the outcome, a date or a name, leave the field empty and list it under gaps.
- Passages from far-apart pages joined into one chronology are not a documented sequence; say so in uncertainties.
- Score honestly. A dramatic story with thin support must get a LOW evidence score; do not inflate."""
