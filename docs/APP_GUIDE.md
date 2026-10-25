# Source-to-Story: application guide

Written 2026-10-24, after Phase 1, Phase 2, Phase 3 batches E (voice) and F (reference sheets, scoring) and the change of visual direction. This is the one document to read to understand the app, run it, and continue building it. The next phases are in [ROADMAP.md](ROADMAP.md).

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
- **Visual direction (owner decision, 2026-10-24): illustrated story scenes, not charts.** The video is a graphic novel: people, places and moments that could really have happened, drawn in one chosen style (default: game-art illustration like a GTA V loading-screen painting; also noir graphic novel and painterly concept art), with faces and emotion. Charts, documents and screens appear only when the narration states exact numbers (at most one scene in six). Characters are invented composite people; a real, named person is only a silhouette, from behind, in shadow or by the hands.
- **On-screen text is English only** (never Devanagari). Short quoted English text is drawn correctly by both image models, so it goes into prompts exactly as written (8 words at most, words and numbers from the facts only).
- **The image models do exactly what is written and invent the rest**, so every character, place and object is described slot by slot with concrete values (colours, materials, counts); nothing is left to the model.
- **Never name a game or brand in a prompt** (it printed as a logo on props); describe the look instead.
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
- Tests: `.venv\Scripts\python.exe -m pytest tests` (mocked models; **185 passed, 1 skipped**). Set `LIVE_LLM=1` for the optional real-model tests.

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
  storyboard.py      asset registry, scenes, timing, retiming to real audio, repeat fixing (redraw, then a model-free sweep so one press settles every repeat)
  director.py        the shot plan: emotion, place, size, angle and camera move for every segment, planned before any scene is drawn; scenes follow it
  narration_audit.py a fixed rubric (questions, flat voice, repeats, stock phrases, romanised Hindi, opening length) to compare two narrations number by number
  styles.py          the visual style presets (filmic is the default; gta, noir, concept remain), their look text, palette, negative words, LoRA hook, and the DIRECTION version
  describe.py        slot-by-slot descriptions: slots per kind, compose the description, report vague or empty slots
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
  refs.py            Batch F: reference model sheets (people: 4 poses on white; objects: 3 views; places: one view), approval, bulk approve
  refscore.py        Batch F: measure a picture and look at it (vision) -> score, with a pose-consistency check for sheets
  thumbnail.py       the YouTube thumbnail: a movie-poster picture with a short curiosity question on it (Qwen, words in quotes, read back, 1280x720)
  auto.py            Auto-run: every unfinished step in order as one job (keep in step with the plan screen)
  api.py
static/              index.html (all pages), plan.js (the plan screen), style_samples/ (three sample pictures); no build step
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
3. **Voice is made from a saved export** whose hash equals the current plan (`voice.load_export`). Reference pictures are the exception: they need only the characters list (the registry), so they come before the storyboard.
4. **Export has two halves.** `public` (everything that may be spoken, shown or sent to a model) and `evidence` (the fact trail, never in a prompt). The leak gate scans `public`; an export with a finding is refused.
5. **No single combined editorial score.** Twelve dimensions, each with score, band, reason and fixes; sign-off has blockers and warnings. (Reference pictures do have one 0-100 ranking score, with its parts shown.)
6. **Long or numeric charts, documents and tables are never drawn by an image model** (a fake chart looks like evidence); they are built by code from verified facts (Batch H). A short quoted English label or number (up to 8 words) on a sign, headline or screen is drawn by the model.
7. **Jobs are one at a time.** A job saves each item as it finishes; Stop loses only the item in flight; a failed item is recorded and the job continues; an unreachable model server stops the job with a clear reason.
8. **Voice validity** is tied to a hash of the annotated text plus the voice: if a part's wording changes, its old audio stops counting.
9. **Picture validity** is tied to a hash of the item's description, fixed details, period, style and model: change them and older pictures are marked old.
10. **Style is chosen once per plan** (`plan.settings.visual_style`) and written into the style asset, every scene prompt (first and again as a closing line) and every reference picture. The registry and the storyboard remember the style and the `DIRECTION` they were made under; if either differs from today's, the plan page marks them "made for another look" and leads through redoing them. The style asset text is set from the preset, never by the model.
11. **Descriptions are composed from slots** (`describe.py`); an asset with empty or vague slots is listed in `cast_gaps` on the plan response and shown with a "Fill in the gaps" button.
12. **The registry reads the whole narration** and must list every person, place and object it needs; charts, graphs and documents are filtered out of the object list in code. "Add one" adds anything it missed.
13. **LoRAs:** none are needed (all three looks render on the base models). `styles.LORAS` names any to send per style and model; attach the file to the model in the gateway console first.
14. **Plan, then draw, and wire what you plan.** The director's shot plan (`story2/director.py`) is made when the storyboard is. Each scene names the shot it follows (`scene.data.direction`), the shot's size and angle are written into `composition`, the Qwen prompt opens with the camera (`imgprompts.shot_line`), and `story3/video.py` takes the camera move from `direction.move`. A new planned field must reach the scene, the prompt and the consumer; check all three.
15. **The blueprint carries a suspense plan** (cold open, stakes, the wrong answer first, the dark moment; per beat: reveal, hold back, plant, feeling, ends on). Every beat's narration prompt gets it, plus a storyteller persona. Narration is sent back (the last attempt is always accepted, so a run never stops on style) for: Hindi in Latin letters, an opening sentence over 14 words, repeated sentences, an opener or a stock phrase used again, characters the voice cannot say. Neutral is the default voice; a flat voice is never penalised.
16. **Step order** (auto-run and the screen): blueprint, narration, characters, storyboard, references, prompts, repeats, approve, export, voice, pictures, graphics, video, thumbnail. References come after the storyboard so only assets the scenes use get one, and are skipped when scenes are drawn plain (auto-run's default), because plain drawing never sends them.
17. **Cards that add nothing are not shown.** A graphic made only from a label, or with a caption cut off mid-sentence (`graphics.thin`), is never approved by itself and counts as settled; the video shows the scene's own picture instead.
18. **The finished video plays at 1.25x** (`video.PLAYBACK_SPEED`: picture, voice and burned captions together, voice pitch kept). Recorded as `meta.speed` and part of the video's hash.
19. **Validators accept their last attempt.** `JsonCaller.last_attempt` tells a checker it is the final try; style checks send the reply back before that and let it through then, so a long run never stops on a style rule. A storyboard reply that is broken JSON is asked again up to three rounds.

## 5. Using the plan screen (the path to a video)

The plan page has a **journey bar** (Story, Blueprint, Narration, Characters, Storyboard, References, Image prompts, Checked, Reviewed, Approved, Exported, Voice), a **"Next:" bar** with one button for the next step, a red/amber/green **banner**, and a **sticky side panel** of numbered steps. The page refreshes itself every 1.5 s while a job runs. A **Visual style** card (three sample pictures) and a **Characters, places and objects** card sit above the storyboard; the **Reference pictures** section follows them.

| Step | What happens | Model needed |
|---|---|---|
| 1 Plan the story | Blueprint: structure, viewer promise, central question, beats | chat |
| 2 Write the narration | Hinglish narration per beat, one emotion per part | chat |
| 3 Create characters and places | Reads the whole narration; lists every person, place and object slot by slot; style asset set from the preset. "Add one" and "Fill in the gaps" complete it | chat |
| 4 Design the storyboard | The director plans the whole film as shots first, then scenes per part follow their shots (a segment that returns broken JSON is asked again); "Redesign" replaces approved scenes too when the style changed | chat |
| 5 Make reference pictures | Model sheets on white (people: four poses; objects: three views; places: one view), only for people and places in two or more scenes and objects in three or more; 2 candidates each, scored; "Approve the best" or approve one by one; Skip. Auto-run skips this step when scenes are drawn plain | image + chat (vision) |
| 6 Write image prompts | Qwen and FLUX prompts for every scene (instant) | none |
| 7 Check everything | Validation of narration, scenes and prompts | none |
| 8 Fix camera repeats | Redraw scenes that repeat the previous camera, then change any that still repeat; rewrites the prompts and re-runs the checks, so one press settles it | chat |
| 9 Review and score | Twelve scores with reasons; sign-off checklist | none |
| 10 Approve the plan | Sign off the exact reviewed version (tied to the content hash) | none |
| 11 Export | Versioned JSON file, schema-checked and leak-checked | none |
| 12 Make the voice | Svara, one request per part; scenes retimed to real audio; "Approve all voice" | voice |
| 13 Scene pictures | Three-scene trial on both models (plain and from the reference sheets), choose the way, then one picture per scene (16:9, 1344x768); Draw again, Correct this, scores, "Approve the best"; resume after a stop | image + chat (vision) |
| 14 Graphics | Cards for chart, document, screen, map and diagram scenes, built by code from the story's facts (stat, comparison, bar or line chart, timeline, title card); approve per scene | none |
| 15 Draft video | Checklist of what is missing or not approved; 1080p draft or small preview with eased pushes, pulls, pans and tilts chosen by the director (no frozen frame except cards) over the approved voice, burned-in captions on by default; the finished video plays at 1.25x; placeholders only on request | none (ffmpeg) |
| 15b Video thumbnail | A movie-poster picture with a short curiosity question on it, in the plan's style; three options written from the blueprint, Qwen draws the words in quotes, a vision check reads them back; "Make another" | chat + image |
| Auto-run | One button (top of the side panel, and in the Next bar) that does every unfinished step in order as one background job (`story3/auto.py`): approves the best, else first, finished outcome at each choice; scene pictures use Qwen drawn plain unless a way was already chosen; thin cards are left out in favour of the scene's picture; the thumbnail is made last; the plan is signed off. Stops at the first thing it cannot settle (a sign-off blocker, a missing model, a failing request) and says which step; everything finished is kept and pressing it again resumes. Character-description gaps are not filled (a person must) | all |
| 16 Go to the first problem | Jumps to the first thing that needs attention | none |

Approval of voice and pictures is optional for the draft (the latest valid take counts), but approved items are never regenerated by "all" actions. Changing the visual style (a click on a sample) rewrites the style asset and recompiles prompts at once; the characters, sheets and scenes made for the old look are then flagged.

### API (all under the same login)

- `/api/...` Phase 1: settings, projects (upload, url, text), scope, process, pause, cancel, stories (review, merge, split), export.
- `/api/plans/...` Phase 2: `GET /styles`, `PATCH /{plan}/visual-style`, `POST /{plan}/assets` (add one), plans CRUD, `job`, `cancel`, `narrator`, `settings`, `blueprint`, `narration`, `registry`, `storyboard`, `fix-repeats`, segments and scenes (patch, move, regenerate), assets patch, `review`, `approve`, `unapprove`, `history`, `export`, `exports/{plan}/{file}`, `image-models`, `compile-prompts`, scene `prompts` and `preview`, `validate`, `providers`, `providers/probe`, `schema`.
- `/api/media/...` Phase 3: `GET /{plan}` (voice, references, scenes, graphics, video, thumbnail and auto-run state), `POST /{plan}/thumbnail`, `POST /{plan}/auto`, `POST /{plan}/voice`, `POST /{plan}/references`, `.../references/score`, `.../references/approve-best`, `.../references/skip`, `PATCH /item/{id}` (approve), `GET /file/{plan}/{path}`.

## 6. Where things stand

- **Code:** committed and pushed to `origin/master` (latest work: the director, camera-first Qwen prompts, the filmic default style, the suspense plan and stricter narration checks, the thumbnail, thin-card handling, 1.25x playback, the repeat-fixer loop fix). The app must be restarted to load a pull (the watcher does it when no job runs). The full suite had 290 passing tests at last count.
- **Proof runs** (an 1854 cholera outbreak, a non-finance story, to prove any subject works): `pl-22f2f454` (6 minutes, 59 scenes, 13 of 13 steps with no human step, video 389 s) and `pl-e6535eac` (3 minutes, 36 scenes, 13 of 13, video 206 s). The line-by-line record of what was found and fixed is **`docs/RUN_LOG.md`**: read it before changing narration, the director, pictures or auto-run.
- **What the proof runs showed:** the filmic style and camera-first prompts look much better than the old game-art look; the director removes frozen frames (13% hold against 39%); readable shop signs were the main reason pictures failed the check (fixed by quoting short sign words); the narration reads like a thriller with the suspense plan but still needs a read in Hindi by a person.
- **Narration comparison:** `python -m story2.narration_audit plan1.json plan2.json` prints a table. Baseline, suspense v1 and v2 are in the run log; v2 (with the later fixes) is the version in use.
- **Facts are marked "unverified"** (the user's own task); the narrator name is unset.

### Keeping every picture tied to the story (any subject)

The pipeline must work the same for a market crash, a conspiracy, a lab accident or a medieval siege, so nothing in the code or the prompts may depend on one subject. The protections, in order:
1. **Registry rules** (`story2/prompts.py`): every asset must belong to this story's world and period; the model sets `literal` false for an idea, figure of speech, chart feature or group and those are dropped (`storyboard.not_drawable`, generic word lists only); props that normally carry writing must be blank; a place must name its **signature** (what a visitor sees first that says where they are, with counts).
2. **Storyboard check** (`validate_storyboard`): a scene that shares no content word with the story's facts, characters, places or objects is flagged "unrelated".
3. **Picture check** (`refscore.look`, scene mode): the chat model with vision is given the story summary, the period and the narration of that moment, and scores `story_fit` along with subject, setting, characters, extra things, hands and style; a picture that does not belong to the story is a hard problem and is never approved by the bulk button.
4. **Auto-run** retries a weak picture before approving the best one and lists any it had to approve with a problem.
5. Existing: the leak check keeps source wording out of prompts, and the storyboard instructions forbid unrelated symbols.
Limit: the checks are only as good as the chat model's reading of the story, and none has been run on a story outside finance yet. Run a second, very different story through the screen before trusting this.

## 7. Known gaps and risks

Parked by the owner (not started; details in `docs/RUN_LOG.md`):
- Faces change between scenes because auto-run draws from the text only; sending the approved reference (edit mode) has not been tested for consistency.
- FLUX is still in the code (76 mentions in 15 files); the owner wants one image model (Qwen).
- No automatic check for the same person in the same pose across scenes (only a prompt rule); `emotional_effect` never reaches the picture prompt; the director caps shots that focus on a person but scenes also add people as assets, which is not capped.
- Wide pictures for pan shots are not built (pans crop a normal frame); long storyboard segments are asked again on broken JSON but not split.
- The leak gate refuses a source whose title is the story's real subject name; the owner decides whether to relax it.

Other:
- Frames are dark under the filmic look; brightness is not tuned.
- The suspense lines, the thumbnail words and the 1.25x playback have been checked on test doubles and one real narration, not on a published video; watch the first ones.
- Svara occasionally repeats or drops a word: the app flags unusual length per part; use "Make again" (new seed).
- Hindi captions rely on the Nirmala UI font being installed. On-screen text inside pictures is English only; quoted short words are drawn best.
- One GPU, one request at a time: a 6-minute video took about 2 hours 20 minutes end to end (voice about 22 minutes, pictures about 95 minutes including redraws).
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
| Props show a logo, a face on a screen or stray letters | a game or brand name, or the character clause of the style, is in the prompt; objects and places use the preset's `object_look`; never name a game |
| The same character looks different between scenes | an empty or vague description slot (see "Fill in the gaps"), or no approved reference sheet |
| The plan screen flips between "Write image prompts" and "Fix camera repeats" | fixed: the repeat fixer now settles every repeat and re-runs the checks; restart the app to load it, then press Fix camera repeats once |
| "made for another look" on the plan page | the style or the direction changed since the characters or scenes were made: press the highlighted step |

## 9. Conventions

- Match the surrounding code's comment density and naming; comments explain why, not what.
- Add tests with each batch (fake gateways, no real models); run the whole suite before committing.
- Small batches, each connected to the screen (journey step, "Next:" prompt, side-panel step, section) so the user can follow the whole process.
- Commit messages describe the batch; the watcher deploys `origin/master`.
