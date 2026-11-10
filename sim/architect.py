"""The Story Architect (docs/PLAN_architect.md): an authored backbone written before the chapters: a hidden truth with clues, rules the person discovers, recurring devices, real-world facts, the ending, and a beat
sheet. The chapter engine plays one beat per chapter; the player's choices decide how the person handles it. A story with no plan runs exactly as before."""
from . import health, models as m, prompts as P, store

DEFAULT_BEATS = 12
CHUNK = 12                                                                        # beats written per model call; a longer film is written act by act
MIN_CLUES = 2
PURPOSES = ("setup", "problem", "solution", "turn", "clue", "payoff", "reveal", "ending")
KINDS = ("authority_lie", "trap", "hidden_resource", "betrayal", "identity", "other")
RULE_KINDS = ("stated", "discovered", "policy")
ORDINALS = ("First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth", "Ninth", "Tenth", "Eleventh", "Twelfth", "Thirteenth", "Fourteenth", "Fifteenth", "Sixteenth",
            "Seventeenth", "Eighteenth", "Nineteenth", "Twentieth")
LADDER_PURPOSES = ("problem", "solution", "turn", "clue", "payoff")                # the beats that are a numbered problem


def beat_for(bible: dict, idx: int) -> dict | None:
    return next((b for b in (bible or {}).get("beats", []) if int(b.get("n", 0)) == idx), None)


def has_plan(bible: dict) -> bool:
    return bool(bible and bible.get("beats"))


def _s(v) -> str:
    return str(v or "").strip()


# ── repairing what the model wrote ────────────────────────────────────────────

def _whole(v: float) -> int | float:
    return int(v) if float(v) == int(v) else round(float(v), 2)


def _in(n, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(n or lo)))


def clean_bible(b: m.BibleOut, start: int, count: int) -> dict:
    """The backbone as stored: numbers become whole numbers, the reveal sits in the last third, clues come before it, the method comes after the clues, the acts sit where a film puts them."""
    last = start + count - 1
    long = count > 16
    reveal = int(b.secret.reveal_beat or 0)
    lo = start + int(count * 0.6)
    reveal = max(lo, min(last, reveal or last - 1))
    clues = sorted(({"beat": max(start, min(reveal - 1, int(c.beat or start))), "clue": _s(c.clue)} for c in b.secret.clues if _s(c.clue)), key=lambda c: c["beat"])
    pov = _s(b.pov).lower()
    pov = "second" if pov.startswith(("second", "you", "2")) else "first" if pov.startswith(("first", "i", "1")) else "third" if pov.startswith(("third", "he", "she", "3")) else "second"
    kind = _s(b.secret.kind).lower().replace(" ", "_").replace("-", "_")
    found_by = _s(b.secret.found_by)
    method = 0
    if found_by:
        method = _in(b.secret.method_beat or reveal - 1, max([c["beat"] for c in clues] or [start]), max(start, reveal - 1))
    rules = []
    for i, r in enumerate(b.rules[:8 if long else 5], 1):
        if not _s(r.text):
            continue
        beat = _in(r.beat or start, start, last)
        k = _s(r.kind).lower()
        rules.append({"name": _s(r.name) or f"Rule {i}", "text": _s(r.text), "beat": beat, "kind": k if k in RULE_KINDS else "stated",
                      "uses": sorted({int(u) for u in r.uses if beat < int(u) <= last}), "shown": _s(r.shown), "broken_beat": int(r.broken_beat) if beat < int(r.broken_beat or 0) <= last else 0})
    out = {"logline": _s(b.logline), "pov": pov, "voice": _s(b.voice),
           "secret": {"truth": _s(b.secret.truth), "who": _s(b.secret.who), "reveal_beat": reveal, "clues": clues, "kind": kind if kind in KINDS else ("other" if _s(b.secret.truth) else ""),
                      "lie": _s(b.secret.lie), "found_by": found_by, "method_beat": method},
           "rules": rules,
           "motifs": [{"name": _s(x.name), "what": _s(x.what), "first_beat": max(start, min(last, int(x.first_beat or start))), "payoffs": sorted({max(start, min(last, int(p))) for p in x.payoffs if p})} for x in b.motifs[:5 if long else 3] if _s(x.name)],
           "facts": [{"fact": _s(f.fact), "use": _s(f.use), "beat": max(start, min(last, int(f.beat or start)))} for f in b.facts[:14 if long else 8] if _s(f.fact)],
           "ending": {"outcome": _s(b.ending.outcome), "final_image": _s(b.ending.final_image), "closing_line": _s(b.ending.closing_line), "inversion": _s(b.ending.inversion)},
           "opening": {"line": _s(b.opening.line), "action": _s(b.opening.action), "belief": _s(b.opening.belief)}}
    steps = {}
    for st in b.countdown.steps:
        k = _in(st.beat or start, start, last)
        steps[k] = {"beat": k, "value": _whole(st.value), "note": _s(st.note)}
    out["countdown"] = {"name": _s(b.countdown.name), "unit": _s(b.countdown.unit), "steps": [steps[k] for k in sorted(steps)]} if _s(b.countdown.name) and len(steps) >= 2 else {}
    objects = []
    for o in b.objects[:12 if long else 8]:
        if not _s(o.name):
            continue
        plant = _in(o.plant_beat or start, start, max(start, last - 1))
        pay = int(o.payoff_beat or 0)
        objects.append({"name": _s(o.name), "what": _s(o.what), "plant_beat": plant, "payoff_beat": pay if plant < pay <= last else last, "payoff": _s(o.payoff)})
    out["objects"] = objects
    out["midpoint"], out["low_point"] = {}, {}
    if count >= 6:
        span = last - start
        mid = _in(b.midpoint.beat or start + span // 2, start + round(span * 0.4), start + round(span * 0.6))
        low = _in(b.low_point.beat or start + round(span * 0.8), max(mid + 1, start + round(span * 0.7)), max(mid + 1, min(last - 1, start + round(span * 0.9))))
        if low == reveal and low - 1 > mid:
            low -= 1
        elif low == reveal:
            low = min(last - 1, low + 1)
        if _s(b.midpoint.change) or b.midpoint.beat:
            out["midpoint"] = {"beat": mid, "change": _s(b.midpoint.change)}
        if _s(b.low_point.loss) or b.low_point.beat:
            out["low_point"] = {"beat": low, "loss": _s(b.low_point.loss)}
    return out


def clean_beats(beats: list[m.BeatIn], bible: dict, start: int, count: int, final: bool = True) -> list[dict]:
    """Beats numbered start.., the last one the ending, each carrying the clues, rule, motif and fact the backbone puts there."""
    out = []
    for i, b in enumerate(beats[:count]):
        n = start + i
        time = _s(b.time)
        title = _s(b.title)
        label = _s(b.label)
        if not title and ":" in label:
            time, title = (x.strip() for x in label.split(":", 1))
        out.append({"n": n, "label": label or (f"{time}: {title}" if time and title else title or f"Part {n}"), "time": time, "title": title or label or f"Part {n}", "event": _s(b.event), "problem": _s(b.problem),
                    "turn": _s(b.turn), "hook": _s(b.hook), "purpose": b.purpose if b.purpose in PURPOSES else "problem", "challenge": _s(b.challenge), "clues": [_s(c) for c in b.clues if _s(c)],
                    "rule": _s(b.rule), "motif": _s(b.motif), "fact": _s(b.fact), "solved_by": _s(b.solved_by)})
    if out and final:
        out[-1]["purpose"] = "ending"
    reveal = bible.get("secret", {}).get("reveal_beat")
    for b in out:
        if b["n"] == reveal:
            b["purpose"] = "reveal"
        for c in bible.get("secret", {}).get("clues", []):                            # a clue the backbone plants in this beat is on the beat even if the model forgot to write it there
            if c["beat"] == b["n"] and c["clue"] not in b["clues"]:
                b["clues"].append(c["clue"])
        for r in bible.get("rules", []):
            if r["beat"] == b["n"] and not b["rule"]:
                b["rule"] = r["name"]
        for mo in bible.get("motifs", []):
            if (b["n"] == mo["first_beat"] or b["n"] in mo["payoffs"]) and not b["motif"]:
                b["motif"] = mo["name"]
        for f in bible.get("facts", []):
            if f["beat"] == b["n"] and not b["fact"]:
                b["fact"] = f["fact"]
        if not b["solved_by"] and b["purpose"] in LADDER_PURPOSES:                      # the fact or rule the beat carries is what solves its problem
            b["solved_by"] = b["fact"] or next((r["text"] for r in bible.get("rules", []) if r["name"] == b["rule"]), "")
    return out


def problems(bible: dict, beats: list[dict], count: int) -> list[str]:
    """What is still wrong with a plan after the repairs (sent back to the model once)."""
    out = []
    if len(beats) < count:
        out.append(f"write exactly {count} beats; there are {len(beats)}")
    if len(bible.get("secret", {}).get("clues", [])) < MIN_CLUES:
        out.append("plant at least 2 clues for the secret before it is revealed")
    if not bible.get("secret", {}).get("truth"):
        out.append("write the hidden truth")
    if not bible.get("rules"):
        out.append("write at least one rule the person discovers")
    if any(not b["event"] or not b["problem"] for b in beats):
        out.append("every beat needs an event and a problem")
    ladder = [b for b in beats if b["purpose"] in LADDER_PURPOSES]
    if len(ladder) >= 3 and sum(1 for b in ladder if not b["solved_by"]) * 2 > len(ladder):
        out.append("write in `solved_by` what solves the problem of each beat (a real fact, a rule or a clever idea); more than half are empty")
    return out


def bible_problems(bible: dict) -> list[str]:
    """What the backbone still lacks that every one of the reference films has (sent back to the model once)."""
    out = []
    if not bible.get("ending", {}).get("inversion"):
        out.append("write ending.inversion: how the ending turns the opening action, rule or belief around")
    if not bible.get("opening", {}).get("action") and not bible.get("opening", {}).get("belief"):
        out.append("write opening.action or opening.belief: what the person does or believes in the first scene")
    if bible.get("secret", {}).get("truth") and not bible["secret"].get("found_by"):
        out.append("write secret.found_by: the method by which the person finds out (a list turned into a map, a measurement, a comparison)")
    return out


def ordinal(n: int) -> str:
    return ORDINALS[n - 1] if 1 <= n <= len(ORDINALS) else f"Number {n}"


def decorate(bible: dict) -> dict:
    """Everything that follows from the backbone and the beats, worked out by code and stored on each beat: the problem number and signpost, the number on screen, the act, the planted and paid objects,
    the rules used again, the method beat. These are recomputed whenever the plan changes; the owner edits the backbone, not these."""
    beats = bible.get("beats", [])
    if not beats:
        return bible
    first, last = min(b["n"] for b in beats), max(b["n"] for b in beats)
    sec, cd, mid, low = bible.get("secret", {}), bible.get("countdown") or {}, bible.get("midpoint") or {}, bible.get("low_point") or {}
    steps = sorted(cd.get("steps", []), key=lambda x: x["beat"])
    no, prev = 0, None
    span = max(1, last - first)
    for b in sorted(beats, key=lambda x: x["n"]):
        n = b["n"]
        if b["purpose"] in LADDER_PURPOSES:
            no += 1
            b["problem_no"], b["signpost"] = no, f"{ordinal(no)} problem: {b['title']}"
        else:
            b["problem_no"], b["signpost"] = 0, ""
        cur = [s for s in steps if s["beat"] <= n]
        b["count"], b["count_was"] = (cur[-1]["value"] if cur else None), prev
        prev = b["count"] if b["count"] is not None else prev
        frac = (n - first) / span
        b["role"] = "midpoint" if mid.get("beat") == n else "low_point" if low.get("beat") == n else ""
        if frac < 0.25:
            b["act"] = "setup"
        elif n <= (mid.get("beat") or first + span * 0.5):
            b["act"] = "rising"
        elif n < (low.get("beat") or first + span * 0.75):
            b["act"] = "complications"
        else:
            b["act"] = "climax"
        b["plant"] = [o["name"] for o in bible.get("objects", []) if o["plant_beat"] == n]
        b["pay"] = [o["name"] for o in bible.get("objects", []) if o["payoff_beat"] == n]
        b["rule_uses"] = [r["name"] for r in bible.get("rules", []) if n in r.get("uses", [])]
        b["rule_broken"] = [r["name"] for r in bible.get("rules", []) if r.get("broken_beat") == n]
        b["method"] = sec.get("found_by", "") if sec.get("found_by") and sec.get("method_beat") == n else ""
        if b["method"] and b["purpose"] == "problem":
            b["purpose"] = "clue"
    return bible


def audit(bible: dict) -> list[dict]:
    """What the plan still lacks against the framework of docs/FRAMEWORK_story_videos.md, as plain sentences for the Plan tab (computed, never a model call)."""
    if not bible or not bible.get("beats"):
        return []
    beats, sec, out = bible["beats"], bible.get("secret", {}), []

    def add(level: str, key: str, text: str):
        out.append({"level": level, "key": key, "text": text})
    if not any(k in bible for k in ("opening", "countdown", "objects", "midpoint")):
        add("info", "old", "This plan was written before the film framework (ladder, number on screen, planted objects, acts, opening and ending echo). Write the whole plan again to get them.")
        return out
    if not bible.get("opening", {}).get("action") and not bible.get("opening", {}).get("belief"):
        add("warn", "opening", "The plan does not say what the person does or believes at the start, so the ending cannot turn it around.")
    if not bible.get("ending", {}).get("inversion"):
        add("warn", "inversion", "The ending does not turn the opening around.")
    if sec.get("truth") and not sec.get("found_by"):
        add("warn", "method", "The secret has no method: nothing says how the person finds out.")
    if sec.get("truth") and sec.get("kind") in ("", "other") and not sec.get("lie"):
        add("info", "lie", "The secret is not tied to something an authority says. In the reference films it is a number or rule someone in charge gave (the lie).")
    if not bible.get("countdown", {}).get("steps"):
        add("warn", "countdown", "No number on screen (days of food, people, minutes to the end) that changes through the story.")
    ladder = [b for b in beats if b["purpose"] in LADDER_PURPOSES]
    unsolved = [b["n"] for b in ladder if not b.get("solved_by")]
    if unsolved:
        add("warn", "ladder", f"{len(unsolved)} of {len(ladder)} problems name nothing that solves them (beats {', '.join(str(n) for n in unsolved[:8])}).")
    if len(beats) >= 6 and not bible.get("midpoint"):
        add("warn", "midpoint", "No midpoint: nothing changes the situation halfway.")
    if len(beats) >= 6 and not bible.get("low_point"):
        add("warn", "low_point", "No low point: the person never loses something big before the end.")
    if not bible.get("objects"):
        add("warn", "objects", "No planted objects: nothing is set up early and paid off late.")
    rules = bible.get("rules", [])
    if rules and not any(r.get("kind") == "policy" for r in rules):
        add("info", "policy", "No unsaid policy: every rule is announced. In the reference films a hierarchy or procedure is shown by what happens.")
    if len(rules) >= 2 and not any(r.get("broken_beat") for r in rules):
        add("info", "broken", "No rule is broken on purpose near the end.")
    if rules and not any(r.get("uses") for r in rules):
        add("info", "uses", "No rule comes back as a refrain after the beat where it is learned.")
    return out


# ── what the prompts see ──────────────────────────────────────────────────────

def label_time(beat: dict | None) -> str:
    return (beat or {}).get("time") or ""


def _rule(bible: dict, name: str) -> dict | None:
    return next((x for x in bible.get("rules", []) if x["name"] == name), None)


def _object(bible: dict, name: str) -> dict:
    return next((x for x in bible.get("objects", []) if x["name"] == name), {"name": name, "what": "", "payoff": ""})


def _count_line(bible: dict, beat: dict) -> str:
    cd = bible.get("countdown") or {}
    if beat.get("count") is None or not cd.get("name"):
        return ""
    was = f" (it was {beat['count_was']})" if beat.get("count_was") not in (None, beat["count"]) else ""
    return f"{cd['name']}: {beat['count']} {cd.get('unit', '')}".rstrip() + was


def plan_block(bible: dict, beat: dict, idx: int) -> str:
    sec = bible.get("secret", {})
    upcoming = [b for b in bible.get("beats", []) if idx < b["n"] <= idx + 2]
    lines = [f"## STORY PLAN (chapter {idx} plays this beat)", f"Logline: {bible.get('logline', '')}", f"Beat {beat['n']}: {beat['label']}", f"Event: {beat['event']}", f"Problem the person must solve: {beat['problem']}",
             f"Turn: {beat['turn']}", f"It ends on: {beat['hook']}", f"Purpose: {beat['purpose']}"]
    if beat.get("solved_by"):
        lines.append(f"What solves the problem: {beat['solved_by']}")
    if beat.get("role") == "midpoint":
        lines.append(f"This beat is the MIDPOINT: {(bible.get('midpoint') or {}).get('change', 'the situation changes')}")
    if beat.get("role") == "low_point":
        lines.append(f"This beat is the LOW POINT: {(bible.get('low_point') or {}).get('loss', 'the person loses something big')}")
    if beat.get("challenge"):
        lines.append(f"Risky act to roll: {beat['challenge']}")
    if beat.get("clues"):
        lines.append("Plant these details, looking harmless: " + "; ".join(beat["clues"]))
    if beat.get("method") and idx < sec.get("reveal_beat", 0):
        lines.append(f"The person starts to find out by this method (without yet reaching the whole truth): {beat['method']}")
    if beat.get("rule"):
        r = _rule(bible, beat["rule"])
        lines.append(f"The person learns {beat['rule']}" + (f": {r['text']}" if r else ""))
    for name in beat.get("rule_uses", []):
        r = _rule(bible, name)
        lines.append(f"The person uses {name} again" + (f": {r['text']}" if r else ""))
    for name in beat.get("rule_broken", []):
        lines.append(f"The person breaks {name} on purpose here, and it costs or saves something.")
    if beat.get("motif"):
        mo = next((x for x in bible.get("motifs", []) if x["name"] == beat["motif"]), None)
        lines.append(f"Recurring device: {beat['motif']}" + (f" ({mo['what']})" if mo else ""))
    if beat.get("fact"):
        lines.append(f"Real-world fact to use: {beat['fact']}")
    for name in beat.get("plant", []):
        lines.append(f"Plant the object {name}: {_object(bible, name)['what']}")
    for name in beat.get("pay", []):
        lines.append(f"Pay off the object {name}: {_object(bible, name)['payoff']}")
    cl = _count_line(bible, beat)
    if cl:
        lines.append(f"The number on screen: {cl}")
    if sec.get("truth") and idx < sec.get("reveal_beat", 0):
        lines.append("The hidden truth stays hidden in this chapter: never say or hint it outright.")
    elif sec.get("truth") and idx == sec.get("reveal_beat"):
        lines.append(f"This chapter reveals the hidden truth: {sec['truth']}" + (f" (the lie told until now: {sec['lie']})" if sec.get("lie") else ""))
    if upcoming:
        lines.append("Next beats: " + " | ".join(f"{b['n']} {b['label']}" for b in upcoming))
    lines.append("The player's action decides HOW the person handles the beat; the beat decides WHAT happens.")
    return "\n".join(lines)


def write_block(bible: dict, beat: dict, signposts: bool = False) -> str:
    pov = {"second": "second person (\"you\")", "first": "first person (\"I\")", "third": "third person"}.get(bible.get("pov"), "third person")
    lines = ["## STORY PLAN FOR THE WRITER", f"Point of view: {pov}. Voice: {bible.get('voice', '')}", f"This chapter is beat {beat['n']}: {beat['label']}. End on: {beat['hook'] or beat['turn']}"]
    first = min((b["n"] for b in bible.get("beats", [])), default=0)
    op = bible.get("opening") or {}
    if beat["n"] == first == 1 and (op.get("line") or op.get("action")):
        lines.append("Open on this: " + "; ".join(x for x in (op.get("line"), op.get("action") and f"the person {op['action']}", op.get("belief") and f"the person believes: {op['belief']}") if x))
    if signposts and beat.get("signpost"):
        lines.append(f"Say the problem out loud in the narration as a signpost, in these words or very close: \"{beat['signpost']}\".")
    if beat.get("solved_by"):
        lines.append(f"The problem is solved by: {beat['solved_by']}. Say why it works in one plain sentence.")
    if beat.get("role") == "midpoint":
        lines.append(f"This is the midpoint: {(bible.get('midpoint') or {}).get('change', 'the situation changes for good')}")
    if beat.get("role") == "low_point":
        lines.append(f"This is the low point: {(bible.get('low_point') or {}).get('loss', 'the person loses something big')}. Let it hurt.")
    if beat.get("clues"):
        lines.append("Plant, looking harmless: " + "; ".join(beat["clues"]))
    sec = bible.get("secret", {})
    if beat.get("method") and beat["n"] < sec.get("reveal_beat", 0):
        lines.append(f"Show the person finding out by this method, a step short of the whole truth: {beat['method']}")
    if beat.get("rule"):
        r = _rule(bible, beat["rule"])
        how = ("never announced by the narrator: show it by what happens" + (f" ({r['shown']})" if r.get("shown") else "")) if r and r.get("kind") == "policy" else "said aloud in its own words" if r and r.get("kind") == "stated" else "learned from what has just happened"
        lines.append(f"Show the person learning {beat['rule']} ({how}).")
    for name in beat.get("rule_uses", []):
        r = _rule(bible, name)
        lines.append(f"Use {name} again" + (f" and repeat its words as a refrain: {r['text']}" if r and r.get("kind") != "policy" else " and let the policy show again without being said") + ".")
    for name in beat.get("rule_broken", []):
        lines.append(f"The person breaks {name} on purpose here.")
    if beat.get("motif"):
        lines.append(f"Use the recurring device: {beat['motif']}.")
    if beat.get("fact"):
        lines.append(f"Use this real fact, in plain words with its numbers: {beat['fact']}")
    for name in beat.get("plant", []):
        lines.append(f"Put the object {name} in the scene, looking ordinary: {_object(bible, name)['what']}")
    for name in beat.get("pay", []):
        lines.append(f"Pay off the object {name}: {_object(bible, name)['payoff']}")
    cl = _count_line(bible, beat)
    if cl:
        lines.append(f"Say the number out loud in the narration: {cl}.")
    if sec.get("truth") and beat["n"] < sec.get("reveal_beat", 0):
        lines.append("Never reveal the hidden truth of the story in this chapter.")
    elif sec.get("truth") and beat["n"] == sec.get("reveal_beat"):
        lines.append(f"Reveal the hidden truth here: {sec['truth']}" + (f" Name the lie everyone has believed: {sec['lie']}" if sec.get("lie") else ""))
    if beat["purpose"] == "ending":
        e = bible.get("ending", {})
        lines.append(f"This is the ending. Outcome: {e.get('outcome', '')}. Final image: {e.get('final_image', '')}. Closing line: {e.get('closing_line', '')}")
        if e.get("inversion"):
            lines.append(f"Turn the beginning around (it began with: {op.get('line') or op.get('action') or op.get('belief') or 'the opening'}): {e['inversion']}")
    return "\n".join(lines)


def referee_block(bible: dict, beat: dict) -> str:
    sec = bible.get("secret", {})
    lines = ["## STORY PLAN", f"Beat {beat['n']}: {beat['event']} (problem: {beat['problem']})"]
    if beat.get("clues"):
        lines.append("Must plant: " + "; ".join(beat["clues"]))
    if beat.get("rule"):
        lines.append(f"Must show the person learning {beat['rule']}")
    for name in beat.get("plant", []):
        lines.append(f"Must put the object {name} in the scene")
    if sec.get("truth") and beat["n"] < sec.get("reveal_beat", 0):
        lines.append(f"HIDDEN TRUTH (must not be revealed or stated in this chapter): {sec['truth']}")
    return "\n".join(lines)


def next_block(bible: dict, idx: int) -> str:
    nb = beat_for(bible, idx + 1)
    if not nb:
        return ""
    return f"## NEXT BEAT (the options are different ways the person could handle its problem)\n{nb['label']}: {nb['problem']}"


def follows(beat: dict, text: str) -> bool:
    """A plan that plays the beat shares its words (the event and the problem)."""
    kw = health.keywords(" ".join([beat.get("event", ""), beat.get("problem", ""), beat.get("title", "")]))
    if not kw:
        return True
    need = 1 if len(kw) <= 4 else 2
    return len(kw & health.keywords(text)) >= need


# ── writing the plan (model calls; the engine is imported late because it imports this module) ──

def _so_far(pid: str) -> tuple[int, str]:
    done = [c for c in store.path(pid) if c["status"] == "done"]
    return len(done) + 1, "\n".join(f"Ch {c['idx']} ({c['story_time']}): {c['summary']}" for c in done if c["summary"])


def total_beats(pid: str, start: int, keep_end: bool = False) -> int:
    """How many beats from `start`: up to the planned length, else a plan of twelve; when the existing plan is re-written it keeps its own last beat."""
    existing = max((b["n"] for b in store.bible(pid).get("beats", [])), default=0)
    if keep_end and existing >= start:
        return existing - start + 1
    length = int(store.project(pid)["settings"].get("length") or 0)
    return max(3, length - start + 1) if length else DEFAULT_BEATS


def chunk_sizes(count: int) -> list[int]:
    """A long film is written act by act: parts of at most CHUNK beats, as equal as can be."""
    k = max(1, -(-count // CHUNK))
    base, rem = divmod(count, k)
    return [base + 1] * rem + [base] * (k - rem)


def _chosen(secret: dict | None) -> str:
    from .engine import fence
    if not secret or not str(secret.get("truth", "")).strip():
        return ""
    keys = (("kind", "kind"), ("truth", "the hidden truth"), ("who", "held by"), ("lie", "the lie everyone believes"), ("found_by", "found out by"))
    body = "; ".join(f"{label}: {_s(secret.get(k))}" for k, label in keys if _s(secret.get(k)))
    clues = [_s(c) for c in secret.get("clues", []) if _s(c)]
    return "\n\nTHE OWNER CHOSE THIS SECRET. Use it as the secret of the plan (keep its meaning, write the clues, the method and the reveal around it):\n" + fence(body + ("; clue ideas: " + " | ".join(clues) if clues else ""))


async def write_bible(pid: str, backend, s: dict, instruction: str = "", secret: dict | None = None) -> dict:
    """The backbone and the beats for the chapters still to come (all of them for a story not yet started). `secret` is one the owner picked from the candidates."""
    from . import memory, seed
    from .engine import _json
    start, so_far = _so_far(pid)
    count = total_beats(pid, start)
    user = (seed._idea_block(pid) + f"WORLD:\n{memory.world_text(store.world(pid))}\n\nCAST AND PLACES:\n{seed._cast_text(pid)}\n"
            + (f"\nTHE STORY SO FAR (it continues from here):\n{so_far}\n" if so_far else "") + f"\nThe plan covers {count} beats, numbered {start} to {start + count - 1}."
            + _chosen(secret) + seed._note(instruction) + "\n\nDesign the backbone now.")

    def v(o: m.BibleOut, caller):
        bad = bible_problems(clean_bible(o, start, count))
        if bad and not caller.last_attempt:
            raise ValueError("; ".join(bad))

    b = await _json(backend, s, P.BIBLE, user, m.BibleOut, v)
    bible = clean_bible(b, start, count)
    bible["beats"] = []
    bible = await _beats(pid, backend, s, bible, start, count, so_far, instruction)
    store.set_bible(pid, bible)
    return bible


async def _beats(pid, backend, s, bible: dict, start: int, count: int, so_far: str, instruction: str = "") -> dict:
    """The beat sheet from `start`, in parts of at most CHUNK beats; each part sees the beats written before it. Ends with the derived fields (decorate)."""
    from . import seed
    from .engine import _json
    import json
    keep = [b for b in bible.get("beats", []) if b["n"] < start]
    core = {k: v for k, v in bible.items() if k != "beats"}
    last = start + count - 1
    written: list[dict] = []
    n0 = start
    for size in chunk_sizes(count):
        before = keep + written
        user = (f"BACKBONE:\n{json.dumps(core, ensure_ascii=False)}\n\n" + (f"WHAT ALREADY HAPPENED:\n{so_far}\n\n" if so_far else "")
                + (("BEATS ALREADY WRITTEN (continue from the last one; do not repeat their problems):\n" + "\n".join(f"{b['n']} {b['label']}: {b['turn'] or b['event']}" for b in before[-24:]) + "\n\n") if before else "")
                + f"The whole plan has beats up to number {last}; beat {last} is the ending. Write exactly {size} beats numbered {n0} to {n0 + size - 1}." + seed._note(instruction) + "\n\nWrite the beat sheet now.")
        system = P.BEATS.replace("{count}", str(size)).replace("{start}", str(n0))
        final = n0 + size - 1 == last

        def v(o: m.BeatsOut, caller, n0=n0, size=size, final=final):
            bad = problems(core, clean_beats(o.beats, core, n0, size, final), size)
            if bad and not caller.last_attempt:
                raise ValueError("; ".join(bad))

        o = await _json(backend, s, system, user, m.BeatsOut, v)
        written += clean_beats(o.beats, core, n0, size, final)
        n0 += size
    return decorate({**core, "beats": keep + written})


async def replan(pid: str, backend, s: dict, instruction: str = "") -> dict:
    """The beats after the chapters already written are written again from the story so far; the hidden truth, rules, motifs, facts and the ending stay."""
    bible = store.bible(pid)
    if not has_plan(bible):
        raise store.SimError("this story has no plan yet")
    start, so_far = _so_far(pid)
    count = total_beats(pid, start, keep_end=True)
    new = await _beats(pid, backend, s, bible, start, count, so_far, instruction)
    store.set_bible(pid, new)
    return new


async def secret_candidates(pid: str, backend, s: dict, instruction: str = "") -> list[dict]:
    """Four different hidden truths for the idea, for the owner to pick from (or edit)."""
    from . import memory, seed
    from .engine import _json
    user = (seed._idea_block(pid) + f"WORLD:\n{memory.world_text(store.world(pid))}\n\nCAST AND PLACES:\n{seed._cast_text(pid)}\n" + seed._note(instruction) + "\n\nPropose the four secrets now.")
    o = await _json(backend, s, P.SECRETS, user, m.SecretsOut)
    out = []
    for c in o.candidates:
        if not _s(c.truth):
            continue
        kind = _s(c.kind).lower().replace(" ", "_").replace("-", "_")
        out.append({"kind": kind if kind in KINDS else "other", "truth": _s(c.truth), "who": _s(c.who), "lie": _s(c.lie), "found_by": _s(c.found_by), "clues": [_s(x) for x in c.clues if _s(x)][:4]})
    return out[:4]
