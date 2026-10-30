# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Source-to-Story: turns a book (PDF) or article into a 16:9 long-form video through three stages with a human checkpoint each: Phase 1 `story/` (source to story candidates), Phase 2 `story2/` (story to video plan), Phase 3 `story3/` (plan to voice, pictures, graphics, ffmpeg draft video). `shorts/` (Phase 4) makes 30-second 9:16 shorts: the image model (Qwen Image) draws a start picture per shot, Wan 2.2 models make every moving picture; plan and status in [docs/PLAN_shorts.md](docs/PLAN_shorts.md). `legacy/` is the old news-podcast generator, not served; leave it alone.

The active quality plan (audit, tasks, status of each) is [docs/TASKS_quality_overhaul.md](docs/TASKS_quality_overhaul.md): read it before changing narration, scenes or prompts, and tick tasks there as they land. Read [docs/RUN_LOG.md](docs/RUN_LOG.md) for what the latest end-to-end runs found and fixed, and [docs/APP_GUIDE.md](docs/APP_GUIDE.md) first (owner rules, measured model facts, invariants, plan-screen flow) and [docs/ROADMAP.md](docs/ROADMAP.md) for what remains.

## Commands

Windows; the app runs from `.venv`.

```
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env                       # TRIPFICK_API_KEY, APP_PASSWORD
.venv\Scripts\python.exe main.py             # http://127.0.0.1:8905
start.bat                                    # watch.py: runs app, auto-pulls origin/master, restarts when idle or on crash
.venv\Scripts\python.exe -m pytest tests     # all tests, mocked models
.venv\Scripts\python.exe -m pytest tests/test_phase3i.py -k name    # single test
set LIVE_LLM=1 && .venv\Scripts\python.exe -m pytest -k live        # optional real-model tests
```

No linter or build step configured. `static/plan.js` is served from disk uncached, so frontend-only changes need no restart; Python changes do. Never restart while a generation job is running (watch.py waits for this).

## Architecture

- `main.py` mounts four FastAPI routers: `story/api.py` (`/api`), `story2/api.py` (`/api/plans`), `story3/api.py` (`/api/media`), `shorts/api.py` (`/api/shorts`). UI is plain static files (`static/index.html`, `plan.js`), no framework.
- All models sit behind one local OpenAI-compatible gateway (default `127.0.0.1:8810/v1`): chat/vision (Gemma), voice (Veena `agastya` by default, Svara `hi_male` selectable; `story2/voices.py`), images (Qwen Image 2.1 is the default; FLUX.2 Klein and every other image model the gateway lists are selectable per scene). Gateway allows one concurrent request per key, so `story2/jobs.py` runs one background job at a time and refuses a second.
- Data in gitignored `data/`: SQLite `story.db` (Phase 1 tables, Phase 2 `plans/segments/scenes/assets/plan_revisions`, Phase 3 `media`), plus sources, exports, previews, media files.
- Phase 3 `media` rows are numbered attempts, never overwritten; approving one un-approves siblings (`story3/store.py`).
- `story3/auto.py` is the "Auto-run" job that chains every unfinished step; keep it in sync when adding a step (and with the step order in `static/plan.js`: the order is blueprint, narration, characters, storyboard, references, prompts, repeats, approve, export, voice, pictures, graphics, video, thumbnail).
- `story2/director.py` plans the whole film as shots (emotion, place, size, angle, camera move per segment) before any scene is drawn; `make_storyboard` calls it when no current plan exists. Each scene names the shot it follows (`scene.data.direction`), the shot's size and angle are written into `composition`, and `story3/video.py` takes the camera move from `direction.move`. Anything planned must be wired the same way: field in the scene, text in the Qwen prompt (`imgprompts.compile_qwen`, camera first), consumer in the video build.
- Tests use fake models/gateways (`tests/fakellm.py`, `tests/conftest.py`).

## Shorts (Phase 4, `shorts/`)

- Start pictures: image mode `qwen` (default) has the planner write a `still` prompt per shot (`shot.still`, editable) and `shorts/stills.py` draws it with the gateway image model (`settings.image_model`, default `qwen-image-2.1`, 720x1280) through `/images/generations`; the person looks at the storyboard (contact sheet, redo/edit/upload per shot) before any video is made. Uploaded pictures win; `wan` mode = no stills (Wan decides, the old behaviour). `pipelines.keyframes_on` says whether a short has the start-picture step (keyframe pipeline always; quick unless mode `wan`).
- Three pipelines, chosen by the Wan model: `quick` (5B, from the start picture, or text in mode `wan`), `keyframe` (a start picture per shot, checked by a person, then each animated with the 14B image-to-video model at full quality), `remix` (Animate: a YouTube video's motion on the user's character). Speed LoRA is off everywhere ("always final"). Clip requests are built only in `shorts/pipelines.py` (and `remix.request`); the one gateway client is `shorts/wan.py`, also used by `story3/clips.py`.
- Owner rule: **no shot is on screen longer than 3.0 seconds** and the short is exactly 30 s (900 frames at 30 fps). `shorts/timeline.py` fits the voice into 30 s and gives every shot whole output frames; `shorts/checks.py` blocks Make on a longer shot; `planner.fit_shots` rewrites a beat's shots when the real voice runs long. Clips are generated at the next 4n+1 frames and trimmed in `stitch.py`.
- Voice is made per beat before any clip (shot lengths come from the real voice, `planner.sync_timing`). Voice, keyframe and clip validity are hashes of their inputs (`store.input_hash`, `pipelines.req_hash`, which leaves the seed out), like the long-form media.
- Clips, keyframes, voice and the final video are `media` rows with `plan_id` = the short's id (kinds `short_key`, `short_clip`, `short_voice`, `short_final`). A running attempt stores the gateway's job id; `clips._adopt` resumes it after a restart.
- Remix: the YouTube video is only the motion guide; it stays under `data/media/<short>/remix/`, is never exported or uploaded, and two rights boxes must be ticked before Make. Animate does not keep the video's own background (character and background come from the picture and the prompt).
- `python -m shorts.probe` measures the gateway's Wan models and writes `data/shorts_probe/timings.json`, which the time estimates read. Run it first on a new gateway.
- Tests: `tests/test_shorts.py` with `tests/shorts_fakes.py` (mock video gateway, fake chat, tone voice, tiny ffmpeg clips).

## Invariants that span files

- Canonical scene is source of truth; image prompts derive from it via `source_hash` and regenerating them never touches scene wording.
- `editorial.content_hash` defines what was approved and deliberately excludes timings, previews, issues, scene `prompts`/`adapters`, asset `reference_images`. Changing it requires migrating stored approvals and re-exporting.
- Voice is made only from a saved export whose hash equals the current plan; reference pictures are the exception (need only the registry).
- Export has `public` (spoken/shown/sent to models) and `evidence` halves; the leak gate (`story2/leak.py`) scans `public` and refuses the export on any finding. No source/author/book mentions or quotes may reach narration, prompts, or screens.
- Style is chosen once per plan (`settings.visual_style`, presets in `story2/styles.py`) and written into style asset, every scene prompt, every reference picture. Bump `DIRECTION` when the visual direction changes so old work is flagged "made for another look".
- Asset descriptions are composed from slots (`story2/describe.py`); the image models invent anything unspecified, so every person/place/prop needs concrete values. Never name a game or brand in a prompt.
- Charts, tables and documents are never drawn by an image model; `story3/graphics.py` builds them from verified facts. On-screen text is English only, 8 words max.
- People are drawn as Indian by default (`cast_indian`); a person's shoes and trousers are only written into a prompt when the shot can see them (`describe.hidden_slots`).
- Maya (`story2/maya.py`) is the default voice for new plans (plans that never chose one stay on Veena). Its emotion tags live on each sentence (`tag`), outside the content hash: the storyboard suggests one per scene (`scene.data.voice_tag`, copied to the sentences by `storyboard.apply_voice_tags`), `story2/voicetags.py` is the model's sentence-level direction (auto-run step `voicetags`), and the editor can change both on the plan screen. Keep the tag lists in `static/plan.js` equal to `maya.py` (a test checks).
- Voice engine/voice is `narrator.tts`, outside the content hash; take hashes carry the engine. Pictures and reference prompts can be redone any time (`scenes.redraw`, `refs.generate(prompts=)`) and the video lists "Changes since the last video".
- Narration is first-person Hinglish in mixed script, numbers as words; one steady emotion per voice segment.
- Voice and picture validity are tied to hashes of their inputs; changing wording/description invalidates old takes.
- Context budget: a request that would exceed `context x (1 - safety)` is refused, never truncated (`story/tokens.py`, `story/llm.py`).
- The blueprint carries a suspense plan that every beat's narration prompt receives; narration checks (`planner.make_narration`) send back repeats, stock openers, a long opening sentence and Hindi in Latin letters. Checks accept their last attempt (`JsonCaller.last_attempt`) so a run never stops on style. Compare two narrations with `python -m story2.narration_audit`.
- The finished video plays at 1.25x (`story3/video.py PLAYBACK_SPEED`); the thumbnail (`story3/thumbnail.py`) is the last auto-run step.
- A project has one story type (`story/storytypes.py`: incident, biography, documentary, explainer, listicle), copied to `plan.settings.story_type`; prompts, scoring and built cards differ by type. Plan: `docs/PLAN_story_types.md`.
- A page that blocks the plain download (403/429/503 or a bot-check page) is retried in headless Edge/Chrome (`ingest.fetch_with_fallback`); paywalls are never retried.
- A real, named person is a silhouette unless the editor confirms a public figure and approves a photo (`story3/likeness.py`): then the character sheet is painted from that photo, which is only ever a reference. Nothing is used before approval.
- Keep checks short: run the tests for the area you changed; the full suite takes about 5 minutes.
