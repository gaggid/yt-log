"""Charts, figures and tables from PDF sources.

The text model never sees pictures, but a story built on a chart (price pattern, map, diagram) is incomplete without it.
So pages that carry a figure are located (large embedded image, or a "Figure/Chart/Exhibit N" caption), rendered once to an
image file, and linked to the stories that cite text on or next to that page. Credit lines such as "© ... used with
permission" are kept and raise a rights flag: showing a figure in a video needs clearance first.
Everything here is best-effort; a failure never blocks an import.
"""
import re
from pathlib import Path

from . import db

# "�" is how a broken © glyph often extracts
_NOTICE = (r"©|�\s*\d{4}|\(c\)\s*\d{4}|\bcopyright\b|all rights reserved|used with permission|\bby permission\b|"
           r"\bcourtesy of\b|\breprinted\b|\breproduced (?:with|by)\b")
RIGHTS_RE = re.compile(_NOTICE, re.I)
CREDIT_RE = re.compile(_NOTICE + r"|\bsource\s*:", re.I)
_CAP_WORDS = r"(?:figure|fig\.?|chart|exhibit|graph|table|diagram|illustration)"
CAPTION_AT_START = re.compile(rf"^\s*{_CAP_WORDS}\s*\d+(?:[.\-]\d+)?\b", re.I)
CAPTION_ANYWHERE = re.compile(rf"\b{_CAP_WORDS}\s*\d+(?:[.\-]\d+)?\s*[:.\-–—]?\s+[A-Z][^.\n]{{2,90}}", re.I)
MIN_IMAGE_SHARE = 0.06                 # embedded image must cover this share of the page to count as a figure
MAX_FIGURES = 400
SCALE = 1.4


def figures_dir(pid: str) -> Path:
    from . import projects
    d = projects.sources_dir() / pid / "figures"
    d.mkdir(parents=True, exist_ok=True)
    return d


def fig_id(pid: str, page: int) -> str:
    return f"F-{pid[:6]}-p{page:04d}"


def despace(t: str) -> str:
    """'F I G U R e 1.1' -> 'FIGURe 1.1': runs of single letters separated by spaces are headings set in spaced capitals."""
    return re.sub(r"(?<![^\W\d_])((?:[^\W\d_] ){3,}[^\W\d_])(?![^\W\d_])", lambda m: m.group(1).replace(" ", ""), t)


def _caption(text: str) -> str | None:
    t = despace(text)
    m = CAPTION_ANYWHERE.search(t)
    if m:
        cap = m.group(0)
        c = re.search(r"esignal", cap, re.I) or CREDIT_RE.search(cap)
        return (cap[:c.start()] if c else cap).strip()
    return t.strip() if len(t) <= 320 and CAPTION_AT_START.match(t) else None


def _captions(paras) -> tuple[dict[int, list[str]], set[int]]:
    """Captions by page, plus the pages where one is a real caption (starts a paragraph or is set in capitals)
    rather than a sentence such as "Figure 1.1 provides an example"."""
    out: dict[int, list[str]] = {}
    strong: set[int] = set()
    for p in paras:
        if not p.page:
            continue
        c = _caption(p.text)
        if c:
            out.setdefault(p.page, []).append(c)
            if CAPTION_AT_START.match(despace(p.text)) or re.search(rf"[A-Z]{{3,}}\w?\s*\d+[.\-]\d+", c):
                strong.add(p.page)
    return out, strong


def _credits(paras, pages: set[int]) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for p in paras:
        if p.page in pages and len(p.text) <= 320 and CREDIT_RE.search(p.text):
            out.setdefault(p.page, []).append(_snippet(p.text))
    return out


def _snippet(text: str) -> str:
    """The credit itself, not the paragraph that happens to contain it."""
    m = CREDIT_RE.search(text)
    if not m or len(text) <= 160:
        return text.strip()
    return text[max(0, m.start() - 40): m.end() + 120].strip()


def _image_pages(pdf) -> dict[int, float]:
    """page number -> share of the page covered by its largest embedded image."""
    import pypdfium2.raw as raw  # type: ignore
    found: dict[int, float] = {}
    for i in range(len(pdf)):
        page = pdf[i]
        w, h = page.get_size()
        best = 0.0
        try:
            for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE]):
                l, b, r, t = obj.get_bounds()
                best = max(best, max(0.0, (r - l) * (t - b)) / max(1.0, w * h))
        except Exception:  # noqa: BLE001 - one odd page must not stop detection
            continue
        if best >= MIN_IMAGE_SHARE:
            found[i + 1] = best
    return found


def extract(pdf_path: Path, pid: str, paras) -> list[dict]:
    """Detect, render and register figure pages. Returns the records stored."""
    try:
        import pypdfium2  # type: ignore
    except ImportError:
        return []
    pdf = pypdfium2.PdfDocument(str(pdf_path))
    try:
        images = _image_pages(pdf)
        captions, strong = _captions(paras)
        chosen = sorted({pg for pg in images if pg > 2 or captions.get(pg)} | strong)[:MAX_FIGURES]
        credits = _credits(paras, set(chosen))
        out_dir = figures_dir(pid)
        recs = []
        for pg in chosen:
            rel = f"p{pg:04d}.jpg"
            try:
                pdf[pg - 1].render(scale=SCALE).to_pil().convert("RGB").save(out_dir / rel, quality=80)
            except Exception:  # noqa: BLE001
                continue
            cred = credits.get(pg, [])
            recs.append({"id": fig_id(pid, pg), "page": pg, "kind": "image" if pg in images else "caption",
                         "caption": (captions.get(pg) or [""])[0][:300], "credit": " | ".join(cred)[:400],
                         "rights": int(any(RIGHTS_RE.search(c) for c in cred)), "file": rel})
        with db.tx() as c:
            c.execute("DELETE FROM figures WHERE project_id=?", (pid,))
            for r in recs:
                c.execute("INSERT INTO figures(id,project_id,page,kind,caption,credit,rights,file) VALUES(?,?,?,?,?,?,?,?)",
                          (r["id"], pid, r["page"], r["kind"], r["caption"], r["credit"], r["rights"], r["file"]))
        return recs
    finally:
        pdf.close()


def list_figures(pid: str) -> list[dict]:
    return db.q("SELECT id,page,kind,caption,credit,rights,file FROM figures WHERE project_id=? ORDER BY page", (pid,))


def near(pid: str, pages: list[int], reach: int = 1) -> list[dict]:
    """Figures on, or within `reach` pages of, the pages a story cites."""
    wanted = {p + d for p in pages for d in range(-reach, reach + 1)}
    return [f for f in list_figures(pid) if f["page"] in wanted]


def image_path(pid: str, fid: str) -> Path | None:
    r = db.one("SELECT file FROM figures WHERE id=? AND project_id=?", (fid, pid))
    if not r:
        return None
    p = figures_dir(pid) / r["file"]
    return p if p.exists() else None


def for_paras(pid: str, para_idxs: list[int]) -> list[dict]:
    """Figures near the passages a story cites, shaped for the export and the review screen."""
    if not para_idxs:
        return []
    marks = ",".join("?" * len(para_idxs))
    pages = [r["page"] for r in db.q(f"SELECT DISTINCT page FROM paras WHERE project_id=? AND idx IN ({marks}) AND page IS NOT NULL",
                                     [pid] + list(para_idxs))]
    return [{"id": f["id"], "page": f["page"], "caption": f["caption"], "credit": f["credit"], "rights_flag": bool(f["rights"]),
             "file": f"figures/{f['file']}"} for f in near(pid, pages)]
