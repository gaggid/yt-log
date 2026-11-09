"""From an idea to a playable setup (docs/PLAN_simulation.md section 10). Four parts, each its own model call so any can be redone alone; all land in editable forms."""
import json

from . import architect, content, memory, models as m, prompts as P, state as S, store, templates
from .engine import _json, fence

PARTS = ("world", "cast", "trackers", "rules", "bible")


def _idea_block(pid: str) -> str:
    p = store.project(pid)
    t = templates.get(p["settings"].get("template_id", ""))
    return f"CONTENT: {content.text(p['settings'])}\n\nIDEA: {fence(p['idea'])}\n" + (templates.hint_text(t) + "\n" if templates.hint_text(t) else "")


def _cast_text(pid: str) -> str:
    return "\n".join(memory.card(e, {}) + (f" Look: {e['look']}" if e.get("look") else "") for e in store.entities(pid, active_only=False)) or "(none yet)"


def _note(instruction: str) -> str:
    return f"\n\nOWNER'S NOTE FOR THIS REDO: {fence(instruction)}" if instruction.strip() else ""


async def seed_world(pid, backend, s, instruction="") -> dict:
    cur = store.world(pid)
    user = _idea_block(pid) + (f"CURRENT WORLD CARD (improve it, keep what is good): {json.dumps(cur)}\n" if instruction.strip() and cur else "") + _note(instruction) + "\n\nWrite the world card now."
    w = await _json(backend, s, P.WORLD, user, m.WorldOut)
    data = {k: v for k, v in w.model_dump().items() if k != "title"}
    store.set_world(pid, data)
    proj = store.project(pid)
    if w.title and proj["title"] == proj["idea"][:60]:
        store.save_project(pid, title=w.title[:80])
    return data


async def seed_cast(pid, backend, s, instruction="") -> list[dict]:
    if store.project(pid)["status"] != "setup":
        raise store.SimError("the cast can only be redone before the story starts; edit people one by one now")
    user = _idea_block(pid) + f"WORLD:\n{memory.world_text(store.world(pid))}\n" + _note(instruction) + "\n\nCreate the cast and places now."

    def v(o: m.CastOut, caller):
        if len([e for e in o.entities if e.kind == "character"]) < 3 and not caller.last_attempt:
            raise ValueError("create at least 3 characters")
        if not [e for e in o.entities if e.kind == "place"] and not caller.last_attempt:
            raise ValueError("create at least one place")

    o = await _json(backend, s, P.CAST, user, m.CastOut, v)
    store.clear_entities(pid)
    store.clear_trackers(pid)                          # trackers refer to people and places by name
    used: set[str] = set()
    for i, e in enumerate(o.entities[:16]):
        name = e.name.strip()
        base, n = name, 2
        while name.lower() in used:
            name, n = f"{base} {n}", n + 1
        used.add(name.lower())
        kind = e.kind if e.kind in store.ENTITY_KINDS else "character"
        data = {k: v for k, v in e.model_dump().items() if k not in ("name", "kind") and v not in ("", [], {})}
        store.save_entity(pid, {"kind": kind, "name": name, "position": i, **data})
    return store.entities(pid)


async def seed_trackers(pid, backend, s, instruction="") -> list[dict]:
    if store.project(pid)["status"] != "setup":
        raise store.SimError("trackers can only be redone before the story starts; edit them one by one now")
    ents = store.entities(pid)
    user = (_idea_block(pid) + f"WORLD:\n{memory.world_text(store.world(pid))}\n\nCAST AND PLACES:\n{_cast_text(pid)}\n" + _note(instruction) + "\n\nPropose the trackers now.")

    def v(o: m.TrackersOut, caller):
        if not [t for t in o.trackers if t.kind in ("clock", "meter")] and not caller.last_attempt:
            raise ValueError("add at least one clock or meter that puts something at stake")

    o = await _json(backend, s, P.TRACKERS, user, m.TrackersOut, v)
    chars = [e["name"] for e in ents if e["kind"] == "character"]
    places = [e["name"] for e in ents if e["kind"] == "place"]
    store.clear_trackers(pid)
    seen, made = set(), []
    for t in o.trackers[:12]:
        if t.kind not in store.TRACKER_KINDS or not t.name.strip() or t.name.lower() in seen:
            continue
        seen.add(t.name.lower())
        data, _bad = S.normalize_tracker({**t.model_dump(), "name": t.name.strip()}, chars, places)
        if t.kind == "relation" and (not data.get("a") or data["a"] not in chars or data.get("b") not in chars):
            continue
        made.append(store.save_tracker(pid, {**data, "name": t.name.strip()}))
    for t in [t for t in made if t["kind"] == "items" and not t.get("start")]:           # the model left the item list empty: take it from the world card
        user = "WORLD:\n" + memory.world_text(store.world(pid)) + "\n\nPLACES: " + ", ".join(places) + "\n\nList the items now."
        r = await _json(backend, s, P.ITEMS, user, m.ItemsOut)
        data, _bad = S.normalize_tracker({**t, "start": [i.model_dump() for i in r.items[:25]]}, chars, places)
        store.save_tracker(pid, {**data, "id": t["id"], "name": t["name"]})
    made += _relation_trackers(pid, ents, made, chars)
    if not [t for t in made if t["kind"] == "location"] and chars and places:
        made.append(store.save_tracker(pid, {"kind": "location", "name": "Where everyone is", "description": "who is where, and which places are locked",
                                             "start": {"at": {c: places[0] for c in chars}, "locked": []}}))
    return made


COLD = {"rival", "rivals", "enemy", "enemies", "distrust", "distrusts", "hates", "hate", "resents", "resent", "suspicious", "suspects", "estranged", "betrayed", "jealous", "blames", "opposes", "adversary", "feud"}
WARM = {"friend", "friends", "mother", "father", "sister", "brother", "daughter", "son", "partner", "trusts", "loyal", "ally", "allies", "lover", "spouse", "mentor", "protects", "cares", "colleague"}


def _relation_trackers(pid: str, ents: list[dict], made: list[dict], chars: list[str]) -> list[dict]:
    """The cast cards already say how people relate; the pairs that matter become relation trackers (at most three) so that people can clash and bond as the story moves."""
    have = {frozenset((S.norm(t.get("a", "")), S.norm(t.get("b", "")))) for t in made if t["kind"] == "relation"}
    out: list[dict] = []
    for e in ents:
        if e["kind"] != "character":
            continue
        for other, text in (e.get("relations") or {}).items():
            o = S.pick({S.norm(n): n for n in chars}, other)
            pair = frozenset((S.norm(e["name"]), S.norm(o or "")))
            if not o or o == e["name"] or pair in have:
                continue
            if len(out) + len([1 for t in made if t["kind"] == "relation"]) >= 3:
                return out
            words = set(S._toks(str(text)))
            trust, tension = (-1, 2) if words & COLD else (2, 0) if words & WARM else (0, 0)
            out.append(store.save_tracker(pid, {"kind": "relation", "name": f"{e['name']} and {o}", "description": str(text)[:100], "a": e["name"], "b": o, "start": {"trust": trust, "tension": tension}}))
            have.add(pair)
    return out


async def seed_rules(pid, backend, s, instruction="") -> list[dict]:
    user = (_idea_block(pid) + f"WORLD:\n{memory.world_text(store.world(pid))}\n\nCAST AND PLACES:\n{_cast_text(pid)}\n" + _note(instruction) + "\n\nWrite the rules now.")

    def v(o: m.RulesOut, caller):
        if len([r for r in o.rules if r.group == "hard"]) < 2 and not caller.last_attempt:
            raise ValueError("write at least 2 hard rules")

    o = await _json(backend, s, P.RULES, user, m.RulesOut, v)
    store.clear_guidelines(pid, "ai")
    for r in o.rules[:16]:
        store.save_guideline(pid, {"grp": r.group if r.group in store.GROUPS else "hard", "text": r.text, "origin": "ai"})
    return store.guidelines(pid)


async def suggest_rules(pid, backend, s, instruction="") -> list[dict]:
    have = "\n".join(f"[{g['grp']}] {g['text']}" for g in store.guidelines(pid)) or "(none)"
    user = (_idea_block(pid) + f"WORLD:\n{memory.world_text(store.world(pid))}\n\nCAST AND PLACES:\n{_cast_text(pid)}\n\nCURRENT RULES:\n{have}" + _note(instruction) + "\n\nSuggest new rules now.")
    o = await _json(backend, s, P.SUGGEST, user, m.RuleSuggest)
    from .engine import _sim
    made = []
    for r in o.rules[:6]:
        if any(_sim(r.text, g["text"]) > 0.7 for g in store.guidelines(pid)):
            continue
        made.append(store.save_guideline(pid, {"grp": r.group if r.group in store.GROUPS else "hard", "text": r.text, "origin": "ai"}))
    return made


async def seed_part(pid, part, backend, s, instruction="") -> object:
    if part not in PARTS:
        raise store.SimError("part must be world, cast, trackers, rules or bible")
    if part == "bible":
        return await architect.write_bible(pid, backend, s, instruction)
    return await {"world": seed_world, "cast": seed_cast, "trackers": seed_trackers, "rules": seed_rules}[part](pid, backend, s, instruction)


async def seed_all(pid, backend, s, progress=None, cancel=lambda: False) -> None:
    parts = [p for p in PARTS if p != "bible" or store.project(pid)["settings"].get("plan", True)]
    for i, part in enumerate(parts):
        if cancel():
            return
        if progress:
            progress(i, len(parts), f"writing the {'story plan' if part == 'bible' else part}")
        await seed_part(pid, part, backend, s)
    if progress:
        progress(len(parts), len(parts), "setup ready: review it, then Start")
