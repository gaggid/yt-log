"""Source extraction: PDF / HTML / text into numbered paragraphs that keep their page or section, plus
detected chapters and extraction-quality warnings. Pure functions; storage lives in projects.py."""
import html as _html
import ipaddress
import re
import socket
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import httpx
from . import textfix

MAX_PARA_CHARS = 1500
MAX_DOWNLOAD = 25 * 1024 * 1024


@dataclass
class ParaIn:
    text: str
    page: int | None = None
    section: str = ""
    kind: str = "p"          # p | h


@dataclass
class ChapterIn:
    title: str
    start: int               # index into paras (0-based)
    end: int                 # inclusive
    source: str = "auto"     # outline | heading | auto | section | single
    page_start: int | None = None
    page_end: int | None = None


@dataclass
class Extracted:
    title: str = ""
    author: str = ""
    fmt: str = "text"
    page_count: int | None = None
    paras: list[ParaIn] = field(default_factory=list)
    chapters: list[ChapterIn] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


class IngestError(Exception):
    pass


# ── paragraph building ──────────────────────────────────────────────────────

_SENT_SPLIT = re.compile(r"(?<=[.!?…])[\"')\]”’]*\s+(?=[A-Z0-9\"“‘(])")
_END_PUNCT = tuple('.!?:"”’…)')


def _split_long(text: str, limit: int = MAX_PARA_CHARS) -> list[str]:
    if len(text) <= limit:
        return [text]
    out, cur = [], ""
    for s in _SENT_SPLIT.split(text):
        if cur and len(cur) + len(s) + 1 > limit:
            out.append(cur)
            cur = ""
        while len(s) > limit * 1.5:                     # pathological run-on: break at whitespace
            cut = s.rfind(" ", 0, limit) or limit
            out.append((cur + " " + s[:cut]).strip() if cur else s[:cut])
            cur, s = "", s[cut:].lstrip()
        cur = (cur + " " + s).strip() if cur else s
    if cur:
        out.append(cur)
    return out


def paras_from_text(text: str, vocab: "textfix.Vocab | None" = None) -> list[str]:
    """Reflow raw extracted text into paragraphs: blank lines split; failing that, short sentence-ending
    lines mark paragraph ends (PDF text often has only single newlines)."""
    text = text.replace("\x00", "").replace("\r", "")
    text = (vocab or textfix.Vocab([text])).fix_breaks(text)
    blocks = [b for b in re.split(r"\n\s*\n", text) if b.strip()]
    spaced = []
    for b in blocks:                                    # a heading line on top of body lines is its own paragraph
        lines = [l for l in b.split("\n") if l.strip()]
        if len(lines) > 1 and is_heading(lines[0]):
            spaced += [lines[0], "\n".join(lines[1:])]
        else:
            spaced.append(b)
    blocks = spaced
    if len(blocks) == 1 and blocks[0].count("\n") >= 3:
        lines = [l.strip() for l in blocks[0].split("\n") if l.strip()]
        widest = max(len(l) for l in lines)
        blocks, cur = [], []
        for l in lines:
            if is_heading(l):
                if cur:
                    blocks.append("\n".join(cur))
                blocks.append(l)
                cur = []
                continue
            if cur and cur[-1].endswith(_END_PUNCT) and len(cur[-1]) < 0.7 * widest:
                blocks.append("\n".join(cur))
                cur = []
            cur.append(l)
        if cur:
            blocks.append("\n".join(cur))
    out: list[str] = []
    for b in blocks:
        t = re.sub(r"\s+", " ", b).strip()
        if t:
            out.extend(_split_long(vocab.fix_split_letters(t) if vocab else t))
    return out


# ── chapter heading heuristics ──────────────────────────────────────────────

_NUMWORDS = r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty"
HEAD_RE = re.compile(
    rf"^(?:(?:chapter|part|book|section)\s+(?:\d+|[ivxlcdm]+|{_NUMWORDS})\b.{{0,80}}"
    r"|(?:prologue|epilogue|introduction|preface|foreword|afterword|conclusion|appendix(?:\s+\w+)?|acknowledg(?:e)?ments|(?:table of )?contents|glossary|bibliography|index|about the authors?)\s*)$",
    re.IGNORECASE)


_HEAD_NUM = re.compile(rf"^(?:chapter|part|book|section)\s+(?:\d+|[ivxlcdm]+|{_NUMWORDS})(?=\W|$)(.*)$", re.IGNORECASE)


SKIP_TITLE_RE = re.compile(
    r"^(?:(?:table of )?contents?|index|glossary(?: of .*)?|bibliography|references|further reading|acknowledg(?:e)?ments?|"
    r"about the authors?|copyright(?: page)?|dedication|front matter|title page|also by .*|notes|endnotes|credits|permissions|"
    r"list of (?:figures|tables|illustrations)|half title|colophon)$", re.IGNORECASE)


def is_skippable_title(title: str) -> bool:
    """Front/back matter that holds no stories (contents, index, glossary, bibliography, ...)."""
    return bool(SKIP_TITLE_RE.match(re.sub(r"[\s.:\-]+$", "", title.strip())))


def is_heading(text: str) -> bool:
    t = text.strip()
    if len(t) > 100 or not HEAD_RE.match(t):
        return False
    m = _HEAD_NUM.match(t)
    rest = m.group(1) if m else ""
    return not re.search(r"\.{3,}|\s\d{1,4}$", rest)           # "Chapter 1 .... 7" is a table-of-contents line


def heading_starts(paras: list[ParaIn]) -> list[tuple[int, str]]:
    """(para index, title) for paragraphs that look like chapter headings. Pages with 3+ matches are a
    table of contents and ignored."""
    hits = [(i, p.text.strip()) for i, p in enumerate(paras) if is_heading(p.text)]
    per_page: dict = {}
    for i, _ in hits:
        per_page[paras[i].page] = per_page.get(paras[i].page, 0) + 1
    hits = [(i, t) for i, t in hits if paras[i].page is None or per_page[paras[i].page] < 3]
    # "Chapter 3" followed by a short title paragraph: fold the subtitle in
    out = []
    for i, t in hits:
        if i + 1 < len(paras) and len(paras[i + 1].text) < 80 and not paras[i + 1].text.endswith((".", "?", "!")) \
                and not is_heading(paras[i + 1].text) and re.match(r"(?i)^(chapter|part|book|section)\b", t):
            t = f"{t}: {paras[i + 1].text.strip()}"
        out.append((i, t))
    return out


def build_chapters(paras: list[ParaIn], starts: list[tuple[int, str]], source: str,
                   front_title: str = "Front matter") -> list[ChapterIn]:
    if not paras:
        return []
    starts = sorted({i: t for i, t in reversed(starts)}.items())
    if not starts or starts[0][0] > 0:
        starts.insert(0, (0, front_title))
    chapters = []
    for n, (i, title) in enumerate(starts):
        end = (starts[n + 1][0] - 1) if n + 1 < len(starts) else len(paras) - 1
        if end < i:
            continue
        pages = [p.page for p in paras[i:end + 1] if p.page is not None]
        chapters.append(ChapterIn(title[:200], i, end, source if title != front_title else "auto",
                                  min(pages) if pages else None, max(pages) if pages else None))
    return chapters


def auto_chapters(paras: list[ParaIn], target_chars: int = 24000) -> list[ChapterIn]:
    """No structure found: cut into evenly sized parts so later stages still get units to summarise."""
    out, start, size = [], 0, 0
    for i, p in enumerate(paras):
        size += len(p.text)
        if size >= target_chars or i == len(paras) - 1:
            pages = [q.page for q in paras[start:i + 1] if q.page is not None]
            label = f"Part {len(out) + 1}" + (f" (pp. {min(pages)}–{max(pages)})" if pages else "")
            out.append(ChapterIn(label, start, i, "auto", min(pages) if pages else None, max(pages) if pages else None))
            start, size = i + 1, 0
    return out


# ── PDF ─────────────────────────────────────────────────────────────────────

def _norm_line(l: str) -> str:
    return re.sub(r"\d+", "#", l.strip().lower())


def strip_page_furniture(pages: list[str]) -> list[str]:
    """Remove bare page numbers and running headers/footers repeated on many pages."""
    lines = [p.split("\n") for p in pages]

    def edges(ls: list[str]) -> set[int]:
        ne = [i for i, l in enumerate(ls) if l.strip()]
        return set(ne[:2] + ne[-2:])

    counts: dict[str, int] = {}
    for ls in lines:
        for i in edges(ls):
            k = _norm_line(ls[i])
            counts[k] = counts.get(k, 0) + 1
    need = max(3, int(0.4 * len(pages)))
    out = []
    for ls in lines:
        edge = edges(ls)
        keep = []
        for i, l in enumerate(ls):
            s = l.strip()
            if i in edge and re.fullmatch(r"(?:page\s+)?(?:\d{1,4}|[ivxlc]{1,7})", s, re.IGNORECASE):
                continue
            if s and i in edge and len(pages) >= 4 and counts[_norm_line(l)] >= need:
                continue
            keep.append(l)
        out.append("\n".join(keep))
    return out


def _ocr_page(pdf_path: Path, page_no: int) -> str:
    try:
        import pypdfium2  # type: ignore
        import pytesseract  # type: ignore
    except ImportError as e:
        raise IngestError("OCR needs the optional packages pytesseract and pypdfium2 (and the Tesseract program)") from e
    pdf = pypdfium2.PdfDocument(str(pdf_path))
    img = pdf[page_no - 1].render(scale=2.5).to_pil()
    return pytesseract.image_to_string(img)


def extract_pdf(path: Path, title_hint: str = "", ocr: bool = False) -> Extracted:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try:
                if not reader.decrypt(""):
                    raise IngestError("PDF is password protected; remove the protection first (DRM is not bypassed)")
            except Exception as e:  # noqa: BLE001
                raise IngestError("PDF is password protected; remove the protection first (DRM is not bypassed)") from e
        n = len(reader.pages)
        raw = []
        for p in reader.pages:
            try:
                raw.append(p.extract_text() or "")
            except Exception:  # noqa: BLE001 - one bad page must not sink the book
                raw.append("")
    except PdfReadError as e:
        raise IngestError(f"cannot read PDF: {e}") from e
    ex = Extracted(fmt="pdf", page_count=n)
    info = reader.metadata
    ex.title = ((info.title if info else "") or "").strip() or title_hint
    ex.author = ((info.author if info else "") or "").strip()

    empty = [i + 1 for i, t in enumerate(raw) if len(t.strip()) < 30]
    if ocr and empty:
        done = 0
        for pg in empty:
            try:
                raw[pg - 1] = _ocr_page(path, pg)
                done += 1
            except IngestError as e:
                ex.warnings.append(str(e))
                break
            except Exception as e:  # noqa: BLE001
                ex.warnings.append(f"OCR failed on page {pg}: {e}")
                break
        if done:
            ex.warnings.append(f"OCR was applied to {done} page(s); expect recognition errors.")
        empty = [i + 1 for i, t in enumerate(raw) if len(t.strip()) < 30]
    ex.meta["blank_pages"] = empty
    if empty and len(empty) > max(2, int(0.02 * n)):            # a few blank/divider pages are normal in a book
        share = len(empty) / n
        ex.warnings.append(
            f"{len(empty)} of {n} pages have no extractable text"
            + (" - this looks like a scanned PDF; enable OCR or supply a text version." if share > 0.5 else "."))
    cleaned = strip_page_furniture(raw)
    vocab = textfix.Vocab(cleaned)
    for i, t in enumerate(cleaned):
        for para in paras_from_text(t, vocab):
            ex.paras.append(ParaIn(para, page=i + 1))
    total = sum(len(p.text) for p in ex.paras)
    if ex.paras:
        if total / max(1, n) < 400:
            ex.warnings.append(f"Very little text per page (~{total // n} chars); extraction may be incomplete.")
        bad = sum(1 for c in "".join(p.text for p in ex.paras[:200]) if c == "�")
        if bad > 20:
            ex.warnings.append("Many unreadable characters found; the PDF font encoding may be broken.")

    # chapters: PDF outline first, then heading patterns, then even parts
    starts = _outline_starts(reader, ex.paras)
    if len(starts) >= 2:
        ex.chapters = build_chapters(ex.paras, starts, "outline")
    else:
        hs = heading_starts(ex.paras)
        if len(hs) >= 2:
            ex.chapters = build_chapters(ex.paras, hs, "heading")
        elif ex.paras:
            ex.chapters = auto_chapters(ex.paras)
            ex.warnings.append("No chapters detected; the text was split into even parts. Edit chapters if needed.")
    _mark_headings(ex)
    return ex


def _outline_starts(reader, paras: list[ParaIn]) -> list[tuple[int, str]]:
    def walk(items, depth, max_depth, acc):
        for it in items:
            if isinstance(it, list):
                if depth + 1 < max_depth:
                    walk(it, depth + 1, max_depth, acc)
                continue
            try:
                pg = reader.get_destination_page_number(it) + 1
            except Exception:  # noqa: BLE001
                continue
            acc.append((pg, str(getattr(it, "title", "")).strip() or f"Section (p. {pg})"))

    try:
        outline = reader.outline
    except Exception:  # noqa: BLE001
        return []
    for max_depth in (1, 2):
        acc: list[tuple[int, str]] = []
        walk(outline, 0, max_depth, acc)
        by_page: dict[int, str] = {}
        for pg, t in acc:
            by_page.setdefault(pg, t)
        if len(by_page) >= 2:
            starts = []
            for pg, t in sorted(by_page.items()):
                idx = next((i for i, p in enumerate(paras) if p.page is not None and p.page >= pg), None)
                if idx is not None:
                    starts.append((idx, t))
            return starts
    return []


def _mark_headings(ex: Extracted) -> None:
    for ch in ex.chapters:
        for p in ex.paras[ch.start:ch.end + 1]:
            p.section = ch.title if ex.fmt == "pdf" else p.section
    for p in ex.paras:
        if is_heading(p.text):
            p.kind = "h"


# ── plain text ──────────────────────────────────────────────────────────────

def decode_bytes(raw: bytes, declared: str | None = None) -> str:
    for enc in ([declared] if declared else []) + ["utf-8-sig", "cp1252"]:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


def extract_text(text: str, title: str = "", fmt: str = "text") -> Extracted:
    ex = Extracted(title=title, fmt=fmt)
    text = text.replace("\r", "")
    blocks = [b for b in re.split(r"\n\s*\n", text) if b.strip()]
    for b in blocks:
        s = b.strip()
        if s.startswith("#") and "\n" not in s and len(s) < 150:
            ex.paras.append(ParaIn(s.lstrip("#").strip(), kind="h", section=s.lstrip("#").strip()))
            continue
        for t in paras_from_text(b):
            ex.paras.append(ParaIn(t))
    if not ex.title and ex.paras:
        first = ex.paras[0].text
        ex.title = first[:100] if len(first) < 120 else ""
    hs = [(i, p.text) for i, p in enumerate(ex.paras) if p.kind == "h"] or heading_starts(ex.paras)
    if len(hs) >= 2:
        ex.chapters = build_chapters(ex.paras, hs, "heading", front_title="Introduction")
    elif ex.paras:
        total = sum(len(p.text) for p in ex.paras)
        ex.chapters = auto_chapters(ex.paras) if total > 40000 else [
            ChapterIn(ex.title or "Text", 0, len(ex.paras) - 1, "single")]
    for ch in ex.chapters:
        for p in ex.paras[ch.start:ch.end + 1]:
            p.section = p.section or ch.title
    _text_checks(ex)
    return ex


def _text_checks(ex: Extracted) -> None:
    total = sum(len(p.text) for p in ex.paras)
    if total < 500:
        ex.warnings.append(f"Only {total} characters extracted; the page may be blocked, paywalled or script-rendered.")
    low = " ".join(p.text for p in ex.paras[:6]).lower()
    if any(k in low for k in ("subscribe to continue", "sign in to read", "log in to continue",
                              "create a free account to read", "enable javascript")):
        ex.warnings.append("The text looks like a paywall or login notice rather than the article.")


# ── HTML articles ───────────────────────────────────────────────────────────

class _Article(HTMLParser):
    SKIP = {"script", "style", "nav", "footer", "aside", "header", "noscript", "form", "svg", "iframe", "button",
            "template"}
    BLOCK = {"h1", "h2", "h3", "h4", "p", "li", "blockquote", "pre"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.article = 0
        self.cur: str | None = None
        self.buf: list[str] = []
        self.blocks: list[tuple[str, str, bool]] = []
        self.in_title = False
        self.title_tag = ""
        self.meta: dict[str, str] = {}

    def _flush(self):
        if self.cur:
            t = re.sub(r"\s+", " ", " ".join(self.buf)).strip()
            t = re.sub(r"\s+([,.;:!?])", r"\1", t)
            if t:
                self.blocks.append((self.cur, t, self.article > 0))
        self.cur, self.buf = None, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            k = (a.get("property") or a.get("name") or "").lower()
            if k and a.get("content"):
                self.meta.setdefault(k, a["content"].strip())
        if tag == "title":
            self.in_title = True
        if tag in self.SKIP:
            self.skip += 1
            return
        if tag == "article":
            self.article += 1
        if tag in self.BLOCK and not self.skip:
            self._flush()
            self.cur = tag
        if tag == "br" and self.cur:
            self.buf.append(" ")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if tag == "article":
            self._flush()
            self.article = max(0, self.article - 1)
        if tag in self.BLOCK:
            self._flush()

    def handle_data(self, data):
        if self.in_title:
            self.title_tag += data
        elif self.cur and not self.skip:
            self.buf.append(data)


_BOILER = re.compile(r"^(share|follow us|subscribe|sign up|advertisement|related (articles|stories)|read more|"
                     r"copyright|all rights reserved|cookie)", re.IGNORECASE)


def extract_html(html_text: str, url: str = "", title_hint: str = "") -> Extracted:
    p = _Article()
    p.feed(html_text)
    p._flush()
    ex = Extracted(fmt="article")
    m = p.meta
    h1 = next((t for tag, t, _ in p.blocks if tag == "h1"), "")
    ex.title = (m.get("og:title") or h1 or _html.unescape(p.title_tag.strip()) or title_hint or url)[:300]
    ex.author = (m.get("author") or m.get("article:author") or m.get("og:article:author") or "").strip()
    ex.meta = {k: m[k] for k in ("og:site_name", "article:published_time", "description") if k in m}
    ex.meta["url"] = url
    blocks = p.blocks
    in_art = [b for b in blocks if b[2]]
    if sum(len(b[1]) for b in in_art) > 600:
        blocks = in_art
    section = ""
    for tag, t, _ in blocks:
        if tag == "h1":
            if t.strip() == ex.title.strip() or ex.paras == [] and not section:
                continue
        if tag in ("h1", "h2", "h3", "h4"):
            section = t
            ex.paras.append(ParaIn(t, section=t, kind="h"))
            continue
        if len(t) < 25 or _BOILER.match(t):
            continue
        for piece in _split_long(t):
            ex.paras.append(ParaIn(("> " + piece) if tag == "blockquote" else piece, section=section))
    # drop headings that ended up with no body
    cleaned: list[ParaIn] = []
    for i, q in enumerate(ex.paras):
        if q.kind == "h" and (i + 1 == len(ex.paras) or ex.paras[i + 1].kind == "h"):
            continue
        cleaned.append(q)
    ex.paras = cleaned
    heads = {tag: [i for i, (tg, t, _) in enumerate(blocks) if tg == tag] for tag in ("h2", "h3")}
    level = "h2" if len(heads["h2"]) >= 2 else ("h3" if len(heads["h3"]) >= 3 else None)
    if level and ex.paras:
        wanted = {b[1] for b in blocks if b[0] == level}
        starts = [(i, q.text) for i, q in enumerate(ex.paras) if q.kind == "h" and q.text in wanted]
        ex.chapters = build_chapters(ex.paras, starts, "section", front_title="Introduction")
    elif ex.paras:
        ex.chapters = [ChapterIn(ex.title, 0, len(ex.paras) - 1, "single")]
    for ch in ex.chapters:
        for q in ex.paras[ch.start:ch.end + 1]:
            q.section = q.section or ch.title
    _text_checks(ex)
    return ex


# ── URL fetching ────────────────────────────────────────────────────────────

def _check_public(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise IngestError(f"cannot resolve host {host!r}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise IngestError("URL points to a private or local address; only public web pages can be fetched")


def _fetch_sync(url: str) -> tuple[bytes, str, str]:
    cur = url.strip()
    headers = {"User-Agent": "Mozilla/5.0 (compatible; story-research/1.0)", "Accept": "text/html,application/pdf,*/*"}
    with httpx.Client(timeout=30, follow_redirects=False, headers=headers) as c:
        for _ in range(6):
            u = urlparse(cur)
            if u.scheme not in ("http", "https") or not u.hostname:
                raise IngestError("only http(s) URLs can be imported")
            _check_public(u.hostname)
            with c.stream("GET", cur) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    cur = str(httpx.URL(cur).join(r.headers["location"]))
                    continue
                if r.status_code in (401, 402, 451):
                    raise IngestError(f"the site refused access (HTTP {r.status_code}); it may be paywalled or "
                                      "blocked. Paste the text or upload a saved file instead.")
                if r.status_code in BROWSER_RETRY:
                    raise BlockedError(f"the site refused the plain download (HTTP {r.status_code})")
                if r.status_code >= 400:
                    raise IngestError(f"the site returned HTTP {r.status_code}")
                data = bytearray()
                for chunk in r.iter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_DOWNLOAD:
                        raise IngestError("download is larger than 25 MB")
                return bytes(data), r.headers.get("content-type", ""), cur
    raise IngestError("too many redirects")


class BlockedError(IngestError):
    """The plain download was refused like a script (HTTP 403/429/503 or a bot-check page). A real browser is tried next."""


BROWSER_RETRY = (403, 429, 503)
_CHALLENGE = re.compile(r"just a moment|verify you are (a )?human|enable javascript and cookies|attention required|access denied|captcha", re.I)
_BROWSERS = (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
             r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
             "msedge", "google-chrome", "chromium", "chrome")


def find_browser() -> str | None:
    import shutil
    for b in _BROWSERS:
        if Path(b).is_file() or shutil.which(b):
            return b
    return None


def looks_blocked(raw: bytes, ctype: str) -> bool:
    """A 200 answer that is really a bot-check page: HTML that is short and carries a challenge phrase."""
    if "html" not in ctype.lower() and raw[:5] != b"<!DOC" and raw[:5].lower() != b"<html":
        return False
    text = raw[:20000].decode("utf-8", "ignore")
    return len(re.sub(r"<[^>]+>|\s+", " ", text)) < 3000 and bool(_CHALLENGE.search(text))


def _fetch_browser(url: str) -> tuple[bytes, str, str]:
    """Open the page in the installed Edge or Chrome (headless) and take the page as it renders. Same rules as the plain download: public hosts only, http(s)
    only, no login, no paywall (a page that still shows a paywall or a bot check is refused with the usual message)."""
    import subprocess
    import tempfile
    u = urlparse(url.strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        raise IngestError("only http(s) URLs can be imported")
    _check_public(u.hostname)
    exe = find_browser()
    if not exe:
        raise IngestError("the site blocked the plain download and no browser (Edge or Chrome) was found to try again. Paste the text or upload a saved file instead.")
    with tempfile.TemporaryDirectory() as prof:
        cmd = [exe, "--headless=new", "--disable-gpu", "--no-first-run", "--disable-extensions", f"--user-data-dir={prof}",
               "--window-size=1280,2000", "--dump-dom", url.strip()]
        out = Path(prof) / "dom.html"                          # a file, not a pipe: the browser's helper processes keep a pipe open after it has finished
        try:
            with open(out, "wb") as fh:
                r = subprocess.run(cmd, stdout=fh, stderr=subprocess.DEVNULL, timeout=75)
        except subprocess.TimeoutExpired as e:
            raise IngestError("the browser took too long to open the page. Paste the text or upload a saved file instead.") from e
        raw = out.read_bytes()
    if r.returncode != 0 or len(raw) < 500 or looks_blocked(raw, "text/html"):
        raise IngestError("the site refused the browser too (a bot check or a paywall). Paste the text or upload a saved file instead.")
    if len(raw) > MAX_DOWNLOAD:
        raise IngestError("download is larger than 25 MB")
    return raw, "text/html; charset=utf-8; via=browser", url.strip()


def fetch_with_fallback(url: str) -> tuple[bytes, str, str]:
    """The plain download first; a refusal that looks like bot protection (403/429/503 or a challenge page) is tried again in a real browser. Paywalls and
    login walls (401/402/451) are not tried again."""
    try:
        raw, ctype, final = _fetch_sync(url)
    except BlockedError:
        return _fetch_browser(url)
    if looks_blocked(raw, ctype):
        return _fetch_browser(url)
    return raw, ctype, final


async def fetch_url(url: str) -> tuple[bytes, str, str]:
    """Fetch a public page politely. Returns (bytes, content_type, final_url). Bot-protection blocks are retried in a real browser; paywalled pages produce
    a clear error and nothing else is bypassed. Runs in a thread (blocking client)."""
    import asyncio
    return await asyncio.to_thread(fetch_with_fallback, url)


def charset_from(content_type: str, raw: bytes) -> str | None:
    m = re.search(r"charset=([\w-]+)", content_type, re.IGNORECASE) or re.search(
        rb"<meta[^>]+charset=[\"']?([\w-]+)", raw[:4096], re.IGNORECASE)
    if not m:
        return None
    v = m.group(1)
    return v.decode() if isinstance(v, bytes) else v
