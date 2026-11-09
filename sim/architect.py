"""The Story Architect (docs/PLAN_architect.md): an authored backbone written before the chapters: a hidden truth with clues, rules the person discovers, recurring devices, real-world facts, the ending, and a beat
sheet. The chapter engine plays one beat per chapter; the player's choices decide how the person handles it. A story with no plan runs exactly as before."""
from . import health, models as m, prompts as P, store

DEFAULT_BEATS = 12
MIN_CLUES = 2
PURPOSES = ("setup", "problem", "solution", "turn", "clue", "payoff", "reveal", "ending")


def beat_for(bible: dict, idx: int) -> dict | None:
    return next((b for b in (bible or {}).get("beats", []) if int(b.get("n", 0)) == idx), None)


def has_plan(bible: dict) -> bool:
    return bool(bible and bible.get("beats"))


def _s(v) -> str:
    return str(v or "").strip()


# ── repairing what the model wrote ────────────────────────────────────────────

def clean_bible(b: m.BibleOut, start: int, count: int) -> dict:
    """The backbone as stored: numbers become whole numbers, the reveal sits in the last third, clues come before it."""
    last = start + count - 1
    reveal = int(b.secret.reveal_beat or 0)
    lo = start + int(count * 0.6)
    reveal = max(lo, min(last, reveal or last - 1))
    clues = sorted(({"beat": max(start, min(reveal - 1, int(c.beat or start))), "clue": _s(c.clue)} for c in b.secret.clues if _s(c.clue)), key=lambda c: c["beat"])
    pov = _s(b.pov).lower()
    pov = "second" if pov.startswith(("second", "you", "2")) else "first" if pov.startswith(("first", "i", "1")) else "third" if pov.startswith(("third", "he", "she", "3")) else "second"
    return {"logline": _s(b.logline), "pov": pov, "voice": _s(b.voice),
            "secret": {"truth": _s(b.secret.truth), "who": _s(b.secret.who), "reveal_beat": reveal, "clues": clues},
            "rules": [{"name": _s(r.name) or f"Rule {i}", "text": _s(r.text), "beat": max(start, min(last, int(r.beat or start)))} for i, r in enumerate(b.rules[:5], 1) if _s(r.text)],
            "motifs": [{"name": _s(x.name), "what": _s(x.what), "first_beat": max(start, min(last, int(x.first_beat or start))), "payoffs": sorted({max(start, min(last, int(p))) for p in x.payoffs if p})} for x in b.motifs[:3] if _s(x.name)],
            "facts": [{"fact": _s(f.fact), "use": _s(f.use), "beat": max(start, min(last, int(f.beat or start)))} for f in b.facts[:8] if _s(f.fact)],
            "ending": {"outcome": _s(b.ending.outcome), "final_image": _s(b.ending.final_image), "closing_line": _s(b.ending.closing_line)}}


def clean_beats(beats: list[m.BeatIn], bible: dict, start: int, count: int) -> list[dict]:
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
                    "rule": _s(b.rule), "motif": _s(b.motif), "fact": _s(b.fact)})
    if out:
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
    return out


# ── what the prompts see ──────────────────────────────────────────────────────

def label_time(beat: dict | None) -> str:
    return (beat or {}).get("time") or ""


def plan_block(bible: dict, beat: dict, idx: int) -> str:
    sec = bible.get("secret", {})
    upcoming = [b for b in bible.get("beats", []) if idx < b["n"] <= idx + 2]
    lines = [f"## STORY PLAN (chapter {idx} plays this beat)", f"Logline: {bible.get('logline', '')}", f"Beat {beat['n']}: {beat['label']}", f"Event: {beat['event']}", f"Problem the person must solve: {beat['problem']}",
             f"Turn: {beat['turn']}", f"It ends on: {beat['hook']}", f"Purpose: {beat['purpose']}"]
    if beat.get("challenge"):
        lines.append(f"Risky act to roll: {beat['challenge']}")
    if beat.get("clues"):
        lines.append("Plant these details, looking harmless: " + "; ".join(beat["clues"]))
    if beat.get("rule"):
        r = next((x for x in bible.get("rules", []) if x["name"] == beat["rule"]), None)
        lines.append(f"The person learns {beat['rule']}" + (f": {r['text']}" if r else ""))
    if beat.get("motif"):
        mo = next((x for x in bible.get("motifs", []) if x["name"] == beat["motif"]), None)
        lines.append(f"Recurring device: {beat['motif']}" + (f" ({mo['what']})" if mo else ""))
    if beat.get("fact"):
        lines.append(f"Real-world fact to use: {beat['fact']}")
    if sec.get("truth") and idx < sec.get("reveal_beat", 0):
        lines.append("The hidden truth stays hidden in this chapter: never say or hint it outright.")
    elif sec.get("truth") and idx == sec.get("reveal_beat"):
        lines.append(f"This chapter reveals the hidden truth: {sec['truth']}")
    if upcoming:
        lines.append("Next beats: " + " | ".join(f"{b['n']} {b['label']}" for b in upcoming))
    lines.append("The player's action decides HOW the person handles the beat; the beat decides WHAT happens.")
    return "\n".join(lines)


def write_block(bible: dict, beat: dict) -> str:
    pov = {"second": "second person (\"you\")", "first": "first person (\"I\")", "third": "third person"}.get(bible.get("pov"), "third person")
    lines = ["## STORY PLAN FOR THE WRITER", f"Point of view: {pov}. Voice: {bible.get('voice', '')}", f"This chapter is beat {beat['n']}: {beat['label']}. End on: {beat['hook'] or beat['turn']}"]
    if beat.get("clues"):
        lines.append("Plant, looking harmless: " + "; ".join(beat["clues"]))
    if beat.get("rule"):
        lines.append(f"Show the person learning {beat['rule']}.")
    if beat.get("motif"):
        lines.append(f"Use the recurring device: {beat['motif']}.")
    if beat.get("fact"):
        lines.append(f"Use this real fact, in plain words with its numbers: {beat['fact']}")
    sec = bible.get("secret", {})
    if sec.get("truth") and beat["n"] < sec.get("reveal_beat", 0):
        lines.append("Never reveal the hidden truth of the story in this chapter.")
    elif sec.get("truth") and beat["n"] == sec.get("reveal_beat"):
        lines.append(f"Reveal the hidden truth here: {sec['truth']}")
    if beat["purpose"] == "ending":
        e = bible.get("ending", {})
        lines.append(f"This is the ending. Outcome: {e.get('outcome', '')}. Final image: {e.get('final_image', '')}. Closing line: {e.get('closing_line', '')}")
    return "\n".join(lines)


def referee_block(bible: dict, beat: dict) -> str:
    sec = bible.get("secret", {})
    lines = ["## STORY PLAN", f"Beat {beat['n']}: {beat['event']} (problem: {beat['problem']})"]
    if beat.get("clues"):
        lines.append("Must plant: " + "; ".join(beat["clues"]))
    if beat.get("rule"):
        lines.append(f"Must show the person learning {beat['rule']}")
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


async def write_bible(pid: str, backend, s: dict, instruction: str = "") -> dict:
    """The backbone and the beats for the chapters still to come (all of them for a story not yet started)."""
    from . import memory, seed
    from .engine import _json, fence
    start, so_far = _so_far(pid)
    count = total_beats(pid, start)
    user = (seed._idea_block(pid) + f"WORLD:\n{memory.world_text(store.world(pid))}\n\nCAST AND PLACES:\n{seed._cast_text(pid)}\n"
            + (f"\nTHE STORY SO FAR (it continues from here):\n{so_far}\n" if so_far else "") + f"\nThe plan covers {count} beats, numbered {start} to {start + count - 1}."
            + seed._note(instruction) + "\n\nDesign the backbone now.")
    b = await _json(backend, s, P.BIBLE, user, m.BibleOut)
    bible = clean_bible(b, start, count)
    bible["beats"] = []
    bible = await _beats(pid, backend, s, bible, start, count, so_far, instruction)
    store.set_bible(pid, bible)
    return bible


async def _beats(pid, backend, s, bible: dict, start: int, count: int, so_far: str, instruction: str = "") -> dict:
    from . import seed
    from .engine import _json
    keep = [b for b in bible.get("beats", []) if b["n"] < start]
    core = {k: v for k, v in bible.items() if k != "beats"}
    import json
    user = (f"BACKBONE:\n{json.dumps(core, ensure_ascii=False)}\n\n" + (f"WHAT ALREADY HAPPENED:\n{so_far}\n\n" if so_far else "")
            + f"Write exactly {count} beats numbered {start} to {start + count - 1}." + seed._note(instruction) + "\n\nWrite the beat sheet now.")
    system = P.BEATS.replace("{count}", str(count)).replace("{start}", str(start))

    def v(o: m.BeatsOut, caller):
        fixed = clean_beats(o.beats, core, start, count)
        bad = problems(core, fixed, count)
        if bad and not caller.last_attempt:
            raise ValueError("; ".join(bad))

    o = await _json(backend, s, system, user, m.BeatsOut, v)
    return {**core, "beats": keep + clean_beats(o.beats, core, start, count)}


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
