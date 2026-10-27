# Plan: story types (documentary, biography) and the cast choice

Status tracker for the work. Tick a box only when the task is built, wired and tested as described. The "Wiring" line under each task names what must be connected, so nothing is built and left unused. Update this file in the same commit as the work.

Name note: `plans.format` and `projects.format` already mean the picture shape (`16:9`) or the source file type. The new idea is called **story type** (`story_type`) everywhere, never `format`.

## Size

Medium. Part A is small and done. Part B touches every phase but most of it is prompt text and one setting; the risky parts are scoring in Phase 1 (B2) and keeping approvals valid (B9). Estimated at 6 batches, each shippable alone, each with fake-model tests.

## Part A: cast choice (Indian cast or as the story says)

- [x] A1. `settings.cast_indian` choice card above the character list (`static/plan.js`, section `sec-cast`). Wiring: calls existing `PATCH /plans/{id}/cast`; `describe.indian_on` feeds prompts and hashes.
- [x] A2. "As the story says" adds an explicit CAST instruction to the registry prompt (`story2/storyboard.py make_registry`). Wiring: only used when `cast_indian` is false.
- [x] A3. Test: registry user prompt contains the Indian line when on, the "do not default" line when off (`tests/test_cast_and_redraw.py`).
- [ ] A4. (needs the real model and plan pl-316662f7, owner step) Real-model check on plan pl-316662f7: choose "As the story says", press "Create again", read the people list, record the result in `docs/RUN_LOG.md`.
- [x] A5. Update `docs/APP_GUIDE.md` invariant 22 (Indian cast is the default, the other option is "as the story says", chosen before characters).

## Part C: blocked articles (browser retry)

- [x] C1. `story/ingest.py`: a plain download refused like a script (HTTP 403/429/503, or a 200 page that is only a bot-check) is retried by opening the page in the installed Edge or Chrome, headless, and taking the rendered page (`fetch_with_fallback`, `_fetch_browser`, `looks_blocked`). No new dependency. Wiring: `fetch_url` (used by `projects.import_url` and the URL import API) now calls it; the private-host guard still applies; 401/402/451 (login, paywall, legal) are never retried. Tests in `tests/test_ingest.py`. Real check: Wikipedia page rendered in 2 s and extracted (484 paragraphs).
- Learned: `--virtual-time-budget` makes Edge hang on real pages; do not add it. The output goes to a file, not a pipe, because helper processes keep a pipe open.
- [x] C2. Show on the import screen which way the page came (plain or browser) and the message when both fail. Wiring: `import_url` result and the project warnings in `static/index.html`.

## Part B: story types

Types: `incident` (what exists now), `biography`, `documentary`, `explainer`, `listicle`. One story type per project (owner decision); to get another type from the same source, import it as another project. Build order inside Part B: incident, biography, documentary, then explainer and listicle (B2b).

### B1. Setting and picker (foundation)
- [x] Store `story_type` on the project (`projects.meta` or a new column with the `ALTER TABLE` pattern in `story/db.py`) and copy it to the plan on `planner.create_plan` into `settings.story_type`. Default `incident`.
- [x] Project screen: picker on import and on the project page. API field in `story/api.py`.
- [x] Plan screen: show the type in the header; changing it after the blueprint exists marks blueprint and later steps as made for another type (same stale pattern as style, see `style_info`).
- Wiring: every consumer below reads one helper, `story2/types.py get(plan)`, never the raw setting. Test: a plan without the setting behaves as `incident`.

### B2. Phase 1: extraction and scoring per type
- [ ] `story/prompts.py`: candidate-finding and candidate-detail prompts per type. Biography: one subject, candidates are life phases or turning points. Documentary: one thesis, candidates are evidence-backed sections.
- [ ] `story/schemas.py`: allow new `nature` values (`biography`, `documentary`) in `_nature` and `contract.py`; check `kind` handling.
- [ ] `story/scoring.py`: completeness and `final_nature` rules per type. A biography must not be downgraded for lacking a single turning point.
- [ ] `story/pipeline.py`, `story/review.py`: pass the project's type to extraction, `NATURE_RANK` ordering, `rescore` (review.py:277) and the candidate list filter.
- [ ] Candidate list UI: filter and badge by type.
- Wiring: `story/export.py` writes the type into the exported story; `story2/intake.py` readiness checks accept it. Test with a fake gateway for each type.

### B2b. Explainer and listicle (Phase 1 and 2 additions)
- [x] Explainer: one question answered step by step; candidates are concepts or processes. Structure: question, simple model, details, misconception, answer. Existing `nature=explainer` label keeps meaning "weak story"; rename the label in the UI for this type so it is not shown as a warning.
- [x] Listicle: N items from the source; candidates are the items plus an order. Structure: hook, item 1..N, closing. Each item becomes a segment; on-screen number card per item (English, 8 words max) built in `story3/graphics.py`, not by the image model.
- Wiring: `story2/types.py` carries structure, shot mix and graphic defaults per type so B3 to B5 need no per-type branches elsewhere. Tests: fake gateway per type.

### B3. Phase 2: blueprint and narration per type
- [x] `story2/prompts.py`: blueprint structure per type. Biography: chronological arc with the suspense plan. Documentary: claim, evidence, counterpoint, conclusion.
- [x] `planner.make_blueprint` and `planner.make_narration` choose the prompt by type. Narration checks (`planner.make_narration`) keep working: first-person Hinglish, no source mentions.
- [x] Date rule: `intake.readiness` "dates" warning becomes type-aware (biography needs dates, so the warning is stronger there).
- [x] Length warning ("short anecdote") becomes a type-aware check.
- Wiring: `story2/narration_audit.py` works on both. `editorial.content_hash` unchanged unless blueprint shape changes; if it does, migrate approvals (see CLAUDE.md invariants).

### B4. Phase 2: shots and scenes per type
- [x] `story2/director.py`: default shot mix per type (documentary leans on graphics and wide establishing shots; biography on the person and places).
- [x] `story2/prompts.py` scene prompt: until B8 ships, a real named person is a silhouette, from behind or in shadow (existing rule; make sure it is in the biography prompt path).
- Wiring: follow the director rule in CLAUDE.md: field in the scene, text in the Qwen prompt, consumer in `story3/video.py`.

### B5. Phase 3: graphics and video
- [x] `story3/graphics.py`: documentary uses charts, tables and timelines built from verified facts. Add a timeline graphic for biography.
- [x] `static/plan.js` and `story3/auto.py`: no new step is expected; confirm and keep the step order list in sync if one is added.

### B6. Leak gate, export and docs
- [x] `story2/leak.py`: biography subject names are real names; resolve the open question (owner's call, ROADMAP parked item 6) before B2 ships.
- [x] `story2/export.py` and `export_schema.py`: record `story_type`; schema test.
- [x] `docs/APP_GUIDE.md` (8b and invariant 22) and `CLAUDE.md` updated. [ ] `docs/ROADMAP.md` and `docs/RUN_LOG.md` after the real runs (B7).

### B8. Named people: researched likeness (owner decision 2026-10-27, needs the safeguards below confirmed)
Owner wants a named real person in a biography or documentary to look like them: find pictures on the internet, turn them into a character that looks similar across the video, and only when nothing is found use a stylised near-likeness.
- [x] Research step: for each named person in the registry, search the web for portrait photos (needs a search/image source; the gateway has none, so choose one: search API or manual upload). Store candidates with source URL, licence if known, and date in `assets.data.likeness`.
- [x] Human checkpoint per person: the editor sees the found pictures and approves one or more, or rejects. Nothing is used without approval (same pattern as other checkpoints).
- [x] Reference-picture step: the approved photo goes in as a reference image in edit mode to make a painted character sheet in the plan's style (`refs.generate`, see ROADMAP parked item 1 on whether edit mode holds faces). The style asset keeps the result illustrated, not photographic.
- [x] Fallback: when nothing is found or approved, a stylised character built from slots (age, build, features the research states), with no photo.
- [x] Leak gate: the person's name is allowed in prompts only through the registry mapping, and `story2/leak.py` still blocks source/author/book mentions. Decide how a real name is kept out of image prompts (use the character's description, not the name).
- [x] Record per person: where the photo came from, that it was used only as a reference, and who approved it, in the export `evidence` half.
- Safeguards (to confirm with owner before building): public figures only, never private individuals; the character must be a painted likeness used in a factual, non-deceptive way (no invented quotes, acts or scenes that could mislead or defame a real person); scenes show the person doing only what the facts say; photos are references, never published or embedded; respect each site's terms and licences for fetching; the editor can switch any person back to silhouette. Copyright, personality and privacy rights differ by country, and a likeness of a real person in published video carries legal risk: the owner should decide whether to get legal advice before publishing such videos.

### B9. Final validation of every deliverable (last task, do not skip)
- [ ] For each item above, open the wiring checklist and prove it from the running app, not only from tests: write the setting from the UI, see it change a prompt or a screen, see old plans still load.
- [ ] Run the full test suite once (about 5 minutes) and record the result here.
- [ ] A grep audit: every new function, setting and endpoint has at least one caller outside its own file and its tests. List the results in this file.
- [ ] Update `docs/RUN_LOG.md` with what was run and what was found.

### B7. Real runs
- [ ] One PDF as biography, one article as documentary, end to end on the real gateway. Record findings in `docs/RUN_LOG.md`, fix what they show.

## Wiring checklist (run before ticking any batch)

For each new setting, field or function:
1. Where is it written? (API, UI control, default)
2. Where is it read? (prompt, check, hash, video). If nothing reads it, it is not done.
3. Is it in the hash or stale logic it should be in, and out of the ones it should not (`editorial.content_hash` excludes timings, previews, prompts; style and cast flags are in `source_hash`/`asset_hash`)?
4. Does the plan screen show it, and does the journey/Next bar still point at the right step?
5. Does `story3/auto.py` still chain every step in the order in `static/plan.js`?
6. Is there a test that fails if the wiring is cut? (fake gateway, assert the prompt text or setting reaches the consumer.)
7. Old plans without the field still load and behave as before.

## Open questions for the owner

Answered 2026-10-27: (1) all five types: incident, biography, documentary, explainer, listicle. (2) One story type per project. (3) Named people: research and use a similar-looking painted character, stylised near-face only as fallback (see B8).

Answered 2026-10-27: B8 photos come from web search, or the owner uploads one; the safeguards are accepted (the owner uses public figures only).

Still open:
1. Which web-search source B8 uses (the app has none yet; pick when B8 starts).
2. B8 changes the invariant "a real named person is only ever shown as a silhouette" in `CLAUDE.md` and `docs/APP_GUIDE.md`; update both when B8 is built, not before.

## Order of work

A3-A5 first (finish the cast choice), then B1, B2, B3, B4, B5, B2b, B6, B7, and B8 last because it needs the owner's answers and safeguards. After each batch: run the tests for the area changed, tick the boxes here, commit.

## Build log (2026-10-27)

Built and tested with fake models; wired as listed. Not yet done: A4, B7 (real-model runs), B8 (named people), B9 final validation sign-off, the candidate-list type badge in Phase 1 (B2, small), the leak-gate decision (B6, waits for B8).

- Part C: `ingest.fetch_with_fallback` -> `fetch_url` -> `projects.import_url` and the URL import API; project warning when the browser path was used. Tests: `tests/test_ingest.py`.
- Part A: card in `static/plan.js` (`sec-cast`) -> `PATCH /plans/{id}/cast`; registry prompt text in `storyboard.make_registry`. Test: `tests/test_describe.py::test_registry_prompt_follows_the_cast_choice`.
- B1: `story/storytypes.py`; `projects.set_story_type`, `PATCH /api/projects/{id}/story-type`, `GET /api/story-types`; import dialog and project page picker in `static/index.html`; `planner.create_plan` copies the type; plan screen badge and "project changed" warning (`story2/api.py`, `static/plan.js`).
- B2/B2b: `pipeline.py` discover and draft prompts, `scoring.final_nature`/`completeness`, `review._reclassify`, `intake.readiness`.
- B3/B4/B5: blueprint, narration, director and scene prompts (`planner.py`, `director.py`, `storyboard.py`) with notes from `storytypes.py`; new structures in `story2/schemas.py`; the scene designer asks for timeline, chart and number cards, built by the existing `story3/graphics.py` templates.
- B6: `plan.story_type` in the export and in `docs/plan_schema.json`.
- Tests: `tests/test_story_types.py` (15) cover each wire above.

## B9 audit: callers outside the defining file and its tests

of_plan 7, of_project 2, for_pid 7, discover_note 4, draft_note 2, blueprint_note 1, narrate_note 1, director_note 1, scenes_note 2, set_story_type 2, fetch_with_fallback 1, looks_blocked 2, _fetch_browser 2, redo_note 1, _completeness_other 1. Live check: a throwaway server on port 8999 accepted an import with a story type, changed it, and refused an unknown one.

## B9 full test run (2026-10-27)

Full suite: 354 passed, 1 skipped, 1 failed. The failure, `tests/test_auto.py::test_the_thumbnail_is_made_last_from_the_plan_and_approved`, also fails with all of this work stashed: the test expects "Movie poster" in the thumbnail prompt, which now reads "Photorealistic YouTube thumbnail ... Composite image" (from commit f08f217). It is not caused by story types and still needs its own fix.

## Build log, second round (2026-10-27)

- Thumbnail test fixed (`tests/test_auto.py`): it still expected the old "Movie poster" prompt and a removed `poster_prompt`; it now checks the composite prompt and `_fallback_prompt`.
- Type badge: shown on the story cards and in the story drawer when the project is not an incident project (`typeBadge` in `static/index.html`).
- B8 built: `story3/likeness.py` (modes, Wikimedia Commons search with licence and author, upload, approve, reject, evidence); API under `/api/media/{plan}/likeness`; "Real person?" block on each person in the plan screen (`likenessBox` in `static/plan.js`); `refs.generate` paints the sheet from the approved photo through the edit endpoint; `make_registry` keeps the editor's choices when the characters are created again; `editorial.content_hash` leaves `likeness_photos` out; the export evidence lists the source of each used photo; the scene prompt text no longer says every real person is a silhouette. Search source chosen: Wikimedia Commons (free images with their licence), because the app had none and a general image search cannot say whether a picture may be used. A live search for a well-known public figure returned licensed photos and a download converted correctly.
- B6 decided and built: the leak gate allows the name of a person the editor confirmed as a public figure, so a biography whose source title is the subject's name can be exported; the author's name is still blocked. Tests in `tests/test_likeness.py`.
- Not covered by a real-model run: the edit call with a real photo and the face likeness it gives. Owner step: try one public figure on a real plan and judge the sheet (ROADMAP parked item 1 asks the same question).

## Simulated run, partial (2026-10-27, real models, throwaway server on port 8999)

The owner stopped the run before it finished; the rest is theirs to check. A one-minute Marie Curie text, imported as a biography:
- Phase 1 (7.5 min): 4 leads, all rated "story", completeness 85 under the biography rules. They are single episodes, not a whole life; merging the four into one story was needed to get a biography. Possible later change: ask the biography prompt for one whole-life lead.
- Plan made with `story_type: biography`; blueprint used the new `life_arc` structure.
- Found and fixed during the run:
  1. A 1-minute target gave 8 beats and a 3.5-minute script. Beats are now capped by the target length (`planner.max_beats`, 3 for one minute), the request says so, and a beat far over its share of the words is sent back once (`LONG_BEAT_FACTOR`, the last attempt is accepted). Second try: 3 beats, as intended.
  2. Planning the story again left narration (and scenes) of beats that no longer exist. They are now removed when narration runs.
  3. People were drawn as Indian (Marie Curie as an "Indian woman, 30") because the cast choice was never forced. Characters can no longer be created, by hand or by auto-run, until the cast is chosen (plans that already have characters are exempt). With "as the story says" the registry gave pale skin, fair hair and period clothes.
  4. The chat model name was sent in every request. The app now names no model unless one is typed in Settings; an old saved default counts as unset, so the model server's own default answers (`llm.model_field`).
- Wikimedia Commons search for "Marie Curie" returned four public-domain photos with author and page; the first was a group photo (a conference), so the editor must look before approving. Upload covers the case where none is good.
- Not reached: storyboard result, reference pictures (including the photo-to-character sheet), scene pictures, voice, video, thumbnail, export. A4 and B7 therefore stay open.
