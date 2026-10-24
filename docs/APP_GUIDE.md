# Source-to-Story: application guide

Written 2026-10-24, after Phase 1, Phase 2 and Phase 3 batches E and F. This is the one document to read to understand the app, run it, and continue building it. The next phases are in [ROADMAP.md](ROADMAP.md).

## 1. What the app is for

It turns a **book (PDF) or an article (URL, pasted text, TXT or HTML)** into a **16:9 long-form YouTube video**, in three stages, each with a human checkpoint:

1. **Story** (Phase 1). Find evidence-linked story candidates in the source; review and approve one.
2. **Video plan** (Phase 2). From the approved story: narration, storyboard, model-aware image prompts, editorial scores, approval and a versioned JSON export.
3. **Media** (Phase 3). From the exported plan: voice, reference pictures, scene pictures, built graphics, and the assembled draft video (ffmpeg).

Everything runs on this machine. The language models, image models and voice model sit behind one local OpenAI-compatible gateway; the app never calls the internet for generation.

### Owner rules (must keep)

- **Nothing carried forward from the source:** no author or book mentions, no quotes, no pointers back. A leak gate checks everything that is spoken, shown or sent to a model.
- **Narrator is first person**; the narrator's name is set later (`Narrator name` on the plan page; unset today).
- **16:9 long-form first.** Vertical 9:16 comes later as its own plan.
- **Voice is Svara `hi_male` only.** Narration is **Hinglish in mixed script** (Devanagari for Hindi, Latin letters for English words, numbers written as words).
- **Licences are not a blocker.** The image models are used as open-source models; every model starts "confirmed" (owner decision, 2026-10-24).
- The user is never left lost: every screen shows what has been done and **what to do next**.

## 2. Run it

```
pip install -r requirements.txt        # the app runs from .venv; use .venv\Scripts\python.exe -m pip ...
copy .env.example .env                 # TRIPFICK_API_KEY, APP_PASSWORD (generated into .env if missing)
python main.py                         # http://127.0.0.1:8905  (login: APP_USER / APP_PASSWORD)
start.bat                              # runs watch.py: starts the app, pulls origin/master, restarts when no job is running, restarts on crash
```

- `static/plan.js` is served from disk with no cache: page-only changes take effect on reload, **no restart**. Python changes need a restart (the watcher restarts after a pull; or restart by hand). **Never restart while a generation job is running.**
- Settings (model server URL, chat model, context budget, retries) are in the app: **Settings**, then **Test connection**. Defaults in `config.py`: gateway `http://127.0.0.1:8810/v1`, chat model `gemma4-12b-qat-uncensored-hauhaucs-balanced`, port 8905.
- Data lives in `data/` (gitignored): `story.db` (SQLite), `sources/`, `plan_exports/<plan>/`, `plan_previews/<plan>/`, `media/<plan>/{voice,refs,...}`.
- Tests: `.venv\Scripts\python.exe -m pytest tests` (mocked models; **168 passed, 1 skipped**). Set `LIVE_LLM=1` for the optional real-model tests.

## 3. The machine and the model server

- **Gateway:** `D:\MiniMaxH3` (config `serve_models.yaml`, code `app/backend/`). OpenAI-compatible at `127.0.0.1:8810/v1`. **One concurrent request per key**; models that cannot share GPU memory take turns (a swap costs about 20 s). The app therefore runs **one job at a time** (`story2/jobs.py`) and refuses to start a second.
- **Models in use:**
  - Chat (all writing stages): `gemma4-12b-qat-uncensored-hauhaucs-balanced`. Also has vision (used to score pictures).
  - Voice: `svara-tts`, voice `hi_male`.
  - Images: `qwen-image-2.1` (default) and `flux2-klein-9b`.
- **Gateway settings we changed:** `svara-tts` `tts.timeout_s: 600` (the default 120 s killed every segment). Do not lower it.
- **Tools:** ffmpeg 7.1.1 at `C:\Ffmpeg\bin` (with ffprobe), Pillow 11, font Nirmala UI (Devanagari), jsonschema.
- **Tried and rejected:** the model entry `qwen3-8b-drama-thinking` (it actually loads `MSFIT-9B-v8`). Worse than Gemma at narration (wrong script, ignored facts), at the emotional arc (unstable) and it skips the creative-choices field. Same result for `qwen3.5-9b` on narration. Pipeline unchanged.

### Measured facts

| Thing | Measurement |
|---|---|
| Svara pace | about 148 words per minute spoken; generation about 3.7x slower than real time (a 7-minute video needs about 26 minutes of voice) |
| Svara request | one request per segment; `max_tokens` 2048 per internal chunk is about 25 s of audio; settings seed 7, temperature 0.6, repetition penalty 1.25; emotion per sentence, **one steady emotion per segment** (a mid-part switch changes pace and voice audibly) |
| Qwen Image 2.1 | 25 steps, cfg 1 (negative prompt ignored), about 52 s per 1024x1344 picture |
| FLUX.2 Klein 9B | 28 steps, cfg 4 (negative prompt honoured), about 125 s per picture including a model swap |
| Both image models | max 2,359,296 pixels, sizes multiple of 16, edits take at most 3 reference images and no masks, text inside pictures is unreliable, no prompt enhancer exposed; 16:9 output 1344x768 |

## 4. How it is built

```
main.py              app entry, login, resumes unfinished work, mounts the three routers
auth.py  config.py   login; environment and paths
watch.py  start.bat  auto-deploy supervisor

story/               PHASE 1: source to story candidates          router /api
  db.py settings.py ingest.py chunker.py tokens.py llm.py (ChatBackend, JsonCaller) pipeline.py
  scoring.py review.py export.py contract.py figures.py textfix.py eta.py guide.py api.py
story2/              PHASE 2: story to video plan                 router /api/plans
  intake.py          loads an approved story: public facts vs evidence
  planner.py         plans, blueprint, narration (Hinglish), validation
  svara.py           spoken-text rules, emotion tags, pause tags, duration estimate
  storyboard.py      asset registry, scenes, timing, retiming to real audio, repeat fixing
  providers.py       what each image model can do (capabilities, sizes, settings_for/model_for)
  imgprompts.py      Qwen and FLUX prompt compilers, validator, reference plan, overlay spec
  imgplan.py         compile and validate prompts, set models, optional single-image preview
  editorial.py       content hash, twelve scores, sign-off, approval, history
  export.py          versioned JSON export with public/evidence split and leak gate
  export_schema.py   JSON Schema 2020-12 (docs/plan_schema.json is generated from it)
  leak.py            source-leak and overlap checks
  jobs.py            one-at-a-time background jobs with progress and cancel
  api.py store.py scene_schemas.py schemas.py prompts.py
story3/              PHASE 3: plan to media                       router /api/media
  store.py           table `media` and file layout; one approved attempt per kind+key
  voice.py           Batch E: Svara per segment, real length, retiming
  refs.py            Batch F: reference pictures, approval, bulk approve
  refscore.py        Batch F: measure a picture and look at it (vision) -> score
  api.py
static/              index.html (all pages) and plan.js (the plan screen); no build step
tests/               pytest, fake models and fake gateways
docs/                this guide, ROADMAP.md, phase2_plan.md, phase3_plan.md, plan_schema.json, story_schema.md
legacy/              the old news-podcast generator (not served)
```

### Data model

- **Phase 1** (`story.db`): `projects`, `paras`, `chapters`, `tasks`, `candidates` (stories), `figures`, `candidate_refs`, `settings`, `runs`.
- **Phase 2:** `plans` (one per approved story: format, settings, narrator, blueprint, validation, status), `segments` (narration parts), `scenes` (canonical scene data plus compiled prompts), `assets` (the continuity registry: person, place, prop, style, narrator), `plan_revisions` (history).
- **Phase 3:** `media` (`id, plan_id, export_rev, kind voice|reference|scene_image|graphic|video, key, attempt, status, file, meta JSON, approved`). Every generated file is a numbered **attempt** that is never overwritten; approving one un-approves its siblings.

### Invariants worth knowing before you change anything

1. **The canonical scene is the source of truth.** Image prompts are derived from it and carry a `source_hash`; regenerating prompts never touches scene wording.
2. **The content hash** (`editorial.content_hash`) defines "what was approved". It deliberately **excludes** derived or after-approval data: timings and wpm (change when real audio arrives), previews, issues, scene `prompts` and `adapters`, and asset `reference_images`. So making voice or pictures never makes an approved plan look changed. Changing this definition needs a migration of stored approvals and a re-export (done twice already; see `docs` history).
3. **Media is made from a saved export** whose hash equals the current plan (`voice.load_export`). Reference pictures are the exception: they need only the storyboard.
4. **Export has two halves.** `public` (everything that may be spoken, shown or sent to a model) and `evidence` (the fact trail, never in a prompt). The leak gate scans `public`; an export with a finding is refused.
5. **No single combined editorial score.** Twelve dimensions, each with score, band, reason and fixes; sign-off has blockers and warnings. (Reference pictures do have one 0-100 ranking score, with its parts shown.)
6. **Charts, documents and screens are never drawn by an image model** (text and numbers are unreliable and a fake chart looks like evidence). They are built by code from verified facts (Batch H).
7. **Jobs are one at a time.** A job saves each item as it finishes; Stop loses only the item in flight; a failed item is recorded and the job continues; an unreachable model server stops the job with a clear reason.
8. **Voice validity** is tied to a hash of the annotated text plus the voice: if a part's wording changes, its old audio stops counting.
9. **Picture validity** is tied to a hash of the item's description, fixed details, period, style and model: change them and older pictures are marked old.

## 5. Using the plan screen (the path to a video)

The plan page has a **journey bar** (Story, Blueprint, Narration, Storyboard, Image prompts, Checked, Reviewed, Approved, Exported, Voice, References), a **"Next:" bar** with one button for the next step, a red/amber/green **banner**, and a **sticky side panel** of numbered steps. The page refreshes itself every 1.5 s while a job runs.

| Step | What happens | Model needed |
|---|---|---|
| 1 Plan the story | Blueprint: structure, viewer promise, central question, beats | chat |
| 2 Write the narration | Hinglish narration per beat, one emotion per part | chat |
| 3 Design the storyboard | Asset registry, then scenes per part | chat |
| 4 Write image prompts | Qwen and FLUX prompts for every scene (instant) | none |
| 5 Check everything | Validation of narration, scenes and prompts | none |
| 6 Fix camera repeats | Redraw scenes that repeat the previous camera | chat |
| 7 Review and score | Twelve scores with reasons; sign-off checklist | none |
| 8 Approve the plan | Sign off the exact reviewed version (tied to the content hash) | none |
| 9 Export | Versioned JSON file, schema-checked and leak-checked | none |
| 10 Make the voice | Svara, one request per part; scenes retimed to real audio; "Approve all voice" for one-click approval | voice |
| 11 Make reference pictures | 2 candidates per recurring item, scored; "Approve the best" or approve one by one; Skip for items a description is enough for | image + chat (vision) |
| 12 Go to the first problem | Jumps to the first thing that needs attention | none |

Approval of voice and pictures is optional for the draft (the latest valid take counts), but approved items are never regenerated by "all" actions.

### API (all under the same login)

- `/api/...` Phase 1: settings, projects (upload, url, text), scope, process, pause, cancel, stories (review, merge, split), export.
- `/api/plans/...` Phase 2: plans CRUD, `job`, `cancel`, `narrator`, `settings`, `blueprint`, `narration`, `registry`, `storyboard`, `fix-repeats`, segments and scenes (patch, move, regenerate), assets patch, `review`, `approve`, `unapprove`, `history`, `export`, `exports/{plan}/{file}`, `image-models`, `compile-prompts`, scene `prompts` and `preview`, `validate`, `providers`, `providers/probe`, `schema`.
- `/api/media/...` Phase 3: `GET /{plan}` (voice and references state), `POST /{plan}/voice`, `POST /{plan}/references`, `.../references/score`, `.../references/approve-best`, `.../references/skip`, `PATCH /item/{id}` (approve), `GET /file/{plan}/{path}`.

## 6. Where things stand

- **Real plan:** `pl-840b02a0`, 6-minute 16:9 plan from the Knight Capital story: 8 segments, 50 scenes, 6 assets (style, narrator, the stock chart, the trader, the cup-and-handle pattern, the earnings release). Prompts compile with no errors; **approved**; export **v003** is current (carries real audio lengths). **Voice made and approved** for all 8 parts (Svara, about 26 minutes). **References:** pictures not yet made on the real plan (four recurring items). Three empty draft plans from earlier tests (`pl-80117505`, `pl-a1b51833`, `pl-c056df3f`) can be deleted from the plan list.
- **The real plan's narration is still the older Devanagari-only text** and its emotional-coherence score is 4 (emotion switches inside parts). Fix: **Rewrite all narration** in the new Hinglish style, then redo storyboard, prompts, review, approval, export and voice. The user has not decided yet; it is the single biggest quality lever.
- **Facts are marked "unverified"** (the user's own task); the narrator name is unset.
- **Of 50 scenes, 20 are chart or document plates** that need Batch H graphics; they are not drawn by an image model.

## 7. Known gaps and risks

- No image or voice quality judged on a whole real run yet (only hand-tested samples and one reference picture on each model). Batch G starts with a three-scene trial for that reason.
- The asset `fixed` lists are sometimes only attribute names ("clothing color"), which gives weak consistency. Rewrite them in Continuity as concrete values.
- Svara occasionally repeats or drops a word: the app flags unusual length per part; use "Make again" (new seed).
- Hindi captions rely on the Nirmala UI font being installed.
- One GPU, one request at a time: a full video is a long job (voice about 26 minutes, pictures about 1 to 2 minutes each).
- README.md still describes Phase 1 in detail; this guide is the current overview.

## 8. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Voice job fails after about 2 minutes with 502 | gateway `timeout_s` for `svara-tts` back at 120; set 600 in `serve_models.yaml` and restart the gateway |
| App will not start after a pull, "No module named ..." | the watcher uses `.venv`; run `.venv\Scripts\python.exe -m pip install -r requirements.txt` |
| "another planning job is running" | one job at a time; wait, or press Stop on the running one |
| "the plan changed after export vN" | export again before making voice |
| Approval shows "changed" | something in the content hash changed (wording, scenes, registry); review and approve again |
| Pictures marked "old" | the item's description, fixed details, style or model changed; draw again |
| Page looks stale after an edit to `plan.js` | hard reload; the file is served uncached |
| A request is refused with 409 | story processing (Phase 1) is running; the model server answers one request at a time |

## 9. Conventions

- Match the surrounding code's comment density and naming; comments explain why, not what.
- Add tests with each batch (fake gateways, no real models); run the whole suite before committing.
- Small batches, each connected to the screen (journey step, "Next:" prompt, side-panel step, section) so the user can follow the whole process.
- Commit messages describe the batch; the watcher deploys `origin/master`.
