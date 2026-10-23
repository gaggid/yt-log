"""Source-leak and originality checks. The videos are our own versions of the stories, so nothing spoken, shown or sent to an
image model may point back to the source or copy its wording. This runs on narration, on-screen text, titles and prompts.

Findings are data, not exceptions: the editor sees what and where, and approval is blocked while any remain.
"""
import re
from dataclasses import dataclass, field

from story import db

NGRAM = 6                                # this many consecutive identical words in the source and in our text = copied wording

# phrases that talk about the source itself (English and Hindi)
_SELF_REF = re.compile(
    r"\b(?:the|this|that|our|his|her)\s+(?:book|author|chapter|text|passage|writer|publisher|preface|foreword|excerpt)\b"
    r"|\baccording to (?:the|this|a)\b|\bas (?:the )?(?:author|book|text)\b|\b(?:in|from) (?:chapter|part|page)\s+\w+"
    r"|\bpage\s+\d+\b|\bpp?\.\s*\d+\b|\bwrites? that\b|\bexplains? in (?:the|his|her)\b"
    r"|लेखक|किताब|पुस्तक|अध्याय|पृष्ठ|प्रकाशक|भूमिका|प्रस्तावना|के अनुसार",
    re.I)
_PARTS = re.compile(r"\bpart\s+(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+|[ivx]+)\b", re.I)
_P_TAG = re.compile(r"\[\s*P\d+")


@dataclass
class Finding:
    kind: str                            # title | author | credit | self_reference | part_title | paragraph_tag | copied_wording
    text: str
    detail: str = ""

    def as_dict(self) -> dict:
        return {"kind": self.kind, "text": self.text, "detail": self.detail}


@dataclass
class SourceProfile:
    title: str = ""
    author: str = ""
    credits: list[str] = field(default_factory=list)
    chapter_titles: list[str] = field(default_factory=list)
    passages: list[str] = field(default_factory=list)


def profile(pid: str, passages: list[str] | None = None) -> SourceProfile:
    p = db.one("SELECT title, author FROM projects WHERE id=?", (pid,)) or {}
    credits = []
    for f in db.q("SELECT credit FROM figures WHERE project_id=? AND credit!=''", (pid,)):
        for c in f["credit"].split(" | "):
            m = re.match(r"\s*([A-Za-z][\w&.\- ]{2,40}?)\s*(?:©|�|\(c\)|copyright|\d{4}|all rights)", c, re.I)
            if m:
                credits.append(m.group(1).strip())
    return SourceProfile(title=(p.get("title") or ""), author=(p.get("author") or ""), credits=sorted(set(credits)),
                         chapter_titles=[c["title"] for c in db.q("SELECT title FROM chapters WHERE project_id=?", (pid,))],
                         passages=passages or [])


def _words(t: str) -> list[str]:
    return re.findall(r"[\w']+", t.lower())


def _title_variants(title: str) -> list[str]:
    t = re.sub(r"\(.*?\)", "", title).strip()
    t = re.sub(r"\b(?:v\d+|copy of)\b", "", t, flags=re.I).strip(" -")
    out = [t] if len(t) >= 6 else []
    if ":" in t:
        out.append(t.split(":")[0].strip())
    return [x for x in out if len(x) >= 6]


def _author_names(author: str) -> list[str]:
    parts = [p for p in re.split(r"\s+", author.strip()) if len(p) > 1 and not p.endswith(".")]
    names = [author.strip()] if len(author.strip()) >= 5 else []
    if len(parts) >= 2:
        names.append(parts[-1])                              # surname alone
    return names


def check(text: str, prof: SourceProfile, ngram: int = NGRAM) -> list[Finding]:
    out: list[Finding] = []
    low = text.lower()
    for t in _title_variants(prof.title):
        if t.lower() in low:
            out.append(Finding("title", t, "names the source book"))
    for a in _author_names(prof.author):
        if re.search(rf"\b{re.escape(a.lower())}\b", low):
            out.append(Finding("author", a, "names the source author"))
    for c in prof.credits:
        if c.lower() in low:
            out.append(Finding("credit", c, "a credit line printed in the source"))
    for ch in prof.chapter_titles:
        if len(ch) >= 12 and ch.lower() in low and not ch.lower().startswith(("front", "contents", "index")):
            out.append(Finding("part_title", ch, "a section title of the source"))
    for m in _SELF_REF.finditer(text):
        out.append(Finding("self_reference", m.group(0), "talks about the source instead of the story"))
    for m in _PARTS.finditer(text):
        out.append(Finding("part_title", m.group(0), "points to a section of the source"))
    if _P_TAG.search(text):
        out.append(Finding("paragraph_tag", "[P…]", "internal paragraph label"))
    out.extend(copied(text, prof.passages, ngram))
    return out


def copied(text: str, passages: list[str], ngram: int = NGRAM) -> list[Finding]:
    """Runs of `ngram` or more consecutive words that also appear in the source passages."""
    tw = _words(text)
    if len(tw) < ngram or not passages:
        return []
    grams = set()
    for p in passages:
        w = _words(p)
        grams.update(tuple(w[i:i + ngram]) for i in range(len(w) - ngram + 1))
    found, i = [], 0
    while i <= len(tw) - ngram:
        if tuple(tw[i:i + ngram]) in grams:
            j = i + ngram
            while j < len(tw) and tuple(tw[j - ngram + 1:j + 1]) in grams:
                j += 1
            found.append(Finding("copied_wording", " ".join(tw[i:j]), f"{j - i} words identical to the source"))
            i = j
        else:
            i += 1
    return found


def check_many(items: list[tuple[str, str]], prof: SourceProfile) -> list[dict]:
    """items: [(where, text)] -> findings with their location, ready for the validation report."""
    rows = []
    for where, text in items:
        for f in check(text, prof):
            rows.append({"where": where, **f.as_dict()})
    return rows


def overlap_share(text: str, passages: list[str], ngram: int = NGRAM) -> float:
    """Share of our words that sit inside a copied run: the measured part of 'originality of treatment'."""
    tw = _words(text)
    if not tw:
        return 0.0
    return round(sum(len(f.text.split()) for f in copied(text, passages, ngram)) / len(tw), 3)
