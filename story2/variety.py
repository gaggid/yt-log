"""The anti-template engine (docs/TASKS_quality_overhaul.md task 7.6; audit 14.3 and the YouTube July 2026 policy on repetitive, template-made content). Every film gets a
signature, chosen to differ from the last films of the channel: a colour palette, a lens feel, the form of the opening, a family of music pads, the form of the structure and a caption
accent colour. The thumbnail frame and the logo stay fixed (a series look); everything else changes from film to film.

`choose` picks the signature for a plan from the signatures of the previous plans, `distance` says how different two signatures are, and the audit reports the difference from the
last five films. The signature lives in `plan.settings.signature`, outside the content hash."""
import hashlib

from story import db

PALETTES = ("warm amber and teal", "cool blue and brass", "faded green and rust", "dusty rose and slate", "ochre and deep indigo", "silver grey and red accent", "sunlit yellow and navy")
LENSES = ("wide lens with deep focus", "standard lens, natural depth", "long lens with soft background", "slightly wide, handheld feel")
OPENINGS = ("cold_open", "question", "object")
STRUCTURES = ("mystery", "countdown", "two_timeline", "case_file", "what_would_you_do")
MUSIC = (0, 1, 2, 3)                              # index of the pad root cycle in story3/audio.py
ACCENTS = ("E6AA50", "60A8B0", "D98C6B", "9CC47C", "C58BD0", "E0D060")                # caption accent, as RGB hex
FIELDS = ("palette", "lens", "opening", "music", "structure", "accent")
RECENT = 5


def previous(exclude: str = "", n: int = RECENT) -> list[dict]:
    rows = db.q("SELECT id, settings FROM plans ORDER BY created_at DESC LIMIT ?", (n + 1,))
    out = []
    for r in rows:
        if r["id"] == exclude:
            continue
        sig = (db.jload(r["settings"], {}) or {}).get("signature")
        if sig:
            out.append(sig)
    return out[:n]


def distance(a: dict, b: dict) -> int:
    """How many of the signature fields differ (0 to 6)."""
    return sum(1 for f in FIELDS if a.get(f) != b.get(f))


def choose(plan_id: str, forced: dict | None = None) -> dict:
    """The signature for a plan: the candidate (out of a deterministic stream seeded by the plan id) that is furthest from the recent films, fewest repeats first. The same plan
    always gets the same signature."""
    recent = previous(plan_id)
    best, best_key = None, None
    for k in range(40):
        h = int(hashlib.sha1(f"{plan_id}:{k}".encode()).hexdigest(), 16)
        cand = {"palette": PALETTES[h % len(PALETTES)], "lens": LENSES[(h >> 8) % len(LENSES)], "opening": OPENINGS[(h >> 16) % len(OPENINGS)], "music": MUSIC[(h >> 20) % len(MUSIC)],
                "structure": STRUCTURES[(h >> 24) % len(STRUCTURES)], "accent": ACCENTS[(h >> 28) % len(ACCENTS)]}
        cand.update(forced or {})
        worst = min((distance(cand, r) for r in recent), default=len(FIELDS))                  # the closest recent film
        total = sum(distance(cand, r) for r in recent)
        key = (worst, total)
        if best_key is None or key > best_key:
            best, best_key = cand, key
        if worst >= 3 and k >= 5:
            break
    return best


def assign(plan_id: str) -> dict:
    """Write the signature to the plan unless it has one (an editor's choice or an earlier run stays)."""
    from . import planner
    plan = planner.get_plan(plan_id)
    if plan["settings"].get("signature"):
        return plan["settings"]["signature"]
    sig = choose(plan_id)
    db.ex("UPDATE plans SET settings=?, updated_at=? WHERE id=?", (db.jdump({**plan["settings"], "signature": sig}), db.now(), plan_id))
    return sig


def look_words(sig: dict | None) -> str:
    """One sentence for the picture prompts: the palette and lens of this film."""
    if not sig:
        return ""
    return f"colour palette of {sig['palette']}; {sig['lens']}"
