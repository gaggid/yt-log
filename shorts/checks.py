"""The checks that run in code before any clip is made (no model). A blocker stops Make; a warning is shown and does not. Each issue says what is wrong in plain words and, where the
app can mend it, which fix applies."""
import re

from . import avatar, cast, languages, models, motion, pipelines as P, planner, shotlist, store, timeline, voice as svoice

TEXT_WORDS = re.compile(r"\b(?:text|writing|written|words?|letters?|caption|subtitles?|sign (?:saying|reading)|reads|newspaper|headline|logo|poster|banner|screen showing)\b", re.I)


def _issue(level: str, code: str, text: str, **extra) -> dict:
    return {"level": level, "code": code, "text": text, **extra}


def voice_gate(short: dict) -> str:
    """Why the next steps (start pictures, clips, the final video) must wait: the narration is on, so every beat needs its voice first (the shot lengths come from the real voice). '' when clear."""
    if short["pipeline"] == "remix" or short.get("settings", {}).get("voice_mode") == "none" or not short.get("beats"):
        return ""
    gone = svoice.missing(short)
    return f"Make the voice first: {len(gone)} of {len(short['beats'])} beats have no voice yet. The shot lengths follow the real voice." if gone else ""


def run(short: dict, tolerance_s: float = 0) -> dict:
    """Run all pre-clip checks. tolerance_s > 0 widens the length and word-count
    gates by that many seconds — used by the agent to allow ±15 s of flex."""
    issues: list[dict] = []
    if not short["shots"]:
        return {"ok": False, "issues": [_issue("block", "no_plan", "Plan the short first.")], "blockers": 1, "warnings": 0, "timeline": None}
    no_voice = short.get("settings", {}).get("voice_mode") == "none"
    real = {} if no_voice else svoice.real_seconds(short)
    tl = timeline.build(short, real)
    gone = voice_gate(short)
    if gone:
        issues.append(_issue("block", "no_voice", gone, fix="make_voice"))
    prof = planner._profile(short)
    t_s = float(short.get("settings", {}).get("target_s") or models.TARGET_S)
    # When a tolerance is given, use the actual voice duration (clamped to the allowed
    # window) as the effective target for word-count validation so the agent isn't
    # penalised for content that fits within the allowed range.
    if not no_voice and tl.get("total_s"):
        eff_t_s = max(t_s - tolerance_s, min(t_s + tolerance_s, tl["total_s"])) if tolerance_s else t_s
    else:
        eff_t_s = t_s
    if not no_voice:
        for p in planner.narration_problems(short["beats"], prof, eff_t_s, languages.of(short["settings"]), svoice.speed(short)):
            soft = p.startswith(("stock phrases", "a sentence is", "the first sentence"))
            issues.append(_issue("warn" if soft else "block", "narration", p))
    for p in tl["problems"]:
        if p["code"] == "shot_too_long":
            issues.append(_issue("block", "shot_too_long", p["text"] + ". Write the shots of those beats again with more shots.", fix="fit_shots", beats=p["beats"]))
        elif p["code"] == "length":
            if tolerance_s and abs(tl["total_s"] - t_s) <= tolerance_s:
                pass  # within agent tolerance — not a blocker
            else:
                issues.append(_issue("block", "length", p["text"] + (": the voice is too long, shorten the narration" if tl["total_s"] > t_s else ": the narration is short, add a sentence"), fix=None))
        else:
            issues.append(_issue("block", p["code"], p["text"]))
    if tl["shots"] and tl["shots"][0]["seconds"] > models.HOOK_MAX_S + 1e-6:
        issues.append(_issue("warn", "hook", f"the first shot is {tl['shots'][0]['seconds']:.1f} seconds; the hook should be {models.HOOK_MAX_S:g} or less", fix="fit_shots", beats={short["beats"][0]["id"]: len(short["beats"][0]["shot_ids"]) + 1}))
    for s in tl["shots"][1:]:
        if s["seconds"] < models.MIN_SHOT_S - 0.05:
            issues.append(_issue("warn", "shot_too_short", f"shot {s['id']} is only {s['seconds']:.1f} seconds; a shot should be at least {models.MIN_SHOT_S:g} (fewer, longer shots read better)"))
            break
    cfg_model = models.TI2V if short["pipeline"] == "quick" else models.I2V
    for sh in short["shots"]:
        try:
            models.gen_frames(sh["seconds"] or models.MAX_SHOT_S, cfg_model)
        except ValueError as e:
            issues.append(_issue("block", "frames", f"shot {sh['id']}: {e}"))
        text = P.compose(short, sh)
        if len(text) >= 3900:
            issues.append(_issue("block", "prompt_long", f"shot {sh['id']}: the prompt is too long for the model"))
        if TEXT_WORDS.search(sh["prompt"]):
            issues.append(_issue("warn", "text_in_picture", f"shot {sh['id']} may ask for words in the picture, which the model cannot draw: \"{TEXT_WORDS.search(sh['prompt']).group(0)}\""))
        if prof is not None:
            from story2 import leak
            for f in leak.check(sh["prompt"], prof, scene=True):
                issues.append(_issue("block", "leak", f"shot {sh['id']} points back to the source: {f.text}"))
    for p in shotlist.problems(short):
        fix = "fix_similar" if p["code"] == "similar_shots" else "reshoot_all"
        issues.append(_issue("warn", p["code"], p["text"], fix=fix, shots=p["shots"]))
    chars = sum(1 for sh in short["shots"] if sh.get("character"))
    if chars > planner.MAX_CHARACTER_SHOTS:
        issues.append(_issue("warn", "many_character_shots", f"{chars} shots show the main character; the same face over many shots drifts. Four or fewer holds up best"))
    for text in cast.problems(short):
        issues.append(_issue("block", "cast", text))
    for p in motion.problems(short):
        issues.append(_issue(p["level"], p["code"], p["text"]))
    for p in avatar.problems(short):
        issues.append(_issue(p["level"], p["code"], p["text"]))
    mode = short["settings"]["image_mode"]
    if mode == "anchor" and not short["images"].get("anchor") and not any("portrait" in m["canon"] for m in cast.members(short) if m["char"]):
        issues.append(_issue("warn", "no_anchor", "The picture of the main character is not uploaded, so every start picture will be drawn by the image model. Upload it, or choose another start-pictures mode."))   # not a blocker: pipelines.start_source falls back to drawing
    if mode == "per_shot" and not short["images"]["shots"]:
        issues.append(_issue("warn", "no_shot_pictures", "No shot has a picture of your own; Wan will make them all."))
    if short["pipeline"] == "keyframe" and any(sh.get("character") for sh in short["shots"]) and not short["plan"].get("character") and mode == "wan":
        issues.append(_issue("warn", "no_character", "Some shots show the main character but the plan has no description of them."))
    blockers = sum(1 for i in issues if i["level"] == "block")
    return {"ok": blockers == 0, "issues": issues, "blockers": blockers, "warnings": len(issues) - blockers, "timeline": tl}
