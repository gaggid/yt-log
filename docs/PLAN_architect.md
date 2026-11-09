# Plan: the Story Architect (an authored backbone for the story simulator)

Status: building. Tasks: [TASKS_architect.md](TASKS_architect.md). Builds on [PLAN_simulation.md](PLAN_simulation.md), [PLAN_discoveries.md](PLAN_discoveries.md), [PLAN_drama.md](PLAN_drama.md).

## 0. Why: the owner's inspiration

The owner's inspiration is a 9-minute animated story, "Zombie Outbreak: 30 Days Locked Inside a School | Nobody Gets In" (2 million views, 12 scenes over 30 days, about 1,500 words). Its transcript shows what a story like that is made of, and the simulator, run on the owner's own story, is "nowhere close". The differences, one by one:

| In the video | In our output |
|---|---|
| One tight situation: one person in one classroom, told to "you" in the present tense | Four people wandering supermarket aisles in third person, with chapters of 15 story minutes |
| A ladder of numbered problems (door, water, bell, food...), each with a concrete number or a real-world fact as the answer: 19 gallons is 19 days; drain a water heater; doors that open outward | Generic scenes (fight in the meat aisle, shelter in a freezer, "decide the next aisle") without numbers or knowledge |
| Rules the person discovers and reuses, named in the story: "move when the bell rings", "they push, they can't pull", and at the end "anyone who tells you to stay put is leaving" | Rules exist only as limits for the AI, never discovered in the story |
| Recurring devices as clocks: Mr. Hale's knock at 3:40, the bell every 50 minutes, the morning announcements | None |
| A hidden truth planted from the first minute: the friendly voice on the speaker is checking where you are, not whether you are alive; clues in four places; revealed near the end | No secret at all; the cast cards' secrets are not used |
| Setups paid off: the V painted on the field, the plane that rocks its wings, the helicopter that lands on the V | Nothing is set up on purpose, so nothing pays off |
| Time compression: one scene per day or two ("Day 5: The Water Heater"), 40 to 60 seconds each, each ending on a turn ("You never told her you went.") | Fixed 15-minute steps, 350 to 400 words each, ending on "left or right" or a plain close |
| A closing inventory and an irony ("one flashlight, two cans of peaches, three rules") | An open end |

The cause is structural: our engine is a simulation that improvises one chapter at a time from the state. A film like this is authored: someone decided the secret, the problems, the rules and the ending first, and every scene serves them. The drama engine (health, tension targets, opposition) made the improvisation better; it cannot make it a designed story.

## 1. What will be built

### A. The story plan (`sim/architect.py`, table `sim_bible`)

One model step at setup (and on demand, also for a story already running, from its next chapter on) writes the plan in two calls:

1. **Bible** (`sm_bible`): `logline`; `pov` (second, first or third person) and a `voice` card (sentence length, tense, humor, how numbers are used); `secret` = the hidden truth, who holds it, the beat where it is revealed and the clues (beat and clue) that are planted before; `rules` = 2 to 4 named rules the person discovers, each with the beat where it is learned; `motifs` = recurring devices (a sound, a ritual, an object) with their first beat and the beats where they pay off; `facts` = real-world knowledge that solves or complicates a problem, each used in a beat; `ending` = outcome, final image, closing line.
2. **Beats** (`sm_beats`): N beats (N is the planned length, or 12), each with a label that carries the time ("Day 5: The Water Heater"), the event, the problem, the turn, the hook (how it ends), its purpose (setup, problem, solution, turn, clue, payoff, reveal, ending), a risky act for the dice (optional), and which clue, rule, motif and fact it carries. The beats must plant what the bible promises before it pays off.

The plan is stored apart from the world card, can be edited (any field, any beat), and is shown on a new **Plan** tab; the secret is hidden until the owner clicks "show the secret".

### B. The chapters play the beats

- **Plan step:** the planner gets a STORY PLAN block: logline, voice, this chapter's beat in full, the clues, rule, motif and fact it must carry, what must not be revealed yet, the next two beats in a line. The player's choice decides *how* the person handles the beat; the beat decides *what* happens. A plan that does not follow the beat is sent back (not on the last attempt).
- **Writer:** gets the voice card and point of view, the beat's turn and hook (end on it), and the rule not to reveal the secret before its beat. The chapter's story time and label come from the beat ("Day 5: The Water Heater").
- **Options:** become different ways to handle the next beat's problem (what to try, what it costs), not shopping menus.
- **Referee:** also checks that the chapter does not reveal the secret early and that it carries the beat's clue, rule or motif.
- **Re-plan:** when the owner writes their own action, or something big changes (a death, a broken rule), the beats after this chapter are written again from the story so far, keeping the secret and the ending. A button does it any time.
- **Without a plan nothing changes:** a story that has no plan (all older stories) runs exactly as before.

### C. Short scenes in a day-by-day film

- A built-in template **Day-by-day film**: second person, present tense, 12 chapters, about 160 words, story time in days; the voice and facts come from the plan.
- Chapter length may go down to 100 words.
- The chapter JSON for the later video step carries the beat label, the facts used and the closing line.

### D. Health reads the plan

Story health adds: which beats were hit (word overlap between the beat and the prose), whether the promised clues were planted before the reveal, whether the rules and motifs appeared where planned, and a plain verdict ("chapter 4 did not play its beat", "the clue for beat 9 was never planted").

## 2. What this does not do (stated plainly)

- It does not guarantee the quality of a hidden-twist story; the plan is written by the same model. The owner can read and edit the secret, the clues and every beat before the first chapter, which is where a human decides if the story is good.
- Real-world facts are the model's general knowledge and are marked as such; the owner checks them (a list on the Plan tab and in the export).
- It does not replace the simulation: stories without a plan, and the dice, things, health and drama features, all stay.

## 3. Build order

1. `sim/architect.py`: tables, models, prompts, bible and beats calls, revise, helpers (beat of a chapter, the block for a prompt, label and time).
2. Engine: plan, write, referee, archive use the beat; story time and title from the beat; re-plan step; seed part `bible`.
3. API and the Plan tab (phone checked); template **Day-by-day film**; settings (chapter words down to 100).
4. Health reads the plan; export carries the beat and facts.
5. Real-gateway run: the video's own premise as the idea, plan plus 4 chapters; read the plan and chapters against the video; tune.
6. Final walk against section 4.

## 4. Traceability: the video against the build

| In the video | Where | Test |
|---|---|---|
| One person, "you", present tense | A `pov` and `voice` in the bible; writer prompt; template | the writer prompt carries pov and voice |
| Numbered problems with facts as answers | A beats `problem` and `facts` | each beat has a problem; the planner prompt carries the fact |
| Discovered rules | A bible `rules` with their beat | the beat that carries a rule names it; health checks it appeared |
| Recurring devices | A bible `motifs` | motif listed in the beat; health checks it appeared |
| A hidden truth with clues and a late reveal | A bible `secret` with clues and reveal beat | writer prompt hides it before its beat; referee checks it; health checks the clues |
| Setups paid off | Clues and motif payoffs are beats in the plan | plan validation: every payoff beat comes after its setup beat |
| Day-by-day time compression and short scenes | Beat labels, 100-word chapters, the template | story time comes from the beat |
| Each scene ends on a turn | Beat `hook`; ending check (drama engine) | writer prompt carries the hook |
| A closing inventory and irony | Bible `ending` | the last beat carries the ending |
| Old stories keep working | No plan means no change | existing tests, plus one without a plan |

## 5. Definition of done

- Every row of section 4 has a test or a recorded real run.
- A real run with the video's own premise (a school, a zombie outbreak, a voice on the speaker) produces a plan with a secret, rules, motifs and 12 beats, and chapters that carry their beats; the result is compared with the video in `docs/RUN_LOG.md`, honestly, including what is still missing.
- The Plan tab works on a phone; the owner can edit any beat; re-plan keeps the secret and the ending.

## 6. Changes made while building

- Added after the first real runs: optional polish pass (`polish` setting, on in the film template), a filter for the model's own task talk, a stock-word check, a cast that fits the idea, and stricter backbone prompts (grounded secret, true facts, concrete problems). See `docs/RUN_LOG.md`.
- A re-plan keeps the plan's own last beat (a story of 12 beats stays 12 beats), and a plan written for a running story starts at its next chapter.
- Not built: choosing between several candidate secrets, an editor pass over the plan itself, and a verification of the facts. They are the next steps if the draft quality needs to go up.
