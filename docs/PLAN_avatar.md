# Plan: talking avatars (InfiniteTalk) and character-driven Animate for Shorts

> **Status 2026-10-30.** Built and pushed: InfiniteTalk on the gateway (`infinitetalk-14b`, fp8 base, workflow `wan21_infinitetalk`); avatar shots in Shorts; Avatar tab in Character Studio (voice, 3 s ready test); Animate with a library character and YouTube, Instagram or uploaded references (whole-short remix and single-shot). **Measured:** about 377 s per 3 s clip (6 sampling steps at 56 s each; the 17 GB model swaps between CPU and GPU). Owner decision: slow avatars are fine for now, used for an opening shot. **On hold: speed.** The 4-bit GGUF files (`wan2.1-i2v-14b-480p-Q4_K_M.gguf` from city96/Wan2.1-I2V-14B-480P-gguf, `Wan2_1-InfiniteTalk_Single_Q8.gguf` from Kijai/WanVideo_comfy_GGUF) were downloaded and then deleted to free 13.5 GB; the gateway code supports them (`block_swap` default, no LoRA merge), but the test that put the whole model on the GPU filled all 16 GB and crashed the machine. Any further speed test must keep the card under about 13 GB (block swap of about 8) and be run with the owner present. Nothing is pending on the gateway.

Status: plan, nothing built. Written 2026-10-30, revised the same day after the owner's decisions.

## 1. Owner decisions (2026-10-30)

1. **S2V is dropped.** Too slow (about 27 min for 7.5 s) to use routinely. It is not measured, not adapted and not used.
2. **Talking avatars use open-source InfiniteTalk** (HeyGen-style: a library character speaks the short's voice with lip sync, head, body and hands). Get it onto the gateway now.
3. **Wan 2.2 Animate is adapted** so that the person picks a **library character** and a **reference video** (upload, YouTube link or Instagram link) and the character performs the reference's motion.

## 2. What exists today (checked in code and on the gateway)

| Piece | State |
|---|---|
| Character Studio to Shorts for `quick` (5B) and `keyframe` (I2V 14B) | Wired: cast characters, looks and place make the start pictures (`shorts/cast.py`, `stills.build`) |
| `remix` (Animate) | YouTube only (`HOSTS` in `shorts/remix.py`), character is a one-way copy of a picture (`/images/anchor/character`, which also forces image mode `anchor`); not tied to `settings.cast`, looks or the character version; uses `wan-2.2-animate-2` only |
| S2V | Table entry in `shorts/models.py` only. To be removed from the model table so nothing offers it |
| Gateway | `D:\MiniMaxH3`, a separate repository. Video models run as **ComfyUI workflows** (`serve_models.yaml`, e.g. `workflow: wan22_s2v`), ComfyUI core from ComfyUI Desktop plus custom nodes in `C:\ComfyUI\custom_nodes`. Models in `C:\ModelWeights\LMStudio_Models\comfy-org\Wan-2.2`. **No InfiniteTalk, no WanVideoWrapper node installed.** GPU: RTX 4060 Ti 16 GB |
| Also installed on this PC | `D:\Wan2GP` (WanGP, Oct 2025 build) already supports **InfiniteTalk** (single and multi speaker, with LoRA accelerators, built for 16 GB cards, automatic background-music removal for better lip sync). It is a ready reference for settings and a fallback runner |
| Undocumented gateway models | `wan-animate-fast`, `wan-animate-2-distilled` appear in `/v1/models` but not in the docs; probe them for Animate speed |

## 3. Why InfiniteTalk

- Open source, built on Wan, audio-driven, full-body motion, any length by sliding windows, one reference picture, can use different shots for one audio. Best lip-sync confidence among the open avatar models in a 2025 comparison (8.48 against 6.71 for Wan S2V); runs with 4-step LoRA accelerators, which is what makes it fast enough (S2V's speed LoRA lost the mouth).
- Rejected: OmniAvatar (rigid body), EchoMimic V2 (hand distortions, fixed body template), StableAvatar (artifacts), LatentSync 1.6 (18 GB), Wav2Lip (soft mouths). MuseTalk 1.5 (about 8 GB, MIT per two sources) stays as a possible later mouth-repair stage only.
- Licence: read each model card before downloading (InfiniteTalk, the Wan 2.1 I2V base it runs on, wav2vec2).

Sources: [Kandinsky S2V paper](https://arxiv.org/html/2610.19290v1), [Soul paper table](https://arxiv.org/html/2512.13495v1), [Live Avatar paper](https://arxiv.org/html/2512.04677v6), [LatentSync paper](https://arxiv.org/pdf/2412.09262), [lip-sync VRAM notes](https://news.creeta.com/en/open-source-lip-sync-models-2026/).

## 4. Part A: InfiniteTalk on the gateway (work in `D:\MiniMaxH3`, not in this repo)

The gateway owns models, so this part is gateway work; this app only calls it. Two ways, in order of preference:

**A1 (preferred): ComfyUI workflow, same pattern as the other Wan models.**
1. Install `ComfyUI-WanVideoWrapper` (kijai) into `C:\ComfyUI\custom_nodes`; it has InfiniteTalk nodes (multitalk/infinitetalk embeds, wav2vec encoder, block swap for 16 GB).
2. Download: InfiniteTalk single-speaker weights (fp8 or GGUF), the Wan 2.1 I2V 14B 480p base it needs (fp8), a Chinese-wav2vec2 audio encoder (WanGP already holds `ckpts/chinese-wav2vec2-base`), umt5 and VAE (already present), and the lightx2v 4-step LoRA for Wan 2.1 I2V. About 20 to 25 GB; free space on C: is 200 GB, D: 1.5 TB.
3. Write the workflow `infinitetalk` and register `infinitetalk-14b` (alias `wan-infinitetalk`) in `serve_models.yaml` with `kind: video`, inputs `image` + `audio` (+ optional `prompt`, `audio_start`, `duration`, `size`, `steps`), outputs mp4 with our audio muxed or silent (flag `keep_audio`).
4. Gateway tests like `test_video_wan14.py`; expose it in `/v1/models` and the docs page.

**A2 (fallback): Wan2GP behind the gateway.** Run `wgp.py` headless for InfiniteTalk jobs. Only if the ComfyUI route is blocked: two engines on one 16 GB card must be unloaded around each other.

**Acceptance for Part A (short measurement, not the S2V-style long run):** one 3 s and one 6 s clip at 480x832 with a Maya Hinglish line and an English line, accelerated settings; a person judges lip sync, hands, identity; record seconds. Target: under 10 minutes for a 6 s clip. If it misses this target we reconsider before building Part B.

## 5. Part B: Avatar in Character Studio and Shorts (this repo)

### B1 Character side ("pre-ready")
A talking clip depends on the words, so only what does not depend on the script is prepared:
- **Avatar tab** on a person character: talking picture (`talk` view: front facing, waist-up, hands visible and relaxed, mouth closed, 480x832 framing) made by edit from the canon, approved by the person, with the strict identity check; one per look if wanted.
- **Voice of the avatar** stored on the character (engine and voice from `story2/voices.py`); a short can override.
- **Ready test**: a 3 s line spoken in that voice through InfiniteTalk; vision check on frames (mouth opens with the loud instants, hands sane, identity) gives `avatar.ready = pass | weak` and keeps the clip for viewing. Same one-job lock as other studio jobs.
- Pack export carries the talking picture, voice and test result (not clips).

### B2 Shorts side
- A shot or beat can be **avatar**. The planner proposes the opening hook as avatar when a cast member is avatar-ready.
- One InfiniteTalk request over the beat's voice wav (split at a sentence boundary beyond the request limit). The result is cut by `stitch.py` into shots of **at most 3.0 s** with different framing (centre, punch-in 115 to 130 %, side crop) so lips stay continuous while the screen changes (owner rule kept).
- Audio: our beat wav is the only source of sound; the clip's own audio is dropped in the stitch.
- Start picture of an avatar shot = the talking picture (or the look's); it shows on the storyboard contact sheet.
- Checks: block Make when an avatar shot has no cast member, talking picture, voice or ready test; time estimate from measured seconds.
- New pipeline switch is not needed: avatar is a shot type inside `quick` and `keyframe`.

## 6. Part C: Animate with a library character and a reference from upload, YouTube or Instagram

Animate copies the body motion, gestures and expression of a driving video onto a reference character (docs: identity from the picture, motion from the video; the prompt describes appearance and background). It does not lip-sync our words; for speech use Part B. Together: Animate for motion-led shots (dance, walk, gesture), InfiniteTalk for talking shots.

- **Character input.** Remix takes a cast member (and look) from `settings.cast` directly, using the body canon or the look picture, framed 9:16; no copied JPEG, no forced `anchor` mode. The request hash includes the character version, so a new canon makes the clip old, like start pictures.
- **Reference sources**, one field "reference video": 
  - **Upload** a file (new; stored under `remix/`, size limit 40 MB after re-encode).
  - **YouTube link** (existing `ytdl` path with yt-dlp).
  - **Instagram link** (reels and posts): yt-dlp supports public Instagram posts; many need a logged-in session. Add an optional cookies file setting (path to a `cookies.txt`, never uploaded or logged) and say plainly when Instagram refuses. Allowed hosts become YouTube, Instagram and direct uploads only.
  - Same two rights boxes as today (reference video is allowed to be used as motion; the character is the person's own, invented or licensed). The reference video stays under `data/media/<short>/remix/`, is never exported or uploaded.
- **Window picker and cut map** stay (30 s window). The picker also supports shorter windows for shot-level use: a reference clip can drive just one shot (2 to 3 s), so Animate can serve a single motion shot inside a normal short, not only a whole-short remix.
- **Models.** Use `wan-2.2-animate-2` by default; probe `wan-animate-fast` and `wan-animate-2-distilled` (undocumented) on one 3 s clip and offer them if the result is acceptable. Add a model select with the measured seconds.
- **Look of the background.** The background comes from the prompt and picture, not the reference; the screen says so (as today).

## 7. Tasks

| # | Task | Where | Notes |
|---|---|---|---|
| G1 | Install WanVideoWrapper, download InfiniteTalk and base weights, register `infinitetalk-14b` workflow and model | `D:\MiniMaxH3` | needs owner consent for ~25 GB download and gateway edits; restart of the gateway (it is shared with the running app, so when no job runs) |
| G2 | Short acceptance run (3 s and 6 s, two voices) | gateway + this app | go/no-go for Part B |
| A1 | Remove S2V from `shorts/models.py`; add INFINITETALK spec once the gateway lists it; `GET /api/shorts/options` shows avatar only when the model exists | this repo | |
| B1 | Talking picture view, approval, identity check, avatar block, voice choice | characters | mock tests |
| B2 | InfiniteTalk request builder, mock gateway with `audio`, make clip, retry, estimate | shorts | |
| B3 | Avatar shot in planner, checks, storyboard card, Make; stitch cut into framed shots of at most 3.0 s | shorts | |
| B4 | Ready test (frame sampling plus vision check) | characters | |
| C1 | Remix from `settings.cast` and look, staleness on character version, drop forced `anchor` mode | shorts | |
| C2 | Reference sources: upload, YouTube, Instagram (cookies setting), host allow-list, single-shot windows | shorts | no network in tests |
| C3 | Probe Animate variants, model select | shorts | one 3 s clip each |
| V1 | One live avatar opening plus one Animate motion shot in a 30 s short; compare with this plan; update docs and CLAUDE.md | all | |

Order: G1, G2 (gateway), then B1 to B4 and C1 to C3 (mock-tested, no GPU needed), then V1.

## 8. Risks

| Risk | Handling |
|---|---|
| Hinglish lip sync weaker than English (wav2vec encoder) | G2 tests both; Wan2GP's music-removal and a Chinese-wav2vec2 encoder are the known settings; MuseTalk mouth repair is the later fallback |
| 16 GB card shared by LLM, image, TTS and video | gateway already unloads on idle (`idle_unload_s`); InfiniteTalk uses block swap and fp8; one job at a time |
| Download size and licences | read model cards; nothing is downloaded without the owner's go |
| Instagram refusing downloads | cookies setting, clear message, upload remains the dependable route |
| Reference video rights | existing two rights boxes, video never exported |
| Identity drift in long clips | strict check (`check.py`) on first, middle and last frame |
| Real or private people | same consent rule as the Studio; the avatar is only a library character with rights recorded |
