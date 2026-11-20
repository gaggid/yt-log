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

from . import looks, models as MODS, seo, store, thumbcheck, variety

BAN = re.compile(r"\b(cures?|treat(?:s|ment)?|heal(?:s|ing)?|therap\w+|insomnia|anxiety|depress\w*|adhd|clinical\w*|proven|guarantee\w*|instantly|miracle|doctors?|medical|"
                 r"better sleep|sleep better|no ads|ad-free)\b", re.I)
STOCK = ("immerse", "embark", "experience the", "transport yourself", "journey")


# ── what the model returns ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
class VisualOut(M):
    scene_prompt: Str


class ThumbOut(M):
    prompt: Str
    text: Str = ""
    summary: Str = ""
    has_person: bool = False


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
You are the art director of a calm rain-ambience YouTube channel. You write the picture prompt of the video's scene for an image model.

scene_prompt: the picture that the video shows, seen in the first person from inside a room, looking out. Start from the BASE PROMPT and keep its place, its
   composition and its layers of depth, but weave in EVERY seed given (light, lamp and its side, season, air, camera, grade, extra thing) so that this picture is
   clearly different from the recent ones listed. Write the way a photographer describes one real moment: concrete, positive words only (say what is there, never
   what is not), no filler adjectives. The picture is WET (just after rain: soaked surfaces, beads of water on glass, puddles, mist) but the AIR is clear: never
   write falling rain, rain streaks, downpour or heavy rain. No person, no text, no logo. 120 to 260 words. End with exactly: No people, no text, no logo.

Return ONLY a JSON object: {"scene_prompt": "..."}"""

THUMB_MODEL = "qwen3.8-27b-Q3_S"          # the owner chose this gateway model for the thumbnail prompt (2026-11-20)

THUMB_SYSTEM = """\
[TASK:rl_thumb]
You are the art director of a YouTube channel of calm rain and sleep music. You write ONE prompt for an image model (Qwen Image) that draws the thumbnail of a video.

The thumbnail must make a tired person scrolling at night feel calm and want to click: it reflects calm, cozy, sleepy rain music. It is a single clear picture with one focal point, readable at small size, rich but soft colour, photorealistic or softly painterly (your choice), 16:9.

You decide the picture yourself, with full freedom: the subject, the framing, the light, the colour palette, the mood, the details. Use the FACTS (place, instrument, length, who it is for) as raw material. Good subjects: a happy person in the rainy place, the instrument resting at a rain-covered window, the place seen from outside, a wide landscape in rain, macro raindrops on glass with glowing bokeh, an animal, a still life, an object. Write it out richly and concretely, as a photographer would describe one real moment.
YOU choose whether a person is in the picture. A happy person (a man or a woman) makes a warm, human thumbnail; a picture with no person can be calmer and more atmospheric. Look at RECENT (each line says whether it had a person) and choose what keeps the channel page varied: do not repeat the last pictures' subject, framing or palette, and aim for about four thumbnails in ten with a person over time. The OPTIONAL PERSON line gives a person to use if you choose one (you may adapt the clothes and the activity to the scene).
IF YOU INCLUDE A PERSON: they are the hero, seen from the waist up with the face clearly visible, natural and attractive, not a close-up, HAPPY and relaxed (a real warm smile or a soft blissful closed-eye smile), fully dressed in cozy modest clothes; describe them concretely (age range, look, hair, clothes, what they do, where they look) and set has_person to true.
IF YOU DO NOT: no people anywhere in the picture, and has_person is false.
Rain must be visible (drops on glass, fine silver lines, wet surfaces, ripples, mist).

THE WORDS IN THE PICTURE: Qwen Image draws text. The picture carries exactly the TEXT given, split over two or three stacked lines, and nothing else is lettered. The words are a main part of the thumbnail and must read at a glance when it is shown the size of a postage stamp. In the prompt, put the exact words in double quotes (every word, every number) and say: huge, bold, heavy, impactful lettering that fills about 40 percent of the picture's width and a third of its height, in the open space on the side given (compose the picture so that space exists, with the subject on the other side), the number or the first line even larger. Describe the lettering with the TYPE and COLOURS given (add a soft dark outline or shadow and a gentle glow so it pops from the background yet stays calm and cozy, never harsh). No logo, no watermark, no channel name, no small print.

Write positive words only (say what is there, never what is not), concrete and visual, 90 to 200 words, one flowing paragraph.

Return ONLY a JSON object: {"prompt": "<the image prompt>", "text": "<the exact words in the picture>", "summary": "<5 to 10 words: what the picture shows>", "has_person": <true or false>}"""

COPY_SYSTEM = """\
[TASK:rl_copy]
You write the YouTube title and description parts for a calm rain-ambience video, for the viewer who would actually search for it. The text answers what, who, when,
where and why, and is true of the video: rain and soft instrumental music, no singing. English only.

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


_PERSON_WORDS = re.compile(r"\b(woman|man|girl|boy|person|people|he|she|his|her)\b")


def thumb_text(st: dict, instrument: str) -> str:
    """The big words drawn into the thumbnail: the length and the instrument ('3 HOURS BAMBOO FLUTE')."""
    return f"{MODS.duration_label(st)} {instrument}".upper().strip()


def thumb_model_problems(t: dict, expected: str, prompt: str, instrument: str = "", has_person: bool | None = None) -> list[str]:
    """Plain-code checks of the art model's thumbnail prompt: the exact words are in it, in quotes, large and bold; rain is visible; and the picture agrees with what the
    model declared: a person is happy, no person means no person. `has_person` None = the seed's subject decides (the stand-in tests)."""
    low = (prompt or "").lower()
    out = []
    if not 350 <= len(prompt or "") <= 2600:
        out.append("the prompt must be 90 to 200 words")
    if '"' not in (prompt or "") and "\u201c" not in (prompt or ""):
        out.append("put the exact words of the TEXT in double quotes")
    have = set(thumbcheck.norm(prompt).split())
    missing = [w for w in thumbcheck.norm(expected).split() if w not in have]
    if missing:
        out.append(f"every word of the TEXT must be in the prompt, missing: {' '.join(missing)}")
    if not re.search(r"\b(bold|heavy|huge)\b", low):
        out.append("say that the lettering is huge, bold and heavy")
    if "rain" not in low:
        out.append("the rain must be visible in the picture: say it")
    person = (t.get("subject") in looks.PERSON_SUBJECTS) if has_person is None else has_person
    if person:
        if not re.search(r"\b(smil\w*|happy|joy\w*|content|blissful)\b", low):
            out.append("the person must be happy: say how they smile")
        if not _PERSON_WORDS.search(low):
            out.append("has_person is true but no person is described")
    elif _PERSON_WORDS.search(low.replace("no people", "")):
        out.append("has_person is false but a person is in the prompt: remove them or set has_person to true")
    return out


async def plan_thumb(session_id: str, s: dict | None = None, backend=None) -> dict:
    """Write the thumbnail picture prompt of this session with the art model, the big words inside it. Never raises: when the model fails or breaks a rule the code prompt
    (no words in it) is stored and `thumb.text_in_picture` is False, so thumb.make lays the words on by code instead."""
    s = s or settings_mod.get()
    session = store.get(session_id)
    if ensure_seeds(session):
        store.save(session)
    st = session["settings"]
    scene = st.get("scene") or MODS.DEFAULT_SCENE
    angle = st["angle"]
    t = dict(st["thumb"])
    length = MODS.duration_label(st)
    instrument = (st.get("music_plan") or {}).get("instrument", "soft piano")
    hist = [h for h in variety.history() if h.get("id") != session_id]
    stand_in = looks.thumb_prompt(scene, t, instrument)
    ang = looks.ANGLES[angle]
    t["headline"] = ang["headlines"][int(st.get("seed") or 0) % len(ang["headlines"])]
    t["subline"] = ang["tail"]
    t["text"] = thumb_text(st, instrument)
    t["text_in_picture"] = False
    prompt, note = stand_in, ""
    try:
        if backend is None:
            backend = llm.ChatBackend({**s, "model": THUMB_MODEL}, settings_mod.api_key())
        caller = llm.JsonCaller(backend, {**s, "model": THUMB_MODEL})
    except Exception as e:                                   # noqa: BLE001  no gateway key (a scratch copy)
        caller, note = None, f"thumb: stand-in (no model: {str(e)[:80]})"
    if caller:
        view = MODS.THUMB_VIEWS.get(scene) or MODS.THUMB_VIEWS[MODS.DEFAULT_SCENE]
        open_side = {"right": "left", "left": "right"}.get(t.get("side", "right"), "left")
        recent = [f"{(h.get('thumb') or {}).get('summary')} ({'with a person' if (h.get('thumb') or {}).get('has_person') else 'no person'})" for h in hist[:6]
                  if (h.get("thumb") or {}).get("summary")]
        person_seed = (f"a happy {t.get('who', 'woman')} {t.get('age', 'in their twenties')}, {t.get('ethnic', 'South Asian')}, with {t.get('hair', 'short dark hair')}, "
                       f"in {t.get('outfit', looks.OUTFITS[0])}")
        user = (f"FACTS\nPlace: {seo.place_of(scene)} ({MODS.SCENES[scene]['label']}). Outside the window: {view}\n"
                f"Music: {instrument} ({looks.INSTRUMENT_TEXT.get(instrument, 'soft instrumental music')}), {length}\n"
                f"Who it is for: {ang['label']} ({'; '.join(ang['audience'][:2])})\n"
                f"Light you may use: {t.get('light', looks.THUMB_LIGHT[0])}\n"
                f"OPTIONAL PERSON: {person_seed}\n\n"
                f"TEXT to draw in the picture: {t['text']}\nTYPE: {t.get('type_style', looks.TYPE_STYLES[0])}\nCOLOURS: {t.get('text_colors', looks.TEXT_COLORS[0])}\n"
                f"The big words go on the {open_side} side; the subject is on the {t.get('side', 'right')}.\n\nRECENT thumbnails to be different from: {recent or ['(none yet)']}")
        try:
            res = await caller.call(THUMB_SYSTEM, user, ThumbOut, validate=lambda v: _raise(thumb_model_problems(t, t["text"], v.prompt, instrument, v.has_person)))
            prompt, t["summary"], t["text_in_picture"], t["has_person"] = res.value.prompt.strip(), res.value.summary.strip(), True, bool(res.value.has_person)
            note = "thumb: model"
        except Exception as e:                               # noqa: BLE001  a model failure must never stop a run
            note = f"thumb: stand-in ({str(e)[:120]})"
    t["planned"] = True
    session = store.get(session_id)
    st = session["settings"]
    st["thumb"], st["thumb_prompt"] = t, prompt
    st["director_notes"] = [n for n in (st.get("director_notes") or []) if not n.startswith("thumb:")] + [note]
    store.save(session)
    return st


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
        if not (st.get("thumb") or {}).get("planned"):          # a session planned before the thumbnail had its own model call
            return await plan_thumb(session_id, s)
        return st
    scene = st.get("scene") or MODS.DEFAULT_SCENE
    look, angle = st["look"], st["angle"]
    hist = [h for h in variety.history() if h.get("id") != session_id]
    length = MODS.duration_label(st)
    instrument = (st.get("music_plan") or {}).get("instrument", "soft piano")
    base_prompt = MODS.SCENES[scene]["prompt"]
    stand_in = looks.compose_prompt(scene, look)
    notes: list[str] = []

    backend = None
    try:
        backend = llm.ChatBackend(s, settings_mod.api_key())
    except Exception as e:                                   # no gateway key (a scratch copy): the stand-ins carry the run
        notes.append(f"no model: {str(e)[:80]}")
    caller = llm.JsonCaller(backend, s) if backend else None

    # 1. the scene picture (the thumbnail has its own call, plan_thumb, with its own model)
    scene_prompt = stand_in
    if caller:
        wet = MODS.WET
        base_wo_wet = base_prompt[len(wet):] if base_prompt.startswith(wet) else base_prompt
        base_wo_wet = " ".join(looks._LIGHT_SENT.sub("", base_wo_wet).split())            # the base light sentence goes: the seed's light replaces it
        user = (f"BASE PROMPT (the place of this video):\n{base_wo_wet}\n\nSEEDS to weave in (all of them):\n{_seed_text(scene, look)}\n\n"
                f"RECENT PICTURES to be different from:\n{_recent_looks(hist)}\n\n"
                f"Video angle: {looks.ANGLES[angle]['label']}; length {length}; instrument {instrument}; place {seo.place_of(scene)}.")

        def check(v: VisualOut) -> None:
            bad = looks.prompt_problems(scene, look, v.scene_prompt)
            if bad:
                raise ValueError("; ".join(bad)[:700])
        try:
            res = await caller.call(VISUAL_SYSTEM, user, VisualOut, validate=check)
            v = res.value
            scene_prompt = wet + " " + v.scene_prompt.strip() if not v.scene_prompt.strip().startswith(wet[:20]) else v.scene_prompt.strip()
            notes.append("visual: model")
        except Exception as e:                           # noqa: BLE001  a model failure must never stop a run
            notes.append(f"visual: stand-in ({str(e)[:120]})")

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
    st["scene_prompt"], st["copy"] = scene_prompt, copy
    st["flame"] = bool(look.get("flame"))
    st["director_hash"] = seeds_hash(st)
    st["director_notes"] = notes
    session["publish"] = {}                                   # the upload text is written again from the new copy
    store.save(session)
    return await plan_thumb(session_id, s)


def _raise(problems: list[str]) -> None:
    if problems:
        raise ValueError("; ".join(problems)[:700])
