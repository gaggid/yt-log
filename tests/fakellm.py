"""Deterministic stand-in for the model: routes on the [TASK:..] tag and builds replies from the prompt text."""
import json
import re

from story.llm import LLMError, LLMResult
from story.tokens import estimate


class FakeBackend:
    def __init__(self, fail_after=None, bad_json=None, truncate_over=None, always_bad=None, discover_limit=None, nature="story"):
        self.calls: list[dict] = []
        self.fail_after = fail_after          # raise LLMError once this many calls have been made
        self.bad_json = dict(bad_json or {})  # task -> number of garbage replies before a good one
        self.truncate_over = truncate_over    # analyze: reply "length" if more than N paragraphs in MAIN TEXT
        self.always_bad = set(always_bad or [])
        self.discover_limit = discover_limit  # discover: shortlist only the first N seeds per call
        self.nature = nature

    def count(self, task):
        return sum(1 for c in self.calls if c["task"] == task)

    async def complete(self, messages, max_tokens):
        system = messages[0]["content"]
        user = "\n".join(m["content"] for m in messages[1:] if m["role"] == "user")
        task = re.match(r"\[TASK:(\w+)\]", system).group(1)
        self.calls.append({"task": task, "tokens": sum(estimate(m["content"]) for m in messages), "max_tokens": max_tokens,
                           "user": user})
        if self.fail_after is not None and len(self.calls) > self.fail_after:
            raise LLMError("simulated outage")
        if task in self.always_bad:
            return LLMResult("this is not json")
        if self.bad_json.get(task, 0) > 0:
            self.bad_json[task] -= 1
            return LLMResult("Sure! here you go: {not valid")
        if task == "p2_judge_narration":                  # the order is swapped on the second ask, so a fixed answer is a split decision: the first version stays
            return LLMResult(json.dumps({"winner": "A", "reason": "test"}))
        if task == "p2_devanagari":
            return LLMResult(user)
        if task == "p2_title":
            return LLMResult(json.dumps({"options": [{"title": "Aakhir kya hua us raat?", "kind": "hinglish", "why": "question"}, {"title": "आखिर उस रात क्या हुआ?", "kind": "hindi", "why": "question"},
                                                     {"title": "What happened that night?", "kind": "english", "why": "question"}]}))
        if task == "p2_subs_en":
            ns = re.findall(r"^(\d+)\. ", user, re.M)
            return LLMResult(json.dumps({"lines": [{"n": int(n), "text": f"English line {n}"} for n in ns]}))
        if task.startswith("p2_rate_"):
            keys = "concrete natural tone payoff variety moment world accuracy curiosity specific honest focus emotion legible".split()
            return LLMResult(json.dumps({"scores": [{"key": k, "score": 4 if k != "variety" else 2, "reason": f"reason for {k}"} for k in keys]}))
        if task == "p2_judge_persona":
            return LLMResult(json.dumps({"answer": {"would_click": True, "click": "the title is clear", "would_leave": "Sunil" in user, "leave_at": "1:30", "leave_why": "slow", "not_understood": "",
                                                    "unfair": "", "share": "with family"}}))
        if task == "p2_backtranslate":
            return LLMResult("English text of the part.")
        if task == "p2_judge_hindi":
            return LLMResult(json.dumps({"missing": [], "contradicted": [], "stiff": [], "english_heavy": False, "gender_wrong": False, "samey": False}))
        if task == "p2_voice_tags":                       # the first sentence of a segment is curious, the rest plain
            n = len(re.findall(r"^\d+\. ", user.split("THE SEGMENT")[-1], re.M))
            return LLMResult(json.dumps({"sentences": [{"n": i, "tag": "curious" if i == 1 else "neutral", "why": "test"} for i in range(1, n + 1)]}))
        main = user.split("CONTEXT (end of")[0]
        if task == "analyze_chunk":
            ids = [int(i) for i in re.findall(r"\[P(\d+)\]", main)]
            if self.truncate_over and len(ids) > self.truncate_over:
                return LLMResult('{"summary": "cut', finish_reason="length")
            out = {"summary": f"Summary of paragraphs {ids[0]} to {ids[-1]} with names and dates preserved.",
                   "events": [{"what": f"Event at {ids[0]}", "when": "1901", "who": ["Ada"], "para_ids": [ids[0], 9999]}],
                   "entities": [{"name": "Ada", "role": "engineer", "para_ids": [ids[0]]}],
                   "facts": [{"claim": f"Fact {ids[-1]}", "caveat": "", "para_ids": [f"P{ids[-1]}"]}],
                   "open_questions": ["Why?"],
                   "story_seeds": [{"title": f"Seed s{ids[0]}x", "premise": "Something happened.", "para_ids": ids[:3]},
                                   {"title": "Ghost", "premise": "cites nothing real", "para_ids": [123456]}]}
            return LLMResult(json.dumps(out))
        if task == "chapter_rollup":
            return LLMResult(json.dumps({"summary": "Consolidated chapter summary keeping all the key events.",
                                         "themes": ["theme"], "threads": ["thread"]}))
        if task == "book_index":
            chs = [int(c) for c in re.findall(r"CHAPTER (\d+):", user)]
            return LLMResult(json.dumps({"overview": "Overview of the whole source with its arc and people.",
                                         "themes": ["t"], "threads": [{"title": "Arc", "description": "d", "chapter_idxs": chs[:2] + [999]}]}))
        if task == "discover":
            seeds = user.split("Story seeds noticed:")
            cands = []
            for part in seeds[1:]:
                m = re.match(r"\s*- \[([P\d,]+)\] ([^:]+): ", part)
                if m:
                    ids = [int(x) for x in re.findall(r"P(\d+)", m.group(1))]
                    cands.append({"title": m.group(2), "premise": "A premise.", "why": "because", "kind": "incident", "nature": self.nature,
                                  "potential": 6, "para_ids": ids})
            return LLMResult(json.dumps({"candidates": cands[:self.discover_limit] if self.discover_limit is not None else cands}))
        if task == "discover_global":
            ids = re.findall(r"\[((?:P\d+,?)+)\]", user.split("STORIES ALREADY FOUND")[1])
            flat = [int(x) for g in ids[:3] for x in re.findall(r"P(\d+)", g)]
            c = [{"title": "Cross chapter saga", "premise": "Spans several chapters.", "why": "w", "kind": "multi_chapter",
                  "potential": 9, "para_ids": flat}] if flat else []
            return LLMResult(json.dumps({"candidates": c}))
        if task == "draft_story":
            raw = re.findall(r"^\[P(\d+)\] (.+)$", user.split("RAW PASSAGES:")[1].split("NOTES (")[0].split("BACKGROUND")[0], re.M)
            pid, text = int(raw[0][0]), raw[0][1]
            lead = re.search(r"STORY LEAD: (.+)", user).group(1).strip()
            quote = " ".join(text.split()[:6])
            f = lambda s: {"score": s, "reason": "because"}  # noqa: E731
            return LLMResult(json.dumps({
                "title": lead, "premise": "Premise sentence.", "nature": self.nature, "arc": {"actor": "Ada", "decision": "acted", "consequence": "it changed", "form": "event"}, "curiosity_question": "What happened?",
                "opening_hook": "A hook.", "overview": "A factual overview of the events described.",
                "people": [{"name": "Ada", "role": "engineer"}], "chronology": [{"when": "1901 [P%d]" % pid, "what": "It began [P%d]" % pid, "para_ids": [pid]}],
                "conflict": "", "stakes": "high", "turning_point": "", "outcome": "",
                "audience_interest": "curious", "context_needed": ["background"],
                "claims": [{"claim": "Something is true", "basis": "quoted", "quote": quote, "para_ids": [pid], "support": "strong"},
                           {"claim": "Invented quote claim", "basis": "quoted", "quote": "words that never appear anywhere here", "para_ids": [pid]}],
                "uncertainties": ["one source"], "research_questions": ["check dates"],
                "scores": {"hook": f(8), "narrative": f(7), "payoff": f(6), "emotion": f(5), "standalone": f(9)},
                "evidence": f(8)}))
        raise AssertionError(f"unexpected task {task}")
