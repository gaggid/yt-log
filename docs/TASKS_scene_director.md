# Tasks: Scene Director

Plan: [PLAN_scene_director.md](PLAN_scene_director.md). Tick a task when it lands.

## Step 1: storyboard check (built 11 Nov 2026)

- [x] `shorts/lint.py`: the rules (stray subject, setting conflict, angle wording, text in the picture, group count), the notes (place, composition, few people), `tidy_shot`, `findings`, `apply_to`, `report`, `stamp`
- [x] Root cause fixed in `stills.looks_line`: a plan subject is added only when the picture text names it (whole name, or a word only that subject has); a short made before the check keeps the old rule
- [x] `stillwriter`: prompt rules (angle as a sentence, no text, exact group counts), validator `problems(strict)` sends back text and vague groups, `tidy_shot` after writing
- [x] `planner.make_plan`: the check runs on the fresh plan before the motion is written
- [x] `auto`: step "Check the storyboard" after the plan; a failure never stops a run; drawn pictures are protected
- [x] `checks.run`: what is left shows as a warning with a fix button (never a blocker)
- [x] API: `POST /{id}/lint` (`protect`, `enable`), `lint` in the short's state, setting `storyboard_lint`
- [x] Screen: Storyboard check card (changes, left alone, to fix, notes, buttons), settings checkbox, fix button in Checks
- [x] Tests: `tests/test_lint.py`
- [x] Real data: on `sh-16824387` the check removes all 9 stray money blocks and all 6 wrong market settings (docs/RUN_LOG.md)

## Step 2: scene review (built 11 Nov 2026)

- [x] `shorts/review.py`: contact sheets with shot labels, the blind description call (strict JSON schema, free-text fields), defects decided in code, engagement (five parts), repeat (measured colour and layout plus description overlap), the three floors, summary, `stamp`/`current`/`ready`, `run_on`/`run`/`report`
- [x] `story/llm.py`: `JsonCaller.call(response_format=...)` (a strict `json_schema` goes to the gateway as it is); `p4_review` samples at temperature 0
- [x] `lint.scene_place`: what a screen shows is not the place of the scene (also used by the storyboard check)
- [x] Auto-run step "Review the pictures" (optional, after the pictures, before the person looks), never stops a run
- [x] API `POST /{id}/review`, `review` in the short's state, setting `scene_review` (on for a new short)
- [x] Screen: Scene review card (summary, floors, per-scene table) and engagement/repeat/defect badges on every start picture; settings checkbox
- [x] Tests: `tests/test_review.py` with `tests/fixtures/review_sh16824387.json` (the real descriptions of the 17 pictures)
- [x] Real run on `sh-16824387` (docs/RUN_LOG.md): 9 of 9 stray money piles, 6 of 6 wrong places, blank backgrounds and the style break, the gibberish text, 120 s for 17 pictures
- [ ] Not in step 2 (by design): stopping before the clips when a floor fails, any automatic change (step 4)

## Step 3: test mode on the next 5 shorts: running by itself

Step 2 reads and reports and changes nothing, so every new short is already in test mode. To do: compare the review's defect list with your own eyes on the next 5 shorts (a defect that you would not call one counts as wrong), then decide whether step 4 may start.
## Step 4: the Director (defect fixes with keep-or-revert): built, runs in shadow first

- [x] `shorts/director.py`: modes off / shadow / defects (setting `director`; a new short and the autopilot start in shadow; a short from before it has no key and stays off)
- [x] Only objective defects (extra object, wrong place, text, style break, blank background, wrong head count, duplicate) are acted on; taste is never changed
- [x] A trial = tidy by code and/or picture writer with a plain note, draw that one picture again, describe only it again; kept only when its defects are gone and no new kind appeared, else the old prompt and so the old picture is back (the trial picture stays as a failed attempt with the reason)
- [x] Limits: 2 rounds, 30% of the shots per round, a shot that failed twice is left for a person, 25 min budget; never touches the person's own picture, an approved picture, an avatar or a made clip
- [x] Hook or dead-stretch floor fails in defects mode: auto-run stops before the clips with "Needs your look" (a third waiting short goes on with a warning, so the autopilot never jams)
- [x] Auto-run step "Fix the pictures" / "Check what could be fixed" (optional, never stops a run on failure), `POST /{id}/director`, `director` in the state, settings select, Director card, Ideas config select
- [x] Tests: `tests/test_director.py`
- [ ] Not done by design: switching the autopilot from shadow to defects (waits for step 3: the owner compares the review with their own eyes on 5 shorts)
## Step 5: audience panel: not started
## Step 6: screens, rules page, dial: not started
## Step 7: calibration with real retention: not started
