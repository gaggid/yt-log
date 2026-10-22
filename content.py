"""Editorial steps: research -> angles/questions -> deeper research -> persona script -> beats -> scene plan.
`chat` is an async callable chat(messages, **kwargs) -> str supplied by main.py."""
import email.utils
import html as _html
import json
import math
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import config

# ── News sourcing ──────────────────────────────────────────────────────────────

_GN = "https://news.google.com/rss"
_INDIA_FEEDS = [
    _GN + "/headlines/section/topic/NATION?hl=en-IN&gl=IN&ceid=IN:en",
    _GN + "/headlines/section/topic/BUSINESS?hl=en-IN&gl=IN&ceid=IN:en",
    _GN + "/headlines/section/topic/TECHNOLOGY?hl=en-IN&gl=IN&ceid=IN:en",
    _GN + "/headlines/section/topic/SCIENCE?hl=en-IN&gl=IN&ceid=IN:en",
]
_TRUSTED = {
    "the hindu", "hindustan times", "indian express", "ndtv", "times of india",
    "livemint", "mint", "economic times", "business standard", "the wire",
    "scroll", "pti", "ani", "bbc", "reuters", "bloomberg", "moneycontrol",
    "techcrunch", "wired", "nature", "science", "forbes india", "quartz",
}
_BAD = {"facebook", "reddit", "youtube", "instagram", "x.com", "twitter", "quora",
        "linkedin", "whatsapp", "tiktok"}
_MAX_AGE_H = 36


def fetch_headlines(topic: str = "") -> list[dict]:
    """Fetch recent India news from Google News RSS (last 36 h). Returns up to 50 candidates."""
    from urllib.parse import quote_plus
    now = datetime.now(timezone.utc)
    feeds = list(_INDIA_FEEDS)
    if topic:
        feeds.append(_GN + "/search?q=" + quote_plus(f"{topic} India when:2d") + "&hl=en-IN&gl=IN&ceid=IN:en")
    seen, out = set(), []
    for url in feeds:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            raw = urllib.request.urlopen(req, timeout=20).read()
            items = ET.fromstring(raw).findall(".//item")
        except Exception:
            continue
        for it in items:
            title = _html.unescape(it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            src = (it.findtext("source") or "").strip()
            try:
                dt = email.utils.parsedate_to_datetime(it.findtext("pubDate") or "")
            except Exception:
                continue
            if not title or not link:
                continue
            if any(b in src.lower() for b in _BAD):
                continue
            age_h = (now - dt).total_seconds() / 3600
            if age_h > _MAX_AGE_H or dt > now:
                continue
            key = re.sub(r"\W+", " ", title.lower())[:50]
            if key in seen:
                continue
            seen.add(key)
            # Strip trailing " - Outlet" from title
            clean_title = re.sub(r"\s+-\s+[^-]{2,60}$", "", title).strip()
            out.append({
                "title": clean_title, "source": src, "url": link,
                "date": dt.strftime("%Y-%m-%d"), "age_h": round(age_h, 1),
                "trusted": any(t in src.lower() for t in _TRUSTED),
            })
    out.sort(key=lambda x: (not x["trusted"], x["age_h"]))
    return out[:50]


async def curate_headlines(chat, candidates: list[dict], topic: str = "") -> list[dict]:
    """AI picks the 8 most important, distinct stories from RSS candidates."""
    if not candidates:
        return []
    listing = "\n".join(
        f"{i}: [{'✓' if c['trusted'] else '~'}] {c['title']} | {c['source']} | {c['age_h']}h ago"
        for i, c in enumerate(candidates)
    )
    focus = (f"specifically about: {topic}" if topic
             else "India science, technology, economy, and politics — stories with lasting significance")
    prompt = (
        f"You are a senior news editor. Pick the 8 most important, distinct stories. "
        f"Focus: {focus}. Prefer [✓] trusted sources. No duplicate events.\n"
        f"Return ONLY JSON: {{\"picks\": [0,3,7,...]}}\n\n{listing}"
    )
    try:
        m = re.search(r"\{.*\}", await chat([{"role": "user", "content": prompt}],
                                            max_tokens=200, temperature=0.1), re.DOTALL)
        picks = [int(i) for i in json.loads(m.group()).get("picks", [])
                 if str(i).isdigit() and int(i) < len(candidates)]
        return [candidates[i] for i in picks[:10]]
    except Exception:
        return candidates[:8]


async def find_uber_story(chat, headlines: list[dict]) -> str:
    """Find the ONE overarching meta-narrative connecting today's curated stories."""
    if not headlines:
        return ""
    listing = "\n".join(f"- {h['title']}" for h in headlines)
    prompt = (
        f"These are today's top India news stories:\n{listing}\n\n"
        "What is the ONE meta-narrative that connects most of these? "
        "Find the deeper structural shift in India's trajectory that these stories collectively reveal. "
        "Be specific — not 'India is growing' but the exact tension or turning point at play. "
        "2-3 sentences a podcast host can use as the spine of the whole episode. "
        "Return ONLY the uber story text, nothing else."
    )
    try:
        result = (await chat([{"role": "user", "content": prompt}], max_tokens=300, temperature=0.3)).strip()
        return result if len(result) > 20 else ""
    except Exception:
        return ""

PERSONA = """You ARE the host of a personal-feeling Indian podcast. Speak in FIRST PERSON, to ONE listener ("aap"), like a sharp
friend on a late-night call, never like a news anchor.
Persona: male, witty, educated, logical. A contrarian who does not accept the headline at face value: you dissect the topic,
ask "but wait, why?", test the popular opinion, and say what most people miss. Light sarcasm and dry humour are welcome, never
cruelty. Sensational hooks are good; fabricated facts are not: every number and claim must come from the research notes.
You anticipate the questions a curious listener would ask and answer them yourself in the flow
("ab aap soch rahe honge..."). You also invite the listener to argue back in the comments, like talking to a friend
("comment mein batao, main har view padhta hoon").
Delivery style: fast-paced and supremely confident. No hedging, no filler ("toh basically", "matlab"). Short punchy
sentences. State things as facts, drive each point home, then move on immediately."""

HINGLISH_RULES = """Language = natural spoken Hinglish written in ROMAN script (English letters), the way educated urban Indians
text and talk: Hindi grammar in Roman ("kya aapko lagta hai ki...", "lekin asli baat ye hai"), English words spelled normally
("ChatGPT", "AI model", "startup", "data", "GDP", "comment", "real problem", "logic").
- Never replace everyday English words with heavy shuddh Hindi: say "model", "internet", "problem", "system", not their
  Sanskritised versions.
- NEVER write a full English sentence or clause. English appears only as single words or short terms (max 3 in a row)
  inside Hindi sentence structure. Wrong: "Let's look at the facts, gold is the ultimate safe haven."
  Right: "Chaliye facts dekhte hain, gold ko log sabse safe jagah maante hain."
- Hindi words in simple, consistent Roman spelling (hai, nahi, kyun, aur, lekin, matlab, sachchai).
- Write numbers as words ("do billion", "bees crore", "tees percent"); no digits except inside product names like GPT-4.
- Male speaker: masculine first-person forms (bol raha hoon, mujhe lagta hai, main maanta hoon).
- Short, punchy sentences (max ~18 words), conversational rhythm, questions to the listener. Plain punctuation only
  (. ? ,). No emojis, no markdown, no stage directions, no brackets, no hashtags, no quotes around words."""


def extract_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group())
        raise ValueError(f"No JSON found in response: {text[:200]}")


async def make_character_bible(chat, script: dict, topic: str) -> dict:
    """Generate a protagonist + environments + tone arc that will anchor every scene visually."""
    segs = script.get("segments", [])
    arc = "\n".join(
        f"  [{s.get('role','').split('|')[0]}] {s['narration'][:100]}..."
        for s in segs[:5])
    prompt = (
        f"You are a casting director and production designer for a short cinematic documentary.\n"
        f"Topic: {topic or script.get('title', 'todays news')}\n"
        f"Story arc:\n{arc}\n\n"
        "Design one protagonist and a visual world that can carry this story.\n"
        "The protagonist is a real-feeling person — not a generic stock-photo type.\n"
        "Give precise physical details an image model can reproduce: age range, ethnicity, hair (length, colour, style), "
        "face (jawline, eyes, glasses or not, stubble or not), clothing (specific colour, style, fit).\n"
        "Return JSON exactly:\n"
        '{"protagonist": {'
        '"description": "3-4 sentences of precise physical appearance",'
        '"arc": "emotional journey in one sentence — what they start feeling vs end feeling"'
        '}, '
        '"environments": ['
        '"[env 1: specific location, time of day, light quality]",'
        '"[env 2]",'
        '"[env 3]"'
        '], '
        '"tone_arc": "one sentence: how visual mood shifts from opening shot to closing shot"}'
    )
    try:
        data = extract_json(await chat([{"role": "user", "content": prompt}],
                                       max_tokens=600, temperature=0.4))
        if data.get("protagonist", {}).get("description"):
            return data
    except Exception:
        pass
    return {
        "protagonist": {
            "description": "Indian male professional, early 30s, wire-frame rectangular glasses, neat short black hair, light stubble, wearing a light blue collared shirt, slim build.",
            "arc": "starts anxious and uncertain, ends confident and clear-eyed"
        },
        "environments": [
            "modern open-plan Indian tech office, dusk, cool blue fluorescent light with city visible through glass partitions",
            "busy Indian city street, mid-morning, harsh sunlight and vendor stalls",
            "clean minimalist home study, evening, warm lamp light"
        ],
        "tone_arc": "opens in cool unsettling blue, transitions through tension to warm resolved amber by the final shot"
    }


async def research(chat, topic: str, headlines: list[dict] | None = None) -> str:
    """Synthesise curated RSS headlines into rich research notes, or fall back to web_search."""
    if headlines:
        listing = "\n".join(
            f"- {h['title']} [{h['source']}, {h['date']}]\n  URL: {h['url']}"
            for h in headlines
        )
        return await chat([{"role": "user", "content":
            "Summarise these curated news stories into detailed research notes for a podcast episode. "
            "For each story: what happened, key numbers and facts, why it matters, and useful background context. "
            "These notes are the ONLY facts the host will use — be thorough.\n\n"
            f"Stories:\n{listing}"}], max_tokens=3000)
    # Fallback for topic-specific research where RSS may not have enough
    query = topic or "India science technology economy politics news today"
    return await chat([{"role": "user", "content":
        f"Research the LATEST news (last 24-48 hours) about: {query}. "
        "Focus on India. Use trusted sources: The Hindu, Economic Times, NDTV, Indian Express, Reuters, BBC. "
        "Find 6-8 key stories with facts, numbers, and context. Be thorough."}],
        server_tools=["web_search"], max_tokens=2500)


async def find_angles(chat, notes: str) -> dict:
    prompt = f"""You are a sharp, sceptical analyst preparing a podcast. Read the research notes.

Notes:
{notes}

Produce exactly:
- core_claim: the one-line story everybody is already repeating
- contrarian_take: a defensible opposite or deeply overlooked angle that challenges the mainstream read
- assumptions_to_challenge: exactly 3 widely-held assumptions this story should force us to re-examine
- questions: exactly 6 questions that put the listener's brain to work — NOT obvious FAQs.
  Each question must reveal a hidden contradiction, a second-order consequence, or an uncomfortable
  implication the listener has not considered yet. Make them specific to this story, not generic.

Return ONLY JSON:
{{"core_claim": "...",
  "contrarian_take": "...",
  "assumptions_to_challenge": ["assumption 1", "assumption 2", "assumption 3"],
  "questions": ["question 1", "question 2", "question 3", "question 4", "question 5", "question 6"]}}"""
    try:
        return extract_json(await chat([{"role": "user", "content": prompt}],
                                       response_format={"type": "json_object"}, max_tokens=1500))
    except Exception:
        return {"core_claim": "", "contrarian_take": "", "assumptions_to_challenge": [], "questions": []}


async def deep_research(chat, topic: str, angles: dict) -> str:
    qs = "\n".join(f"- {q}" for q in angles.get("questions", []))
    if not qs and not angles.get("contrarian_take"):
        return ""
    return await chat([{"role": "user", "content":
        f"Topic: {topic or 'today news'}\nAnswer each question below with concrete, verifiable facts and numbers "
        f"(say when something is unknown), then give evidence FOR and AGAINST this contrarian take: "
        f"\"{angles.get('contrarian_take', '')}\".\nQuestions:\n{qs}"}],
        server_tools=["web_search"], max_tokens=2500)


async def make_script(chat, notes: str, angles: dict, deep: str, n: int, topic: str,
                      uber_story: str = "") -> dict:
    uber_line = (f"\nOVERARCHING NARRATIVE — use this as the spine of the entire episode, "
                 f"return to it in hook and verdict:\n{uber_story}\n" if uber_story else "")
    prompt = f"""{PERSONA}

{HINGLISH_RULES}

Write a {n}-segment solo podcast episode (first person, one listener) about: {topic or "today's top news"}.
{uber_line}
Editorial material (use ONLY these facts):
RESEARCH NOTES:
{notes}

THE STORY EVERYBODY REPEATS: {angles.get('core_claim', '')}
YOUR CONTRARIAN TAKE: {angles.get('contrarian_take', '')}
ASSUMPTIONS TO CHALLENGE: {json.dumps(angles.get('assumptions_to_challenge', []), ensure_ascii=False)}
BRAIN-WORK QUESTIONS (use these to make the listener think, not just listen):
{json.dumps(angles.get('questions', []), ensure_ascii=False)}
DEEPER ANSWERS:
{deep}

Episode arc, spread in this order across the {n} segments:
1. HOOK: a sensational but true claim or a provocative question in the first sentence; promise what they will learn.
2. CONTEXT: what actually happened, fast.
3. THE CATCH: challenge the popular story, dissect it with logic and numbers, show what most people miss.
4. THE QUESTIONS: for each brain-work question above, raise it out loud BEFORE answering ("Lekin sawaal ye hai ki...",
   "Sochiye — agar ye sach hai toh..."). Make the listener feel like they discovered the answer themselves.
5. OTHER SIDE: steelman the opposite view, then say where you land and why.
6. COMMENT MOMENT: ask ONE specific, uncomfortable question and invite the listener to answer in comments.
7. VERDICT: crisp takeaway that ties back to the overarching narrative. End with one open question.
Merge or skip arc steps if there are few segments; keep hook first, comment invitation, and verdict last.

Each segment narration: 5-7 sentences, every sentence moves the story forward.
After the hook opening sentence and before major topic transitions insert [pause:0.8s] — max 2 per segment,
end of a complete sentence only, never mid-sentence.

Return ONLY valid JSON:
{{"title": "catchy Hinglish title (max 70 chars)", "description": "2-line English YouTube description",
  "segments": [{{"id": 1, "role": "hook|context|catch|questions|other_side|comment|verdict",
                 "narration": "...", "emotion": "calm|excited|serious|dramatic|concerned|amused"}}]}}
Exactly {n} segments."""
    return extract_json(await chat([{"role": "user", "content": prompt}],
                                   response_format={"type": "json_object"}, max_tokens=6000))


_EN_FUNC = {"the", "is", "are", "was", "were", "of", "in", "to", "and", "have", "has", "that", "this", "for", "with",
            "from", "let's", "it", "an", "be", "by", "on", "at", "you", "your", "we", "they", "can", "will", "would",
            "should", "not", "but", "or", "as", "if", "when", "what", "how", "why", "so", "all", "also", "just"}


_HI_FUNC = set("""hai hain ho hoga hogi honge tha thi ka ki ke ko mein se par pe aur ya ye yeh wo woh hum hume humein
main mujhe mera meri aap aapko aapka tum nahi na kya kyun kyunki lekin magar toh bhi hi jab tab jo jise ek kuch sab bas abhi
ab phir agar taaki sirf raha rahi rahe karta karti karte kar kiya gaya gayi diya liya sakta sakte sakti chahiye wahan yahan
kaise kitna itna jaisa tarah wajah baat log unka uska iska isliye jaise kaun kahan""".split())


def english_heavy(sentence: str) -> bool:
    """True when a Hinglish sentence contains a real English clause (many English function words, or a 4+ word
    comma-separated clause with no Hindi word in it)."""
    words = re.findall(r"[A-Za-z']+", sentence.lower())
    if sum(w in _EN_FUNC for w in words) >= 3:
        return True
    for clause in re.split(r"[,;:]", sentence):
        cw = re.findall(r"[A-Za-z']+", clause.lower())
        if len(cw) >= 4 and not any(w in _HI_FUNC for w in cw):
            return True
    return False


async def purge_english(chat, narration: str) -> str:
    """Rewrite any sentence that is mostly English into Hinglish with Hindi grammar, keeping the meaning."""
    parts = [x.strip() for x in re.findall(r"[^.?!]+[.?!]*", narration) if x.strip()]
    out = []
    for p in parts:
        for _ in range(3):
            if not english_heavy(p):
                break
            try:
                p = (await chat([{"role": "user", "content":
                    "TRANSLATE this sentence into conversational Hindi written in Roman letters (Hinglish). Use Hindi grammar and "
                    "Hindi verbs; keep only single English nouns/terms such as gold, stock, dollar, risk. "
                    "Example: 'Gold is a lazy asset that just sits there.' -> 'Gold ek lazy asset hai jo bas baitha rehta hai.' "
                    "Keep the meaning and the first-person voice, one sentence, no English clause left.\nSentence: " + p +
                    "\nReturn ONLY the Hinglish sentence."}],
                    max_tokens=1500, temperature=0.3)).strip().strip('"') or p
            except Exception:
                pass
        out.append(p)
    return " ".join(out)


# ── timing: split narration into beats, one image per beat ────────────────────

def _units(text: str, need: int) -> list[str]:
    """Sentence-ish units; split at commas / dashes too if we need more pieces than sentences."""
    units = [u.strip() for u in re.findall(r"[^।.?!]+[।.?!]*", text) if u.strip()]
    if len(units) < need:
        units = [p.strip() for u in units for p in re.findall(r"[^,;:—–]+[,;:—–]*", u) if p.strip()]
    while len(units) < need:                         # still short: split longest on spaces
        i = max(range(len(units)), key=lambda j: len(units[j]))
        w = units[i].split()
        if len(w) < 2:
            break
        units[i:i + 1] = [" ".join(w[:len(w) // 2]), " ".join(w[len(w) // 2:])]
    return units


_MIN_BEAT_WORDS = 6


def split_beats(text: str, k: int) -> list[str]:
    units = _units(text, k)
    k = min(k, len(units))
    total = sum(len(u) for u in units)
    beats, cur, acc = [], [], 0
    for idx, u in enumerate(units):
        cur.append(u)
        acc += len(u)
        left_units = len(units) - idx - 1
        left_beats = k - len(beats) - 1
        if left_beats > 0 and (acc >= total * (len(beats) + 1) / k or left_units == left_beats):
            beats.append(" ".join(cur))
            cur = []
    if cur:
        beats.append(" ".join(cur))
    # merge fragment beats (transition words, incomplete sentences) into neighbours
    merged: list[str] = []
    for b in beats:
        if merged and len(b.split()) < _MIN_BEAT_WORDS:
            merged[-1] += " " + b
        else:
            merged.append(b)
    if len(merged) > 1 and len(merged[-1].split()) < _MIN_BEAT_WORDS:
        merged[-2] += " " + merged.pop()
    return merged


def beat_durations(beats: list[str], seg_dur: float) -> list[float]:
    """Shot length follows how much is said in the beat, clamped into SHOT_MIN..SHOT_MAX (falls back to equal)."""
    n = len(beats)
    w = [max(1, len(b)) for b in beats]
    d = [seg_dur * x / sum(w) for x in w]
    if all(config.SHOT_MIN <= x <= config.SHOT_MAX for x in d):
        return d
    return [seg_dur / n] * n


def choose_shot_count(dur: float) -> int:
    return max(1, math.ceil(dur / config.SHOT_MAX), round(dur / config.SHOT_TARGET))


