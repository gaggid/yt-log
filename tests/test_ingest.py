import pytest

from story import db, ingest, projects

reportlab = pytest.importorskip("reportlab")


def make_pdf(path, chapters=3, pages_per=4, header="The Test Book - Running Header"):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import simpleSplit
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle("The Test Book")
    c.setAuthor("A. Writer")
    page = 0
    for ch in range(1, chapters + 1):
        for pg in range(pages_per):
            page += 1
            c.setFont("Helvetica", 9)
            c.drawString(60, 810, header)
            y = 780
            c.setFont("Helvetica", 11)
            if pg == 0:
                c.setFont("Helvetica-Bold", 16)
                c.drawString(60, y, f"Chapter {ch}")
                y -= 40
                c.setFont("Helvetica", 11)
            for k in range(3):
                text = (f"In chapter {ch} page {page} paragraph {k}, the expedition crossed the river in 19{10 + page} "
                        f"and recorded the water level carefully. " * 4)
                for line in simpleSplit(text, "Helvetica", 11, 470):
                    c.drawString(60, y, line)
                    y -= 14
                y -= 12
            c.drawString(290, 30, str(page))
            c.showPage()
    c.save()
    return path


def test_pdf_pages_chapters_and_furniture(tmp_path):
    pdf = make_pdf(tmp_path / "b.pdf")
    ex = ingest.extract_pdf(pdf)
    assert ex.fmt == "pdf" and ex.page_count == 12
    assert ex.title == "The Test Book" and ex.author == "A. Writer"
    assert {p.page for p in ex.paras} == set(range(1, 13))                 # every page maps back
    assert not any("Running Header" in p.text for p in ex.paras)           # repeated header removed
    assert not any(p.text.strip().isdigit() for p in ex.paras)             # bare page numbers removed
    assert [c.title for c in ex.chapters][:3] == ["Chapter 1", "Chapter 2", "Chapter 3"]
    assert ex.chapters[1].page_start == 5 and ex.chapters[2].page_start == 9
    assert ex.chapters[0].start == 0 and ex.chapters[-1].end == len(ex.paras) - 1


def test_pdf_without_text_warns(tmp_path):
    from reportlab.pdfgen import canvas
    p = tmp_path / "scan.pdf"
    c = canvas.Canvas(str(p))
    for _ in range(3):
        c.rect(10, 10, 100, 100)
        c.showPage()
    c.save()
    ex = ingest.extract_pdf(p)
    assert ex.paras == [] and any("no extractable text" in w for w in ex.warnings)


def test_import_pdf_keeps_original_immutable(env, tmp_path):
    pdf = make_pdf(tmp_path / "b.pdf")
    data = pdf.read_bytes()
    pid = projects.import_file("b.pdf", data)
    p = projects.get(pid)
    assert p["format"] == "pdf" and p["page_count"] == 12 and p["chapter_count"] >= 3 and p["est_tokens"] > 0
    orig = projects.original_path(pid)
    assert orig.read_bytes() == data
    with pytest.raises(PermissionError):
        orig.write_bytes(b"x")
    assert p["sha256"]
    projects.delete(pid)                                                   # read-only files still removable
    assert not orig.exists()


def test_corrupt_pdf_is_rejected(env):
    with pytest.raises(projects.ProjectError):
        projects.import_file("x.pdf", b"not a pdf")


ARTICLE = """<html><head><title>Site | Big Dam Failure</title><meta name="author" content="Jo Reporter">
<meta property="og:title" content="The Dam That Broke"></head><body>
<nav><p>Home About Contact us today for more information</p></nav>
<header><h1>SITE NAME</h1></header>
<article><h1>The Dam That Broke</h1>
<p>On a warm March night in 1928 the St. Francis Dam failed without warning, sending a wall of water down the valley. It killed more than four hundred people.</p>
<h2>The warning signs</h2>
<p>Engineers had noticed new cracks that morning, but the chief engineer inspected the structure and declared it safe after a short visit.</p>
<p>Share this article on social media</p>
<h2>The inquiry</h2>
<blockquote>A quote from the coroner jury that is long enough to keep around.</blockquote>
<p>The inquest blamed the design, and the engineer accepted responsibility publicly in the months that followed the disaster.</p>
</article><aside><p>Related stories you might like to read this week</p></aside>
<footer><p>Copyright 2024 all rights reserved by the publisher</p></footer></body></html>"""


def test_article_extraction():
    ex = ingest.extract_html(ARTICLE, url="https://example.com/dam")
    assert ex.title == "The Dam That Broke" and ex.author == "Jo Reporter" and ex.meta["url"] == "https://example.com/dam"
    texts = [p.text for p in ex.paras]
    assert not any("Home About" in t or "Copyright" in t or "Related stories" in t or t.startswith("Share this") for t in texts)
    assert [c.title for c in ex.chapters] == ["Introduction", "The warning signs", "The inquiry"]
    assert any(p.kind == "h" and p.text == "The inquiry" for p in ex.paras)
    assert next(p for p in ex.paras if "inspected" in p.text).section == "The warning signs"
    assert any(t.startswith("> ") for t in texts)                          # blockquote kept


def test_paywall_warning():
    html = "<html><body><article><p>Subscribe to continue reading this article and more from our newsroom.</p></article></body></html>"
    ex = ingest.extract_html(html)
    assert any("paywall" in w.lower() or "characters" in w for w in ex.warnings)


def test_text_headings_and_long_paragraph_split():
    long = "This is a sentence about the harbour. " * 120
    ex = ingest.extract_text(f"Chapter 1: Start\n\n{long}\n\nChapter 2: End\n\nShort closing paragraph here for the end of it all.")
    assert [c.title for c in ex.chapters][-2:] == ["Chapter 1: Start", "Chapter 2: End"]
    assert max(len(p.text) for p in ex.paras) <= ingest.MAX_PARA_CHARS + 50
    assert "".join(p.text for p in ex.paras if p.kind == "p").count("harbour") >= 120   # nothing lost by splitting


def test_url_guard_blocks_private_hosts():
    import asyncio
    with pytest.raises(ingest.IngestError):
        asyncio.run(ingest.fetch_url("http://127.0.0.1:8905/"))
    with pytest.raises(ingest.IngestError):
        asyncio.run(ingest.fetch_url("file:///etc/passwd"))


def test_manual_correction_and_chapter_edit(env):
    pid = projects.import_text("Chapter 1\n\n" + "First paragraph of the book with enough words in it.\n\n" * 5
                               + "Chapter 2\n\n" + "Second part paragraph with different words inside.\n\n" * 5)
    n = projects.get_paras(pid)["total"]
    projects.edit_para(pid, 3, "Corrected text.")
    row = db.one("SELECT text, orig_text, edited FROM paras WHERE project_id=? AND idx=3", (pid,))
    assert row["text"] == "Corrected text." and row["orig_text"].startswith("First paragraph") and row["edited"] == 1
    chs = projects.set_chapters(pid, [{"title": "A", "start_para": 1}, {"title": "B", "start_para": 5}])
    assert [(c["title"], c["start_para"], c["end_para"]) for c in chs] == [("A", 1, 4), ("B", 5, n)]
    with pytest.raises(projects.ProjectError):
        projects.set_chapters(pid, [{"title": "A", "start_para": 2}])


def test_blocked_download_is_retried_in_a_browser_but_paywall_is_not(monkeypatch):
    html = b"<html><body>" + b"<p>Real article text here.</p>" * 40 + b"</body></html>"
    calls = []

    def blocked(url):
        raise ingest.BlockedError("HTTP 403")
    monkeypatch.setattr(ingest, "_fetch_sync", blocked)
    monkeypatch.setattr(ingest, "_fetch_browser", lambda url: calls.append(url) or (html, "text/html", url))
    assert ingest.fetch_with_fallback("https://example.com/a")[0] == html and calls == ["https://example.com/a"]

    def paywall(url):
        raise ingest.IngestError("the site refused access (HTTP 402)")
    monkeypatch.setattr(ingest, "_fetch_sync", paywall)
    with pytest.raises(ingest.IngestError):
        ingest.fetch_with_fallback("https://example.com/b")
    assert len(calls) == 1                                           # a paywall is never retried


def test_bot_check_page_is_detected_and_retried(monkeypatch):
    page = b"<html><head><title>Just a moment...</title></head><body>Verify you are human</body></html>"
    assert ingest.looks_blocked(page, "text/html") and not ingest.looks_blocked(b"%PDF-1.4", "application/pdf")
    good = b"<html><body>" + b"<p>Article.</p>" * 400 + b"</body></html>"
    monkeypatch.setattr(ingest, "_fetch_sync", lambda url: (page, "text/html", url))
    monkeypatch.setattr(ingest, "_fetch_browser", lambda url: (good, "text/html", url))
    assert ingest.fetch_with_fallback("https://example.com/c")[0] == good


def test_browser_fallback_keeps_the_private_host_guard():
    with pytest.raises(ingest.IngestError):
        ingest._fetch_browser("http://127.0.0.1:8905/")


def test_a_page_read_through_the_browser_is_flagged_on_the_project(env, monkeypatch):
    import asyncio
    from story import projects
    html = ("<html><head><title>Harbour news</title></head><body>" + "<p>The harbour board met on Tuesday and approved the new pier after a long debate about the cost.</p>" * 30 + "</body></html>").encode()

    async def fake_fetch(url):
        return html, "text/html; charset=utf-8; via=browser", url
    monkeypatch.setattr(ingest, "fetch_url", fake_fetch)
    pid = asyncio.run(projects.import_url("https://example.com/news"))
    assert any("opened in a browser" in w for w in projects.get(pid)["warnings"])


def test_no_chat_model_is_named_unless_the_owner_typed_one(env):
    from story import llm, settings as settings_mod
    assert settings_mod.get()["model"] == "" and llm.model_field(settings_mod.get()) == {}
    settings_mod.update({"model": "gemma4-12b-qat-uncensored-hauhaucs-balanced"})                       # the old saved default counts as unset
    assert settings_mod.get()["model"] == "" and llm.model_field(settings_mod.get()) == {}
    settings_mod.update({"model": "my-model"})
    assert llm.model_field(settings_mod.get()) == {"model": "my-model"}
