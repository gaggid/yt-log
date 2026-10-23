"""Repair PDF text-extraction damage using the document's own vocabulary.

Two defects are fixed:
  * line-end hyphens: "long-\\nterm" must stay "long-term", but "inter-\\nesting" must become "interesting";
  * split letters / drop caps: "T he", "V olume", "Y ork" must be rejoined, while real words like "A few" stay.
Decisions come from words seen elsewhere in the same document, so nothing is guessed from a fixed dictionary.
"""
import re
from collections import Counter

# Prefixes that normally keep their hyphen when the second half is a word of its own.
COMPOUND_PREFIXES = {"long", "short", "well", "high", "low", "self", "non", "full", "part", "real", "cross", "multi",
                     "mid", "ex", "all", "half", "open", "close", "wide", "fast", "slow", "top", "end", "day", "high"}
_WORD = re.compile(r"[A-Za-z]+")
_BREAK = re.compile(r"([A-Za-z]+)-\n[ \t]*([A-Za-z]+)")
_HYPH = re.compile(r"\b[A-Za-z]+-[A-Za-z]+\b")
_SPLIT = re.compile(r"\b([A-Za-z]) ([a-z]{2,})\b")
_NOT_SPLIT = {"a", "i"}                                   # real one-letter words need extra proof before joining


class Vocab:
    def __init__(self, texts: list[str] | None = None):
        self.words: Counter[str] = Counter()
        self.hyph: Counter[str] = Counter()
        for t in texts or []:
            self.add(t)

    def add(self, text: str) -> None:
        body = _BREAK.sub(" ", text)                    # fragments split by a line break say nothing about real words
        self.words.update(w.lower() for w in _WORD.findall(body))
        self.hyph.update(h.lower() for h in _HYPH.findall(body))

    def join_break(self, a: str, b: str) -> str:
        """Text for a word split as `a-` / `b` at a line end."""
        if b[0].isupper():
            return f"{a}-{b}"
        if self.hyph[f"{a}-{b}".lower()]:
            return f"{a}-{b}"
        if self.words[(a + b).lower()]:
            return a + b
        if a.lower() in COMPOUND_PREFIXES and self.words[b.lower()] >= 2:
            return f"{a}-{b}"
        return a + b

    def fix_breaks(self, text: str) -> str:
        return _BREAK.sub(lambda m: self.join_break(m.group(1), m.group(2)), text)

    def fix_split_letters(self, text: str) -> str:
        def sub(m: re.Match) -> str:
            letter, rest = m.group(1), m.group(2)
            joined = (letter + rest).lower()
            seen = self.words[joined]
            if not seen:
                return m.group(0)
            if letter.lower() in _NOT_SPLIT and (self.words[rest.lower()] >= 3 or seen < 2):
                return m.group(0)                        # "A few", "I did": keep unless the rest is not a word here
            return letter + rest
        return _SPLIT.sub(sub, text)

    def clean(self, text: str) -> str:
        return self.fix_split_letters(self.fix_breaks(text))
