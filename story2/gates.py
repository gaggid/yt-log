"""The automatic gates (docs/TASKS_quality_overhaul.md M8: 8.3, 8.5, 8.8 and 8.9). No person reviews a film before it is made, so these checks stand in: after the narration, the
storyboard and the pictures, auto-run measures the film with the audit and with the safety and cultural rules, makes ONE targeted repair if something fails, measures again, and
stops with the metric and the place if it still fails.

Every metric is `hard` (it stops auto-run in `strict` mode) or `soft` (it is listed in the notes and shown on the screen). The numbers are first values taken from the audit of
the nine films audited on 2026-10-29 and the real-model bench; they must be calibrated on more real films (task 8.2), so only the unmistakable defects are hard.

Plan setting `gates.mode`: `strict` (default: stop) or `warn` (continue and list)."""
import re

from . import audit, safety

MODES = ("strict", "warn")
# stage -> {metric: (operator, value, level)}
THRESHOLDS: dict[str, dict[str, tuple[str, float, str]]] = {
    "narration": {
        "stock_phrases": ("<=", 1, "soft"), "questions_share": ("<=", 0.10, "soft"), "last_line_not_hindi": ("<=", 0, "hard"), "english_numbers_in_hindi": ("<=", 4, "soft"),
        "name_variants": ("<=", 0, "soft"), "hindi_gate_failures": ("<=", 2, "soft"), "narration_path_older": ("<=", 0, "hard"),
        "min_new_word_share": (">=", 0.40, "soft"), "dead_windows": ("<=", 1, "hard"), "drop_windows": ("<=", 1, "soft"),
    },
    "storyboard": {
        "distinct_places": (">=", 8, "soft"), "top_place_share": ("<=", 0.35, "soft"), "protagonist_share": ("<=", 0.40, "soft"), "face_free_share": (">=", 0.40, "soft"),
        "max_scene_s": ("<=", 25, "hard"), "mean_scene_s": ("<=", 6.5, "soft"), "max_face_closeup_run": ("<=", 3, "soft"),
    },
    "pictures": {"duplicate_pictures": ("<=", 3, "soft")},
}


def _ok(value, op: str, limit: float) -> bool:
    if value is None:
        return True                                                    # a metric that cannot be measured yet does not fail the gate
    return value <= limit if op == "<=" else value >= limit


def measure(plan_id: str, stage: str) -> dict:
    """The audit metrics of the stage against the thresholds: {ok, failures:[{metric, value, target, level, note}]}. `ok` is false when a hard metric fails."""
    plan = audit.load(plan_id)
    metrics = {}
    for g in (audit.narration(plan), audit.viewer(plan), audit.world(plan), audit.pace(plan), audit.pictures(plan)):
        metrics.update(g)
    fails = []
    for name, (op, limit, level) in THRESHOLDS.get(stage, {}).items():
        m = metrics.get(name)
        if m is not None and not _ok(m["value"], op, limit):
            fails.append({"metric": name, "value": m["value"], "target": f"{op} {limit}", "level": level, "note": m.get("note", "")})
    return {"stage": stage, "ok": not any(f["level"] == "hard" for f in fails), "failures": fails}


# ── safety (8.5) and cultural (8.9) ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

GRAPHIC = re.compile(r"\b(beheaded|stabbed|slit|hacked|cleaver (?:hit|struck|cut)|shot dead|strangled|burnt alive|dismember\w*|mutilat\w*|rape[sd]?|raping|tortur\w+)\b", re.I)
GLAMOUR = re.compile(r"\b(genius|mastermind|legend|king|kingpin|brilliant criminal|criminal mind)\b|मास्टरमाइंड|जीनियस|शातिर दिमाग", re.I)
STEREOTYPE = re.compile(r"\b(all|every|always|typical)\b[^.?!]{0,40}\b(people|men|women|boys|youth|villagers)\b[^.?!]{0,40}\b(of|from|in)\s+[A-Z][a-z]+|(?:capital|hub|den|home) of (?:fraud|crime|scam)", re.I)
HELPLINE = re.compile(r"\b1930\b|एक नौ तीन शून्य|उन्नीस सौ तीस|cybercrime\.gov\.in|helpline|हेल्पलाइन", re.I)
MINOR_NAMED = re.compile(r"(\d{1,2})[- ]year[- ]old (?:boy|girl)|\b(?:minor|child|schoolgirl|schoolboy)\b", re.I)


def _sentences(plan: dict) -> list[str]:
    return [s["text"] for seg in plan["segments"] for s in seg["sentences"]]


def safety_findings(plan: dict) -> list[dict]:
    """What a careful editor would stop for: an unattributed accusation, a private name that should have been replaced, a graphic act in narration or scene text, a named minor, a
    glamourising word about an offender, a generalising sentence about a place or people, a community term beside a name, and a scam story with no safety content."""
    out = []
    texts = _sentences(plan)

    def add(kind, text, where="narration", level="hard"):
        out.append({"kind": kind, "text": text[:160], "where": where, "level": level})
    for a in safety.accusations(texts):
        add("attribution", a)
    nm = plan["settings"].get("name_map") or {}
    for real in nm:
        if any(real.lower() in t.lower() for t in texts):
            add("private_name", f"{real} appears in the narration; the plan replaces it with {nm[real]}")
        for sc in plan["scenes"]:
            blob = " ".join(str(sc["data"].get(k, "")) for k in ("subject", "action")) + " " + (((sc["data"].get("prompts") or {}).get("qwen") or {}).get("prompt", ""))
            if real.lower() in blob.lower():
                add("private_name", f"{real} appears in a scene or its picture prompt", sc["id"])
    for t in texts:
        if GRAPHIC.search(t):
            add("graphic", t, level="soft")
        if GLAMOUR.search(t):
            add("glamour", t, level="soft")
        if STEREOTYPE.search(t):
            add("stereotype", t)
        if claim_comm(t) and re.search(r"\b[A-Z][a-z]{2,} [A-Z][a-z]{2,}\b", t):
            add("community", t)
        if MINOR_NAMED.search(t) and re.search(r"\b[A-Z][a-z]{2,}\b", t):
            add("minor", t, level="soft")
    for sc in plan["scenes"]:
        d = sc["data"]
        pic = " ".join(str(d.get(k, "")) for k in ("subject", "action")) + " " + str((d.get("setting") or {}).get("props", ""))
        if GRAPHIC.search(pic):
            add("graphic", pic, sc["id"])
        if safety.grave(" ".join(texts[max(0, sc["s_from"] - 1):sc["s_to"]])) and safety.SMILE.search(pic):
            add("victim_depiction", "a smile or laugh in a scene over a death or an injury", sc["id"])
    if re.search(r"scam|fraud|otp|cyber", " ".join(texts), re.I) and not any(HELPLINE.search(t) for t in texts):
        add("safety_content", "a scam story with no helpline or what-to-do line (cybercrime helpline 1930)", level="soft")
    return out


def claim_comm(text: str) -> bool:
    from . import claimcheck
    return bool(claimcheck.COMMUNITY.search(text))


def safety_gate(plan_id: str) -> dict:
    from . import planner
    f = safety_findings(planner.get_plan(plan_id))
    return {"ok": not any(x["level"] == "hard" for x in f), "findings": f}


# ── the loop (8.3) ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def mode(plan: dict) -> str:
    m = ((plan.get("settings") or {}).get("gates") or {}).get("mode", "strict")
    return m if m in MODES else "strict"


def describe(res: dict) -> str:
    return "; ".join(f"{f['metric']} is {f['value']} (needs {f['target']})" for f in res["failures"] if f["level"] == "hard") or "; ".join(f"{f['metric']} {f['value']}" for f in res["failures"])


async def run(plan_id: str, stage: str, backend=None, s: dict | None = None, notes: list[str] | None = None) -> dict:
    """Measure the stage, repair once when a hard metric fails, measure again. Raises GateStop (in strict mode) naming what is still wrong; soft failures only add notes."""
    from . import planner
    res = measure(plan_id, stage)
    if not res["ok"]:
        await repair(plan_id, stage, res, backend, s)
        res = measure(plan_id, stage)
    if stage == "narration":
        sg = safety_gate(plan_id)
        if not sg["ok"]:
            res["ok"] = False
            res["failures"] += [{"metric": f"safety:{f['kind']}", "value": f["text"], "target": "none", "level": "hard", "note": f["where"]} for f in sg["findings"] if f["level"] == "hard"]
    plan = planner.get_plan(plan_id)
    for f in res["failures"]:
        if f["level"] == "soft" and notes is not None:
            notes.append(f"{stage}: {f['metric']} is {f['value']} (the target is {f['target']})")
    if not res["ok"] and mode(plan) == "strict":
        raise GateStop(f"the {stage} did not pass the quality gate after one repair: {describe(res)}. Set gates.mode to warn to continue anyway")
    if not res["ok"] and notes is not None:
        notes.append(f"{stage} gate failed but continued (warn mode): {describe(res)}")
    return res


class GateStop(Exception):
    pass


async def repair(plan_id: str, stage: str, res: dict, backend, s: dict | None) -> None:
    """One targeted repair. Narration: the parts whose own checks failed are written again (the editor pass sees the findings). Storyboard: the world rules are applied in code (long
    scenes split, cutaways added, repeating faces turned into objects and places)."""
    from . import inserts, planner, storyboard, worldfix
    if stage == "storyboard":
        storyboard.split_long(plan_id)
        inserts.add(plan_id)
        worldfix.sweep(plan_id)
    elif stage == "narration" and backend is not None:
        plan = planner.get_plan(plan_id)
        bad = [seg["beat"] for seg in plan["segments"] if any(i.get("kind") in ("narration_check", "hindi_gate") for i in (seg.get("issues") or []))]
        if bad:
            await planner.make_narration(plan_id, backend, s, bad[:3])
