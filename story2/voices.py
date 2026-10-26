"""Voice engines. Veena (default) and Svara sit behind the same gateway; this module is the one place that knows their voices, how the spoken text is
built for each, and what a request looks like. The choice is stored on the plan (`narrator.tts`) outside the content hash: picking another voice
never un-approves a plan, it only makes the old takes stop counting (their hash carries the voice key).

* Veena has no emotion tags. Pauses come from punctuation (`...` `,` `?` `—`) and `[pause:Ns]`. Text is built from the sentences, so a plan written
  for Svara (emotion tags in `annotated`) speaks fine in Veena.
* Svara keeps its tagged `annotated` text and the plain voice key (`hi_male`), so takes made before Veena existed stay valid.
"""
import re

from . import svara

DEFAULT_ENGINE = "veena-tts"
ENGINES: dict[str, dict] = {
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
    """The engine and voice in use: {"engine", "voice"}. Plans that never chose one (including older plans whose narrator says hi_male) use Veena / agastya."""
    t = (narrator or {}).get("tts") or {}
    eng = t.get("engine") if t.get("engine") in ENGINES else DEFAULT_ENGINE
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


def text_for(k: str, seg: dict) -> str:
    """The exact text sent to the voice for a hash key."""
    return veena_text(seg) if engine_of_key(k) == "veena-tts" else seg["annotated"]


def request_body(cur: dict, text: str, attempt: int, rec: dict | None = None) -> dict:
    """The /audio/speech body. `rec` is an optional override of the engine's defaults. Each retake gets a new seed."""
    cfg = ENGINES[cur["engine"]]
    d = {**cfg["defaults"], **{k: v for k, v in (rec or {}).items() if k in cfg["defaults"]}}
    body = {"model": cur["engine"], "input": text, "voice": cur["voice"], **d}
    body["seed"] = int(d["seed"]) + 11 * (attempt - 1)
    return body


def public() -> dict:
    return {k: {"label": v["label"], "default_voice": v["default_voice"], "voices": v["voices"], "emotions": v["emotions"],
                "default": k == DEFAULT_ENGINE} for k, v in ENGINES.items()}


def narration_rules(engine: str) -> str:
    """The part of the narration prompt that depends on the voice."""
    if engine == "veena-tts":
        return ("Voice: Veena. It has no emotion tags, so the words and the punctuation carry everything. Write for the ear: short sentences, one idea each. "
                "Use '...' (or '…') before a reveal or a held beat, ',' for a breath, '?' for a real question, '—' for a sudden cut. "
                "A pause_after_s becomes a spoken pause; put the natural pause in the punctuation too. "
                "Hindi in Devanagari, English words in Latin letters, numbers as words. Keep 'emotion' neutral unless a sentence is a true peak.")
    return ""
