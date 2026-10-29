"""The repair sweep for the world rules (docs/TASKS_quality_overhaul.md task 3.11; audit 14.4): a film where the same face is in half the pictures feels small however many
places it visits. The storyboard is asked for variety; when it still comes back with too many scenes that show a face (or the main person, or a run of face close-ups), this
sweep, in code, turns the repeating ones into a picture of the event's key object or of the place (hands, an object on a table, the lane without anyone in the foreground).

Rules held: at most `MAX_PERSON_SHARE` of the scenes show a person (so at least 45% are face-free), the main person is in at most `MAX_PROTAGONIST` of the scenes, and no more than
`MAX_CLOSEUP_RUN` face close-ups follow each other. Scenes that are locked, are world inserts, tell a reveal, or have no object or place to show are never touched."""
from story import db

from . import audit, events as events_mod, planner, storyboard, store

MAX_PERSON_SHARE = 0.55
MAX_PROTAGONIST = 0.35
MAX_CLOSEUP_RUN = 2


def _state(plan: dict, scenes: list[dict]) -> dict:
    people = audit._people(plan)
    who = [audit._scene_people(s, people) for s in scenes]
    counts: dict[str, int] = {}
    for w in who:
        for n in set(w):
            counts[n] = counts.get(n, 0) + 1
    main = max(counts, key=counts.get) if counts else ""
    return {"people": people, "who": who, "main": main, "counts": counts}


def _close(s: dict) -> bool:
    return "close" in str((s["data"].get("composition") or {}).get("distance", "")).lower()


def _object_for(plan: dict, scene: dict, places: dict[str, dict]) -> tuple[str, str]:
    """(what to show, a place detail) for a scene: the key object of its event, else the first thing that makes its place recognisable, else the first prop."""
    d = scene["data"]
    ev = next((e for e in events_mod.of(plan) if e["id"] == d.get("event")), {})
    obj = str(ev.get("key_object") or "").strip()
    loc = str((d.get("setting") or {}).get("location") or "").lower()
    asset = places.get(loc) or next((a for n, a in places.items() if n and (n in loc or loc in n)), None)
    detail = ""
    if asset:
        fixed = (asset["data"].get("fixed") or []) + [str((asset["data"].get("appearance") or {}).get("signature", ""))]
        detail = next((str(x) for x in fixed if str(x).strip()), "")
    if not obj:
        props = (d.get("setting") or {}).get("props") or []
        obj = str(props[0]) if props else detail
    return obj, detail


def convert(scene: dict, obj: str, detail: str, place_ids: list[str]) -> dict:
    """The scene data with the people taken out and the object (or the place's detail) as the subject. Camera: a close look at the object, or a wide look at the empty place."""
    d = dict(scene["data"])
    comp = dict(d.get("composition") or {})
    comp.update({"distance": "close" if obj else "wide", "camera_angle": "high" if obj else "eye level", "position": "centre"})
    where = (d.get("setting") or {}).get("location") or "the place"
    d.update({"subject": obj or detail or where, "action": f"{obj or detail} rests in view in {where}, shot as an object study" if (obj or detail) else f"{where} in a still moment, shot as a place study",
              "composition": comp, "prompts": {}, "adapters": {}, "converted": True})
    d["continuity"] = {**(d.get("continuity") or {}), "assets": place_ids, "use_ref_assets": place_ids}
    d["layers"] = {"foreground": obj or detail, "middle": where, "background": ""}
    return d


def _done(plan_id: str, changed: int) -> int:
    if changed:
        store.log(plan_id, "world_sweep", {"changed": changed})
    return changed


def sweep(plan_id: str, max_rounds: int = 200) -> int:
    """Convert face scenes until the rules hold or nothing more can be converted. Returns how many scenes were changed."""
    changed = 0
    for _ in range(max_rounds):
        plan = planner.get_plan(plan_id)
        scenes = sorted(storyboard.get_scenes(plan_id), key=lambda s: (s["start_s"], s["seq"]))
        if not scenes:
            return _done(plan_id, changed)
        st = _state(plan, scenes)
        n = len(scenes)
        with_person = [bool(w) for w in st["who"]]
        run = best = 0
        run_end = -1
        for i, s in enumerate(scenes):
            if with_person[i] and _close(s):
                run += 1
                if run > MAX_CLOSEUP_RUN:
                    run_end = i
                best = max(best, run)
            else:
                run = 0
        too_many = sum(with_person) / n > MAX_PERSON_SHARE
        too_main = bool(st["main"]) and st["counts"].get(st["main"], 0) / n > MAX_PROTAGONIST
        if not (too_many or too_main or best > MAX_CLOSEUP_RUN):
            return _done(plan_id, changed)
        places = {a["name"].lower(): a for a in plan["assets"] if a["kind"] == "place"}
        by_place_id = {a["name"].lower(): a["id"] for a in plan["assets"] if a["kind"] == "place"}
        order = [run_end] if best > MAX_CLOSEUP_RUN and run_end >= 0 else []
        order += [i for i in range(n) if with_person[i] and (not too_main or st["main"] in st["who"][i]) and i not in order]
        done = False
        for i in order:
            s = scenes[i]
            if s["locked"] or s["data"].get("insert") or s["data"].get("converted") or (s["data"].get("narrative") or {}).get("emotional_effect", "") == "reveal":
                continue
            ev = next((e for e in events_mod.of(plan) if e["id"] == s["data"].get("event")), {})
            if ev.get("reveal"):
                continue
            obj, detail = _object_for(plan, s, places)
            if not (obj or detail):
                continue
            loc = str((s["data"].get("setting") or {}).get("location") or "").lower()
            pid = by_place_id.get(loc) or next((v for k, v in by_place_id.items() if k and (k in loc or loc in k)), "")
            data = convert(s, obj, detail, [pid] if pid else [])
            db.ex("UPDATE scenes SET data=?, rev=rev+1, updated_at=? WHERE id=?", (db.jdump(data), db.now(), s["id"]))
            changed += 1
            done = True
            break
        if not done:
            return _done(plan_id, changed)
    return _done(plan_id, changed)
