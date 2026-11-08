"""The upload text of a short: a YouTube title, a description, hashtags and tags, written so the short is found by search and clicked. One chat call (task `p4_publish`) from the finished
narration; code enforces the lengths and the hashtag rules, so the text can be pasted into YouTube Studio as it is. Saved on the short (`short["publish"]`) with the hash of the narration it
was written for, so the screen can say when the narration has changed since."""
import hashlib
import re

from story import llm, settings as settings_mod
from story.schemas import Str, StrList
from story2.schemas import M

TITLE_MAX = 70               # YouTube shows about 70 characters on a phone; the hard limit is 100
TITLE_MIN = 20
DESC_MAX = 4800              # YouTube allows 5000
TAGS_MAX_CHARS = 450         # YouTube allows 500 characters of tags in total
HASHTAGS_MAX = 5             # three show above the title; more than 15 and YouTube ignores them all

PUBLISH = """[TASK:p4_publish]
You write the upload text of a YouTube Short: the title and the description. They must make the short easy to FIND in YouTube search and Google and make people tap it.
Today is {today}. The audience is Indian viewers who search in English and Hinglish. The short is narrated in {language}.

TITLE (one line, {tmin} to {tmax} characters, hard limit {tmax}):
- Put the main search keyword (the subject people type) in the first 40 characters, in plain words people really search.
- Make a curiosity gap or a concrete promise the short really delivers: a number, a name, a "why", a "how". The title must be true to the short; no clickbait the video does not pay off.
- No quotation marks, no ALL CAPS words, at most one emoji, no hashtags in the title, no "#Shorts" in the title.
- Write it in English, or Hinglish in Latin letters when that is how people search for it.

DESCRIPTION (plain text, 600 to 1400 characters):
- The first 150 characters are all people see before "more": make them a hook that repeats the title's keyword and adds a second search phrase.
- Then 2 to 3 short paragraphs: what the short shows and why it matters, using the real topic words and related search phrases naturally (never a list of keywords, never stuffed). Only facts that are in the narration or the brief; invent nothing.
- Then one line that asks a question to start comments, and one line asking to follow for more.
- Last: a line with the hashtags. Do not put hashtags anywhere else.

HASHTAGS: 3 to 5, the first is #Shorts, then the topic words people search (no spaces inside one tag, no punctuation).
TAGS: 8 to 15 search phrases (1 to 4 words each), most important first, including a Hindi or Hinglish phrase when it fits.

Return ONLY a JSON object: {"title": "...", "description": "...", "hashtags": ["#Shorts", "#..."], "tags": ["...", "..."]}"""


class PublishOut(M):
    title: Str
    description: Str
    hashtags: StrList = []
    tags: StrList = []


def narration(short: dict) -> str:
    return " ".join(s["text"] for b in short.get("beats", []) for s in b.get("sentences", []))


def narration_hash(short: dict) -> str:
    return hashlib.sha1(narration(short).encode()).hexdigest()[:12]


def clean_title(t: str) -> str:
    t = re.sub(r"\s+", " ", (t or "").replace('"', "").replace("“", "").replace("”", "")).strip(" -–|#")
    t = re.sub(r"\s*#shorts\b", "", t, flags=re.I).strip()
    if len(t) > TITLE_MAX:
        cut = t[:TITLE_MAX].rsplit(" ", 1)[0].rstrip(" ,:;-–|")
        t = cut if len(cut) >= TITLE_MIN else t[:TITLE_MAX].rstrip()
    return t


def clean_hashtags(tags: list[str]) -> list[str]:
    out: list[str] = []
    for t in tags or []:
        w = "#" + re.sub(r"[^\w]", "", str(t).lstrip("#"), flags=re.UNICODE)
        if len(w) > 1 and len(w) <= 30 and w.lower() not in [x.lower() for x in out]:
            out.append(w)
    out = [x for x in out if x.lower() != "#shorts"]
    return (["#Shorts"] + out)[:HASHTAGS_MAX]


def clean_tags(tags: list[str]) -> list[str]:
    out: list[str] = []
    total = 0
    for t in tags or []:
        w = re.sub(r"\s+", " ", str(t).replace("#", "").replace(",", " ")).strip()
        if w and len(w) <= 40 and w.lower() not in [x.lower() for x in out] and total + len(w) + 2 <= TAGS_MAX_CHARS:
            out.append(w)
            total += len(w) + 2
    return out


def clean_description(body: str, hashtags: list[str]) -> str:
    """The description without any hashtag line the model wrote, then one hashtag line at the end."""
    lines = [ln.rstrip() for ln in (body or "").replace("\r\n", "\n").split("\n")]
    lines = [ln for ln in lines if not (ln.strip() and all(w.startswith("#") for w in ln.split()))]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    text = re.sub(r"[ 	]*#\w+", "", text)                                         # hashtags written inside a sentence are dropped; one hashtag line is added at the end
    text = text[:DESC_MAX - 120].rstrip()
    return f"{text}\n\n{' '.join(hashtags)}"


def problems(out: PublishOut) -> list[str]:
    p: list[str] = []
    t = clean_title(out.title)
    if len(t) < TITLE_MIN:
        p.append(f"the title is {len(t)} characters; write {TITLE_MIN} to {TITLE_MAX}")
    if len((out.title or "").strip()) > TITLE_MAX + 15:
        p.append(f"the title is {len(out.title.strip())} characters; keep it under {TITLE_MAX}")
    n = len((out.description or "").strip())
    if n < 400:
        p.append(f"the description is {n} characters; write 600 to 1400")
    if len(out.tags or []) < 6:
        p.append("write 8 to 15 tags")
    return p


def build(out: PublishOut) -> dict:
    hashtags = clean_hashtags(out.hashtags)
    return {"title": clean_title(out.title), "description": clean_description(out.description, hashtags), "hashtags": hashtags, "tags": clean_tags(out.tags)}


def view(short: dict) -> dict | None:
    """The saved upload text with copy-ready strings, and whether the narration changed after it was written."""
    p = short.get("publish")
    if not p or not p.get("title"):
        return None
    return {**p, "tags_text": ", ".join(p.get("tags", [])), "stale": p.get("for") != narration_hash(short)}


async def make(short_id: str, backend, s: dict | None = None, note: str = "") -> dict:
    """Write (or rewrite) the upload text of a short from its narration. `note` is the producer's wish (for example a keyword to lead with)."""
    from datetime import datetime

    from . import languages, store
    s = s or settings_mod.get()
    short = store.get(short_id)
    if not short.get("beats"):
        raise ValueError("write the narration first")
    lang = languages.LANGUAGES[languages.of(short["settings"])]["label"]
    system = PUBLISH.replace("{today}", datetime.now().strftime("%d %B %Y")).replace("{language}", lang).replace("{tmin}", str(TITLE_MIN)).replace("{tmax}", str(TITLE_MAX))
    brief = (short.get("source") or {}).get("text", "")[:1500]
    user = (f"SHORT TITLE (working name): {short.get('title', '')}\nLOGLINE: {(short.get('plan') or {}).get('logline', '')}\n\nTHE NARRATION (what is said, in order):\n{narration(short)}"
            + (f"\n\nTHE BRIEF THE SHORT WAS MADE FROM:\n{brief}" if brief else "") + (f"\n\nTHE PRODUCER ASKS: {note}" if note.strip() else "") + "\n\nWrite the upload text now.")
    caller = llm.JsonCaller(backend, s)

    def check(out: PublishOut) -> None:
        if caller.last_attempt:
            return
        probs = problems(out)
        if probs:
            raise ValueError("; ".join(probs))

    res = await caller.call(system, user, PublishOut, validate=check)
    short = store.get(short_id)
    short["publish"] = {**build(res.value), "for": narration_hash(short)}
    store.save(short)
    return view(short)
