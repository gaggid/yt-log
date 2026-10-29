"""The audit scorecard: one place that measures a plan against the targets of docs/AUDIT_2026-10-29.md (section 8) and shows where a viewer would lose interest
(the "boredom map", section 14.1). Pure reading of what is stored: no model is called. Audio checks need ffmpeg and are optional.

    python -m story2.audit pl-xxxxxxxx [--json] [--audio]
"""
import json
import re
import statistics
import subprocess
import sys
from pathlib import Path

import config
from story import db

from . import lexicon, planner

DEV = re.compile(r"[ऀ-ॿ]")
LAT = re.compile(r"[A-Za-z]")
WORD = re.compile(r"[ऀ-ॿ]+|[A-Za-z][A-Za-z'\-]*")
HI_STOP = set("है हैं था थी थे को की के में से पर और या एक वह यह कि जो तो भी ही नहीं कर रहा रहे रही गया गई गए ने का".split())
NEG_RX = re.compile(r"must not appear|\bno (?:\w+ ){0,2}(?:crowds?|cars|floating|anime|cartoon|extra|duplicates?)|\bwithout\b|exactly \d+ person", re.I)
QUIET_RX = re.compile(r"quiet|empty|deserted|still|alone|lonely", re.I)
_UNITS = "one|two|three|four|five|six|seven|eight|nine"
_TENS = "twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety"
ENGLISH_NUMBERS = re.compile(r"\b(?:(?:" + _TENS + r")(?:-(?:" + _UNITS + r"))?|" + _UNITS + r"|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|hundred|thousand|lakh|crore)\b", re.I)
CUES = {"turban": r"turban|pagri|pagdi", "dupatta": r"dupatta|chunni", "saree": r"\bsaree\b|\bsari\b", "rickshaw": r"rickshaw", "tram": r"\btram\b", "taxi": r"ambassador|yellow taxi",
        "dhaba": r"dhaba", "scooter": r"scooter|moped", "tractor": r"tractor", "bicycle": r"bicycle", "tea stall": r"tea stall|chai stall|tea shop", "temple": r"temple|mandir",
        "gurdwara": r"gurdwara", "mosque": r"mosque|masjid", "market": r"bazaar|market|mandi", "auto": r"auto-?rickshaw|tuk-?tuk", "station": r"railway|platform|station",
        "lungi": r"lungi|dhoti", "salwar": r"salwar|kameez", "bangles": r"bangles|bindi|sindoor|mangalsutra"}
WINDOW_S = 30


# ── targets: metric -> (operator, value). "ok" when met, "warn" when not. ──────────────────────────────────────
TARGETS: dict[str, tuple[str, float]] = {
    "questions_share": ("<=", 0.07), "stock_phrases": ("<=", 0), "first_sentence_words": ("<=", 12), "max_beat_s": ("<=", 60), "neutral_share": ("<=", 0.80),
    "last_line_not_hindi": ("<=", 0), "english_share": ("<=", 0.25), "english_numbers_in_hindi": ("<=", 0),
    "distinct_places": (">=", 12), "top_place_share": ("<=", 0.20), "person_scene_share": ("<=", 0.55), "face_free_share": (">=", 0.45), "protagonist_share": ("<=", 0.35),
    "max_face_closeup_run": ("<=", 2), "distinct_people": (">=", 8), "regional_cue_types": (">=", 6), "world_inserts": (">=", 6),
    "mean_scene_s": ("<=", 5.5), "max_scene_s": ("<=", 8), "scenes_over_12s": ("<=", 0),
    "prompt_words": ("<=", 170), "identical_prompt_share": ("<=", 0.15), "prompts_with_negation": ("<=", 0), "crowd_quiet_contradictions": ("<=", 0), "style_field_junk": ("<=", 0),
    "min_new_word_share": (">=", 0.45), "dead_windows": ("<=", 0), "drop_windows": ("<=", 0),
    "duplicate_pictures": ("<=", 0), "name_variants": ("<=", 0), "hindi_gate_failures": ("<=", 0), "narration_path_older": ("<=", 0),
    "voice_silence_share": ("<=", 0.15), "voice_longest_gap_s": ("<=", 1.5), "video_lufs": (">=", -15.5), "video_longest_gap_s": ("<=", 1.5),
}


def judge(metric: str, value) -> str:
    if value is None or metric not in TARGETS:
        return "na"
    op, target = TARGETS[metric]
    ok = value <= target if op == "<=" else value >= target
    return "ok" if ok else "warn"


def _m(metric: str, value, note: str = "") -> dict:
    out = {"value": value, "target": ("%s %s" % TARGETS[metric]) if metric in TARGETS else "", "status": judge(metric, value)}
    if note:
        out["note"] = note
    return out


def _r(x, n=2):
    return None if x is None else round(x, n)


# ── loading ─────────────────────────────────────────────────────────────────

def load(plan_id: str) -> dict:
    plan = planner.get_plan(plan_id)
    plan["segments"] = sorted(plan["segments"], key=lambda s: s["seq"])
    plan["scenes"] = sorted(plan["scenes"], key=lambda s: (s["start_s"], s["seq"]))
    return plan


def _sentences(plan: dict) -> list[dict]:
    out = []
    t = 0.0
    for g in plan["segments"]:
        sents = g["sentences"]
        per = g["duration_s"] / max(1, len(sents))
        for i, s in enumerate(sents):
            out.append({"text": s["text"], "emotion": s.get("emotion", "neutral"), "start": t, "segment": g["id"], "last": i == len(sents) - 1})
            t += per
    return out


def _prompt(scene: dict) -> str:
    return ((scene["data"].get("prompts") or {}).get("qwen") or {}).get("prompt", "")


def _place(scene: dict) -> str:
    d = scene["data"]
    return re.sub(r"\s+", " ", ((d.get("setting") or {}).get("location") or d.get("location") or "").strip().lower())


def _people(plan: dict) -> dict[str, str]:
    return {a["id"]: a["name"] for a in plan["assets"] if a["kind"] == "person"}


def _scene_people(scene: dict, people: dict[str, str]) -> list[str]:
    return [people[i] for i in (scene["data"].get("continuity") or {}).get("assets", []) if i in people]


# ── groups ──────────────────────────────────────────────────────────────────

def narration(plan: dict) -> dict:
    rows = _sentences(plan)
    texts = [r["text"] for r in rows]
    n = max(1, len(texts))
    words = [w for t in texts for w in WORD.findall(t)]
    en = sum(1 for w in words if LAT.search(w))
    hindi_sents = [t for t in texts if DEV.search(t)]
    eng_nums = sum(len(ENGLISH_NUMBERS.findall(t)) for t in hindi_sents)
    neutral = sum(1 for r in rows if r["emotion"] in ("neutral", "clear"))
    last = texts[-1] if texts else ""
    return {
        "sentences": _m("sentences", len(texts)), "minutes": _m("minutes", _r(sum(g["duration_s"] for g in plan["segments"]) / 60, 1)),
        "questions_share": _m("questions_share", _r(sum(1 for t in texts if "?" in t) / n)),
        "stock_phrases": _m("stock_phrases", lexicon.count(texts)),
        "first_sentence_words": _m("first_sentence_words", len(texts[0].split()) if texts else None),
        "max_beat_s": _m("max_beat_s", _r(max((g["duration_s"] for g in plan["segments"]), default=0), 0)),
        "neutral_share": _m("neutral_share", _r(neutral / n)),
        "last_line_not_hindi": _m("last_line_not_hindi", 1 if last and not DEV.search(last) else 0, last[:80] if last and not DEV.search(last) else ""),
        "english_share": _m("english_share", _r(en / max(1, len(words)))),
        "english_numbers_in_hindi": _m("english_numbers_in_hindi", eng_nums),
        **_new_path(plan, texts),
    }


def _new_path(plan: dict, texts: list[str]) -> dict:
    """Checks that only exist for the material-based narration: a person's name spelt two ways, parts the Hindi gate still found fault with, and a plan that has a pack but whose
    narration was written by the older one-call path (the blueprint named no details)."""
    from . import material, narrate2
    pack = material.pack(plan) if material.has(plan) else {}
    variants = material.name_variants(" ".join(texts), pack.get("names", [])) if pack else []
    gate = sum(1 for g in plan["segments"] if any(i.get("kind") == "hindi_gate" for i in (g.get("issues") or [])))
    return {"name_variants": _m("name_variants", len(variants), ", ".join(f"{a}/{b}" for a, b in variants[:4])),
            "hindi_gate_failures": _m("hindi_gate_failures", gate),
            "narration_path_older": _m("narration_path_older", 1 if pack and plan["segments"] and not narrate2.applies(plan) else 0)}


def world(plan: dict) -> dict:
    sc = plan["scenes"]
    n = max(1, len(sc))
    people = _people(plan)
    places = [_place(s) for s in sc if _place(s)]
    pc = {}
    for p in places:
        pc[p] = pc.get(p, 0) + 1
    with_person = [bool(_scene_people(s, people)) for s in sc]
    who: dict[str, int] = {}
    for s in sc:
        for p in set(_scene_people(s, people)):
            who[p] = who.get(p, 0) + 1
    top_person = max(who.items(), key=lambda kv: kv[1], default=("", 0))
    run = best = 0
    for s in sc:
        dist = ((s["data"].get("composition") or {}).get("distance") or "").lower()
        if _scene_people(s, people) and "close" in dist:
            run += 1
            best = max(best, run)
        else:
            run = 0
    text = " ".join(_prompt(s).lower() for s in sc)
    cues = [k for k, rx in CUES.items() if re.search(rx, text)]
    return {
        "scenes": _m("scenes", len(sc)),
        "distinct_places": _m("distinct_places", len(pc)),
        "top_place_share": _m("top_place_share", _r(max(pc.values(), default=0) / n), max(pc, key=pc.get) if pc else ""),
        "person_scene_share": _m("person_scene_share", _r(sum(with_person) / n)),
        "face_free_share": _m("face_free_share", _r(1 - sum(with_person) / n)),
        "protagonist_share": _m("protagonist_share", _r(top_person[1] / n), top_person[0]),
        "max_face_closeup_run": _m("max_face_closeup_run", best),
        "distinct_people": _m("distinct_people", len(people)),
        "regional_cue_types": _m("regional_cue_types", len(cues), ", ".join(cues)),
        "world_inserts": _m("world_inserts", sum(1 for s in sc if s["data"].get("insert"))),
    }


def pace(plan: dict) -> dict:
    d = [s["duration_s"] for s in plan["scenes"]]
    return {
        "mean_scene_s": _m("mean_scene_s", _r(sum(d) / len(d), 1) if d else None), "median_scene_s": _m("median_scene_s", _r(statistics.median(d), 1) if d else None),
        "max_scene_s": _m("max_scene_s", _r(max(d), 1) if d else None), "scenes_over_12s": _m("scenes_over_12s", sum(1 for x in d if x > 12)),
    }


def prompts(plan: dict) -> dict:
    sc = plan["scenes"]
    ps = [_prompt(s) for s in sc]
    ps = [p for p in ps if p]
    if not ps:
        return {k: _m(k, None) for k in ("prompt_words", "identical_prompt_share", "prompts_with_negation", "crowd_quiet_contradictions", "style_field_junk")}
    count: dict[str, int] = {}
    parts = [[x.strip() for x in re.split(r"(?<=[.!?])\s+|\n", p) if x.strip()] for p in ps]
    for ss in parts:
        for x in set(ss):
            count[x] = count.get(x, 0) + 1
    thr = len(ps) * 0.4
    total = ident = 0
    for ss in parts:
        for x in ss:
            w = len(x.split())
            total += w
            if count[x] >= thr:
                ident += w
    contradictions = 0
    for s in sc:
        p = _prompt(s)
        d = s["data"]
        if "populated with bystanders" in p and (any("crowd" in str(e).lower() for e in d.get("exclusions", [])) or QUIET_RX.search(str(d.get("atmosphere", "")))):
            contradictions += 1
    return {
        "prompt_words": _m("prompt_words", round(total / len(ps))), "identical_prompt_share": _m("identical_prompt_share", _r(ident / max(1, total))),
        "prompts_with_negation": _m("prompts_with_negation", sum(1 for p in ps if NEG_RX.search(p))),
        "crowd_quiet_contradictions": _m("crowd_quiet_contradictions", contradictions),
        "style_field_junk": _m("style_field_junk", sum(1 for s in sc if str(s["data"].get("style", "")).strip().lower() == "style")),
    }


def _tokens(text: str) -> list[str]:
    return [w for w in (x.lower() for x in WORD.findall(text)) if w not in HI_STOP and len(w) > 2]


def boredom_map(plan: dict) -> dict:
    """Per 30 s of narration time: how many words are new, how many scenes bring a new place or subject, long scenes, questions. Windows are flagged when a viewer
    would have little to hold on to (audit 14.1)."""
    rows = _sentences(plan)
    total = sum(g["duration_s"] for g in plan["segments"])
    if not rows or total <= 0:
        return {"windows": [], "drop_windows": [], "min_new_word_share": None, "dead_windows": 0}
    k_max = int(total // WINDOW_S)
    win = {k: {"t": k * WINDOW_S, "words": 0, "new_words": 0, "scenes": 0, "new_visual": 0, "long_scenes": 0, "questions": 0} for k in range(k_max + 1)}
    seen: set[str] = set()
    for r in rows:
        k = min(k_max, int(r["start"] // WINDOW_S))
        toks = _tokens(r["text"])
        win[k]["words"] += len(toks)
        win[k]["new_words"] += sum(1 for w in toks if w not in seen)
        win[k]["questions"] += 1 if "?" in r["text"] else 0
        seen.update(toks)
    people = _people(plan)
    seen_place, seen_subj = set(), set()
    for s in plan["scenes"]:
        k = min(k_max, int(s["start_s"] // WINDOW_S))
        d = s["data"]
        place, subj = _place(s), (d.get("subject") or "").strip().lower()
        win[k]["scenes"] += 1
        if (place and place not in seen_place) or (subj and subj not in seen_subj):
            win[k]["new_visual"] += 1
        win[k]["long_scenes"] += 1 if s["duration_s"] > 10 else 0
        seen_place.add(place)
        seen_subj.add(subj)
    out, flagged = [], []
    for k in sorted(win):
        w = win[k]
        if w["words"] == 0 and w["scenes"] == 0:
            continue
        w["new_word_share"] = _r(w["new_words"] / max(1, w["words"]))
        last_minute = w["t"] >= total - 60
        flags = []
        if w["words"] and w["new_word_share"] < 0.40 and w["t"] > 0 and not last_minute:
            flags.append("few new words")
        if w["scenes"] and w["new_visual"] == 0:
            flags.append("nothing new on screen")
        if w["long_scenes"]:
            flags.append("scene over 10 s")
        if w["questions"] >= 3:
            flags.append("many questions")
        w["flags"] = flags
        out.append(w)
    drops = []
    for i, w in enumerate(out):
        weak = [f for f in w["flags"] if f != "scene over 10 s"]                # a long scene is a pace problem, listed apart; it does not make a window a drop point on its own
        prev_weak = i > 0 and any(f != "scene over 10 s" for f in out[i - 1]["flags"])
        if len(weak) >= 2 or (weak and prev_weak) or (weak and "scene over 10 s" in w["flags"]):
            drops.append({"t": w["t"], "at": f"{int(w['t'] // 60)}:{int(w['t'] % 60):02d}", "why": w["flags"]})
    shares = [w["new_word_share"] for w in out if w["words"] and w["t"] > 0 and w["t"] < total - 60]
    return {"windows": out, "drop_windows": drops, "min_new_word_share": min(shares) if shares else None,
            "dead_windows": sum(1 for w in out if "few new words" in w["flags"] and "nothing new on screen" in w["flags"])}


def viewer(plan: dict) -> dict:
    b = boredom_map(plan)
    return {"min_new_word_share": _m("min_new_word_share", b["min_new_word_share"]), "dead_windows": _m("dead_windows", b["dead_windows"]),
            "drop_windows": _m("drop_windows", len(b["drop_windows"]), ", ".join(d["at"] for d in b["drop_windows"]))}


# ── audio (optional; needs ffmpeg) ──────────────────────────────────────────

def _ffmpeg(args: list[str]) -> str:
    r = subprocess.run([config.FFMPEG, "-hide_banner", "-nostats", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stderr or ""


def audio_stats(path: Path) -> dict:
    """Silence share, longest silence and loudness of one audio or video file."""
    err = _ffmpeg(["-i", str(path), "-af", "silencedetect=noise=-38dB:d=0.3,ebur128=peak=true", "-f", "null", "-"])
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", err)
    dur = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0
    gaps = [float(x) for x in re.findall(r"silence_duration:\s*([\d.]+)", err)]
    i = re.findall(r"\n\s+I:\s+(-?[\d.]+) LUFS", err)
    pk = re.findall(r"\n\s+Peak:\s+(-?[\d.]+) dBFS", err)
    return {"seconds": _r(dur, 1), "silence_s": _r(sum(gaps), 1), "silence_share": _r(sum(gaps) / dur) if dur else None, "longest_gap_s": _r(max(gaps, default=0)),
            "gaps_over_1_5s": sum(1 for g in gaps if g > 1.5), "lufs": float(i[-1]) if i else None, "peak_dbfs": float(pk[-1]) if pk else None}


def _media_file(plan_id: str, kind: str, key: str = "") -> list[tuple[str, Path]]:
    from story3 import store
    best: dict[str, dict] = {}
    for it in store.items(plan_id, kind, key):
        if it["status"] != "done" or not it["file"]:
            continue
        cur = best.get(it["key"])
        if cur is None or (it["approved"], it["attempt"]) > (cur["approved"], cur["attempt"]):
            best[it["key"]] = it
    return [(k, store.path_of(v)) for k, v in sorted(best.items()) if store.path_of(v).is_file()]


def audio(plan_id: str) -> dict:
    voices = [(k, audio_stats(p)) for k, p in _media_file(plan_id, "voice")]
    out: dict = {}
    if voices:
        total = sum(v["seconds"] or 0 for _, v in voices)
        sil = sum(v["silence_s"] or 0 for _, v in voices)
        out["voice_silence_share"] = _m("voice_silence_share", _r(sil / total) if total else None)
        out["voice_longest_gap_s"] = _m("voice_longest_gap_s", max(v["longest_gap_s"] for _, v in voices), "per take: " + ", ".join(f"{k[-8:]} {v['longest_gap_s']}s" for k, v in voices))
    vids = _media_file(plan_id, "video")
    if vids:
        v = audio_stats(vids[-1][1])
        out["video_lufs"] = _m("video_lufs", v["lufs"])
        out["video_longest_gap_s"] = _m("video_longest_gap_s", v["longest_gap_s"], f"{v['gaps_over_1_5s']} gaps over 1.5 s")
    return out


# ── whole scorecard ─────────────────────────────────────────────────────────

def pictures(plan: dict) -> dict:
    """Checks that need the drawn pictures: near-duplicate pairs (task 4.5). Reads files, so it is skipped (not applicable) when no picture exists."""
    try:
        from story3 import dupes, store
        have = any(store.items(plan["id"], "scene"))
        n = len(dupes.find(plan["id"])) if have else None
    except Exception:                                              # noqa: BLE001 - an unreadable picture must not stop the scorecard
        n = None
    return {"duplicate_pictures": _m("duplicate_pictures", n)}


def scorecard(plan_id: str, with_audio: bool = False) -> dict:
    plan = load(plan_id)
    groups = {"narration": narration(plan), "world": world(plan), "pace": pace(plan), "prompts": prompts(plan), "viewer": viewer(plan)}
    groups["pictures"] = pictures(plan)
    if with_audio:
        groups["audio"] = audio(plan_id)
    flat = [m for g in groups.values() for m in g.values()]
    return {"plan_id": plan_id, "groups": groups, "summary": {"ok": sum(1 for m in flat if m["status"] == "ok"), "warn": sum(1 for m in flat if m["status"] == "warn")},
            "boredom": boredom_map(plan)}


def text(card: dict) -> str:
    out = [f"AUDIT {card['plan_id']}: {card['summary']['ok']} ok, {card['summary']['warn']} to fix"]
    for g, ms in card["groups"].items():
        out.append(f"\n{g}")
        for k, m in ms.items():
            mark = {"ok": "  ok ", "warn": "WARN ", "na": "   - "}[m["status"]]
            out.append(f"  {mark} {k:28} {str(m['value']):>8}   {m['target']:10} {m.get('note', '')}")
    b = card["boredom"]
    out.append("\nboredom map (new words % | new place/subject | flags)")
    for w in b["windows"]:
        out.append(f"  {int(w['t'] // 60)}:{int(w['t'] % 60):02d}  {int(100 * w['new_word_share']):>3}%   {w['new_visual']}/{w['scenes']}   {', '.join(w['flags'])}")
    if b["drop_windows"]:
        out.append("  likely drop points: " + ", ".join(d["at"] for d in b["drop_windows"]))
    return "\n".join(out)


if __name__ == "__main__":
    db.init()
    pid = next((a for a in sys.argv[1:] if a.startswith("pl-")), "")
    if not pid:
        sys.exit("usage: python -m story2.audit pl-xxxxxxxx [--json] [--audio]")
    c = scorecard(pid, "--audio" in sys.argv)
    print(json.dumps(c, ensure_ascii=False, indent=1) if "--json" in sys.argv else text(c))
