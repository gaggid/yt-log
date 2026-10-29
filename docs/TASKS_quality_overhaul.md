# Quality overhaul: task list (living tracker)

Created 2026-10-29 from [AUDIT_2026-10-29.md](AUDIT_2026-10-29.md). Build started 2026-10-29 on the owner's go. Update this file as work proceeds: it is the single place that shows what is done. Read the "Build summary" at the bottom first.

## How to use this file

- Status marks: `[ ]` not started, `[~]` in progress, `[x]` done and verified, `[!]` blocked (say why on the task).
- When a task is finished: tick it, add one line to the **Progress log** at the bottom (date, task id, commit, measured result), and update the milestone status table.
- One task is one small batch: build, test with the fake gateway (`tests/fakellm.py`), run the tests of the area changed (not the whole suite), connect to the plan screen where it has a visible step, commit. Run the full suite (about 5 minutes) once at the end of each milestone.
- Never restart the app while a job runs. Python changes need a restart; `static/plan.js` does not.
- Rules that every task keeps (from `CLAUDE.md` and `docs/APP_GUIDE.md`): no source, author, book or quote reaches narration, pictures, screens or prompts (leak gate); canonical scene is the source of truth; `editorial.content_hash` excludes derived data (changing it needs a migration and re-export, avoid); new planned fields must reach the scene, the prompt and the consumer; auto-run (`story3/auto.py STAGES`) and the screen step order (`static/plan.js`) stay in step; validators accept their last attempt (`JsonCaller.last_attempt`) but the new quality gates in M8 are the exception and stop auto-run.
- Documentation: each milestone ends by updating `docs/APP_GUIDE.md` (invariants and step list) and `docs/RUN_LOG.md`.

## Decisions in force (owner, 2026-10-29)

1. Material Pack may use paraphrased facts from the source passages (no wording, author or source carried into the video).
2. A credit line may appear in the video **description** only.
3. Private victims and not-yet-convicted suspects: role names or invented names by default; confirmed public figures follow `story3/likeness.py`.
4. Graphic reconstruction: implied only, never the act.
5. Playback speed stays a plan setting (default 1.25x) and dead air is trimmed first.
6. Series look: fixed thumbnail frame and logo; palette, music and structure vary per story.
7. **No human review step.** Every gate is automatic. Auto-run never uploads.
Items 2 to 6 were assumed from "yes we can" and can be corrected by the owner at any time.

## Milestones at a glance

| Milestone | Purpose | Tasks | Depends on | Status |
|---|---|---|---|---|
| M0 Foundations | Measure first: audit tool (with viewer-simulation curves), bench, sampling settings, versioning | 0.1 to 0.6 | none | **built (0.5 fakes done with the last tasks)** |
| M1 Defects | Fix confirmed bugs and quick wins | 1.1 to 1.10 | 0.3 (for 1.5 only) | **built and tested** |
| M2 Material, narration and viewer experience | Real story material, experience design, turn schedule, audience language profiles, three-pass Hinglish narration, automatic Hindi gate | 2.1 to 2.17 | 0.1, 0.3, 0.4 | **built; 2.13 partly run on the real model (1 of 3 stories)** |
| M3 Visual story engine and world | Events, places, a big varied world, regional and era accuracy, evidence cards, characters, director and storyboard v2 | 3.1 to 3.16 | M2 (2.1) | **built except 3.4 slim schema and 3.7 (GPU)** |
| M4 Image prompts and picture QA | Prompt v2, judge v2, duplicate detection | 4.1 to 4.7 | 3.4 | **built except 4.3 (GPU)** |
| M5 Video and sound | Pace, motion, sound bed, captions, structure, progress devices | 5.1 to 5.9 | 3.5, 1.8, 1.9 | **built; 5.5, 5.7, 5.9 partly** |
| M6 Packaging | Titles, thumbnails (text by code), metadata, subtitles, claim check, persona-aware packaging | 6.1 to 6.7 | 2.1, 4.4 | **built; 6.2 and 6.7 partly** |
| M7 Selection and story types | Phase 1 scoring incl. region fit, type grammars, anti-template engine | 7.1 to 7.7 | 2.1 | **part built: 7.1, 7.2, 7.7 partly; 7.5 and 7.6 built; 7.3 and 7.4 not** |
| M8 Automatic gates | Judges, persona panel, viewer-simulation gate, cultural gate, calibration, auto-run thresholds, safety gate | 8.1 to 8.9 | M2 to M6 | **built except 8.2 (needs real films) and 8.4; 8.6 partly** |
| M9 Later | Shorts, analytics loop, English track, channel | 9.1 to 9.4 | M8 | **not started (as planned)** |

**Build order.** M0 first (everything after it is measured against it), then M1 (small, safe wins; also gives a visible before/after), then M2, M3, M4 in that order (each needs the one before), M5 and M6 can run in parallel with M3/M4 where marked, M7 and M8 after, M9 last.

**Milestone exit test (bench).** Run the bench (task 0.2) and the audit (task 0.1) and compare with the baseline numbers in `AUDIT_2026-10-29.md` section 8. Targets per milestone are listed under each milestone heading.

---

## M0 Foundations

Exit: `python -m story2.audit <plan>` prints the scorecard of section 8; the bench runs three stories with fake or real models; every chat call can have its own sampling settings; a pipeline version flags old work.

### [x] 0.1 Audit scorecard tool
- **Goal:** turn the audit's throwaway scripts into a permanent tool so every change is measured.
- **Do:** create `story2/audit.py` with one function per metric group (material, narration, world, pace, prompts, characters, pictures, video, packaging, safety) returning numbers plus pass/fail against targets in a `TARGETS` dict. Port the scripts used in the audit (questions share, stock phrase count, distinct places, top-place share, person-in-scene share, protagonist share, mean and max scene seconds, identical-sentence share of prompts, negation phrases per prompt, crowd/quiet contradictions, `style == "style"` count, voice silence share via ffmpeg `silencedetect`, loudness via `ebur128`). Entry points: `python -m story2.audit pl-xxxx [--json]`, `GET /api/plans/{id}/audit`, and an "Audit" card on the plan screen (`static/plan.js`) showing red/amber/green per metric. Extend, do not replace, `story2/narration_audit.py`.
- **Files:** `story2/audit.py` (new), `story2/api.py`, `static/plan.js`, `static/index.html` if needed.
- **Tests:** `tests/test_audit.py` with a fake plan: each metric computed on a hand-built plan with known answers.
- **Done when:** running it on `pl-0b7cead5` reproduces the audit numbers (15% questions, 6 places, 12 scenes over 12 s, 56% identical prompt share).
- **Depends:** none. **Est.:** M.

### [x] 0.2 Bench of three frozen stories
- **Goal:** compare before and after on the same inputs.
- **Do:** add `tools/bench.py` (or `story2/bench.py`) that takes three candidate ids (the fugitive article `S-4a5dbc-001`, the Surat network `S-4ac1ce-002`, the dark-matter `S-545aee-001`), creates a fresh plan for each, and runs stages up to a chosen point (`--until blueprint|narration|storyboard|prompts|pictures`) with the real gateway or a fake one (`--fake`). Save a snapshot of each stage's output under `data/bench/<run-name>/` and print the audit scorecard side by side with the previous run. Include a baseline run taken before any change (run-name `baseline-2026-10-29`) using the existing plans' stored output (no GPU needed for the baseline: read the stored plans).
- **Files:** `story2/bench.py` (new), `tests/test_bench.py`.
- **Done when:** `python -m story2.bench --baseline` prints the baseline table; `--until storyboard` runs on the fake gateway in tests.
- **Depends:** 0.1. **Est.:** M.

### [x] 0.3 Per-task sampling settings
- **Goal:** stop writing prose at temperature 0.2.
- **Do:** (1) probe the gateway for supported sampling fields (`top_p`, `frequency_penalty`, `presence_penalty`, `seed`) with a one-token request each and record the answer in `connection_test` output; (2) give `ChatBackend.complete` and `JsonCaller.call` an optional `params` argument (`temperature`, `top_p`, penalties) merged into the payload; (3) add a `SAMPLING` table in `story/settings.py` keyed by task name (`p2_blueprint` 0.5, `p2_narrate_draft` 0.8, `p2_narrate_edit` 0.4, `p2_narrate_tag` 0.1, `p2_registry` 0.4, `p2_director` 0.5, `p2_scenes` 0.6, `p2_voice_tags` 0.2, `p2_thumbnail` 0.8, material 0.3, judges 0.1) with a settings override and a screen field; (4) unknown fields are dropped silently when the probe says unsupported.
- **Files:** `story/llm.py`, `story/settings.py`, `story/api.py`, `static/index.html` (settings page), the callers in `story2/*`.
- **Tests:** payload contains the task's temperature; unsupported fields are not sent; default behaviour unchanged for tasks without an entry.
- **Done when:** a narration call logs temperature 0.8 and the settings page shows the table.
- **Depends:** none. **Est.:** S.

### [x] 0.4 Pipeline version and "made with older pipeline" flag
- **Goal:** changes in prompts and structure must flag old work, as `DIRECTION` does for looks.
- **Do:** add `PIPELINE = "q2"` in a new `story2/version.py`; store `plan.settings.pipeline` when a plan is made and at each stage (`narration_pipeline`, `storyboard_pipeline`); `plans_api.style_info` style flags gain "made with an older pipeline" with a button that redoes the stage; bump `styles.DIRECTION` to `illustrated-3` when M3 lands (task 3.4), not before. New fields (material, events, places) live in `plan.settings`/scene `data` outside `editorial.content_hash`; add a unit test that the content hash of a stored plan is unchanged by adding them.
- **Files:** `story2/version.py` (new), `story2/api.py`, `static/plan.js`, `tests/test_editorial.py` additions.
- **Done when:** an old plan shows the flag, a new plan does not; content hash test passes.
- **Depends:** none. **Est.:** S.

### [x] 0.5 Test doubles for new calls
- **Goal:** every new model call has a fake in `tests/fakellm.py` keyed by `[TASK:name]`.
- **Do:** add fake replies for `p2_material`, `p2_narrate_draft`, `p2_narrate_edit`, `p2_narrate_tag`, `p2_events`, `p2_judge_*`, `p2_title`, `p2_backtranslate` as each task lands (this task is the checklist; tick when all exist).
- **Depends:** each new call. **Est.:** S per call.

### [x] 0.6 Viewer-simulation metrics (the "boredom map")
- **Goal:** measure, per 30 seconds, what a viewer gets, so retention risk is visible before publishing (audit section 14.1).
- **Do:** add to `story2/audit.py` a `viewer` group and a function `boredom_map(plan_id)` returning per-30 s windows with: new-word share (content words in narration not yet spoken, stop-words removed, Devanagari and Latin tokens), new place-or-subject scenes, scenes longer than 8 s, rhetorical questions without an answer within 60 s, longest run of the same place, longest run with the same protagonist on screen, and a risk flag when new-word share is under 40% for two windows, or no new place/subject for two windows, or a scene over 10 s. Output a table, a sparkline, and a list of predicted drop windows; show it as a strip under the journey bar on the plan screen. Port the script used in the audit.
- **Files:** `story2/audit.py`, `story2/api.py`, `static/plan.js`.
- **Tests:** hand-built plan with a known repetition stretch flags exactly that window.
- **Done when:** on `pl-0b7cead5` it flags the windows near 0:30, 3:30 to 4:30 and 6:30, matching section 14.1. **Depends:** 0.1. **Est.:** S.

---

## M1 Defects and quick wins

Exit: audit shows zero `style == "style"`, zero crowd/quiet contradictions, last spoken line is Hindi, voice silence share at most 15%, video loudness within 1 LU of -14 LUFS, thumbnail shows the right protagonist. Run the full suite once at the end.

### [x] 1.1 Do not append the English `next_hook`
- **Do:** in `story2/planner.py` (the `NEXT VIDEO HOOK` clause near line 321) only add it when `bp.next_hook` is non-empty **and** `bp.series_placement` names a real next story; ask for it in Hinglish; make the closing rule "answer the opening question, end on an image, then a comment question". Change `BLUEPRINT` so `next_hook` is empty unless the source gives a real second story (Phase 1 sibling candidate of the same project).
- **Tests:** narration prompt contains no English hook by default; when present it is written in Hinglish (check script mix); `test_planner`.
- **Done when:** the last sentence of a new film is Hindi and closes the loop. **Est.:** S.

### [x] 1.2 Remove contradictory "bystanders" line
- **Do:** in `story2/imgprompts.py` where `_PUBLIC_RX` adds "Background populated with bystanders...", add it only when the scene's atmosphere or `exclusions` do not contain `crowd`, `empty`, `quiet`, `deserted`, `still`, `alone`; for those scenes add a positive phrase instead ("an almost empty lane with two distant figures").
- **Tests:** prompt for a "quiet street, exclusions: crowds" scene has no bystander line; audit contradiction metric is zero. **Est.:** S.

### [x] 1.3 Fix `Main subject` / `Appearance` mismatch
- **Do:** in `compile_qwen` (and `compile_flux` while it exists) choose the main subject as the first of: the person asset named in `subject` or `assets`, the prop named in `subject`, else the place. Write the appearance of exactly that asset. A place as subject gets the place description, not a person's.
- **Tests:** a scene with subject "Ludhiana Street" and person asset present yields "Main subject: Ludhiana Street" with the place description, and the person appears in a separate "Also in frame" sentence. **Est.:** S.

### [x] 1.4 Remove noise fields from the scene schema
- **Do:** `story2/scene_schemas.py` and the `SCENES` prompt: drop `style` (the model returns the word "style"), `fixed_by_facts`, `creative_choices`, `needs_asset`, `fallback` as required fields; derive them in `storyboard.build_scene` (style from the style asset; `needs_asset` and `fallback` from `visual_type`; `facts.fixed` from the event/ledger ids once M3 lands, until then from the scene's assets). Keep old stored scenes readable.
- **Tests:** schema accepts replies without these fields; `build_scene` fills them; old scene still validates. **Est.:** S.

### [x] 1.5 Emotion guard
- **Do:** in `story2/maya.py` and `story2/mood.py` add `guard(sentence_text, scene_text, tag)`: when the sentence or scene mentions death, killed, injured, arrest of a named minor, victim, funeral and similar (a small Hindi plus English lexicon in `story2/safety.py`, created here), the tag may not be `happy`, `cheerful`, `excited`, `laughs`; the mood line may not contain "smile", "peaceful smile", "relief" for a victim role. Apply at `set_sentence_tags`, `apply_voice_tags`, `voicetags.suggest`, and `mood.line`. Replace a blocked tag with `serious` or `sad`.
- **Tests:** a sentence about a killing tagged happy becomes `sad`; a victim scene never produces a smiling cue. **Depends:** none (uses 0.3 only for sampling). **Est.:** S.

### [x] 1.6 Attribution and anonymisation (safety v1)
- **Do:** create `story2/safety.py` with (a) `accusations(text)` that finds unattributed statements that a named person committed a crime (Hindi verbs for kill/steal/cheat plus names from the plan's people list) and (b) `private_names(plan)` that lists people in `public.people` who are not marked `public_figure` and are victims, minors or not-yet-convicted. In `make_narration` pass an ATTRIBUTION rule block to the prompt ("until a court decision is in the facts, write what police say or allege: पुलिस के मुताबिक, आरोप है, बताया गया") and send a beat back when `accusations` finds a hit (last attempt accepted, then stored as an issue). In the registry and narration, replace private names by roles or invented names (map stored in `plan.settings.name_map`), applied to prompts, narration, captions and scene text; the name map is part of the plan, not of the content hash.
- **Files:** `story2/safety.py`, `story2/planner.py`, `story2/prompts.py`, `story2/leak.py` (names map allowed), `story2/api.py` (name map edit), `static/plan.js` (small card).
- **Tests:** unattributed accusation is sent back; attributed one passes; names in the map never appear in any compiled prompt or caption. **Est.:** M.

### [x] 1.7 Make the edit-to-plain fallback visible and block silently wrong runs
- **Do:** `story3/scenes.resolve_mode` still falls back, but `scenes.state` and the plan screen show "Drawn plain: no approved reference pictures" per scene, and `auto.py`: when plan `scene_pictures.mode` is `edit` and any scene that needs a reference has none, run the references stage first or stop with a clear `AutoStop`. Add the case "mode edit, zero references" to `auto.done("pictures")` as not done.
- **Tests:** `test_auto` case: edit mode with no references runs references first. **Est.:** S.

### [x] 1.8 Trim dead air in the voice
- **Owner report 2026-10-29: long blank pauses in the last film.** Confirmed by measurement: single silences of **6.7 s and 6.9 s** inside two voice takes (beats 2 and 3 of `pl-0b7cead5`, at 84 s of 104 s and 79 s of 100 s), 3.5 s in a third, and **5.4 s and 5.5 s in the finished video** (at 1:56 and 3:15). The take metadata shows the cause: expected length 84.7 s but real 103.9 s (beat 2) and 88.0 s against 99.8 s (beat 3) with `flags: []`, so the take check did not notice. The engine (Maya) produces a dead stretch near the end of a long single request. Two fixes: (a) trim as below, with a hard rule that **no silence over 0.8 s survives unless it is a planned `pause_after_s`**; (b) **take QA**: after generation measure the longest gap and the ratio real/expected length; a take with a gap over 2 s not planned, or a ratio over 1.12, is regenerated (new seed, up to two tries) and flagged in `meta.flags`. Add both numbers to the audit (done: `voice_longest_gap_s`, `video_longest_gap_s`).
- **Do:** after each voice take is saved (`story3/voice.generate`), run an ffmpeg `silenceremove`-style pass that shortens internal silences longer than 0.4 s to a target gap (default 0.30 s) and keeps every planned pause (`pause_after_s`) by re-inserting it exactly; store `meta.trim = {before_s, after_s}` and re-measure the take length (`voice.apply_timing` retimes scenes from real audio, so durations follow). Add plan setting `voice.max_gap_s` (default 0.30). Re-trimmed takes get a new hash tag so they are not mixed with old ones.
- **Files:** `story3/voice.py`, `story3/store.py` meta, `story2/storyboard.retime` unchanged.
- **Tests:** a synthetic wav with 1.2 s gaps shortens to the target; a planned 0.8 s pause survives. **Done when:** silence share at most 15% on a new take. **Est.:** M.

### [x] 1.9 Loudness normalisation
- **Do:** in `story3/video.build` apply `loudnorm` (two-pass if cheap) to the final mix to about -14 LUFS integrated, true peak -1.5 dBTP; record `meta.loudness`. Keep voice-only takes unchanged.
- **Tests:** ffmpeg available test: output measures within 1 LU of target (skip when ffmpeg missing). **Est.:** S.

### [x] 1.10 Thumbnail minimum fixes (before the full rework in M6)
- **Do:** `story3/thumbnail.py`: pass the protagonist's gender, age (at the hook moment) and description into the prompt; one face only; remove the map panel option; fail the read-back when any word other than the quoted headline is legible (ask the vision check for all visible words and compare to the allowed list); retry up to three times.
- **Tests:** fake vision check returning extra words fails the item. **Est.:** S.

---

## M2 Material Pack and narration v2

Exit (bench): at least 70% of the Material Pack items used in narration; questions at most 7% of sentences; stock phrases zero; last line answers the opening question; every accusation attributed; automatic Hindi gate passes; narration total time fits the plan minutes within 15%; **new-word share at least 45% in every 30 s window until the last minute; a turn in every beat; the central answer told by 85% of the running time; the experience design present and used; the audience profile checks pass (no English numbers in Hindi sentences under `hindi_first`).**

### [x] 2.1 Material Pack: model, store, prompt
- **Do:** create `story2/material.py`. Input: the approved story (`intake.load`) including `evidence.passages` (never sent to later steps, only to this one). Output `plan.settings.material = {items: [...], chain: [...], names: {...}, sensory: [...]}` with items `{id, kind (action|object|place|person|number|sensory|irony|cause|clue|aftermath), detail, when, where, who, alleged (bool), visual (0-3), weight (0-3)}`, 30 to 40 items, at least 8 objects, 6 places, 6 actions, 4 sensory, 3 irony. Add prompt `MATERIAL` (`[TASK:p2_material]`, sampling 0.3): paraphrase, never copy five consecutive words, no source or author or brand, numbers exact, attribute allegations, list the chain of discovery in order, give each person a stable spelling in `names`. Run `leak.check_many` and `leak.overlap_share` on every item; sentences over the overlap threshold are sent back.
- **Files:** `story2/material.py`, `story2/prompts.py`, `story2/schemas.py`, `story2/store.py`, `story2/api.py` (`POST /api/plans/{id}/material`, `GET`), `tests/test_material.py`.
- **Tests:** copied wording is rejected; allegations carry `alleged`; ids are unique; fake gateway returns a valid pack.
- **Done when:** on the fugitive story the pack contains the cleaver, Dharavi, orange orchard, family phone calls and the house now divided into four homes. **Depends:** 0.3, 0.4. **Est.:** M.

### [x] 2.2 Material card and auto-run stage
- **Do:** add stage `material` in `story3/auto.py STAGES` between the plan creation and `blueprint`, and the same order in `static/plan.js` (journey step "Material", Next prompt, side-panel step, a collapsible card listing items with kind chips, edit and delete buttons, "Add an item"). `done("material")` = pack exists for the current story.
- **Tests:** `test_auto` order test; screen step list contains the key (extend the existing order test). **Depends:** 2.1. **Est.:** S.

### [x] 2.3 Blueprint v2
- **Do:** `make_blueprint` input gains `intake.facts_text` plus a compact view of the pack (item id, kind, detail). Change `BLUEPRINT`: each beat lists `use` (ids it must tell), `show` (up to 3 ids that must be seen), `question` and `answer_beat`; the cold open must pose the question with a concrete image and never reveal the resolution; `false_answer` optional; `dark_moment` must be a moment, not a fact; `chapter_title` kept and used later; beats at most 45 s of speech (max 60); first beat at most 20 s. Schema `Blueprint` gains the fields (optional, old plans fine). Sampling 0.5.
- **Tests:** plan with beats lacking `use` is sent back; old blueprint still loads. **Depends:** 2.1. **Est.:** M.

### [x] 2.4 Narration pass 1: storyteller draft
- **Do:** new function `planner.draft_beat` using `NARRATE_DRAFT` (`[TASK:p2_narrate_draft]`, sampling 0.8, top_p 0.95, frequency penalty 0.3 when supported). Output is plain Hinglish prose (no JSON). Prompt content: persona in three lines; the beat's `use` items with full detail; what has been told so far as a list of event titles (not sentences); the beat's question and ending feeling; rules: start inside a concrete moment, at most one question in the beat, direct address at most once, no stock phrase examples (none are quoted in the prompt), numbers as words, Devanagari for Hindi and Latin for English words, attribute allegations, length target in words. No emotion tags, no JSON.
- **Files:** `story2/prompts.py`, `story2/planner.py`, `tests/test_planner.py`.
- **Done when:** a draft for the fugitive story's capture beat contains the keypad phone, the beedi, the six-hour watch. **Depends:** 2.3. **Est.:** M.

### [x] 2.5 Narration pass 2: editor with a banned list in code
- **Do:** `NARRATE_EDIT` (`[TASK:p2_narrate_edit]`, sampling 0.4). Duties: delete sentences that add no new fact or image; merge fragments; replace every hit of the banned lexicon; keep numbers and names; keep length within 10%. The banned lexicon lives in `story2/lexicon.py` (new): stock phrases from the audit (सोचिए, क्या आप सोच सकते हैं, अंदाज़ा लगा, यहाँ मुझे सबसे ज़्यादा, मैं आपको ... चाहता हूँ, चलिए मैं, पर यहाँ एक twist/उलझन/सवाल, बहुत बड़ा सच, एक बहुत ही), cliché nouns (ghost, shadow as metaphor, mystery, empire, mastermind, genius, iceberg, जाल बिछा), filler adjectives (interesting, simple, massive, amazing). Matching is in code (normalised, Devanagari and Latin); the prompt only receives the hits found, not the whole list, so the model cannot copy it. The list is data in the file and grows from audit results.
- **Tests:** a draft containing three banned items is returned with them replaced (fake); lexicon matcher handles spacing and case. **Depends:** 2.4. **Est.:** M.

### [x] 2.6 Narration pass 3: sentence tagger (JSON)
- **Do:** `NARRATE_TAG` (`[TASK:p2_narrate_tag]`, sampling 0.1): input is the edited prose; output the existing `NarrationOut` shape (sentences with text, emotion, pause, plus `pronounce`, `emphasis`, `facts_used` by item id). It may not change words (check: joined text equals input after whitespace normalisation, else retry). Emotion default neutral; guard from 1.5 applies; pause rules: 0.4 to 1.2 after a reveal only.
- **Tests:** word-change is rejected; tags validated by `maya.norm_tag`. **Depends:** 2.5. **Est.:** S.

### [x] 2.7 `make_narration` v2 orchestration and checks
- **Do:** rewire `planner.make_narration` to run draft, edit, tag per beat, saving after each beat. Replace the checks with: ledger coverage (at least 70% of the beat's `use` ids present: each item carries `keywords` so detection is code, not model), question budget (at most one per 8 sentences, at most 4 in the video), opening line at most 12 words, banned-lexicon zero, attribution (1.6), beat length window, romanised Hindi, mixed script, digits. A failed check sends the **edit pass** back with the specific defect and, for coverage, the missing items by name; after two tries the last attempt is accepted and written to `segment.issues` (M8 decides whether that stops auto-run). Old plans keep the old path behind `plan.settings.pipeline < "q2"`.
- **Files:** `story2/planner.py`, `story2/prompts.py`, `story2/svara.py` helpers reused.
- **Tests:** full fake run of three passes; coverage failure names missing items; old path still works. **Depends:** 2.4 to 2.6, 1.6. **Est.:** L.

### [x] 2.8 Best-of-two and judge for opening and ending
- **Do:** for the first and last beats generate two drafts (second at temperature 0.9), run the judge prompt `JUDGE_NARRATION` (`[TASK:p2_judge_narration]`, sampling 0.1, rubric: concrete image in the first sentence, new information per sentence, no cliché, opening question posed, ending answers it, tone fits the facts) twice with the order swapped, and keep the winner; the loser is stored in `plan.settings.narration_alt` for the editor.
- **Tests:** position swap yields consistent choice or falls back to draft A. **Depends:** 2.7. **Est.:** M.

### [x] 2.9 Automatic Hindi gate
- **Do:** `story2/hindigate.py`: (a) back-translation: translate each beat to English (`[TASK:p2_backtranslate]`), then ask which pack items are missing or contradicted; (b) naturalness judge (`[TASK:p2_judge_hindi]`): stiff phrasing, English stuffing above 30% of words, gender agreement for a male first-person narrator, repeated sentence shapes; (c) combine with rule checks into `segment.gate = {ok, issues}`. A beat that fails twice stores the failure and counts in the audit (M8 turns it into a stop). Sampling 0.1.
- **Tests:** fake judge replies; mismatched fact flagged; clean beat passes. **Depends:** 2.7. **Est.:** M.

### [x] 2.10 Ending, comment question and credit line
- **Do:** last beat must contain: the answer to the central question, one closing image, then one question to the viewer in Hinglish designed to invite comments (generated from `indian_hook` and the story's moral), then silence 1.5 s. The description credit line is written in M6.
- **Tests:** check in `make_narration` that the last sentence is a question mark sentence only when the previous one is not. **Depends:** 2.7. **Est.:** S.

### [x] 2.11 Canonical names and spoken forms
- **Do:** use `material.names` as the single spelling for narration, captions, scene text and prompts, with a `say` form for the voice (the existing `pronounce` list); detect variants (Chavi/Chabbi/Chhabbi) and rewrite to the canonical one in all text before saving. Add the check to `audit`.
- **Tests:** variant spellings normalised in narration and scene text. **Depends:** 2.1. **Est.:** S.

### [x] 2.12 Story-type notes for the new passes
- **Do:** extend `story/storytypes.py` notes (`blueprint_note`, `narrate_note`) so each type has pass-specific guidance (incident: chain of discovery; biography: life stages; documentary: evidence and counterpoint; explainer: one analogy that stays; listicle: counted items with one vivid example each). Keep the existing notes for old plans.
- **Tests:** notes included in the right prompt per type. **Depends:** 2.4. **Est.:** S.

### [~] 2.13 Regression run on the bench
- **Status 2026-10-29:** First real-model run on the science story (plan pl-a9f9c127, 2026-10-29): stock phrases 17 to 1, questions 9% to 6%, distinct places 5 to 12, new-word share 0.39 to 0.62, drop windows 1 to 0, mean scene 6.8 s to 5.0 s. Still to fix: English numbers beside Hindi (7), top place 33%, one 10.5 s scene. Only one of the three bench stories was run; run the other two before calling this done.
- **Do:** run the bench to `narration` on the three stories, compare with baseline, record in the progress log, then tune the lexicon and rules. No GPU pictures needed.
- **Done when:** exit criteria above are met on all three. **Depends:** 2.1 to 2.17, 0.2. **Est.:** M.

### [x] 2.14 Experience design in the blueprint (the film's own identity)
- **Goal:** each film gets a deliberate design for how it hooks and rewards the viewer (audit 14.2 and 14.3), so films differ in shape and none is only a sequence of narrated facts.
- **Do:** add `experience` to `Blueprint` (optional): `promise`, `stake_to_viewer` (who is at risk and why the viewer cares, stated in the first 15 s), `clock_device` (`countdown | counter | calendar | none` plus the value, e.g. "six hours", "121 apps"), `clue_device` (how the viewer plays detective: which clue is shown before it is explained), `set_piece` (beat id and a 40 to 60 s shot-by-shot idea built from Material Pack items), `participation` (`pause_and_guess` beat id and question; closing question), `afterimage` (the last image, from the pack), `signature_graphic` (the built card type that recurs, chosen from the evidence-card library in 3.15), `structure_form` (`mystery | countdown | two_timeline | case_file | what_would_you_do`). Add a `[TASK:p2_experience]` step (sampling 0.7) run after the blueprint that fills it from the Material Pack, with a validator: stake present, a set piece that uses at least four `visual>=2` items, a clue shown before its answer in `beats` order, an afterimage that is a pack item.
- **Wiring (must reach all consumers):** narration beats receive the device they must set up or pay off; the events ledger (3.1) marks `set_piece` and `clue` events; the director gives set-piece shots longer and tighter coverage; graphics (3.15) builds the signature card; audio (5.3) builds the set-piece cue; the audit checks that each device appears on screen.
- **Files:** `story2/schemas.py`, `story2/prompts.py`, `story2/planner.py`, `story2/export_schema.py` (public half), screen card in `static/plan.js`.
- **Tests:** schema, validator (clue before answer, stake early), old blueprints load. **Depends:** 2.1, 2.3. **Est.:** M.

### [x] 2.15 Audience language profiles (Indian persona fit in the words)
- **Goal:** the same story can be told for different Indian viewers without rewriting prompts by hand (audit 14.5).
- **Do:** `plan.settings.audience = {profile, region}` with profiles `metro_hinglish` (default), `hindi_first` (English words at most 15% of words, only common ones), `senior_friendly` (Hindi numerals and Hindi words for years, months, money, no English jargon, shorter sentences, speed 1.0). Implement in `story2/lexicon.py`: a **common-English whitelist** (phone, bank, police, office, number, photo, video, message, app, call, court, case, team, ...) and a **jargon glossary** (proclaimed offender, digital forensic analysis, malicious APK, OTP, FIR, sigma, ...) each with a plain Hindi explanation; rule: a jargon term may be used only after a one-sentence plain explanation the first time (generated from the glossary or by the model), or replaced. Number style by profile: `metro_hinglish` keeps English number words only beside English nouns, otherwise Hindi numerals; `hindi_first` and `senior_friendly` use Hindi number words everywhere (पैंतीस साल, उन्नीस सौ इक्यानवे). Add the checks to `make_narration` (send back with the offending words) and to `audit` (English share, non-whitelisted English words, English numbers inside Hindi sentences). The profile and region are chosen on the plan card "Who is this for", defaulting to `metro_hinglish`.
- **Files:** `story2/lexicon.py`, `story2/planner.py`, `story2/prompts.py` (profile note in `NARRATE_*`), `story2/svara.py`/`maya.py` (number words per profile), `static/plan.js`.
- **Tests:** a draft with "thirty-five years" fails under `hindi_first`, passes under `metro_hinglish` beside "years" only when the profile allows; jargon without explanation fails. **Depends:** 2.5. **Est.:** M.

### [x] 2.16 Turn schedule and information density (keep the viewer to the last second)
- **Goal:** fix the density collapse (97% to 29% new words) and the late, thin payoff (audit 14.1 and 14.2).
- **Do:** (1) the blueprint states for every beat a `turn` (a reversal or a new fact, never a question) and a `reward` (the concrete new item the viewer gets), and a `payoff_position` for the film's central answer: the answer to the central question must be told by 70 to 85% of the running time, not in the last 10%; (2) `NARRATE_DRAFT` receives per-beat "give a new fact, person, place, object or number at least every 25 seconds" with the beat's items assigned in order; (3) check in `make_narration`: new-word share per 30 s window at least 45% until the last minute (computed as in 0.6) and a new fact item (by ledger keyword) at least every 25 s; windows below the bar are sent back to the edit pass with the unused items named; (4) no recap sentence twice; one recap at most, placed before the final act; (5) the central-question check: the answer is stated in words in a beat at or after `payoff_position` and the opening question is not left open.
- **Files:** `story2/planner.py`, `story2/prompts.py`, `story2/audit.py` (reuse 0.6).
- **Tests:** a fixture narration with a repetitive middle fails; one with a turn per beat passes. **Depends:** 2.7, 0.6. **Est.:** M.

### [~] 2.17 Participation moments
- **Status 2026-10-29:** Held pause (3 s) and the open closing question are built; the "check yourself" helpline line is covered only by the takeaway beat note (7.5).
- **Goal:** give viewers something to do (audit 14.2 point 9), which raises comments and shares.
- **Do:** blueprint `experience.participation` yields (a) one `pause_and_guess` moment: a sentence of the form "रुकिए, आपके हिसाब से आगे क्या हुआ?" planned at 50 to 60% of the running time, placed right before a reveal that the pack answers; the video holds a still for 3 s with a soft tick (5.9); (b) a closing question that is specific to the story and open (no yes/no); (c) in scam and safety stories a "check yourself" prompt with the real helpline number from the pack. Narration, the storyboard (`breath` scene) and the video each get the moment. Banned: generic "like and subscribe" lines inside the narration (kept for the description).
- **Tests:** present once per film, before a pack-answered reveal; closing question not a yes/no. **Depends:** 2.14. **Est.:** S.

---

## M3 Visual story engine

Exit (bench, to storyboard): distinct places at least 12 for a 6+ minute film; top place at most 20% of scenes; scenes with a person at most 55% (face-free share at least 45%); protagonist at most 35% and never more than two close-ups in a row; at least 8 distinct people for 6 minutes with different silhouettes; distinct visual events at least 90% of scenes; motif repeats at most 4; no scene whose event is missing except typed `texture` or `breath` (at most 15%); at least 8 regional world inserts; at least 2 evidence cards per film; names match the cast; no era-object errors; new place or subject in at least every other 30 s window.

### [x] 3.1 Visual events ledger
- **Do:** `story2/events.py`. From the Material Pack and the blueprint's beats produce 40 to 70 events `{id, beat, ledger_ids, who (role names), where, doing, key_object, period, when_in_story, reveal (bool), camera_hint}` with prompt `EVENTS` (`[TASK:p2_events]`, sampling 0.5). Rules: each event is a single filmable moment; at least one event per six seconds of planned narration; events of kind `reveal` are 6 to 10 per film; no abstract events; periods matter (1991 versus present). Validation: unique, each beat has at least its `show` ids covered, period present when the story spans years. Stored in `plan.settings.events`.
- **Tests:** `tests/test_events.py` (coverage, uniqueness, periods). **Depends:** 2.3. **Est.:** M.

### [~] 3.2 Registry v2: places, props, ensemble, life stages
- **Status 2026-10-29:** Places, props, people and life stages come from the events; the ensemble signature colours are not done.
- **Do:** change `REGISTRY` and `storyboard.make_registry`: 12 to 20 places (each with a `signature` of 3 to 5 specific objects and a time of day), 6 to 12 props including hero objects (`hero: true`; must appear in at least two scenes), 6 to 10 people roles, an ensemble rule (named recurring officers or colleagues each get a signature colour or item, extras only by role), `life_stages` for any person whose story spans more than five years: `[{from_year, to_year, age, look_changes}]`. Asset total cap rises to 40. Keep `describe.py` slot rules; add `describe.person_view(a, year)` choosing the stage. `refs.MIN_SCENES` and `MIN_PROP_SCENES` stay.
- **Files:** `story2/prompts.py`, `story2/storyboard.py`, `story2/describe.py`, `story2/imgprompts.py`, `story2/scene_schemas.py`.
- **Tests:** a two-era story yields two life stages; prompt for a 1991 scene uses the 27-year-old stage; place count rule rejects fewer than 10 places on the first two attempts. **Depends:** 3.1. **Est.:** L.

### [x] 3.3 Director v2
- **Do:** `DIRECTOR` plan keeps camera but each shot gets `event_id`, and `problems()` adds: every shot has an event; no event used twice; same place at most three shots in a row and at most 20% overall; a named motif (any asset flagged `motif`) at most 4 shots; reveal events get a push-in or a pull-back and a close or extreme close. `story_map` shows events.
- **Files:** `story2/director.py`, `story2/prompts.py`. **Tests:** `tests/test_director.py` extended. **Depends:** 3.1, 3.2. **Est.:** M.

### [~] 3.4 Storyboard v2 (event-based, slim schema)
- **Status 2026-10-29:** Not done: the slim scene schema (the old 40-field schema is still asked). Done: derived fields, the similarity and same-pose gate, v2 prompts.
- **Do:** new `SCENES` prompt and schema (`SceneOut` about 14 fields: `sentences`, `shot`, `event_id`, `place`, `who`, `doing`, `foreground_object`, `size`, `angle`, `light`, `feeling_cue`, `text_on_screen`, `voice_tag`, `breath`). `build_scene` derives the rest (narrative fields from the event and sentences, `exclusions` from the style, `facts`, `layers` from place signature). Add the similarity gate to `scene_problems`: reject a scene whose `(place, who, doing, size)` token overlap with an earlier scene is above 0.7. Scenes without `event_id` must have `breath: true` or type `texture` and are capped at 15%. Bump `styles.DIRECTION` to `illustrated-3` and `PIPELINE` to `q2` here so old storyboards are flagged. Sampling 0.6.
- **Files:** `story2/prompts.py`, `story2/scene_schemas.py`, `story2/storyboard.py`, `story2/imgprompts.py` (reads new fields), `story2/editorial.py` (reads fields it scored), tests.
- **Tests:** schema, derivation, similarity gate, old scenes still render prompts; `test_phase2*` suites adapted. **Depends:** 3.2, 3.3. **Est.:** L.

### [x] 3.5 Scene cap and second angle
- **Do:** after storyboard, any scene longer than `plan.settings.max_scene_s` (default 8 s) is split by sentence ranges into two or more scenes; each part follows the same event with a different size and angle (a table: wide to medium, medium to close on hands or object, close to wide behind). The second part is marked `variant_of` the first and is drawn in **edit mode from the first picture** ("same moment, second angle") when a reference picture exists, else drawn plain with the same event text. Scene-count budget: median scene 4 to 5.5 s.
- **Files:** `story2/storyboard.py` (`split_long`), `story3/scenes.py` (variant draw), `story3/video.py` (timing unchanged). **Tests:** a 20 s scene becomes three scenes with distinct camera; picture job draws the variant from the base. **Depends:** 3.4. **Est.:** M.

### [x] 3.6 Character system v2 at prompt time
- **Do:** `imgprompts` picks the person's `life_stage` by the event's period, writes the age into the subject line, applies the ensemble signature colour or item, and an emotion-cue table keyed by event kind (grief, fear, resolve, relief, deceit, routine) validated against `mood.guard` (1.5) so a victim is never smiling and a suspect in a calm scene is not drawn terrified. Same-person-same-pose check: same asset, same posture and place twice in a segment is rejected in `scene_problems`.
- **Tests:** 1991 versus present prompts differ in age; victim cue table has no smile entries. **Depends:** 3.2, 1.5. **Est.:** M.

### [!] 3.7 Face-lock experiment and policy
- **Status 2026-10-29:** Needs the GPU (20 scenes drawn twice). Not run.
- **Do:** run experiment 2 of the audit: 20 scenes of one film drawn plain and in edit mode with the approved sheets, scored by the vision model pairwise ("same person? yes/no with confidence") against the sheet. If edit wins by at least 15 points, make edit mode the default (reference stage always runs for people with two or more scenes; sheets cost about 10 minutes); if not, keep plain and rely on prompt strength. Record the result in `docs/RUN_LOG.md`.
- **Tests:** none (an experiment). **Depends:** 1.7. **Est.:** M.

### [x] 3.8 Visual grammar per story type
- **Do:** `story/storytypes.py` and `story2/prompts.py` notes: explainer and listicle stories must use grounded Indian-life analogies drawn from an analogy bank (`story2/analogies.py`: queue at a kirana, a mandi price board, a local train, a power cut, a wedding budget, a school notebook, a cricket scoreboard; each with a prop list and a place) and built cards for numbers; never abstract worlds, floating platforms or symbols (the 1987 film failure). The validator rejects scenes whose place is not a physical place and scenes with visual types `metaphor` above 10%.
- **Tests:** an explainer storyboard on the fake gateway containing "abstract grid" is sent back. **Depends:** 3.4. **Est.:** M.

### [x] 3.9 Built maps and route graphics
- **Do:** `story3/graphics.py`: new template `map` drawing an India (or world) outline with named cities and a route polyline from the event list, with the film palette; data bundled as a simplified GeoJSON in `static/` or `story3/data/`. The image model never draws maps (storyboard visual type `map_timeline` routes here).
- **Tests:** card contains only city names from the facts; route order follows chronology. **Depends:** 3.1. **Est.:** M.

### [x] 3.10 On-screen text discipline
- **Do:** text on screen (signs, whiteboards) must come from the event or the facts; the storyboard validator removes whiteboard and wall-text scenes unless the text is a required story object (e.g., the name board). The scene prompt carries at most one quoted text. Check `text_on_screen` against allowed words (`leak` plus facts).
- **Tests:** an office scene with "FAKE" and "1930" not in the event is stripped. **Depends:** 3.4. **Est.:** S.

### [x] 3.11 World and cast rules (no tiny world, no repeated people)
- **Goal:** enforce the measurable world rules of audit 14.4.
- **Do:** (1) scene classification `face_free` (place wide, object insert, hands only, back or silhouette at distance, document or phone card, map, texture, crowd at distance) versus `face`; (2) validators in the director (`problems`) and the storyboard (`scene_problems`): face-free share at least 45%; protagonist at most 35% of scenes; no more than two consecutive close-ups of any face; at least one new person or place per beat; same person never in the same pose and place twice in a segment; (3) cast rules in `REGISTRY`: at least eight people for six minutes with distinct silhouettes (age, build, clothing colour, a signature item); recurring roles (officers, colleagues) are two or three individuals plus extras, each extra described by role and one visible trait; women and men in varied roles when the story allows; (4) place kinds: at least five of home, street, institution, transit, workplace, nature, night, interior, exterior (stored on each place as `kind`), at least two places per beat; (5) a repair step: when a rule fails after two tries, a code sweep converts the repeating face scenes into object, hands or place inserts using the event's `key_object` and the place's signature.
- **Files:** `story2/director.py`, `story2/storyboard.py`, `story2/prompts.py`, `story2/audit.py` (metrics), `story2/imgprompts.py` (silhouette signature).
- **Tests:** a storyboard where the protagonist is in 50% of scenes is sent back and the sweep brings it under 35% on the fake gateway. **Depends:** 3.2, 3.3. **Est.:** M.

### [x] 3.12 Regional world: cue table and world inserts
- **Goal:** places look like the places in the story, and the world around the people feels big (audit 14.4 and 14.5, persona P5).
- **Do:** (1) `story2/region.py`: a table by state and by well-known city (start with Delhi, Punjab/Ludhiana, Gujarat/Surat, Maharashtra/Mumbai/Dharavi, West Bengal/Kolkata, Uttar Pradesh/Kanpur/Sultanpur, Jharkhand/Jamtara, Goa, Tamil Nadu, Karnataka, Kerala, Rajasthan) giving per region: typical clothing by gender and age and community-neutral where possible, headwear, vehicles, street furniture, signage script and language (Gurmukhi, Gujarati, Marathi, Bengali, Hindi), food stalls, architecture and building materials, weather and season, vegetation, landmarks, bus and train look, police uniform colour; the table is data in a JSON file so it can grow. (2) The registry receives the story's region(s) from the Material Pack and must fill the place `signature` and the people's clothing from the table (no single cream kurta for every man). (3) **World inserts:** after the storyboard, `story2/inserts.py` adds 8 to 12 cutaway scenes per six minutes (1.5 to 2.5 s, no dialogue weight, typed `texture`/`insert`) at beat boundaries and set-piece ramps, each a short specific image of ordinary life in the story's region and period from the cue table (a tea stall at dawn, a hand pulling a shutter, laundry on a terrace, rain on a tin roof, a tram passing, a platform board, school children, a temple bell, a scooter horn lane), drawn with the same style, never reused across the film. (4) Signage uses the region's script only where the scene has quoted text; otherwise blank. (5) `audit` metric: regional cue count per film (at least 6 distinct cue types) and insert count.
- **Files:** `story2/region.py`, `story2/data/regions.json`, `story2/inserts.py`, `story2/prompts.py`, `story2/imgprompts.py`, `story2/storyboard.py`, `static/plan.js` (insert list).
- **Tests:** a Punjab story's prompts contain Punjab cues (turban for men of the relevant community where the story names it, otherwise mixed headwear, dhaba and tractor in insert pool); inserts are unique and short; a Kolkata story keeps trams and yellow taxis. **Depends:** 3.2. **Est.:** L.

### [x] 3.13 Era table and era grading
- **Goal:** right objects, right clothes, right look for each time period, and a visible difference between past and present (audit 14.3 and 14.5).
- **Do:** (1) `story2/era.py`: per decade from 1950 to now a list of anachronisms (no mobile phone before 1995 in India, no smartphone before about 2010 for the average person, no CCTV in a small lane in 1991, tubelights and ceiling fans, Ambassador and Fiat cars, black rotary phone, STD booth) with allowed and forbidden objects; (2) each scene carries `period_year` from its event; a validator rejects forbidden objects in `props`/`doing` and flags suspect ones (a smartphone where the Material Pack says keypad phone); (3) **grading by era:** the style gets an era modifier in the prompt's style sentence (earlier: warm, grainy, softer contrast; present: cleaner, cooler) and in the video (a mild colour grade and grain filter per era through ffmpeg `eq`/`noise`), with a short on-screen year label at jumps in time (a 1.5 s year card, built by code); (4) set cast ages by `life_stages` (3.2).
- **Tests:** 1991 scene with "smartphone" fails; a year label inserted at a time jump; era modifier present in prompt. **Depends:** 3.2, 4.1 for the prompt part. **Est.:** M.

### [x] 3.14 Act-level camera language and point-of-view shots
- **Goal:** the film feels directed: different camera behaviour in each act and views through objects (audit 14.3).
- **Do:** the director plan adds `act` (1 to 3) per segment and a per-act grammar: act 1 locked and calm (hold, slow push, wide), act 2 closer and moving (drift, pan, medium and close), act 3 decisive (slow pushes, low angles, extreme close at the climax, then a pull back); add shot kind `pov` with `through` (`phone screen | window | doorway | CCTV | binoculars | car window | keyhole`) and `pov_of` (who); 4 to 8 per film; `story3/video.py` maps `pov` through shots to a vignette or screen-frame overlay built by code. The Qwen prompt for a `pov` shot names the object frame ("seen through a cracked car window").
- **Tests:** per-act move distribution; pov shots have both fields. **Depends:** 3.3. **Est.:** M.

### [x] 3.15 Evidence-card library and on-screen counters
- **Goal:** carry facts and mystery visually (audit 14.2 points 2 and 3, 14.3), and stop illustrating words.
- **Do:** extend `story3/graphics.py` with built templates, each drawing only facts from the Material Pack and the film's palette and fonts (Nirmala for Devanagari): `chat` (a generic chat-app thread with two or three bubbles, no brand, no logo, a generic green-grey look, bubbles contain only text from the pack), `sms` (a bank-style alert with an amount), `call_log` (a list of calls with one repeating number highlighted), `fir` (a paper scrap with a few fields blanked), `news_clip` (a newspaper-cutting look with a headline paraphrase and a year), `id_card`, `ledger`, `phone_pov` (a lit phone screen in a hand silhouette with one line of text), `route_map` (3.9), `counter` (a big number that counts up, a clock face, a day counter), and `year_card` (3.13). Each card has an animation hint used by `story3/video.py` (count-up, line draw, highlight, reveal in order). The storyboard (3.4) may choose `card:<type>` as a scene type when the event has `signature_graphic`, `clue` or a number item; at least two evidence cards per film are required for incident and explainer types. Numbers on a card must exist in the pack (existing `graphics.verified`).
- **Files:** `story3/graphics.py`, `story3/video.py` (animations), `story2/storyboard.py`, `story2/scene_schemas.py`, `static/plan.js`.
- **Tests:** each card renders with Devanagari and Latin text inside the frame; a number not in the pack is refused; no brand string in any card (lint list). **Depends:** 2.1, 3.1. **Est.:** L.

### [x] 3.16 Names, cast and region must agree
- **Goal:** no Scandinavian name on an Indian cast (audit 14.5) and no random names in an Indian story.
- **Do:** the registry and the Material Pack choose names and clothing from the region table: when the story's people are real and unnamed in public sources, invented names come from the region and community-neutral lists (given names first, avoiding caste surnames and religion-coded combinations where the story does not need them); the cast setting "as the story says" keeps the story's own names and origin. `describe.indianise` also renames a person whose name does not fit the cast (kept in `plan.settings.name_map`, with the editor able to change it), and the `audit` flags a mismatch. International stories with an Indian audience keep names but give each foreign person an appearance that matches the name unless the editor chooses the Indian-cast option, in which case names are localised.
- **Tests:** "Sam Eriksen" under Indian cast becomes a regional name; the map is used in narration, captions and prompts. **Depends:** 3.2, 2.11. **Est.:** S.

---

## M4 Image prompts and picture QA

Exit: story-specific words at least 70% of prompt words; identical-sentence share at most 15%; negation phrases zero; first-try pass rate of the picture check at least 70%; redraws per film at most 8 at a comparable scene count.

### [x] 4.1 Image prompt v2 compiler
- **Do:** new `imgprompts.compile_qwen_v2`: one flowing paragraph of 100 to 140 words in this order: who does what (event), where with the place's two most specific objects, time and light, camera in plain words (size, angle, lens feel), one short style sentence; text clause only when the scene has quoted text; a safe-area clause shortened to one phrase. Positive phrasing only. Keep `MAX_PROMPT_WORDS`, `source_hash`, `sections` (for the screen) and the validator interface. Old plans keep v1 until redone (PIPELINE flag).
- **Tests:** word budget; no `no`/`not`/`without` constructs outside the style sentence; subject and event present; hidden-slot rules from `describe` still honoured. **Depends:** 3.4. **Est.:** L.

### [x] 4.2 Prompt lint
- **Do:** `imgprompts.lint(prompt)` returns issues: negation phrases, contradictions (crowd versus quiet, close versus establishing), age or gender mismatch with the asset, more than one quoted text, over budget. Run it in `imgplan.validate_prompts` and block drawing on `error` level.
- **Tests:** each rule on a crafted prompt. **Depends:** 4.1. **Est.:** S.

### [!] 4.3 Prompt format bench (experiment 1)
- **Status 2026-10-29:** Needs the GPU (24 scenes in three prompt formats). Not run. v2 stays the default only on the strength of the prompt-length and negation audit, not a picture test.
- **Do:** 24 scenes, formats v1, v2, v2 plus one-line style tail; same seeds; score with `refscore.look` and a pairwise vision judge (position swapped); decide the default and record in `docs/RUN_LOG.md`. If v1 wins on any scene type, keep v1 for that type behind a switch.
- **Depends:** 4.1. **Est.:** M (GPU about 45 minutes).

### [x] 4.4 Vision judge v2
- **Do:** `story3/refscore.py` scene mode compares the picture against the **event and the narration of that moment**, not only against the prompt: checks who is present (count and roles), age band, emotion fit with the moment, key object present, place identifiable, text legible and allowed, hands and anatomy, duplicate subject. Output the same score shape plus `event_fit` (0 to 100) and `hard` problems list. `AUTO_APPROVE_MIN` raised only after calibration in 8.2.
- **Tests:** fake vision replies mapped to flags; hard flag blocks bulk approval. **Depends:** 3.4. **Est.:** M.

### [x] 4.5 Duplicate and near-duplicate picture detector
- **Do:** compute a perceptual hash (average hash plus colour histogram) for every approved or candidate scene picture; flag pairs within a distance threshold or the same `(place, who, size)`; the redraw loop redraws the later one with a change request ("different place angle / different moment"). Add the metric to `audit`.
- **Tests:** two near-identical synthetic images flagged; distinct ones not. **Depends:** none. **Est.:** S.

### [x] 4.6 Redraw policy
- **Do:** `story3/auto.py` pictures stage: up to two redraws per scene using the judge's reasons to edit the prompt (add the missing object, fix the age, remove the extra person) instead of only new seeds; stop redrawing when event_fit is at least 75.
- **Tests:** a failing fake score triggers a prompt change, not only a seed change. **Depends:** 4.4. **Est.:** M.

### [x] 4.7 Time budget and ordering
- **Do:** estimate picture time before the run (scene count times seconds per picture per model) and show it on the Auto-run button; group requests by model and mode to avoid swaps; make the draw loop resumable per scene (already) and write estimates to the audit.
- **Depends:** 3.5. **Est.:** S.

---

## M5 Video and sound

Exit: mean scene at most 5.5 s, max at most 8 s; a music bed and place ambience are present under the voice at a stable ducked level; video loudness at -14 LUFS; captions are phrase-level and bold; the film opens with a cold open then a title card and ends with a payoff plus an end card.

### [x] 5.1 Pacing in the assembler
- **Do:** `story3/video.build` enforces `max_scene_s` as a last guard (splits a clip into two moves of the same picture if a scene still exceeds it), ensures consecutive clips never share the same move, and inserts a fast "pattern interrupt" (a 3 to 5% punch zoom or a short cut to a detail picture) when no visual change has happened for 4.5 s.
- **Tests:** a 12 s clip becomes two moves; no two same moves in a row. **Depends:** 3.5. **Est.:** S.

### [x] 5.2 Motion variety and key-moment clips
- **Status 2026-10-29:** `clips.choose_scenes` marks the hook, the reveal events and the last picture (budget `clip_budget`, default 8) when motion clips are on; the depth-parallax move is not built.
- **Do:** auto-enable Wan clips (`story3/clips.py`) for the hook, each `reveal` event and the climax (8 to 12 per film, budget from `plan.settings.clip_budget`); add depth-style parallax (two-layer crop with a gentle offset) as an optional move when the gateway has a depth model or when a simple foreground/background split is available; if not, skip. Clips sit in the same timeline slot as the picture.
- **Tests:** eligibility by event flag; budget respected. **Depends:** 3.1. **Est.:** M.

### [x] 5.3 Sound bed
- **Do:** `story3/audio.py`: from `blueprint.music_brief` and per-beat feeling choose music segments through the gateway music models (`minimax-music-3` or `yue2-3b`, check the listing); generate 3 to 5 stems (tension, calm, discovery, climax, resolution), loop and crossfade by beat; ambience beds per place type (street, house interior, station, office, rural, cave) from a small bundled library or generated; stings on reveal events; sidechain ducking under the voice (`sidechaincompress` or `amix` with `volume` automation); music at about -26 LUFS under voice. Everything is stored as `media` kind `audio_bed` with a hash of the plan's beats; the draft video uses it when present. Setting `audio.enabled` (default on), `audio.music_level`.
- **Files:** `story3/audio.py`, `story3/store.py` kinds, `story3/video.py`, `story3/api.py`, `static/plan.js` (card and auto-run stage `sound` after `voice`).
- **Tests:** timeline length equals voice length; ducking filter present in the command; missing music model reported, never silent.
- **Depends:** 1.8, 1.9. **Est.:** L.

### [x] 5.4 Captions v2
- **Do:** `story3/video.py` caption events: split sentences into phrases of 3 to 6 words timed by character share across the sentence duration; font size about 5.5% of frame height, bold, thick outline, two lines max, lower third inside the safe area; emphasise one key word (number or name) in a second colour; setting `captions.style = phrase|sentence` (default phrase). Hindi uses Nirmala UI bold, English words the same family.
- **Tests:** phrase timing covers the sentence exactly; line length cap. **Est.:** M.

### [~] 5.5 Film structure: cold open, title card, end card
- **Status 2026-10-29:** End card built; the 2-second title card after the cold open is not.
- **Do:** assemble: cold open (first beat's first 10 to 20 s) → 2 s title card (title text, channel mark, no source) → rest; ending: payoff, comment question, 5 s end card with next-video slot (YouTube end screens are added in the platform). The title card text comes from 6.1. Setting `structure.title_card` default on.
- **Tests:** timeline order and lengths. **Depends:** 6.1. **Est.:** M.

### [x] 5.6 Chapters and render profile
- **Do:** write chapter timestamps from beats (`chapter_title`) into the publish pack (6.3); add a `final` render profile (CRF 18, 1080p, 30 fps, AAC 192k, loudness applied) next to `draft` and `preview`, and a `lite` profile (720p, 24 fps, CRF 26, AAC 96k) for low-data viewers, uploaded as a second file or used to check phone legibility of captions and thumbnails.
- **Tests:** timestamps follow real timeline including the speed setting. **Est.:** S.

### [~] 5.7 Pace setting
- **Status 2026-10-29:** `plan.settings.speed` replaces the constant and is part of the hash; the 1.0/1.15/1.25 proxy test is not done. New render profiles `final` and `lite` exist.
- **Do:** `plan.settings.speed` (default 1.25) replaces the constant `PLAYBACK_SPEED` in `story3/video.py`; compute and show total length and words per minute on the video card; automatic proxy test (experiment 5): build at 1.0, 1.15, 1.25 and print length, dead-air share and words per minute.
- **Tests:** speed in hash; changing it marks the video as older. **Est.:** S.

### [x] 5.8 Final mix verification
- **Do:** after every video build run `ebur128` and `silencedetect` on the output and store `meta.audio = {lufs, peak, silence_share}`; the audit reads them; a build outside targets is flagged.
- **Depends:** 1.9. **Est.:** S.

### [~] 5.9 Progress devices and participation moments on screen
- **Status 2026-10-29:** Chapter flash and year label are built; the clue counter, the countdown clock and the pause tick are not.
- **Goal:** viewers see where they are and have something to do (audit 14.2 and 14.3).
- **Do:** `story3/video.py` renders, from `blueprint.experience` and the events: a 2 s **chapter title flash** at each beat start (lower left, the film's accent colour, from `chapter_title`); the film's **counter** (a clue counter "Clue 2 of 4", a countdown clock, or a day counter) in a corner, advancing at its events; the **pause-and-guess** beat: the picture holds for 3 s with a soft tick and a Hinglish prompt line, no voice; the **year card** (3.13); the **end card** (5.5) with three takeaway lines for explainers. All overlays are built by code (Pillow images or ffmpeg `drawtext`/`overlay`), kept inside the safe area, and can be turned off in plan settings (`overlays.*`).
- **Tests:** overlay timings match event times after the speed setting; counter increments only at clue events; overlay off switch works. **Depends:** 2.14, 3.15, 5.7. **Est.:** M.

---

## M6 Packaging

Exit: every film ends with a publish pack: three titles, one chosen thumbnail plus two alternates, description with chapters and credit line, tags, pinned comment, `.srt` files; thumbnail shows the protagonist, is legible at 170 by 95 pixels, and the title claim is verified against the facts.

### [x] 6.1 Title generator
- **Do:** `story2/titles.py` with `[TASK:p2_title]` (sampling 0.8): from `cold_open`, the central question, the most surprising Material Pack item, and `indian_hook` produce 8 Hinglish and English options (max 60 characters, no clickbait lie, one number at most, one named place or person at most), then a judge ranks them (curiosity gap, specificity, honesty, search words). The best is stored as `plan.settings.video_title` (already used by the dark-matter plan). Candidate titles from Phase 1 (7.3) are inputs.
- **Tests:** length limit; honesty check rejects a claim not in the facts. **Est.:** M.

### [~] 6.2 Thumbnail v2
- **Status 2026-10-29:** The headline is written in code (Pillow, Indian money style, Devanagari font) and checked at 170x95; one prompt, up to three tries. Not done: four variants scored by a vision rubric, rupee/lakh in the image, the channel frame.
- **Do:** (text by code) the image model draws **no text at all**; the headline is composited afterwards with Pillow in a bold face (Devanagari through Nirmala UI Bold or a bundled heavy Devanagari font; Latin through a heavy sans), with stroke and shadow, so it is never garbled and Hindi or Hinglish headlines become possible; the image prompt asks for an empty clear area where the text sits. Rewrite `story3/thumbnail.py` and `THUMBNAIL` prompts: one protagonist face (from the protagonist's reference or description, correct gender, age at the hook moment), one secondary element at most (the key object), three words or fewer in large type, high contrast, a consistent channel frame (fixed border and logo position), a look matching the video style; generate 4 variants; score each with a vision rubric (one focal point, emotion readable, text legible at 170 by 95 pixels, matches protagonist, contrast, no garbled words) after downscaling to test size; pick the best, keep two alternates. Numbers use rupee and lakh/crore formatting. Remove the multi-panel layout unless the rubric favours it.
- **Tests:** downscale legibility check on a fake image; garbled-word check. **Depends:** 6.1, 4.4. **Est.:** L.

### [x] 6.3 Publish pack
- **Do:** `story3/publish.py` writes `data/media/<plan>/publish/` with: titles, description (hook paragraph, chapters, key facts, a credit line from `intake` evidence stored in the plan only, keywords in Hinglish and English, hashtags, disclosure note when needed), tags, a pinned comment question, end-screen suggestion, and the disclosure checklist result (realistic-looking reconstruction of a real event: say so). A screen card "Publish pack" shows and edits it; one download button zips it.
- **Tests:** no source string in titles, thumbnail words or video; credit line only in description; chapters sorted and first at 0:00. **Depends:** 6.1, 5.6. **Est.:** M.

### [x] 6.4 Subtitle files
- **Do:** write `captions-hi.srt` from narration sentences with the real timeline (including speed), and `captions-en.srt` from a Gemma translation pass (`[TASK:p2_subs_en]`, sampling 0.3) that keeps names and numbers; both listed in the publish pack.
- **Tests:** times monotonic; English file has the same cue count. **Depends:** 5.7. **Est.:** M.

### [x] 6.5 Claim check between packaging and content
- **Do:** `story2/claimcheck.py`: given title, thumbnail words and first description paragraph, ask a judge (`[TASK:p2_judge_claim]`) whether each claim is stated in the narration or the pack and whether it matches the facts (the 2007 versus 2012 case); fail closed.
- **Tests:** a title with an invented number fails. **Depends:** 6.1. **Est.:** S.

### [~] 6.7 Persona-aware packaging
- **Status 2026-10-29:** Done: three registers, audience order, Indian money style, community-term blocklist. Not done: the thumbnail rubric run in two scripts, the protective promise line.
- **Goal:** titles and thumbnails that work for the Indian viewer types in audit 14.5.
- **Do:** the title generator (6.1) produces options in three scripts/registers (Hinglish in Latin letters, Devanagari Hindi, English) and a judge ranks them for the plan's audience profile (2.15); the description starts with a Hindi hook line and an English line for search; hashtags include both scripts; the thumbnail rubric (6.2) runs once with Devanagari and once with Latin headline text and keeps the better; numbers are written in Indian style (₹64 करोड़, 5 लाख) in titles and thumbnails; no community or religion terms in titles; for scam stories the thumbnail and the first line of the description carry the protective promise ("बचने के 3 तरीके") when the film has the "what this means for you" beat (7.5).
- **Tests:** crore/lakh formatting; no community terms from a small blocklist; both scripts offered. **Depends:** 6.1, 2.15. **Est.:** M.

### [x] 6.6 Screen integration
- **Do:** auto-run stages `title`, `thumbnail`, `publish` (after video); plan screen steps and the Next bar; keep the existing thumbnail card until 6.2 replaces it.
- **Tests:** stage order test. **Est.:** S.

---

## M7 Selection and story types

Exit: Phase 1 shows packaging, visual-richness and safety scores and a YouTube title draft; the template-variance metric differs across the bench stories.

### [~] 7.1 Phase 1 scores
- **Status 2026-10-29:** Computed by rules (`story/reach.py`), shown as chips on the story card. Not done: a model judge for the title, priority adjustment.
- **Do:** add to `story/scoring.py` three scores from the candidate's chronology, people and claims: `visual` (count of distinct filmable events and places), `packaging` (a one-line curiosity title can be written from facts, asked of the model with a judge), `safety` (private victims, minors, graphic violence, allegation status). Default weights stay; the new scores adjust priority modestly (`packaging` and `visual` positive, `safety` flags without removing). Show chips on the story card.
- **Tests:** scores present; ordering changes as expected on fixtures. **Est.:** M.

### [~] 7.2 Sibling merge guidance
- **Status 2026-10-29:** API `GET /api/projects/{pid}/merge-suggestions` only; no button on the review screen.
- **Do:** when several pending candidates come from the same article (the fugitive case), the review screen offers "Merge into one richer story" (`story/review.py` merge exists) with a suggestion that keeps the strongest hook title and all chronology items; auto-suggest when two candidates share more than half their `para_ids`.
- **Tests:** suggestion appears for the fugitive fixture. **Est.:** S.

### [ ] 7.3 YouTube title draft per candidate
- **Do:** when a story is approved, produce 3 title drafts (using 6.1's prompt) saved in `candidate.data.title_drafts`; Phase 2 reads them.
- **Depends:** 6.1. **Est.:** S.

### [ ] 7.4 Type-specific blueprint and storyboard tests
- **Do:** fixtures for biography, documentary, explainer, listicle; check each type's output shape on the fake gateway (life_arc beats carry `life_stages`, listicle beats are numbered items with one vivid example, explainer beats carry an analogy id).
- **Tests:** per-type test files extended. **Depends:** 2.12, 3.8. **Est.:** M.

### [x] 7.5 "What this means for you" segment
- **Do:** for incident and explainer types add an optional last beat `takeaway_action` (what a viewer can do: do not install APKs from messages, call 1930, check a number), generated from the pack and clearly marked as general advice, never as legal or financial advice; skipped for biography.
- **Tests:** present for scam story, absent for biography. **Est.:** S.

### [x] 7.6 Anti-template engine
- **Do:** `story2/variety.py` picks per film a `signature = {palette, lens feel, opening form (cold open | question | object), music family, structure (mystery | cold_open | decision_consequence ...), caption accent}` avoiding the last N films on the channel (read from `plans`); writes into the style asset and prompts; audit metric "difference from the previous five films" (palette distance, structure repeat, opening form repeat).
- **Tests:** consecutive plans differ in at least three signature fields. **Est.:** M.

### [~] 7.7 Region fit and relatability scoring in Phase 1
- **Status 2026-10-29:** Region, sensitivity and a practical-lesson estimate by rules, shown as chips; stored with the story only through the plan region setting.
- **Goal:** choose stories Indian viewers can recognise and care about, and know their region before production (audit 14.5).
- **Do:** add to `story/scoring.py` three scores from the candidate data: `region` (the main states and cities the story names and whether the region table covers them; a missing region lowers the score and shows "add region cues"), `relatability` (a model judge with a fixed rubric: could an ordinary viewer in the target audience imagine this happening to them or near them; is there a practical lesson), `sensitivity` (community, caste, religion and gender flags, minors, ongoing trials). Show chips on the story card and store `candidate.data.region` for Phase 2 (`audience.region`, 2.15, and `region.py`, 3.12). They adjust priority modestly and never remove a story.
- **Tests:** a Punjab story gets `region = Punjab`; a story with named minors gets a sensitivity flag. **Depends:** 3.12 for the table. **Est.:** M.

---

## M8 Automatic gates (replaces the human review)

Exit: auto-run stops with a clear reason when a gate fails; calibration shows the gates reject the nine audited films' worst defects and accept a rewritten good one.

### [x] 8.1 Judge module
- **Do:** `story2/judges.py` with named judges (narration, storyboard, picture, thumbnail, packaging) sharing one runner: fixed rubric, JSON scores 1 to 5 with a reason, run twice with swapped option order where comparative, sampling 0.1, results stored in `plan.settings.judges`.
- **Tests:** deterministic fake; swap consistency logic. **Est.:** M.

### [!] 8.2 Calibration on stored films
- **Status 2026-10-29:** Needs real films with human-labelled scores. The thresholds in `story2/gates.py` are first values from the nine audited films and the bench; only unmistakable defects are hard.
- **Do:** run the judges and the audit on the nine audited plans; use my audit scores (section 2) as labels (newest fugitive film below 5 on narration and storyboard); choose thresholds so the stored films fail where the audit says they fail, and write them to `story2/gates.py` `THRESHOLDS`. Add one hand-improved sample (a rewritten opening) to check acceptance.
- **Tests:** thresholds file loaded; regression test with frozen judge outputs. **Depends:** 8.1, M2 to M6. **Est.:** M.

### [x] 8.3 Auto-run gates and targeted loop
- **Do:** `story3/auto.py`: after narration, storyboard and pictures run the gate; on failure do **one targeted automatic repair** (narration: send failing beats back through the edit pass with the judge's reasons; storyboard: regenerate failing segments; pictures: redraw per 4.6) and re-check; if still failing raise `AutoStop` naming the metric and scene or beat. New plan setting `gates.mode`: `strict` (stop) or `warn` (continue and list), default `strict`.
- **Tests:** a failing fake gate repairs once then stops. **Est.:** M.

### [ ] 8.4 Editorial scores that can see
- **Do:** `story2/editorial.py` adds `storytelling` (judge-based) and `specificity` (ledger coverage, events, places) dimensions to the twelve; sign-off blockers include gate failures; scores no longer give 100 to opening strength without the judge's pass. Content hash unchanged.
- **Tests:** existing editorial tests plus new dimensions. **Est.:** M.

### [x] 8.5 Safety gate
- **Do:** `story2/safety.py` gate: unattributed accusation (1.6), private name present, graphic act detected in scene text or prompts (verbs list plus vision flag on pictures), minors named, distress score of thumbnail, disclosure checklist item; any hit blocks the publish pack with the fix listed.
- **Tests:** each rule. **Est.:** M.

### [~] 8.6 Regression suite and commands
- **Status 2026-10-29:** `python -m story2.bench --check NAME` and `--accept NAME`. The audit thresholds are not yet pytest cases over frozen fixtures.
- **Do:** put the audit thresholds into `pytest` as fast tests over frozen fixtures (no GPU), add `python -m story2.bench --check` that fails when a metric regresses against the last accepted baseline, document in `CLAUDE.md` (one line) and `docs/APP_GUIDE.md`.
- **Est.:** S.

### [x] 8.7 Persona panel judge
- **Goal:** an automatic stand-in for audience review, since no human step is used (audit 14.5).
- **Do:** `story2/personas.py` holds the eight persona profiles (P1 to P8, with language comfort, device, patience, what they look for, what annoys them, sensitivities). The panel runs five questions per persona on the title and thumbnail description, the first 30 seconds of narration, the whole narration with timestamps, and the scene list: (1) would I click, why; (2) where would I leave and why (timestamps); (3) what did I not understand; (4) what felt untrue or unfair to my community, region or gender; (5) would I share it, with whom. Each answer is JSON (sampling 0.3; two runs, take the worse of the two for gates). Results are summarised into `plan.settings.panel` and displayed as a card ("Where viewers would leave"). The panel result feeds the repair loop in 8.3 (the failing beats go back with the persona's reason). **Calibration note:** LLM personas are weak proxies; weights are low until task 9.2 compares them with real retention.
- **Tests:** fake panel replies; worst-of-two logic; summary includes timestamps. **Depends:** 8.1, 0.6. **Est.:** M.

### [x] 8.8 Viewer-simulation gate
- **Goal:** do not finish a film whose boredom map shows a long dead stretch (audit 14.1).
- **Do:** thresholds in `story2/gates.py`: no more than one flagged 30 s window in a row, new-word share at least 45% until the last minute, a new place or subject at least every other window, no scene over 10 s, payoff position by 85% (2.16). Auto-run (8.3) runs the gate after narration and after the storyboard; a failure triggers the targeted repair once (narration: edit pass on the flagged windows with the unused pack items; storyboard: insert world inserts or evidence cards and split long scenes).
- **Tests:** a fixture with a dead stretch fails and is repaired by inserts on the fake gateway. **Depends:** 0.6, 3.12, 3.15, 8.3. **Est.:** S.

### [x] 8.9 Cultural and community sensitivity gate
- **Goal:** protect against community inference, stereotype and tone problems (audit 14.5, persona P8 and P6).
- **Do:** checks in `story2/safety.py`: (a) accused or victim names plus community terms in the same sentence; (b) place stereotypes (a region described as a crime hub in a generalising sentence); (c) glamourising words about offenders ("genius", "legend", "mastermind", "king") from the lexicon (2.5); (d) victim depiction rules (no smile cue, no exposure, no sexualisation); (e) minors named or shown with a face; (f) religion or caste markers in thumbnails and titles; (g) required safety content in scam stories (the helpline from the pack, a one-line "what to do now"). Failures block the publish pack with the fix listed and send narration back once.
- **Tests:** each rule on crafted text. **Depends:** 1.6, 2.5. **Est.:** M.

---

## M9 Later (not planned in detail)

- [ ] 9.1 Shorts: cut 3 to 5 vertical clips per film from reveal events (hook line, one beat, end on the question), composed 9:16 from the same events through edit-mode re-framing, with phrase captions and a pointer to the long video.
- [ ] 9.2 Analytics loop: import YouTube Analytics (retention curve, CTR, returning viewers) per video, map drops to scene ids, store which opening form, length, thumbnail style and music worked; feed `variety.py` and the judges.
- [ ] 9.3 English or multi-audio version from the same events and a translated narration pass.
- [ ] 9.4 Channel and series: playlists, series placement from `series_placement`, fixed frame and logo, upload scheduling notes.

---

## Risks and open points to watch while building

- **Cost of picture count.** A mean scene of 4.5 to 5.5 s means 90 to 110 scenes for 8 minutes. Keep the budget honest with 3.5 (second angles), 5.2 (clips) and 4.7 (estimate on the button). If time per film passes about 3 hours, raise `max_scene_s` to 9 before cutting quality.
- **Gateway sampling support** is unknown until 0.3 probes it. If penalties are unsupported, rely on the editor pass and the banned lexicon.
- **No human review** means subtle Hindi mistakes can reach a film. 2.9 and the judges reduce but do not remove that risk.
- **Hash compatibility.** Keep new data outside `editorial.content_hash`. Any task that needs it inside stops and asks the owner.
- **Source rule.** Material Pack items are paraphrases checked by the leak gate; if a check cannot be satisfied for an item, drop the item rather than weaken the gate.
- **Test time.** Run only the tests of the area during a task; the full suite once per milestone.

## Progress log

| Date | Task | Commit | Result |
|---|---|---|---|
| 2026-10-29 | Audit and second sweep written | uncommitted | `AUDIT_2026-10-29.md`; this list created |
| 2026-10-29 | 0.1 and 0.6 audit tool built | uncommitted | `story2/audit.py`, `story2/lexicon.py`, `GET /api/plans/{id}/audit`, "Audit scorecard" card on the plan screen, `tests/test_audit.py` (8 pass); reproduces audit numbers on `pl-0b7cead5` (15% questions, 6 places, 12 scenes over 12 s, 56% identical prompt share, voice gaps 6.9 s, video LUFS -25.6, drop points 4:00, 5:30, 6:30, 7:00) |
| 2026-10-29 | 0.2 bench, 0.3 per-task sampling, 0.4 pipeline version built | uncommitted | `story2/bench.py` (baseline saved to `data/bench/baseline-2026-10-29.json`), `story/settings.SAMPLING` + `sampling()` (temperature per task, optional fields only after a probe; connection test probes `top_p`, penalties), `JsonCaller` passes `params` to backends that accept it, `story2/version.py` (`PIPELINE="q1"` for now, stamps on narration and storyboard, `style_info` flags), tests `test_bench`, `test_sampling`, `test_version` (all pass). Settings-page field for sampling deferred (PUT /api/settings accepts `sampling`). Note: `tests/test_phase2a.py::test_edit_one_segment_leaves_others_and_locked_survive_regeneration` already failed before these changes (full rewrite resets approved segments); not caused by this work |
| 2026-10-29 | M1 (1.1 to 1.10) built | uncommitted | 1.1 `planner.closing` (no English next-hook line; hook only if Hinglish and a series follows). 1.2 `_ambient_hint` (no bystander line over a quiet scene; crowd exclusion said positively). 1.3 `_subject_lead` (the person, not the place, is the main subject). 1.4 scene `style` from the plan's style, `facts` only for chart scenes (the "must be clearly visible: X is in Y" lines are gone); prompt template trimmed. 1.5 `story2/safety.py` guard: no cheerful voice tag and no smile cue over death or injury (`mood.GRAVE_MARK`, `scrub_scene`, `guard_tags`). 1.6 name map (`plan.settings.name_map`, default victims_and_suspects, applied in `planner._story_for`), attribution rule in the narration prompt plus a send-back check, `private_name` and `attribution` validation issues, `PATCH /api/plans/{id}/settings` takes `anonymise` and `name_map` (no screen card yet). 1.7 auto-run no longer sets edit mode without sheets (plain is stated; edit chosen by hand makes the sheets first; "drawn plain" warning on the Scene pictures card). 1.8 `story3/audiofix.py` (dead air trimmed to 0.40 s, planned pauses kept; 104 s take to 77 s in the trial on the real take), used in `voice.generate`, `voice.retrim` + `POST /api/media/{plan}/voice/trim` + "Remove blank pauses" button. 1.9 `loudnorm` to -14 LUFS in `video.build` (falls back without it on silent audio), video `inputs_hash` includes it, `meta.audio` measured after each build. 1.10 thumbnail face = main person (gender, age, look), one face, read-back rejects extra words, 3 tries. New tests: test_safety, test_audiofix, test_prompt_fixes, test_closing, test_names_and_attribution, test_thumbnail_fixes; test_auto and test_phase2b updated for the new behaviour. Existing film `pl-0b7cead5` was NOT changed: press "Remove blank pauses" on its Voice card, then rebuild the video |
| 2026-10-29 | M2 core built: 2.1 to 2.7, 2.15, density part of 2.16 | uncommitted | `story2/material.py` (+ `MATERIAL` prompt; leak-checked paraphrase pack, name map applied to passages, manual items survive, `POST/PUT /api/plans/{id}/material`, "Story material" card), auto-run stage `material` (inert until `version.PIPELINE` is raised to "q2": a plan made before it needs no pack), blueprint v2 (`use`/`show`/`turn`/`reward`/`question`/`answer_beat`/`payoff_position`, `BLUEPRINT_MATERIAL`, `material.blueprint_problems`), `story2/narrate2.py` (draft, edit, tag passes; `TextCaller` in `story/llm.py`; checks: banned phrases, question budget, details told, attribution, script rules, repeats, length, new-word share >= 40%, dead stretch > 7 sentences, audience profile), `lexicon.PROFILES` (metro_hinglish, hindi_first, senior_friendly; `PATCH settings audience`). Narration v2 runs when a plan has a pack and a blueprint that names details; older plans keep the one-call path. Tests: test_material (9), test_narration_v2 (7), test_language_profiles (6). NOT yet run on the real model: that needs the gateway (bench 2.13) |
| 2026-10-29 | M3 core: events ledger, event-driven registry, director, scenes; scene cap; life-stage ages; world warnings | uncommitted | `story2/events.py` (+ `EVENTS` prompt: one filmable moment per run of sentences, grounded in pack ids; checks: coverage, 8 s limit, no repeats, no run in one place, faces at most half, grounding), stage `events` in auto-run (inert for plans without a pack), `POST /api/plans/{id}/events`. Registry: with events it lists every distinct place (10 to 24), people in two or more events, hero objects, `life_stages` (`REGISTRY_EVENTS`). Director: exactly one shot per event, shot kind taken from the event, `director.current` also checks the events key. Storyboard: with events the prompt carries the event list, one scene per event (sentences and `event` id forced from the event, shot number = event order, period copied), `build_scene` stores `event`; `storyboard.split_long` (8 s, `plan.settings.max_scene_s`) splits long scenes at sentence boundaries into variants with another distance, angle and move (`variant_of`); `describe.stage_for` + `person_view(..., year)` draw a person at the age of the scene's year; `validate_storyboard` reports the world rules (places, top place, people share, face-free share, protagonist share, face close-up run) as warnings for event plans. Tests: test_events (6), test_chain_v2 (4: the whole chain on the fake model), test_split_long (3), test_life_stages (4). Not done: slim scene schema (the old 40-field schema is still asked), repair sweep for the world rules, regional table and inserts (3.12), era table (3.13), act camera and POV (3.14), evidence cards (3.15), names matching the cast (3.16), maps (3.9), explainer grammar (3.8), text discipline (3.10), face-lock experiment (3.7: needs the GPU) |
| 2026-10-29 | 4.1 prompt v2 (first version) | uncommitted | `imgprompts.compile_qwen_v2` for every scene that shows an event (`compile_qwen_auto` picks it): one paragraph of about 120 words (who does what, the place and what is visible, period and light, camera in plain words, the feeling as what face and body show, one style sentence, blank signs, the safe area); no constraints block, no "must not appear" list, no repeated framing paragraph; charts keep the old form; the validator no longer asks v2 prompts for exclusion, style and left/centre/right coverage; scenes without an event keep the old prompt. Tests in test_chain_v2. The prompt-format bench (4.3) on real pictures is still open |
| 2026-10-29 | 2.10 closing question; first part of 2.14 and 2.17 | uncommitted | The last beat must answer the central question, end on one image, then ask one open question (`planner.closing`). The blueprint can carry an `experience` object (`BLUEPRINT_EXPERIENCE`: promise, stake, clock, clue device, set piece, participation, afterimage, signature graphic, structure form); `narrate2.experience_lines` passes the stake, clock, clue, set piece and pause-and-guess to the beat they belong to. Still open for 2.14: a validator for the design and its use by the director, graphics and audio; for 2.17: the held pause-and-guess in the video |
| 2026-10-29 | Viewer, uniqueness, world size and Indian persona audit added | uncommitted | audit section 14; tasks 0.6, 2.14 to 2.17, 3.11 to 3.16, 5.9, 6.7, 7.7, 8.7 to 8.9 added; exit criteria of M2 and M3 extended |
| 2026-10-29 | Build run: rest of M2, M3, M4 to M8 | uncommitted | See "Build summary" below. Bench on the real model (science story): stock phrases 17 to 1, questions 9% to 6%, distinct places 5 to 12, new-word share 0.39 to 0.62. Real-model findings fixed in code: ids written into `facts` (blueprint repair), Hindi in Latin letters (detector, transliteration pass, prompt), pack ids spoken aloud ("M thirteen"), danda treated as part of a word in the safety rules (accusations and grave words were missed at sentence ends). |

## Build summary (2026-10-29)

Built and tested on the fake model, not on real pictures, voice or music: everything marked `[x]` above. Marked `[~]` or `[!]`: see the status line under the task. Not started: 7.3, 7.4, 8.4 and all of M9.

New modules: `story2/` hindigate, names, region (+ data/regions.json), inserts, era, analogies, worldfix, claimcheck, titles, variety, gates, judges; `story3/` cards, audio, dupes, publish; `story/reach.py`.
Behaviour that now differs from before: plans are made at pipeline q2 (material, three-pass narration, events, v2 prompts); auto-run has stages material, events, title and publish and quality gates after narration and storyboard (`gates.mode` strict by default, set `warn` to continue); the finished video has phrase captions, a sound bed under the voice, chapter flashes, year labels, era colour grade and a 4-second end card; the thumbnail headline is written in code.
