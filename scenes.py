"""Scene planning: one explanatory visual per narration beat, with episode-wide de-duplication
(no repeated on-image text, no near-identical scenes)."""
import re

from content import extract_json


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


async def plan_scenes(chat, topic: str, role: str, beats: list[str], mem: Memory) -> list[dict]:
    numbered = "\n".join(f"{i+1}. {b}" for i, b in enumerate(beats))
    shown = "\n".join(f"- {v[:90]}" for v in mem.visuals[-14:]) or "- (none yet)"
    used = ", ".join(sorted(mem.texts)) or "(none yet)"
    prompt = f"""You are the art director of an illustrated explainer video. Topic: {topic or 'news'}. Segment role: {role}.
A narrator says the beats below, in order; each beat gets ONE still image shown while it is spoken.

Beats (Hinglish narration):
{numbered}

For each beat design an image that VISUALLY EXPLAINS what is being said in that beat: a metaphor, a simple diagram made of
shapes and icons, a before/after contrast, an object or scene that makes the idea obvious. A viewer with the sound off
should still get the point. Keep one visual world across the story but make every image look different from the others.
Rules:
- Describe the scene in English, 1-2 sentences, concrete subjects, where things are, camera distance. No style or colour
  words (they are added later).
- Every image must be NEW. Already used in this episode, do not repeat or paraphrase these:
{shown}
- Never show faces or hands in close-up. People only as small figures, silhouettes or from behind.
- Screens, charts, maps, books, documents and blackboards must be abstract (shapes, bars, icons, blank pages): never
  describe anything that would need small readable writing.
- Single full-frame image: no comic panels, no split screens, no multi-panel layouts.
- On-image text ONLY where it truly helps (a key number, a name, a short question): "text" is 1-3 words, English letters and
  digits only, otherwise "". Use text in at most 3 of every 10 beats. Texts already used, never reuse: {used}
Return ONLY JSON: {{"scenes": [{{"beat": 1, "visual": "...", "text": ""}}]}} with exactly {len(beats)} scenes."""
    scenes: list[dict] = []
    try:
        data = extract_json(await chat([{"role": "user", "content": prompt}],
                                       response_format={"type": "json_object"}, max_tokens=4000))
        for s in data.get("scenes", []):
            v = str(s.get("visual", "")).strip()
            if v:
                scenes.append({"visual": v, "text": _clean_text(s.get("text"))})
    except Exception:
        pass
    fallback = ["wide establishing view of the topic", "symbolic object representing the idea", "abstract diagram of the idea"]
    while len(scenes) < len(beats):
        scenes.append({"visual": f"{topic or 'the story'}: {fallback[len(scenes) % 3]}", "text": ""})
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
