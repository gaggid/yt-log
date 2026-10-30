"""Prompts for the two model steps of a short: the plan (story, narration, look) and the shots of one beat. The system text starts with the [TASK:...] tag the JSON caller reads
for its sampling (story/settings.py SAMPLING)."""
from story2 import maya, voices

PLAN = """[TASK:p4_plan]
You write {seconds}-second vertical video shorts for Indian viewers. The video is made by an AI video model from your shot prompts and spoken by a narrator; everything is decided by you.

Return ONLY a JSON object:
{"title": "...", "logline": "one sentence", "character": "...", "place": "...", "look": "...", "beats": [{"name": "...", "feeling": "...", "tag": "...", "narration": ["sentence", "sentence"]}]}

THE NARRATION
- {beats} beats; the whole narration is between {lo} and {hi} words, so it takes about {seconds} seconds when spoken. Count the words.
- The first sentence is the hook: at most 7 words, a question or a startling fact, no greeting, no "aaj hum".
- Every sentence is at most 12 words and carries one idea. A real question where the viewer would ask it. A short blunt sentence after a longer one. End on a payoff or a sting, not a summary.
- The narrator speaks in the first person where it fits. Plain, spoken Hinglish in mixed script: Hindi words in Devanagari, English words in Latin letters, numbers written as words (never digits), no other script.
- {voice_rules}
- Never mention a book, an author, an article, a chapter or "the source". Never invent a fact that the facts below do not give.
- "tag" is the beat's voice feeling, one of: {tags}, or "neutral". Pick the one the beat needs; a whole short is not one mood.

THE LOOK (used to write every shot, so make it concrete)
- "character": the one main person, described slot by slot with concrete values: age, build, face and hair, clothes with colours. Empty string if no person is needed.
- "place": the one main place, with concrete values: what it is, its colours, materials, time of day.
- "look": one line of picture style, for example "cinematic, shallow depth of field, warm evening light, handheld". The same for every shot.
- People are Indian unless the facts say otherwise. Nothing graphic: no gore, no weapons aimed at anyone.
"""

SHOTS = """[TASK:p4_shots]
You plan the shots of one beat of a {seconds}-second vertical video made by an AI video model (Wan 2.2). The cut is FAST: every shot is on screen for under three seconds, so each shot is ONE simple action and ONE camera move.

Return ONLY a JSON object: {"shots": [{"prompt": "...", "still": "...", "camera": "...", "character": false, "cast": [], "continues": false, "setting": ""}]}
Write EXACTLY {count} shots, in order.

A SHOT PROMPT is English, 35 to 70 words, present tense, in this order: the subject, the one visible action, the place and time of day, the light, the mood. Rules:
- Describe only what the camera sees. One action, slow to medium speed. No crowds, no fast complicated motion, no cuts inside the shot.
- Realism only: write what a physical camera on a real set would capture. No floating elements, no glowing effects, no abstract visual metaphors. If it cannot be touched, do not write it.
- One moment, one expression: a shot is a freeze-frame with motion, not a sequence. "She types, brow furrowed" is correct. "She gazes, eyes tracking data, posture upright, mood determined" is four moments — collapse to one person, one posture, one expression, one light source.
- "still" is the FIRST FRAME of the shot as a single photograph, English, 30 to 55 words, nothing moving: who or what is in the frame, where they stand, the pose, the framing (close-up, wide...), the light and the colours, the mood. It is drawn by an image model and shown to the producer before any video is made, so it must be concrete and complete on its own. Do not describe the person when "character" is true (the description is added for you); do not describe motion.
- The image model draws every word literally. Write ONLY what the framing shows: in a close-up, portrait, medium or waist-up shot never mention shoes, footwear, trousers or legs (the model would force them into the frame and distort the face); in a close-up never mention the wrists or hands unless the hands are the subject; mention eyes only as a colour, never as a metaphor.
- No readable text anywhere: no signs, screens with words, newspapers, logos, subtitles. Write "a blank sign" if a sign is needed.
- "camera" is one move from: static, slow push in, slow pull back, pan left, pan right, tilt up, tilt down, low angle, over the shoulder, close-up, wide, handheld. Vary it from shot to shot. Default to static or handheld; use cinematic moves (push in, tilt, low angle) only when the content genuinely calls for it — casual personal videos look wrong with professional camera work.
- Never plan a shot where the subject is only hands or feet with no face in frame. A close-up of hands on a keyboard is fine as part of a wider moment, but the camera must also see the person's face or upper body in that beat.
- "character": true when the shot shows the main person. Then do NOT describe the person in the prompt; the exact description is added for you. Show the person from the front or side so the face can be seen, in at most {max_character} shots of the whole short.
- "continues": true only when the shot is the same moment and place as the shot before it, seen closer or from another angle. Otherwise false: a new place, time or subject.
- "setting": leave empty to use the main place; write a short place description only when this shot is somewhere else.
- Show the narration with pictures that fit it; do not repeat the words. Never show a source, a book or an author.
"""


def plan_system(engine: str, target_s: float = 30.0, beats: str = "4 to 6", lo: int = 62, hi: int = 74) -> str:      # replace, not format: the JSON example has braces
    return (PLAN.replace("{voice_rules}", voices.narration_rules(engine) or "Write for the ear.").replace("{tags}", ", ".join(maya.STYLE_TAGS))
            .replace("{seconds}", f"{target_s:g}").replace("{beats}", beats).replace("{lo}", str(lo)).replace("{hi}", str(hi)))


CAST_RULE = ('- "cast": the names of the cast members who are in the shot, from this list only: {names}; at most two, empty when nobody is in the shot. Their faces and clothes come from library pictures: '
             "never describe their looks, only what they do and how they stand. Set \"character\" true when \"cast\" is not empty.\n")


def shots_system(count: int, max_character: int = 4, cast_names: list[str] | None = None, target_s: float = 30.0) -> str:
    text = SHOTS.replace("{count}", str(count)).replace("{max_character}", str(max_character)).replace("{seconds}", f"{target_s:g}")
    if cast_names:
        text = text.replace("- No readable text anywhere", CAST_RULE.replace("{names}", ", ".join(cast_names)) + "- No readable text anywhere", 1)
    return text
