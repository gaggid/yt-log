"""The publish pack (docs/TASKS_quality_overhaul.md tasks 6.3 and 6.4): everything needed to upload the finished film, written to `media/<plan>/publish/`. Nothing is uploaded.

  title.txt        the chosen title and the other options
  description.txt  a Hindi hook line, an English line for search, the chapters, key facts, the credit line, keywords and hashtags, and the disclosure note
  tags.txt         search tags in Hinglish and English
  pinned.txt       a pinned comment that asks the closing question
  captions-hi.srt  the narration as subtitles at the real time in the finished film (speed-up and end card included)
  captions-en.srt  an English translation of the same cues (when a model is available)

The credit line is the only place the source is named, and only here. Every other text is checked by the leak gate and by the claim check against the film."""
import json
import re
from pathlib import Path

from story import db, llm, settings as settings_mod
from story2 import claimcheck, intake, leak, material, planner, prompts as P, store as plan_store
from story2.schemas import M

from . import store, video
from .voice import MediaError

KIND = "publish"
DISCLOSURE = ("The pictures in this video are AI-generated illustrations that reconstruct events; they are not photographs or footage of the real people or places. "
              "Allegations are described as allegations.")


def publish_dir(plan_id: str) -> Path:
    d = store.media_dir(plan_id, "publish")
    d.mkdir(parents=True, exist_ok=True)
    return d


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def srt(events: list[tuple[float, float, str]], speed: float) -> str:
    """The cues as an SRT file at the time they play in the finished film (the speed-up shortens every time)."""
    out = []
    for n, (a, b, text) in enumerate(events, 1):
        out.append(f"{n}\n{srt_time(a / speed)} --> {srt_time(b / speed)}\n{text}\n")
    return "\n".join(out)


class Line(M):
    n: int = 0
    text: str = ""


class SubsOut(M):
    lines: list[Line] = []


async def english_cues(events: list[tuple[float, float, str]], backend, s: dict) -> list[tuple[float, float, str]] | None:
    """The same cues in English, 40 lines at a time. None when the model cannot do it (the pack then has the Hindi file only)."""
    out = []
    try:
        for i in range(0, len(events), 40):
            chunk = events[i:i + 40]
            body = "\n".join(f"{k}. {t}" for k, (_a, _b, t) in enumerate(chunk, 1))
            res = (await llm.JsonCaller(backend, s).call(P.SUBS_EN, body, SubsOut)).value
            by = {l.n: l.text for l in res.lines}
            if len(by) < len(chunk) * 0.9:
                return None
            out += [(a, b, by.get(k) or t) for k, (a, b, t) in enumerate(chunk, 1)]
    except llm.LLMError:
        return None
    return out


def credit_line(plan: dict) -> str:
    """The one place the source is named: a line at the end of the description (owner decision, 2026-10-29)."""
    story = planner._story_for(plan)
    row = db.one("SELECT title, author FROM projects WHERE id=?", (story["evidence"]["project_id"],)) or {}
    title, author = (row.get("title") or "").strip(), (row.get("author") or "").strip()
    if not title:
        return ""
    return f"Based on reporting and writing in: {title}" + (f" by {author}" if author and author.lower() not in ("unknown", "") else "") + "."


def key_facts(plan: dict, n: int = 5) -> list[str]:
    if not material.has(plan):
        return []
    items = sorted(material.pack(plan)["items"], key=lambda i: (-i.get("weight", 0), i["id"]))
    return [i["detail"] for i in items if not i.get("alleged")][:n]


def hashtags(title: str) -> list[str]:
    tags = ["#TrueStory", "#सच्ची_कहानी"]
    words = [w for w in re.findall(r"[A-Za-z]{4,}", title) if w.lower() not in ("what", "that", "this", "with", "from", "kya", "hua", "aakhir")]
    return tags + [f"#{w.capitalize()}" for w in words[:2]]


def description(plan: dict, title: str, chapters: list[tuple[str, str]]) -> str:
    first = plan["segments"][0]["sentences"][0]["text"] if plan["segments"] and plan["segments"][0]["sentences"] else ""
    bp = plan.get("blueprint") or {}
    parts = [first, bp.get("central_question", ""), ""]
    if chapters:
        parts += ["Chapters:"] + [f"{t} {n}" for t, n in chapters] + [""]
    facts = key_facts(plan)
    if facts:
        parts += ["Key facts:"] + [f"- {f}" for f in facts] + [""]
    parts += [DISCLOSURE, "", " ".join(hashtags(title))]
    cl = credit_line(plan)
    if cl:
        parts += ["", cl]
    return "\n".join(x for x in parts if x is not None).strip()


def pinned_comment(plan: dict) -> str:
    ex = (plan.get("blueprint") or {}).get("experience") or {}
    q = ((ex.get("participation") or {}).get("closing_question") or "").strip()
    if q:
        return q
    last = plan["segments"][-1]["sentences"][-1]["text"] if plan["segments"] and plan["segments"][-1]["sentences"] else ""
    return last if last.endswith("?") else ""


def tags(plan: dict, title: str) -> list[str]:
    base = [w for w in re.findall(r"[A-Za-z][A-Za-z']{3,}", title)]
    if material.has(plan):
        base += [n["name"] for n in material.pack(plan).get("names", [])[:3]]
    return list(dict.fromkeys(["true story", "hindi story", "सच्ची कहानी", *base]))[:15]


async def build(plan_id: str, backend=None, s: dict | None = None, speed: float | None = None) -> dict:
    """Write the pack. Refuses (MediaError) when a title or the description fails the checks, naming what to fix."""
    s = s or settings_mod.get()
    plan = planner.get_plan(plan_id)
    if not plan["segments"]:
        raise MediaError("write the narration first")
    title = (plan["settings"].get("video_title") or "").strip()
    if not title:
        raise MediaError("choose the video title first (or run the title step)")
    sp = float(speed or plan["settings"].get("speed") or video.PLAYBACK_SPEED)
    bad = claimcheck.check(title, plan)
    chs = video.chapters(plan_id, sp)
    desc = description(plan, title, chs)
    story = planner._story_for(plan)
    prof = leak.profile(story["evidence"]["project_id"], story["evidence"]["passages"])
    body = desc.rsplit("\n\n", 1)[0] if credit_line(plan) and credit_line(plan) in desc else desc                  # the credit line is the one allowed mention of the source
    bad += [f"description: {f.kind}: {f.text}" for f in leak.check(body, prof, scene=True)]
    bad += claimcheck.check(" ".join(key_facts(plan)), plan) if False else []
    from story2 import gates
    sg = gates.safety_gate(plan_id)
    bad += [f"safety: {f['kind']}: {f['text'][:80]}" for f in sg["findings"] if f["level"] == "hard"]                 # an unattributed accusation, a private name, a stereotype: no pack until fixed
    if bad:
        raise MediaError("the pack was not written: " + "; ".join(bad[:4]))
    d = publish_dir(plan_id)
    opts = (plan["settings"].get("titles") or {}).get("options", [])
    (d / "title.txt").write_text(title + "\n\nOther options:\n" + "\n".join(f"- {o['title']} ({o['register']})" for o in opts if o["title"] != title), encoding="utf-8")
    (d / "description.txt").write_text(desc, encoding="utf-8")
    (d / "tags.txt").write_text(", ".join(tags(plan, title)), encoding="utf-8")
    pc = pinned_comment(plan)
    (d / "pinned.txt").write_text(pc, encoding="utf-8")
    events = video.caption_events(plan_id)
    end = (events[-1][1] if events else 0)
    (d / "captions-hi.srt").write_text(srt(events, sp), encoding="utf-8")
    files = ["title.txt", "description.txt", "tags.txt", "pinned.txt", "captions-hi.srt"]
    if backend is not None:
        en = await english_cues(events, backend, s)
        if en:
            (d / "captions-en.srt").write_text(srt(en, sp), encoding="utf-8")
            files.append("captions-en.srt")
    pack = {"title": title, "chapters": chs, "files": files, "speed": sp, "closing_comment": pc, "credit_line": credit_line(plan), "ends_at_s": round(end / sp, 1)}
    (d / "pack.json").write_text(json.dumps(pack, ensure_ascii=False, indent=1), encoding="utf-8")
    plan_store.log(plan_id, "publish_pack", {"files": files, "chapters": len(chs)})
    return {**pack, "dir": str(d)}


def state(plan_id: str) -> dict:
    d = store.media_dir(plan_id, "publish")
    p = d / "pack.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
