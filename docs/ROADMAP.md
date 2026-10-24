# Roadmap: from here to a published video

Written 2026-10-24. Read [APP_GUIDE.md](APP_GUIDE.md) first (what exists, how it is built, owner rules). Status: Phase 1, Phase 2 and Phase 3 batches E (voice) and F (reference pictures, with scoring) are done and committed. The detail of Batches E and F is in [phase3_plan.md](phase3_plan.md).

## Start a new chat: paste this

> Project: Source-to-Story at D:\yt-log (FastAPI + SQLite + vanilla JS, branch master, app on port 8905 under watch.py). Read docs/APP_GUIDE.md and docs/ROADMAP.md first, then docs/phase3_plan.md. Phase 1 and 2 and Phase 3 batches E (voice) and F (reference pictures) are done. Build Batch G (scene pictures) next, in small batches, each tested with fake gateways and connected to the plan screen (journey bar, Next bar, side-panel step, section) like the earlier batches. Owner rules are in the guide: nothing from the source carried forward, first-person narrator, 16:9 long-form, voice Svara hi_male only, Hinglish mixed script, licences are not a blocker. Model gateway is at 127.0.0.1:8810 (one request at a time); do not restart the app while a job runs. The real plan is pl-840b02a0.

## Things the user must decide or do (none blocks Batch G)

1. **Rewrite the real plan's narration into the new Hinglish style** (one emotion per part), then redo storyboard, prompts, review, approval, export and voice (about 26 minutes). Its emotional-coherence score is 4 until then. Recommended before the final video; fine to postpone while building G, H and I, because those batches read whatever the current plan is.
2. Run **Make reference pictures** and **Approve the best** on the real plan (about 8 minutes).
3. Verify the story's facts independently (they are marked unverified) and set the narrator name.
4. Delete the three empty draft test plans.

## Remaining Phase 3 batches

Each batch: build, test with fakes, run once for real on three items, then the full run; connect to the screen; commit.

### Batch G: scene pictures

Goal: one approved picture for each of the 50 scenes (plates for chart and document scenes included), made from the compiled prompts.

- **Read** each scene's compiled prompt (live from the plan, after confirming the saved export is current): plain generation, or, where the prompt is in edit mode, reference-conditioned edit with the approved reference pictures (`/v1/images/edits`, multipart, first image is the one edited, up to three references, no masks; written as "change X, keep Y").
- **Model per scene** comes from the plan's image-model settings (default `qwen-image-2.1`, optional per visual type and per scene). Group requests **by model** to limit swaps (about 20 s each).
- **Three-scene trial first** (an opening, a character scene, a plate): generate each on both models and show them side by side with the exact prompts, so the editor picks the default model before the 50-scene run. The risk register says no Phase 2 prompt has been judged on real output yet; this is where that happens. Expect to refine prompt wording from what is seen.
- **Per scene:** candidates (default 1, more on request), approve, "Draw again" with a new seed, and "Correct this" (an edit that says what to change and what to keep). Approved scenes survive "generate all".
- **Scoring** like Batch F, reusing `story3/refscore.py` ideas: measured (blank, blurry, shape, edges) plus a vision look against the scene brief (subject, action, setting, lighting, **extra people or objects not in the brief, text or marks in the picture, anatomy**), with a flag for **continuity** against the approved reference of any asset in the scene. One 0-100 ranking score with its parts; hard problems never auto-approved. "Approve the best" for all open scenes, as in F.
- **Sizes:** 1344x768 for 16:9 (within 2,359,296 pixels, multiples of 16).
- **Storage:** `data/media/<plan>/scenes/<scene>-aN.png` through `story3.store` (`kind scene_image`, one approved per scene); meta records model, prompt, seed, size, seconds, references used, score.
- **Validity:** a picture records the scene's `source_hash` (prompt) and the references' ids; if the scene or a reference changes, the picture is marked old.
- **Time:** about 1 to 2 minutes per picture, so a full 50-scene run is 1 to 2 hours on one GPU: per-item saves, resume, and a clear estimate on the button.
- **Screen:** journey step "Scene pictures", Next prompt, side-panel step, a Scene pictures section (grid by time, filter by "needs a picture / needs a choice / done", side-by-side compare, approve best).
- **Tests:** fake gateway (generation and edits), grouping by model, edit mode sends references in order, failures recorded, resume, approved scenes untouched by "all", validity on prompt change, scoring and bulk approve rules.

### Batch H: built graphics (the 20 chart, document and screen scenes)

Goal: the scenes whose export says `needs_asset` are drawn by code from verified facts, on top of the Batch G backdrop. No invented data, ever.

- **Templates (Pillow, Nirmala UI for Devanagari):** stat card (one verified number and its label), dated timeline (events whose date the story states), two-number comparison (before/after), text or title card, and a simple line or bar chart **only** when the facts give every point.
- **Inputs:** each scene's `overlay` spec (what it must show, text, facts) plus the story's public facts. A scene that wants a full price chart but has only one number gets a stat card, and the screen says why.
- **Rule:** every number on a card must exist in the facts (tested). Text must fit the frame in both scripts. Colours come from the plan's style asset.
- **Output:** a 1920x1080 still (and optionally a short animation spec for Batch I: count-up, line draw). Stored as `kind graphic`, approved like pictures.
- **Screen:** a Graphics section listing each plate scene with its card, the facts used, regenerate and approve.
- **Tests:** numbers traceable to facts, fallback card when facts are thin, text fit, Hinglish rendering.

### Batch I: assembly and draft video (ffmpeg)

Goal: a watchable 1080p MP4 and a checklist of what is missing.

- **Timeline** from the retimed scenes: each approved picture or graphic becomes a clip for exactly its duration, with a slow, varied zoom or pan chosen from the scene's `motion_intent` (never the same move twice in a row), cuts at scene boundaries, short dissolves only where the scene says so.
- **Audio:** approved (else latest valid) voice parts joined in order; scene times already match them (Batch E). Pauses between parts as in the plan.
- **Captions** from the narration sentences, Hinglish, burned in with libass in Nirmala UI, optional and styled for a 16:9 safe area.
- **Output:** 1920x1080 H.264 + AAC draft, and a low-resolution preview for quick checking; the same job at higher quality for the final render.
- **Checklist before building:** missing or unapproved audio and pictures are listed, never skipped silently; a "build anyway with placeholders" option marks the gaps.
- **Screen:** a Draft video card with progress, an in-page player, download, the checklist, and the total length against the plan.
- **Tests:** timeline length equals audio length (ffprobe within tolerance), every scene appears once and in order, missing media reported, caption timing from sentence times.

## Phase 4: make it a good YouTube video (not built, not planned in detail)

Order of value, each its own small project:

1. **Quality pass on the draft:** watch it, then fix the weakest scenes (redraw, correct, retime); a "weakest scenes" view from the scores; per-scene regenerate without disturbing the rest.
2. **Music bed** from the gateway's music model (`minimax-music-3`, `yue2-3b` listed): a quiet instrumental per beat mood, mixed under the voice with ducking.
3. **Title, description, chapters and tags** from the plan (working title is marked "working" today), written in the narrator's voice, no source mentions; thumbnail brief and a thumbnail image from a built template plus a generated backdrop.
4. **Final render settings and a publish checklist** (the export already records a checklist; add fact verification, narrator name, music licence note).
5. **Vertical 9:16 cut** as its own plan (composed, not cropped), shorter, with captions in the lower third.
6. **Upload and analytics** (YouTube API) and a learning loop: which openings and lengths hold viewers.

## Phase 5: running it as a channel (ideas)

- A queue of sources and a calendar; one story per run; all steps resumable.
- Reusable series assets (a recurring narrator avatar, a house style, intro and outro cards).
- Multi-voice or multi-language versions.
- Cost and time dashboard from the gateway metrics (`serve_metrics.db`).

## Decisions already made (do not re-open without the owner)

- Hinglish mixed script; Svara `hi_male` only; one steady emotion per part.
- 16:9 first; verticals separate.
- Licences are not a blocker.
- No source carried forward; charts and documents are built by code from verified facts only.
- Draft quality first: small batches, each visible on the screen, each with tests.
