# Story export schema v1.0

The export is the contract between this module (source to story candidates) and the next one (script generation).
It contains no model-specific fields: nothing in it depends on Gemma, the gateway, prompts or chunking.
The canonical definition is [story/contract.py](../story/contract.py); this page describes it.

Get it with `GET /api/projects/{id}/export?format=json&statuses=approved,pending` (or `format=csv`).
`statuses` is any of `approved`, `pending` (not yet reviewed), `rejected`, or `all`. Stories that were merged or
split into other stories are never exported; their replacements are. `text=false` omits passage text.

Versioning: `schema_version` is `MAJOR.MINOR`. Minor versions only add optional fields. A breaking change
bumps MAJOR. Consumers should check the major version.

## Top level

| field | type | notes |
|---|---|---|
| `schema_version` | string | `"1.0"` |
| `exported_at` | ISO 8601 UTC | |
| `generator` | object | `{module, schema_version}` |
| `source` | object | the book or article, see below |
| `filter` | object | `{statuses: [...], superseded_excluded: true}` |
| `stories` | array | ordered by effective priority, highest first |

### `source`
`project_id`, `title`, `author`, `format` (`pdf`, `article`, `text`), `url`, `sha256` (of the immutable original),
`pages` (PDF only), `estimated_tokens`, `chapters` (`[{index, title, page_start, page_end}]`), `imported_at`,
`overview` (source-level summary, empty if processing has not reached that stage).

## `stories[]`

| field | type | notes |
|---|---|---|
| `id` | string | stable, e.g. `S-1a2b3c-004`. Never reused. Merge and split create new ids. |
| `title`, `premise` | string | working title; one-sentence premise |
| `kind` | string | `incident`, `multi_passage`, `multi_chapter`, `case_study`, `surprising_fact`, `decision_sequence` |
| `curiosity_question`, `opening_hook` | string | editorial ideas, not narration |
| `overview` | string | short factual overview |
| `people` | `[{name, role}]` | |
| `chronology` | `[{when, what}]` | `when` is as stated in the source, may be empty |
| `conflict`, `stakes`, `turning_point`, `outcome` | string | empty when the source does not support them |
| `audience_interest` | string | why a general audience may care |
| `context_needed` | string[] | background required to follow the story |
| `claims` | array | key factual claims, see below |
| `uncertainties` | string[] | conflicting accounts, gaps, unverified items |
| `research_questions` | string[] | what to check next |
| `scores` | object | see below |
| `review` | object | `{status: pending|approved|rejected, needs_research, notes, edited}` |
| `references` | array | the supporting source passages, see below. Never empty. |
| `related` | `[{id, title, overlap}]` | stories sharing source passages |
| `duplicate_warnings` | `[{id, title, overlap}]` | probable duplicates (not merged automatically) |
| `warnings` | string[] | e.g. quotes not found verbatim, passages summarised because they did not fit |
| `lineage` | object | `{origin: pipeline|merge|split, merged_from: [ids], split_from: id|null}` |

### `claims[]`
`claim`, `quote` (verbatim text the model said supports it, may be empty), `quote_verified`
(`true` = found in the cited passages, `false` = **not found**, `null` = no quote), `support`
(`strong|moderate|weak`), `paragraph_ids` (links into `references[].paragraph_id`).

### `scores`
- `story_score` 0-100: weighted mean of five factors (hook, narrative, payoff, emotion, standalone), weights
  configurable in Settings. Before any manual override.
- `evidence_score` 0-100: kept separate on purpose. 50% the model's assessment, 30% share of claims whose quote was
  found in the source, 20% breadth of supporting passages.
- `priority` 0-100: `story_score * (1 - k + k * evidence_score / 100)`, with `k` = "evidence influence" (default 0.4),
  so a dramatic story with thin evidence ranks lower.
- `story_score_override`, `priority_override`: manual values set in review, or `null`.
- `effective_priority`: the override if set, otherwise `priority`. **Sort by this.**
- `factors`: `{hook|narrative|payoff|emotion|standalone: {score 0-10, reason}}`.
- `evidence_reason`, `evidence_breakdown`: why the evidence score is what it is.

### `references[]`
`paragraph_id` (stable within the source), `page` (PDF page, else `null`), `section` (article section or chapter),
`chapter_index`, `chapter_title`, `locator` (human-readable, e.g. `p. 214`), `text` (the passage, unless `text=false`).
Every merge or split keeps these links: a merged story references the union, a split story a subset.

## CSV
One row per story: id, title, premise, status, needs_research, effective_priority, story_score, evidence_score,
the five factor scores, kind, hook and curiosity fields, overview, conflict/stakes/turning point/outcome, pages,
sections, paragraph ids, claims, count of unverified quotes, uncertainties, research questions, duplicate and related
ids, notes. Multi-valued cells are joined with ` | `. UTF-8 with BOM so Excel opens it correctly. JSON is canonical.
