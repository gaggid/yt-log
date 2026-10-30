# Tasks: Character Studio (plan: [PLAN_characters.md](PLAN_characters.md))

Tick a task when it lands. At the end of each batch compare with the plan section named in brackets and list what is not done. Keep checks short: run only the tests of the area changed.

## C0. Probe (no UI) [plan 7, 9]

- [x] C0.1 `characters/probe.py`: lists image models with capabilities; draws a base character (portrait 1024x1024 and full body 720x1280); times each picture.
- [x] C0.2 Edit tests from the base picture with one reference: outfit, age, expression, pose, new environment.
- [x] C0.3 Two-reference edit (character + place picture) and three-reference edit (character face, body, place).
- [x] C0.4 Drift chain: three edits in a row (each from the last) against three edits each from canon, both compared with canon.
- [x] C0.5 Vision identity check (chat model with vision, base vs result): same person yes/no, 1-10, differences. Used for C0.4 and as the prototype of the C3 consistency check.
- [x] C0.6 FLUX Klein edit test (one outfit change) when the gateway lists it; a second Qwen-like edit model if any.
- [x] C0.7 Run on the real gateway; saves pictures and `report.json` under `data/characters_probe/<time>/`, and writes `data/characters_probe/timings.json`.
- [x] C0.8 Short unit test of the helpers (prompt builders, report writer) on a fake gateway, no long run.
- [x] C0.9 Write the findings in `docs/RUN_LOG.md` and set the defaults for C1/C2 (sizes, reference count, whether edit-from-canon wins).
- [x] C0.11 Try-on test: character canon + a garment picture (flat lay drawn by Qwen, or the owner's own via `--garment`), identity and clothing fidelity; run after the main probe: `python -m characters.probe --only tryon`.
- [x] C0.12 LoRA test (done 2026-10-30, see RUN_LOG): attach a realism LoRA to qwen-image-2.1 in the gateway console, then `python -m characters.probe --only lora --lora NAME`: same prompt+seed with/without (`lora` field), and an edit with the inline tag; decide if edits honour LoRAs and the default strength.
- [x] C0.10 Compare with the plan: what C0 settled, what it left open (see the end of this file).

## C1. Library and generation [plan 3, 4.1, 5]  (built 2026-10-30, tests `tests/test_characters.py`, 11 pass on a fake gateway; not yet used on the real gateway from the screen)
- [x] store (`chars` table, media kinds `char_gen` / `char_sheet`), CRUD API (`/api/characters`), library grid (`#/characters`), studio screen (`#/character/<id>`)
- [x] slot form with gap indicator; "Fill in the details from the idea" (chat model, vague values sent back); create from idea / slots / picture (rights box + vision reads the photo into slots) / duplicate; places (kind `place`) use the same engine
- [x] generate candidates (Qwen or FLUX, 1/2/4 at a time, numbered attempts with seed, recipe and identity hash), approve canon (portrait + body), version bump, "older" badge when the description changed
- [x] character sheet as separate pictures: three-quarter, side, back, six expressions, each an edit of the canon with the keep list
- [x] render style + LoRA set per character: default `photoreal` + `purelens-realism` 0.7 with its trigger word (from the gateway listing, built-in fallback), picker from `/images/loras`, locked when canon is approved, unlisted LoRA refused before drawing
- [x] tests (fake gateway), CLAUDE.md entry
- [ ] not in C1 (deferred on purpose): model compare side by side and seed lock in the UI (the API takes a seed), the vision consistency check (C3), prompt drawer and recipes (C2), real-gateway run of the screen

## C2. Edit tool [plan 4.2]
- [ ] edit with instruction and extra references, presets, keep list, lineage, compare, restore, promote to canon, chain-depth badge
- [ ] prompt drawer, recipes
- [ ] dress from a clothes picture (try-on): upload/pick a garment, whole outfit or one piece, second garment, text note, result saved as a look; wardrobe library of garment pictures (plan 4.2)

## C3. Looks and places [plan 3, 4.2]
- [ ] looks (wardrobe), place entities, place-the-character, consistency check (vision), variation matrix

## C4. Shorts integration [plan 6]
- [ ] cast picker, planner cast block, shot `cast`, edit-based stills, fix-with-instruction, swap look, version staleness, Remix picture from library

## C5. Power features [plan 4.2]
- [ ] regional fix, pack export/import, collections, long-form import/export, voice test, bulk redo of drifted pictures

## C6. Auto-run [plan 9]
- [ ] "make a character from an idea" in one click; cast-driven storyboard in Shorts Auto-run

## C0 compared with the plan (2026-10-30)

Done and settled:
- The probe exists, ran on the real gateway, and saved pictures, `report.json` and `timings.json`.
- Edit works with 1, 2 and 3 references at the same cost (about 90-125 s); two characters plus a place is feasible (plan 6.1).
- Identity holds through single edits and a chain of three; editing from canon stays the default as a safeguard, with the chain-depth badge (plan 4.2).
- Budget for estimates: draw 60-70 s, edit 90-125 s (Qwen), 170 s (FLUX). A first character of about 25 pictures is roughly 40 minutes, a 12-shot storyboard about 20-25 minutes (plan 11 said 15: raised).
- FLUX is the better fidelity on the outfit edit (plan 3 decision "selectable with a warning" stands).

Left open (do not assume):
- C0.11 try-on from a garment picture, and C0.12 realism LoRA (and whether edits honour `lora`): both need a run; the LoRA test needs the file attached in the gateway console first.
- The identity check is too lenient to gate anything; C3 must use a feature-by-feature rubric (and calibrate against pictures looked at by a person).
- Rendering drift (style gets glossier along a chain) is not caught by an identity check; the consistency check should also compare style/colour.
- C0.11 try-on: works (faithful garment transfer, identity kept). C0.12 LoRA: realism comes from the draw step only; edits keep the source's look; the `lora` field on edits is accepted but its effect is unproven; render style + LoRA set must be locked before canon (plan 4.2). Open for C2: restyle a painted character to photographic by an edit instruction.
- Whether a 2509-style edit model exists on the gateway: the listed model is `qwen-image-2.1` only; behaviour above is what it does.
