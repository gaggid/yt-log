# Tasks: things, finds, recipes and skills

Plan: [PLAN_discoveries.md](PLAN_discoveries.md). A task is ticked when it is built AND tested. Section numbers refer to the plan. Ticked = built and tested with the scripted model (`tests/test_sim_things*.py`); a task that needs the real gateway says so. D1 to D8 are built and tested with the scripted model; D9 and D10 need the real gateway and the final walk.

## D1 Data and rules in code (plan 4, 5.1, 5.4, 5.5)
- [x] D1.1 `sim/state.py`: thing props (condition, uses, size, tags), origin, `bound_to`; defaults for old states (a test loads an old chapter state)
- [x] D1.2 `state["world_add"]` and `state["recipes"]`; `reconcile` keeps them; `describe` groups things by holder with carrying space
- [x] D1.3 Entity `skills` and `carry`; story setting `carry_limit`; learned skills in `state["entities"]`
- [x] D1.4 `apply_ops`: `discover`, changed `item_add`, `craft`, `item_give`, `item_take`, `item_use`, `item_change`, `skill_learn`; every refusal has a reason; caps (2 finds, 2 makes, 1 skill per chapter)
- [x] D1.5 Bound items cannot move except by a fired instruction; carry limit blocks add, give and take
- [x] D1.6 Tests: one accepted and one refused case per operation; a find is unknown to a branch that did not make it

## D2 Dice for making and finding (plan 5.3)
- [x] D2.1 `sim/dice.py`: skill +2, improvised +2 target, tool +1, known recipe one step easier, damaged tool -1; cap stays at ±6
- [x] D2.2 Tier results for makes and finds: great, success, partial (crude or at a price), fail (half the parts, tools kept), disaster (cost required)
- [x] D2.3 Dice off: every make and find succeeds
- [x] D2.4 Tests per tier and for the modifiers

## D3 Planner and delta contract (plan 5.2, 6)
- [x] D3.1 `RiskIn` gets `kind` and `craft {makes, parts, tools, skill, reasoning}`; plan prompt updated; `reasoning` stored on the chapter and shown
- [x] D3.2 Delta prompt lists the new operations and the dice contract; ops are allowed only against the matching resolved act
- [x] D3.3 Packet sections `RECIPES` and `FOUND LATELY` (low priority, dropped whole); person cards show skills and carry
- [x] D3.4 `sim/think.py`: `sm_plan` and `sm_delta` step up one level when the plan holds a make or search act
- [x] D3.5 Tests with the fake model: an invented make is accepted on parts, tools and roll and refused otherwise; the budget step-up shows in the request

## D4 Seed and templates (plan 6.5)
- [x] D4.1 World card field `craft` (seeded, editable); rule group `craft` in store, seed and UI
- [x] D4.2 `sm_cast` writes 2 to 4 skills per character; seed validation keeps them plain phrases
- [x] D4.3 Templates carry craft text, craft rules and a carry limit; courtroom and survival templates differ

## D5 Referee and archive (plan 6.2)
- [x] D5.1 Referee checks: thing used but not held, wrong condition shown, thing in prose but not in state or world
- [x] D5.2 Archive records a fact for each find, make and recipe; options may use what people carry
- [x] D5.3 Tests

## D6 Give, take, persuade, bind (plan 5.4, 7.4)
- [x] D6.1 Risk kinds `persuade` and `take` with trust, tension and awareness as modifiers
- [x] D6.2 Directive kinds `grant`, `take`, `unbind`; fire once per line like other instructions
- [x] D6.3 Tests: refused give, successful theft with a relation change, bound item, lifted bind

## D7 API and UI (plan 7, 8)
- [x] D7.1 API: things list and edit, bind, undo of one operation (as a sibling chapter), recipes and skills edit, grant instruction
- [x] D7.2 `static/sim.js`: chips on chapters, "Why this works", state panel by holder with carrying bar, Things tab, "+ Give a thing" in the dock, skills and carry on cast cards, thing properties in the items editor, craft rules group
- [x] D7.3 Help text and tooltips updated
- [x] D7.4 Phone check in headless Edge at 390 px on library, story, Things, setup: no sideways overflow, controls 40 px
- [x] D7.5 Browser smoke test: no console errors

## D8 Export, import, storage (plan 10)
- [x] D8.1 Setup export, chapter JSON, story file import and duplicate carry the new fields; old files import with empty values
- [x] D8.2 `as_template` keeps craft text and rules, not story things
- [x] D8.3 Tests

## D9 Real gateway (plan 14)
- [x] D9.1 Supermarket and courtroom stories, three chapters each, with at least one find and one make (no refused give came up on the real model; covered by tests)
- [x] D9.2 Record dropped-operation rate and seconds per stage against the earlier runs in `docs/RUN_LOG.md`; tune prompts if more than a quarter of proposed operations are refused
- [x] D9.3 The owner's own live story was read and audited (3 chapters, run by the owner); prompts and dice fixed from it

## D10 Final walk (plan 15, 16)
- [x] D10.1 Walk every row of plan section 15 and tick it with its test or run
- [x] D10.2 Genre-word grep, "no unfound thing in any prompt" test, old-state test
- [x] D10.3 `CLAUDE.md` paragraph, `docs/PLAN_simulation.md` section 23 note, tasks ticked
- [ ] D10.4 Commit and push

## Later (not in this build, plan section 12)
- New people arriving mid-story
- Painted key things
- Shops and prices
- Spoilage and time-limited things
- Currency, reputation and faction templates
