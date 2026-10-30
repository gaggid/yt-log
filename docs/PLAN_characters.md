# Plan: Character Studio (a reusable cast library) and the Shorts pipeline built on it

Written 2026-10-30. Status: plan only, nothing built. Wait for the owner's go and the answers in section 12 before C1.

## 1. Goal

A new top-level module, **Characters**, where the owner designs a character once, develops it (outfits, ages, expressions, poses, environments) with the Qwen image and image-edit models, saves it in a library, and reuses it everywhere: first in Shorts (idea + chosen cast, storyboard of stills built from the cast by image edit, then Wan animates), later in long-form plans and in Remix.

Non-goals for v1: training LoRAs, 3D, face-swap on real people, cloud sync, multi-user permissions, anything that uploads.

## 2. What already exists and is reused (do not rebuild)

| Need | Existing piece |
|---|---|
| Complete literal character description from slots (ethnicity, gender, age, build, skin, face, hair, eyes, top, bottom, footwear, accessories, expression), vague-value detection, Indian default, hidden slots by shot distance | `story2/describe.py` |
| Image models and what each can do (Qwen Image 2.1 default, FLUX.2 Klein 9B restricted licence, any other model the gateway lists; edit support, max 3 reference pictures, no masks, no negative prompt on Qwen, size multiples of 16, 2.36 MP cap) | `story2/providers.py` |
| Draw (`/images/generations`) and edit (`/images/edits`, multipart, first image is edited, up to 3 images), retries, 429/5xx handling | `story3/scenes.py` (`_post`, `_form`, `draw`), `story3/refs.py` |
| Style presets (filmic, gta, noir, concept ...), loras hook | `story2/styles.py` |
| Real, named person policy: silhouette unless a public figure is confirmed and a photo approved; photo is only a reference | `story3/likeness.py` |
| Picture checks: measurement + vision look against the brief | `story3/refscore.py` |
| Numbered attempts, never overwritten, one approved per key | `story3/store.py` (`media` table) |
| One background job at a time, progress, cancel | `story2/jobs.py` |
| Voices (Maya, Veena, Svara) | `story2/voices.py` |
| Shorts: shot list, `still` prompt per shot, `shorts/stills.py`, storyboard (contact sheet), Wan clips | `shorts/` |

## 3. Concepts

- **Character**: one identity. Name, kind, the slot description (the "identity"), style, personality line, optional voice, tags, notes, status (draft, ready, archived). Reusable across any number of projects.
- **Canon**: the approved pictures that define the face and body: a face close-up, a full-body front view, a three-quarter view. Canon is what every later request is conditioned on. Changing canon bumps the character's **version**; anything made with an older version shows "made with an older version" (same idea as the hash checks in the rest of the app).
- **Look**: a named variant of the same person (Office, Rain jacket, Wedding, Age 60). A look overrides only the wardrobe and age slots (top, bottom, footwear, accessories, hair style, age, expression) and has its own approved picture(s). The face never changes between looks.
- **Gallery**: every picture ever made for the character, as numbered attempts with **lineage** (which picture it was edited from, which instruction, which model, which seed). Nothing is overwritten.
- **Place** (environment): same machinery as a character with the `place` slots from `describe.py`. Needed because "put the character in different environments" needs a place reference. v1 ships person + place; props follow with no new engine.
- **Cast** (in a short): the list of characters chosen for one short, each with the look to wear, plus an optional place.

## 4. The studio (what the owner can do)

### 4.1 Create (five ways in)

1. **From an idea**: one line ("a tired night-shift courier, thirty, quiet humour"). The chat model fills every slot with concrete values (same rule as the registry: no vague words), the owner edits the slots, then draws four candidates and picks one.
2. **From slots**: the slot form directly; each slot has a "suggest" button and a gap indicator (`describe.missing`).
3. **From a picture**: upload a photo or drawing; the vision model reads it into slots; the picture becomes a reference for the first sheet. Rights box required ("this is my own, invented or licensed character, or a person who agreed"). A real named person goes through the existing likeness rule; without a confirmed public figure it is refused or drawn as a silhouette.
4. **From a long-form plan**: "Save to library" on an approved asset of a plan (description + approved reference picture).
5. **Duplicate and fork**: copy a character and change it (a sibling, a younger version).

### 4.2 Develop

- **Generate**: N candidates (default 4) from the compiled prompt on Qwen (default) or FLUX Klein (a warning shows its licence status; export of FLUX pictures to a monetised video needs an explicit confirmation). Seed lock, model compare (same seed and prompt on two models side by side), size chooser (portrait, square, landscape, sheet).
- **Edit with Qwen image edit**: choose a picture, write an instruction ("change the jacket to dark green", "make him fifty", "angry expression", "look over the left shoulder", "put him in a crowded railway station at dusk"), optionally add up to two more reference pictures (the gateway takes three in total). Result is a new numbered picture with lineage. Presets for the common edits (outfit, hair, age, expression, pose, lighting, time of day, weather, background, style). A **keep list** is added to every edit instruction ("same face, same hair, same build") built from the slots, because the gateway has no masks.
- **Edit from canon, not from the last result**: the default base for a look or pose is the canon picture, because chains of edits drift. A chain-depth badge warns after three hops and offers "rebuild from canon".
- **Character sheet**: front, side, back, three-quarter, plus an expression set (neutral, smile, angry, worried, surprised, laugh) and a hands/prop-holding set, each its own picture at full resolution (the long-form sheet packs four views into one image, which costs resolution; the studio makes them one by one from canon by edit, then shows them as a sheet).
- **Dress from a clothes picture (try-on)**: upload (or pick from the wardrobe library, or draw with Qwen) a picture of a garment or a full outfit, and the character wears it. The request is a Qwen 2.1 edit with two references, [character full-body canon, garment picture], and the instruction "dress the man from the first picture in the clothing shown in the second picture, exactly as it appears: same colours, fabric, embroidery and cut; replace his old clothes completely; keep the same face, hair and build; keep the pose and background". Options: whole outfit or one piece only (top, bottom, footwear, accessory, head-wear), a second garment picture for another piece (three references in total with the canon), and a text line for what the picture does not show. Garment pictures are saved in a **wardrobe library** (name, tags, a flat-lay thumbnail) and reusable on any character; a garment photographed on a person is accepted, and the instruction then says to copy the clothing only, never the person. The result becomes a numbered picture with lineage and can be saved as a **look** (the look stores the garment picture, so it can be re-made on a new canon version). Garment pictures carry the same rights box as other uploads (own, licensed or invented); brand logos and printed words on the garment are left as drawn but never prompted. Tested in C0 (`--only tryon`) before it is built.
- **Realism and LoRAs**: every character has a **render style** (a preset from `story2/styles.py`, plus a new `photoreal` preset: photograph wording, natural skin texture, real lens and light, no painted/illustrated words) and a **LoRA set** (up to four, strength -2 to 2, the gateway's limit). The picker is filled from `GET /v1/images/loras?model=...` (name, default strength, trigger words); trigger words are added to the prompt for you; strength is a slider; "Realism" is a one-click preset that picks the realism LoRA and a tested strength. The LoRA set is locked per character (canon, looks, edits and the Shorts stills of that character use the same set), because a canon drawn with a LoRA and shots drawn without one do not look like the same person; the set is part of every request hash. Files are attached to the model by the gateway owner in the gateway console, not from this app; the screen says which LoRAs the gateway lists and, when no realism one is attached, says so. Facts today (checked 2026-10-30): Qwen Image 2.1 lists only `qwen2.1-detail-fix-2.0` (on by default); FLUX Klein and z-image list none; an earlier note records `change_to_raw_photo_v3_qi21` on disk but unattached, which is the realism candidate. The docs show `lora` only on `/images/generations` (and an inline `<lora:name:0.8>` tag in the prompt); whether `/images/edits` honours it is unknown, so C0 tests both (`--only lora --lora NAME`) and the studio uses whichever works for edits.
- **Looks (wardrobe)**: create a look from a slot override + instruction, draw it by editing canon, approve it. Looks appear as chips everywhere a character is chosen.
- **Environments**: pick or create a Place, then **Place the character**: an edit request with references [character canon, place picture] and an instruction for pose, action, camera size/angle, light. Result goes to the gallery as a "shot".
- **Variation matrix** (power): rows = looks or expressions, columns = places or poses; one job draws the grid. Used for production-ready sets in one go.
- **Compare and restore**: before/after slider, side-by-side of any two pictures, restore any older picture as the working one, promote any picture to canon.
- **Prompt drawer** (power): see and edit the compiled prompt, the negative text (written into the prompt for Qwen), model, seed, steps, size; save a **recipe** (a named bundle of those) and apply it to any character; copy settings from any picture.
- **Regional fix** (power, later phase): select a rectangle, the app crops it with margin, edits the crop, and pastes it back with a feathered edge. This gives mask-like control without gateway mask support.
- **Consistency check**: after each generation or edit, the vision model compares the new picture with canon against the slots (hair colour, clothing colours, age, build, distinguishing marks) and returns pass/warn with reasons; "Redo drifted ones" re-runs only those.
- **Library**: grid with search, tags, collections ("Series A cast"), favourites, archive, status filters; export/import a character pack (JSON + pictures in a zip) for backup and moving between machines.
- **Voice and personality**: optional voice (engine + voice from `voices.py`) and a personality line that the narration/shot planner can use. A "hear a line" test button uses the existing TTS.

### 4.3 Safety, rights, licence

- Real named person: existing rule; photo only a reference; nothing used before approval.
- Safety checks (`story2/safety.py`) on prompts; no brand or game names; no readable text in pictures.
- Every picture records model, licence status of that model, and whether a user photo was used; the export of a short lists these.

## 5. Data model

New package `characters/`, router `/api/characters`, static page `#/characters` with `static/characters.js` (no framework, served uncached like `plan.js`).

- Table `chars(id, name, kind, status, data JSON, created_at, updated_at)`; `data` holds slots, style, personality, voice, tags, collection, notes, canon (item ids), looks (list of `{id, name, overrides, approved_item}`), version, rights flags, recipes.
- Pictures are `media` rows (`plan_id` = the character id, like shorts) with kinds `char_gen`, `char_edit`, `char_sheet`, `char_shot`; `meta` carries `parent` (item id), `op` (generate, edit, look, place, sheet), `instruction`, `prompt`, `model`, `seed`, `refs` (item ids), `identity_hash`, `check` (consistency result).
- `identity_hash` = hash of the slots that define the face + the canon item ids. Pictures whose hash differs from the current one are marked "older version" but kept.
- Places use the same tables with `kind = "place"`.
- Request builders live in one place (`characters/requests.py`), like `shorts/pipelines.py` for Wan, so the hash of a request is computed where it is built.

## 6. The connected pipeline: Shorts from the cast

### 6.1 Flow (human checkpoint at each stage)

1. **Idea + cast.** In Shorts: write the idea, then **choose characters from the library** (one to three, each with a look) and optionally a place. Tone, pipeline, voice as today.
2. **Plan.** The planner receives the cast block (slot description, personality, look) instead of inventing a main character. It writes beats and shots; each shot names **which cast members appear** (a list of character ids, replacing today's single boolean `character`) and the place.
3. **Shot list.** As today, plus per shot: who, which look, `still` prompt (what the frame shows), camera size/angle, expression.
4. **Storyboard (the new centre of the flow).** For every shot the app builds an **image-edit request** with the canon pictures of the characters in the shot (and the place picture) as references (maximum three), and an instruction prompt: who stands where, doing what, camera, light. Shots without a character use plain text-to-image. The contact sheet shows one picture per shot; per shot the owner can approve, redo (new seed), edit the still prompt, **fix with an instruction** ("jacket red", "look at camera", "remove the second person") which runs the same edit tool on that picture, replace with an upload, or swap the look.
5. **Consistency gate.** The vision check compares each storyboard picture to canon; drifted shots are flagged and can be redone automatically up to a limit.
6. **Animate.** Approved stills go to Wan (5B or 14B image-to-video) exactly as in the current Shorts pipeline; voice, stitch, captions unchanged.
7. **Remix** (Animate) takes the character picture from the library instead of an upload.

Shots with two characters use two canon pictures plus the place; a third character in the same frame is refused by the checks (gateway limit), with the fix "split into two shots".

### 6.2 What changes in `shorts/`

- `shorts/stills.py`: `request()` becomes edit-aware: if the shot has cast members, build a multipart `/images/edits` request from library references; else the current text request. The hash includes reference item ids and the characters' versions, so a canon change marks stills "made with an older version".
- `shorts/store.py`: `plan.cast = [{character_id, look_id, role}]`; shot field `cast: [ids]` (keep `character` boolean readable for old shorts).
- `shorts/prompts.py` / `planner.py`: the plan prompt takes the cast block as fixed; shots use ids; the leak/safety checks stay.
- `shorts/checks.py`: block more than two characters plus a place in one shot; block a cast member whose canon is missing; warn when the character's style differs from the short's look.
- `static/shorts.js`: cast picker (library chips) at creation, cast row in settings, "fix with instruction" and "swap look" on storyboard cards.
- Long-form later: import a library character into a plan's registry as an asset with its approved reference (skips reference generation); export an approved plan asset into the library.

## 7. Gateway facts that shape the design (confirm in C0)

- One request at a time per key: the studio shares the app's one-job lock; the screen shows the queue and an estimate (about 60 s a picture on Qwen until measured), and a studio job blocks long-form jobs while it runs (as Shorts does).
- Edit takes up to three images, no masks; negative prompt has no effect on Qwen (cfg 1), so exclusions are plain sentences in the prompt.
- Sizes are multiples of 16 with a 2.36 MP cap; the portrait default is 720x1280 for stills and 1024x1024 for portraits.
- FLUX Klein 9B is listed as non-commercial; it stays selectable but flagged.
- Qwen Image 2.1 is what the gateway has today; the model list is read live (`providers.refresh`), so a newer Qwen appears in the selector without code changes.

## 8. Risks and answers

| Risk | Answer |
|---|---|
| Identity drifts across edits and across shots | Edit from canon by default; keep list in every instruction; canon pack of three pictures as references; consistency check with auto-redo; chain-depth warning; measure real drift in C0 |
| Only three reference pictures per edit | Two characters + place is the ceiling; the checks say so; split shots otherwise |
| No masks | Keep list + regional crop-edit-paste in C5 |
| Edit changes more than asked (background, framing) | Instruction templates that state what must stay; before/after compare; cheap redo; presets tested in C0 |
| Queue blocks everything while a batch runs | Batches are one job with cancel; each picture saved on arrival; estimate shown before start |
| Style mismatch between characters in one short | The short has one look; "restyle" is an edit op; the check warns |
| Licence of FLUX output | Recorded per picture; confirmation before a FLUX picture is used in an export |
| Real-person misuse | Existing likeness gate and rights boxes |
| Library grows large | Search, tags, collections, archive; thumbnails generated once |
| Old shorts break when `character` becomes `cast` | Read both; migrate on first save |

## 9. Build order (small batches, each wired to the screen, tests on a fake gateway with `tests/shorts_fakes.py`-style mocks)

- **C0. Probe (no UI).** `python -m characters.probe`: edit fidelity on Qwen Image 2.1 (outfit, age, expression, pose, background changes with one, two and three references), seconds per picture at 720x1280 and 1024x1024, drift over 1, 3 and 5 chained edits, whether a second Qwen edit model exists, FLUX Klein edit behaviour. Writes `data/characters_probe/`. Settles the defaults in section 7.
- **C1. Library and generation.** Store, CRUD, slots form with suggest, generate candidates, approve canon, gallery with lineage, character sheet as separate pictures, library grid. First thing the owner can use.
- **C2. Edit tool.** Edit with instruction and extra references, presets, keep list, compare, restore, promote to canon, chain-depth badge, prompt drawer, recipes.
- **C3. Looks and places.** Wardrobe looks, place entities, "place the character", consistency check with vision, variation matrix.
- **C4. Shorts integration.** Cast picker, planner cast block, edit-based stills, fix-with-instruction, swap look, version staleness, Remix picture from the library.
- **C5. Power features.** Regional fix, pack export/import, collections, long-form import/export, voice test, bulk redo of drifted pictures.
- **C6. Auto-run.** "Make a character from an idea" in one click (slots, four candidates, stops at the pick); in Shorts, the cast-driven storyboard joins Auto-run and stops at the storyboard checkpoint as it does now.

Each batch: run the tests of the area; full suite before a commit. Update `CLAUDE.md` and `docs/APP_GUIDE.md` when C1 and C4 land.

## 10. Screen layout (production-studio feel)

- **Library**: grid of character cards (canon portrait, name, tags, number of looks, status, version), filters, search, "New character" with the five entry points.
- **Studio view**: left, identity (slots, style, personality, voice, rights); centre, large canvas with a history strip (lineage tree, click to branch from any picture) and compare mode; right, tool tabs: Generate, Edit, Looks, Places, Sheet, Shots. A bottom queue bar shows the running job, the estimate and Stop. The prompt drawer slides over the canvas. Keyboard: arrows move through the gallery, A approves, C sets canon, E opens edit, R redoes.
- **In Shorts**: library chips for the cast, a storyboard sheet with per-shot tools.

## 11. Time and cost

About a minute per picture on Qwen at these sizes (to be measured). A first character: four candidates, one pick, three canon views, six expressions, four looks is about 25 pictures, roughly half an hour of gateway time. A 12-shot storyboard from the cast is about 12 edits, roughly twelve to fifteen minutes, before any video.

## 12. Owner decisions (2026-10-30)

1. **Kinds in v1**: person + place. Decided.
2. **Real people**: the studio does NOT use the strict silhouette-only rule. A character may be made from the owner's own photo of a private person, behind a consent box ("this is me, or the person agreed, or the picture is licensed"). Consequences: the consent flag and the photo's origin are stored on the character and shown on every export; the existing `story3/likeness.py` gate stays for long-form plans (a real, named *public figure* in a story), and the studio only reuses its safety checks (`story2/safety.py`); nothing is uploaded anywhere; the photo stays on this machine.
3. **FLUX**: selectable with a licence warning. Decided.
4. **Cast size per shot**: two characters plus one place. Decided.
5. **Start**: C0 (the probe). Decided. Tasks and their status: [docs/TASKS_characters.md](TASKS_characters.md).

## 13. Research notes (2026-10-30, web; mostly community and vendor guides, no independent benchmarks) and what they change

Sources: [Segmind Qwen-Image prompt guide](https://blog.segmind.com/qwen-image-prompt-parameter-guide/), [Qwen-Image-Edit-2509 model card](https://huggingface.co/Qwen/Qwen-Image-Edit-2509), [dreampixelforge Qwen prompts](https://www.dreampixelforge.com/blog/qwen-image-prompts), [promptzone: keeping a character consistent](https://www.promptzone.com/bastien_korhonen/keeping-a-character-consistent-across-ai-image-generations-55io.md), [invideo turnaround FAQ](https://invideo.io/faq/how-do-you-create-a-multi-angle-character-turnaround/), [lemonlight consistent characters](https://www.lemonlight.com/blog/how-to-create-consistent-ai-characters/).

Findings that match the plan (no change): lock the character before making scenes; portrait first, then derive the sheet from the approved face; fixed identity text kept apart from scene text; one to three reference pictures per edit (model card: person+person, person+scene); edit from the canonical reference, not the last output, because identity decays over chains; check every later picture against the sheet; fixed seeds for comparing; approval gates between stages.

Adaptations to make:
1. **Name references by position in edit instructions** ("the man from picture 1 ... in the place from picture 2"), the pattern in the model card. C0 already tests this wording; keep it as the template for place-the-character and the Shorts storyboard.
2. **Prompt order for drawing**: subject first, then style, environment, light, extra effects (Segmind: "order matters"). `shorts/stills.py` currently puts the character block first and the framing/look last; the studio's compiler should use subject, action, environment, light, camera, look, then the exclusions sentence. Keep the character block as one fixed paragraph and never restate it in the scene part (restating gives the model two chances to disagree).
3. **Keep prompts short and concrete**: one to three sentences for the scene part; the long slot paragraph is the identity block, not the scene. Avoid praise words ("beautiful", "striking"): they carry no identity information (the slot validator `describe.VAGUE_VALUES` already rejects vague slot values; extend it to these words).
4. **Turnaround**: separate full-resolution pictures per view derived from the approved face (the plan's choice, confirmed); props and held objects stay out of the turnaround and go in separate gesture panels; outfits and props on their own sheets.
5. **Reference variety**: a close-up for the face, a full-body picture for proportions and clothes, a side profile; the canon pack is exactly that (three pictures, the gateway's limit).
6. **Gateway differs from public guides**: the guides assume cfg 4-5 with a real negative prompt; this gateway runs Qwen at cfg 1 (guidance-free) where a negative prompt has no effect, so exclusions stay as plain sentences in the prompt (already the case). Steps are fixed by the gateway (25 draw, 35 edit); the C0 timings are the budget.
7. **Open question for C0**: the card describes the 2509 edit model; the gateway lists "qwen-image-2.1". C0 measures what it really does with 1, 2 and 3 references; do not assume 2509 behaviour.
8. **Negative prompts**: model-dependent, taken from `providers.PROVIDERS[model]["negative_prompt"]`. Qwen Image 2.1 runs at cfg 1 on this gateway, so a negative prompt has no effect: exclusions are positive sentences in the prompt ("No text, no logo..."). FLUX Klein runs with guidance (cfg 4) and honours `negative_prompt`, so the studio sends one there (and keeps the sentence too). `shorts/stills.py` now does the same. Verify in C1 with a cheap A/B (same seed, with and without a negative, on Qwen) before relying on it.
