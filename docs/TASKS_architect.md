# Tasks: Story Architect

Plan: [PLAN_architect.md](PLAN_architect.md). A task is ticked when it is built AND tested.

## A Plan and beats
- [x] A1 Table `sim_bible`, store helpers, delete with the story, export and import
- [x] A2 `sim/architect.py`: models, prompts `sm_bible` and `sm_beats`, validation (payoffs after setups, secret reveal late, last beat is the ending), seed part `bible` (also for a running story from its next chapter)
- [x] A3 Tests with the scripted model

## B Chapters play the beats
- [x] B1 Plan prompt gets the STORY PLAN block; a plan that ignores the beat is sent back
- [x] B2 Writer gets voice, pov, hook and the no-early-reveal rule; story time and label from the beat
- [x] B3 Options are ways to handle the next beat's problem
- [x] B4 Referee checks early reveal and the beat's clue, rule and motif
- [x] B5 Re-plan of the remaining beats (own action, big change, button)
- [x] B6 Tests

## C Short scenes and the film template
- [x] C1 Template Day-by-day film; chapter words down to 100; setting for pov
- [x] C2 Chapter JSON carries the beat label, the facts and the closing line

## D Health reads the plan
- [x] D1 Beats hit, clues planted, rules and motifs shown, verdicts
- [x] D2 Tests

## E API and UI
- [x] E1 API: bible get (secret hidden), edit, edit one beat, seed, re-plan
- [x] E2 Plan tab (spoiler toggle, beats with status, edit, re-plan), help text, phone check

## R Real run and walk
- [x] R1 Real run with the video's own premise: plan and 4 chapters, compared with the video in `docs/RUN_LOG.md`
- [x] R2 `CLAUDE.md` paragraph, final walk against plan section 4, commit
