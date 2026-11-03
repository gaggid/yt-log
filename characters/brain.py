"""The thinking model for a virtual character. `think()` produces a first-person thought and image
idea from the character's psychometric profile. `draw_thought()` generates the image and saves it
as a char_moment media row. Every call is logged to char_life_events for audit and tuning."""
import time
from datetime import datetime
from pathlib import Path

from story import llm as llm_mod
from story2.schemas import M
from story.schemas import Str

from . import profile as profile_mod, store

# ── output schema ─────────────────────────────────────────────────────────────

class ThoughtOut(M):
    thought:    Str = ""   # first-person inner monologue, 1-2 sentences
    activity:   Str = ""   # plain description of what she is doing
    space:      Str = ""   # which declared space, or "outside" / a place name
    mood:       Str = ""   # one word
    outfit:     Str = ""   # what she is wearing right now
    image_idea: Str = ""   # visual description for the image model, 2-3 sentences


# ── prompt helpers ────────────────────────────────────────────────────────────

def _time_of_day() -> str:
    h = datetime.now().hour
    if h < 6:   return "early morning (before dawn)"
    if h < 10:  return "morning"
    if h < 13:  return "late morning"
    if h < 16:  return "afternoon"
    if h < 19:  return "early evening"
    if h < 22:  return "evening"
    return "late night"


def _build_prompt(char: dict, context_override: str = "") -> tuple[str, str]:
    """(system, user) for the think LLM call."""
    prof = profile_mod.get(char)
    declared = char.get("declared") or {}
    name = char.get("name") or "her"
    age = declared.get("age") or "25"
    gender = declared.get("gender") or "female"
    ethnicity = declared.get("ethnicity") or "Indian"
    personality = prof.get("personality") or "warm, curious"
    interests = prof.get("interests") or {}
    spaces_text = ", ".join(s["name"] for s in (prof.get("spaces") or []) if s.get("name")) or "bedroom, living room, kitchen"
    context = (context_override or prof.get("current_context") or "").strip()
    today = datetime.now().strftime("%A, %d %B %Y")
    tod = _time_of_day()

    system = f"""You are {name}, a {age}-year-old {gender} ({ethnicity}) living in India.
Personality: {personality}.
Interests — books: {interests.get('books','')}, movies: {interests.get('movies','')}, \
music: {interests.get('music','')}, food: {interests.get('food','')}, hobbies: {interests.get('hobbies','')}.
{f'Context: {context}' if context else ''}
Your spaces: {spaces_text}.
Today is {today}. Time: {tod}.

Think in the first person, in English. Be specific, human, and grounded — not poetic or aspirational.
Return ONLY valid JSON with exactly these keys:
{{
  "thought":    "inner monologue, 1-2 sentences, first person",
  "activity":   "plain description of the current activity, 5-10 words",
  "space":      "one of your spaces by name, or a specific outside location",
  "mood":       "one word",
  "outfit":     "what you are wearing right now, casual and specific",
  "image_idea": "2-3 sentences describing the visual: what the frame shows, the framing, the light, the setting. Write as a camera direction, no pronouns."
}}"""

    user = "What are you doing right now? What does the moment look like?"
    return system, user


# ── think ─────────────────────────────────────────────────────────────────────

async def think(char: dict, backend, s: dict, trigger: str = "manual", context_override: str = "") -> dict:
    """Run the brain: one LLM call → ThoughtOut dict with event_id. Logs the event."""
    t0 = time.time()
    system, user = _build_prompt(char, context_override)
    caller = llm_mod.JsonCaller(backend, s)
    caller.last_attempt = True

    inputs = {
        "system_prompt": system,
        "user_prompt": user,
        "profile_snapshot": profile_mod.get(char),
        "time_of_day": _time_of_day(),
        "date": datetime.now().strftime("%A %d %B %Y"),
    }
    try:
        result = await caller.call(system, user, ThoughtOut)
        thought = result.value
        outputs = {**thought.model_dump(), "latency_ms": round((time.time() - t0) * 1000)}
        ev = profile_mod.log_event(char["id"], "think", trigger, inputs, outputs)
        return {**outputs, "event_id": ev["id"], "ok": True}
    except Exception as e:
        outputs = {"error": str(e)[:300], "latency_ms": round((time.time() - t0) * 1000)}
        profile_mod.log_event(char["id"], "error", trigger, inputs, outputs)
        raise


# ── draw ──────────────────────────────────────────────────────────────────────

SELFIE_FRAMING = ("Mobile front-camera selfie, vertical 9:16 frame, natural available light, "
                  "slightly candid angle, close-mid shot, as if glancing at the phone.")
CANDID_FRAMING = ("Candid lifestyle photograph, vertical 9:16 frame, natural available light.")

_HOME_WORDS = {"bedroom", "living room", "kitchen", "bathroom", "study", "balcony", "home"}


def _framing(space: str) -> str:
    return SELFIE_FRAMING if any(w in space.lower() for w in _HOME_WORDS) else CANDID_FRAMING


async def draw_thought(char: dict, event_id: str, thought: dict, s: dict, key: str, trigger: str = "manual") -> dict:
    """Generate a picture from a thought and save it as a char_moment media row."""
    from story3 import store as media
    from . import studio

    image_idea = thought.get("image_idea", "")
    space = thought.get("space", "")
    outfit = thought.get("outfit", "")

    canon = store.canon_items(char)
    has_refs = "portrait" in canon and "body" in canon

    if has_refs:
        from story3.store import path_of as _path
        refs = [_path(canon["portrait"]), _path(canon["body"])]
        ref_ids = [canon["portrait"]["id"], canon["body"]["id"]]
        noun = "photograph"
        prompt = (f"Picture 1 shows the person's face. Picture 2 shows their body. "
                  f"Create a new {noun}: {_framing(space)} {image_idea}"
                  + (f" Wearing: {outfit}." if outfit else "")
                  + " Each person keeps exactly the face, hair, skin tone, build and clothes of their own picture.")
        how = "edit"
    else:
        char_desc = (char.get("identity") or "").strip()
        prompt = f"{_framing(space)} {image_idea}" + (f" Wearing: {outfit}." if outfit else "") + (f" {char_desc}" if char_desc else "")
        refs, ref_ids = [], []
        how = "draw"

    body_req = {"model": char["render"]["model"], "size": "720x1280", "n": 1,
                "response_format": "b64_json", "prompt": prompt[:3900]}
    t0 = time.time()
    inputs_draw = {"prompt": prompt[:500], "refs": ref_ids, "how": how, "event_id": event_id}
    try:
        base_url, api_key = studio._ctx(s, key)
        raw = await studio._post_image(how, body_req, refs, base_url, api_key)

        store.media_dir(char["id"], "char_moment").mkdir(parents=True, exist_ok=True)
        it = media.add(char["id"], "char_moment", "moment", 0, "done",
                       {"event_id": event_id, "thought": thought.get("thought", ""),
                        "activity": thought.get("activity", ""), "space": space,
                        "mood": thought.get("mood", ""), "how": how, "prompt": prompt[:500]})
        fname = f"char_moment/moment-a{it['attempt']}.png"
        (store.media_dir(char["id"]) / fname).write_bytes(raw)
        media.update(it["id"], file=fname,
                     meta={"seconds_taken": round(time.time() - t0, 1),
                           "event_id": event_id, "how": how})

        url = f"/api/characters/file/{char['id']}/{fname}"
        outputs_draw = {"media_id": it["id"], "url": url, "status": "done",
                        "latency_ms": round((time.time() - t0) * 1000)}
        profile_mod.log_event(char["id"], "draw", trigger, inputs_draw, outputs_draw)
        return {"media_id": it["id"], "url": url}
    except Exception as e:
        outputs_draw = {"error": str(e)[:300], "latency_ms": round((time.time() - t0) * 1000)}
        profile_mod.log_event(char["id"], "error", trigger, inputs_draw, outputs_draw)
        raise
