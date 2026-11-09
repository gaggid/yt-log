# Tasks: Story Simulator

Plan: [PLAN_simulation.md](PLAN_simulation.md). A task is ticked when it is built AND tested. Section numbers refer to the plan. Ticked: built and tested with the scripted model (tests/test_sim*.py). Unticked: needs the real gateway or the live app.

## S0 Spike
- [x] S0.1 `sim/spike.py`: run the supermarket story and a courtroom story for 5 chapters against the real gateway
- [x] S0.2 Record seconds per stage, dropped-op rate, word counts, referee catches, repetition review in docs/RUN_LOG.md
- [x] S0.3 Edit the plan for what was learned (stage merges, prompt changes)

## S1 Core
- [x] S1.1 `sim/store.py`: tables of section 3 (lazy schema), CRUD helpers, startup repair of `writing` chapters
- [x] S1.2 `sim/models.py`: schemas (World, Entity, Tracker, Guideline, Directive, ChapterPlan, Delta ops, Options, PanelPlan)
- [x] S1.3 `sim/state.py`: tracker kinds, apply and validate deltas (all rejection cases), starting-state validation
- [x] S1.4 `sim/memory.py`: packet builder with priorities, branch-path reads of facts and threads
- [x] S1.5 `sim/engine.py`: Gather, Plan, Resolve hook, Delta, Write (word check), Referee, Archive, stage persistence and Retry from stage
- [x] S1.6 `sim/seed.py`: world, cast, trackers, rules parts and pressure check; chapter 1 through the normal engine
- [x] S1.7 `sim/jobs.py` + `sim/api.py` (setup, entities, trackers, guidelines, chapters, run, stop, delete) mounted in `main.py`
- [x] S1.8 `static/sim.js`: Library, Setup (with Start validation), Story timeline, dock, State panel, running banner with resume; nav link; script route in `main.py`
- [x] S1.9 Sampling entries for all `sm_*` tasks in `story/settings.py`
- [x] S1.10 `tests/sim_fakes.py` and the S1 tests incl. the genre (courtroom) test

## S2 Steering
- [x] S2.1 Directives: CRUD, all four timings, `sm_condition`, fire-once per path, steer bias
- [x] S2.2 Let it run (`sm_pick`) and Auto-run N with all stop conditions and Stop
- [x] S2.3 Rewrite with instruction, Reroll, Accept, sibling "earlier version" restore
- [x] S2.4 Hand edit with `sm_reread` proposal and Apply, stale marks
- [x] S2.5 Branch from any chapter, branch picker, make-current, delete leaf
- [x] S2.6 Suggest more rules; rules version counter and "changed since" note
- [x] S2.7 Steering tests

## S3 Fun and framework
- [x] S3.1 `sim/dice.py`: rolls, modifiers, difficulty, seeded reroll; roll chips in UI; dice off
- [x] S3.2 Cast minds (`sm_minds`) switch
- [x] S3.3 Rollup summaries (`sm_rollup`) and open threads display
- [x] S3.4 Templates (data), save as template, duplicate, export/import setup and full
- [x] S3.5 Reader view; export md, json, zip with ordered panels and captions
- [x] S3.6 Tests for the above

## S4 Pictures
- [x] S4.1 `sim/paint.py`: style and keep-out constants, request builder (edits with refs, generations fallback), no import from `characters/`
- [x] S4.2 `sm_panels` planner and its code checks
- [x] S4.3 Reference paintings for characters and places, hashes, old marking
- [x] S4.4 Paint job (references then panels), media rows `sim_ref` / `sim_panel`, seeds, recipes in meta
- [x] S4.5 Caption strip by code; wide and tall shapes
- [x] S4.6 Gallery UI: redraw, edit prompt, upload, delete; auto-images switch
- [x] S4.7 `admin/storage.py` support for `sm-` (kind, titles, older attempts, prune, irreplaceable uploads)
- [x] S4.8 Paint tests with the mock gateway; one real chapter painted on the real gateway (scratch app)

## S5 Docs and hardening
- [x] S5.1 CLAUDE.md section, Stories help text on the page, RUN_LOG entry
- [x] S5.2 Leakage checklist (plan section 17) run as tests: delete leaves nothing, branch isolation, prompt isolation, restart repair
- [x] S5.3 Plan section 20 traceability re-checked row by row against the running app
- [x] S5.4 Neighbouring suites pass (`test_shorts`, `test_characters`, `test_storage`, `test_feedback`); pre-existing failures listed by name
- [x] S5.5 Plan section 21 all ticked

All tasks are ticked. Not done by choice (see plan section 23): a separate print stylesheet; the later chapter-to-video step (the owner's decision, the export JSON is its contract). Not yet done: the live app has not been restarted with this code (it is uncommitted).
S5.4 note: the 6 failures in tests/test_shorts.py are the same 6 on the commit before this work (checked on a clean copy of HEAD).
