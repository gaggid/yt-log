# Plan: the drama engine of the story simulator

Status: building. Builds on [PLAN_simulation.md](PLAN_simulation.md) and [PLAN_discoveries.md](PLAN_discoveries.md). Tasks: [TASKS_drama.md](TASKS_drama.md).

## 0. Why

The owner ran a real story (supermarket, 3 chapters) and asked for an audit. The engine remembered and checked the story well, but nothing steered how it felt over time. The audit found, and the owner confirmed, that for any genre the same weaknesses can appear:

1. All dice rolls succeeded, nothing was lost, so there was no tension (a meter in good shape gave a free bonus; the planner picked easy acts).
2. The story walked from place to place; the only escalation came from the owner's own instruction.
3. Options were low-stakes filler, one per character, often the same move twice.
4. Chapters ended on the same "to the left, to the right" menu.
5. Character secrets and goals were not used; one person did everything; nobody changed.
6. The opposing force (threat, rival, deadline) never acted on its own.
7. The owner could not see any of this without reading the story and judging it by hand.

The owner's instruction: change the core system, not the one story, so any genre benefits ("other stories may unfold differently"). Everything below therefore works from the story's own state and goal and names no genre.

## 1. What will be built (four parts)

### A. Story health (code only, no model call)

`sim/health.py` reads the chapters of the current line and computes, per chapter and overall:

- **Dice record:** counts by tier, the current streak of chapters without a failed or partial roll.
- **Costs:** what a chapter cost the people (a failed or partial roll, a meter that fell, a thing lost, a clock that moved, a relation that worsened, a person hurt or dead). A chapter with none is "free".
- **Intensity:** a 0 to 10 score of the chapter from those costs and the pressure it ended under (full clocks, meters in danger).
- **Spotlight:** how many times each living person is named in each chapter, how long since each was a focus, who is neglected.
- **Material used:** for each person, whether their goal, fear and secret have appeared in the prose (word overlap), and how many chapters ago; for each open thread, its age.
- **Endings:** each chapter's closing is classed as hook, decision, reveal, menu (a list of routes), or plain; the last two sentences are compared.
- **Repetition:** words used more often than 0.6 per cent of the story that are not names.
- **Options:** duplicates, share per person, how many were small errands.
- **Pace:** story minutes per chapter, and progress of a countdown clock compared with the story clock.
- **Verdicts:** short plain sentences ("3 chapters, no failed roll and no cost: the story is flat", "Silas has not been in focus for 3 chapters").

Shown on the Story tab as a Health card and returned by the API; the next part uses the same numbers.

### B. Drama director

- **Planned length** (story setting `length`: 0 open-ended, 12, 24, 36): the engine knows the phase: setup, rising, midpoint, crisis, climax, resolution (open-ended stories repeat a six-chapter wave). Each phase has a plain instruction and a target tension (1 to 10).
- **Tension target in the plan:** the planner is told the phase, the target and the intensity of the last chapters; if it is below target the chapter must raise pressure.
- **Risk calibration (code):** before the dice, if the last two chapters had no failed or partial roll and no cost, the riskiest planned act is made one step harder; if the last two chapters were punishing and the story is above target, one step easier. Recorded as `calibrated`.
- **Costs that must land (code):** when a roll failed or went partial and nothing in the changes costs the people, the system adds one (the first pressure clock moves; else the group's first meter falls) and shows it as a change.
- **Neglected material:** the planner gets a list (people not seen for 3 chapters, goals, fears and secrets not surfaced, threads older than 4 chapters) and must move at least one per chapter from chapter 3 on; the plan is sent back when it ignores all of them.
- **Opposition move:** the plan has a new required field `opposition`: what the opposing force (threat, rival, deadline, a secret about to come out) does this chapter whatever the people do. The writer must show its effect.

### C. Ending and option craft

- **Endings:** the writer's reply is sent back when the chapter ends on a menu of routes ("to the left, to the right", "either path") and must end on a hook, a decision or a reveal.
- **Options as dilemmas:** each option has a `cost` (what it may cost) beside the hint; the risk word stays out of the hint; options that repeat a move are removed; the writer is told that some options must conflict (the people cannot do both).

### D. Friction between people

- After the trackers are made, up to three relation trackers are added for the pairs the cast cards already relate (rival, mother, old friend...), with tension taken from the words used. The planner and the delta prompt are told to move relations when people clash or help each other.

## 2. Build order

1. `sim/health.py` and its tests, API field, Health card, per-chapter intensity (A).
2. Arc, phases, setting `length`, plan prompt, `opposition`, neglected list, calibration, cost guarantee (B).
3. Ending check and options with costs (C).
4. Relation trackers at setup (D).
5. Real-gateway runs: supermarket and courtroom, 4 chapters each, health numbers before (the audited live story) against after.
6. Final walk against section 4.

## 3. Rules the build keeps

- No genre word in code or prompts (the existing grep test).
- Every check that can send a reply back accepts the last attempt (`caller.last_attempt`), so a run never stops on style.
- Everything is derived from stored chapters, so old stories get a Health card at once and the director from their next chapter.
- Nothing here edits an old chapter.
- Phone friendly, English only.

## 4. Traceability: audit finding against build

| Finding | Where | Test |
|---|---|---|
| All rolls succeeded, nothing lost | B risk calibration, cost guarantee; dice meter fix (done) | streak of free chapters makes the next risky act harder; a failed roll always costs |
| Story walks aisle to aisle | B arc phases, tension target, opposition | plan prompt carries phase and target; `opposition` required |
| Options were filler | C dilemmas with cost, dedupe; goal line (done) | duplicate removed; cost shown |
| Same ending every chapter | C ending check; A ending class | a menu ending is sent back; health flags two menus in a row |
| Secrets and goals unused, one person does everything | B neglected list; A spotlight | neglected list names the stale ones; plan sent back when it ignores them |
| Opposing force does nothing | B opposition | written into plan and the writer's prompt |
| Characters do not clash | D relations | relation trackers made for related pairs |
| Owner cannot see any of it | A Health card | verdict sentences; intensity per chapter |
| Works for other genres | all | the same code runs the courtroom story; no genre words |

## 5. Definition of done

- Every row of section 4 has a test or a recorded real run.
- Health numbers for the audited live story are computed (read only) and match the manual audit (all rolls succeeded, 0 costs, menu endings in two chapters).
- A real run of two unlike stories shows intensity rising toward the target and at least one failed or partial roll with a cost per story, recorded in `docs/RUN_LOG.md`.
- Old stories open and run unchanged.
