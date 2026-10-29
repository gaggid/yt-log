"""The Material Pack (docs/AUDIT_2026-10-29.md sections 3.1 and 14.2; task 2.1): 30 to 40 concrete, paraphrased details of the story, found in its source passages, so the
blueprint, the narration and the storyboard work from real material and not from a 350-word summary.

The source passages are read here and nowhere else. What leaves this module is the writer's own list, checked by the leak gate: no wording, author, title or source reference
of the source is carried forward (owner rule), and the owner's decision of 2026-10-29 allows paraphrased facts."""
import difflib
import re
import uuid
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, field_validator

from story import db, llm, settings as settings_mod
from story.schemas import Str, StrList

from . import intake, leak, lexicon, planner, prompts as P, safety, store

KINDS = ("action", "object", "place", "person", "number", "sensory", "irony", "cause", "clue", "aftermath")
MIN_ITEMS = 12
MAX_ITEMS = 60
MAX_PASSAGE_CHARS = 60000
NEEDS = {"object": 4, "place": 3, "action": 4}                       # the least a pack must hold of each kind; asked for again once when short


def _kind(v) -> str:
    v = re.sub(r"[^a-z]", "", str(v or "").lower())
    alias = {"detail": "action", "event": "action", "thing": "object", "location": "place", "setting": "place", "character": "person", "figure": "number", "statistic": "number",
             "reversal": "irony", "twist": "irony", "result": "aftermath", "outcome": "aftermath", "evidence": "clue", "reason": "cause", "senses": "sensory"}
    v = alias.get(v, v)
    return v if v in KINDS else "action"


def _level(v) -> int:
    try:
        return max(0, min(3, int(round(float(v)))))
    except (TypeError, ValueError):
        return 1


def _bool(v) -> bool:
    return v if isinstance(v, bool) else str(v).strip().lower() in ("true", "yes", "1")


class M(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Item(M):
    kind: Annotated[str, BeforeValidator(_kind)] = "action"
    detail: Str
    when: Str = ""
    where: Str = ""
    who: Str = ""
    basis: Str = "stated"
    alleged: Annotated[bool, BeforeValidator(_bool)] = False
    visual: Annotated[int, BeforeValidator(_level)] = 1
    weight: Annotated[int, BeforeValidator(_level)] = 1
    say: StrList = []

    @field_validator("detail")
    @classmethod
    def _d(cls, v):
        if len(v.split()) < 3:
            raise ValueError("each detail must be a sentence")
        return v


class Name(M):
    name: Str
    say: Str = ""


class MaterialOut(M):
    items: list[Item]
    chain: StrList = []
    names: list[Name] = []

    @field_validator("items")
    @classmethod
    def _n(cls, v):
        if len(v) < MIN_ITEMS:
            raise ValueError(f"the list has {len(v)} items; it needs at least {MIN_ITEMS} (30 to 40 is right)")
        return v[:MAX_ITEMS]


def _passages(story: dict, name_map: dict) -> list[str]:
    ps = [p for p in story["evidence"]["passages"] if (p or "").strip()]
    return safety.apply_names(ps, name_map)


def user_text(story: dict, name_map: dict) -> str:
    ps = _passages(story, name_map)
    body = "\n".join(f"[{i}] {p.strip()}" for i, p in enumerate(ps, 1))[:MAX_PASSAGE_CHARS]
    return f"STORY FACTS:\n{intake.facts_text(story['public'])}\n\nSOURCE PASSAGES (for understanding only; write in your own words):\n{body}\n\nWrite the list now."


def _wording(it: Item) -> str:
    return " ".join((it.detail, it.when, it.where))


def problems(out: MaterialOut, prof: leak.SourceProfile) -> list[str]:
    """What sends the list back: wording copied from the source or a reference to it, and a list too thin in objects, places or actions."""
    bad = []
    for i, it in enumerate(out.items, 1):
        found = leak.check(_wording(it), prof)
        if found:
            bad.append(f"item {i} ({it.detail[:50]}...): {found[0].detail}: {found[0].text[:60]}")
    for c in out.chain:
        if leak.check(c, prof):
            bad.append(f"chain step '{c[:50]}...' copies or names the source")
    have = {k: sum(1 for it in out.items if it.kind == k) for k in NEEDS}
    short = [f"{n - have[k]} more {k} item(s)" for k, n in NEEDS.items() if have[k] < n]
    if short:
        bad.append("add " + ", ".join(short))
    return bad


async def make_material(plan_id: str, backend, s: dict | None = None) -> dict:
    """Write the plan's Material Pack. Items the owner added by hand (`manual`) survive a new run."""
    s = s or settings_mod.get()
    planner.ensure_name_map(plan_id)
    plan = planner.get_plan(plan_id)
    story = planner._story_for(plan)
    nm = plan["settings"].get("name_map") or {}
    prof = leak.profile(story["evidence"]["project_id"], story["evidence"]["passages"])
    tries: list[int] = []
    caller = llm.JsonCaller(backend, s)

    def check(out: MaterialOut) -> None:
        tries.append(1)
        bad = problems(out, prof)
        if bad and len(tries) <= 2 and not caller.last_attempt:
            raise ValueError("The list is not right yet:\n- " + "\n- ".join(bad[:8]))

    res = await caller.call(P.MATERIAL, user_text(story, nm), MaterialOut, check)
    out = res.value
    kept = [it for it in (plan["settings"].get("material") or {}).get("items", []) if it.get("manual")]
    items, dropped = [], 0
    for n, it in enumerate(out.items, 1):
        if leak.check(_wording(it), prof):
            dropped += 1                                                  # an item that still copies or names the source after the last try is dropped, never kept
            continue
        items.append({"id": f"m{n}", **it.model_dump(), "manual": False})
    items += [{**it, "id": it.get("id") or "x" + uuid.uuid4().hex[:5]} for it in kept]
    pack_ = {"items": items, "chain": [c for c in out.chain if not leak.check(c, prof)], "names": [n.model_dump() for n in out.names], "pipeline": "q2",
             "made_at": db.now(), "dropped": dropped}
    db.ex("UPDATE plans SET settings=?, updated_at=? WHERE id=?", (db.jdump({**planner.get_plan(plan_id)["settings"], "material": pack_}), db.now(), plan_id))
    store.log(plan_id, "material", {"items": len(items), "chain": len(pack_["chain"]), "dropped": dropped, "tokens_out": res.tokens_out})
    return planner.get_plan(plan_id)


def pack(plan: dict) -> dict:
    return (plan.get("settings") or {}).get("material") or {}


def has(plan: dict) -> bool:
    return bool(pack(plan).get("items"))


def save_items(plan_id: str, items: list[dict]) -> dict:
    """The owner's edit of the list: items are kept as sent (unknown fields dropped, kinds and levels cleaned), new ones get an id and are marked manual."""
    plan = planner.get_plan(plan_id)
    cur = pack(plan)
    clean = []
    for it in items:
        try:
            m = Item.model_validate(it).model_dump()
        except ValueError:
            continue
        old = next((x for x in cur.get("items", []) if x["id"] == it.get("id")), None)
        clean.append({**m, "id": it.get("id") or "x" + uuid.uuid4().hex[:5], "manual": bool(old.get("manual")) if old else True})
    db.ex("UPDATE plans SET settings=?, updated_at=? WHERE id=?", (db.jdump({**plan["settings"], "material": {**cur, "items": clean}}), db.now(), plan_id))
    store.log(plan_id, "material_edit", {"items": len(clean)})
    return planner.get_plan(plan_id)


def text_for(plan: dict, ids: list[str] | None = None, kinds: tuple[str, ...] | None = None) -> str:
    """The pack (or part of it) as lines for a prompt: `m3 [object] detail (when; where; who)`."""
    lines = []
    for it in pack(plan).get("items", []):
        if (ids is not None and it["id"] not in ids) or (kinds and it["kind"] not in kinds):
            continue
        bits = "; ".join(x for x in (it.get("when"), it.get("where"), it.get("who")) if x)
        lines.append(f"{it['id']} [{it['kind']}{', ALLEGED' if it.get('alleged') else ''}] {it['detail']}" + (f" ({bits})" if bits else ""))
    return "\n".join(lines)


# ── the blueprint's use of the pack (task 2.3) ──────────────────────────────

def blueprint_problems(bp, items: list[dict]) -> list[str]:
    """What sends a blueprint back when a pack exists: beats that use too little of it, ids that do not exist, a heavy detail nobody tells, a turn that is a question."""
    valid = {it["id"] for it in items}
    heavy = {it["id"]: it["detail"] for it in items if it.get("weight", 0) >= 3}
    bad, used = [], set()
    ids = {b.id or f"b{i}" for i, b in enumerate(bp.beats, 1)}
    for i, b in enumerate(bp.beats, 1):
        name = b.id or f"b{i}"
        known = [x for x in b.use if x in valid]
        unknown = [x for x in b.use + b.show if x not in valid]
        used.update(known)
        if len(known) < min(2, len(valid)):
            bad.append(f'beat {name} uses fewer than 2 details from the story material: give it "use" ids (like m3, m7) of the details it tells')
        if unknown:
            bad.append(f"beat {name} names ids that are not in the story material: {', '.join(unknown[:4])}")
        if not b.turn or "?" in b.turn:
            bad.append(f'beat {name} needs a "turn": a statement of the reversal or new fact, not a question')
    left = [f"{k} ({v[:50]})" for k, v in heavy.items() if k not in used]
    if left:
        bad.append("these important details are used by no beat: " + "; ".join(left[:5]))
    if bp.payoff_position and bp.payoff_position not in ids:
        bad.append(f'"payoff_position" must be the id of one of the beats, not {bp.payoff_position!r}')
    elif bp.payoff_position and len(bp.beats) >= 4:
        order = [b.id or f"b{i}" for i, b in enumerate(bp.beats, 1)]
        if order.index(bp.payoff_position) / len(order) > PAYOFF_BY:                       # where the beat that tells it starts
            bad.append(f'the answer to the central question is told in beat {bp.payoff_position}, too late: it must be told by {round(100 * PAYOFF_BY)}% of the running time, so move "payoff_position" earlier and give the last beats to the aftermath')
    return bad + experience_problems(bp, items)


PAYOFF_BY = 0.85                                    # the central answer is told by this share of the running time (task 2.16)


def experience_problems(bp, items: list[dict]) -> list[str]:
    """What is wrong with the blueprint's experience design (task 2.14): no stake, a set piece that is not built from showable details, a clue nobody is shown before the answer,
    an afterimage that is not in the story material. An empty design is allowed (old blueprints, short films)."""
    ex = bp.experience or {}
    if not ex:
        return []
    by = {it["id"]: it for it in items}
    bad = []
    if not str(ex.get("stake_to_viewer") or "").strip():
        bad.append('"experience.stake_to_viewer" is empty: say who is at risk and why this viewer should care')
    sp = ex.get("set_piece") if isinstance(ex.get("set_piece"), dict) else {}
    if sp:
        beat = next((b for b in bp.beats if b.id == sp.get("beat")), None)
        if beat is None:
            bad.append('"experience.set_piece.beat" must be the id of a beat')
        elif sum(1 for x in beat.use if by.get(x, {}).get("visual", 0) >= 2) < 4:
            bad.append(f"the set piece (beat {sp.get('beat')}) is built from fewer than 4 details with a strong picture (visual 2 or 3): give that beat more of them in \"use\"")
    after = str(ex.get("afterimage") or "")
    if after and not any(narrate_covered(it, after) for it in items if it.get("visual", 0) >= 2):
        bad.append('"experience.afterimage" is not one of the details of the story material: take the last image from them')
    ids = [b.id for b in bp.beats]
    cut = ids.index(bp.payoff_position) if bp.payoff_position in ids else len(ids)
    if ex.get("clue_device") and not any(b.show for b in bp.beats[:cut]):
        bad.append("a clue is planned but no beat before the answer shows anything on screen: put a clue detail in the \"show\" of an earlier beat")
    return bad


def narrate_covered(item: dict, text: str) -> bool:
    low = (text or "").lower()
    words = {w for w in re.findall(r"[a-z]{4,}", (item.get("detail", "") + " " + item.get("who", "")).lower())}
    return len([w for w in words if w in low]) >= 2


def clean_blueprint(bp: dict, items: list[dict]) -> None:
    """Make a blueprint usable by the material-based narration whatever the model returned. Only ids that exist are kept (a model sometimes writes them into `facts`: those count
    as `use`); a beat left with fewer than two details is given the unused ones in story order; a missing turn or reward is taken from the beat's reveal or plant; at most three
    `show` ids per beat; and the payoff position is a beat (the one before the last when none was given)."""
    valid = [it["id"] for it in items]
    ok = set(valid)
    beats = bp["beats"]
    for b in beats:
        ids = [x for x in b.get("use", []) if x in ok]
        if not ids:
            ids = [x for x in re.findall(r"(?<![A-Za-z])m\d+(?!\d)", " ".join(str(f) for f in b.get("facts", []))) if x in ok]
        b["use"] = list(dict.fromkeys(ids))
        b["show"] = [x for x in b.get("show", []) if x in ok][:3]
        b["facts"] = [f for f in b.get("facts", []) if not re.fullmatch(r"m\d+", str(f).strip())] or [it["detail"] for it in items if it["id"] in b["use"]][:6]
    spare = [x for x in valid if not any(x in b["use"] for b in beats)]
    for x in spare:                                                       # leftovers go to the beat with the fewest, keeping story order within a beat
        pool = [b for b in beats if len(b["use"]) < 7] or beats
        least = min(pool, key=lambda b: len(b["use"]))
        if len(least["use"]) < 2 or x in [it["id"] for it in items if it.get("weight", 0) >= 3]:
            least["use"].append(x)
    order = {x: i for i, x in enumerate(valid)}
    for b in beats:
        b["use"].sort(key=lambda x: order[x])
        b["turn"] = b.get("turn") or b.get("reveal") or ""
        b["reward"] = b.get("reward") or b.get("plant") or b.get("reveal") or ""
    ids = [b.get("id") or f"b{i}" for i, b in enumerate(beats, 1)]
    if bp.get("payoff_position") not in ids:
        bp["payoff_position"] = ids[-2] if len(ids) > 2 else ids[-1]


# ── canonical names (task 2.11) ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
NAME_SIMILARITY = 0.78


def _name_tokens(names: list[dict]) -> tuple[list[str], list[str]]:
    latin, deva = [], []
    for n in names:
        latin += [w for w in re.findall(r"[A-Za-z]{4,}", n.get("name", ""))]
        deva += re.findall(r"[ऀ-ॿ]{3,}", n.get("say", "") + " " + n.get("name", ""))
    return list(dict.fromkeys(latin)), list(dict.fromkeys(deva))


def name_variants(text: str, names: list[dict]) -> list[tuple[str, str]]:
    """Words of the text that look like a misspelling of a person's name in the pack (Chavi / Chabbi / Chhabbi), as (found, canonical). A name is a capitalised Latin word of four
    letters or more that starts with the same letter and is close to a canonical one, or a Devanagari word that is close to the spoken form."""
    latin, deva = _name_tokens(names)
    out = []
    for w in dict.fromkeys(re.findall(r"[A-Za-z]{4,}|[ऀ-ॿ]{3,}", text or "")):
        if re.match(r"[A-Za-z]", w):
            if not w[0].isupper() or w in latin or w.lower() in lexicon.COMMON_ENGLISH:
                continue
            pool, limit = latin, NAME_SIMILARITY
        else:
            if w in deva:
                continue
            pool, limit = deva, 0.85
        best = max(((difflib.SequenceMatcher(None, w.lower(), c.lower()).ratio(), c) for c in pool if c[0].lower() == w[0].lower()), default=(0, ""))
        if best[0] >= limit:
            out.append((w, best[1]))
    return out


def canonical(text: str, names: list[dict]) -> tuple[str, list[tuple[str, str]]]:
    """The text with every variant spelling of a pack name rewritten to the canonical one, and what was changed."""
    found = name_variants(text, names)
    for w, c in found:
        text = re.sub(rf"(?<![A-Za-zऀ-ॿ]){re.escape(w)}(?![A-Za-zऀ-ॿ])", c, text)
    return text, found
