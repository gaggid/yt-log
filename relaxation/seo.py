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
        "The scene and the music are AI-generated.",
        "Subscribe for a new rain video every night. What are you doing while it rains?",
        " ".join(HASHTAGS),
    ])[:4800]
