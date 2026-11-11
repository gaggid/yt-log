# Plan: Scene Director — automatic scene review, self-repair and a three-person audience panel

Status: **steps 1 (the storyboard check) and 2 (the scene review) are built and wired** (see docs/TASKS_scene_director.md); the rest is proposed. Written 11 Nov 2026 after the manual audit of short `sh-16824387`. Owner decisions are listed in section 12.

Written for: the owner of the factory, who decides what is built and in which order.

---

## 0. The principle: fix defects, show opinions

The system must not try to control everything. A short that has no defects and a bold idea is better than a short that scores well on every rule and looks like all the others.

- **Defects are fixed automatically.** A defect is something objectively wrong: the picture contradicts its own prompt or the narration, the wrong place, a wrong count, gibberish text, an object nobody asked for, a style break.
- **Taste is shown, never enforced.** Engagement, repeat, faces, places, composition and what the audience personas think are displayed as information and as suggestions with a one-click "Do it". They never change a picture by themselves unless the owner turns that on.
- **No quotas.** There is no "a face in one of three shots", no "at most two scenes per place" and no pass mark for Engagement or Repeat.
- **The model keeps the creative part.** When the system asks for a change it names the problem and never the picture.

## 1. Why: what the manual audit found

The audit of `sh-16824387` (17 start pictures) was done by hand. It found problems the system never noticed, and every one of them can be detected and fixed by the system itself.

| Finding in the audit | How big | Root cause found in the code and the sent prompts |
|---|---|---|
| A pile of rupees and gold coins in pictures that never asked for it | 9 of 17 pictures | `stills.looks_line` added any plan subject whose FIRST word appeared in the picture text, so "Indian Rupees" (and the place "Indian street market") was added to every shot that said "Indian". Found while building step 1; the planner's own subject lists were clean |
| Market background where the shot says living room or office | 6 pictures | The same bug: the place subject "Indian street market" was pulled in by the word "Indian" and became the shot's "Setting:" line |
| Camera angle ignored ("low angle") | 2 of 2 | Angle is a few words at the start of a long prompt |
| Gibberish text and numbers on screens and banknotes | 1 hook picture, all banknotes | The image model cannot write text |
| Wrong head count or pose, style break | 3 pictures (s11, s12, s10) | Long prompts lose counts; empty background invites a style break |
| Same scene again and again | 5 of the last 8 scenes are near copies of earlier ones (repeat score 9 of 10) | Nothing compares a picture with the pictures before it |
| Weak stretch of 5.5 seconds before the closing call to action | s11 to s13 (engagement 3, 3, 5) | Nothing predicts where a viewer would swipe away |

The existing agent (`shorts/agent.py`, `shorts/evaluators.py`) already has a retry loop with a score and a decision log, but its picture checkpoint reads only the **text** of the picture prompts. It never looks at a picture. That is the gap this plan closes.

### 1.1 Prototype test (11 Nov 2026) and what it changed

A throw-away script (outside the app, nothing saved) ran the vision review and the three persona calls on `sh-16824387` (17 pictures) and the first 6 pictures of `sh-7d085858`, and the result was compared with the manual audit.

| Finding | Result | Decision |
|---|---|---|
| A model that sees the prompt and is asked "is anything wrong?" agrees with the prompt | Caught 0 of 9 stray money piles, 3 of 6 wrong places, 0 of 1 gibberish text, 2 of 2 wrong counts | **Do not use it for defects** |
| A model that only describes the pictures (it never sees the prompt) and code that compares the description with the prompt | Caught 8 of 9 stray money piles (the miss was a crude word list), 6 of 6 wrong places, the gibberish text, 0 false alarms; also flagged the numbers printed on banknotes | **Layer 2 uses describe-blind, compare-in-code** |
| Strict JSON output (`response_format` `json_schema`, which the gateway accepts) with **fixed labels** (enums for place, style, camera height) | Valid JSON every time, but the labels collapsed into defaults: "street" for a phone close-up, a key and a pair of shoes, camera height "eye level" for every picture, the isometric picture called "painted", the gibberish text missed. One-picture calls did not fix it | **No enum labels for judgement fields** |
| Strict JSON output with **free-text fields** (place, background, text, style as plain strings; counts as integers) and the picture never shown the prompt | Caught 9 of 9 stray money piles, 6 of 6 wrong places, the blank backgrounds and the isometric style break (2 of 2), and the gibberish text (1 of 1), with no false alarms on those; 29 to 37 s per six-picture sheet | **This is the Layer 2 call**: valid JSON guaranteed, no retries for bad JSON |
| Three separate persona calls | Disagreed by 30 points or more on 7 of 17 scenes; each matched its persona; all three rated the weakest scenes (s11, s16, s17) high-risk | Keep three separate calls |
| Raw persona numbers | Far too pessimistic: predicted survival over 35 seconds near 0% | Use as a **ranking and hotspot finder** until calibrated; label the curve "uncalibrated" |
| Misses | Personas rated the s1 hook low-risk despite gibberish text, and barely noticed the isometric s12 | The defect check (not the personas) must catch glitches and style breaks |
| Time per call | Judge sheet 42 to 57 s, blind-describe sheet 25 to 34 s, persona 51 to 54 s | Estimates in section 8 hold or are slightly high |

## 2. What you get

1. Every short is checked scene by scene by the system, before a person looks at it, with three scores per scene: **Engagement**, **Repeat** (how much it looks like earlier scenes) and **Proof** (does it show what the narration says and what the prompt asked).
2. The system **fixes objective defects by itself** (redraw, rewrite a prompt, remove a stray object, change a setting), checks that the defect is really gone and no new one appeared, and keeps the old picture if not. Everything about taste is shown to you as information and suggestions, not changed.
3. **Three different audience members** (the Scroller, the Relater, the Analyst) rate every scene and say where and why they would swipe away. The three answers become a predicted retention curve and a "most likely drop-off point" for the whole short. This is a report for you: it never changes a picture.
4. The result is shown on the short's page as a score badge on every scene, a retention curve, a list of what the system fixed and reverted, and a list of suggestions you can accept with one click.
5. Later, real YouTube retention curves calibrate the personas so the predictions get closer to what the channel's audience really does.

## 3. The big picture

```
Plan the short
  -> [Layer 1] Storyboard lint            free, no picture drawn yet; fixes contradictions (stray subjects, setting clashes)
  -> Draw the start pictures
  -> [Layer 2] Scene review               a vision model looks at every picture: proof, defects, scores
  -> [Layer 4] The Director               fixes defects only, keeps a fix only if the defect is gone
        (loop: at most 2 rounds)
  -> [Layer 3] Audience panel             three personas on the final pictures: a report, never a gate
  -> Person looks at the pictures         sees scores, suggestions, the curve and the log of what changed
  -> Motion is written from the pictures  (already built)
  -> Clips, put together, upload text
```

Layer 1 runs without any GPU time and removes most problems before a single picture is drawn. Layers 2 to 4 run after the pictures exist, inside the same one-job lock as everything else (the gateway serves one request at a time).

## 4. Layer 1: Storyboard lint (before drawing)

Rules written in code, run when the shots and still prompts exist. Only rules about **contradictions** act. Rules about taste only leave a note.

| Rule | What it checks | What happens |
|---|---|---|
| Subject discipline | A recurring subject (the money pile) is only added to a shot whose own picture text names it | **Fix:** remove the subject from the shot's "How they look" block |
| Setting agrees | The shot's "Setting:" line must match the plan's place and the words of its own picture text | **Fix:** replace the setting by the place from the picture text; if the text names none, use the plan's place |
| Angle wording | A requested angle is written as a full sentence ("seen from below, looking up at him"), not two words | **Fix:** rewrite |
| No text in pictures (decided by the owner: the video model handles text badly) | A picture carries no readable text at all: no screen text, signs, labels, logos or numbers on banknotes. Screens are asked as blank or a soft glow, notes as plain paper without print, signs as blank boards | **Fix:** rewrite the picture prompt; if a number or short phrase really matters, mark a short overlay (at most 4 words or one number) to add at the final step, never inside the picture |
| Count guard | A group name ("family") must carry an exact count and pose | **Fix:** add the count |
| Place repeat | Several shots in the same place | **Note only:** "scenes 3, 8, 11 share a place" |
| Composition repeat | Same size, arrangement and main object in several shots | **Note only** |
| Faces | How many shots show a person | **Note only** |

Why this layer matters most: these rules alone remove the two biggest problems in the audit (the money piles and the wrong places) at zero cost.

## 5. Layer 2: Scene review (after drawing)

A vision model (the gateway's chat model, now able to take pictures) looks at the real pictures. Pictures are sent small and in contact sheets of up to six, so a 17-shot short is three pictures per call, not 17.

### 5.1 What it checks: the AI reports, the code decides

The vision model is **never shown what the picture was asked to show**. It only describes what it sees. Plain code then compares the description with the prompt. This is what the prototype test proved (section 1.1).

**Step A, blind description (AI, one call per sheet of six pictures, strict JSON).** The call uses the gateway's strict JSON schema (`response_format` `json_schema`, so the reply is always valid JSON) with plain-text fields and integer counts, and no fixed-label lists for place, style or camera height (the prototype showed that fixed labels make the model fall back to defaults). For every picture it returns: the place and whether it is indoor or outdoor, the number of people, every clearly visible object, any readable text or numbers (and whether they look like real words), the art style, the shot size, how things are arranged, whether a face is visible, and the two soft scores Read and Pull (0 to 2 each).

**Step B, comparison (code).** It compares the description with the shot's picture text, its `must_show` list and the plan's place:
1. **Extra object:** a visible object (a money pile, for example) that the picture text does not name.
2. **Wrong place:** the described place does not match the place in the picture text (or the plan's place when the text names none).
3. **Wrong count:** the described number of people or things differs from an exact count in the text.
4. **Text in the picture:** any readable text or numbers at all (the no-text rule), including numbers printed on banknotes.
5. **Style break:** a different art style, or an empty blank background.
6. **Unchecked:** a `must_show` item that cannot be matched to the description is shown as "not checked", never as "passed".

**Step C, scene tags (from the same call).** Place, subject, objects, size and arrangement feed the Repeat score.

### 5.2 The three scores (each recorded with the reasons)

| Score | Range | How it is made |
|---|---|---|
| **Engagement** | 0 to 10 | Five parts, 0 to 2 each: Read (one clear subject on a phone), Pull (face, emotion, surprise, contrast, status), Proof (shows the narration line), Clean (no defects), Move (will look alive when animated and differs from neighbours). The first three seconds count double in the short's average |
| **Repeat** | 0 (new) to 10 (near copy) | Two measured parts and one judged part, compared with every earlier picture, not only the one before. Measured: colour match and layout match (already prototyped on `sh-16824387`, results in the audit). Tag overlap (code): same place, same subject, same objects, same arrangement from the scene tags of Step A. The score uses the closest earlier scene; the closest scene is named |
| **Proof** | 0 to 10 | Share of `must_show` items present, minus defects, plus a point when the picture matches the narration line |

A scene is **broken** when it has a defect or Proof is below 7. Only broken scenes are fixed automatically. Engagement and Repeat only colour the scene's badge and feed the suggestions: they have no pass mark and trigger nothing by themselves. The short gets a summary for the person: average of each score, the weakest stretch (three scenes in a row with average Engagement below 5), and the repeat trend from first half to second half.

### 5.3 When a short passes (decided by the owner: no defects, plus three low floors)

A short passes without a person when it has **no defects and clears three floors**. The floors are set low on purpose. They catch disasters, not taste.

| Floor | Rule (starting values, editable on the rules page) | If it fails |
|---|---|---|
| Hook | Each of the first two scenes has Engagement of 4 or more | **Needs your look** |
| Dead stretch | No three scenes in a row all with Engagement of 3 or less | **Needs your look** |
| Duplicate | No scene is a near-duplicate of an earlier one (measured match of 85% or more **and** the same place and subject tags) | Treated as a defect: fixed automatically, by naming the duplicate to the picture writer |

"Needs your look" means the short stops before the clips are made (saving about 20 minutes of gateway time on a short that is likely to be weak), and it waits on the short's page with the reasons and the suggestions. Nothing is rewritten for a floor failure, because that would be a taste change. If two shorts are already waiting for a look, the next short continues with a warning instead of stopping, so the autopilot never jams. The audit short `sh-16824387` would have **cleared** all three floors (hook scenes 5 and 7, no three low scenes in a row), but it had many defects, which the Director would fix.

## 6. Layer 3: The audience panel — three personas

Three viewers who differ in how they think, how they feel and how they are watching. Each one looks at the same pictures and hears the same narration line, and rates each scene from their own point of view. The point is that they leave for different reasons, so the system learns to fix three kinds of problems, not one.

### 6.0 The channel's real audience (owner's YouTube Studio, last 28 days to 10 Nov 2026)

| Fact | Number | What it means for the personas |
|---|---|---|
| New viewers | 99.3% (casual 0.7%, regular under 0.1%); 99.9% of watch time is from people who are not subscribed | Every viewer is a stranger meeting the channel for the first time from the feed. No loyalty, no patience: the first seconds decide everything, so all three personas are written as cold viewers |
| Gender | Male 77.1%, female 23.0% | Two of the three personas are men; the third stands for women and family-minded men |
| Age | 13 to 17: 2.6%, 18 to 24: 14.9%, **25 to 34: 34.3%, 35 to 44: 29.9%**, 45 to 54: 11.5%, 55 to 64: 4.3%, 65+: 2.6% | 64% are 25 to 44. A "20 to 24" persona would be too young to carry 40% of the weight |
| Device | Mobile phone 95.2%, TV 2.1%, tablet 1.5%, computer 1.2% | Everything must read on a phone screen, held in one hand |
| Country and language | India 81.2%; 83.2% watch without subtitles or CC | Indian context, Hindi and Hinglish; the video's own burned-in captions matter more than YouTube's |
| When they watch | Active from late morning to midnight; busiest around 18:00 to 23:00 and at noon; quiet from 02:00 to 08:00 | Personas are set in the noon break, the evening and late night |
| What does best | A hidden-structure-under-the-Moon mystery (3.3K), India vs China air force (2.5K), Hampi's musical pillars (1.9K), India vs China army (1.4K), Elon Musk's master plan (1.3K) | Curiosity, science mystery, defence comparisons, heritage and tech. Emotional or family stories are not what the channel is known for |

### 6.1 The personas

Weights follow the numbers above and are refreshed from the real demographics once a month, with the owner's approval (section 10).

| | **1. The Analyst** ("Rohan", 30 to 44) | **2. The Scroller** ("Arjun", 18 to 28) | **3. The Relater** ("Priya", 28 to 45; stands for women and family-minded men) |
|---|---|---|---|
| Weight | **40%** (the 25 to 44 male explainer viewer is the channel's core) | **35%** (under 25 is 17%, plus the impulsive part of 25 to 34) | **25%** (23% women plus family-minded men) |
| Has never seen this channel | Yes, decides on this video alone | Yes | Yes |
| Mind | High need for cognition, sceptical, wants a point he can trust | High sensation seeking, low patience for thinking, wants stimulation now | High empathy, wants to feel understood, decides with feeling |
| Body and setting | Evening after work or late night, sound on, phone in hand, pays attention if it is worth it | Noon break or late night, thumb already moving, sound sometimes off, decides in about one second | Evening at home, sound on, relaxed but easily put off by coldness |
| What holds them | A specific number, a clear comparison (India vs China), a surprising fact, a fair argument, clean visual metaphors | Fast change, bright colour, a mystery or "wow" visual, faces, surprise, a new look every 2 to 3 seconds | Real human faces, family and money-stress moments, heritage and human stories, warmth, a payoff that says "that is me" |
| What makes them swipe | Cliché openings, wrong or vague claims, AI glitches (wrong counts, odd hands), fluff, clickbait with no answer | Same look for 3 scenes, slow or static, anything unclear in the first 1.5 s, walls of text | Cold objects with no people, preachy tone, line and picture that do not match, no emotional payoff |
| Reads captions | Yes, checks the numbers | Yes (sound may be off) | Sometimes |
| Fit with the channel's usual topics | High | High for mystery and shock, medium for dry comparisons | Lowest: expects a higher swipe risk on defence and geopolitics scenes, which is information, not a fault |
| Rates mostly | Proof, Clean, credibility | Pull, Move, Repeat | Pull (faces), Proof (line fits picture) |

### 6.2 How a persona rates a scene

For each scene the persona answers with:
1. **Swipe risk** (0 to 100%): the chance this viewer leaves during this scene, given that they are still watching at its start.
2. **One reason code** from a fixed list (for example: unclear, boring, repeated, cold, off-topic, glitch, too slow, no payoff, cringe) and one sentence of explanation tied to what is in the picture.
3. **What would keep them**: one concrete change ("show a face", "show the number big").

**Three separate requests, never one.** Each persona is its own call to the model, so one answer can never blend into another:
- Each request has its own system text holding only that persona's card. The other two are never mentioned.
- Each request starts fresh (no shared conversation) and sees only the pictures, the narration line of each scene and its timing. It does not see the Engagement or Repeat scores, or what the other two said, so nothing anchors it.
- The order of the three calls is shuffled on every run, so any order effect averages out; each call has its own seed, stored with the result.
- The reply format has room for one persona only, and code rejects a reply that names another persona or gives almost the same risk to every scene.
- A test checks all of this: three requests, three different system texts, none containing another persona's card.

One call per persona covers the whole short (all scenes in order), not one call per scene: a viewer's patience builds up or runs out across scenes, so the persona has to see the sequence.

Other rules that keep the three from sounding the same:
- Each persona gets its own profile and its own list of triggers, and must name a concrete cause in the picture.
- Each persona must rank the scenes from "safest" to "most likely to leave", which forces a spread instead of "7 for everything".
- A test checks the spread: the three personas must disagree on at least a few scenes in the standard test short.

### 6.3 From ratings to a prediction

- Per persona: survival after scene n = the product of (1 − swipe risk) for scenes 1 to n.
- Panel curve: weighted average of the three survival curves.
- **Predicted drop-off point:** the first scene where the panel's survival goes below 50%, plus the single scene with the largest swipe risk, each with its reason.
- **First-three-seconds hold:** panel survival after the first two scenes (the "viewed vs swiped away" moment).
- Per scene: the persona who is most likely to leave there and why.

In the prototype the raw swipe risks were far too high (a predicted survival near 0%), so until real retention data calibrates them the panel shows the **ranking** (safest to riskiest scenes), the **hotspots** where two or three personas agree, and each persona's reason. The curve is shown but labelled "uncalibrated". This is a model of viewers, not real data. It is a report only: it never triggers a fix by itself, and it runs once, on the final pictures. It is checked against real retention data once shorts are published (section 10).

## 7. Layer 4: The Director (fixes defects, suggests the rest)

### 7.1 The action menu
Every finding maps to a fixed action. The Director never invents new kinds of actions, so what it can do is limited and easy to audit.

| Finding | Action | Done by (existing code) | Level |
|---|---|---|---|
| Stray subject | Remove it from the shot and redraw | `subjects`, `stillwriter`, `clips.make_keyframes` | A: automatic |
| Wrong place | Fix the setting line and redraw | `stillwriter` with a note, `make_keyframes` | A |
| Angle ignored | Rewrite the angle sentence and redraw with a new seed | `stillwriter`, `make_keyframes` | A |
| Gibberish text | Rewrite to a blank screen; mark an overlay | `stillwriter`; overlay in the final step | A |
| Wrong count or pose | Rewrite with exact count and redraw (max twice) | `stillwriter`, `make_keyframes` | A |
| Small defect only | Change one thing in the picture by edit | `clips.fix_keyframe` | A |
| Style break or blank background | Redraw with the style line emphasised | `stills`, `make_keyframes` | A |
| Weak motion line | Rewrite the motion from the picture | `motionwriter` (already built) | A |
| Looks like an earlier scene (high Repeat) | Show the closest scene and one idea for a different picture | `stillwriter` with a note, only on "Do it" | S: suggestion |
| Low Engagement | Show what the personas and the scores point at and one idea | `stillwriter` with a note, only on "Do it" | S |
| Three weak scenes in a row | Show the stretch and a suggestion to change the weakest scene | `planner` (shots), only on "Do it" | S |
| A beat that does not support the narration | Suggest rewriting the shots of that beat | `planner.reshoot_beat`, only on "Do it" | S |
| Narration or hook wording | Never changed by this step (the existing narration checkpoint owns it) | n/a | Person |

Level A actions run by themselves. Level S items are suggestions with a one-click "Do it". The owner can later switch on automatic polishing for the S items (section 7.5), and it stays off until then.

### 7.2 Every fix is a trial
1. Apply the change and make a new attempt of the picture (pictures are numbered attempts and are never overwritten, so going back is just choosing the earlier attempt).
2. Re-score only the changed scene (Layer 2).
3. **Keep** the new picture only if the defect is gone and no new defect appeared. Otherwise **revert** and log why. Engagement and Repeat are never used to decide: a fix is judged on whether it removed the defect, not on whether the picture scores higher.
4. Never make two changes to the same scene in one round.

### 7.3 Limits (so it can never run away)
- At most 2 rounds per short. A round ends early when no scene is broken.
- At most 30% of the scenes redrawn per round (6 of 17).
- A scene that failed two trials is left for a person.
- A round stops if the number of defects does not go down (the same idea as the existing "score did not improve" rule in `agent.py`).
- A time budget per short (default 25 minutes of review and redraw). When it is used up the short continues with what it has.
- A failure anywhere never stops the short. The review is advice plus defect fixes, not a gate. (Same rule as music and publish text.)
- Everything it does is written to the decision log (`story.agent_store`), and past fixes that worked become examples for later runs.

### 7.4 What it will not do without the owner's say
Change the narration, reorder beats, add or remove beats, or change the style, voice or length.

### 7.5 Creative freedom: control less, show more

The earlier draft of this plan had rules that could push every short to the same safe, loud look (keep a fix only when the score rises, a face in one of three shots, at most two scenes per place, persona preferences steering fixes). They are removed. What remains:

1. **Only objective defects are acted on.** Everything else is information.
2. **No quotas and no pass marks on taste.** No face rule, no place rule, no target for Engagement or Repeat.
3. **A fix is judged on the defect, not on the score** (section 7.2).
4. **The Director names the problem, never the picture.** "This picture has a pile of money nobody asked for." The picture writer chooses what to draw.
5. **Personas are a smoke alarm for you, not a judge.** They run once on the final pictures and show a curve and reasons. They steer nothing unless you turn it on after the curve has been compared with real retention.
6. **A dial in the settings:**
   - *Defects only* (default): only objective defects are fixed; everything else is shown.
   - *Suggest*: the same, plus a ready-made suggestion on every scene with low Engagement or high Repeat.
   - *Auto-polish* (opt-in): the system also applies the suggestions by itself, one change per scene, locking any scene with Engagement 8 or more, and judging each change on Engagement and Repeat as well as defects.
7. **Every rule is listed and can be switched off.** A rules page lists each check, what it does and why, with an on/off switch, so nothing acts as a hidden law.
8. **A control group, only where taste is involved, and a sameness watch.** Fixing a defect (a stray money pile, gibberish text) does not need an experiment, so no short is shipped on purpose with known defects. The control group starts when a taste feature is switched on: once *Suggest* is applied automatically or *Auto-polish* is on, one short in five stays at *Defects only* (using the existing explore share of the feedback loop), and the feedback loop compares real retention of the two kinds. The system also measures how alike the channel's last 10 shorts look (the same colour and layout measure) and shows a note if they are drifting together. Both are reports; if the taste features do not help real retention, they are switched off.

## 8. Where it runs, time and cost

### 8.0 AI calls and what is plain code

Counted for a 17-scene, 6-beat short. A "call" is one request to the chat or vision model. Image drawing is counted separately.

| Layer and step | Typical short | Worst case | Notes |
|---|---|---|---|
| 1. Storyboard lint | **0** | 0 | Pure code. Its rules are given to the first picture-writing call as constraints, so there is no extra call; a reply that breaks a rule is sent back by the existing validator (extra calls only when that happens) |
| 2. Scene review | **3** | 4 | 3 blind-description sheets (6 pictures each); 1 extra call only if a count needs a second look |
| 3. Audience panel | **3** | 3 | One call per persona, three separate requests, once, on the final pictures (it steers nothing, so no second run) |
| 4. Director, rewrite picture prompts | **3** | 8 | One call per beat that has a scene to fix (the existing picture writer) |
| 4. Director, re-score changed scenes | **1** | 3 | One call per 6 changed pictures |
| 4. Director, images redrawn | 4 images | 12 images | Image model, about 1 minute each |
| Motion rewrite from pictures | 0 extra | 0 extra | Already part of the existing "motion" step |
| **Total new model calls** | **10** | **18** | Plus 4 to 12 image draws (with the dial on Defects only, usually fewer: only broken scenes are redrawn) |
| **Light mode** (review only, no panel, no automatic fixes) | **3** | 4 | |

For comparison, making a short today already takes roughly 30 calls (script room, shots, picture prompts, motion, upload text), by my count. The review therefore adds about 33% in a typical run. At 25 to 55 seconds per call with pictures (measured in the prototype) that is about 8 minutes, plus about 4 minutes of image drawing.

### 8.0.1 What is deterministic (plain code, no AI) and what is AI

| Part | Code or AI |
|---|---|
| All storyboard lint rules (subject discipline, setting agreement, angle wording, no-text rule, count guard, and the notes on place, composition and faces) | **Code** |
| Building the contact sheets | **Code** |
| Colour match and layout match between pictures | **Code** (image maths) |
| **Repeat score**: combining the measured match with the overlap of scene tags (place, subject, objects, size, arrangement) | **Code** (only the tags come from the AI) |
| **Proof score**: share of "must show" items present, minus defects | **Code** (the yes/no per item comes from the AI) |
| **Clean** and **Move** parts of Engagement: defect count; camera kind, static camera share, strength of the action verb in the motion line | **Code** (existing `motionwriter` checks) |
| Engagement total, double weight for the first 3 seconds, weak-scene flags, weakest stretch, repeat trend | **Code** |
| Retention maths: survival, weighted panel curve, drop-off point, first-three-seconds hold | **Code** |
| Choosing the action for each defect, the order of fixes, budgets, rounds, stop rules, keep-or-revert on the defect, the one-change-per-scene rule | **Code** (a fixed rules table) |
| Checking that persona replies are valid and spread out | **Code** |
| Calibration against real YouTube retention (fitting multipliers and weights) | **Code** (simple fitting maths) |
| Decision log, staleness marks | **Code** |
| Reporting what is in each picture (place, people, objects, text, style, arrangement) and the soft scores Read and Pull | **AI** (vision; it never sees the prompt) |
| Deciding what is a defect by comparing that report with the prompt | **Code** |
| The three persona ratings and their reasons | **AI** (three separate calls) |
| Writing the new picture prompts and any suggested changes | **AI** (the creative part stays with the model) |
| Drawing and editing the pictures | **AI** (image model) |

So the AI reports what it sees and writes the creative parts; every score formula, decision and limit is code that you can read, test and change.

## 8.1 Where it runs, time and cost

| Step | When | GPU or gateway time (estimate) |
|---|---|---|
| Layer 1 lint | After the shots are written, before drawing | None |
| Scene review (Layer 2) | After the start pictures | About 3 to 5 minutes (3 picture-sheet calls plus scoring), measured: a call with 2 to 3 pictures took 40 to 65 seconds |
| Audience panel (Layer 3) | After the review | About 3 to 5 minutes (3 personas, one call each) |
| Director fixes (Layer 4) | After the panel | About 1 minute per redrawn picture plus about 2 minutes to re-score; usually 2 to 5 pictures |
| **Total per short** | | **About 12 to 30 minutes**, no GPU time at all for Layer 1 alone |

For comparison, the clip step takes about 20 minutes with the new default (opening at full steps, rest fast), so the review fits inside the autopilot's two-hour rhythm. A "light" mode (Layers 1 and 2 only, no panel, one round) is available for quick runs.

It runs as a new optional auto-run step **after the start pictures and before the human look** (the order now is: pictures, look, motion from pictures, clips). It is also a button on the short's page and a setting for the Ideas autopilot.

## 9. What the owner sees

- **Contact sheet** of the start pictures with three small badges on every scene (Engagement, Repeat, Proof) and a colour: green, amber or red.
- **Click a scene:** the five Engagement parts, the closest earlier scene (side by side), the three personas' swipe risks with their one-line reasons, and the log of what the Director did to it ("redrawn: removed stray money pile, Repeat 9 to 3, kept").
- **Retention curve:** the panel's predicted viewer curve over the 30 seconds with the three personas as thin lines and the predicted drop-off point marked.
- **Summary card:** average scores before and after the Director, how many fixes were kept or reverted, and the list of suggestions (Level S items) with a "Do it" button each.
- **Settings:** review on or off, autonomy level, persona weights, time budget, "light mode".
- On the Ideas screen the done cards show the review scores so the owner sees which kinds of ideas produce weak scenes.

## 10. The learning loop: making the personas honest

Personas are a model. Real data decides whether they are right.

1. **Collect:** extend the YouTube sync (`youtube/sync.py`) to read the real audience retention curve of every published short (the read-only Analytics scope already in use allows it) and the channel's viewer age, gender, device and country split (the persona weights are first set from the owner's screenshot of 10 Nov 2026 and are then refreshed from this data).
2. **Compare:** line up the predicted panel curve with the real curve by 10% steps of the video. Show both on the Learn tab with the error.
3. **Calibrate:** fit one multiplier per persona on swipe risk, and the persona weights, so the predicted curve matches the real ones. Needs at least 10 shorts inside the learning window (the existing rule: only videos on or after the learning start date count).
4. **Apply with the owner:** the calibration is proposed with an Apply button, the same pattern as the idea-score threshold advice. A calibration is only used after approval, like the Playbook.
5. **Feed the playbook:** when a type of scene repeatedly predicts drop-offs that also happened for real, it becomes a Playbook lesson ("scenes of an object alone with no face lose the Scroller"), cited with the videos behind it.
6. **Re-check the rubric:** each month compare the Engagement score with the real watch time per short; if the correlation is weak, change the rubric.

## 11. Build plan

| Phase | Delivers | Main work | Size | Depends on |
|---|---|---|---|---|
| **0. Gold set and rubric** | Fixed scoring rules and a test fixture. The prototype test is already done (section 1.1) | Turn the audit of `sh-16824387` and the prototype results into a stored gold set (defects by scene, scores, closest scenes); write the rubric and persona cards as data files | S | none |
| **1. Storyboard lint + the two root-cause fixes** (BUILT 11 Nov 2026) | The money-pile and wrong-place problems disappear; no GPU time | `shorts/lint.py` with the rules in section 4; wire subject discipline and setting agreement into `stillwriter` and `stills.prompt`; run in the plan step; tests on `sh-16824387` data | M | 0 |
| **2. Scene review** (BUILT 11 Nov 2026) | Defects, Engagement, Repeat per scene with reasons | `shorts/review.py`; the blind-description call through `JsonCaller.call(images=)` (built); contact-sheet builder with shot labels; the comparison code (extra object, wrong place, wrong count, text, style break); scene tags; measured colour and layout similarity; stored in `short["review"]` with a hash of the pictures | L | 0 |
| **3. The Director** | Automatic fixes with trial and revert | `shorts/director.py`: the action menu, trial and keep-or-revert, budgets and stop rules; decision log; new auto-run step; `POST /{id}/review` and `/{id}/director`; Level A and B actions first | L | 2 |
| **4. Audience panel** | Persona ratings, retention curve, predicted drop-off | `shorts/panel.py` with the three persona cards; ranking rule; curve maths; spread test; feeds the Director's weak list | M | 2 |
| **5. Screens** | Badges, contact sheet, curve, log, settings | `static/shorts.js` review panel; Ideas screen badges | M | 2, 3, 4 |
| **6. Calibration** | Predicted versus real curves; calibration with Apply | Retention report in `youtube/sync.py`; `feedback/personas.py`; Learn tab card; Playbook lessons | L | 4, and 10 or more published shorts |
| **7. Autopilot and guardrails** | Runs by itself on every autopilot short within the time budget | Review settings in the Ideas config; light mode; the dial (Defects only, Suggest, Auto-polish); the rules page with on/off switches; Level S suggestions with one-click buttons; the control group and the sameness watch | M | 3, 5 |

**Rollout (decided by the owner's delegate, to be confirmed): shadow first.** The vision review is new and its judgement is unproven, so a wrong "defect" could cause a pointless redraw.
1. **Phase 1 (the free storyboard lint)** goes live at once: it is plain code and only fixes contradictions.
2. **Phases 2 and 3 run in shadow mode for the first 5 shorts:** the review scores every scene and writes down what the Director *would* fix, but changes nothing. You compare its list with your own eyes on the short's page (the audit of `sh-16824387` is the model for this).
3. If its defect calls agree with yours on most scenes (a call counts as wrong when you would not call it a defect), the dial switches to *Defects only* and the Director starts fixing. If not, the rubric and prompts are corrected and shadow mode is repeated.
4. The audience panel stays report-only throughout.

**Order of value:** Phase 1 first (immediate, free, fixes the worst problems), then 2 and 3 together (the Director), then 4 (the panel), then 5, 7 and 6. Phase 1 can ship on its own.

## 12. Decisions

Decided on 11 Nov 2026:

1. **Autonomy: yes.** Only objective defects are fixed automatically. Everything about taste is a suggestion until Auto-polish is switched on.
2. **Pass rule: partly.** No defects, plus three low floors (section 5.3). Engagement and Repeat have no pass mark beyond those floors.
3. **Autopilot default: *Defects only*.** The control group starts later and applies only to taste features (section 7.5, item 8). The vision review starts in shadow mode for the first 5 shorts (section 11).

Also decided on 11 Nov 2026 (owner's answers and the screenshot of the channel's audience):

4. **Time budget: yes.** 25 minutes of review and redraw per short is accepted. The autopilot cycle stays at 2 hours for now (the owner also allowed 2.5). It is raised to 2.5 hours only if the shadow-mode shorts (section 11) show a whole short, from pictures to the final video, running longer than about 100 minutes, or the idea and brief jobs that share the gateway make the cycle run late. The cycle is a setting on the Ideas screen, so this can change any day.
5. **Audience: confirmed; persona weights set from the real data:** Analyst 40%, Scroller 35%, Relater 25% (section 6).
6. **Text: keep it out of the pictures.** No readable text inside any picture (section 4). A number or a short phrase (at most 4 words) can be added as an overlay at the final step, never inside the picture that goes to the video model.

## 13. Risks and how they are handled

| Risk | Handling |
|---|---|
| The judge model is generous or inconsistent | Fixed rubric with reasons; pairwise comparison when a fix is judged; gold set test; monthly check against real watch time |
| Personas all rate the same | Own profile and triggers each; forced ranking; a spread test on a fixed short |
| Counting objects is where vision models are weakest | Counts use a second look; two failed tries hand the scene to a person |
| Over-fixing makes every scene alike (optimising for the score) | Fixes are judged on defects, not on score; taste is only shown; the dial defaults to Defects only; a control group and a sameness watch measure it; two-round cap; the owner sees every change |
| Redraws cost gateway time | Layer 1 prevents most redraws; per-round redraw cap; time budget; light mode |
| The gateway serves one request at a time | Runs inside the existing one-job lock; the review waits like every other job |
| A prediction that is wrong looks authoritative | The curve is labelled as a model until calibrated; calibration needs approval |

## 14. Engineering notes

- New modules: `shorts/lint.py`, `shorts/review.py`, `shorts/panel.py`, `shorts/director.py`; persona cards and the rubric as data (`shorts/personas.py` or JSON) so they can be edited without code changes; `feedback/personas.py` for calibration.
- Reuse: `JsonCaller.call(images=...)` (vision input, built and tried on the real gateway); add a `response_format` option to it for the strict JSON schema (tried on the real gateway, accepted), `stillwriter.write_beat(note=...)`, `clips.make_keyframes`, `clips.fix_keyframe`, `motionwriter.write_seen`, the checkpoint loop and decision log in `agent.py` and `story/agent_store.py`, `checks.py` issue and fix codes, and the Feedback loop pages for calibration and the Playbook.
- Data: `short["review"] = {round, picture_hash, scenes: {id: {engagement{read,pull,proof,clean,move,total}, repeat{score, closest, measured{colour, layout}, tags}, proof{must_show[], defects[]}, panel{persona: {risk, reason, keep}}}}, panel{curve, drop_scene, hold}, actions[{scene, type, level, result: kept|reverted|needs_you, before, after}], budget_used_s}`; marked stale when the pictures change.
- API: `POST /api/shorts/{id}/review` (run), `GET /api/shorts/{id}/review`, `POST /api/shorts/{id}/review/apply` (a Level S suggestion).
- Auto-run: new step `scenes` in `auto.steps` and `auto.run`, after `keyframes` and before the human `review` checkpoint (rename that checkpoint "look" to avoid a name clash); keep `static/shorts.js` step list in sync.
- Tests: fake vision answers in `tests/shorts_fakes.py`; the gold set from `sh-16824387`; tests that every action is reverted when the score does not improve, that budgets stop the loop, that a failed call never stops a short, and that the three personas disagree on the fixed short.
- Docs to update when built: `CLAUDE.md` (Shorts section), `docs/RUN_LOG.md` (first real run), and a `docs/TASKS_scene_director.md` task list.
