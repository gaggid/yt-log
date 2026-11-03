# Virtual Life — Implementation Plan

**Created:** 2026-11-03  
**Status tracking:** update the `Status` column in each phase table as work lands.

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
| 0 | Remove places as characters | pending | `characters/store.py`, `characters/api.py`, `characters/edits.py`, `static/characters.js` |
| A | Profile (personality, interests, spaces) | pending | `characters/profile.py`, `characters/api.py`, `static/characters.js` |
| B | Brain / Think endpoint | pending | `characters/brain.py`, `characters/api.py` |
| C | Draw from thought | pending | `characters/brain.py`, `characters/api.py` |
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

| File | Action | Phase |
|------|--------|-------|
| `characters/store.py` | Remove place kind | 0 |
| `characters/edits.py` | Replace place ref with PlaceDesc | 0 |
| `characters/api.py` | Remove /place, add /in-place, /profile, /think, /life | 0+A+B+C |
| `characters/studio_edit.py` | Update make_place callers | 0 |
| `characters/profile.py` | New — profile get/patch/suggest | A |
| `characters/brain.py` | New — think(), draw_thought(), event logging | B+C |
| `characters/loop.py` | New — idle loop, retry logic | D |
| `characters/db_init.py` (or wherever tables are created) | Add char_life_events table | B |
| `story2/jobs.py` | Add `_last_job_time` update hook (one line) | D |
| `main.py` | Start loop.run_forever() on startup | D |
| `static/characters.js` | Remove places UI, add Virtual Life tab | 0+A+B+C |

---

## What NOT to build yet

- Space reference image generation (text description is sufficient for v1;
  add when image quality of "in a place" looks proves insufficient)
- Multi-character interaction (two characters in one life moment)
- Social feed / sharing
- Character-initiated outfit try-on automation (manual "Save as look" first,
  auto-save when the brain rates its own output ≥ 7)
- Voice lines from the character's thought

---

## How to use this doc while building

1. Before starting a phase, re-read its section — confirm no assumptions changed.
2. After each file is changed, tick its row in the Files summary.
3. When a phase is complete, update the Milestone table status to `done`.
4. If an implementation detail is changed from this plan, note it inline
   under a `> **Changed:** …` block so future readers know why.
