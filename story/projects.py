"""Project (source) lifecycle: import, metadata, structure edits, listing. The original file is never modified."""
import hashlib
import os
import shutil
import stat
import uuid
from pathlib import Path

import config
from . import db, ingest, settings as settings_mod, storytypes
from .tokens import estimate


class ProjectError(Exception):
    pass


def sources_dir() -> Path:
    d = config.DATA_DIR / "sources"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_original(pid: str, name: str, data: bytes) -> tuple[Path, str]:
    d = sources_dir() / pid
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_bytes(data)
    os.chmod(p, stat.S_IREAD)                      # immutable by convention: extracted data lives in the DB
    return p, hashlib.sha256(data).hexdigest()


def _store(pid: str, ex: ingest.Extracted, *, title: str, author: str, fmt: str, url: str,
           orig: Path | None, sha: str, extra_warnings: list[str] | None = None) -> None:
    s = settings_mod.get()
    cpt = s["chars_per_token"]
    if not ex.paras:
        raise ProjectError("No text could be extracted from this source. "
                           + (" ".join(ex.warnings) if ex.warnings else ""))
    chap_of = [1] * len(ex.paras)
    for k, ch in enumerate(ex.chapters, 1):
        for i in range(ch.start, ch.end + 1):
            chap_of[i] = k
    est_total = 0
    with db.tx() as c:
        for i, p in enumerate(ex.paras):
            tok = estimate(p.text, cpt)
            est_total += tok
            c.execute("INSERT INTO paras(project_id,idx,page,section,chapter_idx,kind,text,orig_text,tokens) "
                      "VALUES(?,?,?,?,?,?,?,?,?)",
                      (pid, i + 1, p.page, p.section, chap_of[i], p.kind, p.text, p.text, tok))
        skips = [ingest.is_skippable_title(ch.title) for ch in ex.chapters]
        if all(skips):
            skips = [False] * len(skips)                   # never skip the whole source
        for k, ch in enumerate(ex.chapters, 1):
            c.execute("INSERT INTO chapters(project_id,idx,title,start_para,end_para,page_start,page_end,source,skip) "
                      "VALUES(?,?,?,?,?,?,?,?,?)",
                      (pid, k, ch.title, ch.start + 1, ch.end + 1, ch.page_start, ch.page_end, ch.source, int(skips[k - 1])))
        c.execute(
            "INSERT INTO projects(id,title,author,format,source_url,created_at,updated_at,status,orig_path,sha256,"
            "page_count,est_tokens,char_count,warnings,meta) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, title or ex.title or "Untitled", author or ex.author, fmt, url, db.now(), db.now(), "imported",
             str(orig) if orig else "", sha, ex.page_count, est_total, sum(len(p.text) for p in ex.paras),
             db.jdump(ex.warnings + (extra_warnings or [])), db.jdump(ex.meta)))


def _add_figures(pid: str, orig: Path, ex: ingest.Extracted) -> None:
    from . import figures
    try:
        recs = figures.extract(orig, pid, ex.paras)
    except Exception as e:  # noqa: BLE001 - figures are an extra; never fail the import over them
        db.ex("UPDATE projects SET warnings=? WHERE id=?", (db.jdump(ex.warnings + [f"Figures could not be extracted: {e}"]), pid))
        return
    if recs:
        rights = sum(r["rights"] for r in recs)
        ex.meta["figures"] = {"pages": len(recs), "with_rights_notice": rights}
        db.ex("UPDATE projects SET meta=? WHERE id=?", (db.jdump(ex.meta), pid))


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def import_file(filename: str, data: bytes, title: str = "", author: str = "") -> str:
    """Sync (CPU-bound for big PDFs): call via asyncio.to_thread."""
    pid = new_id()
    ext = Path(filename).suffix.lower()
    stem = Path(filename).stem
    if ext not in (".pdf", ".txt", ".md", ".html", ".htm"):
        raise ProjectError("Supported files: PDF, TXT, MD, HTML.")
    orig, sha = _save_original(pid, "original" + ext, data)
    try:
        s = settings_mod.get()
        if ext == ".pdf":
            if not data.startswith(b"%PDF"):
                raise ProjectError("This file is not a valid PDF.")
            ex = ingest.extract_pdf(orig, title_hint=stem, ocr=s["ocr"])
        elif ext in (".html", ".htm"):
            ex = ingest.extract_html(ingest.decode_bytes(data, ingest.charset_from("", data)), title_hint=stem)
        else:
            ex = ingest.extract_text(ingest.decode_bytes(data), title=title or stem)
        _store(pid, ex, title=title or ex.title or stem, author=author, fmt=ex.fmt, url="", orig=orig, sha=sha)
        if ext == ".pdf":
            _add_figures(pid, orig, ex)
    except Exception as e:
        shutil.rmtree(sources_dir() / pid, onerror=_rm_ro)
        if isinstance(e, (ProjectError, ingest.IngestError)):
            raise ProjectError(str(e)) from e
        raise
    return pid


def import_text(text: str, title: str = "", author: str = "") -> str:
    if len(text.strip()) < 200:
        raise ProjectError("Pasted text is too short to analyse (under 200 characters).")
    pid = new_id()
    orig, sha = _save_original(pid, "original.txt", text.encode("utf-8"))
    try:
        ex = ingest.extract_text(text, title=title)
        _store(pid, ex, title=title or ex.title or "Pasted text", author=author, fmt="text", url="", orig=orig, sha=sha)
    except Exception:
        shutil.rmtree(sources_dir() / pid, onerror=_rm_ro)
        raise
    return pid


async def import_url(url: str, title: str = "", author: str = "") -> str:
    import asyncio
    try:
        raw, ctype, final = await ingest.fetch_url(url)
    except ingest.IngestError as e:
        raise ProjectError(str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise ProjectError(f"could not fetch the URL: {type(e).__name__}: {e}") from e
    is_pdf = raw[:5] == b"%PDF-" or "pdf" in ctype.lower()
    if is_pdf:
        pid = await asyncio.to_thread(import_file, "download.pdf", raw, title, author)
        db.ex("UPDATE projects SET source_url=? WHERE id=?", (final, pid))
        return pid
    pid = new_id()
    orig, sha = _save_original(pid, "original.html", raw)
    try:
        html_text = ingest.decode_bytes(raw, ingest.charset_from(ctype, raw))
        ex = await asyncio.to_thread(ingest.extract_html, html_text, final, "")
        _store(pid, ex, title=title or ex.title, author=author, fmt="article", url=final, orig=orig, sha=sha,
               extra_warnings=["The site blocked the plain download, so the page was opened in a browser and read from there. Check the text is the whole article."] if "via=browser" in ctype else None)
    except Exception as e:
        shutil.rmtree(sources_dir() / pid, onerror=_rm_ro)
        if isinstance(e, ingest.IngestError):
            raise ProjectError(str(e)) from e
        raise
    return pid


def _rm_ro(func, path, _exc):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def delete(pid: str) -> None:
    with db.tx() as c:
        c.execute("DELETE FROM candidate_refs WHERE candidate_id IN (SELECT id FROM candidates WHERE project_id=?)", (pid,))
        for t in ("candidates", "tasks", "paras", "chapters", "runs", "figures"):
            c.execute(f"DELETE FROM {t} WHERE project_id=?", (pid,))
        c.execute("DELETE FROM projects WHERE id=?", (pid,))
    shutil.rmtree(sources_dir() / pid, onerror=_rm_ro)


# ── read side ───────────────────────────────────────────────────────────────

_LIST_SQL = """
SELECT p.*,
  (SELECT COUNT(*) FROM chapters ch WHERE ch.project_id=p.id) AS chapter_count,
  (SELECT COUNT(*) FROM candidates c WHERE c.project_id=p.id AND c.status!='superseded') AS cand_total,
  (SELECT COUNT(*) FROM candidates c WHERE c.project_id=p.id AND c.status='approved') AS cand_approved,
  (SELECT COUNT(*) FROM candidates c WHERE c.project_id=p.id AND c.status='rejected') AS cand_rejected,
  (SELECT COUNT(*) FROM candidates c WHERE c.project_id=p.id AND c.status='pending') AS cand_pending
FROM projects p"""

_SORTS = {"created": "p.created_at", "title": "LOWER(p.title)", "status": "p.status", "tokens": "p.est_tokens",
          "candidates": "cand_total", "updated": "p.updated_at"}


def _shape(r: dict) -> dict:
    r["warnings"] = db.jload(r.get("warnings"), [])
    r["meta"] = db.jload(r.get("meta"), {})
    r["story_type"] = storytypes.of_project(r)
    r.pop("orig_path", None)
    return r


def list_projects(q: str = "", status: str = "", fmt: str = "", sort: str = "created", desc: bool = True) -> list[dict]:
    where, args = [], []
    if q:
        where.append("(p.title LIKE ? OR p.author LIKE ? OR p.source_url LIKE ?)")
        args += [f"%{q}%"] * 3
    if status:
        where.append("p.status=?")
        args.append(status)
    if fmt:
        where.append("p.format=?")
        args.append(fmt)
    sql = _LIST_SQL + (" WHERE " + " AND ".join(where) if where else "")
    sql += f" ORDER BY {_SORTS.get(sort, 'p.created_at')} {'DESC' if desc else 'ASC'}"
    return [_shape(r) for r in db.q(sql, args)]


def get(pid: str) -> dict:
    r = db.one(_LIST_SQL + " WHERE p.id=?", (pid,))
    if not r:
        raise ProjectError("project not found")
    return _shape(r)


def original_path(pid: str) -> Path:
    r = db.one("SELECT orig_path FROM projects WHERE id=?", (pid,))
    if not r or not r["orig_path"] or not Path(r["orig_path"]).exists():
        raise ProjectError("original file not found")
    return Path(r["orig_path"])


def set_story_type(pid: str, story_type: str) -> dict:
    """Choose what the source becomes (see `story/storytypes.py`). Stored in the project's meta; plans made later copy it."""
    if not storytypes.valid(story_type):
        raise ProjectError(f"unknown story type '{story_type}'")
    r = get(pid)
    meta = {**(r.get("meta") or {}), "story_type": story_type}
    db.ex("UPDATE projects SET meta=?, updated_at=? WHERE id=?", (db.jdump(meta), db.now(), pid))
    return get(pid)


def update_meta(pid: str, title: str | None = None, author: str | None = None) -> dict:
    get(pid)
    if title is not None:
        db.ex("UPDATE projects SET title=?, updated_at=? WHERE id=?", (title.strip() or "Untitled", db.now(), pid))
    if author is not None:
        db.ex("UPDATE projects SET author=?, updated_at=? WHERE id=?", (author.strip(), db.now(), pid))
    return get(pid)


def get_paras(pid: str, offset: int = 0, limit: int = 200, chapter: int | None = None, q: str = "") -> dict:
    where, args = ["project_id=?"], [pid]
    if chapter:
        where.append("chapter_idx=?")
        args.append(chapter)
    if q:
        where.append("text LIKE ?")
        args.append(f"%{q}%")
    w = " AND ".join(where)
    total = db.one(f"SELECT COUNT(*) n FROM paras WHERE {w}", args)["n"]
    rows = db.q(f"SELECT idx,page,section,chapter_idx,kind,text,edited,tokens FROM paras WHERE {w} "
                f"ORDER BY idx LIMIT ? OFFSET ?", args + [limit, offset])
    return {"total": total, "paras": rows}


def get_chapters(pid: str) -> list[dict]:
    return db.q("SELECT c.idx,c.title,c.start_para,c.end_para,c.page_start,c.page_end,c.source,c.skip,"
                "(SELECT COALESCE(SUM(tokens),0) FROM paras p WHERE p.project_id=c.project_id AND p.idx BETWEEN c.start_para AND c.end_para) AS tokens "
                "FROM chapters c WHERE c.project_id=? ORDER BY c.idx", (pid,))


def edit_para(pid: str, idx: int, text: str) -> dict:
    """Manual correction of extracted text. The original extraction is kept in orig_text."""
    text = text.strip()
    if not text:
        raise ProjectError("paragraph text cannot be empty")
    row = db.one("SELECT idx FROM paras WHERE project_id=? AND idx=?", (pid, idx))
    if not row:
        raise ProjectError("paragraph not found")
    tok = estimate(text, settings_mod.get()["chars_per_token"])
    db.ex("UPDATE paras SET text=?, edited=1, tokens=? WHERE project_id=? AND idx=?", (text, tok, pid, idx))
    _refresh_totals(pid)
    return {"idx": idx, "note": "Saved. Re-run processing from the 'analyze' stage for the change to affect results."}


def set_chapters(pid: str, chapters: list[dict]) -> list[dict]:
    """Replace chapter boundaries. chapters: [{title, start_para, skip?}]; skipped chapters are not analysed."""
    if not chapters:
        raise ProjectError("at least one chapter is required")
    n = db.one("SELECT COUNT(*) n FROM paras WHERE project_id=?", (pid,))["n"]
    if all(c.get("skip") for c in chapters):
        raise ProjectError("at least one chapter must be left in")
    chapters = sorted(chapters, key=lambda c: int(c["start_para"]))
    if int(chapters[0]["start_para"]) != 1:
        raise ProjectError("the first chapter must start at paragraph 1")
    starts = [int(c["start_para"]) for c in chapters]
    if len(set(starts)) != len(starts) or starts[-1] > n:
        raise ProjectError("chapter start paragraphs must be unique and within the source")
    with db.tx() as c:
        c.execute("DELETE FROM chapters WHERE project_id=?", (pid,))
        for k, ch in enumerate(chapters, 1):
            end = starts[k] - 1 if k < len(starts) else n
            pg = c.execute("SELECT MIN(page) a, MAX(page) b FROM paras WHERE project_id=? AND idx BETWEEN ? AND ?",
                           (pid, starts[k - 1], end)).fetchone()
            c.execute("INSERT INTO chapters(project_id,idx,title,start_para,end_para,page_start,page_end,source,skip) "
                      "VALUES(?,?,?,?,?,?,?,'manual',?)",
                      (pid, k, str(ch.get("title") or f"Chapter {k}")[:200], starts[k - 1], end, pg["a"], pg["b"],
                       int(bool(ch.get("skip")))))
            c.execute("UPDATE paras SET chapter_idx=? WHERE project_id=? AND idx BETWEEN ? AND ?",
                      (k, pid, starts[k - 1], end))
    return get_chapters(pid)


def _refresh_totals(pid: str) -> None:
    r = db.one("SELECT COALESCE(SUM(tokens),0) t, COALESCE(SUM(LENGTH(text)),0) c FROM paras WHERE project_id=?", (pid,))
    db.ex("UPDATE projects SET est_tokens=?, char_count=?, updated_at=? WHERE id=?", (r["t"], r["c"], db.now(), pid))


# ── processing scope: whole source, chosen chapters, or a page / paragraph range ────────────────

def get_scope(pid: str) -> dict:
    r = db.one("SELECT meta FROM projects WHERE id=?", (pid,))
    if not r:
        raise ProjectError("project not found")
    return (db.jload(r["meta"], {}) or {}).get("scope") or {"mode": "all"}


def resolve_scope(pid: str) -> set[int]:
    """Paragraph numbers that processing will cover. 'all' leaves out chapters marked as skipped; an explicit
    chapter, page or paragraph selection is taken literally."""
    sc = get_scope(pid)
    rows = db.q("SELECT p.idx, p.page, p.chapter_idx, COALESCE(c.skip,0) AS skip FROM paras p "
                "LEFT JOIN chapters c ON c.project_id=p.project_id AND c.idx=p.chapter_idx WHERE p.project_id=?", (pid,))
    mode = sc.get("mode", "all")
    if mode == "chapters":
        want = {int(x) for x in sc.get("chapters", [])}
        return {r["idx"] for r in rows if r["chapter_idx"] in want}
    if mode == "pages":
        a, b = int(sc["page_from"]), int(sc["page_to"])
        return {r["idx"] for r in rows if r["page"] is not None and a <= r["page"] <= b}
    if mode == "paras":
        a, b = int(sc["para_from"]), int(sc["para_to"])
        return {r["idx"] for r in rows if a <= r["idx"] <= b}
    return {r["idx"] for r in rows if not r["skip"]}


def scope_preview(pid: str, chunk_tokens: int | None = None) -> dict:
    ids = resolve_scope(pid)
    s = settings_mod.get()
    rows = db.q("SELECT idx, page, chapter_idx, tokens FROM paras WHERE project_id=?", (pid,))
    sel = [r for r in rows if r["idx"] in ids]
    tokens = sum(r["tokens"] for r in sel)
    target = chunk_tokens or s["chunk_tokens"]
    pages = sorted({r["page"] for r in sel if r["page"] is not None})
    return {"scope": get_scope(pid), "paragraphs": len(sel), "tokens": tokens,
            "chunks": max(1, -(-tokens // max(1, target))) if sel else 0,
            "chapters": sorted({r["chapter_idx"] for r in sel}),
            "page_min": pages[0] if pages else None, "page_max": pages[-1] if pages else None}


def set_scope(pid: str, scope: dict) -> dict:
    """scope: {mode: all} | {mode: chapters, chapters: [idx...]} | {mode: pages, page_from, page_to} |
    {mode: paras, para_from, para_to}. Returns the preview of what will be processed."""
    get(pid)
    mode = scope.get("mode", "all")
    clean: dict = {"mode": mode}
    try:
        if mode == "chapters":
            have = {c["idx"] for c in get_chapters(pid)}
            ch = sorted({int(x) for x in scope.get("chapters", [])})
            if not ch or not set(ch) <= have:
                raise ProjectError("choose at least one existing chapter")
            clean["chapters"] = ch
        elif mode == "pages":
            a, b = int(scope["page_from"]), int(scope["page_to"])
            if a < 1 or b < a:
                raise ProjectError("page range must be from a page to a later or equal page")
            clean.update(page_from=a, page_to=b)
        elif mode == "paras":
            a, b = int(scope["para_from"]), int(scope["para_to"])
            if a < 1 or b < a:
                raise ProjectError("paragraph range must be from a number to a later or equal number")
            clean.update(para_from=a, para_to=b)
        elif mode != "all":
            raise ProjectError("scope mode must be all, chapters, pages or paras")
    except (KeyError, TypeError, ValueError) as e:
        raise ProjectError("incomplete or invalid scope") from e
    meta = (db.jload(db.one("SELECT meta FROM projects WHERE id=?", (pid,))["meta"], {}) or {})
    previous = meta.get("scope") or {"mode": "all"}
    meta["scope"] = clean
    db.ex("UPDATE projects SET meta=?, updated_at=? WHERE id=?", (db.jdump(meta), db.now(), pid))
    prev = scope_preview(pid)
    if not prev["paragraphs"]:
        meta["scope"] = previous                                         # roll back: nothing would be processed
        db.ex("UPDATE projects SET meta=? WHERE id=?", (db.jdump(meta), pid))
        raise ProjectError("that selection contains no text" + (" (this source has no page numbers; use paragraphs)"
                           if mode == "pages" and not db.one("SELECT 1 x FROM paras WHERE project_id=? AND page IS NOT NULL", (pid,)) else ""))
    return prev
