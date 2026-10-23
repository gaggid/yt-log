"""Phase 2 prompts. Tagged [TASK:name] like Phase 1 so test doubles can route them."""

BLUEPRINT = """[TASK:p2_blueprint]
You are a story editor planning a long-form YouTube video (16:9) that tells ONE true story to a general Indian audience.
You receive the facts of the story. Plan the telling; do not write the narration yet.

Choose the structure that fits THIS story. Do not force suspense onto a story that does not have it.
Structures: cold_open (striking moment first, then context, escalation, reveal, consequence) | mystery (clues, competing
explanations, resolution) | decision_consequence (a decision, what followed, recovery, outcome) | problem_mechanism
(a problem, how it works, an example, what it means) | myth_correction (belief, evidence, correction) | multi_case
(several cases, the pattern that connects them, takeaway) | question_journey (a question that is answered step by step).

Return ONLY this JSON object:
{
  "structure": "one of the structure names above",
  "why_structure": "one sentence: why this fits this story",
  "viewer_promise": "what the viewer will get from watching, stated honestly",
  "central_question": "the question that keeps the viewer watching, or empty",
  "opening": "how it opens", "context": "what the viewer must know first", "conflict": "the tension",
  "turning_point": "the decisive moment", "payoff": "what is revealed or understood", "ending": "how it closes",
  "beats": [{"id": "b1", "name": "opening", "purpose": "why this beat exists", "takeaway": "what the viewer understands or feels after it", "facts": ["fact used, in plain words"]}]
}
Rules:
- 5 to 9 beats, in telling order. Every beat has a purpose and uses only facts you were given.
- Use only the facts given. If something is not known (an outcome, a year, a name) leave it out of the plan; never fill it in.
- Everything is our own telling. Never mention a book, an author, a chapter, a page, a source or "the text"."""

NARRATE = """[TASK:p2_narrate]
You write the spoken narration (in Hindi, Devanagari script) for a long-form video, from a story blueprint and its facts.
The narrator speaks in FIRST PERSON, a guide the viewer follows: "मैं" and "हम". The narrator name is {narrator}.

First-person rules:
- Use "मैं" naturally at least three times across the narration: once early, once as a reaction in the middle, once near the end.
- "मैं" guides, reacts and thinks aloud ("चलिए मैं आपको दिखाता हूँ", "यहाँ मुझे सबसे ज़्यादा हैरानी हुई"). Use the masculine form unless told otherwise.
- The narrator was NOT there. Never say "मैंने देखा", "मैं वहाँ था" or invent personal experience. Events are told as things that happened.

Language rules:
- Natural, conversational Indian Hindi in Devanagari, the way a good storyteller speaks. Short sentences. No stiff textbook Hindi.
  Common English words (market, stock, trader, gap) may be written in Devanagari (मार्केट, स्टॉक) as people say them.
- Company and person names are written in Devanagari as they are pronounced (नाइट कैपिटल). List unusual ones under "pronounce".
- Write numbers in words when they are spoken (साढ़े सात करोड़ डॉलर, पैंतालीस मिनट).
- Use only Devanagari letters. No Latin letters, no digits, no letters from any other script, not even inside a word.
- Do not use quotation marks, brackets, stage directions, scene descriptions, citations or speaker labels in the spoken text.

Originality rules (very important):
- This is OUR telling. Never mention or hint at a book, author, chapter, page, publisher, "the text", "according to", or any source.
- Do not reproduce sentences from the facts you were given. Retell in fresh words and your own structure.
- Do not quote anyone. No quotation marks. Tell what people did and said in your own words.
- Use only the facts given. If a year, a number, an outcome or a name is not given, do not state it; speak around it honestly.

Emotion: every sentence has one emotion from: neutral, happy, sad, anger, fear, clear.
- "clear" is for precise, technical or numeric sentences and unfamiliar names. "neutral" is the default.
- Choose the emotion the MOMENT needs, not the loudest one. Quiet and neutral moments are normal; do not make everything intense.
- A moment of uncertainty or explanation is usually neutral or clear, not fear.
- pause_after_s: 0 for most sentences; 0.4 to 1.2 after a reveal or before a turn; never more than 2.

Return ONLY this JSON object:
{"segments": [{
  "beat": "the beat id this segment tells",
  "sentences": [{"text": "one spoken sentence in Devanagari", "emotion": "neutral", "pause_after_s": 0}],
  "emphasis": ["words to stress"],
  "pronounce": [{"word": "नाइट कैपिटल", "say": "Knight Capital", "note": "company name"}],
  "facts_used": ["which facts this segment uses, in plain words"]
}]}
One segment per beat (a long beat may use two). Target about {minutes} minutes of speech: roughly {words} words in total, so
each segment needs about {per_beat} words (at least {min_beat}). Do not rush a beat into two sentences; give the viewer time to follow.
The first segment must hook honestly with something true from the story. The last must land the ending of the blueprint."""


REGISTRY = """[TASK:p2_registry]
You are a visual continuity supervisor for a long-form 16:9 explainer video about ONE true story.
List the recurring visual assets the video needs so every scene looks like the same film: people (as roles), places, key
props, and one overall visual style. Do not write scenes.

Return ONLY this JSON object:
{"assets": [{
  "name": "short unique name, e.g. 'the trader', 'trading floor', 'style'",
  "kind": "person | place | prop | style",
  "description": "approved visual attributes: for a person age range, build, clothing for the period, posture; for a place architecture, materials, light; for a style the look in concrete terms (film stock or illustration technique, palette, contrast, grain)",
  "fixed": ["attributes that must stay identical in every scene"],
  "flexible": ["attributes that may change between scenes"],
  "period": "time period if known, otherwise empty",
  "fictionalisation": "generic_reconstruction | source_supported | real_person_no_likeness | fictional",
  "evidence_note": "what in the story supports this asset, in plain words, or 'creative choice'"
}]}
Rules:
- Exactly one "style" asset: the visual language of the whole video.
- People are roles ("the trader", "the analyst"), not real faces. A real, named person is NEVER given an invented face presented
  as a real likeness: use kind person with fictionalisation real_person_no_likeness (shown from behind, as a silhouette, hands,
  or an anonymous figure). Invented generic people are generic_reconstruction.
- Only describe appearance that the story supports or that you clearly mark as a creative choice. Do not invent facts.
- Keep it small: 3 to 8 assets in total.
- Never mention a book, an author, a chapter, a page or a source."""

SCENES = """[TASK:p2_scenes]
You are a storyboard artist for a long-form 16:9 explainer video. You receive one narration segment, its numbered sentences
(with their spoken seconds), the story facts and the continuity assets. Design the scenes that show this segment.

Each scene covers a run of consecutive sentences ("sentences": [first, last], 1-based, inclusive). Together the scenes must
cover EVERY sentence of the segment exactly once, in order, with no gaps and no overlaps. A scene usually lasts 4 to 12
seconds; a long reveal may hold longer; do not cut faster than the viewer can understand.

For every scene answer: what does the viewer learn, notice or feel from this picture that the previous picture did not give?
Do not repeat a keyword from the narration as a generic picture. Vary the visual type and composition between neighbouring scenes.

Visual types: reconstruction | establishing | character | metaphor | object_process | montage | map_timeline | data_chart |
document_archival | screen_interface | diagram | comparison | text_led | minimalist | atmospheric | transition.
Charts, documents, screens, maps and diagrams cannot be drawn reliably by an image model and must never show invented numbers,
text or quotes: use that visual type, describe in "needs_asset" what verified content it must show (only numbers and events given
in the facts), and give a "fallback" picture an image model can make instead (for example the setting around the screen).

Vary the camera. Distances: extreme wide | wide | medium | close | extreme close. Angles: eye level | high | low | overhead | side.
No two neighbouring scenes may share the same distance AND angle, and do not use "medium, eye level" more than once in three scenes.
Describe only what is VISIBLE, in concrete words. Say who or what, how many, where in the frame (left, centre, right), what they
are doing at this exact instant, camera angle and distance, light and its direction, colours. No vague words like "dramatic",
"tense" or "epic": say which visible details create that effect. One clear focal point per scene.
People are anonymous figures (role, clothing, posture), seen from behind, in silhouette, or as hands, unless the continuity asset
says otherwise. No logos, no readable brand text, no invented text. On-screen text only when essential, 8 words at most.

Return ONLY this JSON object:
{"scenes": [{
  "sentences": [1, 2],
  "purpose": "why this scene exists in the story",
  "new_information": "what is new for the viewer compared with the previous scene",
  "takeaway": "what the viewer understands or feels after it",
  "emotional_effect": "the intended feeling, one short phrase",
  "visual_type": "one of the types above",
  "subject": "the main subject, precisely",
  "action": "the exact visible action at this instant",
  "location": "where", "period": "when, only if known",
  "props": ["objects that must be visible"],
  "composition": {"position": "where the subject sits in the frame", "left": "", "centre": "", "right": "", "camera_angle": "", "distance": "", "perspective": "", "framing": ""},
  "lighting": "source, direction, softness, contrast, time of day",
  "palette": "main colours", "atmosphere": "air, weather, haze, mood in visible terms", "style": "the treatment, matching the style asset",
  "foreground": "", "middle": "", "background": "",
  "motion_intent": "how it could move later (slow push in, pan, static hold)",
  "text_on_screen": [{"text": "exact words", "placement": "where"}],
  "assets": ["names of continuity assets used"],
  "fixed_by_facts": ["visual details that come from the story's facts"],
  "creative_choices": ["details that are our creative decisions"],
  "exclusions": ["things that must not appear"],
  "needs_asset": "", "fallback": ""
}]}
Never mention a book, an author, a chapter, a page or a source. Use only facts given; do not invent names, numbers or outcomes."""
