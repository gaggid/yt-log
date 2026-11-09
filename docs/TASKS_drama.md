# Tasks: drama engine

Plan: [PLAN_drama.md](PLAN_drama.md). A task is ticked when it is built AND tested.

## H Story health (A)
- [x] H1 `sim/health.py`: dice record, costs, intensity, spotlight, material used, endings, repetition, options, pace, verdicts
- [x] H2 Ending classifier shared with the writer check (C)
- [x] H3 API: `health` in the story detail; Health card and per-chapter intensity on the Story tab (phone checked)
- [x] H4 Tests, including the numbers of the audited story shape (all successes, no cost, menu endings)

## B Drama director
- [x] B1 `sim/drama.py`: phases and tension targets for planned length and open-ended waves; setting `length` (store, API, Setup select)
- [x] B2 Plan prompt: arc phase, target, intensity of the last chapters, neglected list; plan field `opposition` (required); sending the plan back when it ignores the neglected list
- [x] B3 Risk calibration before the dice (harder after free chapters, easier after punishing ones), recorded on the roll
- [x] B4 Cost guarantee after the delta (a failed or partial roll always costs something, shown as a change)
- [x] B5 Writer prompt gets the opposition move; plan shows it on the chapter card
- [x] B6 Tests

## C Endings and options
- [x] C1 Writer check sends back a menu ending
- [x] C2 Options with `cost`, risk word out of the hint, repeated moves dropped, conflicting options asked for; card shows the cost
- [x] C3 Tests

## D Friction
- [x] D1 Relation trackers for related pairs at setup; prompts mention relations
- [x] D2 Tests

## R Real runs and the walk
- [x] R1 Health of the audited live story (read only, on a copy of the database): 8 of 8 rolls succeeded, endings plain/menu/menu, "heavy" 10 times, 3 chapters of 4 people not seen: matches the manual audit
- [x] R2 Real run recorded in `docs/RUN_LOG.md`: supermarket 4 chapters; the courtroom story was stopped after chapter 1 so as not to starve the owner's live app (to be repeated when the gateway is free)
- [x] R3 `CLAUDE.md` paragraph, final walk against plan section 4, commit (push only when the owner says)
