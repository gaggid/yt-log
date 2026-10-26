# Plan: Veena voice, Indian cast, reference/scene redraw, redo after video

Written 2026-10-26. Owner decisions: existing plans move to Veena; Indian cast is ON by default for all plans; FLUX stays, and every image model the API lists is selectable, Qwen Image 2.1 stays the default. Validate at the end that nothing is skipped or partly built (see the checklist at the bottom, tick each line when verified).

## 1. Veena voice (default `veena-tts` / `agastya`, Svara selectable)
- 1a. Engine registry (`story2/voices.py`): engines, voices, defaults, request body, text format. Plans without an engine use Veena/agastya (existing plans too).
- 1b. Text per engine: Veena has no emotion tags; keep `...` `,` `?` `—`, pauses as `[pause:Ns]`. Svara unchanged. Svara tag validation only for Svara.
- 1c. Narration prompt block per engine (Veena: write for the ear, short sentences, `…` before a reveal, Devanagari Hindi + Latin English words). Svara emotion rules only for Svara.
- 1d. Voice request: temperature 0.4, top_p 0.9, repetition_penalty 1.05, seed, `Prefer: respond-async`; handle the async answer after probing the gateway.
- 1e. Voice hash includes engine + voice + text; old takes stay as attempts.
- 1f. Consumers read the voice through one helper (`story3/store.py`, `auto.py`, `video.py`, export TTS notes).
- 1g. UI: engine and voice picker in the Voice card, "try one sentence" button.

## 2. Footwear / unseen detail bug
- Show a character detail in a prompt only if the shot can see it (close: head and shoulders; medium: to the waist; wide: full body; seated behind something: no legs). Validator stops requiring hidden details. Storyboard instruction says not to describe unseen clothing.

## 3. Indian cast (on by default)
- Plan setting `cast_indian` (default true). Registry prompt asks for Indian features, names, period clothing. New person slot `ethnicity` composed first. Crowd line in scene prompts. "Apply to existing" button. In `asset_hash` / `source_hash`.

## 4. Edit the reference prompt
- Editable prompt per reference, "Draw with this prompt", "Reset". Stored on the attempt only. Leak gate scans it.

## 5. Scene redraw panel
- Model (every model the API lists; Qwen default), mode (plain / from reference sheets), full editable prompt and negative prompt, candidates. `POST /scenes/{sid}/redraw`. Per-scene choice in plan settings.

## 6. Redo after the video
- "Changes since the last video" panel (old vs new picture per scene), redraw only scenes using a redone reference, rebuild the video as a new attempt reusing unchanged clips.

## Validation (2026-10-26)
- [x] Full suite: 323 tests, all pass (322 + the one test changed on purpose: an approved picture older than a changed reference now stays in the video with a warning).
- [x] 1 Veena: `story2/voices.py`, async job polling in `story3/voice.py`, picker + sample on the Voice card, `PATCH /api/plans/{id}/tts`, `GET /api/plans/voices`, `POST /api/media/{id}/voice/sample`. Real gateway call returned 8.0 s of wav with agastya.
- [x] 2 Unseen detail: `describe.hidden_slots`, `imgprompts._subject_text`, validator, storyboard instruction; `tests/test_visible_detail.py`.
- [x] 3 Indian cast: slot, `indianise`, prompts (Qwen + FLUX), reference prompts, hashes, registry prompt, `PATCH /api/plans/{id}/cast`, toggle on the Characters card.
- [x] 4 Reference prompt edit: textarea + model choice + "Draw with this prompt" / "Reset", `prompts` on `POST /references`, `custom_prompt` on the attempt, leak gate applies.
- [x] 5 Scene redraw: `scenes.options` / `scenes.redraw`, "Redraw…" dialog, per-scene memory, every gateway image model selectable (`providers.refresh` / `register_listing`), Qwen stays default.
- [x] 6 Redo after video: `video.changes_since`, `meta.used`, "Changes since the last video" panel, "Redraw these N scenes", rebuild reuses unchanged clips (tested).
- [x] Docs: APP_GUIDE, CLAUDE.md, RUN_LOG.
- Not done / limits: not run on a real long plan; Veena pace uses 148 wpm until measured; the Veena narration prompt has not been compared by `narration_audit`; the app must be restarted to load this (nothing is committed or pushed).
