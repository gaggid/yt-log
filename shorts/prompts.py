"""Prompts for the two model steps of a short: the plan (story, narration, look) and the shots of one beat. The system text starts with the [TASK:...] tag the JSON caller reads
for its sampling (story/settings.py SAMPLING)."""
from story2 import maya, voices

from . import formats, languages

PLAN = """[TASK:p4_plan]
You write {seconds}-second vertical video shorts for Indian viewers. The video is made by an AI video model from your shot prompts and spoken by a narrator; everything is decided by you.

Return ONLY a JSON object:
{"title": "...", "logline": "one sentence", "format": "...", "subjects": [{"name": "...", "kind": "...", "visual": "..."}], "character": "...", "place": "...", "look": "...", "beats": [{"name": "...", "feeling": "...", "tag": "...", "narration": ["sentence", "sentence"]}]}

THE FORMAT
{format_section}

THE SUBJECTS (what the facts are about, so the pictures show the right things)
- "subjects": at most 6, the most important first: every named or distinct person, group or force, machine or vehicle, organisation, place, product or program the facts are about, from every side of the story.
  "name" is the exact name the facts use, with its common short form (for example "Chinese J-20 stealth fighter"). "kind" is person, group, machine, organisation, place, product, software or other.
- "visual" is English, 20 to 45 words: one concrete description an image model can draw without knowing the story: shape, size, colours, markings, insignia, clothing, materials, where it is usually seen.
  Make each side look like itself, and EVERY machine or person must say whose it is by what can be seen: national roundels and flag colours on aircraft and vehicles, uniforms, a software window by its layout and theme. Real machines and people are drawn as they really look. No readable text in it.
- When the facts name only a class (for example "Chinese stealth fighters"), name the best-known real example in the subject for the pictures, such as "Chinese stealth fighter (J-20)", and describe that real machine; the narration still says only what the facts say.
- Prefer what can be SEEN: list machines, people, places and products rather than a bare organisation or force; do not list the same thing twice.
- Never drop a subject the facts name; the narration and the shots must keep them by name.

THE NARRATION
- {beats} beats; the whole narration is between {lo} and {hi} words, so it takes about {seconds} seconds when spoken. Count the words.
- The first sentence is the hook: at most 7 words, a question or a startling fact, no greeting, no "aaj hum".
- Every sentence is at most 12 words and carries one idea. A real question where the viewer would ask it. A short blunt sentence after a longer one. End on a payoff or a sting, not a summary.
- The narrator speaks in the first person where it fits. {language_rule}
- {voice_rules}
- Never mention a book, an author, an article, a chapter or "the source". Never invent a fact that the facts below do not give.
- "tag": always "neutral". The producer sets voice emotion by hand later.

THE LOOK (used to write every shot, so make it concrete)
- "character": the one main person, described slot by slot with concrete values: age, build, face and hair, clothes with colours. Empty string if no person is needed, and ALWAYS empty unless the format is "story": do not invent a person for a documentary, an explainer or a comparison.
- "place": the one main place, with concrete values: what it is, its colours, materials, time of day.
- "look": one line of picture style, for example "cinematic, shallow depth of field, warm evening light, handheld". The same for every shot.
- People are Indian unless the facts say otherwise. Nothing graphic: no gore, no weapons aimed at anyone.
"""

SHOTS = """[TASK:p4_shots]
You plan the shots of one beat of a {seconds}-second vertical video made by an AI video model (Wan 2.2). The cut is FAST: every shot is on screen for under three seconds, so each shot is ONE simple action and ONE camera move.

Return ONLY a JSON object: {"shots": [{"prompt": "...", "still": "...", "camera": "...", "character": false, "cast": [], "subjects": [], "continues": false, "setting": ""}]}
Write EXACTLY {count} shots, in order.

A SHOT PROMPT is English, 35 to 70 words, present tense, in this order: the subject, the one visible action, the place and time of day, the light, the mood. Rules:
- Describe only what the camera sees. One action, slow to medium speed. No crowds, no fast complicated motion, no cuts inside the shot.
- Realism only: write what a physical camera on a real set would capture. No floating elements, no glowing effects, no abstract visual metaphors. If it cannot be touched, do not write it.
- One moment, one expression: a shot is a freeze-frame with motion, not a sequence. "She types, brow furrowed" is correct. "She gazes, eyes tracking data, posture upright, mood determined" is four moments — collapse to one person, one posture, one expression, one light source.
- "still" is the FIRST FRAME of the shot as a single photograph, English, 30 to 55 words, nothing moving: who or what is in the frame, where they stand, the pose, the framing (close-up, wide...), the light and the mood. Do not describe the person when "character" is true (the description is added for you); never mention their clothes, outfit, colours or accessories — those come from the reference picture. Do not describe motion.
- The image model draws every word literally. Write ONLY what the framing shows: in a close-up, portrait, medium or waist-up shot never mention shoes, footwear, trousers or legs (the model would force them into the frame and distort the face); in a close-up never mention the wrists or hands unless the hands are the subject; mention eyes only as a colour, never as a metaphor.
- No readable text anywhere: no signs, screens with words, newspapers, logos, subtitles. Write "a blank sign" if a sign is needed.
- "camera" is one move from: static, slow push in, slow pull back, pan left, pan right, tilt up, tilt down, low angle, over the shoulder, close-up, wide, handheld. Vary it from shot to shot. Default to static or handheld; use cinematic moves (push in, tilt, low angle) only when the content genuinely calls for it — casual personal videos look wrong with professional camera work.
- Never plan a shot where the subject is only hands or feet with no face in frame. A close-up of hands on a keyboard is fine as part of a wider moment, but the camera must also see the person's face or upper body in that beat.
- "character": true when the shot shows the main person. Then do NOT describe the person in the prompt; the exact description is added for you. Show the person from the front or side so the face can be seen, in at most {max_character} shots of the whole short.
- {format_rule}
- {subject_rule}
- "continues": true only when the shot is the same moment and place as the shot before it, seen closer or from another angle. Otherwise false: a new place, time or subject.
- "setting": leave empty to use the main place; write a short place description only when this shot is somewhere else.
- Show the narration with pictures that fit it; do not repeat the words. Never show a source, a book or an author.
"""


def plan_system(engine: str, target_s: float = 30.0, beats: str = "4 to 6", lo: int = 62, hi: int = 74, format_choice: str = "auto", language_rule: str = "") -> str:      # replace, not format: the JSON example has braces
    return (PLAN.replace("{format_section}", formats.plan_section(format_choice)).replace("{voice_rules}", voices.narration_rules(engine) or "Write for the ear.").replace("{tags}", ", ".join(maya.STYLE_TAGS)).replace("{language_rule}", language_rule or languages.HINGLISH_RULE)
            .replace("{seconds}", f"{target_s:g}").replace("{beats}", beats).replace("{lo}", str(lo)).replace("{hi}", str(hi)))


CAST_RULE = ('- "cast": the names of the cast members who are in the shot, from this list only: {names}; at most two, empty when nobody is in the shot. Their faces and clothes come from library pictures: '
             "never describe their looks, only what they do and how they stand. Set \"character\" true when \"cast\" is not empty.\n")


SUBJECT_RULE = ('"subjects": the exact names (from THE SUBJECTS) of the subjects this shot shows, empty when it shows none. Name the exact subject in "prompt" and "still", never a generic one: write "a Chinese J-20 stealth fighter" '
                'or "an Indian Air Force Su-30MKI", not "a fighter jet". Their looks are added for you; do not repeat them. Keep every side of the story on screen over the whole short.')
NO_SUBJECT_RULE = '"subjects": leave empty (this short has no subject list).'


def shots_system(count: int, max_character: int = 4, cast_names: list[str] | None = None, target_s: float = 30.0, format_id: str = "story", has_subjects: bool = False) -> str:
    text = (SHOTS.replace("{count}", str(count)).replace("{max_character}", str(max_character)).replace("{seconds}", f"{target_s:g}")
            .replace("{format_rule}", f"Format {format_id}: " + formats.shot_rule(format_id) + ("" if formats.allows_character(format_id) or cast_names else ' There is no invented main person: set "character" false in every shot.'))
            .replace("{subject_rule}", SUBJECT_RULE if has_subjects else NO_SUBJECT_RULE))
    if cast_names:
        text = text.replace("- No readable text anywhere", CAST_RULE.replace("{names}", ", ".join(cast_names)) + "- No readable text anywhere", 1)
    return text
