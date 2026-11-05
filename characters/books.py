"""Book reading system for Virtual Life characters.

PDF upload → text extraction → chunk per chapter → LLM summarises each chunk
into 3-5 impressions (stored once). Character reads one chapter per session,
absorbs impressions as learning memories, bumps interests and curiosities.

Character chooses which book to read from her wishlist (LLM pick based on
interests/curiosities). She can skip a book with a reason; it resurfaces after
14 days unless permanently ignored.
"""
import hashlib
import json
import re
import time
import uuid

from story import db, llm as llm_mod

CHUNK_TOKENS   = 800    # approximate tokens per chapter chunk
IMPRESSIONS_N  = 4      # target impressions per chapter
PICK_MAX_BOOKS = 8      # max books shown to LLM when picking
RESURFACE_DAYS = 14     # days before a skipped book is offered again
MAX_CHAPTERS_PER_SESSION = 1   # chapters absorbed per think cycle

_STOP = {"the","and","for","she","her","was","are","with","that","this","have",
         "from","just","been","like","what","when","felt","then","they","were",
         "said","him","his","had","but","not","all","one","our","out","can","its"}


# ── id helpers ────────────────────────────────────────────────────────────────

def _bid() -> str:
    return "bk-" + hashlib.sha1(str(time.time()).encode()).hexdigest()[:8]

def _chid(book_id: str, idx: int) -> str:
    return f"bkch-{hashlib.sha1(f'{book_id}{idx}'.encode()).hexdigest()[:8]}"


# ── PDF extraction & chunking ─────────────────────────────────────────────────

def _extract_text(pdf_bytes: bytes) -> str:
    """Extract all text from PDF bytes using pypdf."""
    import io
    import pypdf
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    pages = []
    for page in reader.pages:
        t = page.extract_text() or ""
        pages.append(t)
    return "\n".join(pages)


def _chunk_text(text: str, chunk_tokens: int = CHUNK_TOKENS) -> list[str]:
    """Split text into roughly equal chunks by word count (≈ tokens*0.75)."""
    words_per_chunk = int(chunk_tokens * 0.75)
    # try to split on paragraph/chapter boundaries first
    paras = [p.strip() for p in re.split(r'\n{2,}', text) if p.strip()]
    chunks, current, current_len = [], [], 0
    for para in paras:
        wc = len(para.split())
        if current_len + wc > words_per_chunk and current:
            chunks.append(" ".join(current))
            current, current_len = [], 0
        current.append(para)
        current_len += wc
    if current:
        chunks.append(" ".join(current))
    # if only one giant chunk, split by words directly
    if len(chunks) == 1 and current_len > words_per_chunk * 1.5:
        words = text.split()
        chunks = [" ".join(words[i:i+words_per_chunk])
                  for i in range(0, len(words), words_per_chunk)]
    return chunks or [text[:4000]]


# ── LLM impression synthesis ──────────────────────────────────────────────────

async def _summarise_chunk(text: str, backend, book_title: str, chapter_idx: int) -> list[str]:
    """Ask the LLM to extract impressions a reader would actually remember."""
    prompt = (
        f"This is a passage from the book '{book_title}' (chapter {chapter_idx + 1}).\n\n"
        f"{text[:3000]}\n\n"
        f"Write exactly {IMPRESSIONS_N} short sentences — things a reader would genuinely remember "
        f"after putting the book down: a striking idea, a character observation, an emotional moment, "
        f"a surprising fact, a turn of phrase that stuck. Each sentence stands alone. "
        f"No summaries, no spoilers, no 'the book says'. Write as if recalling from memory. "
        f"Return a JSON array of {IMPRESSIONS_N} strings."
    )
    try:
        result = await backend.complete(
            messages=[
                {"role": "system", "content": "You extract vivid, memorable impressions from book passages. Return only valid JSON."},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=300,
            params={"response_format": {"type": "json_object"}},
        )
        raw = json.loads(result.content)
        # handle {"impressions": [...]} or bare list
        if isinstance(raw, list):
            items = raw
        elif isinstance(raw, dict):
            items = next((v for v in raw.values() if isinstance(v, list)), [])
        else:
            items = []
        impressions = [str(x).strip() for x in items if str(x).strip()][:IMPRESSIONS_N]
        return impressions or [text[:120].strip() + "…"]
    except Exception:
        # fallback: first sentence of chunk
        first = re.split(r'[.!?]', text)[0].strip()
        return [first[:120] + "…"] if first else []


# ── ingest ────────────────────────────────────────────────────────────────────

async def ingest_pdf(char_id: str, pdf_bytes: bytes, title: str, author: str,
                     synopsis: str, series_name: str, series_order: int,
                     backend) -> dict:
    """Extract, chunk, summarise and store a book. Returns the book row."""
    text = _extract_text(pdf_bytes)
    if not text.strip():
        raise ValueError("PDF appears to be empty or image-only (no extractable text)")

    chunks = _chunk_text(text)
    bid    = _bid()
    now    = time.time()

    db.ex(
        "INSERT INTO char_books(id,char_id,title,author,synopsis,series_name,series_order,"
        "status,current_chapter,total_chapters,added_at) VALUES(?,?,?,?,?,?,?,?,0,?,?)",
        (bid, char_id, title.strip(), author.strip(), synopsis.strip(),
         series_name.strip(), int(series_order), "wishlist", len(chunks), now),
    )

    # process each chunk sequentially (gateway is one-at-a-time)
    for idx, chunk in enumerate(chunks):
        impressions = await _summarise_chunk(chunk, backend, title, idx)
        chid = _chid(bid, idx)
        db.ex(
            "INSERT OR REPLACE INTO char_book_chapters(id,book_id,chapter_index,impressions_json,processed_at)"
            " VALUES(?,?,?,?,?)",
            (chid, bid, idx, db.jdump(impressions), time.time()),
        )

    return get_book(bid)


# ── CRUD ──────────────────────────────────────────────────────────────────────

def get_book(book_id: str) -> dict:
    r = db.one("SELECT * FROM char_books WHERE id=?", (book_id,))
    if not r:
        raise KeyError(f"book not found: {book_id}")
    return dict(r)


def list_books(char_id: str, status: str | None = None) -> list[dict]:
    if status:
        rows = db.q("SELECT * FROM char_books WHERE char_id=? AND status=? ORDER BY series_name,series_order,added_at", (char_id, status))
    else:
        rows = db.q("SELECT * FROM char_books WHERE char_id=? ORDER BY series_name,series_order,added_at", (char_id,))
    return [dict(r) for r in rows]


def set_status(book_id: str, status: str, skip_reason: str = "") -> dict:
    """Update book status. 'ignored' stays ignored; 'skipped' resurfaces after 14 days."""
    allowed = {"wishlist", "reading", "finished", "skipped", "ignored"}
    if status not in allowed:
        raise ValueError(f"status must be one of {allowed}")
    now = time.time()
    updates: dict = {"status": status}
    if status == "reading":
        updates["started_at"] = now
    if status == "finished":
        updates["finished_at"] = now
    if status == "skipped":
        updates["skip_reason"] = skip_reason
        updates["resurfaced_at"] = now + RESURFACE_DAYS * 86400
    sets = ", ".join(f"{k}=?" for k in updates)
    db.ex(f"UPDATE char_books SET {sets} WHERE id=?", (*updates.values(), book_id))
    return get_book(book_id)


def chapters(book_id: str) -> list[dict]:
    rows = db.q(
        "SELECT * FROM char_book_chapters WHERE book_id=? ORDER BY chapter_index",
        (book_id,),
    )
    return [{**dict(r), "impressions": db.jload(r["impressions_json"], [])} for r in rows]


def delete_book(char_id: str, book_id: str) -> None:
    db.ex("DELETE FROM char_book_chapters WHERE book_id=?", (book_id,))
    db.ex("DELETE FROM char_books WHERE id=? AND char_id=?", (book_id, char_id))


# ── pick next book ────────────────────────────────────────────────────────────

async def pick_next_book(char: dict, backend) -> dict | None:
    """LLM picks the most aligned book from the wishlist. Returns book row or None."""
    from . import profile as profile_mod, interests as interests_mod
    prof = profile_mod.get(char)
    now  = time.time()

    # eligible: wishlist books + skipped ones whose resurfaced_at has passed
    candidates = [
        b for b in list_books(char["id"])
        if b["status"] == "wishlist"
        or (b["status"] == "skipped" and b.get("resurfaced_at", 0) <= now)
    ]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    interests_line = interests_mod.inject_line(prof)
    curiosity_names = [c["name"] for c in (prof.get("curiosities") or []) if c.get("spark",0) > 1]
    curiosity_line = ("Curious about: " + ", ".join(curiosity_names)) if curiosity_names else ""

    book_list = "\n".join(
        f"{i+1}. '{b['title']}' by {b['author'] or 'unknown'}"
        + (f" (series: {b['series_name']} #{b['series_order']})" if b.get("series_name") else "")
        + (f" — {b['synopsis'][:80]}" if b.get("synopsis") else "")
        for i, b in enumerate(candidates[:PICK_MAX_BOOKS])
    )

    prompt = (
        f"{interests_line}\n{curiosity_line}\n\n"
        f"Books available to read:\n{book_list}\n\n"
        f"Which book number best fits this person's current interests and curiosities? "
        f"Return JSON: {{\"choice\": <number 1-{min(len(candidates),PICK_MAX_BOOKS)}>, \"reason\": \"one sentence\"}}"
    )
    try:
        result = await backend.complete(
            messages=[
                {"role": "system", "content": "You match a reader to their next book. Return only valid JSON."},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=80,
            params={"response_format": {"type": "json_object"}},
        )
        raw   = json.loads(result.content)
        idx   = int(raw.get("choice", 1)) - 1
        book  = candidates[max(0, min(idx, len(candidates)-1))]
        return book
    except Exception:
        return candidates[0]  # fallback: first candidate


# ── read session ──────────────────────────────────────────────────────────────

async def read_session(char: dict, backend) -> dict | None:
    """Absorb the next chapter of the character's current book. Returns summary or None."""
    from . import memory as memory_mod, interests as interests_mod, profile as profile_mod
    from . import store

    # find current book; pick one if none
    reading = [b for b in list_books(char["id"]) if b["status"] == "reading"]
    book = reading[0] if reading else None

    if not book:
        book = await pick_next_book(char, backend)
        if not book:
            return None
        book = set_status(book["id"], "reading")

    chapter_idx = book["current_chapter"]
    if chapter_idx >= book["total_chapters"]:
        # book finished
        set_status(book["id"], "finished")
        fresh = store.get(char["id"])
        memory_mod.add_manual(
            char["id"],
            f"Finished reading '{book['title']}'" + (f" by {book['author']}" if book.get("author") else ""),
            tags=[w.lower() for w in book["title"].split() if len(w) > 3][:6],
            category="achievement",
        )
        return {"finished": True, "book": book["title"]}

    # get pre-computed impressions for this chapter
    chap_rows = db.q(
        "SELECT impressions_json FROM char_book_chapters WHERE book_id=? AND chapter_index=?",
        (book["id"], chapter_idx),
    )
    if not chap_rows:
        # chapter not processed yet — skip to next
        db.ex("UPDATE char_books SET current_chapter=current_chapter+1 WHERE id=?", (book["id"],))
        return None

    impressions = db.jload(chap_rows[0]["impressions_json"], [])
    source      = f"book:{book['id']}"
    now         = time.time()

    formed = []
    for imp in impressions:
        if not imp.strip():
            continue
        tags = [w.lower() for w in re.findall(r"[a-zA-Z]+", imp) if len(w) > 3 and w.lower() not in _STOP][:8]
        memory_mod.form(char["id"], {"activity": imp, "space": "", "mood": "", "thought": imp},
                        category="learning", source=source)
        formed.append(imp)

    # bump interests and curiosities whose keywords match the impressions
    all_text = " ".join(impressions)
    fresh2 = store.get(char["id"])
    interests_mod.bump(fresh2, all_text)
    interests_mod.curiosity_bump_from_activity(fresh2, all_text)

    # spawn new curiosity if something in impressions isn't covered yet
    _maybe_spawn_curiosity(fresh2, all_text, book["title"], backend)

    store.save(fresh2)

    # advance chapter pointer
    db.ex("UPDATE char_books SET current_chapter=current_chapter+1 WHERE id=?", (book["id"],))

    return {
        "book":        book["title"],
        "chapter":     chapter_idx + 1,
        "total":       book["total_chapters"],
        "impressions": formed,
    }


def _maybe_spawn_curiosity(char: dict, text: str, book_title: str, backend) -> None:
    """Heuristic: pick the most distinctive noun from the impressions and add as curiosity if new."""
    from . import interests as interests_mod, profile as profile_mod
    prof       = profile_mod.get(char)
    known_kw   = {w.lower() for v in (prof.get("interests") or {}).values()
                  for w in (v.get("text","") if isinstance(v,dict) else str(v)).split()}
    known_kw  |= {c["name"].lower() for c in (prof.get("curiosities") or [])}
    # count non-stopword tokens in text
    words = [w.lower() for w in re.findall(r"[a-zA-Z]{4,}", text) if w.lower() not in _STOP]
    freq: dict = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    novel = [(w, c) for w, c in freq.items() if w not in known_kw and c >= 2]
    if not novel:
        return
    top_word = sorted(novel, key=lambda x: -x[1])[0][0]
    interests_mod.curiosity_encounter(char, top_word.capitalize(), "reading")
