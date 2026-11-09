# Plan: things, finds, recipes and skills in the story simulator

Status: PLAN ONLY, nothing is built. Builds on [PLAN_simulation.md](PLAN_simulation.md) (the engine) and [PLAN_simulation.md section 23](PLAN_simulation.md) (what changed while building). Tasks: [TASKS_discoveries.md](TASKS_discoveries.md).

## 0. What the owner asked for

1. Things **discovered during the story** are stored, stay in notice from then on, and characters can **use, drop or give** them, as the story demands.
2. Characters can **make, craft or do** things that nobody listed in advance. What is possible comes from the **thinking of the AI model**, not from a fixed list.
3. "And much more": the owner asked what else belongs here. Section 12 lists it; section 13 says what is in this build and what is later.
4. Use the model's **thinking** (already on in the gateway; section 8).
5. Same rules as the first build: a plan saved before building, traceability against the brief, no partial build, no leaks. Mobile friendly, English only, any genre (nothing here may assume a supermarket or a zombie).

## 1. What exists today (verified in the code)

- Items live in an `items` tracker: `{name: {qty, at, note}}`, `at` is a person or a place. Operations: `item_add`, `item_remove`, `item_move`.
- `item_add` is accepted only from a known place that holds the thing (word match against the world card's "exists" text) or from parts used up in the same step (`crafted`). Everything else is dropped with a reason and shown on the chapter. This is the right guard against "a rocket launcher from nowhere".
- Giving and dropping are `item_move` to a person or a place. They always succeed.
- The planner lists 0 to 3 risky acts with `stats` and `items`; dice (code) decide; the delta step must make a fail cost something.
- People have role, goal, fear, secret, voice, look, relations. No skills, no carrying limit.
- The model's thinking is on by default and is budgeted per task (`sim/think.py`).

## 2. The gaps this plan closes

| # | Gap | Today's effect |
|---|-----|----------------|
| G1 | A thing found in the story but not in the world card's text is refused | An honest discovery (a flare gun in a locker) is lost |
| G2 | Items are only name, quantity, holder | No condition, no uses left, no size, no history, no "why it matters" |
| G3 | No notion of making something new except "parts used up" | The model's inventiveness ("rig an alarm from a bell and rope") is either refused or unchecked |
| G4 | Give, drop, take always succeed, and nobody can refuse | No trade, theft, refusal or demand |
| G5 | No skills | A cashier and a guard have the same chance at picking a lock |
| G6 | No carrying limit | Everyone holds everything |
| G7 | Planner and writer see one flat item list | "Who has the crowbar" is easy to lose; nothing shows where an item came from |
| G8 | No place to see everything found, made and known | The owner cannot review or fix the story's things |
| G9 | Owner demands about things ("Dev never gives up the keys") exist only as free-text rules | Only the referee can catch a breach, after the fact |

## 3. Design principles

1. **The model reasons, the code decides what is real.** The model proposes a find, a make or a give with its reasoning; code checks parts, tools, skill, place, holder and the dice before the state changes. This is the same split as the rest of the simulator.
2. **A thing enters the world only through an act that earned it.** A find needs a roll (or a fired instruction, or text already in the world card). A make needs parts that exist and are used up. Nothing appears because the prose liked the idea.
3. **Everything is data in the story's state.** State is stored per chapter, so branches, rewrites, rerolls and undo stay correct with no extra work. No new tables are needed for the state itself.
4. **Genre-free.** A "thing" is anything the story tracks: a tool, a document, a witness statement, a company asset, a spell component. The world card sets what making and finding mean in this world (section 6.5).
5. **The owner can see and change everything**, before and during the story, on a phone too.
6. **Bounded.** At most two finds and two makes per chapter (code), so the story cannot be inflated by the model.

## 4. Data model

All of it lives inside the existing JSON; no schema migration. Old chapters read as if the new fields were empty.

### 4.1 A thing (extends the entry in the `items` tracker state)

```
name: { qty, at, note,
        props:  { condition: "new|worn|damaged|crude|broken", uses: int|null, size: int (default 1), tags: [..] },
        origin: { how: "start|found|made|given|taken", chapter: idx, by: name, where: place, parts: [..] },
        bound_to: name|"" }            # the owner's rule: this thing never leaves this person (section 7.4)
```

`uses: null` means it does not wear out. Size counts against the carrying limit. `bound_to` is set only by the owner or by a fired instruction.

### 4.2 Finds the world has grown

`state["world_add"]`: a list of `{kind: item|place|clue, name, text, where, chapter, by}`. Each entry is added to what "exists" for this line of the story, so a later chapter may refer to it without the guard in section 1 refusing it. The world card itself is never edited by the model (the owner owns it).

### 4.3 Recipes

`state["recipes"]`: `{name: {makes, needs: [items], tools: [items], skill, note, learned_by: [names], chapter}}`. A recipe is stored the first time something is made successfully, or when a person learns it (a book, a teacher, an instruction). Known recipes are shown to the planner, so the story reuses a craft instead of reinventing it, and a known recipe makes the act easier (section 5.3).

### 4.4 Skills

Characters get `skills` (a short list of plain phrases, for example "locks", "first aid", "bookkeeping"), written by the cast seed and editable. Learned skills live in `state["entities"][name]["skills"]` (a person can learn or lose one). Skills feed the dice (section 5.3) and are shown on the person card.

### 4.5 Carrying limit

Entity field `carry` (default from the story setting `carry_limit`, 8 size units; 0 = no limit). A person holding more than the limit cannot take or receive anything until they drop something.

## 5. Behaviour

### 5.1 New and changed operations (delta step)

| Op | Fields | Code checks |
|----|--------|-------------|
| `discover` | target, kind (item, place, clue, recipe), where, text, why | a resolved act of kind `search` by someone at `where` with tier success or better (partial = found with a price: damaged, or noise, or a clock tick), OR a fired instruction names it, OR the text already stands in the world card or `world_add`. Otherwise dropped with the reason. Max 2 per chapter |
| `item_add` (changed) | adds `props`, `origin` | as today, plus the same checks as `discover` when the thing is new to the world |
| `craft` | target, qty, parts, tools, by, recipe, why | `by` alive and at the place; every part held by `by` or lying at the place and used up (removed in the same step); every tool present and NOT used up; the resolved act's tier decides the result (5.3). Max 2 per chapter |
| `item_give` | target, qty, from, to | giver holds it; both in the same place; not `bound_to` someone else; receiver under the carry limit; consent (5.4) |
| `item_take` | target, from, by | the act of kind `take` succeeded (theft, force, persuasion); not `bound_to` |
| `item_use` | target, by, why | thing held by `by`; `uses` goes down by 1; at 0 it becomes `broken` (kept, but cannot be used) or removed if the recipe says it is consumed |
| `item_change` | target, condition, note | condition from the fixed list; used for repair, damage |
| `skill_learn` | who, skill, why | from a teacher, a book (item) or a fired instruction; max 1 per chapter |
| `item_move` | unchanged | still used for dropping (to a place) |

Every refusal is kept in `chapter.delta.dropped` with a reason, exactly as today, and shown on the page.

### 5.2 The planner's risk grows two fields

`risks[]` gains `kind` (`search`, `make`, `use`, `persuade`, `take`, `fight`, `move`, `other`) and, for `make`, a `craft` object `{makes, parts, tools, skill, reasoning}`. The planner (thinking on) works out in one or two sentences why the thing is possible with what the person holds and knows ("`reasoning`"); that sentence is stored on the chapter and shown under "Why this works". If it cannot be made from what is there, the planner is told to choose another act. The dice then decide, as for every risk.

### 5.3 Dice for making and finding

Same d20, same difficulty shift. Modifier contributions are added to the existing ones (still capped at ±6):

- a matching skill: +2; no matching skill: the act is "improvised" and the target rises by 2
- the right tool present: +1 (items already count up to +3)
- a known recipe: the act is one step easier (hard to normal, normal to easy)
- a damaged or crude tool: -1

Results: great = a better thing (more uses, "well made"); success = as planned; partial = made but crude (1 use, or a flaw noted) or found at a price; fail = nothing made, half the parts lost (rounded down, at least one), the tools kept; disaster = parts lost, and the delta must add a real cost (injury, noise, a clock tick). Dice off: everything succeeds, as today.

### 5.4 Giving, trading, taking, refusing

- A give to someone who wants it, or who trusts the giver (relation trust 0 or higher, or no relation tracker), simply works.
- A give that the receiver might refuse (trust below 0, tension 3 or more, or the receiver has a goal against it) is planned as a `persuade` risk and rolled.
- A `take` (theft, force, a demand) is a risk with the victim's awareness and tension as modifiers; on success it moves the thing and may change the relation; on failure the relation worsens.
- An item with `bound_to` (the owner's rule) cannot be moved by anyone else; only a fired instruction or the owner can lift it.
- Dropping to a place always works and is cheap; the thing stays at that place where anyone present can find it again (it is listed under the place).

### 5.5 Hidden things and leaks

A thing found in a place the people have not been to is not in the state until found. The packet never lists unfound things; the world card's "exists" text is the owner's own and is shown as before. Hidden knowledge (secrets) is already tracked per person.

## 6. What the model sees and writes

### 6.1 State and people

The state block groups things by holder: `Ravi carries (4/8): Crowbar (worn), Rope x2 (frayed, 1 use), ...`; places list what lies there. Each person card shows skills and carrying space. Recipes known and recent finds get their own short packet sections (`RECIPES`, `FOUND LATELY`), dropped before rules and state when over budget.

### 6.2 Prompts

- `sm_plan`: knows the new risk fields and the rule that a make must be possible from what the person holds, uses and knows; `kind` per act; a persuade or take act when a give or demand could be refused.
- `sm_delta`: lists the new operations and the dice contract (a make or a find only if the matching roll was success or better, partial at a price).
- `sm_write`: shows finds, makes, gives and refusals truthfully, uses the thing's condition ("crude", "frayed") in the prose.
- `sm_referee`: new continuity checks: a thing used that is not held by the person; a thing shown with a different condition than the state; a thing appearing in the prose that is not in the state or the world card.
- `sm_archive`: records a durable fact for a find, a make and a recipe; options may use what people now carry.
- `sm_cast`: writes `skills` (2 to 4 per character) and optionally `carry`.
- A `craft` rule group (section 7.1) is sent to plan, delta and referee.

### 6.3 Thinking

Planning a make or a find is exactly where thinking pays. Budgets in `sim/think.py`: `sm_plan` and `sm_delta` rise one step when the plan contains a `make` or `search` act (decided in code before the delta call). The plan's `reasoning` field is the visible result of that thinking. The gateway's `reasoning_content` itself is not stored (it can be large); only the short `reasoning` sentence is.

### 6.4 Chapter limits and room

Reply limits already allow 16000 tokens and a retry without thinking, so the extra fields do not risk a cut-off.

### 6.5 What making and finding mean in this world

The world card gets one more optional field, `craft` ("what can be made here, and what cannot: for example 'makeshift tools only, no electronics' or 'magic needs a sworn oath'"), seeded by the AI and editable. It is shown to plan, delta and referee as a hard-ish rule. A template can pre-fill it (a heist story and a fantasy story differ).

## 7. Owner control

1. **Rules.** New rule group `craft` ("Making and finding") in the rules list; the AI proposes some at setup. The referee checks them like any rule.
2. **Setup.** Cast editor gets skills and carrying space; the items tracker editor gets the new properties per thing (condition, uses, size, bound to).
3. **During the story.** A new **Things** tab (section 8) edits every thing, recipe and skill, with the same "changes apply from the next chapter" note as Setup.
4. **Demands.** "Dev never gives up the keys" becomes `bound_to: Dev` on the keys, which code enforces and the referee also checks in prose. A fired instruction of kind `grant`, `take` or `unbind` (new directive kinds) can give a thing, take a thing, or lift a bind at a chosen time.
5. **Undo.** Every find, make, give and take is an operation on the chapter's delta. The Things tab shows them with the chapter they came from; "Undo this" re-applies that chapter's delta without the operation as a sibling (the existing branch mechanism), never rewriting old chapters.

## 8. UI (phone first, like the rest of the page)

- **Story tab, chapter card:** chips for what happened to things: found, made, gave, took, used up, broken; refusals under "What changed". "Why this works" line when the plan had `reasoning`.
- **State panel:** things grouped by holder with a small bar for carrying space; recent finds first.
- **Things tab** (new, between Story and Setup): sections People's things, Places' things, Recipes, Skills, Found so far (with chapter and finder). Edit, add, remove, bind, undo. Single column under 640 px, 40 px controls.
- **Dock:** "+ Give a thing" (a grant instruction, with picker for who and what) beside "+ Add instruction".
- **Setup:** skills and carry on the cast cards; craft rules in the rules list; the world's `craft` field.
- **Help text** ("How this page works") and the setup tooltips are updated in the same step.

## 9. Pictures

Optional and last: a key thing (marked by the owner or by the model as "important") may get one reference painting like a person, with the same style constants, reused in panels where it appears. Not needed for the core; section 13.

## 10. Export, import, templates

Things, recipes, skills, bound items and world additions are part of the setup export and the chapter JSON (they are the state). Import remaps ids as today. `as_template` keeps the `craft` text and rule group but not story-specific things. Old exports import with empty values.

## 11. Leakage and safety checks

- Nothing in the code names a genre; a test greps `sim/` for genre words as today and a courtroom story crafts a "forged letter" and finds a "witness statement" on the same code.
- A find or make never edits the world card; additions live per line in state, so a branch that did not find it does not know it.
- Hidden things are never in a prompt before they are found.
- Owner text (bound reasons, notes, craft text) is fenced `<owner>` like all owner text.
- Per-chapter caps stop inflation; the referee flags prose that shows a thing the state lacks.
- Undo and rewrite create siblings; old chapters are never edited.

## 12. Everything we could add (from the owner's "and much more")

| Idea | In this build? | Where |
|------|----------------|-------|
| Discoveries stored and in notice | yes | 4.2, 5.1 |
| Use, drop, give, take, refuse, trade | yes | 5.4 |
| Craft and improvise from the model's reasoning | yes | 5.2, 5.3 |
| Recipes remembered | yes | 4.3 |
| Skills and learning | yes | 4.4, `skill_learn` |
| Item condition, uses, size, origin | yes | 4.1 |
| Carrying limit | yes | 4.5 |
| Per-person inventory view | yes | 6.1, 8 |
| Owner demands and bound items | yes | 7.4 |
| Things tab with undo | yes | 7.5, 8 |
| Clues and documents as things that teach knowledge | yes, small: a clue-kind find can carry a secret name and `learn` fires when it is read | 4.2 |
| Discovered places and exits (the map reveals itself) | yes, small: `discover` kind place adds a place to the story's reachable places | 4.2 |
| Currency, reputation, factions | templates only: meters and relations already do it; one new template each | later |
| New people arriving (a stranger joins) | later, own plan: needs a cast entry, a reference painting and relation trackers | 13 |
| Painting key things | later | 9 |
| Trading prices and shops | later: needs a currency convention | 13 |
| Time-limited things (food spoils, batteries drain) | later: `uses` over time, tied to the clock | 13 |

## 13. Decisions for the owner

1. **Dice for finds.** Recommended: a find that is not already in the world card needs a successful search roll (as planned above). Alternative: let the model discover freely at the planner's choice, capped at two per chapter (more surprising, less honest to the dice).
2. **Default carrying limit.** Recommended 8 size units, 0 (none) for stories like a courtroom. The template can set it.
3. **Skills.** Recommended: seeded 2 to 4 per character and used in dice. Alternative: no skills, the model decides who is good at what from the role (simpler, less checkable).
4. **Order of work.** Recommended order is in section 14. New people, shops and spoilage are not in this build.

## 14. Build order

1. D1 data and rules in code (state, ops, caps, carry, bound, refusals) with the scripted model.
2. D2 dice for making and finding (skill, tool, recipe, tiers, partial and fail costs).
3. D3 planner and delta contract (risk fields, `reasoning`, packet sections, thinking step-up).
4. D4 seed (skills, carry, craft field and rules) and templates.
5. D5 referee and archive checks.
6. D6 give, take, persuade and bind, with directives `grant`, `take`, `unbind`.
7. D7 API and Things tab, chips, state panel, dock, setup fields, help (phone checked in headless Edge at 390 px).
8. D8 export, import, template, storage page.
9. D9 real-gateway runs: a supermarket story and a courtroom story, three chapters each, with at least one find, one make and one refused give, recorded in `docs/RUN_LOG.md`.
10. D10 final walk against section 15.

## 15. Traceability: the brief against this plan

| The owner said | Where it is met | How it is tested |
|----------------|-----------------|------------------|
| "variables discovered during the story be stored so they remain in notice" | 4.2 `world_add`, 5.1 `discover`, 6.1 `FOUND LATELY`, 8 Things tab | find survives to chapter 3, shown in the packet; a branch that did not find it does not know it |
| "characters can use" | `item_use`, `uses`, `condition` | uses go down and a spent thing cannot be used |
| "drop" | `item_move` to a place, 5.4 | dropped thing lies at the place and can be found again |
| "give" | `item_give`, 5.4 | give works, is refused when bound or when trust is low, respects carry |
| "per story demands" | 7.1 rules, 7.4 `bound_to`, directives `grant` `take` `unbind` | bound item refuses a move; a fired instruction lifts it |
| "characters can make, craft or do certain things which can only come from the AI model's thinking" | 5.2 `craft.reasoning`, 5.3, 6.3 | fake model proposes an invented make, code accepts or refuses on parts, tools, skill and roll |
| "use Thinking from the AI model" | 6.3 and `sim/think.py` | budget step-up asserted in a request test; real run in D9 |
| "what else could be there" | section 12 | each yes row has a task |
| "any other story, not only zombies" | 3.4, 6.5, 11 | courtroom test on the same code |
| "mobile friendly" (latest instruction) | 8 | headless Edge at 390 px: no overflow, 40 px targets |
| "plan saved first, traceable, no partial build, no leaks" | this file, [TASKS_discoveries.md](TASKS_discoveries.md), section 11 and 16 | final walk D10 |

## 16. Definition of done

- Every row of section 15 has a test or a recorded real run.
- Every operation in 5.1 has an accepted case and at least one refused case in tests.
- Old stories open and run unchanged (a test loads a chapter state without the new fields).
- The Things tab works on a phone, and the help text matches the page.
- Real-gateway runs for two unlike stories are logged, including the dropped-operation rate and the seconds per stage compared with the earlier runs.
- No genre words in `sim/` code (the existing grep test), no prompt contains an unfound thing, and `CLAUDE.md` describes the new behaviour in one paragraph.

## 17. Risks

| Risk | Answer |
|------|--------|
| The model invents things to please the owner | caps per chapter, roll or instruction needed, refusals shown |
| Too many refusals make chapters feel stiff | the planner is told the allowed finds and makes up front; the dropped-op rate is measured in D9 and the prompt tuned |
| Longer plan and delta calls | thinking is stepped up only for chapters with a make or a search; replies already have room |
| Carrying limits annoy | default is generous, 0 turns it off, template-level choice |
| Prompt grows | recipes and finds are low-priority packet parts, dropped whole before state and rules |
| Craft rules differ per world | `craft` field and rule group, seeded and editable |

## 18. Changes made while building (the plan above is kept as written; these are the differences)

- **Where the carrying limit lives.** Story setting `carry_limit` (default 8; templates set 0 for courtroom, mystery, business, drama) and a per-person `carry` field on the cast card. Existing stories get the default of 8 when they next run.
- **A find goes to the finder.** A thing found by a person lands in their hands unless a holder is named or they cannot carry it, in which case it stays at the place (section 5.1 said "at the place" only).
- **Thinking step-up trigger.** Only the player's action decides it (words such as make, build, search, find, repair, learn in the action text), not the previous chapter's plan, so budgets stay predictable. Plan and delta get 1.5 times their budget (`think.boost`).
- **Owner edits and undo act on the chapter's state in place**, the same way the earlier "apply my edit" does: undo changes the state of the chapter that made the change and marks later chapters as written before it. They are not new sibling chapters (section 7.5 said sibling).
- **Undo data** is stored on each applied change (`applied[].undo`), as small actions of the same `things.edit` function the Things tab uses.
- **Instructions that move things** keep their data (`item`, `to`, `qty`) inside the instruction's timing object, so no database change was needed.
- **Dice kinds.** Acts have the kinds `search, make, use, persuade, take, fight, move, learn, other`; only the first, second, fourth, fifth and eighth change what the code allows.
- **Not built (section 12, "later")**: new people arriving, painted key things, shops and prices, spoilage over time, currency and reputation templates.
