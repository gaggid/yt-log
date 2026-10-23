"""Split a source into analysis chunks that respect the token budget and paragraph boundaries.

A chunk is a list of items (para_idx, start, end) - character slices of a paragraph (end=-1 means the whole
paragraph) - plus read-only context items carried over from the previous chunk. Every paragraph of the source
appears in exactly one chunk's main items, so nothing is dropped.
"""
import re
from dataclasses import dataclass, field

_SENT = re.compile(r"(?<=[.!?…])[\"')\]”’]*\s+")


@dataclass
class Chunk:
    items: list[tuple[int, int, int]]
    context: list[tuple[int, int, int]] = field(default_factory=list)
    chapter_idxs: list[int] = field(default_factory=list)
    tokens: int = 0


def _slices(text: str, max_chars: int) -> list[tuple[int, int]]:
    """Cut an oversized paragraph at sentence (then word) boundaries into pieces of at most max_chars."""
    if len(text) <= max_chars:
        return [(0, len(text))]
    cuts = []
    ends = [m.end() for m in _SENT.finditer(text)] + [len(text)]
    piece_start = 0
    last_end = 0
    for e in ends:
        if e - piece_start > max_chars and last_end > piece_start:
            cuts.append((piece_start, last_end))
            piece_start = last_end
        last_end = e
        while last_end - piece_start > max_chars:        # a single sentence longer than the limit
            w = text.rfind(" ", piece_start + 1, piece_start + max_chars)
            w = w if w > piece_start else piece_start + max_chars
            cuts.append((piece_start, w))
            piece_start = w
    if piece_start < len(text):
        cuts.append((piece_start, len(text)))
    return cuts


def build_chunks(paras: list[dict], target_tokens: int, overlap_tokens: int, est, min_fill: float = 0.35) -> list[Chunk]:
    """paras: [{idx, chapter_idx, text}] in source order. est: text -> token estimate.
    Chunks do not cross a chapter boundary unless the chunk so far is under `min_fill` of the target
    (tiny chapters are batched together)."""
    chunks: list[Chunk] = []
    cur: list[tuple[int, int, int]] = []
    cur_tok = 0
    cur_chs: list[int] = []
    sizes: dict[tuple[int, int, int], int] = {}
    max_chars = max(200, int(target_tokens * 3))            # conservative: well below target even for dense text

    def piece_tokens(p, a, b):
        return est(p["text"][a:b]) + 4                     # +4 for the paragraph label

    def flush():
        nonlocal cur, cur_tok, cur_chs
        if cur:
            chunks.append(Chunk(cur, [], cur_chs, cur_tok))
        cur, cur_tok, cur_chs = [], 0, []

    prev_ch = None
    for p in paras:
        if prev_ch is not None and p["chapter_idx"] != prev_ch and cur and cur_tok >= min_fill * target_tokens:
            flush()
        prev_ch = p["chapter_idx"]
        pieces = _slices(p["text"], max_chars)
        # tokens-aware re-cut if a piece is still over target (dense / non-latin text)
        fixed = []
        for a, b in pieces:
            while piece_tokens(p, a, b) > target_tokens and b - a > 50:
                mid = a + (b - a) // 2
                sp = p["text"].rfind(" ", a + 1, mid + 1)
                mid = sp if sp > a else mid
                fixed.append((a, mid))
                a = mid
            fixed.append((a, b))
        for a, b in fixed:
            t = piece_tokens(p, a, b)
            if cur and cur_tok + t > target_tokens:
                flush()
            item = (p["idx"], a, -1 if (a == 0 and b == len(p["text"])) else b)
            cur.append(item)
            sizes[item] = t
            cur_tok += t
            if p["chapter_idx"] not in cur_chs:
                cur_chs.append(p["chapter_idx"])
    flush()

    # read-only context: trailing items of the previous chunk, up to overlap_tokens, same chapter only
    if overlap_tokens > 0:
        chapter_of = {p["idx"]: p["chapter_idx"] for p in paras}
        for i in range(1, len(chunks)):
            first_ch = chapter_of[chunks[i].items[0][0]]
            ctx, used = [], 0
            for item in reversed(chunks[i - 1].items):
                if chapter_of[item[0]] != first_ch or used + sizes[item] > overlap_tokens:
                    break
                ctx.insert(0, item)
                used += sizes[item]
            chunks[i].context = ctx
            chunks[i].tokens += used
    return chunks


def split_chunk(items: list, context: list) -> tuple[list, list] | None:
    """Halve a chunk's items (used when the model reply is cut off). Returns None if it cannot be split."""
    if len(items) < 2:
        return None
    mid = len(items) // 2
    return items[:mid], items[mid:]
