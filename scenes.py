"""Scene planning: one cinematic shot per narration beat.
For cinematic style: full shot-list schema (shot scale, angle, lighting, subject, environment, layers).
For illustrated styles: abstract visual metaphor schema (visual, mood).
Episode-wide de-duplication prevents repeated environments or near-identical compositions.
"""
import re

from content import extract_json


class Memory:
    """What the episode has already shown, shared across segments."""
    def __init__(self):
        self.texts: set[str] = set()
        self.visuals: list[str] = []        # stores subject+environment summary for dedup
        self.environments: list[str] = []   # tracks environments used so we rotate them


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _tokens(visual: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", visual.lower())}


def _similar(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / max(1, len(ta | tb))


def _clean_text(raw, cinematic: bool = False) -> str:
    """For cinematic: allow short sentence (up to 10 words). For illustrated: 1-4 word label."""
    t = re.sub(r"[^A-Za-z0-9 %$&+?!.,'/-]", "", str(raw or "")).strip()
    limit = 10 if cinematic else 4
    return t if len(t.split()) <= limit else " ".join(t.split()[:limit])


def _find_duplicate(summary: str, seen: list[str]) -> bool:
    for v in seen:
        if _similar(summary, v) >= 0.4:
            return True
    return False


_MOOD_HINT = {
    "dramatic":  "tense, high-contrast compositions with strong diagonal lines",
    "serious":   "still and weighty — low horizon, minimal movement",
    "calm":      "open and spacious — soft diffuse light, room to breathe",
    "excited":   "dynamic and kinetic — energetic angles, implied motion",
    "concerned": "heavy overcast atmosphere, unresolved tension in the frame",
    "neutral":   "balanced, clear compositions",
}

_GEO_INDIA = (
    "The story is set in India. Where the beat calls for a real-world setting, "
    "use Indian locations: South Asian office interiors, Indian street textures (auto-rickshaws, chai stalls, "
    "neon hoardings), Kerala/Mumbai/Delhi-specific architecture, rupee ₹ symbol for money. "
    "Apply only where it genuinely fits — never force Indian imagery onto abstract or metaphorical beats."
)

# Shot scale glossary given to the model so it uses consistent notation
_SHOT_GLOSSARY = (
    "Shot scale: ECU (extreme close-up, single feature — eye, hand), "
    "CU (close-up, face fills frame), MCU (medium close-up, head and shoulders), "
    "MS (medium shot, waist up), MLS (medium long shot, full body), "
    "LS (long shot, figure in environment), ELS (extreme long shot, tiny figure, vast space)."
)


async def _rewrite_cinematic(chat, beat: str, current: str, clash: str) -> str:
    prompt = (
        f"Narration beat: {beat}\n"
        f"Current shot description: {current}\n"
        f"Too similar to an earlier shot: {clash}\n"
        "Write a completely different cinematic shot for the same beat — different environment, "
        "different camera angle, different action. Keep the same protagonist. "
        "Return ONLY one short paragraph describing the new shot."
    )
    try:
        return (await chat([{"role": "user", "content": prompt}], max_tokens=400, temperature=0.9)).strip()
    except Exception:
        return current


async def _rewrite_illustrated(chat, beat: str, visual: str, clash: str) -> str:
    prompt = (
        f"Narration beat: {beat}\nCurrent image idea: {visual}\nToo similar to an earlier image: {clash}\n"
        "Write ONE new image idea (1-2 sentences, English) with a completely different subject, metaphor and "
        "composition. No faces, no readable text. Return ONLY the sentence."
    )
    try:
        return (await chat([{"role": "user", "content": prompt}], max_tokens=400, temperature=0.9)).strip().strip('"')
    except Exception:
        return visual


async def plan_scenes(chat, topic: str, role: str, beats: list[str], mem: Memory,
                      emotion: str = "neutral", geo: str = "auto",
                      character_bible: dict | None = None,
                      style: str = "graphic-novel") -> list[dict]:

    numbered = "\n".join(f"{i+1}. {b}" for i, b in enumerate(beats))
    mood     = _MOOD_HINT.get(emotion, _MOOD_HINT["neutral"])
    geo_line = f"\n\nCultural context: {_GEO_INDIA}" if geo == "india" else ""
    n        = len(beats)
    is_cinematic = (style == "cinematic")

    if is_cinematic:
        return await _plan_cinematic(chat, topic, role, beats, mem, emotion, mood, geo_line,
                                     character_bible or {}, numbered, n)
    else:
        return await _plan_illustrated(chat, topic, role, beats, mem, emotion, mood, geo_line,
                                       numbered, n)


async def _plan_cinematic(chat, topic, role, beats, mem, emotion, mood,
                          geo_line, bible, numbered, n) -> list[dict]:
    protagonist = bible.get("protagonist", {})
    char_desc   = protagonist.get("description", "Indian professional, early 30s")
    char_arc    = protagonist.get("arc", "")
    envs        = "\n".join(f"  - {e}" for e in bible.get("environments", []))
    tone_arc    = bible.get("tone_arc", "")
    shown_envs  = ", ".join(mem.environments[-6:]) or "(none yet)"
    shown_shots = "\n".join(f"  - {v[:100]}" for v in mem.visuals[-10:]) or "  - (none yet)"

    prompt = f"""You are a film director planning shot-by-shot coverage for a cinematic documentary segment.

STORY: {topic or 'today\'s news'}
SEGMENT ROLE: {role}
SEGMENT MOOD: {emotion} — aim for {mood}
{_SHOT_GLOSSARY}

PROTAGONIST: {char_desc}
CHARACTER ARC: {char_arc}
TONE ARC: {tone_arc}

AVAILABLE ENVIRONMENTS:
{envs}
{geo_line}

SHOTS ALREADY USED THIS EPISODE (avoid repeating these compositions or environments):
{shown_shots}
ENVIRONMENTS RECENTLY USED (rotate away from these): {shown_envs}

BEATS TO COVER (narrator speaks these in order):
{numbered}

INSTRUCTIONS:
Think carefully about each beat before designing its shot. Ask yourself:
  — What should the viewer FEEL here, not just understand?
  — What is the subtext beneath the spoken words?
  — Which shot scale and angle best delivers that feeling?
  — What is the protagonist doing or feeling in this exact moment?
  — What details in the foreground and background deepen the meaning?
  — What lighting tells the emotional story?

Rules:
- Use the protagonist in shots where a human presence serves the beat. Not every shot needs them.
- Faces ARE allowed and encouraged for emotional beats (fear, confidence, resolve).
- Never invent a new character — only the protagonist or anonymous background figures.
- Environments must feel real and specific — no abstract voids or flat courtyards.
- "text": a short phrase or question (max 8 words, Latin/digits only) that appears on screen as a subtitle.
  Use ONLY where it genuinely sharpens the beat — max 2 per segment. Otherwise "".
  Text already used this episode, never reuse: {', '.join(sorted(mem.texts)) or '(none)'}
- "mood": one word — warm / cool / bright / muted / high-contrast / unsettling / hopeful.

Return ONLY JSON with exactly {n} scene objects:
{{"scenes": [{{"beat": 1, "shot": "MCU", "angle": "eye-level", "lighting": "...", "subject": "...", "environment": "...", "layers": "foreground: ... midground: ... background: ...", "text": "", "mood": "cool"}}]}}"""

    scenes: list[dict] = []
    try:
        data = extract_json(await chat([{"role": "user", "content": prompt}],
                                       response_format={"type": "json_object"}, max_tokens=4000))
        for s in data.get("scenes", []):
            if s.get("subject") or s.get("environment"):
                scenes.append({
                    "shot":        str(s.get("shot", "MS")).upper(),
                    "angle":       str(s.get("angle", "eye-level")),
                    "lighting":    str(s.get("lighting", "")),
                    "subject":     str(s.get("subject", "")),
                    "environment": str(s.get("environment", "")),
                    "layers":      str(s.get("layers", "")),
                    "text":        _clean_text(s.get("text"), cinematic=True),
                    "mood":        str(s.get("mood", "")).lower(),
                })
    except Exception:
        pass

    # fallback: generate minimal cinematic scene if planner fell short
    envs_list = bible.get("environments", ["modern office"])
    while len(scenes) < n:
        env = envs_list[len(scenes) % len(envs_list)]
        scenes.append({
            "shot": "MS", "angle": "eye-level",
            "lighting": "natural light",
            "subject": f"protagonist in {env}, thoughtful expression",
            "environment": env,
            "layers": f"foreground: out-of-focus elements; midground: protagonist; background: {env}",
            "text": "", "mood": "neutral"
        })
    scenes = scenes[:n]

    # episode-wide dedup
    for beat, sc in zip(beats, scenes):
        summary = f"{sc['environment']} {sc['subject']}"
        k = _key(sc["text"])
        if k and k in mem.texts:
            sc["text"] = ""
        if _find_duplicate(summary, mem.visuals):
            sc["subject"] = await _rewrite_cinematic(chat, beat, summary, mem.visuals[-1])
        if sc["text"]:
            mem.texts.add(_key(sc["text"]))
        mem.visuals.append(summary)
        if sc["environment"]:
            mem.environments.append(sc["environment"][:60])

    return scenes


async def _plan_illustrated(chat, topic, role, beats, mem, emotion, mood,
                            geo_line, numbered, n) -> list[dict]:
    shown = "\n".join(f"- {v[:90]}" for v in mem.visuals[-14:]) or "- (none yet)"
    used  = ", ".join(sorted(mem.texts)) or "(none yet)"

    prompt = f"""You are the art director of an illustrated explainer video. Topic: {topic or 'news'}. Segment role: {role}.
Segment mood: {emotion} — aim for {mood}.{geo_line}
A narrator says the beats below, in order; each beat gets ONE still image shown while it is spoken.

Beats (Hinglish narration):
{numbered}

For each beat design an image that VISUALLY EXPLAINS what is being said: a metaphor, a simple diagram of shapes and icons,
a before/after contrast, or a scene that makes the idea obvious without sound.
Rules:
- Describe the scene in English, 1-2 sentences. Concrete subjects, spatial positions, camera distance.
- No style or colour words — those are added later.
- Every image must be visually distinct. Already shown this episode — do NOT repeat or paraphrase:
{shown}
- People only as small figures, silhouettes or from behind. No close-up faces or hands.
- Screens, charts, maps, books must be abstract (shapes, bars, icons): no small readable writing inside.
- Single full-frame image only. No comic panels, no split screens.
- "text": short phrase or question (max 8 words, Latin/digits only) only where it adds real value. Max 2 per segment.
  Already used — never reuse: {used}
- "mood": one word — warm / cool / bright / muted / high-contrast.
Return ONLY JSON: {{"scenes": [{{"beat": 1, "visual": "...", "text": "", "mood": "warm"}}]}} with exactly {n} scenes."""

    scenes: list[dict] = []
    try:
        data = extract_json(await chat([{"role": "user", "content": prompt}],
                                       response_format={"type": "json_object"}, max_tokens=4000))
        for s in data.get("scenes", []):
            v = str(s.get("visual", "")).strip()
            if v:
                scenes.append({"visual": v, "text": _clean_text(s.get("text")),
                               "mood": str(s.get("mood", "")).lower()})
    except Exception:
        pass

    fallback = ["wide establishing view of the topic",
                "symbolic object representing the idea",
                "abstract diagram of the idea"]
    while len(scenes) < n:
        scenes.append({"visual": f"{topic or 'the story'}: {fallback[len(scenes) % 3]}",
                       "text": "", "mood": ""})
    scenes = scenes[:n]

    for beat, sc in zip(beats, scenes):
        k = _key(sc["text"])
        if k and k in mem.texts:
            sc["text"] = ""
        if _find_duplicate(sc["visual"], mem.visuals):
            sc["visual"] = await _rewrite_illustrated(chat, beat, sc["visual"], mem.visuals[-1])
        if sc["text"]:
            mem.texts.add(_key(sc["text"]))
        mem.visuals.append(sc["visual"])

    return scenes
