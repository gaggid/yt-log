"""Scoring reference pictures so the best one per item can be approved in one go. Two independent checks, both shown with their reasons:

- measured: simple facts read from the pixels (blank, blurry, subject cut by the frame, background not plain, subject too small or too large);
- looked at: the chat model with vision reads the picture against the brief and lists defects.

The score ranks candidates for one item; it never replaces looking at the picture. A picture with a hard problem is never approved automatically."""
import base64
import json
from collections import Counter
from pathlib import Path

import httpx
from PIL import Image, ImageFilter, ImageStat

from story import llm, settings as settings_mod

AUTO_APPROVE_MIN = 70                   # lowest score the bulk button will approve
SIZE = 256                              # pictures are measured at this size; plenty for these checks
DIMS = [("subject_matches", "shows what the brief describes"), ("whole_subject_visible", "whole subject inside the frame"),
        ("plain_background", "plain, uncluttered backdrop"), ("no_text_or_marks", "free of text, letters, logos, marks"),
        ("anatomy_clean", "clean shapes (no extra limbs, melted parts, odd patterns)"), ("style_fit", "matches the style")]
MINOR = ("slightly", "minor", "a bit", "somewhat", "subtle", "marginal")
SHEET_DIM = ("consistent_poses", "the same subject shown in at least three clearly different poses or views, identical in look in each")
HARD = ("blank", "cut by the frame", "text or marks", "differs from the quoted text", "does not match its description", "does not match its reference", "does not belong to this story")
SCENE_DIMS = [("subject_matches", "shows the subject and the action described"), ("setting_matches", "setting, period and lighting match the brief"),
              ("characters_match", "every person looks like the description given (age, build, hair, clothes)"),
              ("no_extra_things", "no people or objects that the brief does not mention"), ("anatomy_clean", "hands, faces and bodies are correct (no extra limbs or fingers, no melted parts)"),
              ("composition_ok", "composition as briefed, one clear focal point"), ("style_fit", "matches the style"),
              ("story_fit", "belongs to this story's own world: period, place, people and subject match the story summary and the narration, with no generic or unrelated imagery")]


def _bg(im: Image.Image) -> tuple[int, int, int]:
    w, h = im.size
    px = im.load()
    ring = [px[x, y] for x in range(0, w, 3) for y in (0, h - 1)] + [px[x, y] for y in range(0, h, 3) for x in (0, w - 1)]
    q = Counter((r // 16, g // 16, b // 16) for r, g, b in ring).most_common(1)[0][0]
    near = [c for c in ring if (c[0] // 16, c[1] // 16, c[2] // 16) == q]
    return tuple(sum(c[i] for c in near) // len(near) for i in range(3))


def measure(path: Path | str, kind: str, want_size: tuple[int, int] | None = None) -> dict:
    """Facts from the pixels. Returns a 0-100 score, the reasons that cost points, and the raw numbers."""
    im = Image.open(path).convert("RGB")
    full = im.size
    im.thumbnail((SIZE, SIZE))
    w, h = im.size
    grey = im.convert("L")
    stat = ImageStat.Stat(grey)
    edges = ImageStat.Stat(grey.filter(ImageFilter.FIND_EDGES)).mean[0]
    out: dict = {"width": full[0], "height": full[1], "contrast": round(stat.stddev[0], 1), "edge_strength": round(edges, 2), "reasons": []}
    score = 100
    if stat.stddev[0] < 6:
        out.update(score=0, reasons=["blank: the picture has almost no detail"])
        return out
    if want_size and abs(full[0] / full[1] - want_size[0] / want_size[1]) > 0.03:
        score -= 10
        out["reasons"].append(f"shape {full[0]}x{full[1]} differs from the {want_size[0]}x{want_size[1]} asked for")
    if edges < 1.2:
        score -= 20
        out["reasons"].append("looks blurry or flat")
    if kind in ("person", "prop"):
        bg = _bg(im)
        px = im.load()
        diff = [[sum(abs(px[x, y][i] - bg[i]) for i in range(3)) > 70 for x in range(w)] for y in range(h)]
        ring = [diff[y][x] for y in range(h) for x in range(w) if x < 3 or y < 3 or x >= w - 3 or y >= h - 3]
        plain = 1 - sum(ring) / len(ring)
        rows = [y for y in range(h) if sum(diff[y]) >= max(2, w * 0.01)]
        cols = [x for x in range(w) if sum(diff[y][x] for y in range(h)) >= max(2, h * 0.01)]
        out["background_plain"] = round(plain, 2)
        if not rows or not cols:
            out.update(score=0, reasons=["blank: no subject stands out from the backdrop"])
            return out
        top, bottom, left, right = rows[0], rows[-1], cols[0], cols[-1]
        cover_h, cover_w = (bottom - top + 1) / h, (right - left + 1) / w
        out["subject_height"], out["subject_width"] = round(cover_h, 2), round(cover_w, 2)
        edge = max(2, int(0.015 * min(w, h)))
        cut = [n for n, hit in (("top", top < edge), ("bottom", bottom >= h - edge), ("left", left < edge), ("right", right >= w - edge)) if hit]
        if cut:
            score -= 35
            out["reasons"].append("subject is cut by the frame (" + ", ".join(cut) + ")")
        if plain < 0.92:
            score -= 20
            out["reasons"].append("the backdrop is not plain")
        lo, hi, dim = (0.55, 0.97, cover_h) if kind == "person" else (0.30, 0.90, max(cover_h, cover_w))
        if dim < lo:
            score -= 15
            out["reasons"].append("the subject is small in the frame")
        elif dim > hi and not cut:
            score -= 10
            out["reasons"].append("the subject fills almost the whole frame")
    out["score"] = max(0, score)
    return out


def _brief(row: dict, style: str) -> str:
    return (f"Subject: {row['name']} ({row['kind']}). {row['description']} "
            + (f"Always the same: {'; '.join(row['fixed'])}. " if row["fixed"] else "")
            + {"person": "A character model sheet on a pure white background: the same person in at least three different poses (standing, walking, seated or leaning, a face close-up), whole bodies visible, identical face, hair and clothing in every pose. ",
               "prop": "An object model sheet on a pure white background: the same object from at least three views, identical in every view, with no people, hands or emblems anywhere. ",
               "place": "An empty establishing view with a clear layout. "}[row["kind"]]
            + (f"Style: {style} " if style else "") + "No text, letters, numbers, logos or watermarks.")


def dims_for(kind: str) -> list[tuple[str, str]]:
    if kind == "scene":
        return SCENE_DIMS
    return DIMS + [SHEET_DIM] if kind in ("person", "prop", "narrator") else DIMS


def _prompt(brief: str, kind: str = "place") -> str:
    keys = ", ".join(f'"{k}": 0-10' for k, _ in dims_for(kind))
    guide = "; ".join(f"{k} = {d}" for k, d in dims_for(kind))
    extra = ""
    if kind == "scene":
        extra = ', "text_read": "all readable text exactly as written in the picture, or an empty string", "extras": ["people or objects visible that the brief does not mention"]'
    what = "finished scene picture" if kind == "scene" else "reference picture"
    return (f"You are a strict art director checking a {what} for an illustrated story video.\nBRIEF: {brief}\n\n"
            f"Score each point from 0 to 10 ({guide}). Be harsh: 10 means flawless, a good usable picture is 7, and anything you would ask an artist to redo is 5 or lower. "
            "List every concrete defect you can see (for example an odd colour on a hand, extra fingers, a melted shape, a pattern that makes no sense, something missing from the brief). "
            f'Reply with JSON only: {{{keys}, "text_visible": true or false{extra}, "defects": ["short, concrete"]}}')


async def look(path: Path | str, row: dict, style: str, s: dict | None = None, key: str = "") -> dict:
    """The chat model with vision reads the picture against the brief. Raises on a transport problem so the caller can say so."""
    s = s or settings_mod.get()
    b64 = base64.b64encode(Path(path).read_bytes()).decode()
    brief = row["brief"] if row["kind"] == "scene" else _brief(row, style)
    msg = [{"role": "user", "content": [{"type": "text", "text": _prompt(brief, row["kind"])},
                                       {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}}]}]
    async with httpx.AsyncClient(timeout=300) as c:
        r = await c.post(s["base_url"].rstrip("/") + "/chat/completions", headers={"Authorization": f"Bearer {key or settings_mod.api_key()}"},
                         json={"model": s["model"], "messages": msg, "max_tokens": 3000, "temperature": 0})
    if r.status_code != 200:
        raise RuntimeError(f"the vision check was refused ({r.status_code}): {r.text[:160]}")
    j = llm.parse_json(r.json()["choices"][0]["message"].get("content") or "")
    dims = {k: max(0, min(10, float(j.get(k, 0)))) for k, _ in dims_for(row["kind"])}
    defects = [str(x).strip() for x in (j.get("defects") or []) if str(x).strip() and str(x).strip().lower() not in ("none", "n/a")][:5]
    major = [d for d in defects if not any(w in d.lower() for w in MINOR)]                 # "slightly blocky" is shown but not penalised
    score = round(sum(dims.values()) / len(dims) * 10 - 6 * min(len(major), 3))
    out = {"dims": dims, "defects": defects, "text_visible": bool(j.get("text_visible")), "score": max(0, min(100, score))}
    if row["kind"] == "scene":
        out["text_read"] = str(j.get("text_read") or "")
        out["extras"] = [str(x).strip() for x in (j.get("extras") or []) if str(x).strip() and str(x).strip().lower() not in ("none", "n/a")][:4]
    return out


def combine(auto: dict, seen: dict | None) -> dict:
    """One ranking number with its parts, so the screen can say why. Without the vision check the measured score stands alone."""
    flags = list(auto["reasons"])
    hard = any(any(h in r for h in HARD) for r in flags)
    if seen:
        flags += [f"looks wrong: {d}" for d in seen["defects"]]
        if seen["text_visible"]:
            flags.append("text or marks in the picture")
            hard = True
        total = round(0.5 * auto["score"] + 0.5 * seen["score"])
    else:
        total = auto["score"]
    if auto["score"] == 0:
        hard = True
    return {"total": min(total, 49) if hard else total, "measured": auto["score"], "looked_at": seen["score"] if seen else None, "flags": flags, "hard": hard}


def _norm(x: str) -> str:
    return "".join(ch for ch in x.lower() if ch.isalnum())


def combine_scene(auto: dict, seen: dict | None, quoted: list[str], with_reference: bool = False) -> dict:
    """Ranking score for a scene picture. On top of the reference checks: quoted text must be read back exactly, a picture with no quoted text must
    carry no writing, and a character that does not look like its description (or sheet) is a hard problem."""
    flags = list(auto["reasons"])
    hard = any(any(h in r for h in HARD) for r in flags)
    if seen:
        read = _norm(seen.get("text_read", ""))
        for q in quoted:
            if _norm(q) and _norm(q) not in read:
                flags.append(f'text differs from the quoted text "{q}" (read: "{seen.get("text_read", "").strip()[:60]}")')
                hard = True
        if not quoted and (seen["text_visible"] or read):
            flags.append("text or marks in the picture")
            hard = True
        flags += [f"looks wrong: {d}" for d in seen["defects"]]
        flags += [f"not in the brief: {x}" for x in seen.get("extras", [])]
        if seen["dims"].get("story_fit", 10) <= 4:
            flags.append("the picture does not belong to this story (its period, place or subject do not match the story)")
            hard = True
        if seen["dims"].get("characters_match", 10) <= 4:
            flags.append("a character does not match its reference sheet" if with_reference else "a character does not match its description")
            hard = True
        total = round(0.5 * auto["score"] + 0.5 * seen["score"] - 4 * min(len(seen.get("extras", [])), 3))
    else:
        total = auto["score"]
    if auto["score"] == 0:
        hard = True
    total = max(0, total)
    return {"total": min(total, 49) if hard else total, "measured": auto["score"], "looked_at": seen["score"] if seen else None, "flags": flags, "hard": hard}
