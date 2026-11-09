"""The story's state and the rules for changing it (docs/PLAN_simulation.md section 4). The model proposes operations; this code decides which are real. Nothing here knows a genre: it
knows tracker kinds (items, meter, clock, relation, location, knowledge, flag)."""
import copy
import re
from dataclasses import dataclass, field

from .models import OPS

CLOCK_DEFAULT = 6
REL_MIN, REL_MAX = -5, 5


def norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _num(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", norm(s)) if len(w) >= 4}


# ── building a tracker's definition and starting value ────────────────────────

def normalize_tracker(t: dict, entity_names: list[str], place_names: list[str]) -> tuple[dict, list[str]]:
    """The definition a stored tracker keeps (`start` already in the shape of its kind) and a list of problems found (each one repaired or dropped)."""
    kind, bad = t["kind"], []
    out = {k: t.get(k) for k in ("kind", "name", "description", "owner", "unit") if t.get(k) not in (None, "")}
    start = t.get("start")
    ents = {norm(n): n for n in entity_names}
    places = {norm(n): n for n in place_names}
    if kind == "items":
        items: dict[str, dict] = {}
        rows = start if isinstance(start, list) else [{"name": k, **(v if isinstance(v, dict) else {"qty": v})} for k, v in (start or {}).items()] if isinstance(start, dict) else []
        for r in rows:
            if isinstance(r, str):
                r = {"name": r}
            name = str(r.get("name") or r.get("item") or "").strip()
            if not name:
                continue
            at = str(r.get("at") or r.get("place") or r.get("holder") or "").strip()
            if at and norm(at) not in places and norm(at) not in ents:
                bad.append(f"item {name}: unknown holder {at}")
            items[name] = {"qty": max(1, int(_num(r.get("qty", 1), 1))), "at": at, "note": str(r.get("note") or "")}
        out["start"] = items
    elif kind == "meter":
        lo, hi = _num(t.get("min"), 0), _num(t.get("max"), 10)
        if hi <= lo:
            hi = lo + 10
            bad.append("meter range was empty; widened")
        out.update(min=lo, max=hi, start=min(hi, max(lo, _num(start, (lo + hi) / 2))))
        for k in ("danger_below", "danger_above"):
            if t.get(k) not in (None, ""):
                out[k] = _num(t[k])
    elif kind == "clock":
        mx = max(2, int(_num(t.get("max"), CLOCK_DEFAULT)))
        out.update(max=mx, start=max(0, min(mx, int(_num(start, 0)))), rises=str(t.get("rises") or ""), ends=str(t.get("ends") or ""))
    elif kind == "relation":
        a, b = str(t.get("a") or "").strip(), str(t.get("b") or "").strip()
        for n in (a, b):
            if norm(n) not in ents:
                bad.append(f"relation: unknown character {n}")
        s = start if isinstance(start, dict) else {}
        out.update(a=ents.get(norm(a), a), b=ents.get(norm(b), b),
                   start={"trust": max(REL_MIN, min(REL_MAX, int(_num(s.get("trust"), 0)))), "tension": max(REL_MIN, min(REL_MAX, int(_num(s.get("tension"), 0))))})
    elif kind == "location":
        at: dict[str, str] = {}
        src = start.get("at") if isinstance(start, dict) and isinstance(start.get("at"), dict) else start if isinstance(start, dict) else {}
        for who, place in src.items():
            if norm(who) in ents and norm(place) in places:
                at[ents[norm(who)]] = places[norm(place)]
            else:
                bad.append(f"location: {who} -> {place} is not a known character and place")
        locked = [places[norm(p)] for p in (start.get("locked", []) if isinstance(start, dict) else []) if norm(p) in places]
        out["start"] = {"at": at, "locked": locked}
    elif kind == "knowledge":
        k: dict[str, list[str]] = {}
        if isinstance(start, dict):
            for secret, who in start.items():
                who = [who] if isinstance(who, str) else list(who or [])
                k[str(secret)] = [ents[norm(w)] for w in who if norm(w) in ents]
        elif isinstance(start, list):
            for secret in start:
                k[str(secret)] = []
        if t.get("secret") and str(t["secret"]) not in k:
            k[str(t["secret"])] = []
        out["start"] = k
    elif kind == "flag":
        out["start"] = str(start).strip().lower() in ("true", "yes", "1", "on") if not isinstance(start, bool) else start
    return out, bad


def initial_state(trackers: list[dict], entities: list[dict], world: dict) -> dict:
    return {"time": str(world.get("start_time") or ""),
            "trackers": {t["id"]: copy.deepcopy(t.get("start")) for t in trackers},
            "entities": {e["name"]: {"alive": bool(e.get("alive", True)), "status": str(e.get("status") or "")} for e in entities if e["kind"] == "character"}}


def validate_setup(trackers: list[dict], entities: list[dict]) -> list[str]:
    """What is missing before a story can start (shown as a list, never a silent failure)."""
    out = []
    chars = [e for e in entities if e["kind"] == "character"]
    if len(chars) < 1:
        out.append("add at least one character")
    if not [e for e in entities if e["kind"] == "place"]:
        out.append("add at least one place")
    if not [t for t in trackers if t["kind"] in ("clock", "meter")]:
        out.append("add a clock or a meter so something is at stake")
    return out


# ── reading the state ─────────────────────────────────────────────────────────

def pressure(state: dict, trackers: list[dict]) -> list[dict]:
    """Things at their limit: full clocks (with what happens), meters in the danger zone."""
    out = []
    for t in trackers:
        v = state["trackers"].get(t["id"])
        if t["kind"] == "clock" and v is not None and int(v) >= int(t.get("max", CLOCK_DEFAULT)):
            out.append({"tracker": t["name"], "kind": "clock_full", "text": f"clock {t['name']} is full: {t.get('ends') or 'the threat arrives'}"})
        elif t["kind"] == "meter" and v is not None:
            if t.get("danger_below") is not None and float(v) <= float(t["danger_below"]):
                out.append({"tracker": t["name"], "kind": "danger", "text": f"{t['name']} is dangerously low ({v:g} {t.get('unit', '')})".strip()})
            if t.get("danger_above") is not None and float(v) >= float(t["danger_above"]):
                out.append({"tracker": t["name"], "kind": "danger", "text": f"{t['name']} is dangerously high ({v:g} {t.get('unit', '')})".strip()})
    return out


def describe(state: dict, trackers: list[dict]) -> str:
    """The state as compact text for a prompt."""
    lines = [f"Story time: {state.get('time') or 'unknown'}"]
    for t in trackers:
        v = state["trackers"].get(t["id"])
        k = t["kind"]
        if k == "items":
            body = "; ".join(f"{n} x{i['qty']}" + (f" ({i['at']})" if i.get("at") else "") for n, i in (v or {}).items()) or "none"
        elif k == "meter":
            body = f"{v:g}/{t.get('max', 10):g} {t.get('unit', '')}".strip() + (f" [{t.get('owner')}]" if t.get("owner") else "")
        elif k == "clock":
            body = f"{v}/{t.get('max')}" + (f" (rises with: {t['rises']})" if t.get("rises") else "")
        elif k == "relation":
            body = f"{t.get('a')} <-> {t.get('b')}: trust {v['trust']}, tension {v['tension']}"
        elif k == "location":
            body = "; ".join(f"{w} at {p}" for w, p in (v or {}).get("at", {}).items()) + (f"; locked: {', '.join(v['locked'])}" if (v or {}).get("locked") else "")
        elif k == "knowledge":
            body = "; ".join(f"{s}: known by {', '.join(w) or 'nobody'}" for s, w in (v or {}).items())
        else:
            body = "yes" if v else "no"
        lines.append(f"[{t['name']}] ({k}) {body}")
    ents = state.get("entities") or {}
    if ents:
        lines.append("People: " + "; ".join(f"{n} ({'alive' if e['alive'] else 'DEAD'}{', ' + e['status'] if e.get('status') else ''})" for n, e in ents.items()))
    return "\n".join(lines)


# ── changing the state ────────────────────────────────────────────────────────

@dataclass
class Ctx:
    trackers: list[dict]
    entity_names: list[str]
    place_names: list[str]
    exists_text: str = ""
    allow_death: bool = True
    place_text: dict = field(default_factory=dict)


def _toks(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", norm(s))) - {"the", "a", "an", "of"}


def _same(a: str, b: str) -> bool:
    """Names written a little differently still match: the words of one are all in the other ("Main Entrance" and "The Main Entrance"), or most of the words are shared. Numbers count ("Aisle 4" is not "Aisle 10")."""
    wa, wb = _toks(a), _toks(b)
    if not wa or not wb:
        return False
    if wa <= wb or wb <= wa:
        return True
    return len(wa & wb) / min(len(wa), len(wb)) >= 0.75


def pick(pool: dict, name: str) -> str | None:
    """The real name for a name the model wrote: exact first, then a close one when exactly one candidate is close."""
    n = norm(name)
    if not n:
        return None
    if n in pool:
        return pool[n]
    hits = {v for k, v in pool.items() if _same(k, n)}
    return next(iter(hits)) if len(hits) == 1 else None


def find_tracker(trackers: list[dict], ref: str, kinds: tuple[str, ...], hints: tuple[str, ...] = ()) -> dict | None:
    """The tracker an operation means. The real model often leaves `tracker` empty or writes a name a little differently, so: exact id or name, then a close name, then a hint (the person
    or thing the operation names) matched against the tracker's owner or name, then the only tracker of that kind."""
    pool = [t for t in trackers if t["kind"] in kinds]
    if ref:
        t = next((t for t in pool if t["id"] == ref or norm(t["name"]) == norm(ref)), None) or next((t for t in pool if _same(t["name"], ref)), None)
        if t:
            return t
    for h in hints:
        if not h:
            continue
        t = next((t for t in pool if norm(t.get("owner", "")) == norm(h) or norm(t.get("a", "")) == norm(h) or norm(t.get("b", "")) == norm(h)), None) or next((t for t in pool if _same(t["name"], h)), None)
        if t:
            return t
    return pool[0] if len(pool) == 1 and not ref else None                 # a name that was given but matches nothing is never guessed


def _find_tracker(ctx: Ctx, ref: str, kinds: tuple[str, ...], hints: tuple[str, ...] = ()) -> dict | None:
    return find_tracker(ctx.trackers, ref, kinds, hints)


def apply_ops(state: dict, ops: list, ctx: Ctx) -> tuple[dict, list[dict], list[dict]]:
    """Returns (new state, applied, dropped). A dropped operation says why, so the owner can see what the model tried that the rules refused."""
    st = copy.deepcopy(state)
    applied: list[dict] = []
    dropped: list[dict] = []
    ents = {norm(n): n for n in ctx.entity_names}
    places = {norm(n): n for n in ctx.place_names}
    removed: set[str] = set()

    def drop(op, why):
        dropped.append({"op": op.op, "target": op.target, "why": why})

    def ok(op, text):
        applied.append({"op": op.op, "text": text, "why": op.why})

    for op in ops:
        if op.op not in OPS:
            drop(op, "unknown operation")
            continue
        who = pick(ents, op.who) if op.who else None
        if op.who and not who:
            if pick(places, op.who) or (_words(op.who) & _words(ctx.exists_text)):       # the model sometimes puts the place an item comes from in `who`
                op = op.model_copy(update={"who": "", "source": op.source or op.who})
            else:
                drop(op, f"{op.who} is not in the cast")
                continue
        if who and not st["entities"].get(who, {}).get("alive", True):
            drop(op, f"{who} is dead")
            continue
        k = op.op
        if k.startswith("item_"):
            trk = _find_tracker(ctx, op.tracker or op.name, ("items",))
            if not trk:
                holders = [t for t in ctx.trackers if t["kind"] == "items" and any(norm(n) == norm(op.target) for n in st["trackers"].get(t["id"], {}))]
                trk = holders[0] if holders else next((t for t in ctx.trackers if t["kind"] == "items"), None)
            if not trk:
                drop(op, "the story keeps no items")
                continue
            inv = st["trackers"][trk["id"]]
            have = next((n for n in inv if norm(n) == norm(op.target)), None)
            qty = max(1, int(_num(op.qty, 1)))
            if k == "item_add":
                holder = pick(places, op.to) or pick(ents, op.to) or ""
                crafted = bool(op.parts) and all(norm(p) in removed for p in op.parts)
                src = pick(places, op.source) or pick(ents, op.source)
                exists_w = _words(ctx.exists_text) | (_words(ctx.place_text.get(src, "")) if src else set())
                item_ok = bool(have) or bool(_words(op.target) & exists_w) or any(norm(op.target) in norm(n) or norm(n) in norm(op.target) for n in inv)
                src_ok = (not op.source) or bool(src) or bool(_words(op.source) & _words(ctx.exists_text))
                found = item_ok and src_ok
                if not (crafted or found):
                    drop(op, "an item can only appear from a known place that holds it, or be made from items used in the same step")
                    continue
                if have:
                    inv[have]["qty"] += qty
                else:
                    inv[op.target] = {"qty": qty, "at": holder or src or "", "note": ""}
                ok(op, f"+{qty} {op.target}")
            elif k == "item_remove":
                if not have or inv[have]["qty"] < qty:
                    drop(op, f"{op.target} is not there in that amount")
                    continue
                inv[have]["qty"] -= qty
                removed.add(norm(have))
                if inv[have]["qty"] <= 0:
                    del inv[have]
                ok(op, f"-{qty} {op.target}")
            else:
                holder = pick(places, op.to) or pick(ents, op.to)
                if not have or not holder:
                    drop(op, "the item or the new holder is unknown")
                    continue
                inv[have]["at"] = holder
                ok(op, f"{op.target} now at {holder}")
        elif k in ("meter_set", "meter_change"):
            trk = _find_tracker(ctx, op.tracker or op.name, ("meter",), (op.target, op.who))
            if not trk:
                drop(op, "no such meter")
                continue
            lo, hi, cur = float(trk["min"]), float(trk["max"]), float(st["trackers"][trk["id"]])
            new = _num(op.value, cur) if k == "meter_set" else cur + _num(op.amount)
            limit = (hi - lo) / 2
            if abs(new - cur) > limit:
                new = cur + limit * (1 if new > cur else -1)
                dropped.append({"op": k, "target": trk["name"], "why": f"change was larger than half the range; limited to {limit:g}", "partial": True})
            new = max(lo, min(hi, new))
            st["trackers"][trk["id"]] = new
            ok(op, f"{trk['name']} {cur:g} -> {new:g}")
        elif k in ("clock_advance", "clock_set"):
            trk = _find_tracker(ctx, op.tracker or op.name, ("clock",), (op.target, op.who))
            if not trk:
                drop(op, "no such clock")
                continue
            cur, mx = int(st["trackers"][trk["id"]]), int(trk["max"])
            if k == "clock_advance":
                new = cur + max(1, int(_num(op.amount, 1)))
            else:
                new = int(_num(op.value, cur))
                if new < cur and not op.why:
                    drop(op, "a clock only goes back with a reason")
                    continue
            new = max(0, min(mx, new))
            st["trackers"][trk["id"]] = new
            ok(op, f"{trk['name']} {cur}/{mx} -> {new}/{mx}")
        elif k == "relation_change":
            trk = _find_tracker(ctx, op.tracker or op.name, ("relation",), (op.who, op.to, op.target))
            if not trk:
                drop(op, "no such relationship")
                continue
            axis = norm(op.target) if norm(op.target) in ("trust", "tension") else "trust"
            v = st["trackers"][trk["id"]]
            v[axis] = max(REL_MIN, min(REL_MAX, v[axis] + int(_num(op.amount))))
            ok(op, f"{trk['name']} {axis} is now {v[axis]}")
        elif k in ("move", "lock", "unlock"):
            trk = _find_tracker(ctx, op.tracker or op.name, ("location",))
            if not trk:
                drop(op, "the story keeps no locations")
                continue
            v = st["trackers"][trk["id"]]
            if k == "move":
                who_t = pick(ents, op.target)
                place = pick(places, op.to)
                if not who_t or not place:
                    drop(op, "unknown character or place")
                    continue
                if not st["entities"].get(who_t, {}).get("alive", True):
                    drop(op, f"{who_t} is dead")
                    continue
                if place in v["locked"]:
                    drop(op, f"{place} is locked")
                    continue
                v["at"][who_t] = place
                ok(op, f"{who_t} is now at {place}")
            else:
                place = pick(places, op.target)
                if not place:
                    drop(op, "unknown place")
                    continue
                if k == "lock" and place not in v["locked"]:
                    v["locked"].append(place)
                if k == "unlock" and place in v["locked"]:
                    v["locked"].remove(place)
                ok(op, f"{place} {'locked' if k == 'lock' else 'unlocked'}")
        elif k == "learn":
            trk = _find_tracker(ctx, op.tracker or op.name, ("knowledge",))
            who_t = pick(ents, op.who) or pick(ents, op.to)
            if not trk or not who_t:
                drop(op, "no knowledge tracker or unknown character")
                continue
            if not st["entities"].get(who_t, {}).get("alive", True):
                drop(op, f"{who_t} is dead")
                continue
            secret = next((s for s in st["trackers"][trk["id"]] if norm(s) == norm(op.target)), op.target)
            lst = st["trackers"][trk["id"]].setdefault(secret, [])
            if who_t not in lst:
                lst.append(who_t)
            ok(op, f"{who_t} learns {secret}")
        elif k == "flag_set":
            trk = _find_tracker(ctx, op.tracker or op.target or op.name, ("flag",))
            if not trk:
                drop(op, "no such flag")
                continue
            val = op.value if isinstance(op.value, bool) else str(op.value).strip().lower() in ("true", "yes", "1", "on")
            st["trackers"][trk["id"]] = val
            ok(op, f"{trk['name']} is {'on' if val else 'off'}")
        elif k == "entity_status":
            t = pick(ents, op.target)
            if not t:
                drop(op, "unknown character")
                continue
            if not st["entities"].get(t, {}).get("alive", True):
                drop(op, f"{t} is dead")
                continue
            st["entities"][t]["status"] = str(op.value or "")[:120]
            ok(op, f"{t}: {st['entities'][t]['status']}")
        elif k == "entity_dies":
            t = pick(ents, op.target)
            if not t or t not in st["entities"]:
                drop(op, "unknown character")
                continue
            if not st["entities"][t]["alive"]:
                drop(op, f"{t} is already dead")
                continue
            if not op.why:
                drop(op, "a death needs a reason")
                continue
            if not ctx.allow_death:
                drop(op, "no roll or event allows a death in this chapter")
                continue
            st["entities"][t].update(alive=False, status="dead")
            ok(op, f"{t} dies")
    return st, applied, dropped
