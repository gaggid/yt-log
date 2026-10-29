"""The checks that run in code before any clip is made (no model). A blocker stops Make; a warning is shown and does not. Each issue says what is wrong in plain words and, where the
app can mend it, which fix applies."""
import re

from . import models, pipelines as P, planner, store, timeline, voice as svoice

TEXT_WORDS = re.compile(r"\b(?:text|writing|written|words?|letters?|caption|subtitles?|sign (?:saying|reading)|reads|newspaper|headline|logo|poster|banner|screen showing|displays?)\b", re.I)


def _issue(level: str, code: str, text: str, **extra) -> dict:
    return {"level": level, "code": code, "text": text, **extra}


def run(short: dict) -> dict:
    issues: list[dict] = []
    if not short["shots"]:
        return {"ok": False, "issues": [_issue("block", "no_plan", "Plan the short first.")], "blockers": 1, "warnings": 0, "timeline": None}
    real = svoice.real_seconds(short)
    tl = timeline.build(short, real)
    prof = planner._profile(short)
    for p in planner.narration_problems(short["beats"], prof):
        soft = p.startswith(("stock phrases", "a sentence is", "the first sentence"))
        issues.append(_issue("warn" if soft else "block", "narration", p))
    for p in tl["problems"]:
        if p["code"] == "shot_too_long":
            issues.append(_issue("block", "shot_too_long", p["text"] + ". Write the shots of those beats again with more shots.", fix="fit_shots", beats=p["beats"]))
        elif p["code"] == "length":
            issues.append(_issue("block", "length", p["text"] + (": the voice is too long, shorten the narration" if tl["total_s"] > models.TARGET_S else ": the narration is short, add a sentence"), fix=None))
        else:
            issues.append(_issue("block", p["code"], p["text"]))
    if tl["shots"] and tl["shots"][0]["seconds"] > models.HOOK_MAX_S + 1e-6:
        issues.append(_issue("warn", "hook", f"the first shot is {tl['shots'][0]['seconds']:.1f} seconds; the hook should be {models.HOOK_MAX_S:g} or less", fix="fit_shots", beats={short["beats"][0]["id"]: len(short["beats"][0]["shot_ids"]) + 1}))
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
    chars = sum(1 for sh in short["shots"] if sh.get("character"))
    if chars > planner.MAX_CHARACTER_SHOTS:
        issues.append(_issue("warn", "many_character_shots", f"{chars} shots show the main character; the same face over many shots drifts. Four or fewer holds up best"))
    mode = short["settings"]["image_mode"]
    if mode == "anchor" and not short["images"].get("anchor"):
        issues.append(_issue("block", "no_anchor", "The picture of the main character is not uploaded. Upload it or let Wan decide."))
    if mode == "per_shot" and not short["images"]["shots"]:
        issues.append(_issue("warn", "no_shot_pictures", "No shot has a picture of your own; Wan will make them all."))
    if short["pipeline"] == "keyframe" and any(sh.get("character") for sh in short["shots"]) and not short["plan"].get("character") and mode == "wan":
        issues.append(_issue("warn", "no_character", "Some shots show the main character but the plan has no description of them."))
    blockers = sum(1 for i in issues if i["level"] == "block")
    return {"ok": blockers == 0, "issues": issues, "blockers": blockers, "warnings": len(issues) - blockers, "timeline": tl}
