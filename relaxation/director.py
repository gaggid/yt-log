"""The art director of a rain video: the chat model writes the scene prompt, the thumbnail concept and the YouTube text of THIS video from seeds that code picked
(relaxation/looks.py), so no two videos come out alike.

Why seeds and not "be creative": asked for a fresh idea with nothing to hold on to, a model gives the same answer every day (the owner saw the same lamp,
the same thumbnail and the same text every time). Code therefore decides the variable facts (light, lamp and its side, season, air, camera, colour grade,
what the thumbnail shows, who the video is for), and the model's job is to write them into rich, concrete, consistent words. Code then checks the words
(every seed appears, no rain in the air of the picture, no person in the scene, no health claim, no copy of a recent title) and asks again with the reason;
when the model still fails, the code stand-ins in looks.py / seo.py are used, so a run is never stopped and never repeats itself either.

Nothing here draws anything: the result is stored in the session settings (`scene_prompt`, `thumb`, `thumb_prompt`, `copy`) and read by image.py, thumb.py and publish.py."""
import difflib
import hashlib
import json
import random
import re

from story import llm, settings as settings_mod
from story2.schemas import M, Str, StrList

from . import looks, models as MODS, seo, store, variety

BAN = re.compile(r"\b(cures?|treat(?:s|ment)?|heal(?:s|ing)?|therap\w+|insomnia|anxiety|depress\w*|adhd|clinical\w*|proven|guarantee\w*|instantly|miracle|doctors?|medical|"
                 r"better sleep|sleep better|no ads|ad-free)\b", re.I)
STOCK = ("immerse", "embark", "experience the", "transport yourself", "journey")


# ── what the model returns ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
class VisualOut(M):
    scene_prompt: Str
    thumb_prompt: Str
    headline: Str
    subline: Str = ""


class CopyOut(M):
    title: Str
    hook: Str
    scene_paragraph: Str
    audience: StrList
    when: StrList
    how: StrList
    about: Str = ""


VISUAL_SYSTEM = """\
[TASK:rl_visual]
You are the art director of a calm rain-ambience YouTube channel. You write two picture prompts for an image model and the words of a thumbnail.

1. scene_prompt: the picture that the video shows, seen in the first person from inside a room, looking out. Start from the BASE PROMPT and keep its place, its
   composition and its layers of depth, but weave in EVERY seed given (light, lamp and its side, season, air, camera, grade, extra thing) so that this picture is
   clearly different from the recent ones listed. Write the way a photographer describes one real moment: concrete, positive words only (say what is there, never
   what is not), no filler adjectives. The picture is WET (just after rain: soaked surfaces, beads of water on glass, puddles, mist) but the AIR is clear: never
   write falling rain, rain streaks, downpour or heavy rain. No person, no text, no logo. 120 to 260 words. End with exactly: No people, no text, no logo.
2. thumb_prompt: start from the THUMBNAIL BASE and improve it with the same care. Keep the subject kind, the side the subject is on, who it is and what they do.
   Warm, cozy, uplifting. Photorealistic. End with: No text, no logo.
3. headline: the big words laid on the thumbnail by code: 2 or 3 words, capital letters, at most 16 characters, true to the video (no claims about health).
   subline: 2 to 4 words, capital letters, at most 24 characters.

Return ONLY a JSON object: {{"scene_prompt": "...", "thumb_prompt": "...", "headline": "...", "subline": "..."}}"""

COPY_SYSTEM = """\
[TASK:rl_copy]
You write the YouTube title and description parts for a calm rain-ambience video, for the viewer who would actually search for it. The text answers what, who, when,
where and why, and is true of the video: rain and soft instrumental music, no singing, made by AI. English only.

Return these fields:
- title: at most 70 characters. Keywords people type come FIRST, then the length and the place. Must contain the word "rain" and the length given. Use the ANGLE
  given (who it is for) and a form that differs from the recent titles listed.
- hook: 110 to 190 characters, the first line of the description: the length, what it is, who it is for. Plain words.
- scene_paragraph: two sentences, 25 to 50 words: what the viewer sees (use the seeds: lamp, season, light) and which instrument plays softly under the rain.
- audience: 4 short items (3 to 12 words each): who it is for, matching the angle.
- when: 3 short items: when to play it (a time of day or a moment, with the length where it helps).
- how: 3 short items: how to use it (volume, a sleep timer in the app, speaker or headphones, a lamp, a screen turned down).
- about: one sentence on the place of the scene.
Rules: no claims about health or sleep results, no medical words, no promise of "no ads", no hype, no emoji, no hashtags, do not use the words immerse, embark,
journey. Never start with "Experience".

Return ONLY a JSON object with exactly those fields."""


def _words(s: str) -> int:
    return len((s or "").split())


def _recent_text(hist: list[dict], key: str, n: int = 5) -> list[str]:
    return [h[key] for h in hist[:n] if h.get(key)]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", (s or "").lower())


def title_problems(title: str, length: str, recent: list[str]) -> list[str]:
    t = (title or "").strip()
    out = []
    if not 20 <= len(t) <= seo.TITLE_MAX:
        out.append(f"the title must be 20 to {seo.TITLE_MAX} characters (it is {len(t)})")
    if "rain" not in t.lower():
        out.append('the title must contain "rain"')
    digits = re.findall(r"\d+(?:\.\d+)?", length)
    if digits and digits[0] not in t:
        out.append(f"the title must contain the length ({length})")
    if BAN.search(t) or t.lower().startswith(STOCK):
        out.append("the title makes a health claim or uses a stock opener")
    for r in recent:
        if difflib.SequenceMatcher(None, _norm(t), _norm(r)).ratio() > 0.72:
            out.append(f"the title is too close to a recent one: {r}")
            break
    return out


def copy_problems(c: CopyOut, length: str, recent: list[str]) -> list[str]:
    out = title_problems(c.title, length, recent)
    if not 100 <= len(c.hook) <= 210:
        out.append(f"hook must be 110 to 190 characters (it is {len(c.hook)})")
    if not 18 <= _words(c.scene_paragraph) <= 60:
        out.append("scene_paragraph must be two sentences of 25 to 50 words")
    for name, items, lo, hi, nlo, nhi in (("audience", c.audience, 3, 5, 2, 16), ("when", c.when, 2, 4, 2, 22), ("how", c.how, 2, 4, 2, 22)):
        if not lo <= len(items) <= hi:
            out.append(f"{name} must have {lo} to {hi} items")
        for it in items:
            if not nlo <= _words(it) <= nhi:
                out.append(f"{name} item too short or too long: {it[:40]}")
                break
    blob = " ".join([c.hook, c.scene_paragraph, c.about, *c.audience, *c.when, *c.how])
    if BAN.search(blob):
        out.append(f"remove the health or ad claim: {BAN.search(blob).group(0)}")
    if "#" in blob or any(w in blob.lower() for w in STOCK):
        out.append("no hashtags or stock words (immerse, embark, journey)")
    return out


def thumb_words_problems(headline: str, subline: str) -> list[str]:
    out = []
    if not re.fullmatch(r"[A-Z0-9 &+'!?.,-]{3,16}", (headline or "").strip()) or _words(headline) > 3:
        out.append("headline: 2 or 3 words in capital letters, at most 16 characters")
    if subline and (not re.fullmatch(r"[A-Z0-9 &+'!?.,-]{2,24}", subline.strip()) or _words(subline) > 4):
        out.append("subline: up to 4 words in capital letters, at most 24 characters")
    if BAN.search(f"{headline} {subline}"):
        out.append("no health claims")
    return out


# ── the plan of one video ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _seed_text(scene: str, look: dict) -> str:
    parts = looks.look_parts(scene, look)
    return "\n".join(f"- {slot}: {phrase}" + (f" (the prompt must contain: {', '.join(m)})" if m else "") for slot, (phrase, m) in parts.items())


def _recent_looks(hist: list[dict], n: int = 4) -> str:
    rows = []
    for h in hist[:n]:
        lk = h.get("look") or {}
        if lk:
            rows.append(f"- {h.get('scene', '')}: light {lk.get('light', '')}, lamp {lk.get('lamp', '')} {lk.get('side', '')}, season {lk.get('season', '')}, "
                        f"air {lk.get('air', '')}, camera {lk.get('camera', '')}")
    return "\n".join(rows) or "- (none yet)"


def seeds_hash(st: dict) -> str:
    raw = json.dumps([st.get("scene"), st.get("look"), st.get("angle"), (st.get("thumb") or {}).get("subject"), st.get("music_plan", {}).get("instrument")], sort_keys=True, default=str)
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def ensure_seeds(session: dict, rng: random.Random | None = None) -> bool:
    """Seeds for a session made before this module existed (or a new one): look, angle, thumbnail. Returns True when something was added."""
    st = session.setdefault("settings", {})
    rng = rng or random.Random(int(st.get("seed") or 1))
    hist = [h for h in variety.history() if h.get("id") != session.get("id")]
    changed = False
    scene = st.get("scene") or MODS.DEFAULT_SCENE
    if not st.get("angle"):
        st["angle"] = looks.pick_angle(hist, rng)
        changed = True
    if not st.get("look"):
        st["look"] = looks.pick_look(scene, hist, rng)
        changed = True
    if not st.get("thumb") or "layout" not in st["thumb"]:
        st["thumb"] = looks.pick_thumb(st["angle"], scene, hist, rng)
        st["thumb_person"] = st["thumb"].get("who", st.get("thumb_person", "woman"))
        changed = True
    return changed


async def plan(session_id: str, s: dict | None = None, force: bool = False) -> dict:
    """Write (or keep) the scene prompt, the thumbnail concept and the YouTube text of this session. Never raises for a model failure: the stand-ins are used."""
    s = s or settings_mod.get()
    session = store.get(session_id)
    if ensure_seeds(session):
        store.save(session)
    st = session["settings"]
    if not force and st.get("director_hash") == seeds_hash(st) and st.get("scene_prompt") and (st.get("copy") or {}).get("title"):
        return st
    scene = st.get("scene") or MODS.DEFAULT_SCENE
    look, angle, thumb = st["look"], st["angle"], dict(st["thumb"])
    hist = [h for h in variety.history() if h.get("id") != session_id]
    length = MODS.duration_label(st)
    instrument = (st.get("music_plan") or {}).get("instrument", "soft piano")
    base_prompt = MODS.SCENES[scene]["prompt"]
    stand_in = looks.compose_prompt(scene, look)
    thumb_stand_in = looks.thumb_prompt(scene, thumb)
    notes: list[str] = []

    backend = None
    try:
        backend = llm.ChatBackend(s, settings_mod.api_key())
    except Exception as e:                                   # no gateway key (a scratch copy): the stand-ins carry the run
        notes.append(f"no model: {str(e)[:80]}")
    caller = llm.JsonCaller(backend, s) if backend else None

    # 1. the pictures and the words on the thumbnail
    scene_prompt, thumb_prompt = stand_in, thumb_stand_in
    headline = ""
    subline = ""
    if caller:
        wet = MODS.WET
        base_wo_wet = base_prompt[len(wet):] if base_prompt.startswith(wet) else base_prompt
        base_wo_wet = " ".join(looks._LIGHT_SENT.sub("", base_wo_wet).split())            # the base light sentence goes: the seed's light replaces it
        user = (f"BASE PROMPT (the place of this video):\n{base_wo_wet}\n\nSEEDS to weave in (all of them):\n{_seed_text(scene, look)}\n\n"
                f"RECENT PICTURES to be different from:\n{_recent_looks(hist)}\n\n"
                f"THUMBNAIL BASE:\n{thumb_stand_in}\n\nVideo angle: {looks.ANGLES[angle]['label']}; length {length}; instrument {instrument}; place {seo.place_of(scene)}.")

        def check(v: VisualOut) -> None:
            bad = looks.prompt_problems(scene, look, v.scene_prompt) + [f"thumb_prompt: {p}" for p in looks.thumb_problems(thumb, v.thumb_prompt)] \
                + thumb_words_problems(v.headline.strip().upper(), v.subline.strip().upper())
            if bad:
                raise ValueError("; ".join(bad)[:700])
        try:
            res = await caller.call(VISUAL_SYSTEM, user, VisualOut, validate=check)
            v = res.value
            scene_prompt = wet + " " + v.scene_prompt.strip() if not v.scene_prompt.strip().startswith(wet[:20]) else v.scene_prompt.strip()
            thumb_prompt = v.thumb_prompt.strip()
            headline, subline = v.headline.strip().upper(), v.subline.strip().upper()
            notes.append("visual: model")
        except Exception as e:                           # noqa: BLE001  a model failure must never stop a run
            notes.append(f"visual: stand-in ({str(e)[:120]})")
    if not headline:
        ang = looks.ANGLES[angle]
        headline = ang["headlines"][int(st.get("seed") or 0) % len(ang["headlines"])]
        subline = ang["tail"]
    thumb["headline"], thumb["subline"] = headline, subline

    # 2. the YouTube text
    copy = seo.fallback_copy(scene, angle, length, instrument, look, session_id, _recent_text(hist, "title"))
    if caller:
        recent_titles = _recent_text(hist, "title")
        ang = looks.ANGLES[angle]
        parts = looks.look_parts(scene, look)
        user = (f"ANGLE: {ang['label']} (who: {'; '.join(ang['audience'][:3])}; when: {'; '.join(ang['when'][:2])}; where: {ang['where']}; why: {ang['why']})\n"
                f"Length: {length}\nPlace: {seo.place_of(scene)} ({MODS.SCENES[scene]['label']})\nInstrument: {instrument} ({looks.INSTRUMENT_TEXT.get(instrument, 'soft instrumental music')})\n"
                f"What the picture shows: {parts['lamp'][0]}; {parts['season'][0]}; {parts['light'][0]}; {parts['air'][0]}\n"
                f"Title forms to be different from (recent titles): {recent_titles or ['(none yet)']}\n"
                f"Title patterns that work for this angle: {[p.format(L=length.title(), Place=seo.place_of(scene, True), Ins=instrument.title()) for p in ang['titles']]}")
        try:
            res = await caller.call(COPY_SYSTEM, user, CopyOut, validate=lambda c: _raise(copy_problems(c, length, recent_titles)))
            c = res.value
            copy = {**copy, "title": c.title.strip(), "hook": c.hook.strip(), "scene_paragraph": c.scene_paragraph.strip(), "audience": [x.strip() for x in c.audience],
                    "when": [x.strip() for x in c.when], "how": [x.strip() for x in c.how], "about": c.about.strip() or copy.get("about", ""), "source": "model"}
            notes.append("copy: model")
        except Exception as e:                           # noqa: BLE001
            notes.append(f"copy: stand-in ({str(e)[:120]})")

    session = store.get(session_id)
    st = session["settings"]
    st["scene_prompt"], st["thumb_prompt"], st["thumb"], st["copy"] = scene_prompt, thumb_prompt, thumb, copy
    st["flame"] = bool(look.get("flame"))
    st["director_hash"] = seeds_hash(st)
    st["director_notes"] = notes
    session["publish"] = {}                                   # the upload text is written again from the new copy
    store.save(session)
    return st


def _raise(problems: list[str]) -> None:
    if problems:
        raise ValueError("; ".join(problems)[:700])
