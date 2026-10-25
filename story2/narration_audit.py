"""A fixed rubric for a plan's narration, so two runs can be compared number by number: how it opens, how much it asks, how flat the voice is, how often it repeats
itself, and whether it keeps to the language rules. Pure text work: no model is called. `python -m story2.narration_audit plan.json [plan2.json ...]` prints a table."""
import json
import re
import sys

from . import planner, svara

STOCK = planner.STOCK_OPENERS
DEV = re.compile(r"[ऀ-ॿ]")
LAT = re.compile(r"[A-Za-z]")


def _sentences(plan: dict) -> list[tuple[int, dict]]:
    segs = sorted(plan["segments"], key=lambda s: s["seq"])
    return [(i, s) for i, g in enumerate(segs) for s in g["sentences"]]


def audit(plan: dict) -> dict:
    rows = _sentences(plan)
    texts = [s["text"] for _, s in rows]
    n = max(1, len(texts))
    words = [len(t.split()) for t in texts]
    emo = {}
    for _, s in rows:
        emo[s["emotion"]] = emo.get(s["emotion"], 0) + 1
    segs = sorted(plan["segments"], key=lambda s: s["seq"])
    flips = sum(max(0, len({x["emotion"] for x in g["sentences"]}) - 1) for g in segs)
    ends_q = sum(1 for g in segs if g["sentences"] and ("?" in g["sentences"][-1]["text"] or "क्या" in g["sentences"][-1]["text"]))
    letters = sum(len(DEV.findall(t)) for t in texts)
    latin = sum(len(LAT.findall(t)) for t in texts)
    first = texts[0] if texts else ""
    return {
        "beats": len(segs), "sentences": len(texts), "seconds": round(sum(g["duration_s"] for g in segs)),
        "first_sentence_words": len(first.split()), "first_sentence": first,
        "questions": sum(1 for t in texts if "?" in t), "beats_ending_on_a_question": ends_q,
        "flat_share": round((emo.get("neutral", 0) + emo.get("clear", 0)) / n, 2), "emotions": emo, "emotion_flips_inside_a_beat": flips,
        "happy_share": round(emo.get("happy", 0) / n, 2),
        "repeated_sentences": len(planner.repeated_sentences([], texts, 0.6)), "overused_openers": planner.overused_openers([], texts),
        "stock_phrases": sum(1 for t in texts for s in STOCK if t.startswith(s)),
        "romanised_hindi_sentences": sum(1 for t in texts if svara.romanised_hindi(t)),
        "i_statements": sum(1 for t in texts if "मैं" in t or "मुझे" in t), "talks_to_viewer": sum(1 for t in texts if "आप" in t),
        "avg_words": round(sum(words) / n, 1), "short_sentences_share": round(sum(1 for w in words if w <= 6) / n, 2),
        "long_sentences_share": round(sum(1 for w in words if w >= 22) / n, 2),
        "devanagari_share": round(letters / max(1, letters + latin), 2),
        "digits_in_text": sum(1 for t in texts if re.search(r"\d", t)),
        "suspense_plan": bool((plan.get("blueprint") or {}).get("cold_open")),
    }


def table(named: list[tuple[str, dict]]) -> str:
    keys = [k for k in named[0][1] if k not in ("first_sentence", "emotions")]
    out = ["| measure | " + " | ".join(n for n, _ in named) + " |", "|---|" + "---|" * len(named)]
    for k in keys:
        out.append(f"| {k} | " + " | ".join(str(a[k]) for _, a in named) + " |")
    return "\n".join(out)


if __name__ == "__main__":
    plans = [(p.rsplit("\\", 1)[-1].rsplit("/", 1)[-1], audit(json.load(open(p, encoding="utf-8")))) for p in sys.argv[1:]]
    print(table(plans))
    for n, a in plans:
        print(f"\n{n} opens: {a['first_sentence']}  | emotions: {a['emotions']}")
