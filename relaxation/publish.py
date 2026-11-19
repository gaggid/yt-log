"""YouTube upload text for a rain video.

The title, tags, hashtags and the bones of the description are made in code (relaxation/seo.py: keyword first,
a place that differs by theme, three hashtags, the AI disclosure, nothing untrue). The chat model writes only two plain
sentences about what the viewer sees and hears; when it fails a template sentence is used, so a video is never left without text.
Category is Music (10); not made for kids; the master is -14 LUFS."""
import hashlib

from story import llm, settings as settings_mod
from story2.schemas import M, Str

from . import models as MODS, seo, store

TITLE_MAX = seo.TITLE_MAX

SYSTEM = """\
[TASK:rl_publish]
You write two plain sentences for the YouTube description of an ambient rain video. Say only what the viewer sees and hears \
in this scene and which instrument plays softly under the rain. English only.
Rules: exactly two sentences, 20 to 45 words together, calm and concrete, no hype, no claims about health or sleep results, \
no emoji, no quotation marks, no hashtags, do not start with "Immerse" or "Experience".

Return ONLY a JSON object: {{"paragraph": "..."}}"""


class ParaOut(M):
    paragraph: Str


def _clean_paragraph(text: str) -> str:
    t = " ".join((text or "").replace('"', "").split())
    bad = ("immerse", "experience the", "embark", "transport", "sleep better", "cure")
    words = len(t.split())
    if not (12 <= words <= 60) or any(b in t.lower() for b in bad) or "#" in t:
        return ""
    return t


def narration_hash(session: dict) -> str:
    """A hash of the session inputs that the publish text was written for."""
    st = session.get("settings") or {}
    raw = f"{session['id']}{st.get('scene')}{(st.get('music_plan') or {}).get('instrument', '')}{MODS.duration_label(st)}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


async def generate(session_id: str, s: dict | None = None, force: bool = False) -> dict:
    """Write title/description/tags. Saves to the session and returns the publish dict."""
    s = s or settings_mod.get()
    session = store.get(session_id)
    settings = session.get("settings") or {}
    scene = settings.get("scene") or MODS.DEFAULT_SCENE
    length = MODS.duration_label(settings)                       # '3 hours' or '5 minutes'
    instrument = (settings.get("music_plan") or {}).get("instrument", "piano")

    existing = session.get("publish") or {}
    if not force and existing.get("title") and existing.get("nh") == narration_hash(session):
        return existing

    paragraph = ""
    try:
        backend = llm.ChatBackend(s, settings_mod.api_key())
        user = (f"Scene: {MODS.SCENES.get(scene, {}).get('label', scene)}, {seo.place_of(scene)}\n"
                f"What the picture shows: {MODS.SCENES.get(scene, {}).get('prompt', '')[:420]}\n"
                f"Music: soft {instrument} under steady rain")
        res = await llm.JsonCaller(backend, s).call(SYSTEM, user, ParaOut)
        paragraph = _clean_paragraph(res.value.paragraph)
    except llm.LLMError:
        paragraph = ""

    publish = {
        "title": seo.title(scene, length, session["id"]),
        "description": seo.description(scene, length, instrument, paragraph),
        "hashtags": seo.HASHTAGS,
        "tags": seo.tags(scene, instrument),
        "nh": narration_hash(session),
        "category_id": MODS.YT_CATEGORY_MUSIC,
    }
    session["publish"] = publish
    store.save(session)
    return publish
