"""Reading and publishing later (docs/PLAN_simulation.md section 13): the current line of the story as Markdown, JSON or a zip with the pictures in order. The chapter JSON is the contract of a later
"chapter to video" step: narration = prose, shots = panels in order, cast = look texts."""
import io
import json
import zipfile

import config

from . import store


def _panels(c: dict) -> list[dict]:
    return [p for p in c.get("panels", []) if p.get("file")]


def _at(c: dict) -> list[int]:
    """The paragraph after which each finished picture shows."""
    from . import paint
    return paint.placement(_panels(c), len(paint.paragraphs(c.get("prose", ""))))


def chapter_json(pid: str) -> dict:
    p = store.project(pid)
    ents = store.entities(pid)
    chapters = store.path(pid)
    plan = store.bible(pid)
    return {"title": p["title"], "idea": p["idea"], "world": store.world(pid),
            "plan": ({"logline": plan.get("logline", ""), "pov": plan.get("pov", ""), "voice": plan.get("voice", ""), "rules": plan.get("rules", []), "motifs": plan.get("motifs", []), "facts": plan.get("facts", []), "ending": plan.get("ending", {})} if plan else None),
            "cast": [{"name": e["name"], "kind": e["kind"], "role": e.get("role", ""), "look": e.get("look", ""), "skills": e.get("skills", [])} for e in ents],
            "chapters": [{"n": c["idx"], "title": c["title"], "story_time": c["story_time"], "prose": c["prose"], "summary": c["summary"], "focus": c["focus"],
                          "beat": (c.get("flags") or {}).get("beat", {}).get("label", ""), "things": [a["text"] for a in c["delta"].get("applied", []) if a.get("op") in ("discover", "craft", "item_give", "item_take", "item_use", "item_change", "skill_learn") and not a.get("undone")],
                          "panels": [{"file": f"images/{c['idx']:02d}-{i}.png", "caption": x.get("caption", ""), "shot": x.get("shot", ""), "who": x.get("who", []), "place": x.get("place", ""),
                                      "action": x.get("action", ""), "after": at} for i, (x, at) in enumerate(zip(_panels(c), _at(c)), 1)]} for c in chapters if c["status"] == "done"]}


def markdown(pid: str) -> str:
    j = chapter_json(pid)
    out = [f"# {j['title']}", "", f"*{j['idea']}*", ""]
    for c in j["chapters"]:
        out += [f"## Chapter {c['n']}: {c['title']}", f"*{c['story_time']}*", ""]
        paras = [x.strip() for x in c["prose"].split("\n") if x.strip()] or [c["prose"]]
        for i, para in enumerate(paras, 1):                                    # each picture sits after the paragraph it illustrates
            out += [para, ""]
            for x in c["panels"]:
                if (x["after"] or len(paras)) == i:
                    out += [f"![{x['caption']}]({x['file']})", f"*{x['caption']}*", ""]
    return "\n".join(out)


def zipped(pid: str) -> bytes:
    j = chapter_json(pid)
    buf = io.BytesIO()
    base = config.DATA_DIR / "media" / pid
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("story.md", markdown(pid))
        z.writestr("chapters.json", json.dumps(j, indent=1, ensure_ascii=False))
        for c in store.path(pid):
            if c["status"] != "done":
                continue
            for i, x in enumerate(_panels(c), 1):
                f = base / (x.get("capfile") or x["file"])
                if f.is_file():
                    z.write(f, f"images/{c['idx']:02d}-{i}.png")
    return buf.getvalue()


def reading_minutes(pid: str) -> int:
    words = sum(len(c["prose"].split()) for c in store.path(pid))
    return max(1, round(words / 220))
