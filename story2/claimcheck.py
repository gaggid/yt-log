"""The claim check between packaging and content (docs/TASKS_quality_overhaul.md task 6.5; audit section 2: a title that said 2007 over a story that happened in 2012). A title, a
thumbnail headline or the first line of a description may only claim what the film itself says. Done in code, with no model: every number in the text must be among the numbers
of the narration, the story material or the facts, every name or place (a capitalised word) must be spelled in the narration, the material or the facts, and nothing may carry
a community, religion or caste term. It fails closed: a doubt is a finding."""
import re

COMMUNITY = re.compile(r"\b(hindu|muslim|sikh|christian|jain|buddhist|dalit|brahmin|rajput|jat|yadav|bania|adivasi|caste|community|upper caste|lower caste|shudra|kshatriya)\b"
                       r"|हिंदू|हिन्दू|मुस्लिम|सिख|ईसाई|दलित|ब्राह्मण|राजपूत|जाट|यादव|आदिवासी", re.I)
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
_NAME = re.compile(r"\b[A-Z][a-z]{2,}\b")
_SKIP = {"The", "This", "That", "What", "Why", "How", "Who", "When", "Where", "Did", "Was", "Were", "His", "Her", "Their", "And", "But", "For", "With", "From", "After", "Before",
         "Police", "Crore", "Lakh", "India", "Indian", "Hindi", "English"}


def _numbers(text: str) -> set[str]:
    return {m.group().replace(",", "").rstrip(".") for m in _NUM.finditer(text or "")}


def known_text(plan: dict) -> str:
    """Everything the film says or knows: the narration, the story material and the story's own facts."""
    from . import intake, material, planner
    parts = [s["plain"] for s in plan["segments"]]
    if material.has(plan):
        parts += [i.get("detail", "") + " " + i.get("where", "") + " " + i.get("who", "") for i in material.pack(plan)["items"]]
        parts += [n.get("name", "") for n in material.pack(plan).get("names", [])]
    try:
        parts.append(intake.facts_text(planner._story_for(plan)["public"]))
    except Exception:                                                              # noqa: BLE001 - facts are an extra source, not required
        pass
    return " ".join(parts)


def check(text: str, plan: dict) -> list[str]:
    """What in the text the film does not support, one sentence each (empty: the text is safe to publish)."""
    known = known_text(plan)
    low = known.lower()
    nums = _numbers(known)
    spoken_nums = nums | {n.lstrip("0") for n in nums}
    issues = []
    for n in sorted(_numbers(text)):
        if n not in spoken_nums and n.replace(".0", "") not in spoken_nums:
            spelled = _words_for(n)
            if not any(w in low for w in spelled):
                issues.append(f"the number {n} is not in the film or its details")
    starts = {m.group(1) for m in re.finditer(r"(?:^|[.?!]\s+)([A-Z][a-z]+)(?!\s+[A-Z][a-z])", text)}          # a capitalised first word of a sentence is a word, not a name (Aakhir, Why)
    for w in dict.fromkeys(_NAME.findall(text)):
        if w in _SKIP or w in starts:
            continue
        if w.lower() not in low:
            issues.append(f"the name {w} is not in the film or its details")
    m = COMMUNITY.search(text)
    if m:
        issues.append(f"a community or religion term ({m.group()}) in a title or headline can imply guilt by community")
    return issues


_SMALL = {"1": "one", "2": "two", "3": "three", "4": "four", "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine", "10": "ten", "12": "twelve", "20": "twenty", "30": "thirty",
          "35": "thirty-five", "100": "hundred", "1000": "thousand"}


def _words_for(n: str) -> list[str]:
    return [_SMALL[n]] if n in _SMALL else []
