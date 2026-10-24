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
You write the spoken narration (in Hinglish: Hindi with English words, the way urban India talks) for a long-form video, from a story blueprint and its facts.
The narrator speaks in FIRST PERSON, a guide the viewer follows: "मैं" and "हम". The narrator name is {narrator}.

First-person rules:
- Use "मैं" naturally at least three times across the narration: once early, once as a reaction in the middle, once near the end.
- "मैं" guides, reacts and thinks aloud ("चलिए मैं आपको दिखाता हूँ", "यहाँ मुझे सबसे ज़्यादा हैरानी हुई"). Use the masculine form unless told otherwise.
- The narrator was NOT there. Never say "मैंने देखा", "मैं वहाँ था" or invent personal experience. Events are told as things that happened.

Language rules:
- Natural, conversational Hinglish, the way a good storyteller speaks. Short sentences. No stiff textbook Hindi.
- Hindi grammar and Hindi words are written in Devanagari. English words and terms are written in Latin script, exactly as spelled in English:
  story, stock, perfect, earnings release, trend, technical analysis, EMA support. Prefer the English word wherever a person would say it in English
  (market, stock, trader, profit, loss, chart, deal). Do not invent stiff Hindi for them and do not write them in Devanagari.
- Company and person names are written in Latin script as normally spelled (Knight Capital Group). List unusual ones under "pronounce".
- Always put a space between an English word and the Hindi word next to it: "stock को", never "stockको". One word never mixes the two scripts.
- Write numbers and years as words, never digits. Use English number words beside English terms ("January two thousand seven में", "seventeen percent",
  "fifty day EMA support") and Hindi number words otherwise (साढ़े सात करोड़ रुपये).
- Use only Devanagari and Latin letters. No digits, no symbols such as % or $, no letters from any other script.
- Do not use quotation marks, brackets, stage directions, scene descriptions, citations or speaker labels in the spoken text.

Originality rules (very important):
- This is OUR telling. Never mention or hint at a book, author, chapter, page, publisher, "the text", "according to", or any source.
- Do not reproduce sentences from the facts you were given. Retell in fresh words and your own structure.
- Do not quote anyone. No quotation marks. Tell what people did and said in your own words.
- Use only the facts given. If a year, a number, an outcome or a name is not given, do not state it; speak around it honestly.

Emotion: every sentence has one emotion from: neutral, happy, sad, anger, fear, clear.
- "clear" is for precise, technical or numeric sentences and unfamiliar names. "neutral" is the default.
- Choose the emotion the MOMENT needs, not the loudest one. Quiet and neutral moments are normal; do not make everything intense.
- Keep ONE emotion through a segment. Switching mid-segment changes the voice and pace audibly. Change it at most once, and only at a real turn.
- A moment of uncertainty or explanation is usually neutral or clear, not fear.
- pause_after_s: 0 for most sentences; 0.4 to 1.2 after a reveal or before a turn; never more than 2.

Return ONLY this JSON object:
{"segments": [{
  "beat": "the beat id this segment tells",
  "sentences": [{"text": "one spoken sentence in Hinglish (Devanagari + Latin words)", "emotion": "neutral", "pause_after_s": 0}],
  "emphasis": ["words to stress"],
  "pronounce": [{"word": "Knight Capital Group", "say": "नाइट कैपिटल ग्रुप", "note": "company name"}],
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
  "appearance": {"one key per slot, every slot filled, see SLOTS below": "a concrete value"},
  "description": "one sentence summary (it is rebuilt from appearance)",
  "fixed": ["attributes that must stay identical in every scene"],
  "flexible": ["attributes that may change between scenes"],
  "period": "time period if known, otherwise empty",
  "fictionalisation": "generic_reconstruction | source_supported | real_person_no_likeness | fictional",
  "evidence_note": "what in the story supports this asset, in plain words, or 'creative choice'"
}]}
SLOTS (fill every one, with concrete values; the picture model draws exactly what is written and invents whatever is missing):
- person: gender (man, woman, boy, girl) | age (a number of years) | build (height and build) | skin (skin tone) | face (face shape, distinctive features) |
  hair (colour, length, style) | eyes (colour) | top (upper clothing and its colour) | bottom (lower clothing and its colour) | footwear (shoes and colour) |
  accessories (watch, glasses, bag, jewellery, or the word none) | expression (usual expression)
- place: type | architecture (structure and layout) | materials (main materials and their colours) | light (sources, direction, time of day) |
  objects (key furniture and objects, with counts) | size (size and how crowded)
- prop: type | shape (shape and size) | material | colour (exact colours) | condition (new, worn, damaged) | markings (lettering or marks, or the word none)
Write colours as colours ("navy blue", "charcoal grey"), materials as materials ("brushed steel", "worn oak"), numbers as numbers. Never write
"nice", "typical", "generic", "casual", "business attire", "various", "etc" or "and so on": say which items, which colours, how many.
Rules:
- Exactly one "style" asset: the visual language of the whole video.
- The video is a story told through hand-illustrated pictures of things that could really have happened. Assets are what an
  illustrator needs to draw the same world again and again.
- People are invented composite characters, named by role ("the trader", "the analyst"). Give each an age range, build, face and
  hair, clothing right for the period and one distinctive item, so the same person can be drawn in every scene. Invented people are
  generic_reconstruction. A real, named person is NEVER given an invented likeness: use kind person with fictionalisation
  real_person_no_likeness (shown as a silhouette, from behind, in shadow or by the hands only).
- Places are real-feeling settings where the story happens (a trading floor, a small office, a street at dusk): architecture,
  materials, light, typical objects. Props are physical things people use or hold (a desk phone, a wall of monitors, a printed
  report). Never list a chart, graph, diagram or document as an asset.
- Only describe appearance that the story supports or that you clearly mark as a creative choice. Do not invent facts.
- Read the whole NARRATION. Every person or role it mentions or clearly implies, every place it is set in and every object that matters
  to the story must be an asset, so no scene ever needs something that is missing from this list. Include secondary people
  (a colleague, a manager, a customer, a crowd member who appears) when the narration needs them. Merge duplicates.
- Keep it complete but small: 4 to 12 assets in total.
- Never mention a book, an author, a chapter, a page or a source."""

SCENES = """[TASK:p2_scenes]
You are a storyboard artist for a long-form 16:9 explainer video. You receive one narration segment, its numbered sentences
(with their spoken seconds), the story facts and the continuity assets. Design the scenes that show this segment.

Each scene covers a run of consecutive sentences ("sentences": [first, last], 1-based, inclusive). Together the scenes must
cover EVERY sentence of the segment exactly once, in order, with no gaps and no overlaps. A scene usually lasts 4 to 12
seconds; a long reveal may hold longer; do not cut faster than the viewer can understand.

For every scene answer: what does the viewer learn, notice or feel from this picture that the previous picture did not give?
Do not repeat a keyword from the narration as a generic picture. Vary the visual type and composition between neighbouring scenes.

TELL THE STORY WITH PICTURES. The video is a graphic novel: every scene is an illustrated moment of the story world, drawn like a
panel. Show people, places and things happening: who is there, where, doing what, feeling what. Prefer these visual types:
reconstruction (a moment that happened or could have happened) | character (a person's face, hands or posture) | establishing
(the place, wide) | atmospheric (the mood of a place) | object_process (a thing being used) | montage | transition.
Use at least four in five scenes from this list. Use "metaphor" rarely, and only as an image inside the story world (a lit window
in a dark street, a hand hovering over a phone). Never invent unrelated symbols such as a runner, a train, a pillar, a bridge,
a mountain or a ship: every object and person in a picture must belong to the places and people of the story.
Do not turn an idea into a diagram. If the narration talks about momentum, pressure or a drop, show a person living it (a trader
leaning toward his screens, a hand over a phone, a street in rain) instead of a chart.
Charts, documents, screens, maps and diagrams (visual types data_chart | document_archival | screen_interface | map_timeline |
diagram | comparison | text_led) are allowed only when the narration states exact numbers, dates or a document that the viewer must
read, and then in at most one scene in six. They cannot be drawn reliably by an image model and must never show invented numbers,
text or quotes: describe in "needs_asset" what verified content it must show (only numbers and events given in the facts), and
make the "fallback" a full illustrated scene in the story world (for example a trader at a wall of glowing monitors; the screens
show abstract light only). Elsewhere, a chart may appear only as a glowing, unreadable shape on a screen inside a room.
Panel language to use: an establishing wide of the place, over-the-shoulder, a close-up on eyes or hands, a low angle that gives
a person weight, a high angle that makes someone small, a silhouette against a lit window, a foreground object framing the
subject. Give every scene depth: something in the foreground, the subject, something behind.

Vary the camera. Distances: extreme wide | wide | medium | close | extreme close. Angles: eye level | high | low | overhead | side.
No two neighbouring scenes may share the same distance AND angle, and do not use "medium, eye level" more than once in three scenes.
Describe only what is VISIBLE, in concrete words. Say who or what, how many, where in the frame (left, centre, right), what they
are doing at this exact instant, camera angle and distance, light and its direction, colours. No vague words like "dramatic",
"tense" or "epic": say which visible details create that effect. One clear focal point per scene.
People are the continuity characters, drawn with faces and clear emotion (what the face and body show), using the same names as the
assets. A real, named person is shown only as a silhouette, from behind, in shadow or by the hands. Clothing, devices and rooms
must fit the period. No logos and no brand text. On-screen text is allowed and the picture models draw it correctly when it is short and
quoted: a headline, a sign, a label, a big number on a screen (for example "STOCK FALLS 17%"). Rules for it: English letters only (never
Hindi on screen), 8 words at most per text, only words and numbers that are in the story facts, never a quotation from a book or person.
Screens and papers without such text show abstract light or marks only.

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
