"""Scene planning: one explanatory visual per narration beat, with episode-wide de-duplication
(no repeated on-image text, no near-identical scenes)."""
import re

from content import extract_json

_MOOD_HINT = {
    "dramatic":  "tense, high-contrast compositions with strong diagonal lines",
    "serious":   "still and weighty scenes, minimal movement, low horizon",
    "calm":      "open, spacious scenes with soft diffuse light",
    "excited":   "dynamic layouts with energetic implied motion and radiating shapes",
    "concerned": "heavy overcast atmosphere, unresolved tension in the composition",
    "neutral":   "balanced, clear compositions",
}

_GEO_INDIA = (
    "The story is set in India. Where the beat naturally calls for it, include culturally specific visual cues: "
    "South Asian architecture (tiled roofs, courtyard homes, bazaar streets), tropical light, coconut/banyan trees, "
    "rupee ₹ symbol for money amounts, Indian urban or rural textures. "
    "Apply only when it genuinely fits the beat — never force Indian imagery onto abstract or metaphorical ideas."
)


class Memory:
    """What the episode has already shown, shared across segments."""
    def __init__(self):
        self.texts: set[str] = set()
        self.visuals: list[str] = []


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _tokens(visual: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", visual.lower())}


def _similar(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / max(1, len(ta | tb))


def _clean_text(raw) -> str:
    t = re.sub(r"[^A-Za-z0-9 %$&+?!.,'/-]", "", str(raw or "")).strip()
    return t if len(t.split()) <= 4 else " ".join(t.split()[:4])


def _find_duplicate(visual: str, seen: list[str]) -> str | None:
    for v in seen:
        if _similar(visual, v) >= 0.45:
            return v
    return None


async def _rewrite(chat, beat: str, visual: str, clash: str) -> str:
    prompt = (f"Narration beat: {beat}\nCurrent image idea: {visual}\nIt is too similar to an earlier image: {clash}\n"
              "Write ONE new image idea (1-2 sentences, English) that explains the same beat with a completely different "
              "subject, metaphor and composition. No faces, no readable text, no maps or documents with writing. "
              "Return ONLY the sentence.")
    try:
        out = (await chat([{"role": "user", "content": prompt}], max_tokens=1500, temperature=0.9)).strip().strip('"')
        return out or visual
    except Exception:
        return visual


async def plan_scenes(chat, topic: str, role: str, beats: list[str], mem: Memory,
                      emotion: str = "neutral", geo: str = "auto") -> list[dict]:
    numbered = "\n".join(f"{i+1}. {b}" for i, b in enumerate(beats))
    shown = "\n".join(f"- {v[:90]}" for v in mem.visuals[-14:]) or "- (none yet)"
    used = ", ".join(sorted(mem.texts)) or "(none yet)"
    mood = _MOOD_HINT.get(emotion, _MOOD_HINT["neutral"])
    geo_line = f"\nCultural context: {_GEO_INDIA}" if geo == "india" else ""
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
- "text": 1-3 word English/digit label only where it adds real value (key number, sharp question). Max 3 per 10 beats.
  Already used text — never reuse: {used}
- "mood": one word — warm / cool / bright / muted / high-contrast — matching how this beat should feel.
Return ONLY JSON: {{"scenes": [{{"beat": 1, "visual": "...", "text": "", "mood": "warm"}}]}} with exactly {len(beats)} scenes."""
    scenes: list[dict] = []
    try:
        data = extract_json(await chat([{"role": "user", "content": prompt}],
                                       response_format={"type": "json_object"}, max_tokens=4000))
        for s in data.get("scenes", []):
            v = str(s.get("visual", "")).strip()
            if v:
                scenes.append({"visual": v, "text": _clean_text(s.get("text")),
                               "mood": str(s.get("mood", "")).strip().lower()})
    except Exception:
        pass
    fallback = ["wide establishing view of the topic", "symbolic object representing the idea", "abstract diagram of the idea"]
    while len(scenes) < len(beats):
        scenes.append({"visual": f"{topic or 'the story'}: {fallback[len(scenes) % 3]}", "text": "", "mood": ""})
    scenes = scenes[:len(beats)]

    # episode-wide de-duplication
    for beat, sc in zip(beats, scenes):
        k = _key(sc["text"])
        if k and k in mem.texts:
            sc["text"] = ""                                  # same message already shown: image goes without text
        clash = _find_duplicate(sc["visual"], mem.visuals)
        if clash:
            sc["visual"] = await _rewrite(chat, beat, sc["visual"], clash)
        if sc["text"]:
            mem.texts.add(_key(sc["text"]))
        mem.visuals.append(sc["visual"])
    return scenes
