# Source to Story

Phase 1 of a modular content pipeline. Import a **book (PDF)** or an **article (URL, pasted text, TXT/HTML)** and get a
searchable, scored, evidence-linked list of **story candidates** to review and export as JSON/CSV for a later
script-generation module. It does not write scripts, narration, images or video.

The previous news-podcast video generator is kept untouched in [legacy/](legacy/) and is no longer served.

## Run

```
pip install -r requirements.txt
copy .env.example .env      # set TRIPFICK_API_KEY and APP_PASSWORD
python main.py              # http://127.0.0.1:8905
```

`start.bat` runs `watch.py`, which starts the app, pulls new commits from `origin/master` and restarts when no source is being
processed. Unfinished processing resumes automatically after any restart.

Open the app, **Settings**, press **Test connection**, then **Import source**.

## How it works

1. **Ingest.** PDF text with page numbers (headers, footers and page numbers stripped), article extraction with headings,
   chapter detection (PDF outline, then heading patterns, then even parts). The original file is stored read-only with its
   SHA-256. Extraction warnings are shown; paragraphs and chapters can be corrected by hand.
2. **Process** (hierarchical, every unit checkpointed in SQLite):
   analyze chunks, consolidate chapters, build a source index, find story leads (per chapter group, then across chapters),
   merge duplicate leads, draft each story from the cited **raw passages**, score, flag related/duplicate stories.
   Details (events, dates, people, facts, caveats, open questions) are carried forward, not just summaries.
3. **Review.** Approve, reject, edit, merge, split, flag for research, override scores. Source links survive every edit.
4. **Export.** `GET /api/projects/{id}/export` (see [docs/story_schema.md](docs/story_schema.md)).

## Context budget

Nothing assumes the whole model window is usable. Settings hold the context limit (default **32768**; raise after testing),
output reserve, safety margin, chunk size, overlap, concurrency, retries and timeout. Every request is checked as
`instructions + input + output reserve <= context x (1 - safety)`; a request that would not fit is refused, never silently
truncated. If a reply is cut off at the output limit, the chunk is automatically split in two and analysed in two turns.
Invalid JSON is retried a bounded number of times with the validation error; failed replies are kept (Progress, errors).

## Model access

OpenAI-compatible `POST {base_url}/chat/completions`. Base URL, model id and key come from Settings / `.env`
(`TRIPFICK_BASE_URL`, `TRIPFICK_API_KEY`, `CHAT_MODEL`). The gateway reports no context length or tokenizer, so tokens are
estimated from characters (tunable). JSON mode is used only if the connection test shows the endpoint supports it.

## Tests

```
pip install pytest reportlab
python -m pytest                    # mocked model, deterministic
set LIVE_LLM=1 && python -m pytest -k live     # optional: real local model
```

## Layout

```
main.py            app entry, login, resume on start
story/db.py        SQLite schema        story/settings.py   runtime settings
story/ingest.py    PDF/HTML/text         story/chunker.py    budget-aware chunking
story/tokens.py    estimates + budget    story/llm.py        model client, JSON validation, retries
story/pipeline.py  stages, resume        story/scoring.py    explainable scores
story/review.py    edit/merge/split      story/export.py + contract.py  versioned export
story/api.py       HTTP API              static/index.html   UI
```

## Known limits

See the end-of-work report in the pull request / chat; notable: OCR needs Tesseract (untested without it), many news sites block
automated fetching (paste text instead), token counts are estimates, quality depends on the local model.
