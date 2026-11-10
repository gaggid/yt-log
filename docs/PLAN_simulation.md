# Plan: Story Simulator (`sim/`)

Status: plan only, nothing built. Tasks and tick-boxes: [TASKS_simulation.md](TASKS_simulation.md). Written 9 Nov 2026 from the owner's brief and answers.

## 0. What the owner asked for, and the decisions taken

**The brief (owner's words, shortened).** A module that simulates imaginary or real-life situations with the text model. The owner gives a short idea; the AI proposes the characters to start with. Guidelines (rules) keep the whole simulation inside limits; the AI can write them, the owner can add and change them. The AI keeps adding chapters in timeline form on each run. The owner can add instructions at any time (outside factors, e.g. raiders arriving over time). It is storytelling with options to choose or add on each chapter, then simulate to the next chapter. Pictures are optional and turn a chapter into visuals of characters and places. Example only: a night-shift salesman in a supermarket when a zombie outbreak starts. It must be a **framework** that runs many different stories over time.

**Decisions (answered 9 Nov 2026).**

| # | Decision |
|---|---|
| D1 | Several characters. The story is an ensemble; every chapter has one or more *focus characters* and the owner can switch focus. |
| D2 | English only. |
| D3 | About 350 words per chapter (accepted range 280 to 430, code-checked). |
| D4 | Dice on by default (a switch turns them off per simulation). |
| D5 | Pictures: not from Character Studio. Cinematic painted style only, no photorealism. Drawn from text by the gateway image model, with the simulation's own reference paintings for face and place consistency. |
| D6 | For the owner's own reading now; publishing later by turning chapters into videos. So every chapter is stored in a form that a later video step can use (section 13). |
| D7 | Any genre. Nothing in the engine assumes survival, weapons, zombies or an inventory (section 4). |

## 1. Research summary (Nov 2026)

| Product / work | Does well | Falls short | Taken into this design |
|---|---|---|---|
| [AI Dungeon](https://dreamgen.com/blog/articles/ai-dungeon-alternatives) | Free-form actions; Plot Essentials, Author's Note, Story Cards, automatic summaries, Memory Bank | Shallow memory on long runs; the model agrees with the player | Layered memory (always-on essentials + summaries + cards fetched by match) |
| [NovelAI / SillyTavern](https://listicler.com/comparisons/sillytavern-vs-novelai-creative-fiction) | Lorebook entries that switch on by keyword | The user maintains them by hand | Fact cards, written and kept by the AI |
| [Hidden Door](https://gamesbeat.com/hidden-door-launches-social-role-playing-platform-with-ai/) | Restricted actions keep the story coherent | Less freedom | A few strong options and free text |
| [Friends & Fables](https://fables.gg/blog/best-ai-dungeon-alternatives) | AI game master voices every NPC; rules run in code | Heavy, rules-bound | Outcomes decided by code |
| [Neuro-symbolic world state (IVIE/PAYADOR), ChatRPG v3](https://themodelwire.com/article/world-state-transformations-for-neuro-symbolic-interactive-storytelling-01KSH6DKBED3X73TVA3ZVRFYET) | The model proposes state changes, code applies and checks them, a separate call writes prose; roles Examiner, Navigator, Narrator, Archivist; game-master models over-comply with the player | Engineering | The core architecture |
| [Generative Agents / Concordia](https://arxiv.org/abs/2312.03664) | Agents with memory, reflection, planning; a Game Master turns intentions into events | Many calls per step | "Cast minds" step (section 5.3) so each character wants something |

Finding: stories that hold over many chapters keep a **structured state outside the prose** and send the model a bounded packet each time. Chat-log products drift (forgotten items, dead people who speak, broken rules, an unbeatable hero).

## 2. Vocabulary

- **Simulation** (`sm-xxxxxxxx`): one story project.
- **Setup**: world card, cast, trackers, guidelines, settings. Editable before and during the run.
- **Tracker**: one thing the story keeps count of (section 4).
- **State**: the values of all trackers at a moment. Every chapter stores `state_before` and `state_after`.
- **Chapter**: one step of the timeline: prose, story-time stamp, rolls, state change, summary, options.
- **Branch**: a line of chapters. A chapter has one parent; two children of one parent are two branches. The *current branch* is the path from the root to the chosen head.
- **Option**: a suggested next action for a focus character, with a risk hint.
- **Directive**: an owner instruction injected into the story (event, constraint, twist, steer) with a timing.
- **Guideline**: a rule sentence with a group, an on/off switch, and an origin (AI or owner).
- **Fact card**: a short remembered fact the Archivist wrote (names, places, promises, injuries, secrets).
- **Open thread**: a promise the story made and has not paid off.
- **Roll**: a dice result decided by code for a risky action.

## 3. Data model (SQLite in the existing `story.db`, schema created lazily like `feedback/store.py`)

All ids are text. JSON columns are written with `db.jdump`/`db.jload`. Timestamps are `time.time()`.

```
sim_projects(id PK 'sm-…', title, idea, status 'setup'|'running'|'archived', settings JSON, head_id, created_at, updated_at)
  settings: difficulty 'gentle'|'fair'|'brutal', dice bool, chapter_words 350, auto_images bool, image_model, panel_shape 'wide'|'tall',
            captions bool, seed int, template_id, resolution 'dice'|'none'
sim_world(project_id PK, data JSON)             -- place, time period, tone, pacing, what exists (free text lists), starting scene, story clock start
sim_entities(id PK, project_id, kind 'character'|'place'|'group', name, data JSON, position INT, active INT, created_at)
  character data: role, goal, fear, secret, voice (how they speak), look (one paragraph, the painted-picture description), relations{name:text},
                  starting_condition, alive bool, status text
  place data: description, look, connects_to[names], locked bool
sim_trackers(id PK, project_id, kind 'items'|'meter'|'clock'|'relation'|'location'|'knowledge'|'flag', name, data JSON, position INT, active INT)
  data holds the definition (range, unit, owner, danger_when, links) and the STARTING value
sim_guidelines(id PK, project_id, grp 'hard'|'world'|'tone'|'style', text, enabled INT, origin 'ai'|'owner', position INT, created_at)
sim_directives(id PK, project_id, kind 'event'|'constraint'|'twist'|'steer', text, timing JSON, status 'pending'|'fired'|'cancelled', fired_in TEXT, created_at)
  timing: {"mode":"next"} | {"mode":"in","chapters":N,"from":chapter_idx_at_creation} | {"mode":"when","condition":"text","tracker":optional} | {"mode":"story_time","at":"day 2, dawn"}
sim_chapters(id PK, project_id, parent_id, idx INT, branch_label, status 'writing'|'done'|'failed', title, prose, story_time, summary,
             focus JSON, plan JSON, rolls JSON, delta JSON, state_before JSON, state_after JSON, options JSON, chosen JSON,
             flags JSON, fired JSON, panels JSON, created_at, updated_at)
sim_facts(id PK, project_id, chapter_id, text, tags JSON, entity_names JSON, created_at, retired INT)
sim_threads(id PK, project_id, text, opened_in, closed_in, status 'open'|'closed')
sim_runs(project_id PK, data JSON)                -- last run: stage, error, stage log; survives restarts (section 17, item 4)
sim_templates(id PK, name, data JSON, builtin INT, created_at)   -- the owner's saved templates; built-in ones live in sim/templates.py
```

Pictures use the existing `media` table with `plan_id` = the simulation id and kinds `sim_ref` (reference painting of a character or place, key = entity id) and `sim_panel` (key = `chapter_id:panel_no`). Files live under `data/media/<sm-id>/`. That makes numbered attempts, approval and the storage clean-up work without new code (section 17).

## 4. Genre-free state

**Rule: the engine knows tracker kinds, never story words.** Trackers are declared per simulation (the seed step proposes them, the owner edits them). Kinds and their value shapes:

| Kind | Definition | Value | Typical use |
|---|---|---|---|
| `items` | holder names, optional capacity | `{item: {qty, at: place-or-person, note}}` | stock, evidence, tools |
| `meter` | `min`, `max`, `unit`, `owner` (entity or `group`), `danger_below`/`danger_above` | number | health, morale, cash, reputation, fuel |
| `clock` | `max` segments, `rises` (what advances it), `ends` (what happens at full) | integer 0..max | horde nears, audit day, storm, deadline |
| `relation` | pair of entities | `{trust, tension}` each -5..5 | alliances, rivalries |
| `location` | entities and places | `{entity: place}` plus `locked: [places]` | who is where |
| `knowledge` | secret name | list of entities that know it | mystery, intrigue |
| `flag` | name | bool | power on, door barricaded |

State JSON shape (`state_before`/`state_after`): `{"time": "Day 1, 23:40", "trackers": {"<tracker id>": value, …}, "entities": {"<entity id>": {"alive": true, "status": "…"}}}`.

**Delta** (what the model proposes): a list of operations, each `{op, target, …, why}`:
`item_add|item_remove|item_move|meter_set|meter_change|clock_advance|clock_set|relation_change|move|lock|unlock|learn|flag_set|entity_status|entity_dies|tracker_add|time_advance`.

**Validation in `sim/state.py` (code, not the model)**:
- every `target` must exist (tracker id, entity, place, item holder); unknown targets are dropped and reported in `flags`;
- `item_remove`/`item_move` need the item at that holder with enough quantity; `item_add` is allowed only when a reason names an existing source (a place that holds it, a crafted item whose parts were removed in the same delta, or a directive that fired); otherwise dropped;
- meters clamp to `min..max`; a meter change larger than `max/2` in one chapter is clamped and flagged;
- a dead entity cannot be the actor of a later op, cannot `move`, and cannot `learn`; `entity_dies` needs a reason and, when `dice` is on, a failed roll or a fired directive that allows it;
- clocks only move forward except by an explicit `clock_set` with a reason; a full clock records `ends` as a due event for the next plan;
- `time_advance` is positive and at most the pacing limit in the world card;
- every applied op is written to `chapter.delta.applied`, every dropped op to `chapter.flags` so the owner sees what the model tried that the rules refused.

## 5. The chapter engine (`sim/engine.py`)

One chapter is a fixed list of stages. Each stage is one call (or code) and writes its result to the chapter row as it finishes, so a restart loses at most the stage in flight (like `story2/planner`). The job reports `progress(done, total, label)` per stage. Model calls use `story.llm.JsonCaller` with a Pydantic schema, the usual retries, and a task tag `[TASK:sm_*]` at the start of the system prompt (the app's convention; sampling table entries are in section 16).

Inputs to a run: project id, parent chapter (head), `action` = `{kind:'option'|'text'|'auto', option_id?, text?, who?}`. Stage list:

### 5.1 Gather (code)
Builds the **packet** (section 9), selects due directives (section 8), reads the active guidelines and the pressure state (full clocks, meters in danger, open threads).

### 5.2 Plan (`sm_plan`, model)
Output schema `ChapterPlan`: `focus` (1 to 3 entity names), `scene` (where, what is happening in two sentences), `intent` (what the focus characters try, from the owner's action or from their goals), `pressure` (which clock/meter/directive the chapter leans on; must name at least one due thing when any exists), `risks` (0 to 3 risky acts, each `{who, act, stat_tracker_ids[], difficulty 'easy'|'normal'|'hard'}`), `beat` (one of `escalate|setback|discovery|respite|choice|reversal|reveal`), `time_passes` (e.g. "40 minutes").
Code checks: focus names exist and are alive; `beat` differs from the previous two chapters' beats unless the plan states why (variety rule); every due directive is addressed or a reason to wait is given (a `when` directive may wait; a `next` directive may not); an owner `text` action must be reflected in `intent` (word overlap check, one retry).

### 5.3 Cast minds (removed 10 Nov 2026: the authored story plan decides what the others do; this step was off by default and never used)
For each non-focus character on the same scene: one line of what they want to do now. Folded into the plan context for 5.4. (Generative-Agents style; off by default for speed, built and tested as a switch, not left out.)

### 5.4 Resolve (code, `sim/dice.py`)
For each risk in the plan: roll. `roll = d20 + modifier`, target by difficulty (easy 8, normal 12, hard 16, shifted by simulation difficulty: gentle -2, fair 0, brutal +2). `modifier` = sum of up to three contributions the plan linked through `stat_tracker_ids`: a meter contributes `(value - mid) / (range/10)` rounded, items present that the plan names contribute +1 each (max +3), relation trust contributes -1..+1, `danger_*` states contribute -2. Result tiers: nat 20 or margin >= 5 `great`, margin 0..4 `success`, margin -1..-5 `partial`, worse `fail`, nat 1 `disaster`. Seeded: `random.Random(f"{seed}:{chapter_idx}:{risk_no}")` so a redo of the same chapter with the same action gives the same rolls; "Reroll" in the UI changes the salt. With dice off, every risk resolves to `success` and the chapter stores `rolls=[]`.

### 5.5 Delta (`sm_delta`, model)
Gets plan + rolls + current state; returns the operation list of section 4 whose consequences must match the rolls (the prompt states "the outcome is fixed: partial means ..."). Code validates and applies (section 4). Result `state_after`.

### 5.6 Write (`sm_write`, model)
Gets plan, rolls, applied delta, state_after, style guidelines, the previous chapter's last paragraph, relevant fact cards. Returns `title`, `prose` (about 350 words), `story_time`. Code checks: word count 280 to 430 (one retry with the count stated, then accepted and flagged); no more than two focus-character POV switches; names used exist; the outcome tier of each risk is reflected (checked by the referee).

### 5.7 Referee (`sm_referee`, model, then code)
Input: prose, active guidelines (hard, world, tone, style), state_after, applied delta. Output: `violations` list `{guideline_id|'continuity', quote, fix}` and `ok`. Code: when a **hard** rule or continuity violation exists, run Write once more with the violations listed; a second failure keeps the chapter, sets `flags.rule_break` with the quotes, and the UI shows a red banner with *Accept*, *Rewrite with instruction*, *Edit by hand*. Soft rules (tone/style) are advisory (amber).

### 5.8 Archive (`sm_archive`, model)
Returns `summary` (2 to 3 sentences, at most 60 words), `facts` (0 to 6 new fact cards with entity names), `threads_opened` / `threads_closed`, and `options` (3 or 4 next actions: each `{id, who, label, hint, risk 'low'|'medium'|'high'}`; at least one per focus character; at most one `risk high`; no two options that do the same thing, checked by word overlap). Code stores everything, updates `sim_facts` and `sim_threads`, marks fired directives as `fired` with this chapter's id, and sets the project head.

### 5.9 Pictures (optional, section 12)
Only when `auto_images` is on; otherwise the owner presses *Paint this chapter*.

**Failure handling.** A stage that fails after retries stops the run with `sim_runs.data = {stage, error}`; the chapter row is `failed` with the stages already stored; *Retry from this stage* continues from the stored stage outputs. A chapter that never finished is never made the head, so an interrupted run cannot corrupt the timeline.

## 6. Owner actions on the timeline (all in scope)

- **Continue** with: a chosen option; the owner's own text (with a focus character picker); *Let it run* (code picks the option via `sm_pick`, one small call, based on the focus character's goal and the risk setting); *Auto-run N chapters* (1 to 10): repeats Let-it-run and stops early on: a `rule_break` flag, a main character death, a clock full, a directive that needs the owner (kind `steer`), a failed stage, or the owner pressing Stop.
- **Rewrite chapter**: with an instruction; re-runs Plan→Archive for the same parent and action, with the instruction added to the plan prompt. The old version is kept as a sibling branch labelled "earlier version" and can be restored.
- **Regenerate**: same but the dice salt changes ("reroll").
- **Edit by hand**: owner edits prose or summary. If prose changed, `sm_reread` (one model call) reads the edit and proposes a delta correction; the owner sees it before it applies. Editing a non-head chapter marks later chapters `stale` (shown amber); the owner can branch from the edited chapter (their choice, not automatic).
- **Branch**: from any chapter, with any action. Never deletes the original line.
- **Rewind view**: the timeline shows the current branch; a branch picker shows siblings. "Make this line current" changes the head only.
- **Delete chapter**: only a leaf; removes its panels' media and files.

## 7. Guidelines and the referee

- Groups: `hard` (never break), `world` (how things work here), `tone` (mood, pacing), `style` (voice; chapter length is a setting, not a rule).
- AI proposes a set at seed time and on demand (*Suggest more rules*, one call that sees the idea, the world card and the current rules and must not repeat them). Owner can add, edit, reorder, switch off, delete. Origin is shown.
- Only enabled rules go into prompts. Hard and world rules go into Plan, Delta and Write and are checked by the Referee; tone and style go into Write.
- Rules are plain sentences. The example rules ("use only what the supermarket holds", "secure the perimeter", "think how stock becomes weapons") work through three mechanisms: the world card lists what exists, `item_add` is rejected without a source, and the referee checks the prose.
- The rule list has a **version counter**; every chapter records the version it was written under; a rule change shows "rules changed since chapter N" on the page.

## 8. Directives (outside factors, any time)

- Created from a box on the story page: text, kind, timing (*next chapter* / *in N chapters* / *when* a condition / *at story time*). A condition can be free text ("when the power fails") or tied to a tracker (`when clock X is full`, `when meter Y below N`); free-text conditions are judged by `sm_condition` (one cheap yes/no call over the state and last summary) at Gather.
- A directive is `pending` until fired. Firing is decided in Gather (timing met), the Plan must address it, the Archive marks it `fired` with the chapter id. It never fires twice; a branch has its own firing history because firing is stored on the chapter (`fired`), and "pending" is computed per branch as: created directives minus those fired on the path to the head. This is what stops directives leaking between branches.
- The owner can edit or cancel a pending directive; a fired one is read-only history and shown on the chapter card.
- `steer` directives bias the Plan toward a destination ("move toward rescue by chapter 8") without forcing it; the Plan must show progress or a reason.
- Reasoning on injection safety: directive text and idea text are the owner's own content, but they are fenced in prompts as data (`<owner_instruction>…</owner_instruction>`) so quoted text inside a chapter cannot act as a system instruction.

## 9. Memory packet (`sim/memory.py`) — the only way prompts are built

Contents, in order, each with a budget share: world card essentials (fixed); active guidelines (fixed); state_after of the head (compact JSON, fixed); entities that appear in the plan (card each); the head's last paragraph (fixed); `story so far` (rolling summary: every 8 chapters an `sm_rollup` call merges the oldest 8 chapter summaries into the paragraph; summaries of the latest 8 chapters are kept verbatim); fact cards matched by entity names and tags in the current scene (top 8 by match count then recency, retired ones skipped); open threads (all, capped at 8, oldest first); due directives. The existing `Budget` refuses an over-budget packet, so the packet builder **drops lowest-priority parts first** (matched facts, then older summaries, then entity cards beyond the focus) and records what it dropped in `chapter.flags.packet_trimmed`; it never truncates inside a part.

## 10. Seed: from idea to a playable setup (`sim/seed.py`)

Each part is its own call so any can be redone alone, and every result lands in editable forms:
1. `sm_world`: idea (+ optional template) → world card, tone, pacing, starting scene, story clock.
2. `sm_cast`: idea + world → 4 to 10 entities (characters with role/goal/fear/secret/voice/look/relations; key places; groups). Names unique; `look` is one painted-picture paragraph (age, build, face, hair, clothes, one distinguishing mark; no brand words).
3. `sm_trackers`: idea + world + cast → the trackers this story needs (3 to 10), each with a starting value taken from the world card (for example, the stock list the owner or model wrote).
4. `sm_rules`: idea + world → 6 to 14 guidelines in the four groups.
5. `sm_open`: setup → opening chapter 1 prose is produced by the normal engine (a first run with no parent and no action), so chapter 1 is not special code.
Code checks: unique names, every tracker references existing entities/places, starting state is valid under section 4, at least one hard rule and one clock or meter in danger range exist (otherwise the model is asked once to add pressure).
Owner can edit all, add or remove entities/trackers/rules, redo any part with an instruction, then press **Start**. Setup stays editable afterward; edits that change the world apply to future chapters and are listed on the page ("changed since chapter N").

**Templates** (`sim/templates.py`, data only): survival, mystery, courtroom or politics, business, heist, historical what-if, relationship drama, free. Each carries tracker suggestions, rule groups, pacing, difficulty and prompts hints; seed uses it when chosen. *Save as template* stores the owner's own (table `sim_templates`, section 3). **Portable**: *Export setup* downloads one JSON (world, cast, trackers, rules, settings, no chapters); *Export full* includes chapters; *Import* creates a new simulation (new ids, media not included); *Duplicate* copies the setup (or everything) in the database.

## 11. Resolution styles
`dice` (default) as in 5.4; `none` = story mode: the Plan owns outcomes, every risk is `success`, difficulty ignored. The state, rules and referee work the same in both.

## 12. Pictures (cinematic painted, optional)

- **Style**: one locked style string `STYLE = "cinematic digital painting, dramatic lighting, painterly brushwork, rich colour grading, film-still composition, concept-art quality"`; the key-out line forbids photographs, photorealism, text, letters, logos, watermarks, collage ("An original painted illustration, not a photograph. No text, no letters, no logo, no watermark"). The style and keep-out text are constants in `sim/paint.py` with a test that every request contains them and none contains "photo" except in the keep-out.
- **Reference paintings**: for each character and place that appears in a chapter being painted and has none yet, a `sim_ref` is drawn from its `look` paragraph (portrait or establishing view). The owner can redraw or edit the look text; changing `look` marks the reference and panels that used it *old* (hash of look text + style + model, like the other media hashes).
- **Panels**: `sm_panels` (model) turns the chapter into 3 to 5 panels: `{shot (wide|medium|close|detail|over-shoulder), who[] (≤2), place, action (one sentence), light/mood, caption (≤12 words, English), beat_ref}`; code enforces: names exist, ≤2 people per panel, each panel's action is positive wording (no "not/without/no"), caption length. Panels are in order of the chapter.
- **Drawing**: request builder `sim/paint.py` only. With references: `/images/edits` with up to 3 pictures (the speaking/acting characters' reference paintings, then the place's), prompt names the pictures by position and says what happens (same pattern as `shorts/stills.edit_prompt`). With none, or when the model has no edit endpoint, or the edit fails twice: `/images/generations` from the full text (look paragraphs included). Image model from `settings.image_model` (default `qwen-image-2.1`); size 1280x720 (`wide`, default) or 720x1280 (`tall`); seed = `project seed + chapter idx*31 + panel_no`. Output saved as `sim_panel` media rows with the recipe in `meta` (prompt, refs, model, seed, hashes).
- **Caption strip** (setting `captions`, default on): lettered by code (PIL) on a copy `…-cap.png` at the bottom; the model never draws text.
- **Gallery per chapter** shown on the timeline card; each panel can be redrawn, edited (prompt box), swapped for an upload, or deleted. A chapter edit marks its panels *old* (hash of the panel plan).
- **Jobs**: *Paint this chapter* queues references then panels as one background job; images wait behind text jobs (one-job lock). `auto_images` paints after each chapter when on (default off).

## 13. Reading and publishing later (D6)

Nothing is rendered to video in this build (the owner will convert later), but the data must be ready, so these are in scope:
- **Reader view**: the whole branch as a book page (title, chapters with panels and captions in order), print-friendly CSS, reading time.
- **Export** (`GET /api/sim/{id}/export?format=md|json|zip`): Markdown (chapters, captions), JSON (the full branch with state summaries), and zip (Markdown + `images/` panels in order + `chapters.json`). Chapter JSON includes per chapter: `title, story_time, prose, summary, panels[{file, caption, shot, who, place}]`, which is exactly what a later "chapter to short" step needs (narration = prose, shots = panels, cast = look texts).
- The later video step is out of this plan by the owner's choice; the storage layout and JSON above are its contract.

## 14. API (`sim/api.py`, router `/api/sim`, mounted in `main.py` after the feedback router)

```
GET    /api/sim                         list simulations (title, status, chapters, last activity, bytes of media)
POST   /api/sim                         create from {idea, template_id?}  (no model call; status setup)
GET    /api/sim/{id}                    everything for the page: setup, head, current branch chapters, pending directives, run state
PATCH  /api/sim/{id}                    title, idea, settings
DELETE /api/sim/{id}                    full delete (section 17)
POST   /api/sim/{id}/seed/{part}        world|cast|trackers|rules  (job)  body: {instruction?}
POST   /api/sim/{id}/start              validates setup, runs chapter 1 (job)
CRUD   /api/sim/{id}/entities, /trackers, /guidelines, /directives     (+ POST …/guidelines/suggest as a job)
POST   /api/sim/{id}/chapters           {parent_id?, action} -> run one chapter (job)
POST   /api/sim/{id}/auto               {n, stop_on?} (job)
POST   /api/sim/{id}/chapters/{cid}/rewrite | /reroll | /accept | /retry
PATCH  /api/sim/{id}/chapters/{cid}     hand edit (prose/summary/title); returns the proposed re-read delta
POST   /api/sim/{id}/chapters/{cid}/reread/apply
POST   /api/sim/{id}/head               {chapter_id}  make a line current
DELETE /api/sim/{id}/chapters/{cid}     leaf only
POST   /api/sim/{id}/chapters/{cid}/paint  {panels?: [n]}  (job)
POST   /api/sim/{id}/panels/{mid}/redraw | PATCH (prompt) | upload | DELETE
GET    /api/sim/{id}/run                progress of the current job (the screen polls; also survives reload)
POST   /api/sim/{id}/stop               cooperative stop at the next stage boundary
GET    /api/sim/{id}/export?format=md|json|zip
POST   /api/sim/import | POST /api/sim/{id}/duplicate | POST /api/sim/{id}/save-template | GET /api/sim/templates
```

Jobs use `story2/jobs.start(project_id, kind, work)`-style locking through one helper `sim/jobs.py` (wraps `story2.jobs` so the single-request gateway rule holds and a second job is refused with 409). Errors follow the app's `HTTPException` messages.

## 15. UI (`static/sim.js`, page `#/sim`, nav link "Stories" in `static/index.html`; `main.py` serves the script no-store with the `?v=` stamp like the others)

1. **Library** (`#/sim`): cards for every simulation (title, idea line, chapters, status, last read, media size), *New story* (idea box + template picker), Import.
2. **Setup** (`#/sim/<id>`, tab Setup): idea; world card; Cast list (cards with look text, edit/redo/add/remove); Trackers (add/edit by kind with a form per kind); Rules by group with switches and *Suggest more*; Settings (difficulty, dice, words, images, captions, panel shape, deep minds); **Start** button with a validation list ("what is missing") instead of silent failure.
3. **Story** (tab Story, default once started): vertical timeline of chapter cards (number, title, story time, prose, summary toggle, roll chips "Barricade the bay: 14+2 vs 12 → success", flags banners, directive chips "Raiders arrive – fired here", panels strip, *Paint*), branch picker, stale markers. Bottom dock: option buttons (each shows who, hint, risk), text box + focus picker, *Let it run*, *Auto-run N*, *Stop*, and the **Add instruction** drawer (kind, text, timing). Right panel: **State** (trackers grouped by kind with bars for meters, segment dots for clocks, inventory table, who is where, relations grid, knowledge), pending directives, open threads, rules with violation counts.
4. **Read** (tab Read): the reader view and Export buttons.
5. Running state: a banner with stage label and elapsed time; on mount the page checks `/api/sim/{id}/run` and resumes watching (the lesson from the Learn tab fix); leaving the page loses nothing.
6. A collapsible *How this page works* help, kept in sync like `learn.js` (CLAUDE.md rule for tabs).

## 16. Settings, sampling, and files

- New sampling entries in `story/settings.SAMPLING`: `sm_world`/`sm_cast`/`sm_trackers`/`sm_rules` temperature 0.8; `sm_plan` 0.8; `sm_minds` 0.9; `sm_delta` 0.3 (structured); `sm_write` 0.85 with `top_p` 0.95 and `frequency_penalty` 0.3; `sm_referee` 0.2; `sm_archive` 0.4; `sm_pick` 0.7; `sm_condition` 0.1; `sm_rollup` 0.3; `sm_reread` 0.2; `sm_panels` 0.6.
- Files: `sim/__init__.py, models.py, store.py, seed.py, templates.py, portable.py, memory.py, state.py, dice.py, engine.py, referee.py, panels.py, paint.py, jobs.py, export.py, api.py`; `static/sim.js`; `tests/test_sim.py` with `tests/sim_fakes.py`; `docs/PLAN_simulation.md`, `docs/TASKS_simulation.md`; a CLAUDE.md section.
- No content limits in the story prompts (the owner reviews, as in `shorts`); nothing is published automatically; images are painted style by constant.

## 17. Leakage controls and clean-up (the "no leakages" requirements)

1. **Delete is complete.** `DELETE /api/sim/{id}` removes, in one transaction, rows in every `sim_*` table for that project plus its `media` rows, then the folder `data/media/<id>/`. A test counts rows in every sim table (and `media`) after delete and requires zero. (This is the gap found in `characters/store.delete`, which leaves orphan life/memory rows; sim does not repeat it.)
2. **Storage page**: `admin/storage.py` learns the prefix `sm-` (`kind_of` → "story", titles from `sim_projects`); "older attempts" clean-up works; panels and references are regenerable so they are not marked irreplaceable, but hand uploads are (`upload/` folder marked irreplaceable like shorts' uploads). After a clear, `_prune_after` removes panel references to missing files from `sim_chapters.panels` and `sim_entities` ref ids.
3. **Branch isolation**: state, facts, threads and directive firing are computed per path. `sim_facts` and `sim_threads` rows carry the chapter that created them; a read for the current branch includes only rows whose chapter is on the path to the head. A test builds two branches from one chapter and shows a fact, an item and a fired directive on one are invisible on the other.
4. **Job leaks**: one job at a time; the finished/failed run is recorded in `sim_runs`; on startup, a `sim_chapters` row left `writing` is marked `failed` (no ghost running state); stop requests are cleared when a job ends.
5. **No prompt leaks between simulations**: the packet builder takes a project id and path; a test with two projects checks no name of project B appears in A's prompt.
6. **Owner text is fenced as data** in every prompt (section 8).
7. **Orphans**: deleting an entity removes its references from trackers/relations after confirming; deleting a tracker keeps old states (history is immutable) but removes it from the next chapter's state; deleting a rule is a soft retire (history keeps the text).
8. **Immutable history**: `state_before/state_after`, `plan`, `rolls` and `delta` of a done chapter are never rewritten, except by Rewrite/Reroll, which create a sibling.
9. **Restart safety**: every stage output is stored as it finishes; the server can be restarted between stages (watch.py waits for running jobs as everywhere).
10. **No unfinished features**: section 20 maps every sentence of the brief to a feature, a stage and a test, and section 21 is the done checklist.

## 18. Tests (`tests/test_sim.py`, fake chat in `tests/sim_fakes.py` routing on `[TASK:sm_*]`)

Unit: tracker kinds and validation (each rejected-op case in section 4); dice determinism, difficulty shifts, modifier math, dice-off; directive timing (next, in N, when, story_time) and fire-once; per-branch pending; packet builder trims lowest priority and never truncates; word-count check and retry; referee rewrite once then flag; option dedup and count; Let-it-run pick; Auto-run stop conditions; rewrite keeps the old as a sibling; hand edit re-read flow; branch isolation; delete cleanliness; export formats; import/duplicate; templates produce valid setups; panel planner constraints; paint request always has style + keep-out and no word "photo" outside keep-out; reference reuse; old-hash marking; caption lettering; API tests for every endpoint including 409 when a job runs; startup repair of `writing` chapters; storage page sees `sm-` projects. **Genre test**: the same engine runs a non-survival fixture (courtroom) through setup, 3 chapters, directives and export with zero code branches on genre.
Live (optional, `LIVE_LLM=1`): two stories, 5 chapters each (stage S0).

## 19. Build order (each stage ships working and tested; nothing left half-wired)

| Stage | Content | Exit test |
|---|---|---|
| S0 Spike | Script `sim/spike.py` runs the supermarket and a courtroom story for 5 chapters on the real gateway; records seconds per stage, validation drop rates, word counts, referee catch rate. Output decides final stage splits and prompt tuning, written to docs/RUN_LOG.md. | Both stories finish; drop rate and times recorded |
| S1 Core | store, models, state (validation), memory packet, engine stages 5.1 to 5.8, seed parts 1 to 5, API for setup/chapters/run, Library+Setup+Story pages without extras | Genre test and unit tests pass; a story runs 5 chapters from the UI |
| S2 Steering | directives (all timings), Let it run, Auto-run, Stop, rewrite, reroll, hand edit + re-read, branches, delete leaf, stale marks, rule suggest | Steering tests pass; two branches isolated |
| S3 Fun & framework | dice and difficulty (UI roll chips), cast minds switch, templates + save template, export/import/duplicate setup, rollups, state panel complete, open threads, reader view and export formats | Dice/portable/rollup tests; export zip opens |
| S4 Pictures | `paint.py`, panel planner, reference paintings, drawing via edits/generations, caption strip, gallery, redraw/edit/upload, old-hash, auto-images switch, storage page support | Paint tests with the mock gateway; one real chapter painted in the live app |
| S5 Docs & hardening | CLAUDE.md section, help text on the page, RUN_LOG entry, full-suite run, restart/idle checks, leakage checklist run | Section 21 all ticked |

## 20. Traceability: the owner's brief, sentence by sentence

| # | Brief | Delivered by | Stage | Proved by |
|---|---|---|---|---|
| T1 | New module for simulating imaginary or real situations with the AI text model | `sim/` package, nav "Stories", all model steps via `JsonCaller` | S1 | API + genre test |
| T2 | Give an initial idea, short summarised form | `POST /api/sim` idea field; New story box | S1 | api test |
| T3 | AI generates the characters to start with | `sm_cast` seed part, editable cast cards, redo with instruction | S1 | seed test |
| T4 | Guidelines the simulation must stay under | Guidelines table, groups, enabled switch, referee (5.7), prompts (7) | S1 | referee test |
| T5 | Guidelines generated by AI | `sm_rules` seed + *Suggest more* | S1/S2 | seed + suggest tests |
| T6 | Guidelines added and modified by the user, any time | CRUD on rules, rule version counter, "changed since" note | S1 | api test |
| T7 | Example rules: use stuff in the place, secure the perimeter, make weapons from materials, survival plan | World card stock + `item_add` source rule (4) + hard rules + referee | S1 | state test (item with no source rejected), genre fixtures |
| T8 | The AI thinks and keeps adding chapters in timeline format on each run | Engine 5.x, chapter rows, Story timeline | S1 | engine test |
| T9 | Each run produces a new chapter that follows from the last | parent chain, packet with last paragraph/summaries/state | S1 | continuity test |
| T10 | User can add instructions about external factors (zombies, raiders over time) | Directives: event/constraint/twist/steer with timing | S2 | directive tests |
| T11 | Instructions can be added at any point of time | Add instruction drawer always available; applies to the head's next chapter | S2 | directive test |
| T12 | Storytelling with options to choose on each chapter | `options` from Archive, option buttons | S1 | engine test |
| T13 | ...or add on each chapter (own input) | text action + focus picker | S1 | engine test |
| T14 | Then simulate to get the new chapter | Continue / job / progress | S1 | api + job test |
| T15 | Images optional per chapter | Paint button, `auto_images` off by default | S4 | paint tests |
| T16 | Turn a chapter into visualisation including character and place | panel planner, reference paintings of characters and places, edits with refs | S4 | paint tests |
| T17 | (answers) several characters | ensemble focus, per-chapter focus picker, options per focus character | S1 | engine test with 3 focus names |
| T18 | (answers) English, 350 words | language fixed in prompts, word check 280 to 430 | S1 | word-count test |
| T19 | (answers) dice | `dice.py`, difficulty, roll chips, seeded rerolls | S3 | dice tests |
| T20 | (answers) cinematic painted, no realism, not from characters | `paint.py` constants, no Character Studio imports (test greps imports) | S4 | style test |
| T21 | (answers) read myself, publish later as videos | reader view, export md/json/zip with panel order and captions | S3 | export tests |
| T22 | "Zombie story was an example", a framework for many stories over time | tracker kinds, templates, import/export/duplicate, library, genre test | S1 to S3 | genre fixture runs a courtroom story |
| T23 | Research how such apps work, plan | section 1 | done | this document |

## 21. Definition of done: no partial build, no leaks

All must be true before the work is called finished:
- [ ] Every row of section 20 has working code, an automated test and (for UI items) a manual run in the live app recorded in docs/RUN_LOG.md.
- [ ] No endpoint in section 14 is missing; no button on the pages calls a missing endpoint (a test lists the routes the script calls and checks each exists).
- [ ] Every table in section 3 has a writer, a reader and a delete path; delete leaves zero rows and no folder.
- [ ] Every setting in section 3 and 16 has a UI control and an effect proven by a test.
- [ ] Branch isolation, directive fire-once and prompt isolation tests pass.
- [ ] Restart test: stop the server mid-chapter, restart, the chapter shows failed with *Retry from this stage*.
- [ ] Dice off, deep minds on, captions off, tall panels are each exercised in a test.
- [ ] The paint module imports nothing from `characters/`.
- [ ] The Stories help text, CLAUDE.md section, TASKS file and storage page are updated.
- [ ] `pytest tests/test_sim.py` and the neighbouring suites (`test_shorts`, `test_characters`, `test_storage`, `test_feedback`) pass; any pre-existing failure is listed by name and checked against the previous run.
- [ ] Section 22 risks reviewed after S0 and the plan edited for anything learned.

## 22. Risks

- **Model quality on state deltas** (Gemma may invent items or forget deaths): validation in code, retries, dropped ops reported; S0 measures the drop rate and may change the prompts or split Delta in two (items vs. everything else).
- **Chapter time**: 5 to 7 calls per chapter on a one-request gateway; progress shown, Auto-run stoppable; `deep` minds off by default.
- **Sameness across chapters**: beat variety rule, open threads, pressure rule, rollup summaries; S0 reviews a 5-chapter run for repetition.
- **Face consistency of painted characters**: reference paintings + edits; if the edit model drifts, fallback to text-only plus the seed; the owner can redraw. Honest limit: perfect identity across many panels is not guaranteed with a text-to-image model.
- **GPU load**: images are queued behind text, never concurrent, and only on request unless auto-images is switched on. Any GPU-heavy test needs headroom and the owner's go-ahead (stored feedback).
- **Scope**: S1 is the big stage. If S0 shows a stage can be merged (for example Plan+Resolve prompt), that is decided then and written here, never silently dropped.

## 23. Changes made while building (the plan above is kept as written; these are the differences)

- Story time is the free text the writer sets for each chapter (`story_time`), not an `time_advance` operation; the plan names how long the chapter takes (`time_passes`) and the writer turns it into the new time.
- `resolution` is the single switch `dice` (on by default). Story mode = dice off.
- An instruction's "fired" state is not stored on the instruction: it is read from the chapters of the current line (`fired` list on each chapter), which is what keeps branches separate. `status` on the instruction row only says `pending` or `cancelled`.
- "In N chapters" counts from the chapter the instruction was added after: N = 1 means the next chapter, N = 2 the one after it.
- The operation `tracker_add` was dropped: trackers are added by the owner in Setup, not invented by the model in the middle of a story.
- Items are stored as name -> {qty, at, note}; moving part of a stack is not supported (a move moves the whole entry).
- The real model sometimes writes an operation as `{"move": {...}}` instead of `{"op": "move", ...}`; both are read (`models._ops`). Found in the S0 run.
- Reference paintings for people use a 1024 x 1024 canvas; panels are 1280 x 720 (wide) or 720 x 1280 (tall).
- Uploaded pictures are saved under `upload/` and the storage page treats that folder as irreplaceable; painted ones are under `panels/` and `refs/`.
- The reader view is the Read tab; a separate print stylesheet was not added (the browser's print of the Read tab is the print view).
- What the real model run (S0) taught: the model writes operations in several JSON shapes and often leaves the tracker name empty or loose, so shapes and names are matched tolerantly (never guessed when a name was given that matches nothing); the plan keeps all stages (none could be merged: each of plan, delta, write, referee and archive takes 30 to 50 seconds on the local model, a chapter 3.5 to 5 minutes); the referee stays but its first reasons are now stored (`flags.first_violations`); the writer prompt forbids repeated openings. The stage list, tracker kinds and dice rules did not need to change.

- Things, finds, makes, recipes and skills were added after the first build: see [PLAN_discoveries.md](PLAN_discoveries.md) (section 18 lists what changed while building). The world card also has `craft` and `goal` lines now, and the dice no longer give a free bonus for a meter in good shape.
