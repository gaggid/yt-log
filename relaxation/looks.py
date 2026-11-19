"""Variety for the Rain Channel: what makes one video look, read and sell differently from the last ones.

Three things varied (owner, 2026-11-19: every picture, thumbnail and text came out alike, so the daily run could not be switched on):
  1. the scene picture: light, lamps (kind, number, side), season, air, camera and colour grade, picked per video from pools;
  2. the thumbnail: what is shown (a person, a person from behind, a cat, a still life), what they do, the side, the layout of the words, the font, the colours;
  3. the angle of the text: who the video is for, when and where it is played (sleep, study, work, reading, calm, noise, meditation, rainy day, late night),
     which drives the title, the description and the words on the thumbnail.

Code picks the seeds here and remembers them in the session (`settings.look`, `settings.angle`, `settings.thumb`); each choice avoids what the last videos used.
The chat model (relaxation/director.py) then writes the real prompt and the real text from those seeds; when it fails or breaks a rule, `compose_prompt` and
the pools below stand in, so a run never stops and never repeats itself either."""
import random
import re

from . import models as M

RECENT = 6                          # a seed is not used again while it is among this many latest videos, when another choice exists

# ── scene look ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
# every choice: key -> (phrase for the picture prompt, a word that must appear when the model writes the prompt)
LIGHT_TAIL = "gently and evenly lit, every detail clearly visible, calm and inviting, not dark and not gloomy."
LIGHT: dict[str, tuple[str, str]] = {
    "moonlit": ("Soft blue moonlit night", "moonlit"),
    "predawn": ("Soft blue pre-dawn light", "dawn"),
    "overcast": ("Soft silver overcast afternoon light under a pale sky", "afternoon"),
    "dusk": ("Warm golden-blue dusk with the last glow of sunset behind the clouds", "dusk"),
    "morning": ("Gentle grey-green early morning light with mist lifting", "morning"),
    "evening": ("Deep blue evening with the first lights coming on", "evening"),
    "break": ("Dim afternoon with a bright break in the clouds lighting the mist", "afternoon"),
    "twilight": ("Violet-blue twilight", "twilight"),
}
LIGHT_ONLY = {"old_town_lane": ["moonlit", "evening", "dusk", "twilight"], "night_city": ["moonlit", "evening", "twilight"]}

SIDES = ["left", "right", "left", "right"]


def _lamps(group: str) -> list[tuple[str, str, str, bool]]:
    """(key, phrase with {side}, must-word, flame) for a group of themes. Phrases say where the lamp is, so two videos of one theme differ."""
    common = [("none", "no lamp in the frame, the only warm glow coming from a few lit windows far away", "window", False)]
    if group == "japan":
        return [("paper", "a paper shoji lantern glowing warm amber at the {side} edge of the frame", "lantern", False),
                ("andon", "a tall paper andon floor lamp glowing softly at the {side} of the frame", "lamp", False),
                ("candle", "a single white candle in a glass jar flickering low at the {side} of the frame", "candle", True),
                ("tea", "a row of small tea lights glowing along the {side} edge of the low table", "tea light", True),
                ("two", "two paper lanterns glowing warm amber, one at each edge of the frame", "lanterns", False)] + common
    if group == "north":
        return [("candle", "a single white candle burning on a nightstand at the {side} edge of the frame", "candle", True),
                ("shade", "a bedside lamp with a linen shade glowing warm at the {side} of the frame", "lamp", False),
                ("string", "tiny warm string lights along the top beam of the frame", "string lights", False),
                ("lantern", "a small metal lantern glowing warm amber on the {side} of the sill", "lantern", True),
                ("none", "no lamp in the frame, only soft daylight and the glow of a far cabin window", "window", False)]
    if group == "india":
        return [("oil", "a small brass oil lamp glowing warm gold on the {side} of the sill", "lamp", True),
                ("candles", "three small candles in brass holders flickering on the {side} of the sill", "candles", True),
                ("hang", "a brass hanging lamp glowing warm at the upper {side} of the frame", "lamp", False),
                ("both", "two small oil lamps glowing warm, one at each edge of the sill", "lamps", True),
                ("string", "tiny warm fairy lights along the top edge of the frame", "fairy lights", False)] + common
    return [("sconce", "a warm wall sconce glowing amber at the {side} edge of the frame", "sconce", False),
            ("lanterns", "hanging lanterns glowing warm along the {side} of the lane", "lanterns", False),
            ("none", "no lamp in the frame, only the glow of the street windows below", "window", False)]


GROUPS = {"night_city": "japan", "bamboo_teahouse": "japan", "mountain_forest": "north", "countryside": "north", "lakeside_porch": "north", "forest": "north",
          "himalayan_ridge": "india", "monastery_window": "india", "kerala_veranda": "india", "courtyard": "india", "ocean": "india", "old_town_lane": "town"}

SEASONS = {
    "japan": [("spring", "fresh spring green with a few pale blossom petals on the wet stone", "blossom"), ("summer", "deep summer green, every leaf heavy with water", "green"),
              ("autumn", "early autumn with a few red maple leaves on the wet stones", "maple"), ("winter", "late winter, bare branches and a light dusting of snow on the stones", "snow")],
    "north": [("summer", "lush midsummer green", "green"), ("autumn", "autumn colour, golden birch leaves and rust-red undergrowth", "autumn"),
              ("early", "early spring, fresh pale-green buds and patches of old snow", "spring"), ("winter", "a light first snow dusting the high ground", "snow")],
    "india": [("monsoon", "deep monsoon green, every leaf shining", "green"), ("spring", "spring bloom with red and pink flowers", "bloom"),
              ("golden", "late-season gold and green after the first cool rains", "gold"), ("snowline", "a fresh dusting of snow on the far ridges", "snow")],
    "town": [("autumn", "autumn, a few fallen leaves shining on the wet cobblestones", "leaves"), ("spring", "spring, flower boxes in bloom on the balconies", "flower"),
             ("winter", "winter, a little frost in the corners of the stones", "frost"), ("summer", "summer, green vines climbing the old walls", "vines")],
}
AIR = [("mist", "thin drifting mist between the foreground and the distance", "mist"), ("fog", "thick low fog filling the valley", "fog"),
       ("clear", "clear still air with the far scenery sharp", "clear"), ("cloud", "a heavy low cloud base hugging the scenery", "cloud")]
CAMERA = [("centre", "a calm symmetrical view with the window or opening in the centre of the frame", "centre"),
          ("left", "the opening sits to the left with a solid wall on the right side of the frame", "left"),
          ("right", "the opening sits to the right with a solid wall on the left side of the frame", "right"),
          ("low", "a low camera just above the blanket, the scenery rising above it", "low"),
          ("high", "a slightly raised camera looking down and out over the scenery", "raised"),
          ("wide", "a wide view with a generous sky and distance", "wide"),
          ("tight", "a closer view that fills the frame with the scenery and only a thin edge of the room", "closer")]
GRADE = [("teal", "teal and amber colour grade", "teal"), ("green", "soft green-grey colour palette", "green-grey"),
         ("blue", "cool blue shadows with warm highlights", "blue"), ("film", "muted natural film colours", "muted")]
THINGS = [("book", "an open paperback book resting on the blanket", "book"), ("mug", "a ceramic mug of tea steaming on the sill", "mug"),
          ("cat", "a small sleeping cat curled on the blanket", "cat"), ("plant", "a small potted plant on the sill", "plant"),
          ("notebook", "a notebook and a pen on the sill", "notebook"), ("glasses", "a pair of reading glasses on an open book", "glasses"), ("none", "", "")]


def _hist_keys(hist: list[dict], slot: str) -> list[str]:
    return [(h.get("look") or {}).get(slot, "") for h in hist[:RECENT]]


def _fresh(options: list, hist_keys: list[str], rng: random.Random, kidx: int = 0):
    """An option not among the recent ones (the one used longest ago when all were); options are tuples whose item `kidx` is the key."""
    recent = [k for k in hist_keys if k]
    fresh = [o for o in options if o[kidx] not in recent]
    if fresh:
        return rng.choice(fresh)
    age = {o[kidx]: (recent.index(o[kidx]) if o[kidx] in recent else 99) for o in options}
    best = max(age.values())
    return rng.choice([o for o in options if age[o[kidx]] == best])


def pick_look(scene: str, hist: list[dict], rng: random.Random) -> dict:
    """The seeds of one scene picture: {light, lamp, side, season, air, camera, grade, thing} (keys), plus `flame` (does the lamp burn)."""
    group = GROUPS.get(scene, "north")
    light_keys = LIGHT_ONLY.get(scene) or list(LIGHT)
    light = _fresh([(k,) for k in light_keys], _hist_keys(hist, "light"), rng)[0]
    lamp = _fresh(_lamps(group), _hist_keys(hist, "lamp"), rng)
    season = _fresh(SEASONS[group], _hist_keys(hist, "season"), rng)
    air = _fresh(AIR, _hist_keys(hist, "air"), rng)
    camera = _fresh(CAMERA, _hist_keys(hist, "camera"), rng)
    grade = _fresh(GRADE, _hist_keys(hist, "grade"), rng)
    thing = _fresh(THINGS, _hist_keys(hist, "thing"), rng)
    return {"light": light, "lamp": lamp[0], "side": rng.choice(SIDES), "season": season[0], "air": air[0], "camera": camera[0], "grade": grade[0], "thing": thing[0],
            "flame": bool(lamp[3])}


def _find(options, key: str, kidx: int = 0):
    return next((o for o in options if o[kidx] == key), options[0])


def look_parts(scene: str, look: dict) -> dict:
    """The words of each seed: {slot: (phrase, [must-words])}."""
    group = GROUPS.get(scene, "north")
    lamp = _find(_lamps(group), look.get("lamp", ""))
    side = look.get("side") or "left"
    lp = lamp[1].format(side=side)
    must_lamp = [lamp[2]] + ([side] if "{side}" in lamp[1] else [])
    season = _find(SEASONS[group], look.get("season", ""))
    air, cam, grade = _find(AIR, look.get("air", "")), _find(CAMERA, look.get("camera", "")), _find(GRADE, look.get("grade", ""))
    thing = _find(THINGS, look.get("thing", ""))
    light = LIGHT.get(look.get("light", "")) or LIGHT["moonlit"]
    return {"light": (light[0], [light[1]]), "lamp": (lp, must_lamp), "season": (season[1], [season[2]]), "air": (air[1], [air[2]]),
            "camera": (cam[1], [cam[2]]), "grade": (grade[1], [grade[2]]), "thing": (thing[1], [thing[2]] if thing[2] else [])}


_LIGHT_SENT = re.compile(r"(Soft|Deep|Gentle|Warm)[^.]*?(light|night|dusk|twilight|evening|morning)[^.]*\.")
_LAMP_RE = re.compile(r"[^,.]*\b(lamp|lantern|candle|sconce)\b[^,.]*(of the frame|on the sill|sill)[^,.]*")


def compose_prompt(scene: str, look: dict, base: str | None = None) -> str:
    """The scene prompt from the base prompt and the seeds, by code alone (the stand-in when the model's prompt is refused): the base prompt keeps its place
    and its rules; the lamp, light, season, air, camera, grade and an extra thing in the frame come from the seeds."""
    base = base or M.SCENES[scene]["prompt"]
    parts = look_parts(scene, look)
    tail = "No people, no text, no logo."
    body = base.replace(tail, "").rstrip()
    m = _LAMP_RE.search(body)
    if m:
        body = body[:m.start()].rstrip() + " " + parts["lamp"][0] + body[m.end():]
    else:
        body += " " + parts["lamp"][0].capitalize() + "."
    body = _LIGHT_SENT.sub("", body)                       # the base light sentence; the seed's replaces it
    extra = [parts["light"][0] + ", " + LIGHT_TAIL, parts["season"][0].capitalize() + ".", parts["air"][0].capitalize() + ".", parts["camera"][0].capitalize() + ".",
             parts["grade"][0].capitalize() + "."]
    if parts["thing"][0]:
        extra.append("Also in the frame: " + parts["thing"][0] + ".")
    return " ".join(body.split()) + " " + " ".join(extra) + " " + tail


# words that put rain in the AIR of the picture; the rain is drawn later by code, so the picture is wet but the air is clear (models.WET)
AIR_RAIN = re.compile(r"\b(falling rain|rain falling|rain(?:drops)? (?:is |are )?falling|downpour|rain streaks?|streaks? of rain|heavy rain|pouring rain|rain pours?|"
                      r"sheets of rain|rain in sheets|raining|rain lines|silver threads|rain threads|torrential)\b", re.I)


def prompt_problems(scene: str, look: dict, text: str) -> list[str]:
    """Why a model-written scene prompt is refused (empty = fine)."""
    t = (text or "").strip()
    low = t.lower()
    out = []
    if not 500 <= len(t) <= 2600:
        out.append("length")
    if "no people, no text, no logo" not in low:
        out.append("missing the closing 'No people, no text, no logo.'")
    if not _only_after_rain(t):
        out.append("rain in the air (the picture is wet, the air clear)")
    if re.search(r"\b(person|people|man|woman|girl|boy|child|figure|silhouette)\b", low.replace("no people", "").replace("first-person", "")):
        out.append("a person is named")
    for slot, (_phrase, musts) in look_parts(scene, look).items():
        for w in musts:
            if w and w.lower() not in low:
                out.append(f"{slot}: '{w}' is not in the prompt")
    own = (LIGHT.get(look.get("light", "")) or LIGHT["moonlit"])[1]
    for other in {v[1] for v in LIGHT.values()} - {own}:
        if other not in ("afternoon",) and re.search(rf"{other}", low):
            out.append(f"light: '{other}' contradicts the chosen light ({own})")
    return out


def _only_after_rain(t: str) -> bool:
    """'after heavy rain' / 'just after heavy rain' is the wet look, not rain in the air."""
    cleaned = re.sub(r"(after|following)\s+(?:the\s+)?(?:steady\s+|tropical\s+|night\s+)?(heavy\s+)?rain", "", t, flags=re.I)
    return not AIR_RAIN.search(cleaned)


# ── thumbnail ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
# The thumbnail is a different PICTURE each time (owner, 2026-11-19: "why do we always show a man or woman with a mug"): the place seen from outside, a wide
# landscape in rain, macro raindrops with bokeh, a still life, an animal, an object, a person walking with an umbrella; a person at the window is the rare one.
# Rain is visible in a thumbnail (it is a still picture, so it may fall in fine lines).
SUBJECT_WEIGHTS = [("exterior", 18), ("landscape", 18), ("macro", 14), ("still", 12), ("animal", 10), ("object", 10), ("walk", 8), ("person", 6), ("back", 4)]
SUBJECTS = [k for k, w in SUBJECT_WEIGHTS for _ in range(w)]
THUMB_PLACES = {
    "night_city": ("a traditional Japanese house with a glowing paper-screen veranda beside a moss garden and a stone lantern", "a hidden moss garden with a koi pond, maples and stone lanterns"),
    "mountain_forest": ("a small wooden Nordic cabin with warm glowing windows among tall spruce and birch", "a vast spruce and birch forest valley with one distant cabin light"),
    "ocean": ("an open-air Balinese villa pavilion with warm lamps above a lotus pond", "terraced jungle hills with palms and rice terraces"),
    "countryside": ("a Swiss alpine chalet with a lit window and wooden shutters under a steep pine slope", "an alpine valley with pine slopes and low cloud"),
    "forest": ("a glass treehouse lit warmly high among giant ancient trees", "an ancient mossy rainforest canopy"),
    "himalayan_ridge": ("a stone and timber mountain lodge with a glowing window and strings of prayer flags", "a Himalayan ridge with snow peaks, pines and prayer flags"),
    "monastery_window": ("a hilltop mountain monastery with golden lit windows above a misty valley", "white stupas and terraced rooftops in a mountain valley"),
    "courtyard": ("a traditional courtyard house with a covered veranda and a brass lamp beside a lotus pond", "a stone courtyard with a lotus pond and a banyan tree"),
    "old_town_lane": ("an old town house with a lit balcony over a cobblestone lane", "a narrow cobblestone lane with glowing lanterns"),
    "kerala_veranda": ("a Kerala house with a red-tiled roof and a lit veranda among coconut palms", "monsoon rice fields with coconut palms"),
    "lakeside_porch": ("a lakeside cabin porch with a lantern glowing over the water", "a calm mountain lake with pine shores"),
    "bamboo_teahouse": ("a Japanese tea house with a glowing paper lantern at the edge of a bamboo grove", "a bamboo grove and a moss garden"),
}
ANIMALS = [("cat", "a fluffy cat curled up asleep on a cushioned windowsill beside a rain-covered window showing {view}"),
           ("dog", "a small sleepy dog curled on a soft rug beside a rain-covered window showing {view}"),
           ("owl", "a brown owl perched on a wet branch under the eaves, {view} blurred behind it"),
           ("deer", "a young deer standing still at the edge of {view}"),
           ("ducks", "a pair of ducks gliding across a rain-rippled pond with {view} behind them"),
           ("kitten", "a tiny kitten asleep in a woollen blanket on a windowsill, rain on the glass behind it showing {view}")]
OBJECTS = [("lantern", "a glowing paper lantern hanging in the rain, {view} soft behind it"),
           ("umbrella", "a red umbrella leaning on a wet wooden railing, {view} soft behind it"),
           ("lamp", "an old brass oil lamp glowing on a wet stone ledge, {view} soft behind it"),
           ("bicycle", "a bicycle with a basket of flowers parked by a wet wall, {view} soft behind it"),
           ("bench", "a wooden bench under the eaves with a folded wool blanket, {view} soft behind it"),
           ("record", "a vinyl record player and a pair of headphones beside a rain-covered window showing {view}"),
           ("boots", "a pair of yellow rain boots by a doorstep, {view} soft behind them")]
WHO = ["woman", "man"]
ETHNIC = ["South Asian", "East Asian", "European", "Black", "Latino", "Southeast Asian", "Middle Eastern", "mixed-heritage"]
OUTFITS = ["an oversized cream knit sweater", "a soft grey hoodie", "a mustard cardigan", "a green flannel shirt", "a white linen shirt under a wool blanket",
           "a dusty-pink knit sweater", "a navy turtleneck", "a rust-coloured cardigan"]
HAIR = {"woman": ["long dark hair", "a messy bun", "short wavy hair", "long wavy brown hair", "a loose braid", "curly hair"],
        "man": ["short dark hair", "tousled hair", "short curly hair", "a short beard and tousled hair", "medium-length wavy hair", "short neat hair"]}
ACTIVITY = {
    "sleep": "lying in bed under a thick blanket with eyes gently closed and headphones on, a faint peaceful smile",
    "study": "sitting at a window desk with an open notebook, headphones around the neck, looking up at the rain with a content smile",
    "work": "sitting with a laptop on the knees by the window, headphones on, relaxed, looking out at the rain for a moment",
    "read": "reading a paperback book in a cushioned armchair by the window, a calm smile",
    "calm": "sitting by the window with eyes closed, a deep calm smile, headphones around the neck",
    "noise": "wearing headphones with eyes closed, shoulders relaxed, a peaceful smile",
    "meditate": "sitting cross-legged on a cushion with eyes closed and hands resting on the knees, serene",
    "rainy": "wrapped in a blanket looking out at the rain with a warm smile",
    "late": "sitting up in the lamp light with headphones, a soft sleepy smile, looking at the rain outside",
}
THUMB_LIGHT = ["warm golden lamp light against the cool blue rainy dusk", "soft silver grey daylight on a rainy afternoon", "peach and rose sunset glow through the clouds and rain",
               "deep blue moonlit night with warm lights glowing", "soft green-grey misty morning light", "violet twilight with warm lights glowing"]
SIDES_T = ["right", "left", "right", "left", "centre"]
LAYOUTS = ["side", "bottom", "top", "badge", "stack"]
FONTS = [("impact.ttf", "Impact"), ("georgiab.ttf", "Georgia Bold"), ("segoeuib.ttf", "Segoe UI Bold"), ("bahnschrift.ttf", "Bahnschrift"), ("trebucbd.ttf", "Trebuchet Bold"),
         ("constanb.ttf", "Constantia Bold"), ("arialbd.ttf", "Arial Bold")]
PALETTES = [((255, 255, 255), (255, 214, 130)), ((255, 244, 224), (255, 170, 120)), ((240, 250, 255), (150, 210, 255)), ((255, 255, 255), (170, 235, 190)),
            ((255, 250, 240), (255, 205, 90)), ((250, 240, 255), (220, 180, 255))]
PERSON_SUBJECTS = ("person", "back", "walk")


def pick_thumb(angle: str, scene: str, hist: list[dict], rng: random.Random) -> dict:
    """The seeds of one thumbnail: what the picture is of, the side the subject is on, the layout of the words, the font, the colours (and, for a person, who and what they do)."""
    last = [(h.get("thumb") or {}) for h in hist[:RECENT]]

    def fresh(options, slot, window=RECENT):
        recent = [t.get(slot) for t in last][:window]
        pool = [o for o in options if o not in recent]
        return rng.choice(pool or options)
    recent_subjects = [t.get("subject") for t in last][:3]
    pool = [s for s in SUBJECTS if s not in recent_subjects] or SUBJECTS                 # not one of the last three kinds of picture
    subject = rng.choice(pool)
    who = fresh(WHO, "who", 2)
    animal = fresh([a[0] for a in ANIMALS], "animal")
    obj = fresh([o[0] for o in OBJECTS], "object")
    return {"subject": subject, "who": who, "ethnic": rng.choice(ETHNIC), "age": rng.choice(["in their twenties", "in their early thirties"]), "outfit": rng.choice(OUTFITS),
            "hair": rng.choice(HAIR[who]), "activity": angle if angle in ACTIVITY else "calm", "light": rng.choice(THUMB_LIGHT), "side": fresh(SIDES_T, "side", 2),
            "layout": fresh(LAYOUTS, "layout", 2), "font": fresh([f[0] for f in FONTS], "font", 3), "palette": rng.randrange(len(PALETTES)), "animal": animal, "object": obj}


def _entry(pool, key):
    return next((x for x in pool if x[0] == key), pool[0])


def thumb_prompt(scene: str, t: dict) -> str:
    """The picture prompt of a thumbnail from its seeds (the stand-in for the model's prompt, and the model's starting point)."""
    view = M.THUMB_VIEWS.get(scene) or M.THUMB_VIEWS[M.DEFAULT_SCENE]
    ext, wide = THUMB_PLACES.get(scene) or THUMB_PLACES["courtyard"]
    side = t.get("side", "right")
    sub = t.get("subject", "exterior")
    light = t.get("light", THUMB_LIGHT[0])
    open_side = {"right": "left", "left": "right"}.get(side, "")
    comp = (f"composed with the main subject on the {side} and calm, softer open space on the {open_side}" if open_side else "composed with the main subject in the upper two thirds and calm open space below")
    rain = "soft rain falling in fine silver lines, wet shining surfaces, drifting mist"
    if sub == "exterior":
        body = f"{ext[0].upper() + ext[1:]}, seen from outside, warm light glowing in the windows, {rain}, reflections on the wet ground"
    elif sub == "landscape":
        body = f"A wide cinematic view of {wide}, {rain}, one tiny warm light glowing in the distance"
    elif sub == "macro":
        body = f"Extreme close-up macro of raindrops on window glass, each drop a tiny lens showing {view} upside down, soft glowing warm bokeh lights behind, shallow depth of field"
    elif sub == "still":
        body = f"A steaming mug of tea, an open book and a small glowing candle on a windowsill, rain on the glass behind showing {view}"
    elif sub == "animal":
        a = _entry(ANIMALS, t.get("animal", "cat"))
        body = f"{a[1].format(view=view)[0].upper() + a[1].format(view=view)[1:]}, {rain if a[0] in ('owl', 'deer', 'ducks') else 'raindrops running down the glass'}"
    elif sub == "object":
        o = _entry(OBJECTS, t.get("object", "lantern"))
        body = f"{o[1].format(view=view)[0].upper() + o[1].format(view=view)[1:]}, {rain}"
    elif sub == "walk":
        body = f"A person seen from behind holding a clear umbrella, walking slowly through {wide}, {rain}"
    elif sub == "back":
        body = (f"A person seen from behind, wrapped in {t.get('outfit', OUTFITS[0])} and a blanket, sitting at a large rain-covered window looking out at {view}, "
                "raindrops running down the glass")
    else:
        who = f"A happy young {t.get('who', 'woman')} {t.get('age', 'in their twenties')}, {t.get('ethnic', 'South Asian')}, with {t.get('hair', 'short dark hair')}, wearing {t.get('outfit', OUTFITS[0])}, {ACTIVITY.get(t.get('activity'), ACTIVITY['calm'])}"
        body = f"{who}, seen in a three-quarter view beside a large rain-covered window showing {view}"
    return (f"{body}. {comp}. {light.capitalize()}. Photorealistic, cinematic, shallow depth of field, rich colour, a calm and uplifting mood, a clear single focal point. "
            + ("No text, no logo." if sub in PERSON_SUBJECTS else "No people, no text, no logo."))


def thumb_problems(t: dict, text: str) -> list[str]:
    low = (text or "").lower()
    out = []
    if not 250 <= len(text or "") <= 1800:
        out.append("length")
    if "no text" not in low:
        out.append("missing 'No text, no logo.'")
    if "rain" not in low:
        out.append("the rain must be visible in the picture: say it")
    sub = t.get("subject", "exterior")
    must = {"person": [t.get("who", "woman")], "back": ["behind"], "walk": ["umbrella"], "exterior": ["outside"], "landscape": ["wide"], "macro": ["macro"], "still": ["mug"],
            "animal": [t.get("animal", "cat")], "object": [(_entry(OBJECTS, t.get("object", "lantern"))[0])]}.get(sub, [])
    for w in must:
        if w.lower() not in low:
            out.append(f"'{w}' is not in the prompt")
    if sub not in PERSON_SUBJECTS and re.search(r"\b(woman|man|girl|boy|person|people)\b", low.replace("no people", "")):
        out.append("a person in a picture that has none")
    return out


# ── the angle of the text ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
# who it is for, when and where it is played, why, how; title patterns; the words on the thumbnail. Nothing here claims a health result.
ANGLES: dict[str, dict] = {
    "sleep": {
        "label": "sleeping",
        "titles": ["{L} Rain Sounds for Sleeping | {Place}", "Fall Asleep to Rain at {Place} | {L}, Soft {Ins}", "{L} of Rain & Soft {Ins} for Deep Sleep | {Place}"],
        "headlines": ["RAIN TO SLEEP", "BEDTIME RAIN", "SLEEP TO RAIN", "DEEP SLEEP RAIN"], "tail": "DEEP SLEEP",
        "audience": ["light sleepers who wake at small sounds", "anyone winding down after a long day", "people who live on a noisy street", "night-shift workers sleeping in the day",
                     "travellers in a hotel room that is not quiet"],
        "when": ["at bedtime, about half an hour before you want to be asleep", "through the whole night: it plays for {L_lower} (a sleep timer in the app stops it when you like)",
                 "for an afternoon nap"],
        "where": "bedroom, hotel room, guest room or any quiet corner", "why": "steady rain is an even sound that can cover small noises around you",
        "tags": ["rain sounds for sleeping", "sleep music", "deep sleep rain", "rain for bedtime", "fall asleep to rain"]},
    "study": {
        "label": "studying",
        "titles": ["Study With Rain & Soft {Ins} | {L} at {Place}", "{L} Rain Sounds for Studying & Focus | {Place}", "Calm Focus Rain at {Place} | {L} Study Session"],
        "headlines": ["STUDY WITH RAIN", "STUDY SESSION", "FOCUS RAIN", "EXAM WEEK RAIN"], "tail": "STUDY & FOCUS",
        "audience": ["students preparing for exams", "anyone who studies better with steady background sound", "readers working through a long book", "people studying in a shared room",
                     "writers and note-takers"],
        "when": ["at the start of a long study block, to settle in", "late-night revision when the house is quiet", "for {L_lower} of uninterrupted work, without a track change to pull you out"],
        "where": "desk, library corner, dorm room or kitchen table", "why": "there are no lyrics, so the words you are reading stay yours",
        "tags": ["study with rain", "study music", "focus rain sounds", "rain for studying", "deep focus"]},
    "work": {
        "label": "working",
        "titles": ["{L} Rain Ambience for Work & Deep Focus | {Place}", "Work From Home Rain Sounds | {L} at {Place}", "Focus Music With Rain & {Ins} | {L}, {Place}"],
        "headlines": ["DEEP WORK RAIN", "WORK FROM HOME", "FOCUS MODE", "CODE WITH RAIN"], "tail": "DEEP WORK",
        "audience": ["remote workers and freelancers", "programmers and designers in a long session", "people in an open-plan office with headphones", "anyone who wants a calm background for emails and writing"],
        "when": ["on a morning work block, before the day gets loud", "through a long afternoon of focused tasks", "for {L_lower} on one tab, with no track changes you have to manage"],
        "where": "home office, co-working space, cafe or on the train with headphones", "why": "a soft, even sound keeps the room from feeling empty without competing for attention",
        "tags": ["rain sounds for work", "focus music", "deep work", "work from home music", "coding music"]},
    "read": {
        "label": "reading",
        "titles": ["Reading Nook Rain Sounds | {L} at {Place}", "Read by the Window in the Rain | {L} of Soft {Ins}", "{L} Cozy Rain & {Ins} for Reading | {Place}"],
        "headlines": ["READING NOOK", "READ WITH RAIN", "BOOK & RAIN", "COZY READING"], "tail": "COZY READING",
        "audience": ["book lovers on a slow afternoon", "anyone with a blanket, a tea and a long novel", "readers who like a little sound but no singing"],
        "when": ["on a rainy weekend afternoon", "for an evening chapter before bed", "on a lazy Sunday morning with a hot drink"],
        "where": "armchair, window seat, bed or a corner of the sofa", "why": "the rain fills the room without words that pull you off the page",
        "tags": ["reading music", "rain and reading", "cozy reading ambience", "book ambience", "rainy day reading"]},
    "calm": {
        "label": "unwinding",
        "titles": ["Calm Your Mind: {L} of Rain at {Place}", "{L} Relaxing Rain & {Ins} to Unwind After a Long Day", "Unwind to Rain Sounds at {Place} | {L}"],
        "headlines": ["UNWIND", "CALM YOUR MIND", "SOFT RAIN", "SLOW DOWN"], "tail": "RELAX",
        "audience": ["anyone coming home after a long day", "people who want ten quiet minutes that turn into an hour", "anyone who has not sat still all week"],
        "when": ["right after work, before the evening starts", "during a bath or a slow cup of tea", "any time you want the day to go quieter"],
        "where": "sofa, bath, balcony or bedroom", "why": "slow, gentle sound is an easy way to mark the end of a busy day",
        "tags": ["relaxing rain", "calming rain sounds", "unwind music", "relaxation music", "relaxing rain ambience"]},
    "noise": {
        "label": "blocking noise",
        "titles": ["Rain Sounds to Block Out Noise | {L} at {Place}", "{L} Rain White Noise for a Quiet Room | {Place}", "Mask City Noise With Rain | {L}, {Place}"],
        "headlines": ["BLOCK THE NOISE", "QUIET ROOM", "CITY NOISE OFF", "RAIN NOISE"], "tail": "QUIET ROOM",
        "audience": ["city dwellers with traffic outside", "people with loud neighbours", "light sleepers and households that need a steady backdrop", "anyone working near a busy street"],
        "when": ["when the street is loudest", "at night when every small sound seems close", "for {L_lower} of steady cover while you work or rest"],
        "where": "a flat on a main road, a shared house or an open office", "why": "a steady, even sound makes sudden noises stand out less",
        "tags": ["rain white noise", "block out noise", "noise masking rain", "rain sounds for noisy neighbours", "quiet room"]},
    "meditate": {
        "label": "meditation",
        "titles": ["{L} Rain Meditation Music | Soft {Ins} at {Place}", "Rain & {Ins} for Meditation, Yoga & Stretching | {L}", "Mindful Rain Sounds at {Place} | {L}"],
        "headlines": ["MEDITATION RAIN", "MINDFUL RAIN", "BREATHE & LISTEN", "YOGA RAIN"], "tail": "MEDITATE",
        "audience": ["people who meditate or do yoga at home", "beginners who find silence hard", "anyone who wants a slow soundtrack for stretching or breathing"],
        "when": ["at sunrise before the day begins", "for a sitting practice of any length (the video runs {L_lower})", "in the evening to close the day"],
        "where": "yoga mat, cushion by the window or a quiet room", "why": "a soft, slow sound gives the mind one calm thing to follow",
        "tags": ["meditation music", "rain meditation", "yoga music", "mindfulness rain", "breathing music"]},
    "rainy": {
        "label": "a rainy day",
        "titles": ["Rainy Day at {Place} | {L} of Cozy Rain Ambience", "Cozy Rainy Afternoon at {Place} | {L}, Soft {Ins}", "Rainy Sunday Mood | {L} of Rain at {Place}"],
        "headlines": ["RAINY DAY", "COZY RAIN", "RAINY SUNDAY", "STAY IN"], "tail": "COZY DAY",
        "audience": ["anyone who loves a rainy day indoors", "people who miss the rain where they live now", "anyone who wants a cozy room without leaving home"],
        "when": ["on a grey weekend afternoon", "when it is sunny outside and you wish it were not", "on a slow morning with coffee"],
        "where": "living room, cafe-style corner, balcony or a cozy bedroom", "why": "it brings the feeling of a rainy day to a room that has none",
        "tags": ["rainy day ambience", "cozy rain", "rain ambience", "rainy sunday", "cozy ambience"]},
    "late": {
        "label": "late nights",
        "titles": ["Late Night Rain at {Place} | {L} of Soft {Ins}", "{L} Rain Sounds for Late Nights | {Place}", "Midnight Rain Ambience at {Place} | {L}"],
        "headlines": ["LATE NIGHT RAIN", "MIDNIGHT RAIN", "NIGHT OWL", "AFTER MIDNIGHT"], "tail": "LATE NIGHT",
        "audience": ["night owls working or reading after midnight", "people who cannot switch off at night", "anyone awake while the rest of the house sleeps"],
        "when": ["after midnight, when the house goes quiet", "on a long night shift or a night of gaming", "when you are not sleepy yet but the day is over"],
        "where": "desk lamp corner, bedroom or kitchen table", "why": "a gentle, low sound keeps the night company without waking the house",
        "tags": ["late night rain", "midnight rain", "night ambience", "night owl music", "rain at night"]},
}
INSTRUMENT_TEXT = {"soft piano": "slow, soft piano notes", "harp": "gentle harp arpeggios", "bamboo flute": "a breathy bamboo flute melody", "kalimba": "soft kalimba plucks",
                   "flute": "a warm, airy flute melody", "nylon guitar": "slow nylon-string guitar", "vibraphone": "a soft vibraphone", "singing bowls": "slow singing bowls",
                   "other": "soft instrumental music"}


def pick_angle(hist: list[dict], rng: random.Random) -> str:
    """The angle least used lately (never the previous video's)."""
    recent = [h.get("angle", "") for h in hist[:RECENT]]
    fresh = [a for a in ANGLES if a not in recent]
    if fresh:
        return rng.choice(fresh)
    age = {a: (recent.index(a) if a in recent else 99) for a in ANGLES if a != (recent[0] if recent else "")}
    best = max(age.values())
    return rng.choice([a for a in age if age[a] == best])
