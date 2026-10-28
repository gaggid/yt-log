"""Voice engines. Maya (default for new plans), Veena and Svara sit behind the same gateway; this module is the one place that knows their voices, how the spoken text is
built for each, and what a request looks like. The choice is stored on the plan (`narrator.tts`) outside the content hash: picking another voice
never un-approves a plan, it only makes the old takes stop counting (their hash carries the voice key).

* Maya has inline emotion and sound tags in square brackets (`story2/maya.py`); the storyboard suggests them per scene. Its text is built from the
  sentences and their `tag`, and may be sent as several requests when it is long.
* Veena has no emotion tags. Pauses come from punctuation (`...` `,` `?` `—`) and `[pause:Ns]`. Text is built from the sentences, so a plan written
  for Svara (emotion tags in `annotated`) speaks fine in Veena.
* Svara keeps its tagged `annotated` text and the plain voice key (`hi_male`), so takes made before Veena existed stay valid.
"""
import re

from . import maya, svara

DEFAULT_ENGINE = "maya-tts"                     # what a new plan starts with
LEGACY_ENGINE = "veena-tts"                     # what a plan that never chose one has always used: its takes stay valid
ENGINES: dict[str, dict] = {
    "maya-tts": {
        "label": "Maya", "default_voice": "Siddhant", "async": True,
        # gender / age as listed by GET /audio/voices?model=maya-tts; every voice speaks every language
        "voices": {"Ahana": "female", "Vaidehi": "female", "Malini": "female", "Charvi": "female", "Jahnavi": "female", "Nivedita": "female", "Ishwari": "female",
                   "Vrinda": "female", "Kayal": "female", "Tanushree": "female", "Anirban": "male", "Nakul": "male", "Vasant": "male", "Siddhant": "male",
                   "Satvik": "male", "Abhay": "male", "Ritvik": "male", "Sreekar": "male", "Shaunak": "male", "Akshat": "male"},
        "defaults": {"response_format": "wav", "seed": 7, "language": "hi", "speed": 1.0},       # sampler values are tuned by the gateway; narration is mixed script, so the language is named
        "emotions": True, "pace_wpm": 148,
    },
    "veena-tts": {
        "label": "Veena", "default_voice": "agastya", "async": True,
        "voices": {"agastya": "male", "kavya": "female", "maitri": "female", "vinaya": "female"},
        "defaults": {"response_format": "wav", "seed": 7, "temperature": 0.4, "top_p": 0.9, "repetition_penalty": 1.05, "speed": 1.0},
        "emotions": False, "pace_wpm": 148,
    },
    "svara-tts": {
        "label": "Svara", "default_voice": "hi_male", "async": False,
        "voices": {"hi_male": "male"},
        "defaults": {"response_format": "wav", "seed": 7, "temperature": 0.6, "repetition_penalty": 1.25},
        "emotions": True, "pace_wpm": 148,
    },
}


def current(narrator: dict | None) -> dict:
    """The engine and voice in use: {"engine", "voice"}. Plans that never chose one (including older plans whose narrator says hi_male) use Veena / agastya; new plans are created with Maya."""
    t = (narrator or {}).get("tts") or {}
    eng = t.get("engine") if t.get("engine") in ENGINES else LEGACY_ENGINE
    voice = t.get("voice") if t.get("voice") in ENGINES[eng]["voices"] else ENGINES[eng]["default_voice"]
    return {"engine": eng, "voice": voice}


def choose(narrator: dict, engine: str, voice: str | None = None) -> dict:
    """The narrator dict with the engine and voice set. Raises ValueError for an unknown engine or voice."""
    if engine not in ENGINES:
        raise ValueError(f"unknown voice engine '{engine}' (use one of: {', '.join(ENGINES)})")
    voice = voice or ENGINES[engine]["default_voice"]
    if voice not in ENGINES[engine]["voices"]:
        raise ValueError(f"'{voice}' is not a {ENGINES[engine]['label']} voice (use one of: {', '.join(ENGINES[engine]['voices'])})")
    return {**narrator, "tts": {"engine": engine, "voice": voice}}


def key(cur: dict) -> str:
    """What a take's hash carries. Svara keeps the bare voice name so older takes stay valid."""
    return cur["voice"] if cur["engine"] == "svara-tts" else f"{cur['engine']}:{cur['voice']}"


def engine_of_key(k: str) -> str:
    return k.split(":", 1)[0] if ":" in k else "svara-tts"


_END = re.compile(r"[.!?।…]$")


def veena_text(seg: dict) -> str:
    """Narration for Veena: the sentences as written, each ending in punctuation (a missing mark reads flat), a pause tag where the plan asks for one."""
    out = []
    for s in seg.get("sentences") or []:
        t = svara.plain_text(s["text"]).strip()
        if not t:
            continue
        out.append(t if _END.search(t) else t + "।" if re.search(r"[ऀ-ॿ]$", t) else t + ".")
        p = svara.pause_tag(s.get("pause_after_s") or 0)
        if p:
            out.append(p)
    return " ".join(out) if out else svara.plain_text(seg.get("annotated", ""))


def texts_for(k: str, seg: dict) -> list[str]:
    """The exact requests' inputs for a hash key: one, or several when Maya's text is longer than a request may be."""
    e = engine_of_key(k)
    if e == "maya-tts":
        return maya.chunks(seg.get("sentences") or []) or [svara.plain_text(seg.get("annotated", ""))]
    return [veena_text(seg) if e == "veena-tts" else seg["annotated"]]


def text_for(k: str, seg: dict) -> str:
    """The text a take is made from (what its hash covers)."""
    return "\n".join(texts_for(k, seg))


def request_body(cur: dict, text: str, attempt: int, rec: dict | None = None) -> dict:
    """The /audio/speech body. `rec` is an optional override of the engine's defaults. Each retake gets a new seed."""
    cfg = ENGINES[cur["engine"]]
    d = {**cfg["defaults"], **{k: v for k, v in (rec or {}).items() if k in cfg["defaults"]}}
    body = {"model": cur["engine"], "input": text, "voice": cur["voice"], **d}
    body["seed"] = int(d["seed"]) + 11 * (attempt - 1)
    return body


def public() -> dict:
    return {k: {"label": v["label"], "default_voice": v["default_voice"], "voices": v["voices"], "emotions": v["emotions"],
                "default": k == DEFAULT_ENGINE, **({"tags": {"style": list(maya.STYLE_TAGS), "sound": list(maya.SOUND_TAGS)}} if k == "maya-tts" else {})}
            for k, v in ENGINES.items()}


def narration_rules(engine: str) -> str:
    """The part of the narration prompt that depends on the voice."""
    if engine == "maya-tts":
        return ("Voice: Maya. It acts the lines: a separate voice-direction step adds the emotion tags later, so never write brackets, tags or stage directions in the sentences. "
                "Write for a storyteller's ear: short sentences with one idea each, a real question where the viewer would ask it, a held beat ('...') before a reveal, "
                "a short blunt sentence after a long one, and one line per beat that carries the turn or the sting. Hindi in Devanagari, English words in Latin letters, "
                "numbers as words. Keep 'emotion' neutral.")
    if engine == "veena-tts":
        return ("Voice: Veena. It has no emotion tags, so the words and the punctuation carry everything. Write for the ear: short sentences, one idea each. "
                "Use '...' (or '…') before a reveal or a held beat, ',' for a breath, '?' for a real question, '—' for a sudden cut. "
                "A pause_after_s becomes a spoken pause; put the natural pause in the punctuation too. "
                "Hindi in Devanagari, English words in Latin letters, numbers as words. Keep 'emotion' neutral unless a sentence is a true peak.")
    return ""
