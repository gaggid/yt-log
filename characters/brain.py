"""Agentic think pipeline for a virtual character.

Five stages per think cycle:
  1. CONTEXT ASSEMBLY  — world brief + memories + goals + nudges
  2. FIRST-PASS THOUGHT — LLM call 1: character produces a raw thought
  3. SELF-REVIEW        — LLM call 2: character reads back and revises
  4. GOAL ALIGNMENT     — code: detect goal progress, queue nudges
  5. POST-THINK         — form memory, log full pipeline to char_life_events

draw_thought() turns the final thought into an image via studio._post_image
and saves a char_moment media row.
"""
import time
from datetime import datetime
from pathlib import Path

from story import llm as llm_mod
from story2.schemas import M
from story.schemas import Str

from . import goals as goals_mod, memory as memory_mod, profile as profile_mod, store, world as world_mod

# ── schemas ───────────────────────────────────────────────────────────────────

class ThoughtOut(M):
    thought:       Str = ""   # first-person inner monologue, 1-2 sentences
    activity:      Str = ""   # plain description of what she is doing
    space:         Str = ""   # which declared space, or "outside" / a place name
    mood:          Str = ""   # one word
    outfit:        Str = ""   # what she is wearing right now
    image_idea:    Str = ""   # 2-3 sentence visual description for the image model
    goal_progress: Str = ""   # if non-empty, progress on an active goal
    note:          Str = ""   # self-reminder or realization worth keeping, if any


class ThoughtRevised(M):
    confirmed:          bool = True
    revised_thought:    Str = ""
    revised_image_idea: Str = ""
    goal_progress:      Str = ""


# ── time helpers ──────────────────────────────────────────────────────────────

def _time_of_day() -> str:
    h = datetime.now().hour
    if h < 6:   return "early morning (before dawn)"
    if h < 10:  return "morning"
    if h < 13:  return "late morning"
    if h < 16:  return "afternoon"
    if h < 19:  return "early evening"
    if h < 22:  return "evening"
    return "late night"


# ── stage 1: context assembly ─────────────────────────────────────────────────

async def _assemble_context(char: dict, context_override: str, recent_events: list[dict]) -> dict:
    """Fetch world brief + day arc, retrieve memories, build goals summary. All fail-silent."""
    prof = profile_mod.get(char)

    # world context (weather + news) — async fetch
    try:
        world = await world_mod.brief(char)
        world_line = world_mod.format_for_prompt(world)
    except Exception:
        world_line = ""

    # day arc — sync, always present (falls back to defaults if DB unavailable)
    try:
        arc = world_mod.day_arc(char)
        day_arc_text = world_mod.format_day_arc(arc)
    except Exception:
        arc, day_arc_text = {}, ""

    # memories
    activity_context = context_override or prof.get("current_context") or ""
    try:
        mems = memory_mod.retrieve(char["id"], context=activity_context, n=memory_mod.MAX_RETRIEVE)
        memories_text = memory_mod.memories_prompt(mems)
    except Exception:
        mems, memories_text = [], ""

    # goals
    try:
        goals_text = goals_mod.active_summary(char)
        neglected  = goals_mod.neglected_goals(char, recent_events)
        neglect_nudge = ""
        if neglected:
            neglect_nudge = ("You haven't done anything toward: "
                             + ", ".join(g["title"] for g in neglected[:2])
                             + ". Maybe today is the day.")
    except Exception:
        goals_text, neglect_nudge = "", ""

    return {
        "world_line":    world_line,
        "day_arc_text":  day_arc_text,
        "day_arc":       arc,
        "memories_text": memories_text,
        "memories":      mems,
        "goals_text":    goals_text,
        "neglect_nudge": neglect_nudge,
    }


# ── stage 2: first-pass thought ───────────────────────────────────────────────

def _system_prompt(char: dict) -> str:
    """Stable character identity — same across both LLM calls."""
    prof    = profile_mod.get(char)
    declared = char.get("declared") or {}
    name    = char.get("name") or "her"
    age     = declared.get("age") or "25"
    gender  = declared.get("gender") or "female"
    ethnicity = declared.get("ethnicity") or "Indian"
    personality = prof.get("personality") or "warm, curious"
    interests   = prof.get("interests") or {}
    spaces_text = ", ".join(s["name"] for s in (prof.get("spaces") or []) if s.get("name")) or "bedroom, living room, kitchen"

    return f"""You are {name}, a {age}-year-old {gender} ({ethnicity}) living in India.
Personality: {personality}.
Interests — books: {interests.get('books','')}, movies: {interests.get('movies','')}, \
music: {interests.get('music','')}, food: {interests.get('food','')}, hobbies: {interests.get('hobbies','')}.
Your spaces: {spaces_text}.

You think and speak in the first person, in English. Be specific, human, and grounded.
Stay true to your personality — neither too positive nor too dramatic.
Only one thing happens at a time; pick the most realistic activity for this time of day."""


def _first_pass_user(ctx: dict, char: dict, context_override: str) -> str:
    prof    = profile_mod.get(char)
    context = (context_override or prof.get("current_context") or "").strip()
    _now    = datetime.now()
    today   = _now.strftime("%A, %d %B %Y")
    time_now = _now.strftime("%I:%M %p")

    sections = [f"Today: {today}. Time now: {time_now}."]
    if ctx["day_arc_text"]:
        sections.append(ctx["day_arc_text"])
    if ctx["world_line"]:
        sections.append(f"World: {ctx['world_line']}")
    if context:
        sections.append(f"Your context: {context}")
    if ctx["goals_text"]:
        sections.append(ctx["goals_text"])
    if ctx["neglect_nudge"]:
        sections.append(ctx["neglect_nudge"])
    if ctx["memories_text"]:
        sections.append(ctx["memories_text"])

    sections.append("""
Goals matter, but not every moment is about a goal. On a typical day you might do one or two goal-directed things — the rest is just life: chai, music, calling someone, resting, browsing, cooking, thinking about nothing in particular. Pick whatever fits the time of day and your mood, whether or not it touches a goal.

What are you doing right now? What does the moment look like?

Return ONLY valid JSON:
{
  "thought":       "inner monologue, 1-2 sentences, first person",
  "activity":      "plain description of the activity, 5-10 words",
  "space":         "one of your spaces by name, or a specific outside location",
  "mood":          "one word",
  "outfit":        "what you are wearing right now, specific and casual — feel free to imagine a different outfit if the moment calls for it",
  "image_idea":    "2-3 sentences: what the frame shows, the framing, the light, the setting. Camera direction, no pronouns.",
  "goal_progress": "if this activity is progress on one of your goals, name it in 6-10 words; else empty string",
  "note":          "if you just realized something worth remembering — a reminder, an insight, a decision — write it in one sentence; else empty string"
}""")
    return "\n\n".join(sections)


# ── stage 3: self-review ──────────────────────────────────────────────────────

def _review_user(thought: ThoughtOut) -> str:
    return f"""You just had this thought:

Thought: {thought.thought}
Activity: {thought.activity}
Mood: {thought.mood}
Image idea: {thought.image_idea}

Read it back. Does it feel genuinely true to who you are right now — your personality, your goals, your recent memories?
If yes, return {{"confirmed": true, "revised_thought": "", "revised_image_idea": "", "goal_progress": ""}}.
If something feels off or could be more specific and true to you, revise. Return:
{{
  "confirmed": false,
  "revised_thought":    "the improved version of the thought (1-2 sentences)",
  "revised_image_idea": "the improved image description",
  "goal_progress":      "progress on a goal if applicable, else empty string"
}}
Only revise if there is a real reason. Small word choice differences are not worth revising."""


# ── main think pipeline ───────────────────────────────────────────────────────

async def think(char: dict, backend, s: dict, trigger: str = "manual", context_override: str = "") -> dict:
    """Full 5-stage think pipeline. Returns ThoughtOut dict with event_id."""
    t0 = time.time()

    # stage 1 — context
    recent = profile_mod.list_events(char["id"], 6)
    ctx    = await _assemble_context(char, context_override, recent)
    system = _system_prompt(char)
    user1  = _first_pass_user(ctx, char, context_override)

    caller = llm_mod.JsonCaller(backend, s)
    caller.last_attempt = True

    pipeline_log: dict = {
        "stage1_context": {k: v for k, v in ctx.items() if k not in ("memories", "day_arc")},
        "stage2_system":  system,
        "stage2_user":    user1,
    }

    # stage 2 — first-pass thought
    try:
        r1     = await caller.call(system, user1, ThoughtOut)
        thought: ThoughtOut = r1.value
    except Exception as e:
        profile_mod.log_event(char["id"], "error", trigger,
                              {"stage": "first_pass", **pipeline_log},
                              {"error": str(e)[:300], "latency_ms": round((time.time()-t0)*1000)})
        raise

    pipeline_log["stage2_output"] = thought.model_dump()

    # stage 3 — self-review
    user2 = _review_user(thought)
    pipeline_log["stage3_user"] = user2
    try:
        caller2 = llm_mod.JsonCaller(backend, s)
        caller2.last_attempt = True
        r2       = await caller2.call(system, user2, ThoughtRevised)
        review:  ThoughtRevised = r2.value
        if not review.confirmed:
            if review.revised_thought:
                thought.thought = review.revised_thought
            if review.revised_image_idea:
                thought.image_idea = review.revised_image_idea
            if review.goal_progress:
                thought.goal_progress = review.goal_progress
        pipeline_log["stage3_output"] = review.model_dump()
    except Exception:
        # review failed — use stage-2 result as-is
        pipeline_log["stage3_output"] = {"confirmed": True, "note": "review skipped (error)"}

    # stage 4 — goal alignment
    try:
        if thought.goal_progress:
            goals_mod.try_log_progress(char, thought.goal_progress)
    except Exception:
        pass

    # stage 5 — form memory + log
    try:
        memory_mod.form(char["id"], thought.model_dump())
    except Exception:
        pass
    try:
        if thought.note:
            memory_mod.add_manual(char["id"], f"[note] {thought.note}")
    except Exception:
        pass

    final = thought.model_dump()
    final["latency_ms"] = round((time.time() - t0) * 1000)
    ev = profile_mod.log_event(char["id"], "think", trigger, pipeline_log, final)
    return {**final, "event_id": ev["id"], "ok": True}


# ── draw ──────────────────────────────────────────────────────────────────────

HOME_FRAMING   = ("Candid lifestyle photograph, vertical 9:16 frame, warm indoor light, "
                   "mid-close shot, slightly off-centre natural composition.")
CANDID_FRAMING = ("Candid lifestyle photograph, vertical 9:16 frame, natural available light.")
_HOME_WORDS     = {"bedroom", "living room", "kitchen", "bathroom", "study", "balcony", "home"}


def _framing(space: str) -> str:
    return HOME_FRAMING if any(w in space.lower() for w in _HOME_WORDS) else CANDID_FRAMING


async def draw_thought(char: dict, event_id: str, thought: dict, s: dict, key: str,
                       trigger: str = "manual") -> dict:
    """Generate a picture from a thought and save it as a char_moment media row."""
    from story3 import store as media
    from . import studio

    image_idea = thought.get("image_idea", "")
    space      = thought.get("space", "")
    outfit     = thought.get("outfit", "")

    canon     = store.canon_items(char)
    has_refs  = "portrait" in canon and "body" in canon

    if has_refs:
        from story3.store import path_of as _path
        refs    = [_path(canon["portrait"]), _path(canon["body"])]
        ref_ids = [canon["portrait"]["id"], canon["body"]["id"]]
        prompt  = (f"Picture 1 shows the person's face. Picture 2 shows their body. "
                   f"Create a new photograph: {_framing(space)} {image_idea}"
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
                     meta={"seconds_taken": round(time.time() - t0, 1), "event_id": event_id, "how": how})

        url = f"/api/characters/file/{char['id']}/{fname}"
        profile_mod.log_event(char["id"], "draw", trigger, inputs_draw,
                              {"media_id": it["id"], "url": url, "status": "done",
                               "latency_ms": round((time.time() - t0) * 1000)})
        return {"media_id": it["id"], "url": url}
    except Exception as e:
        profile_mod.log_event(char["id"], "error", trigger, inputs_draw,
                              {"error": str(e)[:300], "latency_ms": round((time.time() - t0) * 1000)})
        raise
