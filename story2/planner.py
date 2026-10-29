"""Phase 2 batch A: plan -> blueprint -> narration (Hindi, first person) -> validation.

Every step writes its result before the next begins, so a restart never loses work. Approved or locked segments are never
overwritten by regeneration or by edits to other segments.
"""
import re
import uuid
from types import SimpleNamespace

from story import db, llm, projects, settings as settings_mod, storytypes
from . import intake, leak, lexicon, material, maya, narrate2, prompts as P, safety, store, svara, version, voices
from .schemas import Blueprint, NarrationOut

WPM = 148                                    # spoken Hinglish words per minute, measured on real Svara hi_male audio (125 was a guess)
DEFAULT_MINUTES = 8.0
LONG_BEAT_FACTOR = 1.6                         # a beat longer than this many times its share of the target is sent back
MIN_BEAT_WORDS = 40                            # a beat is never narrated in fewer words than this, so a short video has few beats


def max_beats(minutes: float, wpm: float = WPM) -> int:
    return max(3, min(9, int(minutes * wpm / MIN_BEAT_WORDS)))
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
            "voice": "hi_male", "tts": {"engine": voices.DEFAULT_ENGINE, "voice": voices.ENGINES[voices.DEFAULT_ENGINE]["default_voice"]}, "avatar": {"status": "to be designed"}}
    db.ex("INSERT INTO plans(id,project_id,candidate_id,format,status,narrator,settings,readiness,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
          (pid, story["evidence"]["project_id"], candidate_id, "16:9", "draft", db.jdump(narr),
           db.jdump({"minutes": float(minutes), "wpm": WPM, "story_type": storytypes.of_project(projects.get(story["evidence"]["project_id"])), "pipeline": version.PIPELINE}), db.jdump(ready), db.now(), db.now()))
    store.log(pid, "created", {"candidate": candidate_id})
    from . import variety
    variety.assign(pid)                                                       # a signature that differs from the recent films (palette, lens, opening, music, structure, caption accent)
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
    """The approved story as the planner sees it. Real names of private victims (and, by default, of people not yet convicted) are replaced by the plan's `name_map` in everything
    a model reads; a plan without a map (made before the map existed) is unchanged."""
    story = intake.load(plan["candidate_id"])
    nm = (plan.get("settings") or {}).get("name_map")
    if nm:
        story["public"] = safety.apply_names(story["public"], nm)
    return story


def ensure_name_map(plan_id: str) -> dict:
    """Write the plan's name map once (settings `anonymise`, default victims_and_suspects). Later calls leave it alone, so the owner's edits stay."""
    plan = get_plan(plan_id)
    st = plan["settings"]
    if "name_map" in st:
        return st["name_map"]
    mode = st.get("anonymise") or "victims_and_suspects"
    nm = safety.suggest_name_map(intake.load(plan["candidate_id"])["public"], mode)
    db.ex("UPDATE plans SET settings=?, updated_at=? WHERE id=?", (db.jdump({**st, "anonymise": mode, "name_map": nm}), db.now(), plan_id))
    store.log(plan_id, "name_map", {"mode": mode, "names": len(nm)})
    return nm


# ── blueprint ───────────────────────────────────────────────────────────────

async def make_blueprint(plan_id: str, backend, s: dict | None = None) -> dict:
    s = s or settings_mod.get()
    ensure_name_map(plan_id)
    plan = get_plan(plan_id)
    story = _story_for(plan)
    minutes = float(plan["settings"]["minutes"])
    cap = max_beats(minutes, plan["settings"].get("wpm", WPM))
    user = ("STORY FACTS:\n" + intake.facts_text(story["public"]) + f"\n\nTarget length: about {minutes:g} minutes."
            + (f" That is short: plan AT MOST {cap} beats (this replaces the 5 to 9 beats rule), each needing about {MIN_BEAT_WORDS} spoken words, and pick only the facts that fit." if cap < 5 else ""))

    pack_items = material.pack(plan).get("items", []) if material.has(plan) else []
    if pack_items:
        user += "\n\nSTORY MATERIAL (ids you can use):\n" + material.text_for(plan)
    caller = llm.JsonCaller(backend, s)

    def fits(out: Blueprint) -> None:
        if len(out.beats) > cap + 1 and cap < 9 and not caller.last_attempt:            # sent back with the reason, then the last attempt is accepted
            raise ValueError(f"The plan has {len(out.beats)} beats but a {minutes:g}-minute video has room for {cap}: each beat is about {MIN_BEAT_WORDS} spoken words. Merge or drop beats.")
        if pack_items and not caller.last_attempt:
            bad = material.blueprint_problems(out, pack_items)
            if bad:
                raise ValueError("The plan does not use the story material properly yet:\n- " + "\n- ".join(bad[:6]))
    res = await caller.call(P.BLUEPRINT + (P.BLUEPRINT_MATERIAL + P.BLUEPRINT_EXPERIENCE + (P.TAKEAWAY_NOTE if takeaway_wanted(plan, pack_items) else "") if pack_items else "") + storytypes.blueprint_note(storytypes.of_plan(plan)), user, Blueprint, fits)
    bp = res.value.model_dump()
    if pack_items:
        material.clean_blueprint(bp, pack_items)
    for i, b in enumerate(bp["beats"], 1):
        b["id"] = b["id"] or f"b{i}"
    db.ex("UPDATE plans SET blueprint=?, rev=rev+1, updated_at=? WHERE id=?", (db.jdump(bp), db.now(), plan_id))
    store.log(plan_id, "blueprint", {"structure": bp["structure"], "beats": len(bp["beats"])})
    return get_plan(plan_id)


_PRACTICAL_RX = re.compile(r"scam|fraud|cheat|cyber|otp|phishing|apk|loan app|fake call|digital arrest|online|upi|bank account|helpline", re.I)


def takeaway_wanted(plan: dict, items: list[dict]) -> bool:
    """A "what this means for you" beat for incident and explainer films whose details are about something a viewer can protect themselves from (task 7.5); never for a biography."""
    if storytypes.of_plan(plan) not in ("incident", "explainer"):
        return False
    return len(_PRACTICAL_RX.findall(" ".join(i.get("detail", "") for i in items))) >= 3


# ── narration ───────────────────────────────────────────────────────────────

_PUNCT = re.compile(r"[\s।,.!?;:\"'()\-–—]+")


def _tokens(text: str) -> set[str]:
    return {w for w in _PUNCT.split(text.lower()) if w}


def suspense_text(bp: dict, beat: dict) -> str:
    """The blueprint's suspense plan, as instructions for one beat: what the video as a whole is built on, and what this beat reveals, holds back, plants and ends on.
    Empty for a blueprint made before the plan existed."""
    whole = [f"{lbl}: {bp[k]}" for lbl, k in (("Cold open", "cold_open"), ("What is at stake", "stakes"), ("The obvious explanation that turns out wrong", "false_answer"),
                                              ("The dark moment before the turn", "dark_moment")) if bp.get(k)]
    mine = [f"{lbl}: {beat[k]}" for lbl, k in (("This beat reveals", "reveal"), ("This beat must NOT say yet (a later beat tells it)", "hold_back"),
                                              ("Plant this small detail here", "plant"), ("The feeling of this beat (let the words carry it; tag a sentence with an emotion only at a true peak, neutral otherwise)", "feeling"), ("End this beat on", "ends_on")) if beat.get(k)]
    if not whole and not mine:
        return ""
    return ("SUSPENSE PLAN (tell it as a storyteller who raises the question before the fact):\n" + "\n".join(whole + mine) + "\n\n")


def closing(bp: dict, is_last_beat: bool) -> str:
    """What the last beat must do. The blueprint's `next_hook` is added only when it is in Hinglish (has Devanagari) and the blueprint names a series to follow: an English
    teaser read by a Hindi voice, or a teaser for a story that does not exist, is worse than none."""
    if not is_last_beat:
        return ""
    hook = (bp.get("next_hook") or "").strip()
    out = ("\n\nENDING: answer the video's central question first, in plain words. Then close on one concrete image or consequence that stays with the viewer. "
           "Do not end on a summary or on a question the video never answers. The very last sentence is one specific, open question to the viewer about this story "
           "(something they can answer in a comment from their own life or opinion, never yes or no, never 'what do you think').")
    if hook and re.search(r"[ऀ-ॿ]", hook) and (bp.get("series_placement") or "").strip():
        out += f" The very last line may plant the next story, in your own words: {hook}"
    return out


STOCK_OPENERS = ("मैं आपको", "यहाँ मैं आपको", "चलिए मैं", "पर यहाँ एक सवाल", "पर यहाँ एक उलझन", "पर यहाँ एक twist", "यहाँ मुझे सबसे")
MAX_FIRST_SENTENCE_WORDS = 14


def stock_opener(text: str) -> str:
    return next((s for s in STOCK_OPENERS if text.startswith(s)), "")


def overused_openers(prior: list[str], new: list[str], limit: int = 2, words: int = 3) -> list[str]:
    """Sentence openers (the first words) that the whole video would use more than `limit` times, and the stock phrases ("मैं आपको बताता हूँ ...") that make a video
    sound the same everywhere: a second use is already too many."""
    def head(t: str) -> str:
        return " ".join(t.split()[:words])
    count: dict[str, int] = {}
    stock: dict[str, int] = {}
    for t in prior:
        count[head(t)] = count.get(head(t), 0) + 1
        if stock_opener(t):
            stock[stock_opener(t)] = stock.get(stock_opener(t), 0) + 1
    out = []
    for t in new:
        h = head(t)
        count[h] = count.get(h, 0) + 1
        so = stock_opener(t)
        if so:
            stock[so] = stock.get(so, 0) + 1
        if (len(h.split()) == words and count[h] > limit) or (so and stock[so] > 1):
            if (so or h) not in out:
                out.append(so or h)
    return out


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

def set_sentence_tags(seg_id: str, tags: list[str]) -> None:
    """Write Maya voice tags onto a segment's sentences, in order. Nothing else changes: tags are outside the content hash."""
    row = db.one("SELECT sentences FROM segments WHERE id=?", (seg_id,))
    if not row:
        raise PlanError("segment not found")
    sents = db.jload(row["sentences"], [])
    for x, t in zip(sents, tags):
        x["tag"] = maya.norm_tag(t)
    safety.guard_tags(sents)                                    # a death or an injury is never read cheerfully
    db.ex("UPDATE segments SET sentences=? WHERE id=?", (db.jdump(sents), seg_id))


def _segment_fields(sentences: list[dict], wpm: float) -> dict:
    sents = [{"text": x["text"].strip(), "emotion": svara.norm_emotion(x.get("emotion")), "tag": maya.norm_tag(x.get("tag")),
              "pause_after_s": float(x.get("pause_after_s") or 0)}
             for x in sentences if x.get("text", "").strip()]
    safety.guard_tags(sents)
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
    ensure_name_map(plan_id)
    plan = get_plan(plan_id)
    story = _story_for(plan)
    bp = plan["blueprint"]
    gone = [x["id"] for x in plan["segments"] if x["beat"] not in {b["id"] for b in bp["beats"]} and not x["locked"] and x["status"] != "approved"]
    if gone:                                       # the story was planned again: narration (and scenes) of beats that no longer exist would be left over
        with db.tx() as c:
            for sid in gone:
                c.execute("DELETE FROM scenes WHERE segment_id=?", (sid,))
                c.execute("DELETE FROM segments WHERE id=?", (sid,))
        plan = get_plan(plan_id)
    # A full rewrite (not only_missing, no specific beat_ids) should not be silently blocked by the auto-run approval step.
    # Reset approved-but-not-locked segments to draft so the rewrite can proceed.
    if not only_missing and not beat_ids:
        with db.tx() as c:
            c.execute("UPDATE segments SET status='draft', updated_at=? WHERE plan_id=? AND status='approved' AND locked=0", (db.now(), plan_id))
        plan = get_plan(plan_id)
    kept_beats = {x["beat"] for x in plan["segments"] if x["locked"] or x["status"] == "approved"}
    have = {x["beat"] for x in plan["segments"]}
    want = [b for b in bp["beats"] if (not beat_ids or b["id"] in beat_ids) and b["id"] not in kept_beats
            and not (only_missing and b["id"] in have)]
    if not want:
        return plan
    minutes = float(plan["settings"]["minutes"])
    wpm = plan["settings"].get("wpm", WPM)
    n_beats = max(1, len(bp["beats"]))
    per_beat = max(MIN_BEAT_WORDS, int(minutes * wpm / n_beats))
    order = {b["id"]: i for i, b in enumerate(bp["beats"])}
    ev_ids = story["evidence"]["paragraph_ids"]
    outline = "\n".join(f"{b['id']} ({b['name']}): {b['purpose']}" + (f" [reveals: {b['reveal']}]" if b.get("reveal") else "") for b in bp["beats"])
    caller = llm.JsonCaller(backend, s)

    spoken: list[str] = []
    opening = {"on": False}

    def check(out: NarrationOut) -> None:
        first = out.segments[0].sentences[0].text if out.segments and out.segments[0].sentences else ""
        if opening["on"] and len(first.split()) > MAX_FIRST_SENTENCE_WORDS and not caller.last_attempt:
            raise ValueError(f"The first sentence of the video has {len(first.split())} words; it must have {MAX_FIRST_SENTENCE_WORDS} or fewer. Put the single most striking moment in it "
                             "and move the date, the place and the details to the sentences after it.")
        words = sum(len(x.text.split()) for seg in out.segments for x in seg.sentences)
        if words > per_beat * LONG_BEAT_FACTOR and not caller.last_attempt:
            raise ValueError(f"The narration has {words} words but this beat has room for about {per_beat} (the whole video must fit its {minutes:g} minutes). "
                             "Keep the most striking facts and cut the rest.")
        again = repeated_sentences(spoken, [x.text for seg in out.segments for x in seg.sentences])
        if again and not caller.last_attempt:
            raise ValueError("These sentences repeat something already spoken in the video; say something new instead: " + " | ".join(again[:4]))
        said = [x.text for seg in out.segments for x in seg.sentences]
        unattributed = safety.accusations(said)
        if unattributed and not caller.last_attempt:
            raise ValueError("These sentences state a crime as plain fact; say what the police say or allege (पुलिस के मुताबिक, आरोप है कि, बताया गया): " + " | ".join(unattributed[:3]))
        samey = overused_openers(spoken, [x.text for seg in out.segments for x in seg.sentences])
        if samey and not caller.last_attempt:
            raise ValueError("Too many sentences begin the same way as earlier ones (" + " | ".join(samey[:4]) + "). Start those sentences differently, with something specific to this moment.")
        for n, seg in enumerate(out.segments, 1):
            text = " ".join(x.text for x in seg.sentences)
            bad = svara.foreign_chars(text)
            if bad:
                raise ValueError(f"segment {n} contains characters that cannot be spoken: {' '.join(bad)}. "
                                 "Use Devanagari for Hindi and Latin letters for English words only; write numbers as words, never digits; no other script.")
            roman = [x.text for x in seg.sentences if svara.romanised_hindi(x.text)]
            if roman:
                raise ValueError(f"segment {n} writes Hindi in Latin letters ({roman[0][:60]}). Hindi words must be in Devanagari; only English words use Latin letters.")
            mixed = svara.mixed_words(text)
            if mixed:
                raise ValueError(f"segment {n} glues English letters to Hindi letters in one word: {' '.join(mixed)}. "
                                 "Write the English word on its own, with a space before the Hindi particle (stock को, not stockको).")

    _indian_hook = (bp.get("indian_hook") or "").strip()
    system = ((P.NARRATE + storytypes.narrate_note(storytypes.of_plan(plan))
               + (f"\n\nCULTURAL CONTEXT FOR THIS AUDIENCE: {_indian_hook}" if _indian_hook else "")
               + ("\n\n" + voices.narration_rules(voices.current(plan["narrator"])["engine"])).rstrip()
               + "\n\n" + safety.ATTRIBUTION_RULE)
              .replace("{narrator}", plan["narrator"].get("name") or UNSET_NAME)
              .replace("{minutes}", f"{minutes / n_beats:.1f}").replace("{words}", str(per_beat))
              .replace("{per_beat}", str(per_beat)).replace("{min_beat}", str(int(per_beat * 0.7))))
    v2 = narrate2.applies(plan)
    tokens_out = 0
    for k, beat in enumerate(want):
        if progress:
            progress(k, len(want), f"beat {k + 1} of {len(want)}: {beat['name']}")
        before = [x for x in list_segments(plan_id) if order.get(x["beat"], 99) < order[beat["id"]]]
        said = " ".join(x["plain"] for x in before)[-1200:]
        opening["on"] = not said
        spoken.clear()
        spoken.extend(s_["text"] for x in list_segments(plan_id) if x["beat"] != beat["id"] for s_ in x["sentences"])       # the whole video so far, whichever beat it belongs to
        earlier = chr(10).join(f"- {t}" for t in spoken)[-3500:]
        user = (f"STORY FACTS:\n{intake.facts_text(story['public'])}\n\nBLUEPRINT (structure: {bp['structure']}):\n"
                f"Viewer promise: {bp['viewer_promise']}\nCentral question: {bp['central_question']}\n"
                f"Turning point: {bp['turning_point']}\nPayoff: {bp['payoff']}\nEnding: {bp['ending']}\n\n"
                + suspense_text(bp, beat) +
                f"ALL BEATS (for orientation):\n{outline}\n\n"
                + (f"ALREADY NARRATED (continue from here, do not repeat it):\n{said}\n\nEVERY SENTENCE SPOKEN SO FAR (never say any of these again, and do not tell a fact "
                   f"again that they already told; move the story forward):\n{earlier}\n\n" if said else "This is the opening of the video.\n\n")
                + f"WRITE NARRATION FOR THIS BEAT ONLY ({beat['id']}, about {per_beat} words):\n"
                  f"purpose: {beat['purpose']}\nviewer takeaway: {beat['takeaway']}\nfacts: {'; '.join(beat['facts'])}"
                + closing(bp, beat["id"] == want[-1]["id"]))
        issues: list[dict] = []
        if v2:                                                  # three passes from the Material Pack (story2/narrate2.py)
            by_id = {it["id"]: it for it in material.pack(plan)["items"]}
            ctx = SimpleNamespace(bp=bp, beat=beat, pos=order[beat["id"]] + 1, total=n_beats, per_beat=per_beat, first=not said, last=beat["id"] == want[-1]["id"], spoken=list(spoken),
                                  items=[by_id[i] for i in beat.get("use", []) if i in by_id], names=material.pack(plan).get("names", []), avoid=(),
                                  questions=sum(1 for t in spoken if "?" in t), told=[f"{b.get('reward') or b.get('turn') or b.get('purpose')}" for b in bp["beats"] if order[b["id"]] < order[beat["id"]]]
                                  + [t for t in spoken[-3:]], rules=voices.narration_rules(voices.current(plan["narrator"])["engine"]), profile=lexicon.profile_of(plan["settings"]))
            checks = plan["settings"].get("checks") or {}
            ctx.tell_note, ctx.polish_note = storytypes.tell_note(storytypes.of_plan(plan)), storytypes.polish_note(storytypes.of_plan(plan))
            ctx.payoff, ctx.is_payoff = bp.get("payoff") or "", beat["id"] == bp.get("payoff_position")
            ctx.best_of_two, ctx.hindi_gate = checks.get("best_of_two", True), checks.get("hindi_gate", True)           # extra model calls: a second version of the opening and the ending, and the Hindi gate
            value, issues, tok = await narrate2.write_beat(ctx, backend, s)
            res = SimpleNamespace(value=value, tokens_out=tok)
            if ctx.alt:                                                                                          # the version that lost is kept for the editor
                st = get_plan(plan_id)["settings"]
                db.ex("UPDATE plans SET settings=? WHERE id=?", (db.jdump({**st, "narration_alt": {**(st.get("narration_alt") or {}), beat["id"]: ctx.alt}}), plan_id))
        else:
            res = await caller.call(system, user, NarrationOut, check)
        tokens_out += res.tokens_out
        with db.tx() as c:
            c.execute("DELETE FROM segments WHERE plan_id=? AND beat=? AND locked=0 AND status!='approved'", (plan_id, beat["id"]))
            for n, seg in enumerate(res.value.segments):
                f = _segment_fields([x.model_dump() for x in seg.sentences], wpm)
                c.execute("INSERT INTO segments(id,plan_id,seq,beat,sentences,plain,annotated,emphasis,pronounce,facts_used,duration_s,"
                          "evidence_ids,issues,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          ("seg-" + uuid.uuid4().hex[:8], plan_id, order[beat["id"]] + n / 100, beat["id"], db.jdump(f["sentences"]),
                           f["plain"], f["annotated"], db.jdump(seg.emphasis), db.jdump([x.model_dump() for x in seg.pronounce]),
                           db.jdump(seg.facts_used), f["duration_s"], db.jdump(ev_ids), db.jdump(issues), db.now()))
    store.log(plan_id, "narration", {"beats": [b["id"] for b in want], "tokens_out": tokens_out})
    db.ex("UPDATE plans SET settings=? WHERE id=?", (db.jdump(version.stamp(get_plan(plan_id)["settings"], "narration")), plan_id))
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
        sentences = [{"text": t, "emotion": old[i]["emotion"] if len(old) == len(parts) else "neutral", "tag": old[i].get("tag", "") if len(old) == len(parts) else "",
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
        hidden = safety.real_names_in([s["plain"]], plan["settings"].get("name_map") or {})
        if hidden:
            found.append({"where": s["id"], "kind": "private_name", "text": "a real name that this plan hides is spoken: " + ", ".join(hidden), "detail": "the plan's name map (settings) replaces private victims and not-yet-convicted people"})
        said = safety.accusations([x["text"] for x in s["sentences"]])
        if said:
            found.append({"where": s["id"], "kind": "attribution", "level": "warn", "text": "a crime is stated as plain fact: " + said[0][:90], "detail": "say what the police say or allege (पुलिस के मुताबिक, आरोप है कि)"})
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
