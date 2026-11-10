# Plan: Story Architect 2 (the film framework)

Status: built and tested with the scripted model; the real-gateway run (tasks E2) waits for the owner to say the gateway is free. Tasks: [TASKS_architect2.md](TASKS_architect2.md). Reference: [FRAMEWORK_story_videos.md](FRAMEWORK_story_videos.md). Builds on [PLAN_architect.md](PLAN_architect.md).

## 0. Why

Comparing four videos of the same channel with the first Story Architect showed that the skeleton matches (second person, secret with clues, rules, motifs, facts, day beats, hooks) and that seven structural elements are missing or only suggested. They are properties of the plan, so they are built into the plan, validated in code, shown to the writer, and read by story health. The prose quality stays bounded by the model; this plan makes the structure complete.

## 1. What will be built (items 1 to 7 of the comparison)

All new plan fields are optional: a plan written before this change keeps working and is simply reported as lacking them on the Plan tab.

| # | Element | Plan field | Code decides | Writer and planner see | Health and Plan tab |
|---|---|---|---|---|---|
| 1 | Problem ladder with signposts and the solving fact | beat `solved_by`, derived `problem_no`, `signpost` ("Second problem: the water heater") | numbering by code; at least half of the problem beats must name what solves them (fact, rule or idea), else the model is sent back once | the planner is told what solves the problem; the writer is told to say the signpost aloud when the setting `signposts` is on (film template) | audit: unsolved problems; health: signpost words in prose |
| 2 | Countdown number | bible `countdown` {name, unit, steps [{beat, value, note}]}; derived beat `count` | steps clamped to beats and sorted, value carried forward to every beat | the writer must state the number and what it was before | audit: no countdown; health: the value missing from a chapter |
| 3 | Authority-lie secret with a method | secret `kind` (authority_lie, trap, hidden_resource, betrayal, identity, other), `lie` (what the authority publicly says), `found_by` (how the person finds out), `method_beat`; four candidates before the plan (`sm_secrets`) | method beat sits after the last clue and before the reveal, else moved | the method beat gets purpose clue and the method text; the reveal names the lie | audit: secret without method; the Plan tab shows four candidates to pick or edit |
| 4 | Ending turns the opening around | bible `opening` {line, action, belief}; ending `inversion` | an ending without an inversion is sent back once | the first chapter opens on the line and action; the last chapter must turn that action or belief around | audit: no inversion; health: ending words against the opening |
| 5 | Act shape | bible `midpoint` {beat, change}, `low_point` {beat, loss}; derived beat `act`, `role` | midpoint clamped to 40 to 60 per cent, low point to 70 to 90 per cent and after the midpoint, never the reveal or the last beat | the beat gets its role and a line saying what changes | audit: missing or misplaced; Plan tab shows the act of each beat |
| 6 | Planted-object ledger | bible `objects` [{name, what, plant_beat, payoff_beat, payoff}]; derived beat `plant`, `pay` | payoff after plant, both inside the plan; at most 8 | planner and writer: plant it, show it, pay it off the way the ledger says | audit: unpaid object; health: object missing from the chapter |
| 7 | Long films | beats written in chunks of 12 with the beats so far in the prompt; bible sizes scale with the length | chunk numbering, one ending, global checks after the merge | the chunk prompt carries the beats already written | a 45-beat plan is a test, not a guess |

### Rules of four kinds (the question about unsaid policies)

Rules the person discovers gain `kind` (stated, discovered, policy), `uses` (the beats where the rule is used again; the writer repeats its wording as a refrain), `shown` (for a policy: how it appears without being said) and `broken_beat` (one rule is broken on purpose in the last third). A policy is never announced by the narrator; the writer is told to show it by what happens. The rule that is a lie is the secret's `lie`.

### Four candidate secrets

`POST /{id}/secrets` asks the model for four different secrets that fit the idea (at least one authority lie, one that is not), each with its lie, method and three clues in short form. The person picks one (or edits it) and the plan is written around it (`POST /seed/bible` with `secret`). Without a pick the model chooses, as before.

## 2. What this does not do

- It does not make the prose better; it makes the structure complete and checks it.
- Facts stay the model's general knowledge; they are listed for the owner to check.
- Stories without a plan, and plans written before this change, run exactly as before.

## 3. Build order

1. Models, `architect.clean_bible` / `clean_beats` / `decorate` / `audit`, prompts BIBLE and BEATS, chunked beats, `secret_candidates`.
2. Blocks for the planner, writer and referee (`plan_block`, `write_block`, `referee_block`) and the engine call with the `signposts` setting.
3. Health: new counts and verdicts. API: audit in the plan view, candidates endpoint, secret pick, rule and beat edits for new fields.
4. Plan tab: audit list, countdown, objects, acts, rule kinds, candidates picker. Film template turns signposts on.
5. Tests, then a real-gateway run only when the owner's live story is idle.
6. Docs, CLAUDE.md, final walk against section 1.

## 4. Traceability (comparison item to test)

| Item | Test |
|---|---|
| 1 ladder | `problem_no` and signposts are set; a plan with fewer than half the problems solved is sent back; the writer block carries the signpost only when the setting is on |
| 2 countdown | values carried forward to every beat; the writer block carries the number; health flags a chapter without it |
| 3 secret | method beat moved between last clue and reveal; candidates endpoint returns four; the pick reaches the bible prompt; the method beat has purpose clue |
| 4 ending | an ending without inversion is sent back once; first block carries the opening, last block the inversion; health verdict |
| 5 acts | midpoint and low point clamped; derived `act` and `role`; audit flags a missing one |
| 6 objects | payoff after plant; plant and pay show in the blocks; health flags a missing object |
| 7 long | a 40-beat plan is written in 4 calls with one ending and continuous numbers |
| rules | kind, uses, shown, broken_beat are cleaned; policy rule is told to be shown, not stated |
| old plans | the existing architect tests pass unchanged |
