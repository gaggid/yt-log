"""Optional background music for a long-form film or a short, made by the gateway's YuE2 model (`yue2-3b`, `POST /v1/audio/music`).

The music engine can give odd results, so the music is kept small on purpose: ONE quiet instrumental loop for the whole film, with common instruments, a steady tempo and no build-ups,
not a score that follows each scene. The idea is planned with the rest of the plan, from the story, its type and its audience (`plan_music`); a model proposes tags from a short vocabulary,
and code keeps only tags from that vocabulary, caps the instruments at three and always adds "instrumental, no vocals". If the model fails, a fixed recipe per story type is used.
YuE2 wants a one-line style prompt of 6 to 12 comma-separated tags (language first) and section tags in the lyrics; an empty section tag is an instrumental passage (docs: /v1/audio/music/guide).

The track is shorter than the film (about 25 seconds per section); `bed_from_track` loops it with cross-fades, levels it and trims it to the film. The synthetic pad in audio.py stays
the bed when music is off or could not be made. The track is a `media` row (kind `music`, key `bgm`) of the plan or the short, numbered, never overwritten.

Settings: long-form `plan.settings.music`, shorts `short.settings.music*`; both are read through the dicts built here (`DEFAULT`)."""
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path

from story import llm
from story2.schemas import M, Str, StrList

from . import store
from .voice import MediaError

MODEL = "yue2-3b"
KIND, KEY = "music", "bgm"
SECTION_S = 25                                  # the docs: about 20 to 30 seconds for each sectioned block
MAX_SECTIONS, MIN_SECTIONS = 5, 2               # a track of about 50 to 125 seconds; a longer film loops it
CROSSFADE_S = 4.0
DEFAULT = {"enabled": False, "level": -34, "plan": {}, "seed": 7}      # level: loudness of the bed in LUFS before it is ducked under the voice
LEVEL_MIN, LEVEL_MAX = -46, -24
MIX_VERSION = "m1"

GENRES = ("ambient", "cinematic ambient", "minimal", "neo-classical", "lo-fi", "acoustic", "chamber", "soft underscore")
MOODS = ("calm", "warm", "reflective", "hopeful", "tender", "mysterious", "tense", "melancholic", "curious", "gentle", "dreamy", "serious", "light")
INSTRUMENTS = ("soft piano", "felt piano", "warm pad", "soft strings", "string pad", "acoustic guitar", "nylon guitar", "harp", "cello", "music box", "soft marimba", "vibraphone", "upright bass", "light shaker")
MAX_INSTRUMENTS, MAX_MOODS = 3, 2
TAIL = ("instrumental", "no vocals", "soft dynamics", "steady")        # always last, so the track stays a quiet bed
BPM = re.compile(r"^(\d{2,3})\s*bpm$")

# One recipe for each story type (story/storytypes.py) and for a short: used when the model fails, and the model's answer is checked against the same vocabulary.
RECIPES: dict[str, dict] = {
    "incident": {"genre": "cinematic ambient", "moods": ["tense", "reflective"], "bpm": 66, "instruments": ["warm pad", "soft strings"]},
    "biography": {"genre": "neo-classical", "moods": ["warm", "reflective"], "bpm": 70, "instruments": ["soft piano", "soft strings"]},
    "documentary": {"genre": "minimal", "moods": ["serious", "curious"], "bpm": 72, "instruments": ["soft piano", "warm pad"]},
    "explainer": {"genre": "lo-fi", "moods": ["curious", "light"], "bpm": 80, "instruments": ["soft piano", "soft marimba"]},
    "listicle": {"genre": "lo-fi", "moods": ["light", "hopeful"], "bpm": 84, "instruments": ["soft piano", "acoustic guitar"]},
    "short": {"genre": "ambient", "moods": ["gentle", "curious"], "bpm": 80, "instruments": ["soft piano", "warm pad"]},
}
DEFAULT_RECIPE = "documentary"


class MusicOut(M):
    genre: Str = ""
    moods: StrList = []
    bpm: int = 0
    instruments: StrList = []
    why: Str = ""


SYSTEM = f"""[TASK:music_plan]
You choose the BACKGROUND MUSIC of a video. It is made by a small music model that gives odd results when asked for much, so ask for very little: ONE quiet instrumental loop that plays from start to end under the narrator, with common instruments, a steady tempo and no changes. It supports the voice and is never noticed on its own.
Think about the story and the people who will watch: what feeling should sit under the words for them, and what would feel at home to them. Choose by the whole story, not by single scenes. No build-ups, no drops, no solos, no drums.

Return ONLY a JSON object: {{"genre": "...", "moods": ["...", "..."], "bpm": 72, "instruments": ["...", "..."], "why": "one plain sentence"}}
Choose ONLY from these lists (exact words):
- genre, exactly one of: {", ".join(GENRES)}
- moods, one or two of: {", ".join(MOODS)}
- instruments, one to three of: {", ".join(INSTRUMENTS)}
- bpm: a slow, steady tempo as a number, within the range given in the request.
"why": say in one sentence what the music should feel like under this story and for this audience."""


def settings(plan: dict) -> dict:
    """Long-form: the plan's music settings with defaults."""
    return norm((plan.get("settings") or {}).get("music"))


def norm(raw: dict | None) -> dict:
    m = {**DEFAULT, **(raw if isinstance(raw, dict) else {})}
    m["enabled"] = bool(m["enabled"])
    try:
        m["level"] = max(LEVEL_MIN, min(LEVEL_MAX, int(m["level"])))
    except (TypeError, ValueError):
        m["level"] = DEFAULT["level"]
    m["plan"] = m["plan"] if isinstance(m["plan"], dict) else {}
    return m


def short_settings(short: dict) -> dict:
    """A short keeps the same fields beside its other settings: `music` (on/off), `music_level`, `music_plan`."""
    st = short.get("settings") or {}
    return norm({"enabled": st.get("music"), "level": st.get("music_level", DEFAULT["level"]), "plan": st.get("music_plan"), "seed": st.get("music_seed", DEFAULT["seed"])})


# ── the plan ─────────────────────────────────────────────────────────────────

def recipe_for(kind: str) -> dict:
    return RECIPES.get(kind) or RECIPES[DEFAULT_RECIPE]


def bpm_range(speed: float = 1.0) -> tuple[int, int]:
    """A film played faster than 1x plays its music faster too, so the track is asked for a slower tempo."""
    lo, hi = 56, 92
    return max(48, round(lo / speed)), max(60, round(hi / speed))


def clean(genre: str, moods: list[str], bpm: int, instruments: list[str], kind: str, speed: float = 1.0) -> dict:
    """Keep only words from the vocabulary; anything missing comes from the recipe of the story type. Returns the plan's parts and the one-line style prompt."""
    rec = recipe_for(kind)
    g = next((x for x in GENRES if x == (genre or "").strip().lower()), rec["genre"])
    ms = list(dict.fromkeys(x for x in (m.strip().lower() for m in moods) if x in MOODS))[:MAX_MOODS] or rec["moods"]
    ins = list(dict.fromkeys(x for x in (i.strip().lower() for i in instruments) if x in INSTRUMENTS))[:MAX_INSTRUMENTS] or rec["instruments"]
    lo, hi = bpm_range(speed)
    b = int(bpm) if isinstance(bpm, (int, float)) and bpm else round(rec["bpm"] / speed)
    b = max(lo, min(hi, b))
    return {"genre": g, "moods": ms, "bpm": b, "instruments": ins, "caption": caption({"genre": g, "moods": ms, "bpm": b, "instruments": ins})}


def caption(p: dict) -> str:
    """The YuE2 style prompt: language, genre, mood, tempo, instruments, then the fixed tail (6 to 12 tags)."""
    return ", ".join(["English", p["genre"], *p["moods"], f"{p['bpm']} BPM", *p["instruments"], *TAIL])


def parse_caption(text: str, kind: str, speed: float = 1.0) -> dict | None:
    """An edited style prompt: its tags are sorted into the vocabulary again, so a typed 'heavy metal' cannot get through."""
    tags = [t.strip().lower() for t in re.split(r"[,\n]", text or "") if t.strip()]
    if not tags:
        return None
    genre = next((t for t in tags if t in GENRES), "")
    moods = [t for t in tags if t in MOODS]
    ins = [t for t in tags if t in INSTRUMENTS]
    bpm = next((int(m.group(1)) for m in (BPM.match(t) for t in tags) if m), 0)
    return clean(genre, moods, bpm, ins, kind, speed)


def fallback(kind: str, speed: float = 1.0) -> dict:
    p = clean("", [], 0, [], kind, speed)
    return {**p, "why": "A quiet standard bed for this kind of film.", "source": "recipe"}


async def plan_music(context: str, kind: str, backend, s: dict, speed: float = 1.0) -> dict:
    """The music plan from the story's own words (`context`: what the film is about, its type, who watches). Never raises for a model failure: the recipe of the story type is used."""
    lo, hi = bpm_range(speed)
    user = f"{context}\n\nTempo range for this film: {lo} to {hi} BPM. Choose the quiet loop that fits."
    try:
        res = await llm.JsonCaller(backend, s).call(SYSTEM, user, MusicOut)
    except llm.LLMError:
        return fallback(kind, speed)
    o = res.value
    return {**clean(o.genre, o.moods, o.bpm, o.instruments, kind, speed), "why": o.why.strip()[:300], "source": "writer"}


def context_for_plan(plan: dict) -> tuple[str, str]:
    """(text for the model, story type) of a long-form plan."""
    from story import storytypes
    from story2 import lexicon
    bp = plan.get("blueprint") or {}
    st = plan.get("settings") or {}
    kind = storytypes.of_plan(plan)
    aud = st.get("audience") or {}
    prof = lexicon.PROFILES.get(aud.get("profile") or lexicon.DEFAULT_PROFILE, lexicon.PROFILES[lexicon.DEFAULT_PROFILE])
    lines = [f"STORY TYPE: {storytypes.STORY_TYPES.get(kind, {}).get('label', kind)} ({storytypes.STORY_TYPES.get(kind, {}).get('short', '')})",
             f"AUDIENCE: Indian viewers; language register: {prof['label']}" + (f"; region: {aud['region']}" if aud.get("region") else ""),
             f"WHAT THE VIDEO PROMISES: {bp.get('viewer_promise', '')}", f"CENTRAL QUESTION: {bp.get('central_question', '')}", f"STAKES: {bp.get('stakes', '')}",
             f"THE PLANNER'S NOTE ON MUSIC: {bp.get('music_brief', '')}", f"LENGTH: about {st.get('minutes', '')} minutes"]
    return "\n".join(x for x in lines if x.split(": ", 1)[-1].strip()), kind


def context_for_short(short: dict) -> tuple[str, str]:
    plan = short.get("plan") or {}
    st = short.get("settings") or {}
    bible = ((short.get("script") or {}).get("bible")) or ""
    lines = ["STORY TYPE: a 30-second vertical short for Instagram reels and YouTube Shorts",
             f"AUDIENCE: viewers of short vertical videos; narration language: {st.get('language', 'hi')}; tone: {st.get('tone_id') or st.get('tone') or ''}",
             f"TITLE: {plan.get('title', '')}", f"STORY: {plan.get('logline', '')}", f"STORY NOTES: {json.dumps(bible, ensure_ascii=False)[:600] if bible else ''}", f"PICTURE STYLE: {st.get('visual_style') or ''}"]
    return "\n".join(x for x in lines if x.split(": ", 1)[-1].strip()), "short"


# ── the request ──────────────────────────────────────────────────────────────

def sections_for(total_s: float) -> int:
    return max(MIN_SECTIONS, min(MAX_SECTIONS, math.ceil(min(total_s, MAX_SECTIONS * SECTION_S) / SECTION_S)))


def lyrics_for(sections: int) -> str:
    """Section tags with no words: every one is an instrumental passage."""
    return "[Intro]\n\n" + "[Instrumental]\n\n" * max(0, sections - 2) + "[Outro]\n"


def request(cfg: dict, total_s: float) -> dict:
    cap = (cfg["plan"] or {}).get("caption", "")
    if not cap:
        raise MediaError("the music is not planned yet")
    n = sections_for(total_s)
    return {"model": MODEL, "caption": cap, "lyrics": lyrics_for(n), "cot": "full", "steps": 16, "duration": min(300, n * 30 + 20), "seed": int(cfg.get("seed", DEFAULT["seed"])),
            "response_format": "mp3"}


def req_hash(body: dict) -> str:
    return hashlib.sha1(json.dumps(body, sort_keys=True).encode()).hexdigest()[:12]


def chosen(plan_id: str, cfg: dict, total_s: float) -> dict | None:
    """The track made from the current plan and length class (approved one first, else the newest)."""
    if not cfg["enabled"] or not (cfg["plan"] or {}).get("caption"):
        return None
    want = req_hash(request(cfg, total_s))
    good = [i for i in store.items(plan_id, KIND, KEY) if i["status"] == "done" and i["file"] and i["meta"].get("input_hash") == want]
    ok = [i for i in good if i["approved"]]
    return (ok or good[-1:] or [None])[0] if good else None


def state(plan_id: str, cfg: dict, total_s: float) -> dict:
    items = store.items(plan_id, KIND, KEY)
    cur = None
    try:
        cur = chosen(plan_id, cfg, total_s)
    except MediaError:
        pass
    return {"enabled": cfg["enabled"], "level": cfg["level"], "plan": cfg["plan"], "have": bool(cur), "total_s": round(total_s, 1),
            "current": ({"id": cur["id"], "url": f"/api/media/file/{plan_id}/{cur['file']}", "duration_s": cur["meta"].get("duration_s")} if cur else None),
            "attempts": [{"id": i["id"], "status": i["status"], "error": i["meta"].get("error", "")} for i in items][-5:], "lyrics": lyrics_for(sections_for(total_s)), "model": MODEL}


# ── making the track ─────────────────────────────────────────────────────────

async def make(plan_id: str, cfg: dict, total_s: float, s: dict, api_key: str, progress=None, force: bool = False) -> dict:
    """Make the track for this film length with the music model. A finished track made from the same request is reused. Raises MediaError with a plain message."""
    from shorts import wan
    body = request(cfg, total_s)
    h = req_hash(body)
    if not force:
        have = chosen(plan_id, cfg, total_s)
        if have:
            return have
    it = store.add(plan_id, KIND, KEY, 0, "running", {"input_hash": h, "caption": body["caption"], "seed": body["seed"]})
    base = s["base_url"]
    try:
        if progress:
            progress(0, 1, "the music model is composing a quiet loop")
        ans = await wan.submit(body, base, api_key, True, "/audio/music")
        res = wan._result(ans) if ans.get("status") == "succeeded" or not ans.get("id") else await wan.wait(ans["id"], base, api_key, 1800)
        data = await wan.fetch(res, base, api_key)
        out_dir = store.media_dir(plan_id, "music")
        name = f"bgm-a{it['attempt']}.mp3"
        (out_dir / name).write_bytes(data)
        return store.update(it["id"], status="done", file=f"music/{name}", meta={"duration_s": float(res.get("duration_s") or 0), "score": bool(res.get("score_abc")), "lint": res.get("lint") or []})
    except (wan.WanError, OSError) as e:
        store.update(it["id"], status="failed", meta={"error": str(e)[:300]})
        raise MediaError(f"the music could not be made: {e}") from e


def _run(ffmpeg: str, args: list[str], cwd: Path | None = None) -> None:
    r = subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *args], capture_output=True, text=True, cwd=cwd, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(((r.stderr or r.stdout).strip().splitlines() or [str(r.returncode)])[-1][:240])


def bed_from_track(ffmpeg: str, item: dict, total_s: float, work: Path, level_lufs: float) -> Path | None:
    """The track looped with cross-fades to `total_s`, levelled to `level_lufs`, faded in and out, as a 24 kHz mono wav (the bed `audio.mix_args` ducks under the voice). None when ffmpeg fails."""
    src = store.path_of(item)
    dur = float(item["meta"].get("duration_s") or 0)
    if not src.is_file() or dur < 8 or total_s <= 0:
        return None
    n = 1 if dur >= total_s else min(60, math.ceil((total_s - CROSSFADE_S) / (dur - CROSSFADE_S)))
    inputs: list[str] = []
    for _ in range(n):
        inputs += ["-i", str(src)]
    chain, last = "", "[0:a]"
    for k in range(1, n):
        chain += f"{last}[{k}:a]acrossfade=d={CROSSFADE_S}:c1=tri:c2=tri[x{k}];"
        last = f"[x{k}]"
    fade_out = min(4.0, total_s / 4)
    graph = (chain + f"{last}atrim=0:{total_s:.2f},asetpts=PTS-STARTPTS,aresample=24000,aformat=channel_layouts=mono,loudnorm=I={level_lufs}:TP=-6:LRA=7,"
             f"afade=t=in:d=2,afade=t=out:st={max(0.0, total_s - fade_out):.2f}:d={fade_out:.2f}[o]")
    out = work / "music_bed.wav"
    try:
        _run(ffmpeg, [*inputs, "-filter_complex", graph, "-map", "[o]", "-c:a", "pcm_s16le", "-ar", "24000", "-ac", "1", str(out)], cwd=work)
    except (RuntimeError, OSError):
        return None
    return out


# ── a long-form plan ─────────────────────────────────────────────────────────

def plan_total_s(plan_id: str) -> float:
    """The film's length as far as it is known: the real voice when it exists, else the planned minutes."""
    from story2 import planner
    secs = store.audio_seconds(plan_id)
    if secs:
        return sum(secs.values())
    return float(planner.get_plan(plan_id)["settings"].get("minutes") or 8) * 60


def _speed() -> float:
    from . import video
    return float(video.PLAYBACK_SPEED)


def save_plan_settings(plan_id: str, patch: dict) -> dict:
    """Turn the music on or off, set its level, or replace the style prompt (its tags are checked against the vocabulary). Returns the plan's music settings."""
    from story import db
    from story2 import planner
    plan = planner.get_plan(plan_id)
    cur = settings(plan)
    if "enabled" in patch and patch["enabled"] is not None:
        cur["enabled"] = bool(patch["enabled"])
    if patch.get("level") is not None:
        cur["level"] = int(patch["level"])
    if (patch.get("caption") or "").strip():
        p = parse_caption(patch["caption"], _kind_of(plan), _speed())
        if p:
            cur["plan"] = {**cur["plan"], **p, "source": "edited"}
    cur = norm(cur)
    db.ex("UPDATE plans SET settings=?, updated_at=? WHERE id=?", (db.jdump({**plan["settings"], "music": cur}), db.now(), plan_id))
    return cur


def _kind_of(plan: dict) -> str:
    return context_for_plan(plan)[1]


async def replan(plan_id: str, backend, s: dict) -> dict:
    """Plan the music of a long-form film from its blueprint, story type and audience, and keep it in the plan's settings."""
    from story import db
    from story2 import planner
    plan = planner.get_plan(plan_id)
    ctx, kind = context_for_plan(plan)
    p = await plan_music(ctx, kind, backend, s, _speed())
    cur = norm({**settings(plan), "plan": p})
    db.ex("UPDATE plans SET settings=?, updated_at=? WHERE id=?", (db.jdump({**plan["settings"], "music": cur}), db.now(), plan_id))
    return cur


def plan_state(plan_id: str) -> dict:
    from story2 import planner
    plan = planner.get_plan(plan_id)
    return state(plan_id, settings(plan), plan_total_s(plan_id))


def current_for_plan(plan_id: str) -> tuple[dict | None, dict]:
    """(the track to mix, the music settings) of a long-form plan."""
    from story2 import planner
    cfg = settings(planner.get_plan(plan_id))
    return chosen(plan_id, cfg, plan_total_s(plan_id)), cfg


# ── a short ──────────────────────────────────────────────────────────────────

def short_total_s(short: dict) -> float:
    return float((short.get("settings") or {}).get("target_s") or 30)


async def plan_for_short(short: dict, backend, s: dict) -> dict:
    """Plan the music of a short from its story and set `settings.music_plan` (the caller saves the short). Does nothing when music is off."""
    st = short["settings"]
    if not st.get("music"):
        return {}
    ctx, kind = context_for_short(short)
    p = await plan_music(ctx, kind, backend, s)
    st["music_plan"] = p
    return p


def save_short_caption(short: dict, caption_text: str) -> None:
    p = parse_caption(caption_text, "short")
    if p:
        short["settings"]["music_plan"] = {**(short["settings"].get("music_plan") or {}), **p, "source": "edited"}


def short_current(short: dict) -> dict | None:
    return chosen(short["id"], short_settings(short), short_total_s(short))


def short_wanted(short: dict) -> bool:
    return short_settings(short)["enabled"]


def short_missing(short: dict) -> bool:
    return short_wanted(short) and short_current(short) is None


async def make_for_short(short_id: str, s: dict, api_key: str, backend=None, progress=None, force: bool = False) -> dict:
    """Plan (when it is not planned) and make the track of a short. Raises MediaError."""
    from shorts import store as sstore
    short = sstore.get(short_id)
    if not short["settings"].get("music"):
        raise MediaError("background music is off")
    if not (short["settings"].get("music_plan") or {}).get("caption"):
        if backend is None:
            raise MediaError("the music is not planned yet")
        await plan_for_short(short, backend, s)
        sstore.save(short)
    return await make(short_id, short_settings(short), short_total_s(short), s, api_key, progress, force)
