"""Moving a story around (docs/PLAN_simulation.md section 10): export the setup (or everything but the pictures) as one JSON, import it as a new story, duplicate a story. Ids are made new on the way
in; the places that refer to them (tracker ids inside saved states, instruction ids inside chapters, parent links) are rewritten."""
import json

from story import db

from . import store

FORMAT = 1


def export_data(pid: str, full: bool = False) -> dict:
    p = store.project(pid)
    out = {"format": FORMAT, "kind": "full" if full else "setup", "project": {"title": p["title"], "idea": p["idea"], "settings": p["settings"]},
           "world": store.world(pid), "entities": [{k: v for k, v in e.items() if k != "project_id"} for e in store.entities(pid, active_only=False)],
           "trackers": [{k: v for k, v in t.items() if k != "project_id"} for t in store.trackers(pid, active_only=False)],
           "guidelines": [{"grp": g["grp"], "text": g["text"], "enabled": g["enabled"], "origin": g["origin"]} for g in store.guidelines(pid)]}
    if full:
        out["directives"] = [{k: v for k, v in d.items() if k != "project_id"} for d in store.directives(pid)]
        out["chapters"] = [{k: v for k, v in c.items() if k != "project_id"} for c in store.chapters(pid)]
        out["facts"] = [{k: v for k, v in f.items() if k != "project_id"} for f in store.facts(pid)]
        out["threads"] = [{k: v for k, v in t.items() if k != "project_id"} for t in store.threads(pid)]
        out["head_id"] = p["head_id"]
        out["status"] = p["status"]
    return out


def import_data(data: dict, title_suffix: str = "") -> dict:
    if not isinstance(data, dict) or data.get("format") != FORMAT or "project" not in data:
        raise store.SimError("this file is not a story export")
    pj = data["project"]
    p = store.create_project(pj.get("idea") or "imported story", (pj.get("title") or "Imported story") + title_suffix)
    pid = p["id"]
    st = {k: v for k, v in (pj.get("settings") or {}).items() if k in store.DEFAULT_SETTINGS and k != "seed"}
    store.save_project(pid, settings=st)
    store.set_world(pid, data.get("world") or {})
    for g in data.get("guidelines", []):
        store.save_guideline(pid, {**g, "origin": g.get("origin", "owner")})
    for e in data.get("entities", []):
        store.save_entity(pid, {k: v for k, v in e.items() if k not in ("id", "active")})
    tmap: dict[str, str] = {}
    for t in data.get("trackers", []):
        new = store.save_tracker(pid, {k: v for k, v in t.items() if k != "id"})
        tmap[t["id"]] = new["id"]
    if data.get("kind") != "full":
        return store.project(pid)
    dmap: dict[str, str] = {}
    for d in data.get("directives", []):
        new = store.save_directive(pid, {"kind": d["kind"], "text": d["text"], "timing": d["timing"]})
        if d.get("status") == "cancelled":
            store.cancel_directive(pid, new["id"])
        dmap[d["id"]] = new["id"]
    cmap: dict[str, str] = {}
    for c in sorted(data.get("chapters", []), key=lambda x: (x["idx"], x["created_at"])):
        new = store.add_chapter(pid, cmap.get(c["parent_id"], ""), c.get("branch_label", ""))
        cmap[c["id"]] = new["id"]
        fields = {k: c[k] for k in ("title", "prose", "story_time", "summary", "focus", "plan", "rolls", "delta", "options", "chosen", "flags", "status") if k in c}
        for k in ("state_before", "state_after"):
            fields[k] = {**c[k], "trackers": {tmap.get(i, i): v for i, v in c[k].get("trackers", {}).items()}}
        fields["fired"] = [dmap.get(i, i) for i in c.get("fired", [])]
        fields["plan"] = {**fields.get("plan", {}), "addresses": [dmap.get(i, i) for i in fields.get("plan", {}).get("addresses", [])]}
        fields["panels"] = []
        store.update_chapter(new["id"], **fields)
    for f in data.get("facts", []):
        if f["chapter_id"] in cmap:
            store.add_fact(pid, cmap[f["chapter_id"]], f["text"], f["entity_names"], f["tags"])
    for t in data.get("threads", []):
        if t["opened_in"] in cmap:
            tid = store.add_thread(pid, cmap[t["opened_in"]], t["text"])
            if t.get("closed_in") in cmap:
                store.close_thread(tid, cmap[t["closed_in"]])
    store.save_project(pid, head_id=cmap.get(data.get("head_id", ""), ""), status=data.get("status", "setup"))
    return store.project(pid)


def duplicate(pid: str, full: bool = False) -> dict:
    return import_data(json.loads(json.dumps(export_data(pid, full))), " (copy)")


def as_template(pid: str) -> dict:
    """What a saved template keeps of a story: its tone, rules, settings and the kinds of things it tracked (without the people and places of this one story)."""
    p = store.project(pid)
    w = store.world(pid)
    keep = ("items", "meter", "clock", "flag")
    return {"tone": w.get("tone", ""), "pacing": w.get("pacing", ""), "hint": f"Based on the story '{p['title']}'.",
            "settings": {k: p["settings"][k] for k in ("difficulty", "dice", "chapter_words", "deep", "panel_shape", "captions")},
            "rules": [(g["grp"], g["text"]) for g in store.guidelines(pid, enabled_only=True)],
            "trackers": [(t["kind"], t["name"], t.get("description", "")) for t in store.trackers(pid) if t["kind"] in keep]}
