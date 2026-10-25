"""Phase 2 batch A: plan -> blueprint -> narration (Hindi, first person) -> validation.

Every step writes its result before the next begins, so a restart never loses work. Approved or locked segments are never
overwritten by regeneration or by edits to other segments.
"""
import re
import uuid

from story import db, llm, settings as settings_mod
from . import intake, leak, prompts as P, store, svara
from .schemas import Blueprint, NarrationOut

WPM = 148                                    # spoken Hinglish words per minute, measured on real Svara hi_male audio (125 was a guess)
DEFAULT_MINUTES = 8.0
UNSET_NAME = "(not set yet: do not say a name)"


class PlanError(Exception):
    pass


def _row(r: dict | None) -> dict | None:
    if r is None:
        return None
    for k in ("narrator", "settings", "blueprint", "readiness", "validation"):
        r[k] = db.jload(r.get(k), {} if k in ("narrator", "settings") else None)
    return r


def get_plan(plan_id: str) -> dict:
    store.ensure()
    r = _row(db.one("SELECT * FROM plans WHERE id=?", (plan_id,)))
    if not r:
        raise PlanError("plan not found")
    from . import storyboard
    r["segments"] = list_segments(plan_id)
    r["duration_s"] = round(sum(s["duration_s"] for s in r["segments"]), 1)
    r["scenes"] = storyboard.get_scenes(plan_id)
    r["assets"] = storyboard.get_assets(plan_id)
    return r


def list_segments(plan_id: str) -> list[dict]:
    out = db.q("SELECT * FROM segments WHERE plan_id=? ORDER BY seq, id", (plan_id,))
    for s in out:
        for k in ("sentences", "emphasis", "pronounce", "facts_used", "evidence_ids", "scene_ids", "issues"):
            s[k] = db.jload(s[k], [])
        s["locked"] = bool(s["locked"])
    return out


def list_plans(candidate_id: str = "", project_id: str = "") -> list[dict]:
    """Plans with a one-line progress summary, for the project's Video plans tab."""
    store.ensure()
    where, args = [], []
    if candidate_id:
        where.append("candidate_id=?")
        args.append(candidate_id)
    if project_id:
        where.append("project_id=?")
        args.append(project_id)
    rows = db.q("SELECT id, candidate_id, project_id, format, status, rev, updated_at, blueprint, settings FROM plans "
                + ("WHERE " + " AND ".join(where) + " " if where else "") + "ORDER BY updated_at DESC", args)
    for r in rows:
        bp = db.jload(r.pop("blueprint"), None)
        r["minutes"] = (db.jload(r.pop("settings"), {}) or {}).get("minutes")
        beats = [b["id"] for b in bp["beats"]] if bp else []
        segs = db.q("SELECT beat, duration_s FROM segments WHERE plan_id=?", (r["id"],))
        r["blueprint"] = bool(bp)
        r["beats"] = len(beats)
        r["beats_written"] = len({s["beat"] for s in segs if s["beat"] in beats})
        r["spoken_s"] = round(sum(s["duration_s"] for s in segs), 1)
        r["scenes"] = db.one("SELECT COUNT(*) n FROM scenes WHERE plan_id=?", (r["id"],))["n"]
        from . import export                                           # late import: export builds on this module
        r["exports"] = len(export.list_exports(r["id"]))
    return rows


def create_plan(candidate_id: str, narrator_name: str = "", minutes: float = DEFAULT_MINUTES, allow_unapproved: bool = False) -> dict:
    store.ensure()
    story = intake.load(candidate_id)
    ready = intake.readiness(story, allow_unapproved)
    if not ready["ready"]:
        raise PlanError("; ".join(c["text"] for c in ready["checks"] if c["level"] == "blocked"))
    pid = "pl-" + uuid.uuid4().hex[:8]
    narr = {"name": narrator_name.strip(), "person": "first", "gender": "male", "language": "hi", "script": "Devanagari",
            "voice": "hi_male", "avatar": {"status": "to be designed"}}
    db.ex("INSERT INTO plans(id,project_id,candidate_id,format,status,narrator,settings,readiness,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
          (pid, story["evidence"]["project_id"], candidate_id, "16:9", "draft", db.jdump(narr),
           db.jdump({"minutes": float(minutes), "wpm": WPM}), db.jdump(ready), db.now(), db.now()))
    store.log(pid, "created", {"candidate": candidate_id})
    return get_plan(pid)


def set_narrator(plan_id: str, name: str | None = None, **fields) -> dict:
    p = get_plan(plan_id)
    n = {**p["narrator"], **fields}
    if name is not None:
        n["name"] = name.strip()
    db.ex("UPDATE plans SET narrator=?, updated_at=? WHERE id=?", (db.jdump(n), db.now(), plan_id))
    store.log(plan_id, "narrator", {"name": n["name"]})
    return get_plan(plan_id)


def _story_for(plan: dict) -> dict:
    return intake.load(plan["candidate_id"])


# ── blueprint ───────────────────────────────────────────────────────────────

async def make_blueprint(plan_id: str, backend, s: dict | None = None) -> dict:
    s = s or settings_mod.get()
    plan = get_plan(plan_id)
    story = _story_for(plan)
    user = "STORY FACTS:\n" + intake.facts_text(story["public"]) + f"\n\nTarget length: about {plan['settings']['minutes']:g} minutes."
    res = await llm.JsonCaller(backend, s).call(P.BLUEPRINT, user, Blueprint)
    bp = res.value.model_dump()
    for i, b in enumerate(bp["beats"], 1):
        b["id"] = b["id"] or f"b{i}"
    db.ex("UPDATE plans SET blueprint=?, rev=rev+1, updated_at=? WHERE id=?", (db.jdump(bp), db.now(), plan_id))
    store.log(plan_id, "blueprint", {"structure": bp["structure"], "beats": len(bp["beats"])})
    return get_plan(plan_id)


# ── narration ───────────────────────────────────────────────────────────────

_PUNCT = re.compile(r"[\s।,.!?;:\"'()\-–—]+")


def _tokens(text: str) -> set[str]:
    return {w for w in _PUNCT.split(text.lower()) if w}


def repeated_sentences(prior: list[str], new: list[str], threshold: float = 0.75) -> list[str]:
    """Sentences in `new` that say (nearly) the same thing, word for word, as one already spoken or as an earlier one in `new`."""
    seen = [_tokens(p) for p in prior]
    out = []
    for n in new:
        a = _tokens(n)
        if len(a) >= 4 and any(b and len(a & b) / len(a | b) >= threshold for b in seen):
            out.append(n)
        seen.append(a)
    return out

def _segment_fields(sentences: list[dict], wpm: float) -> dict:
    sents = [{"text": x["text"].strip(), "emotion": svara.norm_emotion(x.get("emotion")), "pause_after_s": float(x.get("pause_after_s") or 0)}
             for x in sentences if x.get("text", "").strip()]
    plain = " ".join(x["text"] for x in sents)
    annotated = svara.serialise(sents)
    pauses = sum(x["pause_after_s"] for x in sents)
    return {"sentences": sents, "plain": plain, "annotated": annotated, "duration_s": svara.spoken_seconds(plain, wpm, pauses)}


async def make_narration(plan_id: str, backend, s: dict | None = None, beat_ids: list[str] | None = None,
                         progress=None, only_missing: bool = False) -> dict:
    """Write narration beat by beat (Devanagari needs many tokens per word, so one beat per call), saving each beat as it is done.
    Locked or approved segments are left exactly as they are; only the requested beats (default: all) are written."""
    s = s or settings_mod.get()
    plan = get_plan(plan_id)
    if not plan["blueprint"]:
        raise PlanError("make the blueprint first")
    story = _story_for(plan)
    bp = plan["blueprint"]
    kept_beats = {x["beat"] for x in plan["segments"] if x["locked"] or x["status"] == "approved"}
    have = {x["beat"] for x in plan["segments"]}
    want = [b for b in bp["beats"] if (not beat_ids or b["id"] in beat_ids) and b["id"] not in kept_beats
            and not (only_missing and b["id"] in have)]
    if not want:
        return plan
    minutes = float(plan["settings"]["minutes"])
    wpm = plan["settings"].get("wpm", WPM)
    n_beats = max(1, len(bp["beats"]))
    per_beat = max(40, int(minutes * wpm / n_beats))
    order = {b["id"]: i for i, b in enumerate(bp["beats"])}
    ev_ids = story["evidence"]["paragraph_ids"]
    outline = "\n".join(f"{b['id']} ({b['name']}): {b['purpose']}" for b in bp["beats"])
    caller = llm.JsonCaller(backend, s)

    flat_tries: list[int] = []
    spoken: list[str] = []

    def check(out: NarrationOut) -> None:
        flat_tries.append(1)
        felt = [svara.norm_emotion(x.emotion) for seg in out.segments for x in seg.sentences]
        if len(flat_tries) <= 2 and not caller.last_attempt and felt and all(e in ("neutral", "clear") for e in felt):          # a whole beat in one flat voice: sent back twice
            raise ValueError("Every sentence of this beat is neutral or clear. A story told in one flat voice loses the viewer. Find the moment in this beat that is "
                             "frightening, sad, angering or relieving and give the sentences around it that emotion (fear, sad, anger or happy), keeping one emotion within a segment.")
        again = repeated_sentences(spoken, [x.text for seg in out.segments for x in seg.sentences])
        if again and not caller.last_attempt:
            raise ValueError("These sentences repeat something already spoken in the video; say something new instead: " + " | ".join(again[:4]))
        for n, seg in enumerate(out.segments, 1):
            text = " ".join(x.text for x in seg.sentences)
            bad = svara.foreign_chars(text)
            if bad:
                raise ValueError(f"segment {n} contains characters that cannot be spoken: {' '.join(bad)}. "
                                 "Use Devanagari for Hindi and Latin letters for English words only; write numbers as words, never digits; no other script.")
            mixed = svara.mixed_words(text)
            if mixed:
                raise ValueError(f"segment {n} glues English letters to Hindi letters in one word: {' '.join(mixed)}. "
                                 "Write the English word on its own, with a space before the Hindi particle (stock को, not stockको).")

    system = (P.NARRATE.replace("{narrator}", plan["narrator"].get("name") or UNSET_NAME)
              .replace("{minutes}", f"{minutes / n_beats:.1f}").replace("{words}", str(per_beat))
              .replace("{per_beat}", str(per_beat)).replace("{min_beat}", str(int(per_beat * 0.7))))
    tokens_out = 0
    for k, beat in enumerate(want):
        if progress:
            progress(k, len(want), f"beat {k + 1} of {len(want)}: {beat['name']}")
        before = [x for x in list_segments(plan_id) if order.get(x["beat"], 99) < order[beat["id"]]]
        said = " ".join(x["plain"] for x in before)[-1200:]
        spoken.clear()
        spoken.extend(s_["text"] for x in list_segments(plan_id) if x["beat"] != beat["id"] for s_ in x["sentences"])       # the whole video so far, whichever beat it belongs to
        earlier = chr(10).join(f"- {t}" for t in spoken)[-3500:]
        user = (f"STORY FACTS:\n{intake.facts_text(story['public'])}\n\nBLUEPRINT (structure: {bp['structure']}):\n"
                f"Viewer promise: {bp['viewer_promise']}\nCentral question: {bp['central_question']}\n"
                f"Turning point: {bp['turning_point']}\nPayoff: {bp['payoff']}\nEnding: {bp['ending']}\n\n"
                f"ALL BEATS (for orientation):\n{outline}\n\n"
                + (f"ALREADY NARRATED (continue from here, do not repeat it):\n{said}\n\nEVERY SENTENCE SPOKEN SO FAR (never say any of these again, and do not tell a fact "
                   f"again that they already told; move the story forward):\n{earlier}\n\n" if said else "This is the opening of the video.\n\n")
                + f"WRITE NARRATION FOR THIS BEAT ONLY ({beat['id']}, about {per_beat} words):\n"
                  f"purpose: {beat['purpose']}\nviewer takeaway: {beat['takeaway']}\nfacts: {'; '.join(beat['facts'])}")
        flat_tries.clear()
        res = await caller.call(system, user, NarrationOut, check)
        tokens_out += res.tokens_out
        with db.tx() as c:
            c.execute("DELETE FROM segments WHERE plan_id=? AND beat=? AND locked=0 AND status!='approved'", (plan_id, beat["id"]))
            for n, seg in enumerate(res.value.segments):
                f = _segment_fields([x.model_dump() for x in seg.sentences], wpm)
                c.execute("INSERT INTO segments(id,plan_id,seq,beat,sentences,plain,annotated,emphasis,pronounce,facts_used,duration_s,"
                          "evidence_ids,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          ("seg-" + uuid.uuid4().hex[:8], plan_id, order[beat["id"]] + n / 100, beat["id"], db.jdump(f["sentences"]),
                           f["plain"], f["annotated"], db.jdump(seg.emphasis), db.jdump([x.model_dump() for x in seg.pronounce]),
                           db.jdump(seg.facts_used), f["duration_s"], db.jdump(ev_ids), db.now()))
    store.log(plan_id, "narration", {"beats": [b["id"] for b in want], "tokens_out": tokens_out})
    db.ex("UPDATE plans SET rev=rev+1, validation=NULL, updated_at=? WHERE id=?", (db.now(), plan_id))
    from . import storyboard
    storyboard.after_narration(plan_id)
    if progress:
        progress(len(want), len(want), "done")
    return get_plan(plan_id)


def edit_segment(seg_id: str, sentences: list[dict] | None = None, text: str | None = None, **fields) -> dict:
    """Edit one segment. Pass `sentences` ([{text, emotion, pause_after_s}]) or plain `text` (keeps the existing emotions where
    the sentence count matches, otherwise neutral). Only this segment changes; scene links and other segments are untouched."""
    store.ensure()
    seg = db.one("SELECT * FROM segments WHERE id=?", (seg_id,))
    if not seg:
        raise PlanError("segment not found")
    if seg["locked"]:
        raise PlanError("this segment is locked; unlock it first")
    plan = get_plan(seg["plan_id"])
    old = db.jload(seg["sentences"], [])
    if sentences is None and text is not None:
        parts = [t.strip() for t in __import__("re").split(r"(?<=[।.!?])\s+", text.strip()) if t.strip()]
        sentences = [{"text": t, "emotion": old[i]["emotion"] if len(old) == len(parts) else "neutral",
                      "pause_after_s": old[i]["pause_after_s"] if len(old) == len(parts) else 0} for i, t in enumerate(parts)]
    sets, args = [], []
    if sentences is not None:
        f = _segment_fields(sentences, plan["settings"].get("wpm", WPM))
        sets += ["sentences=?", "plain=?", "annotated=?", "duration_s=?"]
        args += [db.jdump(f["sentences"]), f["plain"], f["annotated"], f["duration_s"]]
    for k in ("emphasis", "pronounce"):
        if k in fields:
            sets.append(f"{k}=?")
            args.append(db.jdump(fields[k]))
    if "status" in fields:
        if fields["status"] not in ("draft", "edited", "approved", "rejected"):
            raise PlanError("status must be draft, edited, approved or rejected")
        sets.append("status=?")
        args.append(fields["status"])
    elif sentences is not None:
        sets.append("status='edited'")
    if "locked" in fields:
        sets.append("locked=?")
        args.append(1 if fields["locked"] else 0)
    if not sets:
        return get_plan(seg["plan_id"])
    db.ex(f"UPDATE segments SET {', '.join(sets)}, rev=rev+1, issues='[]', updated_at=? WHERE id=?", [*args, db.now(), seg_id])
    if sentences is not None:
        from . import storyboard
        storyboard.on_segment_changed(seg_id, len(old), len(sentences))
        storyboard.retime(seg["plan_id"])
    db.ex("UPDATE plans SET validation=NULL, rev=rev+1, updated_at=? WHERE id=?", (db.now(), seg["plan_id"]))
    store.log(seg["plan_id"], "segment", {"id": seg_id, "fields": [k for k in ("sentences",) if sentences is not None] + list(fields)})
    return get_plan(seg["plan_id"])


# ── validation ──────────────────────────────────────────────────────────────

def validate_plan(plan_id: str) -> dict:
    """Svara tags, source leaks, copied wording, and duration consistency. Stored on the plan; blocks approval, not editing."""
    plan = get_plan(plan_id)
    story = _story_for(plan)
    prof = leak.profile(story["evidence"]["project_id"], story["evidence"]["passages"])
    issues, per_seg = [], {}
    total_plain = []
    for s in plan["segments"]:
        found = []
        found += [{"where": s["id"], "kind": "svara", "text": p, "detail": ""} for p in svara.validate(s["annotated"])]
        found += leak.check_many([(s["id"], s["plain"])], prof)
        bad = svara.foreign_chars(s["plain"])
        if bad:
            found.append({"where": s["id"], "kind": "script", "text": "characters the voice cannot read: " + " ".join(bad), "detail": "digits and non-Latin, non-Devanagari scripts are skipped or mispronounced; write numbers as words"})
        mixed = svara.mixed_words(s["plain"])
        if mixed:
            found.append({"where": s["id"], "kind": "script", "text": "English and Hindi letters joined in one word: " + " ".join(mixed), "detail": "write the English word on its own, then the Hindi particle"})
        if svara.plain_text(s["annotated"]) != s["plain"]:
            found.append({"where": s["id"], "kind": "svara", "text": "spoken text and annotated text differ", "detail": ""})
        per_seg[s["id"]] = found
        issues += found
        total_plain.append(s["plain"])
    if plan["blueprint"]:
        for b in plan["blueprint"]["beats"]:
            for k in ("purpose", "takeaway"):
                issues += leak.check_many([(f"{b['id']}.{k}", b[k])], prof)
        covered = {s["beat"] for s in plan["segments"]}
        missing = [b["id"] for b in plan["blueprint"]["beats"] if b["id"] not in covered]
        if plan["segments"] and missing:
            issues.append({"where": "plan", "kind": "coverage", "text": f"no narration yet for beats {', '.join(missing)}", "detail": ""})
    target = float(plan["settings"]["minutes"]) * 60
    got = sum(s["duration_s"] for s in plan["segments"])
    if plan["segments"] and not (0.6 * target <= got <= 1.5 * target):
        issues.append({"where": "plan", "kind": "duration", "level": "warn", "text": f"narration is about {got / 60:.1f} min; target is {target / 60:.1f} min", "detail": ""})
    share = leak.overlap_share(" ".join(total_plain), story["evidence"]["passages"])
    report = {"ok": not any(i.get("level") != "warn" for i in issues), "issues": issues, "duration_s": round(got, 1), "target_s": target, "copied_share": share,
              "segments": {k: len(v) for k, v in per_seg.items()}}
    for sid, found in per_seg.items():
        db.ex("UPDATE segments SET issues=? WHERE id=?", (db.jdump(found), sid))
    keep = {k: v for k, v in (plan["validation"] or {}).items() if k in ("storyboard", "prompts", "scores", "signoff")}      # other checks keep their last report
    db.ex("UPDATE plans SET validation=?, updated_at=? WHERE id=?", (db.jdump({**keep, **report}), db.now(), plan_id))
    return report
