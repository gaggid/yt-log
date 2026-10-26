"""The feeling of a scene, as something a picture model can draw. The director plans an emotion for every part of the video and every scene has an
`emotional_effect`, but a picture model cannot draw a word like "dread": it draws what is written. So the feeling is turned into visible cues (what the face
and the body do, what the light does), and the cues the shot cannot show (a face seen from behind, a wide shot) are left out, like any other detail the frame
cannot see."""
import re

# label, words that select it, face, body, light. Order matters: the first row that matches wins. No vague words (see imgprompts.VAGUE) in the cues.
CUES: list[tuple[str, str, str, str, str]] = [
    ("fear", r"fear|dread|panic|terror|anxi|alarm|worr|nervous|unease|suspens|threat|danger", "eyes wide, brows pulled together, lips pressed tight",
     "shoulders drawn up, hands closed tight on something, body half turned away", "cold hard side light with deep shadow"),
    ("shock", r"shock|disbelief|stunn|surpris|astonish|stagger|bewilder", "eyes wide open, mouth slightly open, brows raised",
     "frozen mid-movement, one hand lifted halfway", "bright flat light and pale colours"),
    ("sorrow", r"sad|grief|loss|regret|sorrow|despair|heartbreak|mourn|defeat|ruin|devastat", "eyes lowered, brows tilted up in the middle, mouth turned down",
     "shoulders slumped, head bowed, hands hanging loose", "dim desaturated light from a window"),
    ("anger", r"anger|rage|furi|outrage|frustrat|injustice|betray|resent|indign", "jaw clenched, brows low and drawn together, a hard stare",
     "chest forward, fists closed", "warm hard light with red tones and dark edges"),
    ("joy", r"joy|relief|triumph|happy|delight|celebrat|pride|elat|victory|win|success", "a broad open smile, bright eyes",
     "shoulders loose, arms open", "warm golden soft light"),
    ("hope", r"hope|curios|wonder|determin|resolve|anticipat|inspir|ambition|optimis", "eyes lifted and focused ahead, a faint steady smile",
     "upright, leaning slightly forward", "soft warm light from the front and clear air"),
    ("unease", r"guilt|shame|embarrass|doubt|uncertain|hesitat|conflict|suspici|confus", "eyes cast aside, a tight half-smile, brows slightly raised",
     "arms crossed or a hand at the neck, weight shifted back", "uneven light with half of the face in shadow"),
    ("loneliness", r"alone|lonel|isolat|empty|abandon|silence|quiet", "a blank distant stare",
     "small in the frame, completely still", "cool dim light with a large empty space around the person"),
    ("urgency", r"urgen|rush|hurry|race|deadline|chase|desperat|pressure|frantic|scrambl", "eyes fixed on one point, mouth set, a sheen of sweat",
     "mid-stride, leaning forward, hands busy", "hard overhead light with long shadows"),
]
FACE = {"face", "eyes", "expression"}


def label(texts: list[str]) -> str:
    """The feeling named by the first text that matches a row (the scene's own phrase first, then the director's emotion for its part). "" for calm or unknown."""
    for t in texts:
        t = (t or "").lower()
        for lab, rx, *_ in CUES:
            if re.search(rx, t):
                return lab
    return ""


def line(texts: list[str], hide: set[str] | frozenset = frozenset(), people: bool = True) -> str:
    """One sentence for the prompt, or "" when there is no feeling to show. Face cues are dropped when the face is hidden or there is no person; the light always stays."""
    lab = label(texts)
    if not lab:
        return ""
    _l, _rx, face, body, light = next(c for c in CUES if c[0] == lab)
    cues = []
    if people and "expression" not in hide:
        cues.append(face)
    if people:
        cues.append(body)
    cues.append(light)
    return f"Feeling of the moment: {lab}. Show it with {', '.join(cues)}."
