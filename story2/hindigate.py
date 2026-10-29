"""The automatic Hindi gate (docs/TASKS_quality_overhaul.md task 2.9): no person reads the Hindi before a film is made, so each part of the narration is checked by two
model calls and a few rules in code.

  1. BACK-TRANSLATION  the part is translated to literal English, then a judge compares that English with the details the part must tell: a detail that is missing or says
                       something else in the translation means the Hindi lost or changed a fact;
  2. NATURALNESS       the same judge call lists sentences that sound translated or stiff, too many English words, wrong gender for a male narrator, and the same sentence shape.
  
The result is `{ok, issues, missing, contradicted}`. A part that fails goes back to the editor pass once with the issues named; the final result is stored on the segment as
issues of kind `hindi_gate`, which the audit counts (and which task 8.3 turns into a stop)."""
import re

from story import llm
from story.schemas import Str, StrList

from . import prompts as P
from .schemas import M


class Stiff(M):
    start: Str = ""
    why: Str = ""


class JudgeOut(M):
    missing: StrList = []
    contradicted: StrList = []
    stiff: list[Stiff] = []
    english_heavy: bool = False
    gender_wrong: bool = False
    samey: bool = False


def _details(items: list[dict]) -> str:
    return "\n".join(f"{it['id']}: {it['detail']}" for it in items)


async def check(sentences: list[str], items: list[dict], profile: str, backend, s: dict) -> dict:
    """The gate result for one part. A model failure never stops the film: the part is then reported as unchecked (`ok` true, `unchecked` true)."""
    text = " ".join(sentences)
    try:
        english = (await llm.TextCaller(backend, s).call(P.BACKTRANSLATE, text)).value
        verdict = (await llm.JsonCaller(backend, s).call(P.JUDGE_HINDI, f"HINDI TEXT:\n{text}\n\nLITERAL ENGLISH:\n{english}\n\nDETAILS THE PART MUST TELL:\n{_details(items)}", JudgeOut)).value
    except llm.LLMError:
        return {"ok": True, "unchecked": True, "issues": [], "missing": [], "contradicted": []}
    known = {it["id"] for it in items}
    missing = [x for x in verdict.missing if x in known]
    contradicted = [x for x in verdict.contradicted if x in known]
    issues = []
    if contradicted:
        issues.append("these details are told differently from the story material (check numbers, names, places, order): " + ", ".join(contradicted))
    if missing and len(missing) > max(1, len(items) // 3):
        issues.append("the Hindi leaves out these details: " + ", ".join(missing))
    for st in verdict.stiff[:3]:
        issues.append(f"sounds translated or stiff ({st.start[:40]}): {st.why}")
    if verdict.english_heavy:
        issues.append("too many English words; use the Hindi word wherever a Hindi speaker would")
    if verdict.gender_wrong:
        issues.append("the narrator is a man: use masculine verb forms for himself (मैं गया, मैंने देखा)")
    if verdict.samey:
        issues.append("most sentences have the same shape; vary the length and the way they begin")
    return {"ok": not issues, "unchecked": False, "issues": issues, "missing": missing, "contradicted": contradicted}


def as_issues(gate: dict) -> list[dict]:
    """The stored form: one issue per finding, kind `hindi_gate` (an empty list when the part passed or could not be checked)."""
    if gate.get("ok"):
        return []
    return [{"where": "", "kind": "hindi_gate", "level": "warn", "text": t, "detail": "the Hindi gate still found this after the editor's second try"} for t in gate["issues"]]
