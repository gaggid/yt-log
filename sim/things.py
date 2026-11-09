"""Things: finds, makes, gives, takes, uses, recipes and skills (docs/PLAN_discoveries.md). The model proposes operations with its reasoning; this code decides which are real. A thing enters the world
only through an act that earned it (a roll, a fired instruction, or text already in the world), a make uses up parts that exist and needs tools that are there, and nothing here knows a genre."""
import copy
import math

from . import state as S

CONDITIONS = ("new", "worn", "damaged", "crude", "well made", "broken")
TIERS_OK = ("great", "success", "partial")
CAPS = {"find": 2, "make": 2, "skill": 1}
NEW_OPS = ("discover", "craft", "item_give", "item_take", "item_use", "item_change", "skill_learn")
FIND_KINDS = ("item", "place", "clue", "recipe")
MAX_SKILLS = 8


# ── a thing ───────────────────────────────────────────────────────────────────

def clean_props(p) -> dict:
    p = p if isinstance(p, dict) else {}
    cond = S.norm(p.get("condition", ""))
    uses = p.get("uses")
    tags = p.get("tags") if isinstance(p.get("tags"), list) else []
    return {"condition": cond if cond in CONDITIONS else "",
            "uses": None if uses in (None, "") or str(uses).lower() in ("null", "none", "unlimited") else max(0, int(S._num(uses))),
            "size": max(1, min(9, int(S._num(p.get("size"), 1) or 1))),
            "tags": [str(t)[:24] for t in tags[:4]]}


def props(e: dict) -> dict:
    return {**clean_props({}), **(e.get("props") or {})}


def new_thing(qty, at, note="", p=None, origin=None, bound_to="") -> dict:
    return {"qty": max(1, int(qty)), "at": at, "note": note, "props": clean_props(p), "origin": origin or {}, "bound_to": bound_to}


def thing_text(name: str, e: dict) -> str:
    p = props(e)
    bits = []
    if p["condition"]:
        bits.append(p["condition"])
    if p["uses"] is not None:
        bits.append(f"{p['uses']} use{'s' if p['uses'] != 1 else ''} left")
    if e.get("bound_to"):
        bits.append(f"bound to {e['bound_to']}")
    if e.get("note"):
        bits.append(e["note"])
    return f"{name} x{e['qty']}" + (f" ({', '.join(bits)})" if bits else "")


# ── looking things up ─────────────────────────────────────────────────────────

def item_trackers(ctx) -> list[dict]:
    return [t for t in ctx.trackers if t["kind"] == "items"]


def find_item(st: dict, ctx, name: str):
    """(inventory, key) of the thing the model means, in any items tracker: exact name first, then one close name."""
    n = S.norm(name)
    if not n:
        return None, None
    close = []
    for t in item_trackers(ctx):
        inv = st["trackers"].get(t["id"]) or {}
        for k in inv:
            if S.norm(k) == n:
                return inv, k
            if S._same(k, n):
                close.append((inv, k))
    return close[0] if len(close) == 1 else (None, None)


def place_of(st: dict, ctx, who: str) -> str:
    for t in ctx.trackers:
        if t["kind"] == "location":
            return (st["trackers"].get(t["id"]) or {}).get("at", {}).get(who, "")
    return ""


def at_hand(st: dict, ctx, who: str, name: str):
    """(inventory, key) of a thing the person holds or that lies where they are."""
    inv, key = find_item(st, ctx, name)
    if not key:
        return None, None
    at = inv[key].get("at", "")
    here = place_of(st, ctx, who)
    return (inv, key) if S.norm(at) == S.norm(who) or (here and S.norm(at) == S.norm(here)) else (None, None)


def carried(st: dict, ctx, who: str) -> int:
    n = 0
    for t in item_trackers(ctx):
        for e in (st["trackers"].get(t["id"]) or {}).values():
            if S.norm(e.get("at", "")) == S.norm(who):
                n += int(e.get("qty", 1)) * props(e)["size"]
    return n


def limit(ctx, who: str) -> int:
    return int(ctx.carry.get(who, ctx.carry_default) or 0)


def room_for(st: dict, ctx, who: str, size: int) -> bool:
    lim = limit(ctx, who)
    return not lim or carried(st, ctx, who) + size <= lim


def relation(st: dict, ctx, a: str, b: str):
    for t in ctx.trackers:
        if t["kind"] == "relation" and {S.norm(t.get("a")), S.norm(t.get("b"))} == {S.norm(a), S.norm(b)}:
            return t, st["trackers"][t["id"]]
    return None, None


def match_roll(ctx, kinds, who: str, target: str = "", about_only: bool = False) -> dict | None:
    """The unused roll of this kind of act by this person (the one about this thing first; with `about_only` only a roll about this thing)."""
    kinds = (kinds,) if isinstance(kinds, str) else kinds
    pool = [r for r in ctx.rolls if r.get("kind") in kinds and r.get("n") not in ctx.used_rolls and (not who or not r.get("who") or S._same(r["who"], who))]
    about = [r for r in pool if target and S._words(r.get("makes", "") + " " + r.get("act", "")) & S._words(target)]
    if not about and (about_only or not pool):
        return None
    pick = (about or pool)[0]
    ctx.used_rolls.add(pick["n"])
    return pick


def _find_allowed(st: dict, ctx, who: str, target: str, kinds=("search",)):
    """(ok, how-or-reason, roll): may this thing come into the story now?"""
    seen = S._words(ctx.exists_text) | S._words(" ".join(f"{w['name']} {w.get('text', '')}" for w in st.get("world_add", [])))
    r = match_roll(ctx, kinds, who, target, about_only=True)                    # a roll about this very thing decides, even when the world text names it
    if r:
        return (r["tier"] in TIERS_OK), ("found by a roll" if r["tier"] in TIERS_OK else "the search failed"), r
    if S._words(target) & seen:
        return True, "the world already holds it", None
    r = match_roll(ctx, kinds, who, target)
    if r:
        if r["tier"] in TIERS_OK:
            return True, "found by a roll", r
        return False, "the search failed", r
    if any(S._words(t) & S._words(target) for t in ctx.fired):
        return True, "an instruction", None
    return False, "nothing earned it: it is not in the world, no search was rolled and no instruction names it", None


# ── the operations ────────────────────────────────────────────────────────────

def handle(k: str, op, who: str | None, st: dict, ctx, ents: dict, places: dict, drop, ok, snap) -> None:
    forced = op.kind == "forced"
    if who and not st["entities"].get(who, {}).get("alive", True):
        drop(op, f"{who} is dead")
        return
    fn = {"discover": _discover, "craft": _craft, "item_give": _give, "item_take": _take, "item_use": _use, "item_change": _change, "skill_learn": _skill}[k]
    fn(op, who, st, ctx, ents, places, drop, ok, snap, forced)


def _first_inv(st, ctx):
    ts = item_trackers(ctx)
    return (st["trackers"][ts[0]["id"]], ts[0]["id"]) if ts else (None, None)


def _discover(op, who, st, ctx, ents, places, drop, ok, snap, forced):
    kind = S.norm(op.kind) or "item"
    target = (op.target or "").strip()
    if kind not in FIND_KINDS:
        drop(op, f"only an item, a place, a clue or a recipe can be found, not a {op.kind}")
        return
    if not target:
        drop(op, "nothing named")
        return
    if ctx.counts["find"] >= CAPS["find"] and not forced:
        drop(op, f"at most {CAPS['find']} finds a chapter")
        return
    allowed, how, roll = (True, "owner", None) if forced else _find_allowed(st, ctx, who or "", target, ("search", "learn") if kind in ("recipe", "clue") else ("search",))
    if not allowed:
        drop(op, how)
        return
    add = st.setdefault("world_add", [])
    if kind == "item":
        inv, tid = _first_inv(st, ctx)
        if inv is None:
            drop(op, "the story keeps no items")
            return
        if find_item(st, ctx, target)[1]:
            drop(op, f"{target} is already known")
            return
        where = S.pick(places, op.where) or S.pick(places, op.source) or place_of(st, ctx, who or "") or ""
        holder = S.pick(ents, op.to) or who or where
        if not holder:
            drop(op, "say where it was found")
            return
        p = clean_props(op.props)
        if roll and roll["tier"] == "partial" and not p["condition"]:
            p["condition"] = "damaged"
        qty = max(1, int(S._num(op.qty, 1)))
        if S.pick(ents, holder) and not room_for(st, ctx, holder, qty * p["size"]) and not forced:
            holder = where or place_of(st, ctx, holder) or holder                 # cannot carry it now: it stays where it was found
        snap(tid, target)
        inv[target] = new_thing(qty, holder, "", p, {"how": "found", "chapter": ctx.chapter, "by": who or "", "where": where or holder})
        add.append({"kind": "item", "name": target, "text": (op.text or op.why or "")[:160], "where": where or holder, "chapter": ctx.chapter, "by": who or ""})
        ctx.counts["find"] += 1
        ctx.undo.append({"do": "pop_world_add", "name": target})
        ok(op, f"found {target}" + (f" ({p['condition']})" if p["condition"] else "") + f" at {inv[target]['at']}", ctx.pop_undo())
    elif kind == "place":
        if S.pick(places, target):
            drop(op, f"{target} is already a known place")
            return
        add.append({"kind": "place", "name": target, "text": (op.text or op.why or "")[:160], "where": S.pick(places, op.where) or "", "chapter": ctx.chapter, "by": who or ""})
        places[S.norm(target)] = target
        ctx.counts["find"] += 1
        ctx.undo.append({"do": "pop_world_add", "name": target})
        ok(op, f"discovered the place {target}", ctx.pop_undo())
    elif kind == "clue":
        add.append({"kind": "clue", "name": target, "text": (op.text or op.why or "")[:240], "where": S.pick(places, op.where) or place_of(st, ctx, who or ""), "chapter": ctx.chapter, "by": who or ""})
        ctx.counts["find"] += 1
        ctx.undo.append({"do": "pop_world_add", "name": target})
        learned = ""
        trk = S.find_tracker(ctx.trackers, op.tracker, ("knowledge",)) if (op.tracker or op.value) else None
        secret = next((s for s in (st["trackers"].get(trk["id"]) or {}) if S.norm(s) == S.norm(str(op.value or ""))), None) if trk else None
        if trk and secret and who and who not in st["trackers"][trk["id"]][secret]:
            st["trackers"][trk["id"]][secret].append(who)
            learned = f"; {who} learns {secret}"
        ok(op, f"found the clue {target}{learned}", ctx.pop_undo())
    else:
        _add_recipe(op, who, st, ctx, target, ok, "learned")
        ctx.counts["find"] += 1


def _add_recipe(op, who, st, ctx, target, ok, how):
    rec = st.setdefault("recipes", {})
    prev = copy.deepcopy(rec.get(target))
    cur = rec.setdefault(target, {"makes": target, "needs": [], "tools": [], "skill": "", "learned_by": [], "chapter": ctx.chapter})
    if op.parts:
        cur["needs"] = list(op.parts)
    if op.tools:
        cur["tools"] = list(op.tools)
    if op.skill:
        cur["skill"] = op.skill
    if who and who not in cur["learned_by"]:
        cur["learned_by"].append(who)
    ctx.undo.append({"do": "put_recipe", "name": target, "entry": prev})
    ok(op, f"{who or 'someone'} {how} how to make {target}", ctx.pop_undo())


def _craft(op, who, st, ctx, ents, places, drop, ok, snap, forced):
    target = (op.target or "").strip()
    if not who or not target:
        drop(op, "say who makes what")
        return
    if ctx.counts["make"] >= CAPS["make"] and not forced:
        drop(op, f"at most {CAPS['make']} makes a chapter")
        return
    inv, tid = _first_inv(st, ctx)
    if inv is None:
        drop(op, "the story keeps no items")
        return
    need: dict[str, int] = {}
    for p in op.parts:
        need[p] = need.get(p, 0) + 1
    held = []
    here = place_of(st, ctx, who)
    scenery = S._words(ctx.exists_text) | S._words(ctx.place_text.get(here, ""))
    for name, n in need.items():
        i, key = at_hand(st, ctx, who, name)
        if not key and (S.norm(name) in ctx.removed or any(S._same(name, r) for r in ctx.removed)):
            continue                                                                         # the model already took it out this chapter: it is used up
        if not key and not find_item(st, ctx, name)[1] and S._words(name) & scenery:
            continue                                                                         # something the world text says is lying about (a chair, a crate) and nobody tracks: it needs no tracking
        if not key or i[key]["qty"] < n:
            drop(op, f"{who} has no {name} to use" if not key else f"not enough {name}")
            return
        held.append((i, key, n))
    for name in op.tools:
        i, key = at_hand(st, ctx, who, name)
        if not key and not find_item(st, ctx, name)[1] and S._words(name) & scenery:
            continue                                                                         # a tool the world text says is lying about here
        if not key:
            drop(op, f"the tool {name} is not here")
            return
        if props(i[key])["condition"] == "broken":
            drop(op, f"the tool {name} is broken")
            return
    roll = None if forced else match_roll(ctx, "make", who, target)
    if ctx.dice_on and not roll and not forced:
        drop(op, "no act of making was rolled for this")
        return
    tier = roll["tier"] if roll else "success"

    def use_parts(frac_all: bool, count: int):
        lost = []
        left = count
        for i, key, n in held:
            take = n if frac_all else min(n, left)
            if take <= 0:
                continue
            for tid2 in [t["id"] for t in item_trackers(ctx) if i is st["trackers"][t["id"]]]:
                snap(tid2, key)
            i[key]["qty"] -= take
            left -= take
            lost.append(f"{take} {key}")
            if i[key]["qty"] <= 0:
                del i[key]
        return lost

    if tier in ("fail", "disaster"):
        total = sum(n for _, _, n in held)
        lost = use_parts(tier == "disaster", max(1 if total else 0, math.ceil(total / 2)))
        ctx.counts["make"] += 1
        ok(op, f"{who} failed to make {target}" + (f" and lost {', '.join(lost)}" if lost else ""), ctx.pop_undo())
        return
    p = clean_props(op.props)
    if tier == "partial":
        p["condition"] = "crude"
        p["uses"] = 1 if p["uses"] is None else min(1, p["uses"])
    elif tier == "great":
        p["condition"] = p["condition"] or "well made"
        p["uses"] = None if p["uses"] is None else p["uses"] + 1
    qty = max(1, int(S._num(op.qty, 1)))
    if not forced and not room_for(st, ctx, who, qty * p["size"]):
        drop(op, f"{who} cannot carry more")
        return
    lost = []
    for i, key, n in held:
        for tid2 in [t["id"] for t in item_trackers(ctx) if i is st["trackers"][t["id"]]]:
            snap(tid2, key)
        i[key]["qty"] -= n
        lost.append(f"{n} {key}")
        if i[key]["qty"] <= 0:
            del i[key]
    have = next((n for n in inv if S.norm(n) == S.norm(target)), None)
    snap(tid, have or target)
    if have:
        inv[have]["qty"] += qty
    else:
        inv[target] = new_thing(qty, who, "", p, {"how": "made", "chapter": ctx.chapter, "by": who, "where": place_of(st, ctx, who), "parts": list(op.parts)})
    rec = st.setdefault("recipes", {})
    prev = copy.deepcopy(rec.get(target))
    cur = rec.setdefault(target, {"makes": target, "needs": list(op.parts), "tools": list(op.tools), "skill": op.skill or (roll or {}).get("skill", ""), "learned_by": [], "chapter": ctx.chapter})
    if who not in cur["learned_by"]:
        cur["learned_by"].append(who)
    ctx.undo.append({"do": "put_recipe", "name": target, "entry": prev})
    ctx.counts["make"] += 1
    ok(op, f"{who} made {target}" + (f" ({p['condition']})" if p["condition"] else "") + (f" from {', '.join(lost)}" if lost else ""), ctx.pop_undo())


def _holder_check(op, who, st, ctx, name):
    inv, key = find_item(st, ctx, name)
    return inv, key


def _give(op, who, st, ctx, ents, places, drop, ok, snap, forced):
    to = S.pick(ents, op.to)
    giver = who or S.pick(ents, op.source)
    inv, key = find_item(st, ctx, op.target)
    if not key or not to or not giver:
        drop(op, "the thing, the giver or the receiver is unknown")
        return
    e = inv[key]
    if S.norm(e.get("at", "")) != S.norm(giver) and not forced:
        drop(op, f"{giver} does not hold {key}")
        return
    if e.get("bound_to") and not forced:
        drop(op, f"{key} is bound to {e['bound_to']} and stays with them")
        return
    if not st["entities"].get(to, {}).get("alive", True):
        drop(op, f"{to} is dead")
        return
    pg, pt = place_of(st, ctx, giver), place_of(st, ctx, to)
    if pg and pt and pg != pt and not forced:
        drop(op, f"{giver} and {to} are not in the same place")
        return
    qty = min(e["qty"], max(1, int(S._num(op.qty, 1))))
    if not forced and not room_for(st, ctx, to, qty * props(e)["size"]):
        drop(op, f"{to} cannot carry more")
        return
    if ctx.dice_on and not forced:
        t, v = relation(st, ctx, giver, to)
        if t and (v["trust"] < 0 or v["tension"] >= 3):
            r = match_roll(ctx, "persuade", giver, key)
            if not r or r["tier"] not in TIERS_OK:
                drop(op, f"{to} would refuse; a persuading act has to succeed first")
                return
    tid = next(t["id"] for t in item_trackers(ctx) if st["trackers"][t["id"]] is inv)
    snap(tid, key)
    if qty >= e["qty"]:
        e["at"] = to
        ok(op, f"{giver} gave {key} to {to}", ctx.pop_undo())
    else:
        e["qty"] -= qty
        nk = f"{key} ({to})"
        snap(tid, nk)
        inv[nk] = {**copy.deepcopy(e), "qty": qty, "at": to}
        ok(op, f"{giver} gave {qty} {key} to {to}", ctx.pop_undo())


def _take(op, who, st, ctx, ents, places, drop, ok, snap, forced):
    victim = S.pick(ents, op.source)
    inv, key = find_item(st, ctx, op.target)
    if not who or not key or not victim:
        drop(op, "the taker, the thing or the person it is taken from is unknown")
        return
    e = inv[key]
    if S.norm(e.get("at", "")) != S.norm(victim) and not forced:
        drop(op, f"{victim} does not hold {key}")
        return
    if e.get("bound_to") and not forced:
        drop(op, f"{key} is bound to {e['bound_to']} and stays with them")
        return
    pw, pv = place_of(st, ctx, who), place_of(st, ctx, victim)
    if pw and pv and pw != pv and not forced:
        drop(op, f"{who} and {victim} are not in the same place")
        return
    if not forced and not room_for(st, ctx, who, e["qty"] * props(e)["size"]):
        drop(op, f"{who} cannot carry more")
        return
    roll = None
    if ctx.dice_on and not forced:
        roll = match_roll(ctx, "take", who, key)
        if not roll:
            drop(op, "no act of taking was rolled for this")
            return
        if roll["tier"] not in TIERS_OK:
            drop(op, f"{who} failed to take {key}")
            t, v = relation(st, ctx, who, victim)
            if t:
                v["tension"] = min(S.REL_MAX, v["tension"] + 1)
            return
    tid = next(t["id"] for t in item_trackers(ctx) if st["trackers"][t["id"]] is inv)
    snap(tid, key)
    e["at"] = who
    e["origin"] = {**(e.get("origin") or {}), "how": "taken", "chapter": ctx.chapter, "by": who}
    t, v = relation(st, ctx, who, victim)
    if t and not forced:
        v["tension"] = min(S.REL_MAX, v["tension"] + 1)
    ok(op, f"{who} took {key} from {victim}", ctx.pop_undo())


def _use(op, who, st, ctx, ents, places, drop, ok, snap, forced):
    if not who:
        drop(op, "say who uses it")
        return
    inv, key = at_hand(st, ctx, who, op.target)
    if not key:
        drop(op, f"{who} does not have {op.target}")
        return
    e = inv[key]
    p = props(e)
    if p["condition"] == "broken" or p["uses"] == 0:
        drop(op, f"{key} is broken or spent")
        return
    tid = next(t["id"] for t in item_trackers(ctx) if st["trackers"][t["id"]] is inv)
    snap(tid, key)
    if p["uses"] is not None:
        p["uses"] -= 1
        if p["uses"] <= 0:
            p["condition"] = "broken"
        e["props"] = p
        ok(op, f"{who} used {key}" + (" and it is spent" if p["uses"] <= 0 else f" ({p['uses']} left)"), ctx.pop_undo())
    else:
        ok(op, f"{who} used {key}", ctx.pop_undo())


def _change(op, who, st, ctx, ents, places, drop, ok, snap, forced):
    inv, key = find_item(st, ctx, op.target)
    if not key:
        drop(op, f"{op.target} is unknown")
        return
    e = inv[key]
    tid = next(t["id"] for t in item_trackers(ctx) if st["trackers"][t["id"]] is inv)
    snap(tid, key)
    p = props(e)
    cond = S.norm(op.value if isinstance(op.value, str) else "") or S.norm((op.props or {}).get("condition", ""))
    if cond in CONDITIONS:
        p["condition"] = cond
        if cond == "broken":
            p["uses"] = 0 if p["uses"] is not None else p["uses"]
    if (op.props or {}).get("uses") not in (None, ""):
        p["uses"] = max(0, int(S._num(op.props["uses"])))
    if op.text:
        e["note"] = op.text[:120]
    if forced and "bound_to" in (op.props or {}):
        e["bound_to"] = S.pick(ents, str(op.props["bound_to"])) or ""
    e["props"] = p
    ok(op, f"{key} is now {p['condition'] or 'changed'}" + (f", {p['uses']} uses" if p["uses"] is not None else ""), ctx.pop_undo())


def _skill(op, who, st, ctx, ents, places, drop, ok, snap, forced):
    skill = (op.target or op.skill or "").strip()[:40]
    if not who or not skill:
        drop(op, "say who learns what")
        return
    if ctx.counts["skill"] >= CAPS["skill"] and not forced:
        drop(op, f"at most {CAPS['skill']} new skill a chapter")
        return
    if not forced:
        r = match_roll(ctx, "learn", who, skill)
        if not ctx.fired and not (r and r["tier"] in TIERS_OK):
            drop(op, "nothing taught it: no learning act succeeded and no instruction says so")
            return
    mine = st["entities"][who].setdefault("skills", [])
    if any(S.norm(x) == S.norm(skill) for x in mine):
        drop(op, f"{who} already has {skill}")
        return
    if len(mine) >= MAX_SKILLS:
        drop(op, f"{who} has too many skills already")
        return
    mine.append(skill)
    ctx.counts["skill"] += 1
    ctx.undo.append({"do": "remove_skill", "who": who, "skill": skill})
    ok(op, f"{who} learned {skill}", ctx.pop_undo())


# ── the owner's edits and undo (one function for both) ────────────────────────

def edit(st: dict, ctx, action: dict) -> str:
    """Change a state directly: the Things tab and Undo. Returns what was done; raises ValueError for anything that makes no sense."""
    do = action.get("do")
    ents = {S.norm(n): n for n in ctx.entity_names}
    places = {S.norm(n): n for n in ctx.place_names + [w["name"] for w in st.get("world_add", []) if w.get("kind") == "place"]}
    if do == "put_thing":
        inv = st["trackers"].get(action.get("tracker"))
        if inv is None:
            raise ValueError("unknown items tracker")
        if action.get("entry") is None:
            inv.pop(action["name"], None)
            return f"removed {action['name']}"
        inv[action["name"]] = copy.deepcopy(action["entry"])
        return f"restored {action['name']}"
    if do == "set_thing":
        name = str(action.get("name", "")).strip()
        if not name:
            raise ValueError("give the thing a name")
        inv, key = find_item(st, ctx, name)
        f = action.get("fields") or {}
        holder = f.get("at")
        if holder is not None and holder != "":
            holder = S.pick(ents, holder) or S.pick(places, holder)
            if not holder:
                raise ValueError("the holder must be a person or a place of the story")
        if not key:
            ts = item_trackers(ctx)
            if not ts:
                raise ValueError("the story keeps no items")
            inv = st["trackers"][ts[0]["id"]]
            key = name
            inv[key] = new_thing(1, holder or "", "", {}, {"how": "owner", "chapter": ctx.chapter})
        e = inv[key]
        if holder is not None:
            e["at"] = holder or ""
        if "qty" in f:
            e["qty"] = max(1, int(S._num(f["qty"], 1)))
        if "note" in f:
            e["note"] = str(f["note"])[:120]
        if "bound_to" in f:
            b = str(f["bound_to"] or "")
            e["bound_to"] = (S.pick(ents, b) or "") if b else ""
            if b and not e["bound_to"]:
                raise ValueError("bind it to a person of the story")
        p = {**props(e), **{k: f[k] for k in ("condition", "uses", "size", "tags") if k in f}}
        e["props"] = clean_props(p)
        return f"{key} updated"
    if do == "remove_thing":
        inv, key = find_item(st, ctx, action.get("name", ""))
        if not key:
            raise ValueError("no such thing")
        del inv[key]
        return f"removed {key}"
    if do == "pop_world_add":
        n = S.norm(action.get("name", ""))
        before = len(st.get("world_add", []))
        st["world_add"] = [w for w in st.get("world_add", []) if S.norm(w["name"]) != n]
        if len(st["world_add"]) == before:
            raise ValueError("nothing to take back")
        return f"took back {action.get('name')}"
    if do == "put_recipe":
        rec = st.setdefault("recipes", {})
        if action.get("entry") is None:
            rec.pop(action["name"], None)
        else:
            rec[action["name"]] = copy.deepcopy(action["entry"])
        return f"recipe {action['name']} restored"
    if do == "set_recipe":
        name = str(action.get("name", "")).strip()
        if not name:
            raise ValueError("name what it makes")
        cur = st.setdefault("recipes", {}).setdefault(name, {"makes": name, "needs": [], "tools": [], "skill": "", "learned_by": [], "chapter": ctx.chapter})
        for k in ("needs", "tools", "learned_by"):
            if k in action:
                cur[k] = [str(x) for x in (action[k] or [])]
        if "skill" in action:
            cur["skill"] = str(action["skill"])[:40]
        return f"recipe {name} saved"
    if do == "remove_recipe":
        if action.get("name") not in st.get("recipes", {}):
            raise ValueError("no such recipe")
        del st["recipes"][action["name"]]
        return f"recipe {action['name']} removed"
    if do in ("add_skill", "remove_skill"):
        who = S.pick(ents, action.get("who", ""))
        skill = str(action.get("skill", "")).strip()[:40]
        if not who or who not in st["entities"] or not skill:
            raise ValueError("say who and which skill")
        mine = st["entities"][who].setdefault("skills", [])
        if do == "add_skill":
            if not any(S.norm(x) == S.norm(skill) for x in mine):
                mine.append(skill)
            return f"{who} has {skill}"
        st["entities"][who]["skills"] = [x for x in mine if S.norm(x) != S.norm(skill)]
        return f"{who} lost {skill}"
    raise ValueError("unknown change")
