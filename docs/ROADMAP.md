# Roadmap: from here to a published video

Written 2026-10-24 (updated after the visual-direction change). Read [APP_GUIDE.md](APP_GUIDE.md) first (what exists, how it is built, owner rules), then [phase3_plan.md](phase3_plan.md) (batch details, the "Visual direction" section, measurements). Status: Phase 1, Phase 2 and Phase 3 batches E (voice) and F (reference model sheets with scoring) are done and pushed, plus the move to **illustrated story scenes** in a chosen style, slot-by-slot descriptions, and short English quoted text in pictures.

## Start a new chat: paste this

> Project: Source-to-Story at D:\yt-log (FastAPI + SQLite + vanilla JS, branch master, app on port 8905 under watch.py). Read docs/APP_GUIDE.md, docs/ROADMAP.md and docs/phase3_plan.md first (especially "Visual direction"). Done: Phases 1 and 2, Phase 3 batches E (voice) and F (reference sheets, scoring) and the illustrated-story direction (styles, characters before scenes, white-background model sheets, slot-by-slot descriptions, English quoted text). Build Batch G (scene pictures) next, in small batches, each tested with fake gateways and connected to the plan screen (journey bar, Next bar, side-panel step, section) like the earlier batches. Owner rules are in the guide: nothing from the source carried forward, first-person narrator, 16:9 long-form, voice Svara hi_male only, Hinglish mixed script, on-screen text English only, licences are not a blocker, never name a game or brand in a prompt, the image models do exactly what is written so descriptions must be complete. Model gateway is at 127.0.0.1:8810 (one request at a time); do not restart the app while a job runs. The real plan is pl-840b02a0. Caveman mode may be on: write docs, code and commits in normal prose.

## What the user does now (none of it blocks building Batch G; all of it is needed for the real video)

1. **Restart the app once** (loads the latest code) and reload the plan page.
2. Plan page, in order: **Create characters and places** (about 1 minute), **Fill in the gaps** if any slot is listed, **Make reference pictures** (about 8 to 10 minutes), **Approve the best**, then **Redesign scenes in the chosen style** (about 12 minutes; replaces the old chart scenes, keeps narration and voice). Read the new storyboard before approving it.
3. Re-run Check, Review, Approve and Export (the plan hash changed with the new scenes).
4. Decide whether to **rewrite the narration** into the new Hinglish style with one emotion per part (the plan's emotional-coherence score is 4 until then). It means redoing the voice (about 26 minutes) and the storyboard; best done before the final render.
5. Choose the visual style on the Visual style card if the default (game-art) is not wanted. Do it before step 2.
6. Verify the story's facts independently and set the narrator name (both still open).
7. Optional clean-up: delete the three empty draft plans.

## Remaining Phase 3 batches

Each batch: build, test with fakes, run once for real on three items, then the full run; connect to the screen; commit; update the docs.

### Batch G: scene pictures

Goal: one approved picture for each scene (about 50), drawn from the compiled prompts, with characters that stay the same.

- **Read** each scene's compiled prompt live from the plan (the saved export must still be current for the plan hash).
- **Character consistency, decided by testing first.** Two ways, tested on three scenes: (a) plain generation from the full prompt, which already carries the complete character description (gave one consistent trader across three scenes), and (b) reference-conditioned edit (`/v1/images/edits`, multipart, first image is the one edited, up to three references, no masks, written "change X, keep Y") using the approved model sheets. Keep whichever holds identity and style better per scene type; record the result in phase3_plan.md. A model sheet is one reference slot, so up to three assets can be sent per scene.
- **Model per scene** from the plan's image-model settings (default Qwen; Qwen is the safer choice for quoted text; FLUX may repeat a word and adds unrequested crowd detail). Group requests by model to limit swaps (about 20 s each).
- **Three-scene trial first** (an opening, a character scene, a scene with quoted text), each on both models side by side with the exact prompts, so the editor picks the default before the full run.
- **Per scene:** candidates (default 1, more on request), approve, "Draw again" with a new seed, "Correct this" (an edit that says what to change and what to keep). Approved scenes survive "generate all".
- **Scoring**, reusing `story3/refscore.py`: measured (blank, blurry, shape, edges) plus a vision look against the scene brief (subject, action, setting, lighting, **people or objects that are not in the brief, text that differs from the quoted text, anatomy and hands, a character that does not match its description or reference sheet**). One 0 to 100 ranking score with its parts; hard problems never auto-approved; "Approve the best" for all open scenes as in Batch F.
- **Sizes:** 1344x768 (16:9, within 2,359,296 pixels, multiples of 16). Storage `data/media/<plan>/scenes/<scene>-aN.png` through `story3.store` (`kind scene_image`, one approved per scene); meta records model, prompt, seed, size, seconds, references used, score.
- **Validity:** a picture records the scene's `source_hash` and the reference ids; if the scene or a reference changes, the picture is marked old.
- **Time:** about 25 to 60 s per picture on Qwen (2 minutes on FLUX), so 50 scenes is about 30 to 60 minutes on Qwen: per-item saves, resume, an honest estimate on the button.
- **Screen:** journey step "Scene pictures", Next prompt, side-panel step, a Scene pictures section (grid by time; filter "needs a picture / needs a choice / done"; side-by-side compare; approve the best).
- **Tests:** fake gateway (generation and edits), grouping by model, edit mode sends references in order, failures recorded, resume, approved scenes untouched by "all", validity on prompt change, scoring and bulk approve rules.

### Batch H: built graphics (only scenes that need exact numbers or a real chart)

Goal: scenes whose narration states numbers that must be read (a price series, a comparison) get a chart or card built by code from verified facts. Far fewer than before: short numbers and labels are now drawn by the picture model itself, and the storyboard is told to keep chart scenes to at most one in six.

- Templates (Pillow, a font that covers English; Devanagari captions stay in Batch I): stat card, dated timeline, two-number comparison, and a line or bar chart **only** when the facts give every point. Colours from the style preset. A scene with too few facts falls back to a stat card and says why. No invented data points, ever.
- Output a 1920x1080 still (and an animation hint for Batch I: count-up, line draw); stored as `kind graphic`, approved like pictures; a Graphics section on the plan page.
- Tests: every number on a card exists in the facts; fallback card when facts are thin; text fits the frame.

### Batch I: assembly and draft video (ffmpeg 7.1.1 at `C:\Ffmpeg\bin`)

Goal: a watchable 1080p MP4 and a checklist of what is missing.

- Timeline from the retimed scenes: each approved picture or graphic becomes a clip for exactly its duration, with a slow, varied zoom or pan chosen from the scene's `motion_intent` (never the same move twice in a row), cuts at scene boundaries, dissolves only where the scene says so.
- Audio: approved (else latest valid) voice parts joined in order; scene times already match them (Batch E).
- Hinglish captions from the narration sentences, burned in with libass in Nirmala UI, optional, inside the 16:9 safe area.
- Output 1920x1080 H.264 + AAC draft and a low-resolution preview; the same job at higher quality for the final render.
- Checklist before building: missing or unapproved audio and pictures are listed, never skipped silently; "build anyway with placeholders" marks the gaps.
- Screen: a Draft video card with progress, an in-page player, download, the checklist, and total length against the plan.
- Tests: timeline length equals audio length (ffprobe tolerance), every scene appears once and in order, missing media reported, caption timing from sentence times.

## Phase 4: make it a good YouTube video (not built, not planned in detail)

1. **Quality pass on the draft:** watch it, fix the weakest scenes (redraw, correct, retime); a "weakest scenes" view from the scores.
2. **Music bed** from the gateway's music models (`minimax-music-3`, `yue2-3b`): a quiet instrumental per beat mood, mixed under the voice with ducking.
3. **Title, description, chapters and tags** from the plan (the working title is marked "working"), in the narrator's voice, no source mentions; a thumbnail brief and thumbnail picture in the chosen style.
4. **Final render settings and a publish checklist** (fact verification, narrator name, music note).
5. **Vertical 9:16 cut** as its own plan (composed, not cropped), shorter, captions in the lower third.
6. **Upload and analytics** (YouTube API) and a learning loop on openings and lengths.

## Phase 5: running it as a channel (ideas)

- A queue of sources and a calendar; one story per run; all steps resumable.
- Reusable series assets (a recurring narrator avatar, a house style, intro and outro cards).
- Multi-voice or multi-language versions.
- Cost and time dashboard from the gateway metrics (`serve_metrics.db`).

## Decisions already made (do not re-open without the owner)

- Hinglish mixed script; Svara `hi_male` only; one steady emotion per part.
- 16:9 first; verticals separate.
- Licences are not a blocker.
- No source carried forward; long charts and documents are built by code from verified facts only.
- **Illustrated story scenes** in one chosen style (default game-art illustration), faces and emotion, real named people only as silhouettes or shadows; on-screen text English only; no game or brand names in prompts.
- Descriptions are literal and complete (slot by slot); the registry reads the whole narration.
- Chat model stays `gemma4-12b-qat-uncensored-hauhaucs-balanced`; `qwen3.5-9b` and the MSFIT-9B-v8 entry were tested and rejected.
- Small batches, each visible on the screen, each with tests.
