"""Reading and publishing later (docs/PLAN_simulation.md section 13): the current line of the story as Markdown, JSON or a zip with the pictures in order. The chapter JSON is the contract of a later
"chapter to video" step: narration = prose, shots = panels in order, cast = look texts."""
import io
import json
import zipfile

import config

from . import store


def _panels(c: dict) -> list[dict]:
    return [p for p in c.get("panels", []) if p.get("file")]


def chapter_json(pid: str) -> dict:
    p = store.project(pid)
    ents = store.entities(pid)
    chapters = store.path(pid)
    return {"title": p["title"], "idea": p["idea"], "world": store.world(pid),
            "cast": [{"name": e["name"], "kind": e["kind"], "role": e.get("role", ""), "look": e.get("look", "")} for e in ents],
            "chapters": [{"n": c["idx"], "title": c["title"], "story_time": c["story_time"], "prose": c["prose"], "summary": c["summary"], "focus": c["focus"],
                          "panels": [{"file": f"images/{c['idx']:02d}-{i}.png", "caption": x.get("caption", ""), "shot": x.get("shot", ""), "who": x.get("who", []), "place": x.get("place", ""),
                                      "action": x.get("action", "")} for i, x in enumerate(_panels(c), 1)]} for c in chapters if c["status"] == "done"]}


def markdown(pid: str) -> str:
    j = chapter_json(pid)
    out = [f"# {j['title']}", "", f"*{j['idea']}*", ""]
    for c in j["chapters"]:
        out += [f"## Chapter {c['n']}: {c['title']}", f"*{c['story_time']}*", ""]
        for x in c["panels"]:
            out += [f"![{x['caption']}]({x['file']})", f"*{x['caption']}*", ""]
        out += [c["prose"], ""]
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
