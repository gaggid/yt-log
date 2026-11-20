"""YouTube search text for a rain video, assembled in code from the theme, the length and the music.

What this relies on (YouTube publishes no ranking formula; these are its own creator guidance and long-standing practice):
  - the words people type come first in the title ("rain sounds for sleeping", the length), the theme's place makes every title different;
  - the first ~150 characters of the description are what search results show, so they carry the same keywords in plain words;
  - only the first three hashtags are shown above the title, and more than 15 make YouTube ignore all of them: three are used;
  - tags matter little; they hold the exact phrases and common misspellings, the main phrase first, under 450 characters;
  - everything must be true of the video (no fake chapters, no claims about health); the scene and the music are AI-made and the description says so.
The model only writes two plain sentences about the scene (publish.py); the rest never depends on a model, so it never drifts or repeats a stock opener."""
import hashlib

from . import models as M

TITLE_MAX = 70

# how each theme is named in a title and a description
PLACES: dict[str, dict] = {
    "night_city": {"place": "a Japanese Rain Garden", "short": "a Japanese Garden", "words": ["japanese garden rain", "zen garden rain"]},
    "mountain_forest": {"place": "a Nordic Forest Cabin", "short": "a Forest Cabin", "words": ["cabin rain sounds", "forest rain"]},
    "ocean": {"place": "a Bali Jungle Villa", "short": "a Bali Villa", "words": ["bali rain sounds", "tropical rain"]},
    "countryside": {"place": "an Alpine Mountain Chalet", "short": "an Alpine Chalet", "words": ["alpine rain", "chalet rain sounds"]},
    "forest": {"place": "a Glass Treehouse in the Rainforest", "short": "a Rainforest Treehouse", "words": ["treehouse rain", "rainforest rain sounds"]},
    "himalayan_ridge": {"place": "a Himalayan Mountain Lodge", "short": "a Himalayan Lodge", "words": ["himalayan rain", "mountain lodge rain"]},
    "monastery_window": {"place": "a Mountain Monastery", "short": "a Monastery", "words": ["monastery rain", "himalayan monastery"]},
    "courtyard": {"place": "a Peaceful Courtyard", "short": "a Courtyard", "words": ["courtyard rain", "rain on roof tiles"]},
    "old_town_lane": {"place": "a Cobblestone Old Town Street", "short": "an Old Town Street", "words": ["old town rain", "rain on cobblestone"]},
    "kerala_veranda": {"place": "a Kerala Monsoon Veranda", "short": "a Kerala Veranda", "words": ["monsoon rain sounds", "kerala rain"]},
    "lakeside_porch": {"place": "a Misty Lake Cabin", "short": "a Lake Cabin", "words": ["lake rain sounds", "rain on lake"]},
    "bamboo_teahouse": {"place": "a Bamboo Tea House", "short": "a Tea House", "words": ["bamboo rain sounds", "japanese tea house rain"]},
}
TAILS = ["Deep Sleep", "Sleep & Study", "Relax & Focus"]
HASHTAGS = ["#RainSounds", "#SleepMusic", "#RelaxingRain"]          # three: only the first three are shown, more than 15 are all ignored
BASE_TAGS = ["rain sounds", "rain sounds for sleeping", "rain sounds for sleep", "sleep sounds", "relaxing rain",
             "ambient rain", "rain ambience", "rain and soft music", "sleep music", "study music", "white noise",
             "cozy rain", "nature sounds", "ASMR rain"]


def _pick(seed_text: str, n: int) -> int:
    return int(hashlib.sha1(seed_text.encode()).hexdigest()[:8], 16) % n


def place_of(scene: str, short: bool = False) -> str:
    p = PLACES.get(scene) or {"place": "a Cozy Room", "short": "a Cozy Room", "words": []}
    return p["short" if short else "place"]


def title(scene: str, length: str, key: str = "") -> str:
    """Title: the length and the main phrase first, a place that differs by theme, a use at the end. Up to TITLE_MAX characters."""
    L = length.title()
    n = _pick(key or scene, len(TAILS) * 3)
    tails = TAILS[n % len(TAILS):] + TAILS[:n % len(TAILS)]
    pattern = n // len(TAILS)
    for short in (False, True):
        place = place_of(scene, short)
        for tail in tails:
            cands = [f"{L} Rain Sounds at {place} | {tail}",
                     f"Rain Sounds for Sleeping | {L} at {place}",
                     f"{L} Rain Ambience at {place} | {tail}"]
            cands = cands[pattern:] + cands[:pattern]
            for c in cands:
                if len(c) <= TITLE_MAX:
                    return c
    return f"{L} Rain Sounds | {tails[0]}"[:TITLE_MAX]


def tags(scene: str, instrument: str = "") -> list[str]:
    words = list((PLACES.get(scene) or {}).get("words", []))
    out = []
    for t in [BASE_TAGS[0], BASE_TAGS[1], *words, *BASE_TAGS[2:]] + ([f"{instrument} and rain"] if instrument else []):
        if t.lower() not in [x.lower() for x in out]:
            out.append(t)
    keep, total = [], 0
    for t in out:
        total += len(t) + 1
        if total > 450 or len(keep) >= 15:
            break
        keep.append(t)
    return keep


def scene_text(scene: str, instrument: str) -> str:
    """Two plain true sentences, used when the model does not write its own."""
    place = place_of(scene)
    return (f"Rain falls steadily at {place}, seen from inside. "
            f"Soft {instrument or 'piano'} drifts gently under the sound of the rain.")


def description(scene: str, length: str, instrument: str, scene_paragraph: str = "") -> str:
    place = place_of(scene)
    hook = f"{length} of calming rain sounds at {place}, with soft {instrument or 'piano'} for deep sleep, study and relaxation."
    para = (scene_paragraph or "").strip() or scene_text(scene, instrument)
    return "\n\n".join([
        hook,
        para,
        "Use it for: falling asleep, studying, reading, working, meditation or simply a quiet room.",
        "Subscribe for a new rain video three times a week. What are you doing while it rains?",
        " ".join(HASHTAGS),
    ])[:4800]


# ── text that follows the video's angle (who it is for, when, where, why), relaxation/looks.py ANGLES ───────────────────────────────────────────
ANGLE_HASHTAGS = {"sleep": "#SleepMusic", "study": "#StudyMusic", "work": "#FocusMusic", "read": "#ReadingMusic", "calm": "#RelaxingMusic", "noise": "#WhiteNoise",
                  "meditate": "#MeditationMusic", "rainy": "#CozyRain", "late": "#LateNightMusic"}
HOW_POOL = ["keep the volume low, just above the sound of the room", "set the sleep timer in the YouTube app if you want it to stop on its own",
            "use a speaker across the room or soft headphones, whichever is more comfortable", "dim the screen or turn it face down: the sound does the work",
            "leave one warm lamp on and let the room settle", "play it on loop in the background: it does not need your attention"]


def _L(length: str) -> str:
    return length.title()


def _ins_title(instrument: str) -> str:
    return "Soft Music" if instrument in ("", "other") else instrument.title()


def fallback_title(scene: str, angle: str, length: str, instrument: str, key: str, recent: list[str]) -> str:
    """A title from the angle's patterns: the first that fits 70 characters and is not close to a recent title; patterns rotate by `key`."""
    import difflib
    pats = looks_angles()[angle]["titles"]
    n = _pick(key or scene, len(pats))
    pats = pats[n:] + pats[:n]
    best = ""
    for short in (False, True):
        place = place_of(scene, short).removeprefix("a ").removeprefix("an ")
        for p in pats:
            t = p.format(L=_L(length), Place=place, Ins=_ins_title(instrument))
            if len(t) > TITLE_MAX:
                continue
            best = best or t
            if all(difflib.SequenceMatcher(None, t.lower(), r.lower()).ratio() <= 0.72 for r in recent):
                return t
    return best or title(scene, length, key)


def looks_angles() -> dict:
    from . import looks
    return looks.ANGLES


def fallback_copy(scene: str, angle: str, length: str, instrument: str, look: dict, key: str, recent: list[str]) -> dict:
    """The whole text of the upload from code alone (the chat model writes a better version; this one is true and different from video to video)."""
    from . import looks
    ang = looks.ANGLES[angle]
    parts = looks.look_parts(scene, look)
    place = place_of(scene)
    ins_text = looks.INSTRUMENT_TEXT.get(instrument, "soft instrumental music")
    n = _pick(key or scene, 997)
    aud = [ang["audience"][(n + i) % len(ang["audience"])] for i in range(min(4, len(ang["audience"])))]
    when = [w.format(L_lower=length) for w in (ang["when"][(n + i) % len(ang["when"])] for i in range(min(3, len(ang["when"]))))]
    how = [HOW_POOL[(n + i) % len(HOW_POOL)] for i in range(3)]
    hook = ""
    for k in (3, 2, 1):                                     # as many of the audiences as fit in the hook (about 190 characters)
        who = ", ".join(aud[:k - 1]) + (" and " if k > 1 else "") + aud[k - 1]
        hook = f"{_L(length)} of gentle rain and {ins_text} at {place}, made for {who}."
        if len(hook) <= 190:
            break
    hook = hook[:190]
    lamp = parts["lamp"][0]
    cap = lambda x: x[0].upper() + x[1:]                    # noqa: E731
    paragraph = (f"The view from inside {place} just after the rain: {parts['season'][0]}, and {parts['air'][0]}. "
                 f"{cap(lamp)}. {cap(ins_text)} plays softly under the sound of the rain.")
    return {"title": fallback_title(scene, angle, length, instrument, key, recent), "hook": hook, "scene_paragraph": paragraph, "audience": aud, "when": when, "how": how,
            "about": f"The scene is {place}.", "source": "code"}


def tags_for(scene: str, angle: str, instrument: str = "") -> list[str]:
    from . import looks
    first = list(looks.ANGLES[angle]["tags"])
    words = list((PLACES.get(scene) or {}).get("words", []))
    out = []
    for t in [BASE_TAGS[0], first[0], BASE_TAGS[1], *first[1:], *words, *BASE_TAGS[2:]] + ([f"{instrument} and rain"] if instrument and instrument != "other" else []):
        if t.lower() not in [x.lower() for x in out]:
            out.append(t)
    keep, total = [], 0
    for t in out:
        total += len(t) + 1
        if total > 450 or len(keep) >= 15:
            break
        keep.append(t)
    return keep


def hashtags_for(angle: str) -> list[str]:
    return ["#RainSounds", ANGLE_HASHTAGS.get(angle, "#SleepMusic"), "#RainAmbience"]


# The shape of the description changes from video to video (owner, 2026-11-20: repetitive, template-like text is what YouTube's inauthentic-content rule looks at): which sections
# there are, their order, their headings, how a heading is written, the bullet sign and the closing lines. The hook stays first and the three hashtags last.
SECTION_HEADS = {
    "hear": ["WHAT YOU WILL HEAR", "THE SOUND", "WHAT IS PLAYING", "LISTEN FOR"],
    "who": ["WHO IT IS FOR", "MADE FOR", "GOOD COMPANY FOR", "BEST FOR"],
    "when": ["WHEN TO PLAY IT", "BEST TIMES", "WHEN IT HELPS MOST", "PLAY IT WHEN"],
    "where": ["WHERE IT WORKS", "WHERE TO LISTEN", "GOOD PLACES FOR IT"],
    "how": ["HOW TO USE IT", "LISTENING TIPS", "MAKE THE MOST OF IT", "SMALL TIPS"],
    "scene": ["ABOUT THE SCENE", "THE PLACE", "THE VIEW", "WHERE THIS IS"],
}
HEAD_STYLES = ["caps", "title", "dash"]
BULLETS = ["•", "–", "·", "→"]
CLOSERS = [
    "Where are you listening from, and what are you doing while it rains? Tell us in the comments. New rain videos arrive three times a week: subscribe so you can find the next one.",
    "Tell us where you are and what the weather is like there tonight. Subscribe for a new rain video three times a week.",
    "Leave a comment: what are you working on, reading or dreaming about right now? A new scene comes every few days, so subscribe if you want the next one.",
    "If you enjoyed it, a like and a comment help others find it. Each rain video is a new place, a new instrument and a new mood, three times a week.",
]
DEFAULT_LAYOUT = {"order": ["hear", "who", "when", "where", "how", "scene"], "heads": {k: 0 for k in SECTION_HEADS}, "style": "caps", "bullet": "•", "closer": 0, "sig": "default"}


def pick_layout(key: str, recent: list[str]) -> dict:
    """The shape of one video's description, drawn from `key` (the session id, so a second call gives the same shape) and different from the last videos' (`recent`: their signatures).
    The sections 'hear', 'who' and 'when' are always there (the keywords of the search), one to three of 'where', 'how', 'scene' are added, and the order is shuffled."""
    import random
    rng = random.Random(int(hashlib.sha1(key.encode()).hexdigest()[:12], 16))
    last = [r for r in recent[:6] if r]
    best = None
    for _ in range(60):
        extra = rng.sample(["where", "how", "scene"], rng.choice((1, 2, 3)))
        order = ["hear", "who", "when", *extra]
        rng.shuffle(order)
        heads = {k: rng.randrange(len(SECTION_HEADS[k])) for k in SECTION_HEADS}
        style, bullet, closer = rng.choice(HEAD_STYLES), rng.choice(BULLETS), rng.randrange(len(CLOSERS))
        sig = f"{'>'.join(order)}|{style}|{bullet}|{closer}|{''.join(str(heads[k]) for k in order)}"
        best = {"order": order, "heads": heads, "style": style, "bullet": bullet, "closer": closer, "sig": sig}
        if sig not in last and not any(order[:2] == r.split("|")[0].split(">")[:2] for r in last[:3]):          # not a shape of the last videos, and not the same two sections first as one of the last three
            return best
    return best


def _head(text: str, style: str) -> str:
    if style == "title":
        return text.title().replace("'S", "'s")
    if style == "dash":
        return f"— {text} —"
    return text


def description_from_copy(scene: str, angle: str, length: str, instrument: str, c: dict, layout: dict | None = None) -> str:
    """The description: a hook that carries the keywords (search shows the first ~150 characters), then the sections of `layout` (what, who, when and some of where, how, the scene, in a
    different shape each video), a closing question and three hashtags. Every part follows the video's angle. There is no AI line: the disclosure is YouTube's own flag."""
    from . import looks
    lay = layout or DEFAULT_LAYOUT
    ang = looks.ANGLES[angle]
    place = place_of(scene)
    bullets = lambda items: "\n".join(f"{lay['bullet']} {x[0].upper() + x[1:]}" if x else "" for x in items)       # noqa: E731
    ins_text = looks.INSTRUMENT_TEXT.get(instrument, "soft instrumental music")
    body = {
        "hear": f"{c['scene_paragraph']} The music is instrumental: {ins_text}, slow and calm, with no singing and no drums.",
        "who": bullets(c["audience"]),
        "when": bullets(c["when"]),
        "where": f"{ang['where'][0].upper() + ang['where'][1:]}. {ang['why'][0].upper() + ang['why'][1:]}.",
        "how": bullets(c["how"]),
        "scene": c.get("about") or "The scene is " + place + ".",
    }
    parts = [c["hook"]]
    for k in lay["order"]:
        parts.append(f"{_head(SECTION_HEADS[k][lay['heads'][k]], lay['style'])}\n{body[k]}")
    parts += [CLOSERS[lay["closer"]], " ".join(hashtags_for(angle))]
    return "\n\n".join(parts)[:4800]