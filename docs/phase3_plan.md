# Phase 3 plan: from the exported plan to a draft video

Status: plan saved 2026-10-24; built in small batches E to I, tested after each. Phase 2 ends at the exported file (`docs/plan_schema.json`); Phase 3 reads that file and produces media. Nothing in Phase 3 may re-decide editorial matters: wording, scene order, timing intent and prompts all come from the export.

## Owner decisions (carry forward)

- **Licences are not a blocker.** The image models are used as open-source models; every model starts "confirmed" and no warning or checklist item stops work. The export records it as an owner decision. (Done in Phase 2 code on 2026-10-24.)
- **Voice:** Svara `hi_male`, Hinglish script, one segment per request, seed 7, temperature 0.6, repetition penalty 1.25 (measured, see `phase2_plan.md`).
- **Format:** 16:9 long-form first. Vertical comes later and as its own plan.
- **No quotes from, and no pointers to, the source** in anything spoken, shown or generated. The export's leak gate already covers `public`; media steps never read `evidence`.
- **No music or publishing** in Phase 3. Music (the gateway has a music model) is a possible Phase 4.

## What exists on this machine (audited)

| Need | Found | Consequence |
|---|---|---|
| Voice | Svara through the gateway; real pace about 148 wpm; generation about 3.7x slower than real time; gateway `timeout_s` now 600 | A 7-minute video needs about 26 minutes of voice generation. Jobs must be background, resumable, per segment. |
| Images | `qwen-image-2.1`, `flux2-klein-9b` via `/v1/images/generations` and `/v1/images/edits` (3 references, no masks) | One request at a time on the gateway; switching models costs a swap (about 20 s), so generate in model batches. |
| Video assembly | ffmpeg 7.1.1 (essentials build) at `C:\Ffmpeg\bin`, `ffprobe`, Pillow 11, Nirmala UI font (Devanagari) | Stills with slow zoom, captions burned in with libass, mux, all local. |
| Gateway load | One concurrent request per key; Phase 1 and Phase 2 jobs share it | Media jobs reuse `story2.jobs` (one at a time, progress polling) and refuse to start while story processing runs. |

## Principles

1. **The export is the contract.** A media job names the export version it used and stores it with every file. If the plan changed after that export, the screen says so and asks for a new export before generating more.
2. **Every generated file is a candidate** until a person approves it. Regenerating one item never touches approved items. Nothing is overwritten: new attempts get new numbers.
3. **Record everything needed to repeat it:** model, exact prompt, seed, parameters, gateway answer, seconds taken. Same pattern as the Phase 2 preview.
4. **Resume anywhere.** A job saves each item as it finishes; a restart or Stop loses at most the item in flight.
5. **No fabricated evidence.** Charts, documents and screens are built from verified facts by code (Batch H), never drawn by an image model.
6. **The user is never lost.** Each batch adds its steps to the same journey bar, "Next:" bar and sidebar on the plan page; the plan page gains a Production section instead of a separate tool.

## Data

Files live under `data/media/<plan_id>/export_v<NNN>/` (`voice/`, `refs/`, `scenes/`, `graphics/`, `video/`). One table `media` (new, additive): `id, plan_id, export_rev, kind (voice|reference|scene_image|graphic|video), key (segment, asset or scene id), attempt, status (queued|running|done|failed), file, meta (JSON: model, prompt, seed, params, seconds, duration_s, error), approved, created_at`. A small package `story3/` holds `store.py`, `voice.py`, `refs.py`, `images.py`, `graphics.py`, `assemble.py`, `api.py`, mounted next to the Phase 2 routes.

## Batches

### Batch E: voice
- Read the export, send each segment's `annotated` text to Svara with the proven settings, one request per segment, as a resumable background job with progress and a time estimate learned from the first segments.
- Save the audio per segment; measure its real duration with `ffprobe`.
- **Retime to real audio:** scale each segment's sentence durations so they add up to the real audio length, then recompute every scene's start, end and duration (Phase 2 `retime`). This replaces the 148 wpm guess with measured time and keeps every scene aligned with its sentences.
- Screen: a Voice section with a player per segment, real duration, Generate or Regenerate, Approve, and "Generate all missing". Approved segments are skipped by "all".
- Tests (fake gateway): one request per segment; resume after a stop; regenerate keeps old attempts; retiming makes scene time equal audio time; approved segments are not regenerated; export-version mismatch is refused.

### Batch F: reference images (built 2026-10-24)
- **Who gets one:** a person, place or prop that appears in two or more scenes (`story3/refs.py: targets`). Style and the narrator placeholder never do; an asset shown once is created by its own scene. On the real plan that is four items: the stock chart (31 scenes), the trader (9), the cup-and-handle pattern (7), the earnings release icon (7).
- **Prompt:** built from the asset's description, fixed details, period and the plan's style asset, in the wording of the chosen model (Qwen: exclusions written in the prompt; FLUX: negative prompt). Person: whole body, neutral pose, plain backdrop, anonymous (back or profile) when the asset is a no-likeness person. Place: empty establishing view. Prop: one centred object. Always "no text, letters, numbers, logos". Sizes 1024x1344 (person), 1344x768 (place), 1024x1024 (prop). A leak check runs on every prompt before any request; a prompt carrying source wording is refused.
- **Candidates:** 2 per item by default (1 to 4), distinct seeds, saved as numbered attempts under `data/media/<plan>/refs/`. Each records model, exact prompt, seed, size, seconds. Measured on the real plan: Qwen about 52 s, FLUX about 125 s (includes a model swap) per picture.
- **Approval:** one approved picture per item. Approving writes it into the asset's `reference_images` and recompiles the image prompts, so scenes showing the item switch to reference-conditioned edit mode (at most three references per scene). Unapproving undoes it. **Skip** marks an item as not needing a reference (kept in plan settings, so it never changes the approved content).
- **Currency:** a picture records a hash of the description, fixed details, style and model it was made from; if any change, older pictures are marked old and do not count.
- **Approval is not disturbed:** reference pictures and recompiled prompts are derived data, so they are left out of the content hash (like timings). An approved plan stays approved and the latest export stays current; export once more at the end to put the references into the file.
- **Screen:** journey step "References", sidebar step 11, a "Next:" prompt, and a Reference pictures section with the candidates, full-size view, approve, skip, draw more and the exact prompt.
- **Tests:** `tests/test_phase3f.py` (24): targets, prompt content per model, one request per candidate, failures recorded, unreachable server, approval writes the asset and switches scenes to edit mode, siblings unapproved, plan stays approved, old pictures stop counting, leak refusal, skip and done state, API, measuring, scoring, best marker, bulk approve rules.
- **Scoring and bulk approval (`story3/refscore.py`):** every new picture gets a 0-100 score from two independent checks, both shown with reasons: *measured* from the pixels (blank, blurry, subject cut by the frame, backdrop not plain, subject too small or large, shape differs from the request) and *looked at* by the vision-capable chat model against the brief (six points 0-10, harsh instructions, a list of concrete defects, a text-visible flag; "slightly" and "minor" defects are shown but not penalised). Total is the mean of the two; a hard problem (blank, cut, text or marks) caps it at 49 and is never auto-approved. If the vision check is down the measured score stands alone and says so. Tested on the real trader pictures: the two good ones scored 88 each, a copy with the head cropped off 49, a copy with printed text and a box 49. **Approve the best** approves, per open item, its best current picture when it scores 70 or more and has no hard problem; the rest are listed with the reason. Chosen or skipped items are never touched. The score ranks pictures, it does not replace looking.
- **Known limits:** the asset `fixed` list is sometimes only attribute names ("clothing color"), which says little; rewrite it in Continuity as concrete values for stronger consistency. Abstract items (a chart, an icon) may be better skipped and built as graphics in Batch H.

## Visual direction (changed 2026-10-24, after the first look at real output)

The first plan drew the story as abstract charts and diagrams on plain backgrounds, which the owner rejected. The direction is now **illustrated story scenes**: people, places and moments that could really have happened, drawn like a graphic novel or a game loading-screen painting, with faces and emotion. Charts, documents and screens appear only when the narration states exact numbers or a document to read (at most one scene in six) and are then built by code (Batch H); elsewhere a chart is only an unreadable glow on a monitor inside a room.

- **One style per plan** (`story2/styles.py`): `gta` (default; bold outlines, cel-shaded colour with painterly gradients, saturated cinematic colour, strong rim light), `noir` (heavy ink, crosshatching, halftone, deep blue/red/amber) and `concept` (painterly game concept art). The choice rewrites the style asset in the registry and is written into every scene prompt (first and again as a closing reminder), both models, and every reference picture. Three sample pictures (same scene, same model, only the style words differ) are shown on the plan page. Tested on `qwen-image-2.1`: all three render well without any LoRA.
- **Do not name a game in a prompt.** Naming the game made the model print its logo on props. The prompts describe the look ("premium open-world action-game loading-screen key art, painted and graphic"); the game's name is only in the UI label.
- **Objects and places use a variant of the style text without "expressive faces"** (`object_look`); the character clause put faces and people onto screens.
- **LoRAs:** none needed. The gateway supports them (`/v1/images/loras`, a `lora` field on generate and edit; Qwen has `qwen2.1-detail-fix-2.0` on by default, FLUX has none, and `change_to_raw_photo_v3_qi21` is on disk but unattached and is the opposite direction). If a look ever drifts, download a `.safetensors` style LoRA, attach it to the model in the gateway console, then name it in `styles.LORAS` and it is sent automatically.
- **Characters are invented composite people with a face, hair, build and period clothing.** A real, named person is never given an invented likeness: only a silhouette, from behind, in shadow or by the hands (`fictionalisation: real_person_no_likeness`). The old "anonymous figure" wording is gone.
- **Order of work:** narration, then **characters and places** (the registry now reads the whole narration so nobody is missed, and the editor can add what is missing), then **reference model sheets**, then the storyboard, prompts, scene pictures. A plan whose registry or storyboard was made under an older direction or another style is flagged ("made for another look") and the screen leads through redoing them; **Redesign** replaces approved scenes too (locked ones are kept).
- **Reference sheets:** a person is one picture on pure white with the same person four times (front, three-quarter stride, seated or leaning, close-up face); an object is three views; a place is one wide view. One sheet is one reference slot, so up to three assets can condition a scene. Verified on the real model: the trader sheet is consistent across all four poses; an object sheet needed "no people, no faces, no emblems" to stop faces appearing on its screen.
- **Literal descriptions (the models do exactly what is written and invent the rest).** People, places and objects are described slot by slot (`story2/describe.py`): a person has gender, age, build, skin, face, hair, eyes, top, bottom, footwear, accessories and expression; a place has type, architecture, materials, light, objects with counts and size; an object has type, shape, material, colour, condition and markings. The registry model must fill every slot with concrete values; the description sent to the image models and the "always the same" details are composed from the slots, so none can be dropped. Empty or vague slots ("business casual", "various", "typical") are listed on the plan page with a "Fill in the gaps" button. Charts, graphs and documents are never accepted as drawable objects. Tested on the real chat model: every slot came back filled with concrete values.
- **Text in pictures.** Short English text written in quotes is drawn correctly by both models (tested: "STOCK FALLS 17%" on a newspaper, "-17%" and "Knight Capital" on a monitor; Qwen was exact every time, FLUX once repeated a word). So short quoted English text (up to 8 words, words and numbers from the facts only) goes into the prompt as `the words "..." ... spelled exactly as inside the quotes`, including on screens. Text that is longer, or not English (Devanagari is never drawn on screen), is left out of the picture and noted for a later overlay. Prefer Qwen for scenes with quoted text.
- **Storyboard model instructions** (`story2/prompts.py`) were rewritten: tell the story with pictures, prefer reconstruction, character, establishing, atmospheric and object scenes, no unrelated symbols (a runner, a train, a pillar), panel language (establishing wide, over-the-shoulder, close on eyes or hands, low and high angles, silhouettes, foreground framing), depth in every scene. Result on the real plan (first two parts, copy of the data): no chart scenes, a consistent recognisable trader across scenes, 12 scenes at about 25-40 s per picture.

### Batch G: scene images
- Generate each scene from its exported prompt: plain generation, or reference-conditioned edit (multipart, up to 3 references). Models are batched to limit swaps. `overlay_plate` scenes get their backdrop here.
- Per scene: candidates, approve, regenerate with a new seed, and a "correct this" edit that states what to change and what to keep (no masks).
- Quality guard: a cheap automatic check per image (size, not blank, aspect) and the prompt checklist shown beside the image; judgement stays with the editor.
- Tests: size and aspect honoured; failed requests are recorded and retried; edit mode sends references in order; approved images survive a regenerate-all.

### Batch H: built graphics
- Scenes whose export says `needs_asset` get their content drawn by code (Pillow) from the overlay spec and the story's verified facts, on top of the Batch G backdrop. Templates: stat card (one verified number and its label), dated timeline (events whose date the source states), two-number comparison, title or text card.
- Only what the facts support is drawn. If a scene wants a full price chart but only one number is known, it gets a stat card and the editor sees why. No invented data points, ever.
- Tests: every number on a card exists in the facts; a scene without enough facts falls back to a stat or text card and says so; text fits the frame with the Devanagari-capable font.

### Batch I: assembly and draft video
- Timeline from the retimed scenes: each approved image (or graphic) becomes a clip for its exact duration with a slow, varied zoom or pan (motion intent from the scene), cross-cuts only where the scene says so.
- Audio: the approved segment files joined in order; the scene times already match them from Batch E.
- Captions from the narration sentences (Hinglish), burned in with libass in Nirmala UI, optional.
- Output: a 1920x1080 H.264 draft MP4 with AAC audio, plus a "preview" low-resolution cut for quick checking. Final render is the same job at higher quality.
- Screen: a Draft video card with progress, download and a check list (missing audio, missing or unapproved images) so it never builds half a video silently.
- Tests: the timeline adds up to the audio length; missing media is reported, not skipped; ffprobe confirms duration within a small tolerance of the audio.

## After Phase 3

Possible later work, not planned in detail: music bed from the gateway's music model, a vertical cut-down plan, upload and publishing, analytics. Each is its own project.

## Risks

- **Time on one GPU.** About 26 minutes of voice plus image generation for about 30 scenes (speed not measured yet) means a full video is a long job. Mitigation: per-item saves, resume, model batching, previews of single items before "generate all".
- **Image quality is unproven.** No Phase 2 prompt has been judged on real output yet. Batch G therefore starts with a three-scene trial and a side-by-side before the full run.
- **Svara repeats or drops words occasionally** (one repeated word heard in testing). Mitigation: regenerate per segment, higher repetition penalty, and a real-duration versus expected-duration sanity flag per segment.
- **Hindi captions** depend on the font; Nirmala UI is present on this machine, so it works here but not on a machine without it.
