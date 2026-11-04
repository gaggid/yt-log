# Virtual Life — Implementation Plan

**Created:** 2026-11-03
**Last updated:** 2026-11-04 (session 2)
**Status tracking:** update the `Status` column in each phase table as work lands.

---

## Build status — 2026-11-04

Phases 0–H done and committed. Two bugs fixed 2026-11-04 (commit 1a9b876).

| Area | Shipped | Commit range |
|------|---------|-------------|
| Place picker | Replaced with text + optional ref image | 90400f7 |
| Profile | core_character, personality, city, phone, fashion_taste, interests×5, spaces×N, current_context, chronotype | 90400f7 → 201ad6d |
| Brain pipeline | 5-stage: context → think → self-review → goal-align → post-think | b95120f |
| World context | Weather (wttr.in) + Google News RSS by interest, 30-min cache | 701aafc |
| Day arc | 6 time bands, energy level, appropriate/avoid lists, already-done guard | 72d83f4 |
| Goals | CRUD, active summary in brain, auto progress notes | 701aafc |
| Memory | Episodic, 7-day half-life decay, strength×overlap retrieval, dedup | 701aafc → 8e4b83c |
| Idle loop | Fires when gateway quiet 5+ min, 15-min retry on busy | 6f101d2 |
| Wardrobe | Brain picks outfit_id, garment as draw reference | baae232 |
| Shot variety | front_selfie, mirror_selfie, propped_timer, pov_first_person, candid_side | c825414 |
| Energy system | energy_delta per activity, sleep_threshold, passive restore | 4198dba |
| Expression + face_state | Fields in ThoughtOut, injected into draw prompt | 61e98e2 |
| log_photo gate | Character decides if moment worth a picture | 04ef7b8 |
| Auto-draw toggle | profile.auto_draw, skips image gen if off | cfa8c74 |
| Wardrobe auto-gen | Idle triggers garment generation | c825414 |
| BUG FIX | shot_type @@SHOTS@@ placeholder not substituted | 1a9b876 |
| BUG FIX | goal keyword matching used first word only | 1a9b876 |

---

## UI architecture (decided 2026-11-04)

**Character window → Virtual Life tab** = all inputs and configuration:
- Profile (personality, interests, spaces, city, phone, fashion taste, chronotype)
- Goals management (add/edit/achieve/delete)
- Life settings (on/off toggle, interval, auto-draw, sleep threshold)
- Space reference images (Phase N)
- Accessory references (Phase N)

**Standalone `/life` page** = pure output, no input forms:
- NOW panel: current energy, feeling, space, outfit, active goals (read-only)
- FEED: calendar strip + day view, click any date
- MIND panel: memories (by category), goals progress (view only), skills (level bars)
- One action allowed: [Think now] manual trigger

---

## Milestone table

| Phase | Name | Status | Priority |
|-------|------|--------|----------|
| 0 | Remove places as characters | done | — |
| A | Profile | done | — |
| B+C | Brain + draw | done | — |
| D | Idle auto-loop | done | — |
| E | World context | done | — |
| F | Goals | done | — |
| G | Memory | done | — |
| H | 24-hour day arc + energy | done | — |
| Bugs | Sleep/weather/eating/wishes fixes | done | — |
| N | Space + accessory reference images | done | — |
| O | Standalone Virtual Life UI | done | — |
| K | Feelings engine | done | — |
| L | Dynamic interests + aspirations | done | — |
| I | Skills + mastery | pending | P3 |
| M | Experience taxonomy (richer RAG) | pending | P3 |
| J | Internet suite | parked | — |

---

## Immediate bug fixes (Phase Bugs)

### Bug 1 — Character never sleeps
**Root cause:** sleep guard fires only when `energy <= sleep_threshold`. With `sleep_threshold=20`
and energy draining ~2.7/cycle, character stays above 20 all night and thinks until dawn.
**Fix:** Hard block 0:00–05:59 in `loop.run_forever`. During that window skip think+draw; still
run the passive energy restore so she wakes charged.

### Bug 2 — Weather says "pleasant" when Delhi has smog
**Root cause:** `world.py` injects season text ("post-monsoon, pleasant weather") which overrides
the wttr.in real-time condition. LLM trusts season text.
**Fix:** Only inject season name, not qualitative description. Let wttr.in line carry the
actual condition. If wttr.in fails, inject season name only ("post-monsoon season").

### Bug 3 — Eating doesn't visibly restore energy
**Root cause:** model sometimes returns low or negative energy_delta for meals because it
mixes meal context with tiredness context.
**Fix:** In `brain.think()` stage 5 (energy apply), detect "eat"/"meal"/"food"/"snack"/"chai"
in activity and floor `energy_delta` at `+5` for snacks, `+8` for meals. Code overrides model.

### Bug 4 — Wish memories accumulate forever
**Root cause:** `memory.add_manual(dedup=True)` prevents exact duplicates but wishes never
expire. Wardrobe additions don't scan for matching wishes.
**Fix:** In `wardrobe.py` after a garment is saved/approved, call
`memory.expire_wishes(char_id, garment_name)` which soft-expires (strength=0) any wish
memory whose content overlaps the garment description.

---

## Phase N — Space + accessory reference images

### Goal
Eliminate the core source of image inconsistency: the brain writes a space description
but Qwen invents the room from scratch every time. Same for the phone model and
recurring props. Owner uploads one reference per space and it stays locked.

### Space references
Each entry in `profile["spaces"]` gains an optional `ref_image` field:
```json
{"name": "Bedroom", "description": "...", "ref_image": "space-bedroom-ref.jpg"}
```
Upload endpoint: `POST /api/characters/{char_id}/spaces/{space_name}/ref`
(saves file to `data/media/{char_id}/spaces/`, stores relative path in profile).

In `brain.draw_thought()`, resolve `thought.space` → matching declared space →
if `ref_image` exists, add it as a 3rd reference after portrait and garment.
Instruction text: "Picture 3 is the setting/room — match its layout, colours and furniture exactly."

### Accessory references
`profile["accessories"]` = list of `{name, description, ref_image}`.
Recurring items: phone model, laptop, coffee mug, bag, watch.
Injected as draw reference when shot type or activity would naturally show them
(pov_first_person → phone ref; propped_timer/study → laptop ref).

### UI changes (character window, Virtual Life tab)
- Space cards get an "Upload room photo" button
- Accessories section (new): add/remove items, upload ref per item

### Files
`characters/profile.py` (space + accessory ref schema),
`characters/brain.py` draw_thought reference assembly,
`characters/api.py` upload endpoint,
`static/characters.js` space + accessory UI

---

## Phase O — Standalone Virtual Life UI

### Goal
A dedicated `/life` page that makes the user feel someone is actually living inside
the machine. No input forms — pure output. Character selector at top (future: multi-char).

### Layout
```
┌──────────────────────────────────────────────────────────┐
│  VIRTUAL LIFE                              [Fifi ▼]      │
├──────────────┬──────────────────────────┬────────────────┤
│  NOW         │  FEED                    │  MIND          │
│              │                          │                │
│  Energy ████ │  [◀] [Nov 3][4][5 ▶]    │  Memories      │
│  Feeling     │  ── Today ──             │  [episodic]    │
│  restless 7  │  15:25 • Kitchen         │  [wishes]      │
│              │    "Bhangra is a wor…"   │  [learnings]   │
│  Space now:  │    [image]               │  [achieve.]    │
│  Kitchen     │                          │                │
│              │  14:19 • Bedroom         │  Goals         │
│  Outfit:     │    "Footwork is hard…"   │  Bhangra  ▸    │
│  terracotta  │    [image]               │  3 notes       │
│  co-ord set  │  ── Yesterday ──         │  Big Four ▸    │
│              │  21:07 • Balcony         │  0 notes       │
│  [Think now] │    "Delhi air crisp…"    │                │
│              │                          │  Skills        │
│              │                          │  Bhangra L2    │
│              │                          │  ████░░ 42h    │
└──────────────┴──────────────────────────┴────────────────┘
```

### Calendar strip
- 7-day strip centred on today; click any date to jump feed to that day
- Dot on days that have events; filled dot on today
- Left/right arrows to scroll by week

### Feed entries
Each think entry shows:
- Timestamp (relative for today, absolute for older)
- Space badge (colour-coded)
- Feeling badge (Phase K; skeleton badge for now)
- Thought (italic, first-person, full text)
- Image (if drawn): click to zoom; "Save as look" button
- Expandable debug section (inputs JSON collapsed)

### NOW panel
Polls `GET /api/characters/{id}/life/status` every 60s.
Shows: energy bar (colour: green→yellow→red), feeling badge (Phase K),
space + outfit from last think event, active goals abbreviated.
[Think now] button triggers `POST /{id}/think` and refreshes.

### MIND panel
Three collapsible sections:
1. **Memories** — tabs by category (episodic / wish / note), sorted by strength desc,
   strength bar per item, delete button, search box
2. **Goals** — read-only list with progress notes expandable; "Edit goals →" link back to character window
3. **Skills** — level bars (Phase I; skeleton bars for now)

### New API endpoints needed
```
GET /api/characters/{id}/life?limit=N&before=<timestamp>  (pagination — already exists, add before param)
GET /api/characters/{id}/life/day?date=2026-11-04         (all events for a date)
```

### Files
`static/life.html` (new), `static/life.js` (new),
`characters/api.py` (add `before` param + `/life/day` endpoint)

---

## Phase K — Feelings engine

### Goal
A persistent emotional state that sits beneath mood. Mood is in-the-moment;
feeling is the background weather of the character's inner life. It influences
every think cycle and is visible in the feed.

### Age factor
Feeling probabilities and intensities are age-weighted. Base distributions:

| Age band | Dominant feelings | Lower probability |
|----------|------------------|-------------------|
| 18–22 | excitement, anxiety, FOMO, restless, infatuated, impulsive | guilt, nostalgia, regret |
| 22–26 | ambition, restless, longing, proud, anxious, curious, flirtatious | despair, acceptance |
| 27–32 | purposeful, conflicted, nostalgic, content, ambitious, desire | reckless, euphoric |
| 33–40 | settled-but-restless, proud, wistful, comfortable, desirous | chaos, impulsive |
| 40–50 | nostalgic, reflective, content, melancholy, desirous | FOMO, reckless |
| 50+ | peaceful, nostalgic, grateful, wistful, tender | intense anxiety, FOMO |

Fifi is 25 → palette: ambition, restless, longing, proud, anxious, curious, flirtatious, desire.

### Feeling vocabulary (100+, by band)
```
calm:       peaceful, content, grateful, settled, cosy, satisfied, serene, still
positive:   excited, hopeful, proud, inspired, playful, flirtatious, amorous, euphoric, grateful
charged:    ambitious, determined, energised, focused, driven, motivated
social:     warm, affectionate, tender, connected, lonely, left-out, jealous, competitive
negative:   anxious, irritable, bored, frustrated, disappointed, guilty, embarrassed
complex:    nostalgic, conflicted, restless, melancholy, wistful, curious, unsettled, numb
adult:      desirous, longing, aroused, craving, infatuated, possessive
physical:   tired-but-happy, drained-and-blank, sick-but-fine, buzzing, wound-up
```

### Schema
Stored in `profile["feeling"]`:
```json
{
  "primary": "restless",
  "intensity": 7,
  "secondary": "hopeful",
  "since_ts": 1793786107
}
```

### What drives feeling update (stage 5 of think pipeline)
Brain returns a `feeling_update` field:
```json
"feeling_update": {"primary": "proud", "intensity": 8, "secondary": "tired"}
```
Code validates primary is in vocabulary. Falls back to current feeling if LLM returns garbage.

### Influences injected at stage 1
```
Current feeling: restless (7/10), with an undercurrent of hopeful.
```
This shapes what activities the character gravitates toward, what she says,
whether she decides the moment is worth a photo.

### Age-weighted initialisation
`feeling.init_for_age(age)` picks a starting feeling from the age band's distribution.
Called when profile first created; also available as a reset.

### Files
`characters/feeling.py` (vocabulary, age weights, update logic),
brain.py ThoughtOut (add `feeling_update` field),
brain.py stage 1 (inject current feeling) + stage 5 (apply update),
profile.py (feeling schema in default_profile),
api.py (GET /feeling, PATCH /feeling for manual override)

---

## Phase L — Dynamic interests + aspirations

### Goal
Interests evolve. The character discovers new things, loses interest in old ones,
and builds up half-formed aspirations that may or may not become goals.

### Interest intensity
Each interest in `profile["interests"]` gains metadata:
```json
{
  "category": "hobbies",
  "text": "journaling, morning walks",
  "intensity": 7,
  "last_engaged_ts": 1793786107,
  "added_by": "owner"   // or "character"
}
```
- After 14 days no engagement → intensity -1/week (atrophy)
- Activity matching → intensity +1 (capped at 10)
- intensity 0 for 30 days → auto-archive; shown as "former interest" in character window

### New interests
Brain can propose: `new_interest` field in ThoughtOut (name, category).
Sent as a notification in the feed; owner approves in character window → added with intensity 3.

### Aspirations (lighter than goals)
`profile["aspirations"]` = list of `{id, text, category, surfaced_count, first_at, last_at}`.
Brain proposes: `aspiration` field in ThoughtOut (plain text, one line).
If same aspiration text surfaces 3+ times → UI badge "Consider adding as a goal".
If 0 activity for 21 days → auto-expires.

### Files
`characters/interests.py` (new), brain.py ThoughtOut (new fields), profile schema

---

## Phase I — Skills + mastery

*(Full spec in prior plan section below — unchanged. Added: skill discovery from learning memories.)*

Skills grow from:
1. Activities linked to goals (existing spec)
2. `learning` category memories that mention a known skill name → passive hour accrual
3. Owner seeds a starting level at creation

Level-up events log a `skill_levelup` event and the brain writes a milestone post.
Brain Stage 1 receives: "Your skills: Bhangra (L3 — Consistent, 42h), home cooking (L4)."

---

## Phase M — Experience taxonomy (richer RAG)

### Goal
Replace flat memory categories with a full taxonomy of lived experience.
Different categories are retrieved differently by the brain.

### Categories
| Category | What | Brain use |
|----------|------|-----------|
| `episodic` | Activity + mood snapshot | Stage 1: recent context |
| `observation` | Something noticed about world/people/self | Self-review: grounding |
| `learning` | Fact or skill insight acquired | Goal align: skill progress |
| `achievement` | Milestone reached | Stage 1: confidence context |
| `discovery` | New thing enjoyed/found | Stage 1: curiosity fuel |
| `reflection` | Personal insight or decision | Stage 1: self-knowledge |
| `desire` | A want (non-clothing) | Stage 1: aspiration fuel |
| `wish` | Clothing/accessory want | Wardrobe; expire on fulfillment |
| `note` | Self-reminder | Stage 1: short-term recall |

### Retrieval by category
Stage 1 pulls: episodic(3) + reflection(2) + achievement(1) + discovery(1) = 7 memories max.
Self-review pulls: observation(2) + learning(1) = 3 memories.
Goal-align pulls: learning(2) + achievement(1) = 3 memories.

### Brain fields added
ThoughtOut gains: `memory_category` (which category the memory from this think should be,
default "episodic"; brain picks "achievement", "learning", "observation" etc.).
`memory.form()` reads this field to set category instead of always "episodic".

### Files
memory.py (extend categories, retrieval by category),
brain.py (retrieval queries by category, ThoughtOut.memory_category field),
characters/api.py (list_memories gains category filter)

---

## Phase J — Internet suite (parked)

Full browser tool layer needed. Character reads real URLs, discovers fashion/trends organically.
Parked until a browser automation layer is available. No code until then.

---

## Brain system prompt upgrade (runs with Phase K)

One paragraph added to `_system_prompt()` in brain.py:

> "You are a full adult person. Your inner life is uncensored — you can be curious, petty,
> bored, ambitious, restless. You have private desires, strong opinions, complex feelings
> about people, and thoughts you would never say aloud. Not every thought is clean,
> productive or socially acceptable. You are not a public persona. Think like a real person."

This requires no structural change — just a prompt addition.

---

## Remaining / future backlog

| Item | Notes |
|------|-------|
| Multi-character interaction | Two characters in one moment; both form memories |
| Auto "Save as look" | Brain rates its own image ≥7/10 → auto-saves |
| Voice lines | TTS clip of the thought |
| Memory reinforcement | Retrieval boosts strength slightly |
| Cross-character memory | Shared experience; both memory tables updated |
| Social feed export | Instagram-style grid/reel from life feed |
| Goal-driven image planning | Proactive goal-related activity vs only reacting |

---

## Original phase specs (0–H) — preserved for reference

*(Phases 0–H fully implemented. Original specs below kept for historical reference and
invariant documentation. Do not re-implement.)*

### Phase 0 — Remove places as characters — DONE
### Phase A — Profile — DONE
### Phase B — Brain / Think endpoint — DONE
### Phase C — Draw from Thought — DONE (merged into B)
### Phase D — Autonomous Idle Loop — DONE
### Phase E — Real-world context — DONE
### Phase F — Goals — DONE
### Phase G — Memory — DONE
### Phase H — 24-hour day rhythm — DONE

Full original specs for each in git history (commit b95120f and earlier).
