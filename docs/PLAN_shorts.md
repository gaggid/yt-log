# Plan: Shorts module (30-second 9:16 videos made with Wan 2.2 only)

Written 2026-10-29, revised the same day after the owner's answers (section 2). Status: S1 to S7 built on 2026-10-29 and tested on a fake gateway (`tests/test_shorts.py`); S0 (`python -m shorts.probe`) and the first real run are for the owner. Pipelines B and D, the vision check and the 704x1280 test on the 14B models are not built. Source of the model facts: https://llm.tripfick.com/docs (Wan 2.2 section). Numbers marked "docs" are from there; "estimate" are ours and must be measured in task S0.

> **Update 2026-10-30 (owner decision): start pictures come from the image model, not from Wan.** Image mode `qwen` is the default. The shot list carries a `still` prompt per shot (first frame as a photograph); `shorts/stills.py` draws it with Qwen Image (`/images/generations`, 720x1280, model selectable from the gateway's image models); the contact sheet is the storyboard the person approves before the 14B/5B models animate it. Both the keyframe and the quick pipeline use it (`pipelines.keyframes_on`). Uploads (anchor / per shot) still override; mode `wan` keeps the old text-only behaviour. Where this plan says "Wan makes the keyframes", read "the image model makes them". "Wan 2.2 only" now means every *moving* picture.

## 1. Goal and non-goals

A new section of the app, **Shorts**, that plans and makes a 30-second vertical (9:16, 1080x1920 final) video. Every moving picture comes from a Wan 2.2 model on the gateway. The user picks a pipeline; the pipeline decides which Wan model runs, because the five models need different inputs and give different results.

Not in scope: the long-form 16:9 flow (unchanged), uploading anywhere, cutting a short out of an existing long video (a different idea, no Wan; ask if wanted).

## 2. Owner decisions (2026-10-29)

| Topic | Decision | What it means for the build |
|---|---|---|
| Voice | Use the existing TTS (Maya default, Veena/Svara selectable) | Voice per beat through `story3/voice.py` machinery; Wan only makes pictures (and S2V/Animate audio, off by default) |
| Pictures | The user can provide a picture, or let Wan decide | Every pipeline has an "image mode": none (Wan decides), one anchor picture, or a picture per shot |
| Source | Both: free-text idea and an approved story | Story source goes through the leak gate; idea source does not need it |
| Language | Hinglish, mixed script, numbers as words | Same narration rules as long-form (`story2/lexicon.py`, script checks) |
| Pace | **Fast. No shot longer than 3 seconds on screen** | Hard check (blocks Make): every shot 3.0 s or less; plan 11-13 shots; hard cuts, no slow crossfades |
| Quality | **Always final.** No draft mode | Speed LoRA off by default on the 14B models; the cost of a bad result is high, so every expensive step is preceded by a cheap human checkpoint (section 4) |
| v1 pipelines | Decided below: A, C, E | B and D follow |
| Animate | The user pastes a YouTube link; the app downloads it, and the character from the user's picture replaces the person | Pipeline E, with a downloader, window picker and rights confirmation (section 3E) |

## 3. What the docs give us

One endpoint for all: `POST /v1/video/generations` (202 + job id, poll `GET /v1/jobs/{id}`, or `wait: true`). The result is an MP4 URL plus width, height, frames, fps, duration, seed. One clip renders at a time; queued jobs also wait for other GPU models. The first call after idle adds 30-60 s of model load. Job results are kept about 1 hour; download links about a day.

| Model id | What it does | Needs | Native | Frame cap | 5 s clip time (RTX 4060 Ti 16 GB, docs) |
|---|---|---|---|---|---|
| `wan-2.2-ti2v-5b` | text or image to video, fast | prompt; image optional | 24 fps, up to 1280x704 | 241 | 832x480 20 steps about 3.5 min; 1280x704 about 10 min |
| `wan-2.2-t2v-a14b` | text to video, best quality | prompt only (rejects pictures) | 16 fps, 832x480 or 1280x720 | 161 | speed LoRA 4 steps about 2.7 min; full 20 steps about 22.6 min |
| `wan-2.2-i2v-a14b` | image to video, optional last frame | prompt + image; `end_image` optional | 16 fps | 161 | speed LoRA 480x640 about 2 min; 10 steps about 8 min (measured); 20 steps about 15 min (estimate) |
| `wan-2.2-s2v-14b` | still picture speaks to audio, lip sync | image + audio | 16 fps | 481 | default 7.5 s about 27 min; speed LoRA about 4 min |
| `wan-2.2-animate-2` | character copies motion and expression of a driving video | image + driving video | 30 fps | 481 | about 66 s of work per second of output at 480x640; `fps: 30` roughly doubles it |

Facts that shape the design:

- **Vertical is supported** (`480x832`; 5B snaps to multiples of 32, 14B to 16). 720x1280 on the 14B and 30 fps Animate are "not tested on the server GPU" (docs). Final 1080x1920 is an ffmpeg upscale; expect softness. S0 tests 5B at 704x1280.
- **Clips are 4n+1 frames** (T2V, I2V; the app uses the same rule for 5B). For the 3-second rule: at 16 fps, 41 frames = 2.56 s and 49 frames = 3.06 s; at 24 fps, 61 = 2.54 s and 73 = 3.04 s. The app generates the next 4n+1 above the shot's planned length and **trims in ffmpeg to the exact planned frames**, so a 3.0 s shot is 48 of 49 frames. The planned length, not the generated one, is what the 3-second check reads.
- **Only S2V and Animate produce sound.** The rest are silent; voice comes from our TTS and the bed from `story3/audio.py`.
- **Wan cannot be trusted to draw words**: captions are burned by ffmpeg, never prompted.
- **Same seed and inputs reproduce a clip.** Used for "make again" (new seed) and for tests.
- **Short clips are cheaper than long ones**, but not proportionally (model load, fixed overhead per request). S0 measures a 2.5 s clip per model, because the plan is about twelve of them.

### Animate: what it will and will not do (read before promising it)

The docs describe Animate as: the reference character copies the motion, expressions and sound of a driving video; the prompt describes the character's appearance **and the background**. That is character animation, not a cut-out swap. The expected result is **the character from the picture, in a background taken from the picture/prompt, moving like the person in the YouTube video**. It is not the original video with only the person replaced and the original scene kept. S0 checks what the gateway really does with the video's own background; the screen must say plainly which of the two it is.

## 4. Pipelines

All pipelines share the same front (idea, short plan, shot list, checks, voice) and back (stitch, captions, sound, export). Only the middle, "how each shot's clip is made", differs.

### v1 pipelines (decided)

**A. Quick: `wan-2.2-ti2v-5b`.** One model that takes text or a picture per shot, so it never swaps models and handles all three image modes.
- Image mode "Wan decides": every shot from text. Option "continue from the previous shot" starts a shot from the last frame of the previous one (for same-scene beats); otherwise shots are independent cuts.
- Image mode "one picture": the anchor starts shot 1 (or every shot that shows the character); later shots are text or continue.
- Image mode "picture per shot": the user uploads one per shot.
- 24 fps, `480x832` default, optional `704x1280`. About 21 min for 30 s at 20 steps (estimate from 3.5 min per 5 s).
- Why in v1: the only quick route, so wrong ideas are found in minutes, not hours, and it covers every image mode with one model.

**C. Keyframe then animate: `wan-2.2-i2v-a14b`.** The quality route, and the one that fits fast cuts best, because each shot starts from its own picture and so needs no chaining (no drift).
1. **Keyframes** (one per shot). From the user: uploaded pictures (one anchor for the character plus optional per-shot pictures). If the user lets Wan decide: **Wan makes the keyframes** with a very short text-to-video request (`num_frames: 5`, last frame kept) on `wan-2.2-t2v-a14b`, one per shot, with the shared character/place block. S0 confirms a 5-frame request is accepted and looks good; fallback is a 5B image-mode request.
2. **Checkpoint**: the screen shows the keyframes as a contact sheet. The user keeps, replaces (upload) or redoes any. Cheap, so mistakes die here.
3. **Animate each keyframe** with I2V, **speed LoRA off** ("always final"), 10 steps default (measured), 20 steps as "maximum quality". Optional `end_image` when two neighbouring keyframes should be joined smoothly (only for same-scene shots).
- 16 fps, portrait crop of each keyframe to 9:16 before sending. About 48 min at 10 steps for 30 s plus keyframes (estimate: 8 min per 5 s x 6 + roughly 1 min x 12).
- Why in v1: best look per hour and the clearest human checkpoint before the long wait.

**E. Remix from a YouTube video: `wan-2.2-animate-2`.** Asked for by the owner. Flow:
1. User pastes a YouTube link and uploads the character picture (required).
2. The app fetches metadata and downloads the video (new dependency `yt-dlp`, kept updatable; bot checks and removals make this the flakiest step, so errors say what happened).
3. The user picks a **30-second window** (start time; the player shows the clip). The app shows where cuts fall (ffmpeg scene detect) and flags stretches where a shot lasts over 3 s, because here the pace is the source video's, not ours. The user can pick a faster-cut window.
4. The app re-encodes the window: portrait 9:16 crop or pad (user picks), 480x832 area (about 0.4 MP, inside the docs' "about 640x640" budget), 16 fps so that 30 s is 480 frames (inside the 481 cap), small enough for the 25 MB body (target 10 MB raw, about 13 MB base64; docs say about 15 MB practical).
5. One `wan-animate` request (or two 15 s requests if S0 shows one long request is unreliable; the seam is hidden by a hard cut at the shared boundary). `keep_audio` is **off by default**; the voice-over (our TTS, optional) and sound bed replace it.
6. Back-end as for other pipelines: 30 fps conversion, captions, sound, export.
- Time: about 33 min per 30 s at 16 fps (estimate; 66 s per second of output), about double at 30 fps. One request is not stoppable mid-way without losing it; the screen says so before it starts.
- **Rights and likeness gate (required checkboxes before Make):** "I have the right to use this video" and "the picture is my own, invented or licensed character, not a private person". The source URL is stored on the record; nothing is ever uploaded by the app; the downloaded video is kept under `data/` only, never exported or published. A real named person's likeness follows the existing rule (`story3/likeness.py`): no photo of a real person unless the editor confirmed a public figure.

### Later releases

- **B. Cinematic: `wan-2.2-t2v-a14b`.** Independent text-to-video shots. Always-final means full quality, 20 steps, about 2 h 15 min for 30 s, so it is not a v1 default. Cheap to add after A and C (same client, different request body). Needs the repeated character/place block for continuity.
- **D. Talking narrator: `wan-2.2-s2v-14b`.** A host picture speaks the voice track. Final quality is about 1 h 50 min for 30 s, and the docs say English speech is untested while ours is Hinglish. Ships only if S0 shows usable lip sync.

Model availability is checked at screen load with `GET /v1/models` (type `video`); a pipeline whose model the key cannot use is greyed with the reason.

## 5. Product flow (a human checkpoint at each stage)

1. **Idea.** Source: free text, or an approved story (its facts and leak gate come free). Topic, tone, pipeline, image mode, and the voice (default Maya).
2. **Short plan** (chat model, JSON): hook inside the first 2 s, four to five beats, one payoff or cliffhanger. Narration about 65-75 words for 30 s.
3. **Shot list** (chat model, JSON): **11-13 shots, none over 3.0 s, the hook shot 2 s or less**, average about 2.5 s. Per shot: narration phrase (about 6-8 words), the Wan prompt in English (subject, scene, motion, camera, light; about 60-100 words; the camera move named), duration, whether it starts from a picture, and the shot's cut type (hard cut by default; a short whip or flash only on a beat change). The repeated **character/place block** is injected by code (slot idea from `story2/describe.py`), not left to the model. Editable on screen.
4. **Checks** (code, no model; any failure blocks Make and says what to fix): every shot 3.0 s or less; total 30.0 s plus or minus 0.5 s; each shot's generated frames are 4n+1 and cover the planned length; the model's mode fits the shot (no picture to T2V, picture present for I2V); no text-in-picture request; leak gate on narration, prompts and captions when a source is used (`story2/leak.py`); safety (`story2/safety.py`); narration script and number rules.
5. **Voice** (existing TTS). One request per **beat** (two or three shots each, one steady emotion per segment, as in long-form), real length measured. Shot lengths are then fitted to the real audio (each still 3.0 s or less; if a beat's audio needs a longer shot, the planner adds a shot). Voice may be sped up at most 1.1x to land on 30 s.
6. **Pictures** (pipeline C only): keyframes and their checkpoint.
7. **Make the clips**: one job, shot by shot, each saved when done. Each attempt is a numbered `media` row, never overwritten. The user watches each clip, approves it, "Makes again" with a new seed, or edits the prompt and redoes only that shot. In A, a shot that continues from another is flagged "made from an older shot" when that one is redone.
8. **Stitch** (ffmpeg): hard cuts by default; each clip trimmed to its planned frames; 16/24 fps converted to 30 fps (frame blend by default, `minterpolate` as an option); scale and crop to 1080x1920; trim to exactly 30.0 s; phrase captions in the lower third, in short chunks that change with the cut rhythm (reuse the caption code in `story3/video.py`, Nirmala UI font); voice plus a ducked sound bed (`story3/audio.py`); loudness -14 LUFS. No 1.25x speed-up: 30 s is the contract.
9. **Review and export**: final MP4 and a small publish pack (title, description, hashtags) as in `story3/publish.py`. Never uploads.

An **Auto-run** button chains every unfinished step and stops at the first thing it cannot settle (a missing model, a failed clip after retries, a failed check, an unconfirmed rights box); everything finished is kept and pressing it again resumes. Because of "always final", it pauses at the keyframe checkpoint of pipeline C unless the user turned that checkpoint off.

## 6. Where it lives in the code (reuse first)

New package `shorts/` (router `/api/shorts`), mounted in `main.py` next to the other three; a "Shorts" page in `static/index.html` with its own `static/shorts.js` (no framework, served uncached, like `plan.js`).

| File | Job |
|---|---|
| `shorts/store.py` | table `shorts` (id, title, source ref, pipeline, model, image mode, settings JSON, brief JSON, shots JSON, status, timestamps). Clip, keyframe, voice and final files use the existing `media` table with `plan_id = short id` and new kinds `short_key`, `short_clip`, `short_voice`, `short_final`, so numbered attempts and one-approved-per-key come free from `story3/store.py` |
| `shorts/wan.py` | one gateway client for `/video/generations`: body per model, send, poll with a per-model timeout (45 min, not 300 s), download (resolve a relative URL against the gateway origin), retry on 502/503/429 honouring `Retry-After`, job id stored in the media row so a restart resumes polling (results live about an hour; after that the shot is marked "lost, make again") |
| `shorts/pipelines.py` | A, C, E (B, D later): `plan_requests(short)` returns per shot the request and its dependencies; `run(short, shot)` |
| `shorts/planner.py`, `shorts/prompts.py` | short plan and shot list through `JsonCaller` with `[TASK:...]` tags and a sampling entry |
| `shorts/checks.py` | the code checks of step 4 |
| `shorts/frames.py` | ffmpeg helpers: last frame, crop to 9:16, trim to N frames, fps conversion |
| `shorts/ytdl.py` | E only: metadata, download, window, scene-cut detect, re-encode to the size limit |
| `shorts/stitch.py` | step 8 |
| `shorts/auto.py` | the Auto-run chain |
| `shorts/api.py`, `static/shorts.js` | endpoints and screen (journey bar, "Next:" bar, shot cards with a video player, contact sheet for keyframes, cut map for E) |

Reuse, do not rebuild: `story2/jobs.py` (one job at a time; Shorts uses the same lock so a short and a long-form job cannot collide on the one GPU), `story3/store.py`, `story/llm.py`, `story2/voices.py` and the voice code in `story3/voice.py`, `story3/audio.py`, `story3/video.py` caption and ffmpeg helpers, `story2/leak.py`, `story2/safety.py`, `story/settings.py` for gateway URL and key. New dependency: `yt-dlp` in `requirements.txt` (ffmpeg is already at `C:\Ffmpeg\bin`).

**Existing code to clean up on the way.** `story3/clips.py` already calls `wan-2.2-ti2v-5b` with its own post/poll/download code and a 300 s poll timeout. Move that into `shorts/wan.py` and make `clips.py` call it, so there is one video client. Also check: the docs show the result `url` as `/video/{token}.mp4` (no host), while `clips.py` passes it straight to `client.get`.

### Request defaults per model (from docs; S0 confirms)

| Use | size (portrait) | fps | frames per 2.5 s shot | steps / guidance | notes |
|---|---|---|---|---|---|
| A, 5B | `480x832` (or `704x1280`) | 24 | 61 | 20 / 5 | `shift` 8; `image` for picture shots |
| C keyframe, T2V | `480x832` | 16 | 5 | 20 / 3, `guidance_low` 4, `shift` 12, `speed_lora: false` | last frame kept |
| C animate, I2V | follows the picture (cropped to 9:16 first) | 16 | 41 | 10 / 3.5, `speed_lora: false` | `end_image` optional |
| E, Animate | about 480x832 | 16 | 480 for 30 s | 10 / 1, sampler `lcm`, `keep_audio: false` | `pose_strength` 1; prompt describes appearance and background only |

## 7. Time (one GPU, one request at a time, always final)

Estimates for 30 s, before retries and model swaps (each swap about 20-60 s; allow 1.3x for redone shots):

| Pipeline | Estimate |
|---|---|
| A. 5B, 480x832, 20 steps | about 21 min |
| A. 5B, 704x1280 | about 60 min |
| C. keyframes + I2V, 10 steps | about 1 h |
| C. keyframes + I2V, 20 steps | about 1 h 40 min |
| E. Animate, 16 fps | about 33 min (about 66 min at 30 fps) |
| B (later). T2V full quality | about 2 h 15 min |
| D (later). S2V default | about 1 h 50 min |

The screen shows the estimate before Make, uses the existing ETA display, warns over an hour, and says that a Shorts job blocks long-form jobs while it runs.

## 8. Risks

| Risk | Answer |
|---|---|
| Characters and places drift between independent shots | repeated slot-composed block in every prompt, one anchor picture where the user gives one, a shared seed base; few recurring subjects (one character, one place) in the short plan |
| Twelve cuts in 30 s read as chaos | planner rule: shots grouped in beats of the same place; hook first; cut type shown on the card |
| Wan decides keyframes are poor | cheap checkpoint before the animation; per-keyframe redo and upload |
| 480x832 upscaled to 1080x1920 looks soft | S0 tests 704x1280 on 5B and 720x1280 on 14B (untested per docs); light sharpen; honest note in the UI |
| Clip takes longer than the poll timeout or the app restarts mid-clip | per-model timeout, stored job id, resume on startup; expired result becomes "lost, make again" |
| YouTube download fails (bot check, removal, age gate, format change) | `yt-dlp` kept current, clear error text, fallback: the user uploads the video file instead |
| Animate does not keep the video's background | stated on screen; S0 checks the behaviour; the character's background comes from the picture and prompt |
| Animate output is long and one request | S0 checks stability at 30 s; fallback is two 15 s requests |
| Copyright or likeness misuse in E | rights and likeness checkboxes, source URL stored, no export of the downloaded video, no upload, `keep_audio` off by default |
| S2V with Hinglish speech (later D) | decided by S0 |
| Gateway 502 (`video_generation_failed`) | retry up to twice (docs advise it), then record the failure on the shot and continue |
| Gateway queue 429/503 | wait `Retry-After`, never hammer |
| Wan draws text or logos | prompts never ask for text; captions are burned; negative prompt is the standard Wan one plus "text, watermark, logo" |
| Source text leaking into prompts or captions | the long-form leak gate on narration, prompts and captions |

## 9. Build order (small batches, each wired to the screen, tests with a fake gateway)

- **S0. Measure first (no UI).** `python -m shorts.probe`: list video models; make a 2.5 s clip per model at 480x832 (5B also at 704x1280, T2V and I2V also at 720x1280); a 5-frame T2V keyframe request; an I2V clip from it; one Animate clip (5 s, then 30 s at 16 fps) from a short test video, noting whether the video's background survives; a relative-URL check on the result. Writes seconds and files under `data/shorts_probe/`. These numbers settle the defaults in section 6 and the open items (keyframes by T2V, Animate in one request). Needs the gateway free for about an hour.
- **S1. Wan client and store.** `shorts/wan.py`, `shorts/store.py`; migrate `clips.py` onto the client. Fake `/video/generations` and `/jobs` in `tests/conftest.py`: 202 then poll, 502 retry, 429 `Retry-After`, expired result, resume after restart.
- **S2. Plan and shots.** Prompts, planner, checks (3-second rule, 4n+1 frames, total length), leak gate. Tests with `tests/fakellm.py`.
- **S3. Pipeline A and the screen.** Idea, plan, shots, make clips with 5B in all three image modes, approve, stitch to a silent 30 s 1080x1920 MP4. First thing the owner can look at.
- **S4. Voice, captions, sound, final export.**
- **S5. Pipeline C**: keyframes (upload or Wan), contact-sheet checkpoint, I2V animation, redo one shot.
- **S6. Pipeline E**: `ytdl.py`, window picker, cut map, re-encode, Animate request, rights gate. Fixtures use a tiny local video, no network in tests.
- **S7. Auto-run, resume, ETA**; update `docs/APP_GUIDE.md` and `CLAUDE.md` (new package, shared lock, Wan defaults, 3-second rule).
- **S8. Pipelines B and D**, then a vision check of first, middle and last frame per clip (`story3/refscore.look`).

Each batch: run only the tests of the area changed (`pytest tests/test_shorts_*.py`); full suite before a commit.

## 10. Still open

1. Animate background: only S0 can say whether the video's own scene can be kept. The plan assumes it cannot.
2. Whether the gateway accepts a 5-frame T2V request (keyframes by Wan). If not, keyframes come from the 5B in image mode.
3. Veena/Maya pace for fitting the voice to 30 s (measured at the voice step, S4).
