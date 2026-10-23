"""Token estimation and the context-budget manager.

There is no tokenizer endpoint on the gateway, so tokens are estimated from characters. The safety margin
absorbs the estimation error; real `usage` numbers from responses are logged when the server returns them.
"""
from dataclasses import dataclass

DEFAULT_CPT = 3.5            # chars per token for latin-script text
NON_LATIN_CPT = 1.6          # devanagari, CJK etc. tokenise far worse


def estimate(text: str, cpt: float = DEFAULT_CPT) -> int:
    if not text:
        return 0
    non_ascii = sum(1 for c in text if ord(c) > 127) / len(text)
    return int(len(text) / (cpt if non_ascii < 0.3 else min(cpt, NON_LATIN_CPT))) + 1


class BudgetExceeded(Exception):
    pass


@dataclass(frozen=True)
class Budget:
    context: int = 32768
    output_reserve: int = 6000
    safety: float = 0.10
    cpt: float = DEFAULT_CPT

    @classmethod
    def from_settings(cls, s: dict) -> "Budget":
        return cls(int(s["context_limit"]), int(s["output_reserve"]), float(s["safety_margin"]),
                   float(s["chars_per_token"]))

    def est(self, text: str) -> int:
        return estimate(text, self.cpt)

    @property
    def usable(self) -> int:
        """Tokens of the window we allow ourselves to fill (input + reserved output)."""
        return int(self.context * (1 - self.safety))

    def input_limit(self, instruction_tokens: int = 0) -> int:
        """Max tokens of variable input once instructions and the output reserve are accounted for."""
        return max(0, self.usable - self.output_reserve - instruction_tokens)

    def check(self, input_tokens: int) -> None:
        if input_tokens + self.output_reserve > self.usable:
            raise BudgetExceeded(
                f"request needs ~{input_tokens} input + {self.output_reserve} output tokens, "
                f"but only {self.usable} of the {self.context}-token window is usable "
                f"(safety margin {self.safety:.0%}). Raise the context limit or lower chunk size.")

    def chunk_target(self, configured: int, instruction_tokens: int) -> int:
        """Source tokens per chunk: the configured size, clamped so the whole request still fits."""
        return max(200, min(configured, self.input_limit(instruction_tokens)))

    def warnings(self, configured_chunk: int, instruction_tokens: int) -> list[str]:
        out = []
        if self.output_reserve >= self.usable * 0.6:
            out.append("Output reserve is over 60% of the usable window; little room is left for input.")
        if configured_chunk > self.input_limit(instruction_tokens):
            out.append(f"Chunk size {configured_chunk} does not fit; "
                       f"it will be reduced to {self.chunk_target(configured_chunk, instruction_tokens)} tokens.")
        return out


def pack(items: list[int], limit: int) -> list[list[int]]:
    """Greedily group consecutive items (given as token sizes) into groups of at most `limit` tokens.
    An item larger than `limit` raises BudgetExceeded rather than being truncated."""
    groups: list[list[int]] = []
    cur: list[int] = []
    used = 0
    for i, size in enumerate(items):
        if size > limit:
            raise BudgetExceeded(f"single item of ~{size} tokens exceeds the available input budget of {limit}")
        if cur and used + size > limit:
            groups.append(cur)
            cur, used = [], 0
        cur.append(i)
        used += size
    if cur:
        groups.append(cur)
    return groups
