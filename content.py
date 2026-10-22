"""Editorial steps: research -> angles/questions -> deeper research -> persona script -> beats -> scene plan.
`chat` is an async callable chat(messages, **kwargs) -> str supplied by main.py."""
import json
import math
import re

import config

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


async def research(chat, topic: str) -> str:
    query = topic or "India top news stories today"
    return await chat([{"role": "user", "content":
        f"Research and summarize the latest news about: {query}. "
        "Find 6-8 key stories with facts, numbers, context and quotes. Be thorough."}],
        server_tools=["web_search"], max_tokens=2500)


async def find_angles(chat, notes: str) -> dict:
    prompt = f"""You are a sharp, sceptical analyst preparing a podcast. Read the research notes and find what makes the topic
interesting and arguable.

Notes:
{notes}

Return ONLY JSON:
{{"core_claim": "the one-line story everybody is repeating",
  "contrarian_take": "a defensible opposite or overlooked angle",
  "assumptions_to_challenge": ["...", "...", "..."],
  "questions": ["6 specific questions a curious viewer will ask while listening, each answerable with facts"]}}"""
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


async def make_script(chat, notes: str, angles: dict, deep: str, n: int, topic: str) -> dict:
    prompt = f"""{PERSONA}

{HINGLISH_RULES}

Write a {n}-segment solo podcast episode (first person, one listener) about: {topic or "today's top news"}.

Editorial material (use ONLY these facts):
RESEARCH NOTES:
{notes}

THE STORY EVERYBODY REPEATS: {angles.get('core_claim', '')}
YOUR CONTRARIAN TAKE: {angles.get('contrarian_take', '')}
ASSUMPTIONS TO CHALLENGE: {json.dumps(angles.get('assumptions_to_challenge', []), ensure_ascii=False)}
QUESTIONS THE LISTENER WILL ASK: {json.dumps(angles.get('questions', []), ensure_ascii=False)}
DEEPER ANSWERS:
{deep}

Episode arc, spread in this order across the {n} segments:
1. HOOK: a sensational but true claim or a provocative question in the first sentence; promise what they will learn.
2. CONTEXT: what actually happened, fast.
3. THE CATCH: challenge the popular story, dissect it with logic and numbers, show what most people miss.
4. THE QUESTIONS: raise the listener's likely questions out loud and answer them with the deeper facts.
5. OTHER SIDE: steelman the opposite view, then say where you land and why.
6. COMMENT MOMENT (one segment around the middle-to-late part): ask a specific question and invite the listener to
   write their view in the comments, personally ("aap kya sochte ho? comment mein likho").
7. VERDICT: a crisp takeaway and one last open question for the comments.
Merge or skip arc steps if there are few segments, but keep the hook first, the comment invitation, and the verdict last.

Each segment narration: 5-7 sentences, every sentence moves the story forward. Keep a consistent voice across segments.
After the hook opening sentence and before major topic transitions insert [pause:0.8s] — max 2 per segment, end of a
complete sentence only, never mid-sentence.

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
    return beats


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


