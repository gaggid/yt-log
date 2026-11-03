# Virtual Life — Implementation Plan

**Created:** 2026-11-03  
**Status tracking:** update the `Status` column in each phase table as work lands.

---

## Build status — 2026-11-03

All phases 0–H are **done and committed** (commits 90400f7 → 201ad6d).

| Area | Shipped |
|------|---------|
| Place picker | Replaced with text + optional image upload in character edits |
| Profile | Core character (immutable), personality, city, phone model, fashion taste, interests ×5, spaces, current context |
| Brain pipeline | 5-stage: context assembly → first-pass thought → self-review → goal alignment → memory formation |
| World context | Weather (wttr.in), Google News RSS by interest keyword, Indian season — 30-min cache, fail-silent |
| Day arc | 6 time bands (pre-dawn → night); energy level; appropriate/avoid activity lists; "already done today" guard |
| Goals | CRUD (add/pause/achieve/delete); active summary injected into brain; auto progress-note from ThoughtOut |
| Memory | Episodic; 7-day half-life decay; retrieval by strength × keyword overlap; strength bars in UI |
| Idle loop | Fires when gateway quiet 5+ min; respects `life_enabled` toggle + interval; 15-min retry on busy |
| Wardrobe | Brain sees full wardrobe listing; picks garment via `outfit_id` → garment used as draw reference instead of body canon; `wardrobe_want` saved as memory |
| Shot variety | Brain chooses shot style in `image_idea` (selfie, mirror, propped, POV, candid); phone model named |
| Notes | `note` field in ThoughtOut saved as `[note]` memory for later retrieval |
| UI | Life tab: core char + fashion taste fields; feed shows time, note, wardrobe wish, outfit badge, thumbnail + zoom |

---

## What this is

A "Virtual Life" system layered on top of Character Studio. A character has a
psychometric profile (personality, interests, spaces she lives in). A text
thinking model acts as her brain, bounded by that profile. When the gateway
key is idle, the brain wakes, decides what she is doing right now, forms an
image idea, and generates that look — which is saved to her gallery. Every
step is logged so the owner can audit, replay, and tune the system.

Places are no longer first-class characters. When a user wants to put a
character in a place they supply a text description and an optional reference
image instead.

---

## Milestone table

| Phase | Name | Status | Files |
|-------|------|--------|-------|
| 0 | Remove places as characters | done | `characters/store.py`, `characters/api.py`, `characters/edits.py`, `static/characters.js` |
| A | Profile (personality, interests, spaces) | done | `characters/profile.py`, `characters/api.py`, `static/characters.js` |
| B | Brain / Think endpoint + Draw | done | `characters/brain.py`, `characters/api.py` |
| C | ~~Draw from thought~~ | merged into B | — |
| D | Idle auto-loop | done | `characters/loop.py`, `main.py`, `story2/jobs.py` |
| E | Real-world context (weather + news) | done | `characters/world.py`, `characters/brain.py` |
| F | Goals — set future goals, brain plans toward them | done | `characters/goals.py`, `characters/profile.py`, `characters/brain.py` |
| G | Memory — episodic memory with time-decay and retrieval | done | `characters/memory.py`, `characters/store.py`, `characters/brain.py` |
| D | Autonomous idle loop | pending | `characters/loop.py`, `main.py` |

---

## Phase 0 — Remove places as characters

### Goal
Places are no longer a `kind` in the character library. "Character in a place"
edits accept a text description + an optional uploaded reference image.

### Changes

**`characters/store.py`**
- Remove `"place"` from `KINDS` tuple → `KINDS = ("person",)`
- Remove `"place"` branches from `DECLARED`, `CANON_VIEWS`, and any
  `kind == "place"` guards
- `listing()`: drop the `kind="place"` filter path (only persons now)

**`characters/edits.py`**
- `build_place()` (and any callers in `studio_edit.py`): replace the
  `place` character reference with a `PlaceDesc` struct:
  ```
  class PlaceDesc(TypedDict):
      text: str          # "a sun-lit café in Mumbai"
      image: str | None  # path to an uploaded reference image, or None
  ```
- `PLACE` template stays; the reference list just changes from
  `[portrait, body, place_image]` to `[portrait, body, image]` (when image
  is given) or `[portrait, body]` with text in the prompt.

**`characters/api.py`**
- Remove `POST /{char_id}/place` route that takes a `place` (character id)
- Add `POST /{char_id}/in-place`:
  ```
  Body: { text: str, image: bytes|None, action: str, base: str, n: int }
  ```

**`static/characters.js`**
- Remove the "Places" tab / gallery section
- Replace the place-character picker in the edit modal with a text input
  ("Describe the setting") + file upload ("Reference image (optional)")
- Shorts cast `place_id` is a different feature (background reference for
  the whole short); leave it alone.

### Acceptance
- No place can be created from the UI
- "Character in a place" edit works with text + optional image
- Existing person characters unaffected

---

## Phase A — Profile

### Goal
Each character stores a psychometric profile used by the brain.

### DB change
Add a `profile` key inside the existing `data` JSON blob in `chars` table.
No migration needed — missing `profile` key treated as empty profile.

Profile schema (stored as `char["data"]["profile"]`):
```json
{
  "personality":    "warm, curious, slightly introverted, quick to laugh",
  "interests": {
    "books":    "literary fiction, self-help, mythology",
    "movies":   "slice-of-life, indie drama",
    "music":    "Hindustani classical, lo-fi",
    "food":     "South Indian, dark chocolate, chai",
    "hobbies":  "journaling, morning walks, cooking experiments"
  },
  "spaces": [
    { "name": "Bedroom",     "description": "cosy room with fairy lights, a bookshelf, warm yellow walls, a small desk by the window" },
    { "name": "Living Room", "description": "open, plant-filled, linen sofa, big window, afternoon sun" },
    { "name": "Kitchen",     "description": "small Indian kitchen, white tiles, steel utensils, smell of spices" }
  ],
  "current_context": "just moved to a new city for a job, slightly anxious but excited",
  "life_enabled":    false,
  "life_interval_m": 60
}
```

### New file: `characters/profile.py`
```python
def get(char: dict) -> dict:
    return char.get("data", {}).get("profile") or {}

def patch(char: dict, updates: dict) -> None:
    """Merge updates into profile and save."""

PROFILE_SYSTEM = """You fill in the personality and interests of a fictional character.
Return only a JSON object with keys: personality (one sentence), interests (dict:
books, movies, music, food, hobbies — each a short phrase), spaces (list of
{name, description}), current_context (one sentence).
Do not invent a name or age — those come from the character."""
```

### API change: `characters/api.py`
```
GET  /{char_id}/profile          → returns profile dict
PATCH /{char_id}/profile         → body is partial profile dict; merges and saves
POST /{char_id}/profile/suggest  → LLM call to auto-fill missing fields from the
                                    character's declared age + interests keywords
```

### UI: "Virtual Life" tab in character window
Add a fourth tab (after Gallery / Edit / Looks):

```
┌─────────────────────────────────────────────────┐
│  [Gallery]  [Edit]  [Looks]  [Virtual Life]     │
└─────────────────────────────────────────────────┘

Virtual Life tab — two panels:

LEFT: Profile
  ┌ Personality (textarea) ─────────────────────┐
  │ warm, curious, quick to laugh               │
  └─────────────────────────────────────────────┘
  ┌ Interests ──────────────────────────────────┐
  │  Books: [                              ]    │
  │  Movies:[                              ]    │
  │  Music: [                              ]    │
  │  Food:  [                              ]    │
  │  Hobbies:[                             ]    │
  └─────────────────────────────────────────────┘
  ┌ Spaces (editable list) ─────────────────────┐
  │  + Bedroom · cosy room with fairy lights…   │
  │  + Living Room · …                          │
  │  [+ Add space]                              │
  └─────────────────────────────────────────────┘
  ┌ Current context (what is happening) ────────┐
  │ just moved cities, slightly anxious         │
  └─────────────────────────────────────────────┘
  [Auto-suggest profile]   [Save]
  ─────────────────────────────────────────────
  Auto life:  [ ] Enabled    Interval: [60] min

RIGHT: Life Feed (Phase B onwards — empty until then)
```

### Acceptance
- Profile editable and persisted
- Auto-suggest fills blank fields via LLM, keeps filled ones
- Life enabled toggle + interval saved

---

## Phase B — Brain / Think endpoint

### Goal
One LLM call that produces a structured "thought" from the character's
profile + current date/time. Manual trigger + auto idle trigger.

### New file: `characters/brain.py`

#### Input to LLM
```
SYSTEM:
You are {name}, a {age}-year-old {gender} living in India.
Personality: {personality}
Interests — books: {books}; movies: {movies}; music: {music};
             food: {food}; hobbies: {hobbies}.
Current context: {current_context}.
Today is {weekday}, {date}. Time: {time_of_day}.
Think in the first person. Be specific and human, not poetic.

USER:
What are you doing right now? What does the moment look like?

Return ONLY this JSON:
{
  "thought":     "inner monologue, 1-2 sentences, first person",
  "activity":    "plain description of the activity",
  "space":       "which space from your list, or 'outside' / a place name",
  "mood":        "one word mood tag",
  "outfit":      "what she is wearing right now, plain words",
  "image_idea":  "visual description for an image model: what the picture shows,
                  framing, light, setting — 2-3 sentences, no 'she' or 'her'"
}
```

#### Output schema (`ThoughtOut`)
```python
class ThoughtOut(M):
    thought:    str   # "Ugh, the chai is over-brewed again."
    activity:   str   # "making chai in the kitchen"
    space:      str   # "Kitchen"
    mood:       str   # "nostalgic"
    outfit:     str   # "oversized kurta, hair tied up"
    image_idea: str   # "Close-up of hands wrapping around a steel mug of chai …"
```

#### `think(char, backend, s)` → `ThoughtOut`
- Build system + user prompt from profile
- Call `llm.JsonCaller`
- Log event (see §Event log below)
- Return `ThoughtOut`

### API: `POST /{char_id}/think`
```
Request body: {} (empty, or { "context_override": "…" } for manual nudge)
Response:
{
  "event_id": "evt-…",
  "thought": "…",
  "activity": "…",
  "space": "Kitchen",
  "mood": "nostalgic",
  "outfit": "oversized kurta …",
  "image_idea": "Close-up of hands …"
}
```

### UI
- "What is she thinking?" button in the Virtual Life tab
- Shows a card with the thought + activity + mood badge
- "Draw this look" button on the card → Phase C

### Acceptance
- Manual trigger produces a thought
- Event logged with full inputs + outputs
- Error (LLM down) shows fallback message, logs error event

---

## Phase C — Draw from Thought

### Goal
Turn a `ThoughtOut` into a generated picture saved to the character's gallery.

### Logic in `characters/brain.py`

```python
async def draw_thought(char, event_id, thought_out, backend, s, key):
    """Build an image request from the thought and send it through the edit pipeline."""
    # 1. Resolve space description
    space_desc = _space_text(char, thought_out.space)
    # 2. Build prompt:
    #    image_idea + "Setting: {space_desc}." + outfit context
    #    + mobile selfie framing line (see SELFIE_FRAMING below)
    prompt = _draw_prompt(char, thought_out, space_desc)
    # 3. Use existing edit pipeline (portrait + body refs if canon exists)
    refs = _canon_refs(char)
    body = { "model": settings.image_model, "prompt": prompt,
             "size": "720x1280", "n": 1, "seed": … }
    # 4. Save as media row kind="char_moment"
    # 5. Log draw event
```

#### `SELFIE_FRAMING`
```
"Mobile front-camera selfie, vertical 9:16 frame, natural light, slight candid
angle, close-mid shot, not posed — as if the person glanced at their phone."
```

For non-selfie activities (e.g., cooking, reading) use:
```
"Candid lifestyle photograph, vertical frame, natural available light."
```

Decide by `space` — "outside" or "café" → neutral; home spaces → selfie by default.

### New DB kind: `char_moment`
A `char_moment` media row has the same columns as `char_gen` plus:
```json
"meta": {
  "event_id": "evt-…",
  "thought":  "…",
  "activity": "…",
  "space":    "Kitchen",
  "mood":     "nostalgic"
}
```

### API: `POST /{char_id}/life/{event_id}/draw`
```
Response: { "media_id": "…", "status": "queued" }
```
Starts a job (uses the existing one-job lock in `story2/jobs.py`).

### UI
- "Draw this look" button on the thought card → starts draw job
- Shows the generated image in the Life Feed when done
- "Save as look" button → tags it as a named look in the character's Look gallery

### Acceptance
- Draw produces an image with the character's face from canon refs
- Image saved with event metadata
- "Save as look" works

---

## Phase D — Autonomous Idle Loop

### Goal
When the gateway key has been idle for N minutes, trigger `think` + `draw`
for every character that has `life_enabled = true`.

### Idle detection rule
- The brain only starts when `jobs.busy() == False`
- If the first LLM/image call gets a `JobBusy` exception (another job started
  between the check and the call) → log a `retry` event, reschedule after 15
  minutes
- "Idle" = no job has started for at least 5 minutes (configurable, default 5)

### New file: `characters/loop.py`

```python
RETRY_DELAY_S   = 15 * 60   # 15 min on busy-key error
CHECK_INTERVAL_S = 60        # wake every 60 s to check idle condition
IDLE_AFTER_S     = 5 * 60   # key idle for 5 min before life loop runs

_last_job_time: float = 0.0   # updated by a hook in jobs.start()


async def run_forever(backend, s, key):
    """Background task mounted in main.py on startup."""
    while True:
        await asyncio.sleep(CHECK_INTERVAL_S)
        if jobs.busy():
            continue
        if time.time() - _last_job_time < IDLE_AFTER_S:
            continue
        for char in store.listing("person"):
            prof = profile.get(char)
            if not prof.get("life_enabled"):
                continue
            interval_s = (prof.get("life_interval_m") or 60) * 60
            last_run = _last_life_run(char["id"])
            if last_run and time.time() - last_run < interval_s:
                continue
            try:
                thought = await brain.think(char, backend, s)
                if not jobs.busy():
                    await brain.draw_thought(char, thought.event_id,
                                             thought, backend, s, key)
            except jobs.JobBusy:
                _log_retry(char["id"])
                await asyncio.sleep(RETRY_DELAY_S)
                break                       # retry the whole cycle after delay
```

### Hook into `jobs.start()`
Add one line at the top of `jobs.start()`:
```python
from characters import loop as _vl
_vl._last_job_time = time.time()
```

### `main.py`
On startup, launch `loop.run_forever(...)` as a background task.

### UI
- Auto life toggle + interval in the Profile panel (Phase A)
- Status line in the Life Feed header: "Last run: 5 min ago · Next: ~55 min"

### Acceptance
- Loop only fires when truly idle (no pending user jobs)
- Busy-key error → 15-min retry, logged
- `life_enabled = false` → character never auto-runs

---

## Event log (telemetry / audit trail)

Every action the brain takes is stored so the owner can inspect inputs,
outputs, and errors to improve the system over time.

### New table: `char_life_events`
```sql
CREATE TABLE IF NOT EXISTS char_life_events (
    id          TEXT PRIMARY KEY,
    char_id     TEXT NOT NULL,
    event_type  TEXT NOT NULL,   -- think | draw | retry | error
    trigger     TEXT NOT NULL,   -- manual | auto
    attempt     INTEGER DEFAULT 1,
    inputs      TEXT DEFAULT '{}',   -- JSON: full LLM prompt, image prompt, etc.
    outputs     TEXT DEFAULT '{}',   -- JSON: ThoughtOut, media_id, error message
    created_at  REAL
);
```

Every `think` call logs:
```json
{
  "inputs": {
    "system_prompt": "…",
    "user_prompt": "…",
    "profile_snapshot": { "personality": "…", "interests": {…}, "spaces": […] },
    "date": "Monday 2026-11-03",
    "time_of_day": "afternoon"
  },
  "outputs": {
    "thought": "…",
    "activity": "…",
    "space": "…",
    "mood": "…",
    "outfit": "…",
    "image_idea": "…",
    "model": "…",
    "latency_ms": 1200
  }
}
```

Every `draw` call logs:
```json
{
  "inputs": {
    "image_prompt": "…",
    "refs": ["portrait path", "body path"],
    "size": "720x1280",
    "seed": 42
  },
  "outputs": {
    "media_id": "…",
    "status": "done"
  }
}
```

Every `retry` or `error`:
```json
{
  "outputs": {
    "error": "JobBusy: another planning job is running",
    "retry_after_s": 900
  }
}
```

### API: `GET /{char_id}/life`
Returns the 50 most recent events, newest first:
```json
[
  {
    "id": "evt-…",
    "event_type": "think",
    "trigger": "manual",
    "created_at": 1762123456.0,
    "outputs": { "thought": "…", "image_idea": "…", "media_id": "…" }
  }
]
```

### UI: Life Feed
Each entry in the Life Feed:
- Timestamp (relative: "3 min ago")
- Mood badge + activity label
- Thought (italic, first-person)
- Generated image (if drawn), with "Save as look" button
- Collapsed "Debug" section: shows `inputs` + `outputs` JSON
  (so the owner can see exactly what went in and came out and tune it)

---

## Files summary

| File | Action | Phase | Status |
|------|--------|-------|--------|
| `characters/store.py` | KINDS kept (shorts cast); `char_life_events` + `char_memories` tables added to SCHEMA | 0+B+G | done |
| `characters/edits.py` | `build_in_place()` added (text + optional image path, no place character) | 0 | done |
| `characters/studio_edit.py` | `make_in_place()` added | 0 | done |
| `characters/api.py` | `/in-place`, `/profile`, `/goals`, `/memories`, `/think`, `/life`, `/life/status`, `/life/{id}/draw` | 0+A+B+D+F+G | done |
| `characters/profile.py` | New — get/patch/default_profile, log_event/list_events/last_run_time | A | done |
| `characters/brain.py` | New — 5-stage pipeline (context assembly → think → self-review → goal alignment → post-think), draw_thought() | B+E+F+G | done |
| `characters/world.py` | New — weather (wttr.in), news (Google RSS), season; 30-min cache | E | done |
| `characters/goals.py` | New — add/update/delete/active_summary/neglected_goals/try_log_progress | F | done |
| `characters/memory.py` | New — form/retrieve/decay/list/delete/add_manual, 7-day half-life | G | done |
| `characters/loop.py` | New — idle loop, 5-min quiet guard, 15-min retry on JobBusy | D | done |
| `story2/jobs.py` | `_last_activity` float + one-line update in `start()` | D | done |
| `main.py` | `loop.start(s, key)` in lifespan, `loop.stop()` on shutdown | D | done |
| `static/characters.js` | Places removed from UI; Virtual Life tab (profile/goals/memory/feed) | 0+A+B+D+F+G | done |

---

## Phase E — Real-world context (weather + news)

### Goal
Before each `think()` call, fetch a brief about the character's current world:
weather for her city and 2–3 news headlines relevant to her interests.
The brain sees this as additional context and reacts naturally — rain →
stays home, IPL final → thinks about the match.

### New file: `characters/world.py`

```python
CACHE: dict = {}          # {key: (timestamp, data)}
CACHE_TTL_S = 1800        # 30 minutes

async def brief(char: dict) -> dict:
    """Return {weather: str, news: list[str]} — both optional, fail silently."""

# Weather: wttr.in (no API key, simple one-line format)
async def _weather(city: str) -> str:
    url = f"https://wttr.in/{city}?format=3"
    # "Mumbai: ⛅️  +28°C"

# News: Google News RSS filtered by interest keywords
# https://news.google.com/rss/search?q={topic}&hl=en-IN&gl=IN&ceid=IN:en
# Parse XML, take first 3 titles, strip source suffix
async def _news(interests: dict) -> list[str]:
    keywords = _top_keywords(interests)   # up to 3 most specific interest terms
    ...
```

### City in profile
Add `city: str` field to profile (default "Mumbai"). Used for weather lookup.
`profile["city"] = "Mumbai"`

### Integration in `brain.think()`
```python
world = await world_mod.brief(char)
# Injected into system prompt:
# "Today: ⛅️ 28°C in Mumbai. Trending in India: IPL Finals today, Ranveer interview."
```

### Acceptance
- Weather and news are fetched and injected before think
- If both fail → think proceeds with no world context
- Results cached 30 min (no duplicate calls on rapid manual triggers)

---

## Phase F — Goals

### Goal
A character can hold 3–5 goals at a time (career, personal, creative, health,
social). Active goals are summarised in the brain's prompt so thoughts tend
toward them. The brain can note progress and the owner can mark goals done.

### Storage
Goals live in `profile["goals"]` — a list of dicts. No new table.

```json
"goals": [
  {
    "id": "g-abc12",
    "title": "Learn Kathak",
    "category": "creative",
    "description": "Take one class a week, practice 20 min at home every day",
    "status": "active",      // active | paused | achieved
    "created_at": 1762000000,
    "progress_notes": ["Enrolled in a class near home", "First session felt hard but fun"]
  }
]
```

### New file: `characters/goals.py`
```python
def list_goals(char: dict) -> list[dict]:
def add_goal(char: dict, title, category, description) -> dict:
def update_goal(char: dict, goal_id, **updates) -> dict:
def delete_goal(char: dict, goal_id) -> dict:
def active_summary(char: dict) -> str:
    """2-3 sentence summary of active goals for the brain's prompt."""
```

### API endpoints
```
GET    /{char_id}/goals           → list
POST   /{char_id}/goals           → add
PATCH  /{char_id}/goals/{goal_id} → update (status, progress_notes, etc.)
DELETE /{char_id}/goals/{goal_id} → remove
```

### Brain integration
System prompt gains a section:
```
Current goals (working toward):
- Learn Kathak (creative): take one class a week, practice daily
- Get promoted to senior marketing (career): lead one campaign this quarter
```

The brain naturally references these in its thoughts ("I should practice today")
and the `ThoughtOut` schema gets an optional `goal_progress` field:
```
"goal_progress": "practiced Kathak for 20 min"  // or "" if irrelevant
```
When non-empty, it is appended as a progress note to the matching goal.

### UI
- Goals section in the Virtual Life tab (below Profile)
- Add / edit / mark achieved / delete
- Each goal shows status badge + progress notes (expandable)

### Acceptance
- Goals appear in brain system prompt
- Brain occasionally references them in thoughts
- Progress notes grow over time

---

## Phase G — Memory

### Goal
The character builds episodic memories from her daily thoughts. Memories
decay with age (newer = stronger = more likely recalled). Before each think
the brain gets her 4–5 most relevant memories so she stays consistent and
builds on past experience.

### Memory decay
Half-life = 7 days. `strength(t) = 0.5^(days_since_formed / 7.0)`.
Memories with `strength < 0.04` (≈ 40 days old at full formation) are
considered faded and not retrieved (but kept in DB for history).

### New table: `char_memories`
```sql
CREATE TABLE IF NOT EXISTS char_memories (
    id            TEXT PRIMARY KEY,
    char_id       TEXT NOT NULL,
    content       TEXT NOT NULL,     -- the memory sentence(s)
    tags          TEXT DEFAULT '[]', -- JSON [keyword, ...]
    category      TEXT DEFAULT 'episodic',  -- episodic | goal | reflection
    base_strength REAL DEFAULT 1.0,  -- set at formation, never changed
    formed_at     REAL,
    last_accessed_at REAL
);
```

### New file: `characters/memory.py`

```python
HALF_LIFE_DAYS = 7.0
FADE_THRESHOLD = 0.04     # below this → faded, not retrieved

def strength(mem: dict) -> float:
    days = (time.time() - mem["formed_at"]) / 86400
    return mem["base_strength"] * (0.5 ** (days / HALF_LIFE_DAYS))

def form(char_id: str, thought: dict) -> dict:
    """Extract and save a memory from a ThoughtOut. Called automatically after think."""
    content = f"{thought.get('activity','?')} at {thought.get('space','?')}. {thought.get('thought','')}"
    tags = _extract_tags(thought)
    # Save to char_memories
    ...

def retrieve(char_id: str, context: str, n: int = 5) -> list[dict]:
    """Top n memories by strength × keyword_overlap(context). Skips faded ones."""
    ...

def memories_prompt(mems: list[dict]) -> str:
    """A short block injected into the brain's user prompt."""
    if not mems: return ""
    lines = [f"- {m['content']} (strength {strength(m):.2f})" for m in mems]
    return "Recent memories (freshest first):\n" + "\n".join(lines)
```

### Brain integration
Before `think()`:
```python
mems = memory.retrieve(char["id"], context=activity_context, n=5)
# Injected into user prompt:
# "Recent memories:
#  - Made great pasta at home last Tuesday. (0.92)
#  - Felt disconnected at Priya's party. (0.74)
#  - Started 'The White Tiger'. Gripping so far. (0.41)"
```

After `think()`:
```python
memory.form(char["id"], thought_out)
```

### Memory retrieval algorithm
1. Load all char memories with `strength > FADE_THRESHOLD`
2. Score each: `score = strength × (1 + 0.5 × keyword_overlap(content, context))`
3. Sort by score descending, return top n
4. Update `last_accessed_at` for retrieved memories

### UI
- Memory viewer in the Virtual Life tab — a list of memories with their
  strength bars (0–1 visualised as a thin bar, greyed when < 0.2)
- Search/filter by tag
- Owner can manually add a memory or delete one

### Acceptance
- Memory formed after every think (no extra LLM call)
- 5 strongest memories appear in brain's user prompt
- After 40 days without reinforcement, memory fades below threshold
- Memory list visible in the UI with strength bars

---

## Agentic think pipeline (Phases E + F + G combined)

The `think()` call is not a single linear prompt. It runs an iterative pipeline:

```
Stage 1: CONTEXT ASSEMBLY
  - World brief (weather, news)          → world.py
  - Active memories (top 5 by strength)  → memory.py
  - Active goals summary                 → goals.py
  - Time of day, season, day of week

Stage 2: FIRST-PASS THOUGHT (LLM call 1)
  System: character identity + personality + interests + spaces
  User:   assembled context above
  Out:    ThoughtOut (thought, activity, space, mood, outfit, image_idea)

Stage 3: SELF-REVIEW (LLM call 2 — the character "reads back" her thought)
  System: same character identity
  User:   "You just thought this: [thought]. Does it feel true to you right now,
           given your goals and recent memories? Revise if needed or confirm."
  Out:    ThoughtRevised { confirmed: bool, revised_thought: str, revised_image_idea: str }
  — if confirmed: use original; if revised: use revised values

Stage 4: GOAL ALIGNMENT CHECK (code, no LLM)
  - If ThoughtOut.activity is semantically close to an active goal → append
    progress note to that goal automatically
  - If no goal touched in last 3 days → nudge: inject "she has been neglecting
    her Kathak practice" into Stage 1 next time

Stage 5: POST-THINK
  - Form memory from final thought
  - Log full pipeline inputs/outputs to char_life_events
  - Return final ThoughtOut
```

### Why iterative (not one big prompt)
A single prompt asking the character to think, self-review, align with goals
and produce an image idea reliably in one shot is too long a chain — the model
drifts. Two small focused calls (think → review) with the second grounded in
the first produces more coherent, self-consistent output.

### ThoughtRevised schema
```python
class ThoughtRevised(M):
    confirmed:          bool = True
    revised_thought:    Str = ""
    revised_image_idea: Str = ""
    goal_progress:      Str = ""   # if non-empty, append to matching goal
```

---

## Remaining / future work

These are not started. Add a phase row and spec section before building.

| Item | Notes |
|------|-------|
| **Phase H — 24-hour day rhythm** | See full spec below |
| **Phase I — Character evolution (skills, mastery)** | See full spec below |
| **Internet suite (Phase J)** | Full-fledged browsing: character opens real URLs, reads pages, reacts to content, discovers fashion/trends/news organically. Not limited to RSS. Needs a browser tool layer. Parked until that layer is built. |
| Space reference image generation | Text description is good enough for v1; add when "in a place" image quality proves insufficient |
| Multi-character interaction | Two characters in one life moment — needs cast + shared scene logic |
| Social feed / sharing | Export life feed as Instagram-style reel or image grid |
| Auto "Save as look" | Brain rates its own image (≥7/10) → auto-saves as a named look; manual for now |
| Voice lines | Character speaks her thought as a short audio clip (TTS) |
| Profile auto-suggest | LLM fills blank interest/personality fields from the character's idea — endpoint spec'd in Phase A but not built |
| Goal-driven image planning | Brain proactively imagines a goal-related activity rather than reacting to the current moment only |
| Memory reinforcement | Recalling a memory during think boosts its strength slightly (currently pure time-decay) |
| Cross-character memory | Two characters share an experience and both form memories of it |

---

## Phase H — 24-hour day rhythm (not started)

### The problem today
The brain knows the time of day but treats every think cycle identically.
A 25-year-old does not paint at 3 am or do cardio at 11 pm. The day is a
structured arc and the brain should know exactly where it sits in that arc —
and what has already happened today so it does not repeat itself.

### Day arc: 6 bands

| Band | Hours | Energy | Appropriate | Never |
|------|-------|--------|-------------|-------|
| Pre-dawn | 00–05 | 0 | sleep, insomnia scroll, late-night reflection | exercise, social outings |
| Morning | 06–10 | rising | routine (chai, skincare, workout), planning, commute | heavy social events |
| Midday | 10–14 | peak | focused work, errands, lunch, learning practice | wind-down, passive TV |
| Afternoon | 14–18 | moderate | creative work, casual social, snack, light practice | heavy decisions |
| Evening | 18–22 | social | dinner, friends, outings, phone calls, hobbies | focused work, study |
| Night | 22–00 | falling | wind-down, reading, reflection, skincare | exercise, social outings |

### Week-level awareness
- **Weekday**: work/study obligations; goal-directed activities more likely
- **Saturday**: highest energy for outings, social, creative experiments
- **Sunday**: rest and reflection; introspective mood; week-prep
- **Month start (day 1)**: special — review goals, reflect on last month

### "Already done today" guard
Stage-1 context assembly queries today's think events to prevent repetition:
```python
# world.py or brain.py
done_today = [ev["outputs"]["activity"] for ev in recent if is_today(ev["created_at"])]
# Injected: "Today you have already: made chai, went for a walk, had a work call."
```
The brain will not repeat these naturally once it knows.

### Implementation sketch
Extend `world.py` with `day_arc(char)` returning band, energy, appropriate
activities list, avoid list, day type, and any month/week milestone note.
Inject as a short paragraph into stage-1 context. No new DB table needed.

---

## Phase I — Character evolution: experience → skills → mastery (not started)

### The idea
A character who has practiced Kathak for 3 months thinks about it differently
than someone who started last week. Skills have levels. How fast a character
levels up depends on hours spent AND a natural efficiency modifier declared
at creation. Over weeks and months the character genuinely changes — not just
accumulating memories but becoming someone new.

### Skill model

Each skill:
- **Name** — "Kathak", "home cooking", "Hindustani vocals", "watercolour"
- **Category** — creative / physical / professional / social / knowledge
- **Level** — 0 to 10 (0 = curious newcomer, 10 = mastery)
- **Efficiency** — 0.5–2.0 (talent modifier; declared at profile creation, never changes)
- **Practice hours** — accumulated total
- **Goal link** — `goal_id` this skill is tied to (practice flows from goal progress)

| Level | Label | Base hours to reach next |
|-------|-------|--------------------------|
| 0 | Curious | 2 |
| 1 | Beginner | 8 |
| 2 | Trying | 20 |
| 3 | Consistent | 40 |
| 4 | Developing | 80 |
| 5 | Competent | 150 |
| 6 | Skilled | 250 |
| 7 | Proficient | 400 |
| 8 | Advanced | 600 |
| 9 | Expert | 900 |
| 10 | Mastery | — |

Actual hours to level up = `BASE_HOURS[level] / efficiency`. A naturally
talented character (efficiency 1.5) reaches Competent in 100 hours instead of 150.

### How skills grow
`goals.try_log_progress()` calls `skills.accumulate(char, goal_id, hours)`.
Practice hours per session are estimated from the time-band (Phase H) — an
evening hobby session ≈ 1.0 hr, a weekend deep-dive ≈ 2.5 hr.

Skills can also be seeded at any level in the profile: "she has been cooking
since childhood" → owner sets starting level 5.

### How skills enter the brain
Stage-1 context summary:
```
Your skills: Kathak (level 3 — Consistent, 42h), home cooking (level 6 — Skilled).
```
The brain writes `image_idea` and `thought` with this context so:
- Level 1 Kathak → clumsy stance, practice clothes, basic room
- Level 8 Kathak → confident performance posture, studio, expressive face

No extra code path — the image prompt is written by the brain naturally.

### Milestone events
On level-up, a `skill_levelup` event is logged to `char_life_events`.
The brain is told "you just reached level 4 in Kathak" and produces a
milestone reflection + a distinct image to mark the moment.

### Storage
```python
# profile["skills"] = [
#   {"name": "Kathak", "category": "creative", "level": 3,
#    "efficiency": 1.2, "practice_hours": 42.5, "goal_id": "g-abc12"},
# ]
```
Stored in `profile["skills"]` — no new table needed.

### Implementation order (when the time comes)
1. Skill declaration at profile creation (or linked to a goal, starts at level 0)
2. `skills.accumulate(char, goal_id, hours)` — called by `goals.try_log_progress`
3. `skills.summary(char)` — plain text block for stage-1 context
4. Level-up detection + milestone event in `skills.accumulate`
5. UI: skills panel in Virtual Life tab (below goals), level bars + hours shown

---

## How to use this doc while building

1. Before starting a phase, re-read its section — confirm no assumptions changed.
2. After each file is changed, tick its row in the Files summary.
3. When a phase is complete, update the Milestone table status to `done`.
4. If an implementation detail is changed from this plan, note it inline
   under a `> **Changed:** …` block so future readers know why.
