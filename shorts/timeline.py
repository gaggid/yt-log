"""Who is on screen when. The voice decides: each beat's real spoken length (or an estimate before the voice exists) is fitted, with a little speed change, into exactly 30 seconds;
the shots of a beat share the beat's time; every length is a whole number of frames of the finished 30 fps video, so the short is exactly 900 frames."""
from . import models

PACE_WPS = 148 / 60                    # spoken words per second of the voices (story2/voices.py pace_wpm)
GAP_S = 0.12                           # silence between two beats
END_HOLD_S = 0.3                       # the last picture stays a moment after the last word
TEMPO_MIN, TEMPO_MAX = 0.9, 1.12       # how much the voice may be slowed or sped up to land on 30 s
SAFE_SHOT_S = 2.75                     # the planner aims at this, so real voice that runs a little long still fits under the 3-second rule


def words(beat: dict) -> int:
    return sum(len(str(s.get("text", "")).split()) for s in beat.get("sentences", []))


def estimate_voice(beat: dict) -> float:
    return words(beat) / PACE_WPS


def shots_needed(span_s: float) -> int:
    """How many shots a stretch of `span_s` seconds needs so none is longer than the safe length."""
    return max(1, -(-int(span_s * 100 + 0.5) // int(SAFE_SHOT_S * 100)))


def silent(short: dict) -> bool:
    """A short with no voice: the narration is only the script the shots are planned from, so its words never decide how long the short is."""
    return (short.get("settings") or {}).get("voice_mode") == "none"


def plan_counts(beats: list[dict], target_s: float = models.TARGET_S, mute: bool = False) -> list[int]:
    """Shots per beat before any voice exists: from the estimated spoken length, scaled to the whole target seconds."""
    tl = _spans([estimate_voice(b) for b in beats], target_s, mute)
    counts = [shots_needed(sp) for sp in tl["spans"]]
    if counts and tl["spans"][0] / counts[0] > models.HOOK_MAX_S:      # the first shot is short; a first beat of one long shot gets a second
        counts[0] = max(counts[0], 1 + shots_needed(tl["spans"][0] - models.HOOK_MAX_S))
    return counts


def _spans(voice: list[float], target_s: float = models.TARGET_S, mute: bool = False) -> dict:
    """`mute`: no voice will be made, so the beats share the target in proportion to their words and the total is always the target (nothing can run long)."""
    n = len(voice)
    gaps = GAP_S * max(0, n - 1) + END_HOLD_S
    tempo = 1.0 if mute else min(TEMPO_MAX, max(TEMPO_MIN, sum(voice) / max(1.0, target_s - gaps)))
    speech = [d / tempo for d in voice]
    raw = [s + (GAP_S if i < n - 1 else END_HOLD_S) for i, s in enumerate(speech)]
    total = sum(raw)
    scale = target_s / total if (mute or total <= target_s + models.TOLERANCE_S) else 1.0      # too long: nothing can be squeezed in, the check says so
    return {"tempo": tempo, "speech": speech, "spans": [r * scale for r in raw], "raw_total": total}


def build(short: dict, voice: dict[str, float] | None = None) -> dict:
    """The timeline of a short. `voice` maps beat id to the real spoken seconds of its take; a beat without one is estimated (and `estimated` is true)."""
    target_s = float(short.get("settings", {}).get("target_s") or models.TARGET_S)
    beats = short["beats"]
    voice = voice or {}
    estimated = any(not voice.get(b["id"]) for b in beats)
    ds = [float(voice.get(b["id"]) or estimate_voice(b)) for b in beats]
    sp = _spans(ds, target_s, silent(short))
    out_beats, out_shots, problems = [], [], []
    t = 0.0
    cut_at = 0
    plan: list[tuple[dict, float]] = []                   # (shot, seconds) before the frames are rounded
    for i, b in enumerate(beats):
        ids = b.get("shot_ids") or []
        span = sp["spans"][i]
        out_beats.append({"id": b["id"], "start": round(t, 3), "span": round(span, 3), "voice_s": round(sp["speech"][i], 3), "raw_voice_s": round(ds[i], 3)})
        n = len(ids)
        if n:
            first = min(models.HOOK_MAX_S, span / n) if (i == 0 and n > 1) else span / n
            rest = (span - first) / (n - 1) if n > 1 else 0
            for k, sid in enumerate(ids):
                plan.append((next(s for s in short["shots"] if s["id"] == sid), first if k == 0 else rest))
        else:
            problems.append({"code": "no_shots", "beat": b["id"], "text": f"beat {i + 1} has no shots"})
        t += span
    total = sum(sec for _, sec in plan)
    acc = 0.0
    for shot, sec in plan:
        a, b = round(acc * models.OUT_FPS), round((acc + sec) * models.OUT_FPS)
        acc += sec
        fr = max(1, b - a)
        out_shots.append({"id": shot["id"], "beat": shot["beat"], "start": round(a / models.OUT_FPS, 3), "frames": fr, "seconds": round(fr / models.OUT_FPS, 3)})
    need: dict[str, int] = {}
    for s in out_shots:
        if s["seconds"] > models.MAX_SHOT_S + 1e-6:
            bi = next(i for i, b in enumerate(beats) if b["id"] == s["beat"])
            need[s["beat"]] = shots_needed(sp["spans"][bi])
    if need:
        problems.append({"code": "shot_too_long", "text": "some shots would be on screen longer than " + f"{models.MAX_SHOT_S:g} seconds", "beats": need})
    if abs(total - target_s) > models.TOLERANCE_S:
        problems.append({"code": "length", "text": f"the short would be {total:.1f} seconds, not {target_s:g}"})
    return {"tempo": round(sp["tempo"], 4), "beats": out_beats, "shots": out_shots, "total_s": round(total, 3), "estimated": estimated, "problems": problems}
