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

from . import feeling as feeling_mod, goals as goals_mod, interests as interests_mod, memory as memory_mod, profile as profile_mod, skills as skills_mod, store, world as world_mod

# ── schemas ───────────────────────────────────────────────────────────────────

class ThoughtOut(M):
    thought:          Str = ""   # first-person inner monologue, 1-2 sentences
    activity:         Str = ""   # plain description of what she is doing
    space:            Str = ""   # which declared space, or "outside" / a place name
    mood:             Str = ""   # one word
    expression:       Str = ""   # specific facial expression for this moment
    face_state:       Str = ""   # physical face condition (makeup, tiredness, flush, etc.)
    log_photo:        bool = True   # does the character think this moment is worth a picture?
    shot_type:        Str = ""   # one of the defined shot types — controls camera and phone visibility
    outfit:           Str = ""   # text description of what she is wearing
    outfit_id:        Str = ""   # wardrobe garment id if wearing an item from wardrobe
    wardrobe_want:    Str = ""   # garment she wants to add to wardrobe, described in one line
    image_idea:       Str = ""   # scene content, light and setting only — no camera or phone
    goal_progress:    Str = ""   # if non-empty, progress on an active goal
    energy_delta:     int = 0    # energy change this activity causes (negative = draining, positive = restoring)
    note:             Str = ""   # self-reminder or realization worth keeping, if any
    feeling_update:   dict = {}  # Phase K: {primary, intensity, secondary} — brain updates the feeling state
    new_interest:     dict = {}  # Phase L: {name, category} — propose a new interest discovered this cycle
    aspiration:       Str  = ""  # Phase L: a half-formed want or aspiration surfaced this cycle
    memory_category:  Str  = "episodic"  # Phase M: brain classifies the memory type for this cycle


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


# ── feeling helpers ───────────────────────────────────────────────────────────

def _age_of(char: dict) -> int:
    """Parse age from declared fields; default 25."""
    try:
        return int(char.get("declared", {}).get("age") or 25)
    except (TypeError, ValueError):
        return 25


def _feeling_line(prof: dict) -> str:
    """Format current feeling for Stage-1 context injection."""
    return feeling_mod.format_for_prompt(prof.get("feeling"))


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

    # memories — Phase M: pull by category for richer context
    activity_context = context_override or prof.get("current_context") or ""
    try:
        # Stage-1 spec: episodic(3) + reflection(2) + achievement(1) + discovery(1) = 7 max
        mems = memory_mod.retrieve_by_categories(
            char["id"],
            {"episodic": 3, "reflection": 2, "achievement": 1, "discovery": 1},
            context=activity_context,
        )
        # fill remaining slots with any category if under budget
        if len(mems) < memory_mod.MAX_RETRIEVE:
            extras = memory_mod.retrieve(char["id"], context=activity_context, n=memory_mod.MAX_RETRIEVE)
            seen = {m["id"] for m in mems}
            for m in extras:
                if m["id"] not in seen and len(mems) < memory_mod.MAX_RETRIEVE:
                    mems.append(m)
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

    # wardrobe
    try:
        from . import wardrobe as wardrobe_mod
        garments = wardrobe_mod.listing()
        if garments:
            wardrobe_text = "Wardrobe items you own: " + "; ".join(
                f"{g['name']} (id: {g['id']})" + (f" [{', '.join(g['tags'][:3])}]" if g.get("tags") else "")
                for g in garments[:20]
            )
        else:
            wardrobe_text = "Your wardrobe is currently empty."
    except Exception:
        wardrobe_text = ""

    return {
        "world_line":     world_line,
        "day_arc_text":   day_arc_text,
        "day_arc":        arc,
        "memories_text":  memories_text,
        "memories":       mems,
        "goals_text":     goals_text,
        "neglect_nudge":  neglect_nudge,
        "wardrobe_text":  wardrobe_text,
        "feeling_line":   _feeling_line(prof),
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
    spaces_text    = ", ".join(s["name"] for s in (prof.get("spaces") or []) if s.get("name")) or "bedroom, living room, kitchen"
    phone          = prof.get("phone") or ""
    core_character = prof.get("core_character") or ""
    fashion_taste  = prof.get("fashion_taste") or ""
    chronotype     = prof.get("chronotype") or ""
    energy         = int(prof.get("energy") or 80)
    sleep_threshold = int(prof.get("sleep_threshold") or 20)

    core_block    = f"Background and core character (fixed — this never changes):\n{core_character}\n\n" if core_character else ""
    fashion_block = f"Fashion sense and style preferences: {fashion_taste}\n" if fashion_taste else ""

    _chrono_desc = {
        "early bird": "naturally wakes early, peak energy in the morning, winds down by 9–10 pm",
        "night owl":  "naturally stays up late, slow to start in the morning, peak energy in the evening",
        "balanced":   "no strong preference — adapts to a normal 7am–11pm day",
    }
    chrono_line = ""
    if chronotype:
        chrono_line = f"Chronotype: {_chrono_desc.get(chronotype, chronotype)}.\n"

    if energy > 70:
        energy_desc = "fully charged and alert"
    elif energy > 50:
        energy_desc = "moderately energised"
    elif energy > 30:
        energy_desc = "noticeably tired"
    elif energy > sleep_threshold:
        energy_desc = "quite exhausted — winding down"
    else:
        energy_desc = "utterly drained — needs to sleep"

    def _int(v): return v.get("text", "") if isinstance(v, dict) else str(v or "")

    return f"""{core_block}You are {name}, a {age}-year-old {gender} ({ethnicity}) living in India.
Personality: {personality}.
Interests — books: {_int(interests.get('books',''))}, movies: {_int(interests.get('movies',''))}, \
music: {_int(interests.get('music',''))}, food: {_int(interests.get('food',''))}, hobbies: {_int(interests.get('hobbies',''))}.
{fashion_block}{chrono_line}Your spaces: {spaces_text}.{(' Phone: ' + phone + '.') if phone else ''}
Current energy: {energy}/100 — {energy_desc}. Let this shape what you choose to do right now.

You think and speak in the first person, in English. Be specific, human, and grounded.
Stay true to your core character and personality — neither too positive nor too dramatic.
Only one thing happens at a time; pick the most realistic activity for this time of day."""


def _first_pass_user(ctx: dict, char: dict, context_override: str) -> str:
    prof    = profile_mod.get(char)
    shot_choices = shot_choices_text(allowed_shot_types(prof))
    context = (context_override or prof.get("current_context") or "").strip()
    _now    = datetime.now()
    today   = _now.strftime("%A, %d %B %Y")
    time_now = _now.strftime("%I:%M %p")

    sections = [f"Today: {today}. Time now: {time_now}."]
    if ctx["day_arc_text"]:
        sections.append(ctx["day_arc_text"])
    if ctx["world_line"]:
        sections.append(f"World: {ctx['world_line']}")
    if ctx.get("feeling_line"):
        sections.append(ctx["feeling_line"])
    interests_line = interests_mod.inject_line(prof)
    if interests_line:
        sections.append(interests_line)
    skills_line = skills_mod.inject_line(prof)
    if skills_line:
        sections.append(skills_line)
    if context:
        sections.append(f"Your context: {context}")
    if ctx["goals_text"]:
        sections.append(ctx["goals_text"])
    if ctx["neglect_nudge"]:
        sections.append(ctx["neglect_nudge"])
    if ctx.get("wardrobe_text"):
        sections.append(ctx["wardrobe_text"])
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
  "expression":    "the specific facial expression for this moment — be precise, not generic (e.g. 'tired half-smile, eyes slightly heavy', 'wide genuine laugh, teeth showing', 'focused frown, lips pressed', 'soft contemplative gaze', 'surprised and delighted'). It must match the mood and activity.",
  "face_state":    "physical condition of the face right now based on time of day and what you have been doing (e.g. 'no makeup, natural skin', 'light day makeup', 'post-workout flush, dewy skin', 'makeup worn off, bare face with slight shine', 'evening makeup, defined eyes'). Be honest about the time of day.",
  "outfit":        "text description of what you are wearing right now — for display only; the actual clothes in the photo come from your wardrobe or your approved body picture",
  "outfit_id":     "the id of the wardrobe item you want to wear (exactly as listed above); set this to change your outfit in the photo. If empty, your default approved outfit is shown.",
  "wardrobe_want": "if you spot or imagine a piece of clothing you want to own — describe it in one line (e.g. 'dark green silk kurti with mirror work'); else empty string",
  "log_photo":     "true or false (a JSON boolean). Would you really take a picture of this moment and keep it? Be selective like a real person: true only for something worth remembering or sharing (a meal, a view, an outfit, progress on a goal, a good mood, something new). Routine or private moments (resting, scrolling, being tired, plain chores) are usually false. If false, leave shot_type and image_idea as empty strings.",
  "shot_type":     "@@SHOTS@@",
  "image_idea":    "2-3 sentences: what fills the frame, the light, the setting, visible props. Describe ONLY the scene content — do NOT mention the camera, the phone, or how the picture was taken. No pronouns.",
  "goal_progress":    "if this activity made concrete progress on a goal, describe WHAT YOU ACTUALLY DID in 6-10 words (e.g. 'practiced first 10 minutes of Bhangra footwork', 'finished chapter 3 of the book'). Do not write meta-reflections or intentions about the goal. Else empty string.",
  "energy_delta":     "integer: how much energy this activity changes. Draining: intense exercise/dance -15 to -20, focused work/study -10 to -15, errands/commute -8 to -12, socialising -6 to -10, casual browsing/reading -2 to -5. Restoring: full meal +8, short nap +20, full night sleep +65, light rest +5. Return a plain integer like -12 or 8.",
  "note":             "if you just realized something worth remembering — a reminder, an insight, a decision — write it in one sentence; else empty string",
  "feeling_update":   {"primary": "@@FEELING_VOCAB@@", "intensity": "1-10 integer", "secondary": "one more feeling word or empty string"},
  "new_interest":     "if you genuinely discovered or became curious about something NEW today that is not in your existing interests, return {\"name\": \"short label\", \"category\": \"one word\"}; else {}",
  "aspiration":       "if a half-formed want or ambition surfaced naturally in your thinking — something you want to do, try, become, or experience — write it in one plain sentence; else empty string. Not a goal, just a floating desire.",
  "memory_category":  "classify this moment's memory: episodic (activity snapshot), observation (something noticed), learning (fact or skill insight), achievement (milestone reached), discovery (new thing enjoyed), reflection (personal insight), desire (a want or craving), wish (clothing/accessory want) — pick exactly one word"
}""".replace("@@SHOTS@@", shot_choices).replace(
        '"@@FEELING_VOCAB@@"',
        '"one word from: ' + ', '.join(sorted(feeling_mod.ALL_FEELINGS)[:40]) + ' … (pick what genuinely fits this moment)"'
    ))
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

    # stage 5 — form memory + log (Phase M: use brain-classified category)
    try:
        mem_cat = thought.memory_category or "episodic"
        if mem_cat not in memory_mod.CATEGORIES:
            mem_cat = "episodic"
        memory_mod.form(char["id"], thought.model_dump(), category=mem_cat)
    except Exception:
        pass
    try:
        if thought.note:
            memory_mod.add_manual(char["id"], thought.note, category="note", dedup=True)
    except Exception:
        pass
    try:
        if thought.wardrobe_want:
            memory_mod.add_manual(char["id"], thought.wardrobe_want, category="wish", dedup=True)
    except Exception:
        pass

    # apply energy delta — reload fresh to avoid clobbering concurrent saves
    try:
        fresh = store.get(char["id"])
        prof  = profile_mod.get(fresh)
        delta = int(thought.energy_delta or 0)
        # code-enforced floor: meals always restore energy regardless of model output
        act_lower = (thought.activity or "").lower()
        if any(w in act_lower for w in ("eat", "meal", "food", "snack", "chai", "coffee",
                                         "lunch", "dinner", "breakfast", "poha", "dosa",
                                         "rice", "roti", "makhana", "fruit")):
            delta = max(delta, 5)   # snack floor
        if any(w in act_lower for w in ("lunch", "dinner", "breakfast", "meal", "biryani",
                                         "thali", "dal", "sabzi")):
            delta = max(delta, 8)   # full meal floor
        new_energy = max(0, min(100, int(prof.get("energy") or 80) + delta))
        profile_mod.patch(fresh, {"energy": new_energy})
        store.save(fresh)
    except Exception:
        pass

    # apply feeling update — always run; falls back to natural drift on bad model output
    try:
        fresh2 = store.get(char["id"])
        prof2  = profile_mod.get(fresh2)
        age    = _age_of(char)
        current_feeling = prof2.get("feeling") or feeling_mod.default_feeling(age)
        new_feeling = feeling_mod.apply_update(current_feeling, thought.feeling_update or {}, age)
        profile_mod.patch(fresh2, {"feeling": new_feeling})
        store.save(fresh2)
    except Exception:
        pass

    # Phase L: interest atrophy/engagement + aspiration logging
    try:
        fresh3 = store.get(char["id"])
        interests_mod.tick(fresh3)
        interests_mod.bump(fresh3, thought.activity)
        store.save(fresh3)
    except Exception:
        pass

    try:
        if thought.aspiration:
            fresh4 = store.get(char["id"])
            profile_mod.add_aspiration(fresh4, thought.aspiration)
            store.save(fresh4)
    except Exception:
        pass

    # Phase I: skill hours bump + level-up event
    try:
        fresh5 = store.get(char["id"])
        levelled = skills_mod.bump_hours(fresh5, thought.activity)
        store.save(fresh5)
        for sk_name in levelled:
            sk = next((s for s in (fresh5.get("profile") or {}).get("skills", []) if s["name"] == sk_name), {})
            profile_mod.log_event(
                char["id"], "skill_levelup", trigger,
                {"activity": thought.activity},
                {"skill": sk_name, "new_level": sk.get("level", ""), "hours": sk.get("hours", 0)},
            )
    except Exception:
        pass

    # Phase L: log new_interest proposal as a life event (owner approves separately)
    if thought.new_interest and isinstance(thought.new_interest, dict) and thought.new_interest.get("name"):
        try:
            profile_mod.log_event(
                char["id"], "interest_proposal", trigger,
                {"activity": thought.activity},
                thought.new_interest,
            )
        except Exception:
            pass

    final = thought.model_dump()
    final["latency_ms"] = round((time.time() - t0) * 1000)
    ev = profile_mod.log_event(char["id"], "think", trigger, pipeline_log, final)
    return {**final, "event_id": ev["id"], "ok": True}


# ── shot-type → camera direction ─────────────────────────────────────────────

SHOT_DIRECTIONS: dict[str, str] = {
    "front_selfie": (
        "Front-camera selfie held at arm's length. Close-up on face and shoulders. "
        "Phone NOT in frame. Slight upward angle, casual and natural."
    ),
    "mirror_selfie": (
        "Mirror selfie. Full-length or half-body reflection visible in the mirror. "
        "Phone held in one hand at chest or hip height, its screen facing the mirror. "
        "The reflection of the person and the phone are both visible in the mirror. "
        "Slight side-angle so person and reflection are both in frame."
    ),
    "propped_timer": (
        "Phone placed on a surface (shelf, desk, windowsill) acting as a stationary camera. "
        "Person visible in the mid or full background. Phone NOT in frame. "
        "Eye-level or slight angle, person looks relaxed, not posing directly at the lens."
    ),
    "pov_first_person": (
        "First-person point-of-view shot. Camera IS the person — eye-level looking down or forward. "
        "Shows what the person sees: her own hands, a plate, a book, a view, a screen. "
        "No other people anywhere in the frame. Person's body and face completely absent. "
        "Phone not visible. Only the subject (the food, object, scene) and optionally her own hands at the bottom of frame."
    ),
    "candid_side": (
        "Candid lifestyle shot from a slight side angle. Person unaware of camera. "
        "No phone in frame. Natural moment."
    ),
}
_DEFAULT_SHOT = "front_selfie"

# parent category chosen by the person -> shot types the character may use
SHOT_CATEGORIES: dict[str, list[str]] = {
    "third_person": ["propped_timer", "candid_side"],
    "selfie":       ["front_selfie", "mirror_selfie"],
    "pov":          ["pov_first_person"],
}
_SHOT_HELP = {
    "front_selfie":     (
        "front_selfie — arm-length face close-up, phone not visible in final frame. "
        "PICK WHEN: checking appearance, bored and making faces, expressing a mood or emotion, "
        "quick mood capture, something funny just happened, feeling cute or confident."
    ),
    "mirror_selfie":    (
        "mirror_selfie — full or half-body reflection in a mirror, phone visible in the reflection. "
        "PICK WHEN: wearing something new or trying an outfit, checking how you look head-to-toe, "
        "passed a mirror somewhere interesting, want to show the full look not just the face."
    ),
    "propped_timer":    (
        "propped_timer — phone on a surface acting as a stationary camera, person in mid/background, "
        "phone not visible in frame. "
        "PICK WHEN: dancing or doing Bhangra practice, yoga, stretching, cooking in the kitchen, "
        "doing any full-body or movement activity where both hands are busy."
    ),
    "candid_side":      (
        "candid_side — lifestyle shot from a slight side angle, no phone, no posing. "
        "PICK WHEN: reading, studying, working at a desk, sitting somewhere scenic, "
        "having tea/coffee, lost in thought, a quiet and atmospheric moment."
    ),
    "pov_first_person": (
        "pov_first_person — camera IS the person; she is invisible. Shows only what she is looking at: "
        "her plate below her, an open book, a view out a window, a screen. "
        "NO other people visible anywhere. NOT a shot of her from outside. "
        "PICK WHEN: the star is a thing in front of her (her own meal, her book, a view she is enjoying) "
        "and she is simply the unseen eyes. DO NOT pick if another person is involved or if 'being served' — "
        "use candid_side or propped_timer for social eating scenes."
    ),
}


def allowed_shot_types(prof: dict) -> list[str]:
    """Shot types allowed by the profile's shot_styles (all when unset or empty)."""
    cats = [c for c in (prof.get("shot_styles") or []) if c in SHOT_CATEGORIES] or list(SHOT_CATEGORIES)
    return [t for c in SHOT_CATEGORIES if c in cats for t in SHOT_CATEGORIES[c]]


def shot_choices_text(types: list[str]) -> str:
    choices = " | ".join(_SHOT_HELP[t] for t in types)
    return (
        "choose exactly one — read each option's PICK WHEN and select the type whose "
        "trigger best matches the current activity and subject. "
        "If eating/drinking alone and the food is the star (no other people, just her plate): pov_first_person. "
        "If showing an outfit: mirror_selfie. "
        "If movement/dance/cooking: propped_timer. "
        "If a quiet atmospheric moment: candid_side. "
        "If mood/face/emotion: front_selfie. "
        "Options: " + choices + ". Empty string if log_photo is false."
    )


def wants_auto_draw(prof: dict, thought: dict) -> bool:
    """Auto-draw only when the person turned it on AND the character judged the moment worth logging."""
    if not prof.get("auto_draw"):
        return False
    lp = thought.get("log_photo", True)
    if isinstance(lp, str):
        lp = lp.strip().lower() not in ("false", "no", "0", "")
    return bool(lp)

# ── draw ──────────────────────────────────────────────────────────────────────

async def draw_thought(char: dict, event_id: str, thought: dict, s: dict, key: str,
                       trigger: str = "manual") -> dict:
    """Generate a picture from a thought and save it as a char_moment media row."""
    from story3 import store as media
    from . import studio

    image_idea  = thought.get("image_idea", "") or thought.get("activity", "") or thought.get("thought", "")   # skipped moments drawn by hand have no idea written
    outfit      = thought.get("outfit", "")
    outfit_id   = thought.get("outfit_id", "").strip()
    expression  = thought.get("expression", "")
    face_state  = thought.get("face_state", "")
    allowed     = allowed_shot_types(profile_mod.get(char))
    shot_type   = thought.get("shot_type", "")
    if shot_type not in allowed:   # the person's shot styles decide; pick the nearest allowed type
        shot_type = allowed[0]
    shot_dir    = SHOT_DIRECTIONS[shot_type]

    canon     = store.canon_items(char)
    has_refs  = "portrait" in canon

    # resolve garment reference if the character picked a wardrobe item
    garment_ref = None
    if outfit_id:
        try:
            from . import wardrobe as wardrobe_mod
            garment_ref = wardrobe_mod.usable(outfit_id)
        except Exception:
            garment_ref = None

    # resolve space reference image for the current activity's space
    space_ref_path = None
    space_name = thought.get("space", "")
    if space_name:
        prof_now = profile_mod.get(char)
        for sp in (prof_now.get("spaces") or []):
            if sp.get("name", "").lower() == space_name.lower() and sp.get("ref_image"):
                candidate = store.media_dir(char["id"]) / sp["ref_image"]
                if candidate.exists():
                    space_ref_path = str(candidate)
                break

    if has_refs:
        from story3.store import path_of as _path
        portrait_path = _path(canon["portrait"])
        portrait_id   = canon["portrait"]["id"]
        expr_line = ""
        if expression or face_state:
            expr_line = " Expression: " + (expression or "") + ("." if expression else "") + (" Face: " + face_state + "." if face_state else "") + " Apply this expression — do not copy the neutral look from the reference picture."

        scene = f"{shot_dir} {image_idea}".strip()
        space_line = (" Match the room/setting layout, furniture, colours and props from the last picture exactly." if space_ref_path else "")
        if garment_ref:
            refs    = [portrait_path, garment_ref["path"]]
            ref_ids = [portrait_id, garment_ref["id"]]
            if space_ref_path:
                refs.append(space_ref_path); ref_ids.append("space-ref")
            prompt  = (f"Picture 1 is an identity reference only (face shape, skin tone, hair colour and length, build). "
                       f"Picture 2 shows the garment/outfit to wear. "
                       + (f"Picture 3 is the room/setting reference — match its layout and decor exactly. " if space_ref_path else "")
                       + f"Create a new vertical 4:5 photograph: {scene}"
                       + (f" Wear the outfit from Picture 2." if outfit else "")
                       + expr_line + space_line
                       + " Match the person's face identity from Picture 1 exactly.")
        else:
            body_in_canon = canon.get("body")
            if body_in_canon:
                refs    = [portrait_path, _path(body_in_canon)]
                ref_ids = [portrait_id, body_in_canon["id"]]
                if space_ref_path:
                    refs.append(space_ref_path); ref_ids.append("space-ref")
                prompt  = (f"Picture 1 is an identity reference only (face shape, skin tone, hair colour and length, build). "
                           f"Picture 2 shows their body and outfit — keep the outfit exactly as in Picture 2. "
                           + (f"Picture 3 is the room/setting reference — match its layout and decor exactly. " if space_ref_path else "")
                           + f"Create a new vertical 4:5 photograph: {scene}"
                           + expr_line + space_line
                           + " Match the person's face identity from Picture 1 exactly.")
            else:
                refs, ref_ids = [portrait_path], [portrait_id]
                if space_ref_path:
                    refs.append(space_ref_path); ref_ids.append("space-ref")
                prompt  = (f"Picture 1 is an identity reference only (face shape, skin tone, hair colour and length, build). "
                           + (f"Picture 2 is the room/setting reference — match its layout and decor exactly. " if space_ref_path else "")
                           + f"Create a new vertical 4:5 photograph: {scene}"
                           + (f" Wearing: {outfit}." if outfit else "")
                           + expr_line + space_line
                           + " Match the person's face identity from Picture 1 exactly.")
        how = "edit"
    else:
        char_desc = (char.get("identity") or "").strip()
        prompt = f"Vertical 4:5 photograph. {shot_dir} {image_idea}" + (f" Wearing: {outfit}." if outfit else "") + (f" {char_desc}" if char_desc else "")
        refs, ref_ids = [], []
        how = "draw"

    from . import render as render_mod

    render_cfg   = char.get("render", {})
    base_loras   = [{"name": x["name"], "strength": x["strength"]} for x in render_cfg.get("loras", []) if x.get("name")]
    existing_names = {x["name"] for x in base_loras}
    # always add raw-photo-v3 for life moments (flat camera look); skip if already present
    all_loras = base_loras + ([{"name": render_mod.RAW_LORA, "strength": 0.7}] if render_mod.RAW_LORA not in existing_names else [])

    # prepend trigger words for active LoRAs (purelens-realism → "p3r4l4ns")
    triggers = render_mod.trigger_words(render_cfg)
    if triggers:
        prompt = f"{triggers} {prompt}"

    body_req = {"model": render_cfg.get("model", ""), "size": "864x1080", "n": 1,
                "response_format": "b64_json", "prompt": prompt[:3900]}
    if all_loras:
        body_req["lora"] = all_loras
    t0 = time.time()
    inputs_draw = {"prompt": prompt[:500], "refs": ref_ids, "how": how, "event_id": event_id}
    try:
        base_url, api_key = studio._ctx(s, key)
        raw = await studio._post_image(how, body_req, refs, base_url, api_key)

        store.media_dir(char["id"], "char_moment").mkdir(parents=True, exist_ok=True)
        it = media.add(char["id"], "char_moment", "moment", 0, "done",
                       {"event_id": event_id, "thought": thought.get("thought", ""),
                        "activity": thought.get("activity", ""), "space": thought.get("space", ""),
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
