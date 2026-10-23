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

### Batch F: reference images
- For every recurring asset (person, place, prop) used in two or more scenes, build a reference prompt from its approved description and fixed attributes plus the plan's style, generate candidates (1 to 3 per asset, chosen model), and let the editor approve one.
- An approved image is stored in the asset's `reference_images` (the field Phase 2 already reads) and prompts are recompiled, so later scenes switch to reference-conditioned edit mode automatically (up to 3 references).
- Real people: only generic or explicitly fictional looks, as Phase 2 recorded; no invented likeness presented as real.
- Tests: reference prompt contains the fixed attributes; approval writes the asset record; recompiling then lists the reference; at most 3 per scene.

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
