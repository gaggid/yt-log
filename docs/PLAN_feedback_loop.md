# Plan: the idea factory learns from YouTube (feedback and evolve loop)

Status and tasks: [TASKS_feedback_loop.md](TASKS_feedback_loop.md). Owner decisions (2026-11-09) are in the last section.

## Why

Idea generation ([shorts/ideas.py](../shorts/ideas.py)) knew only the date, web signals and a list of covered topics. Rating was the model's own opinion with no real results behind it. Style and tone rotated blindly. The YouTube module ([youtube/](../youtube/)) now holds views, 2/7/28-day windows, percentage watched, likes, comments, shares and subscribers per video, linked to idea and short. This plan closes the loop.

## The loop

Measure, grade, explain, feed, experiment, measure again. Every turn changes what the factory makes next, and the next results show whether it helped.

```
idea -> short -> video -> numbers -> GRADE -> insights -> PLAYBOOK (owner approves) -> prompts, bandit, remix -> idea ...
```

## Stage 1: Outcomes (a fair grade)

- **Freeze features at make time** in `idea_outcomes` (so later edits do not blur the picture): mechanisms and their pair, hook type (question, shock, number, what-if), hook length in words, subject territory, picture style, tone, target length, language, idea score and its seven sub-scores, upload hour and weekday (IST), and how style/tone were chosen (`exploit`, `explore`, `rotation`, `idea`).
- **Territory** is a new idea field from a fixed vocabulary (`feedback/features.TERRITORIES`), written by the generator and filled for older ideas and for channel videos by a cheap tagging call.
- **Grade against the channel's own baseline** (medians of reference shorts, not averages: Shorts views are lumpy):
  - reach: 7-day views / baseline median (40%)
  - retention: average percentage viewed / baseline median (30%)
  - engagement: (likes + comments + shares) per 1,000 views / baseline (15%)
  - growth: subscribers gained per 1,000 views / baseline (15%)
  - each component index `i` becomes `100 * i / (i + 1)` (1.0 = 50), then the weighted sum is the 0-100 grade. Missing components are left out and the weights renormalised; a grade built without retention is marked `partial`.
  - label: top quarter `winner`, bottom quarter `flop` once 8 videos are graded; before that absolute lines (62 and 38).
- **Early read at 48 hours** (`early_grade`, from the 2-day window against the 2-day baseline). The 7-day grade is the authority and replaces it.
- **Channel history** (videos not made by the app) joins the sample for the features a title alone gives: hook type, hook length, territory, duration, upload hour and weekday.

## Stage 2: Explain

- **Code first.** For each feature value: n, median grade, win rate, and a lift (median reach index of the group over the overall median), shrunk towards 1 on the log scale with `n / (n + 4)`. Nothing is reported under 3 videos.
- **Model second.** Given the top 5 and bottom 5 with their metrics, hooks and premises plus the computed lifts, the model writes the **Playbook**: do more, do less, open questions, a title note, a script note. Every item has a scope (`idea`, `script`, `title`) and evidence (video ids). Code drops any item that cites nothing or cites a video that does not exist.
- **Playbook versions** are stored with the data they came from and a diff against the last approved version (the evolution report).

## Stage 3: Feed (only an approved Playbook version feeds anything)

1. Generation prompt gets a "channel learnings" block: winner hooks (pattern, not subject), flop patterns, do-more and do-less, pinned principles. Covered topics are still excluded.
2. Territory plan: each slot of a batch gets a territory from a bandit.
3. Style choice (`ideas.pick_style` fallback) and an optional tone arm come from the same bandit.
4. Rating prompt gets calibration anchors (past ideas with their score and their real grade). A calibration table shows how each sub-score and the total correlate with the grade; a threshold advice (`approve_min`, `min_score`) is shown with an Apply button, never applied silently.
5. Winner remix: a winner above 3x baseline reach gets sequel, part-2 and same-formula ideas (origin `sequel:<idea>`).
6. Comments as a source: top public comments of the best videos become ideas (origin `comment:<video>`).
7. The upload-title writer gets the Playbook's title note and the winning title shapes.
8. The script room gets the Playbook's script note (concept-level: what holds viewers), only after enough retention data.
9. Upload time: a best-hours card (advice only; uploads are manual).

## Stage 4: Evolve

- **Bandit** (`feedback/bandit.py`) for territory, style and tone: exploration share 35% (setting `explore`, allowed 30-40%): an explore pick takes the least-tried arm (including never-tried), otherwise the arm is drawn by softmax of its shrunk score. An arm with 4 or more flops and no winner is cooled down for 14 days (still reachable by exploring).
- **Experiments** are the labelled choices: the page compares exploit and explore results per factor.
- **Weekly evolution report**: with every new draft Playbook, the diff against the approved one and the experiment table.
- **Auto-feedback step** in the autopilot (setting `auto_feedback`): refresh outcomes after each sync, draft a Playbook when enough new graded videos exist, propose sequels and comment ideas. It only drafts: approval stays manual.

## Guardrails

- Small numbers: n and confidence are always shown; a pattern is used only above the minimum sample; early on the factory behaves as before.
- No Goodhart: the grade includes retention and engagement; rule R5 (real, verifiable facts) and "sharpen, never sanitise" are untouched; the owner pins principles the Playbook may never override.
- Owner in charge: Playbook drafts need approval; each insight can be disabled; the whole thing has an off switch (`use_playbook`).
- Comments and titles are data, never instructions: they are quoted into prompts inside labelled blocks.

## UI

"Learn" tab on the YouTube page: graded videos, lifts by feature with n, does-our-score-predict-views table, best hours, experiments, Playbook drafts (approve, reject, disable an item), pins, buttons (refresh, draft Playbook, sequels, comment ideas). The Ideas screen shows "Using Playbook vN".

## Owner decisions (2026-11-09)

1. Grade weights 40 / 30 / 15 / 15 (reach, retention, engagement, growth): approved.
2. A new Playbook version is used only after the owner reviews and approves it.
3. Exploration share 30-40% (default 35%).
4. Comments as an idea source and channel-history backfill: yes.

## Changes made to the first sketch

- Items carry a scope and evidence ids; uncited items are dropped by code.
- Threshold tuning is advice with an Apply button, not automatic.
- The tone arm is applied only on an explore roll, so most shorts keep the tone that fits their idea.
- Hours and weekdays are in IST.
- The privacy page lists public comments among the data read.
