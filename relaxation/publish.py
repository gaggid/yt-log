"""Generate YouTube metadata for a relaxation video.

Research findings (2026-11-18):
  - Title pattern: "[Duration] [Sound] | [Use Case]", under 60 chars, function-first
  - Description: first 150 chars = SEO hook; 200+ words total; YouTube chapters;
    3-5 hashtags only at the end
  - Tags: 8-12, all lowercase, exact search phrases users type
  - Category: Music (10), not People & Blogs
  - Made for kids: No
  - Master loudness: -14 to -16 LUFS (we target -14)

The model writes the title and description; tags and hashtags are code-assembled
from the scene type to avoid off-brand or inconsistent outputs.
"""
import hashlib
import re
from datetime import date

from story import llm, settings as settings_mod
from story2.schemas import M, Str, StrList

from . import models as MODS, store

TITLE_MAX = 60     # keep under 60 chars; YouTube shows ~70 on mobile, we aim tighter


SYSTEM = """\
[TASK:rl_publish]
You write the YouTube upload text for an ambient rain relaxation video of the stated duration. The channel targets \
viewers who search for sleep sounds, study music and relaxation. Write in English only.

TITLE (one line, {tmin} to {tmax} characters, hard limit {tmax}):
- Structure: "[Duration] [Sound] | [Use Case]"  — always functional, never poetic.
- Lead with the duration and the main search phrase (rain sounds, rain on window, rain ambience).
- End with the use case people type: sleep, study, relax, focus, meditation, deep sleep.
- Do NOT use clever metaphors, questions, or ALL-CAPS words. No quotation marks.
- Example format: "3 Hours Rain on Window | Deep Sleep & Study"

DESCRIPTION (plain text, 180 to 350 characters for the visible preview, 600 to 900 total):
- First sentence (the preview hook, ≤150 chars): repeat the title keyword and add one synonym.
  Example: "3 hours of gentle rain falling on a window in a cozy room, with soft ambient music for deep sleep and relaxation."
- Next 2 paragraphs: describe the scene and the use cases naturally with related search phrases
  (sleep sounds, rain sounds for sleeping, ambient noise for studying, ASMR rain, white noise, \
cozy room ambience). Only say what the video actually shows; invent nothing.
- YouTube chapters line, three timestamps inside the stated duration (none beyond it), e.g. for 3 hours:
  "0:00 Rain begins  |  1:00:00 Deep rain  |  2:00:00 Still falling"
- One engagement question: "What do you like to do while it rains?"
- One subscribe line: "Subscribe for a new rain video every day."
- End with hashtags on the last line. HASHTAGS: exactly 3 to 5; first must be #RainSounds, \
then topic words (#SleepMusic, #ASMRRain, #AmbientRain, #RelaxingRain, #CozyRain, #StudyMusic).

Return ONLY a JSON object: {{"title": "...", "description": "..."}}"""


class PublishOut(M):
    title: Str
    description: Str


# Per-scene tag sets (all lowercase, exact search phrases)
_BASE_TAGS = [
    "rain sounds", "rain sounds for sleeping", "sleep sounds", "ambient rain",
    "rain on window", "relaxing rain", "sleep music", "white noise",
    "study music", "ASMR rain", "nature sounds", "cozy rain",
]
_SCENE_TAGS: dict[str, list[str]] = {
    "night_city": ["city rain sounds", "rain at night", "urban rain"],
    "mountain_forest": ["mountain rain sounds", "forest rain", "cabin rain"],
    "ocean": ["ocean rain sounds", "seaside rain", "coastal ambience"],
    "countryside": ["countryside rain", "farmhouse rain", "rain on window"],
    "forest": ["forest rain sounds", "jungle rain", "treehouse rain"],
}
_HASHTAGS = ["#RainSounds", "#SleepMusic", "#ASMRRain", "#AmbientRain", "#CozyRain"]


def _clean_title(t: str, length: str) -> str:
    """`length` is the video's length in words ('3 hours', '5 minutes')."""
    t = re.sub(r"\s+", " ", (t or "").replace('"', "")).strip()
    if len(t) > TITLE_MAX:
        t = t[:TITLE_MAX].rsplit(" ", 1)[0].rstrip(" ,:;-–|")
    # make sure the length is right
    if length.split()[0] not in t and "hour" not in t.lower() and "minute" not in t.lower():
        t = f"{length.title()} " + t
    return t[:TITLE_MAX]


def _tags(scene: str) -> list[str]:
    base = list(_BASE_TAGS)
    base += _SCENE_TAGS.get(scene, [])
    return base[:15]


def _fallback_title(scene: str, length: str) -> str:
    label = MODS.SCENES.get(scene, {}).get("label", "Rain")
    return f"{length.title()} Rain Sounds | {label} | Sleep & Study"[:TITLE_MAX]


def _fallback_description(scene: str, length: str) -> str:
    label = MODS.SCENES.get(scene, {}).get("label", "Cozy Room")
    return (
        f"{length} of gentle rain falling on a window in a cozy {label.lower()} setting, "
        "with soft ambient music for deep sleep and relaxation.\n\n"
        "Perfect for sleeping, studying, working from home or unwinding after a long day. "
        "Let the steady rhythm of the rain wash away stress and help you focus.\n\n"
        + ("0:00 Rain begins  |  1:00:00 Deep rain  |  2:00:00 Still falling\n\n" if "hour" in length else "0:00 Rain begins\n\n") +
        "What do you like to do while it rains? Tell us in the comments.\n"
        "Subscribe for a new rain video every day.\n\n"
        "#RainSounds #SleepMusic #ASMRRain #AmbientRain #CozyRain"
    )


def narration_hash(session: dict) -> str:
    """A hash of the session inputs that the publish text was written for."""
    return hashlib.sha1(
        f"{session['id']}{(session.get('settings') or {}).get('scene')}".encode()
    ).hexdigest()[:12]


async def generate(session_id: str, s: dict | None = None, force: bool = False) -> dict:
    """Write title/description/tags via model. Saves to session and returns the publish dict."""
    s = s or settings_mod.get()
    session = store.get(session_id)
    settings = session.get("settings") or {}
    scene = settings.get("scene") or MODS.DEFAULT_SCENE
    hours = MODS.duration_label(settings)       # '3 hours' or '5 minutes'

    existing = session.get("publish") or {}
    if not force and existing.get("title") and existing.get("nh") == narration_hash(session):
        return existing

    backend = llm.ChatBackend(s, settings_mod.api_key())
    system = SYSTEM.format(tmin=30, tmax=TITLE_MAX)
    user = (
        f"Scene: {MODS.SCENES.get(scene, {}).get('label', scene)}\n"
        f"Duration: {hours}\n"
        f"Today's date: {date.today().isoformat()}\n"
        f"Music: soft ambient YuE2 bed under steady rain"
    )

    try:
        res = await llm.JsonCaller(backend, s).call(system, user, PublishOut)
        o = res.value
        title = _clean_title(o.title, hours)
        description = (o.description or "").strip()[:4800]
    except llm.LLMError:
        title = _fallback_title(scene, hours)
        description = _fallback_description(scene, hours)

    publish = {
        "title": title,
        "description": description,
        "hashtags": _HASHTAGS[:5],
        "tags": _tags(scene),
        "nh": narration_hash(session),
        "category_id": MODS.YT_CATEGORY_MUSIC,
    }
    session["publish"] = publish
    store.save(session)
    return publish
