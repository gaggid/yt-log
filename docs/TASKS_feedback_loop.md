# Tasks: feedback and evolve loop

Plan: [PLAN_feedback_loop.md](PLAN_feedback_loop.md). A task is ticked when it is built AND tested. The last section checks the plan line by line.

## A. Outcomes and insights (foundation)

- [x] A1 `feedback/features.py`: TERRITORIES vocabulary, hook type, hook length, IST hour/weekday, bands
- [x] A2 `ideas.territory` column; generator asks for it (`__TERRITORIES__` filled by `_generate_system`); code validates it against the vocabulary
- [x] A3 `feedback/store.py`: tables `idea_outcomes`, `yt_video_tags`, `playbooks`, `playbook_pins`, `yt_comments`, `fb_kv`
- [x] A4 Freeze features when a short is made (`api._queue_idea` -> `_freeze_features`) and for linked older ideas (`outcomes.freeze_missing`)
- [x] A5 `feedback/outcomes.py`: baselines (medians), component indices, 40/30/15/15 grade, partial flag, early grade, labels
- [x] A6 `feedback/generate.tag_missing`: territory for ideas without one and for channel videos (batched model call, code validates)
- [x] A7 `feedback/insights.py`: lifts per feature (shrunk, n >= 3), win and flop rate, history rows, best hours
- [x] A8 `feedback/api.py` `/api/feedback` (overview, refresh, jobs); wired in main.py; regrade after every YouTube sync (`sync._grade`)

## B. Playbook and feeding

- [x] B1 Playbook synthesis (`feedback/playbook.py`, task `p4_playbook`): items with scope + evidence, uncited dropped
- [x] B1b Lesson memory: the draft sees every earlier lesson (`ledger`, ids L1..), items come back `new`/`stronger`/`contradicts`; code settles repeats by word overlap, the model judges the grey zone (`p4_playbook_same`); lessons in force are carried over (`memory.state` carried), "stronger" needs a new video id, upload day/hour lessons are dropped (`off_topic`), nothing new = `NothingNew` (no draft, `pb_checked` stops the daily retry), switched-off items stay off, drafts older than the learning window are `stale`, the Playbook version in use is frozen with each idea (`features.playbook`, lift dimension "Playbook version in use")
- [x] B2 Versions draft / approved / rejected / archived; approve, reject, per-item disable, pins (principles)
- [x] B3 Config: `use_playbook`, `explore` (clamped 0.30-0.40), `auto_feedback`, `playbook_min_new`, `tone_arms`
- [x] B4 Learnings block in the generation prompt (`ideas.feedback_extra`): winners, flops, do more, do less, pins; approved only
- [x] B5 `feedback/bandit.py`: explore share, softmax, cooldown, sources recorded
- [x] B6 Territory plan in generation (`bandit.territory_block`, `assign_sources`); bandit in `ideas.style_choice`; tone arm on explore in `api._queue_idea`
- [x] B7 Calibration anchors in the rating prompt (`playbook.rating_anchors`)
- [x] B8 Title note into `publish.make` (`publish.learnings`); script note into `script._source`

## C. Evolve

- [x] C1 Calibration table (sub-scores and total against grade) and threshold advice with Apply (`POST /calibration/apply`)
- [x] C2 Winner remix: `generate.sequels` (origin `sequel:`), winners at 3x median reach or more, once per winner
- [x] C3 `youtube/client.comments`, `sync._comments`, `yt_comments`; `generate.comment_ideas` (origin `comment:`); privacy page updated
- [x] C4 Experiments table (`insights.experiments`): results by how each choice was made
- [x] C5 Evolution report: `playbook.diff` stored with each draft, shown on the page
- [x] C6 Autopilot step (`api._start_feedback`, daily, needs YouTube connected) running `generate.run_cycle`: grade, tag, draft when due, sequels, comment ideas, dedup and rate; drafts only

## D. UI

- [x] D1 "Learn: what works" tab on the YouTube page (`static/learn.js`): controls, tiles, lifts, calibration, best hours, experiments, graded shorts
- [x] D2 Playbook panel: drafts with diff, approve / reject, disable items, pins
- [x] D3 Ideas screen: "Using Playbook vN" chip + draft-to-review link, origin and territory badges

## E. Tests, docs, validation

- [x] E1 `tests/test_feedback.py` (27 tests) and the comments test in `tests/test_youtube.py`
- [x] E2 Existing tests: `tests/test_shorts.py` has the same 6 failures as before this work (checked against the pre-change run); the rest of the suite is run at the end
- [x] E3 CLAUDE.md section
- [x] E4 Validation against the plan (below)

## Validation against the plan

| Plan line | Where it is | Test |
|---|---|---|
| Freeze features at make time (mechanisms, pair, hook type/length, territory, style, tone, target length, language, score + 7 sub-scores, choices) | `features.freeze`, `api._freeze_features` | `test_a_made_short_freezes_its_features...` |
| Upload hour and weekday (IST) | derived from the video's publish time when graded (not known at make time): `outcomes.graded_rows` | `test_hook_shapes_territories_and_ist_time` |
| Territory field, tagging of ideas and channel videos | `ideas.territory`, `generate.tag_missing`, `yt_video_tags` | `test_tagging_fills_territories...` |
| Grade 40/30/15/15, index `100*i/(i+1)`, partial, labels, early read | `outcomes.grade`, `label` | `test_grade_orders_videos...`, `test_early_grade...`, `test_a_grade_without_retention_is_partial` |
| Channel history in the sample | `outcomes.graded_rows` (source `history`) | `test_lifts_shrink_small_groups...` (12 rows incl. history features) and the run on a copy of the real database (33 graded, 0 by the app yet) |
| Lifts shrunk, min 3, win/flop rate | `insights.lifts` | `test_lifts_shrink_small_groups_and_hide_tiny_ones` |
| Playbook: scope, evidence, uncited dropped, versions, diff | `playbook.draft`, `_clean`, `diff` | `test_a_draft_keeps_only_cited_items...`, `test_a_new_version_replaces...` |
| Only an approved version feeds anything; switch; disable items; pins | `playbook.enabled`, `learnings_block`, `toggle_item` | `test_only_an_approved_playbook_feeds_prompts...`, `test_the_bandit_does_nothing_without_an_approved_playbook` |
| Generation prompt block and territory plan | `ideas.feedback_extra`, `bandit.territory_block` | `test_the_generation_prompt_carries...`, `test_the_territory_plan_gets_matched...` |
| Bandit: explore 30-40 %, least-tried, softmax, 14-day cooldown | `bandit.choose`, `save_config` clamp | `test_the_bandit_explores...`, `test_explore_share_stays_between_thirty_and_forty_percent` |
| Style from the bandit; tone arm only on an explore roll; sources recorded | `ideas.style_choice`, `bandit.choose_tone`, `api._queue_idea` | `test_a_made_short_freezes...`, `test_the_bandit_does_nothing...` |
| Rating anchors; calibration; threshold advice with Apply | `playbook.rating_anchors`, `insights.calibration`, `/calibration/apply` | `test_rating_anchors...`, `test_spearman_calibration_and_threshold_advice`, API test |
| Winner remix at 3x | `generate.sequels` | `test_sequels_are_written_once_per_winner...` |
| Comments as an idea source (read, store, fence as data, origin) | `client.comments`, `sync._comments`, `generate.comment_ideas` | `test_comment_ideas_...`, `test_public_comments_of_the_best_videos...` |
| Title note, script note | `publish.learnings`, `script._source` | `test_only_an_approved_playbook_feeds_prompts...` (title and script blocks); wiring is two guarded calls |
| Best hours advice | `insights.best_hours`, Learn tab | covered by lifts (dimension `hour`, `weekday`) |
| Experiments: exploit vs explore | `insights.experiments` | `test_experiments_compare_how_choices_were_made` |
| Evolution report | `playbook.diff` in `data.changes`, Learn tab | `test_a_new_version_replaces...` |
| Autopilot step drafts only | `api._start_feedback`, `generate.run_cycle` | `test_the_autopilot_starts_the_feedback_cycle...`, `test_the_daily_cycle_grades_drafts...` |
| Owner approves; off switch | `/playbooks/{id}/approve`, `use_playbook` | API test |
| UI: Learn tab, Playbook panel, Ideas chip and badges | `static/learn.js`, `static/youtube.js`, `static/ideas.js` | `node --check` on all three; not exercised in a browser |

### Not done or different from the plan (stated honestly)

- Upload hour and weekday are derived when a video is graded, not stored at make time (the publish time does not exist yet then).
- The "weekly" evolution report is produced with every new Playbook draft (the diff), not on a weekly clock.
- The Learn tab and the Ideas chip were checked for JavaScript syntax only; nobody has clicked through them in a browser yet.
- The model steps (tagging, Playbook, sequels, comment ideas) are tested with a scripted model; none has run against the real gateway yet.
- No app-made short has a 7-day grade yet (the first ones are 1 to 2 days old), so the app-side lifts, calibration and experiments will be empty until about 16 Nov.
