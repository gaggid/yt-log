"""Batch D: editorial review. Twelve separately scored dimensions, each with the measurement behind it, a reason and concrete fixes; a sign-off
check that says exactly what stands between the plan and approval; approval that is tied to the exact content that was approved.

These are measured checks on the plan's own data, not a prediction of views or retention, and there is deliberately no single combined score.
Judgement calls that code cannot make (is the hook gripping, does the Hindi sound natural) stay with the editor; the scores point at where to look."""
import hashlib
import json
import re
from collections import Counter

from story import db

from . import imgplan, imgprompts, intake, leak, planner, providers, store, storyboard
from .scene_schemas import ASPECTS, NEEDS_ASSET

DISCLAIMER = ("Measured checks on this plan, not a forecast of views or retention. Each score has its reason and fixes; judge hook strength and natural "
              "Hindi by listening and watching.")
GOOD, OK = 80, 60
INTENSE = {"anger", "fear", "sad", "happy"}
_NUM_WORDS = re.compile(r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|seventeen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
                        r"hundred|thousand|million|billion)\b|सौ|हज़ार|हजार|लाख|करोड़|प्रतिशत|सत्रह|पचास|बीस|तीस|चालीस|साठ", re.I)
_PROPER = re.compile(r"\b[A-Z][a-z]{2,}\b")
_STOP = set("a an the of and or to in on at with for from by is are was were be as it its this that his her their".split())


def _band(score: float) -> str:
    return "good" if score >= GOOD else "ok" if score >= OK else "weak"


def _dim(key: str, label: str, score: float, reason: str, fixes: list[dict] | None = None, measured: dict | None = None) -> dict:
    score = int(round(max(0, min(100, score))))
    return {"key": key, "label": label, "score": score, "band": _band(score), "reason": reason, "fixes": fixes or [], "measured": measured or {}}


def _fix(text: str, where: list[str] | None = None, tab: str = "plan") -> dict:
    return {"text": text, "where": where or [], "tab": tab}


def _words(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", t.lower()) if w not in _STOP and len(w) > 1}


def _pct(n: float, d: float) -> float:
    return 100.0 * n / d if d else 0.0


# ── content identity ────────────────────────────────────────────────────────

def content_hash(plan: dict) -> str:
    """Identity of what would be exported: wording, scenes, prompts, registry and the settings that change them. Approval state, previews,
    ratings, issue lists and revision counters are left out, so approving or checking does not change it."""
    skip = {"previews", "issues"}
    doc = {
        "format": plan["format"], "blueprint": plan["blueprint"],
        "narrator": {k: plan["narrator"].get(k) for k in ("name", "voice", "gender", "person", "language")},
        "minutes": plan["settings"].get("minutes"), "wpm": plan["settings"].get("wpm"),
        "image_models": {k: v for k, v in (plan["settings"].get("image_models") or {}).items() if k in ("default", "by_type")},
        "segments": [{"id": s["id"], "seq": s["seq"], "beat": s["beat"], "sentences": s["sentences"], "annotated": s["annotated"],
                      "pronounce": s["pronounce"], "emphasis": s["emphasis"]} for s in plan["segments"]],
        "scenes": [{"id": s["id"], "seq": s["seq"], "seg": s["segment_id"], "range": [s["s_from"], s["s_to"]], "start": s["start_s"], "end": s["end_s"],
                    "data": {k: v for k, v in s["data"].items() if k not in skip}} for s in plan["scenes"]],
        "assets": [{"id": a["id"], "name": a["name"], "kind": a["kind"], "data": a["data"]} for a in plan["assets"]],
    }
    return hashlib.sha1(json.dumps(doc, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


# ── the twelve dimensions ───────────────────────────────────────────────────

class Ctx:
    def __init__(self, plan_id: str):
        self.plan = planner.get_plan(plan_id)
        self.story = planner._story_for(self.plan)
        p = self.plan
        self.segs = sorted(p["segments"], key=lambda s: (s["seq"], s["id"]))
        self.scenes = sorted(p["scenes"], key=lambda s: (s["start_s"], s["seq"]))
        self.assets = p["assets"]
        v = p["validation"] or {}
        self.narr, self.sb, self.pr = v, v.get("storyboard") or {}, v.get("prompts") or {}
        self.beats = (p["blueprint"] or {}).get("beats", [])
        self.total_s = sum(s["duration_s"] for s in self.segs) or 0.0
        self.seg_name = {s["id"]: next((b["name"] for b in self.beats if b["id"] == s["beat"]), s["beat"]) for s in self.segs}
        self.prof = leak.profile(self.story["evidence"]["project_id"], self.story["evidence"]["passages"])

    def issues(self, report: dict, *kinds) -> list[dict]:
        return [i for i in report.get("issues", []) if not kinds or i.get("kind") in kinds]


def evidence_fidelity(c: Ctx) -> dict:
    claims = c.story["public"]["claims"]
    used = [" ".join(s["facts_used"]) for s in c.segs]
    covered = [cl for cl in claims if any(len(_words(cl) & _words(u)) / max(1, len(_words(cl))) >= 0.5 for u in used)]
    with_facts = sum(1 for s in c.segs if s["facts_used"])
    coverage = _pct(len(covered), len(claims)) if claims else 100.0
    seg_share = _pct(with_facts, len(c.segs)) if c.segs else 0.0
    num_err = [i for i in c.issues(c.sb, "text") if i.get("level") == "error"] + c.issues(c.pr, "number")
    score = 0.55 * coverage + 0.45 * seg_share - 15 * len(num_err)
    notes, fixes = [], []
    if c.plan["verification"] == "unverified":
        score = min(score, 85)
        notes.append("facts are not independently verified (capped at 85)")
        fixes.append(_fix("Check the story's key facts against independent public sources before publishing.", tab="plan"))
    if len(covered) < len(claims):
        missing = [cl for cl in claims if cl not in covered]
        fixes.append(_fix(f"{len(missing)} key point(s) from the story are not used in any narration part, e.g. “{missing[0][:90]}”.", tab="narration"))
    if with_facts < len(c.segs):
        fixes.append(_fix("Some narration parts list no facts they rely on; confirm they only use what the story supports.", [s["id"] for s in c.segs if not s["facts_used"]], "narration"))
    if num_err:
        fixes.append(_fix(f"{len(num_err)} number(s) in on-screen text or prompts are not in the story's facts.", [i["where"] for i in num_err], "storyboard"))
    reason = f"{len(covered)} of {len(claims)} key points are used, {with_facts} of {len(c.segs)} narration parts name their facts" + (f"; {'; '.join(notes)}" if notes else "") + "."
    return _dim("evidence_fidelity", "Evidence fidelity", score, reason, fixes,
                {"claims": len(claims), "claims_used": len(covered), "segments_with_facts": with_facts, "number_errors": len(num_err), "verification": c.plan["verification"]})


def narrative_clarity(c: Ctx) -> dict:
    covered = {s["beat"] for s in c.segs}
    miss = [b for b in c.beats if b["id"] not in covered]
    lens = [len(x["text"].split()) for s in c.segs for x in s["sentences"]]
    avg = sum(lens) / len(lens) if lens else 0
    long_share = _pct(sum(1 for n in lens if n > 30), len(lens))
    score = 100 - 40 * len(miss) / max(1, len(c.beats)) - max(0, avg - 18) * 2.5 - 0.6 * long_share
    fixes = []
    if miss:
        fixes.append(_fix(f"No narration for: {', '.join(b['name'] for b in miss)}.", tab="narration"))
    if avg > 22 or long_share > 15:
        fixes.append(_fix(f"Sentences are long (average {avg:.0f} words, {long_share:.0f}% over 30). Split them so each carries one idea.",
                          [s["id"] for s in c.segs if any(len(x["text"].split()) > 30 for x in s["sentences"])], "narration"))
    return _dim("narrative_clarity", "Narrative clarity", score, f"{len(c.beats) - len(miss)} of {len(c.beats)} planned beats are told; sentences average {avg:.0f} words, {long_share:.0f}% longer than 30.",
                fixes, {"beats": len(c.beats), "missing_beats": len(miss), "avg_sentence_words": round(avg, 1), "long_sentence_share": round(long_share, 1)})


def opening_strength(c: Ctx) -> dict:
    if not c.segs:
        return _dim("opening_strength", "Opening strength", 0, "There is no narration yet.", [_fix("Write the narration first.", tab="narration")])
    first = c.segs[0]
    two = " ".join(x["text"] for x in first["sentences"][:2])
    n1 = len(first["sentences"][0]["text"].split()) if first["sentences"] else 0
    concrete = bool(_NUM_WORDS.search(two) or _PROPER.search(two))
    first_scene = next((s for s in c.scenes if s["segment_id"] == first["id"]), None)
    scene_ok = bool(first_scene and first_scene["data"]["visual_type"] not in NEEDS_ASSET and first_scene["data"]["narrative"].get("new_information"))
    share = _pct(first["duration_s"], c.total_s)
    score = (30 if n1 <= 25 else 15) + (30 if concrete else 5) + (20 if scene_ok else 5) + (20 if share <= 20 else 8)
    fixes = []
    if n1 > 25:
        fixes.append(_fix(f"The first sentence has {n1} words. Open on one short, concrete sentence.", [first["id"]], "narration"))
    if not concrete:
        fixes.append(_fix("The first two sentences name no person, place, number or event. Start from something specific that is true in the story.", [first["id"]], "narration"))
    if not scene_ok:
        fixes.append(_fix("The first picture is a chart or has no stated purpose. Open on a clear, concrete image.", [first_scene["id"]] if first_scene else [], "storyboard"))
    if share > 20:
        fixes.append(_fix(f"The opening takes {share:.0f}% of the video; get to the story sooner.", [first["id"]], "narration"))
    return _dim("opening_strength", "Opening strength", score, f"First sentence {n1} words; {'names something concrete' if concrete else 'names nothing concrete'}; opening is {share:.0f}% of the running time; "
                f"{'first picture is concrete' if scene_ok else 'first picture is weak'}. Whether it truly hooks is for you to judge.", fixes,
                {"first_sentence_words": n1, "concrete": concrete, "opening_share": round(share, 1)})


def progression_payoff(c: Ctx) -> dict:
    order = [s["beat"] for s in c.segs]
    plan_order = [b["id"] for b in c.beats if b["id"] in order]
    in_order = [b for b in order if b in plan_order] == plan_order
    shares = Counter()
    for s in c.segs:
        shares[s["beat"]] += s["duration_s"]
    biggest = max(shares.values()) / c.total_s * 100 if shares and c.total_s else 0
    last = c.segs[-1] if c.segs else None
    last_beat_ok = bool(c.beats and last and last["beat"] == c.beats[-1]["id"] and len(last["sentences"]) >= 2)
    covered = len({s["beat"] for s in c.segs} & {b["id"] for b in c.beats})
    score = 50 * covered / max(1, len(c.beats)) + (20 if in_order else 0) + (15 if last_beat_ok else 0) + (15 if biggest <= 40 else 5)
    fixes = []
    if not in_order:
        fixes.append(_fix("The narration parts are not in the planned order.", tab="narration"))
    if not last_beat_ok:
        fixes.append(_fix("The video does not end on the planned final beat with at least two sentences. Give the payoff room.", [last["id"]] if last else [], "narration"))
    if biggest > 40:
        fixes.append(_fix(f"One beat takes {biggest:.0f}% of the running time; the story may sag there.", tab="narration"))
    return _dim("progression_payoff", "Progression and payoff", score, f"{covered} of {len(c.beats)} beats told, {'in the planned order' if in_order else 'out of order'}; "
                f"{'ends on the planned final beat' if last_beat_ok else 'the final beat is missing or thin'}; longest beat {biggest:.0f}% of the time.", fixes,
                {"beats_told": covered, "in_order": in_order, "longest_beat_share": round(biggest, 1)})


def emotional_coherence(c: Ctx) -> dict:
    emos = [x["emotion"] for s in c.segs for x in s["sentences"]]
    if not emos:
        return _dim("emotional_coherence", "Emotional coherence", 0, "There is no narration yet.", [_fix("Write the narration first.", tab="narration")])
    switchy = [s for s in c.segs if sum(1 for a, b in zip(s["sentences"], s["sentences"][1:]) if a["emotion"] != b["emotion"]) > 1]
    intense = _pct(sum(1 for e in emos if e in INTENSE), len(emos))
    kinds = len(set(emos))
    quiet = any((x.get("pause_after_s") or 0) >= 0.8 for s in c.segs for x in s["sentences"])
    score = 100 - 12 * len(switchy) - max(0, intense - 35) * 1.2 - (10 if kinds == 1 else 0) - (0 if quiet else 8)
    fixes = []
    if switchy:
        fixes.append(_fix(f"{len(switchy)} narration part(s) change emotion more than once; the voice and pace shift audibly. Keep one emotion per part and change it only at a real turn.",
                          [s["id"] for s in switchy], "narration"))
    if intense > 35:
        fixes.append(_fix(f"{intense:.0f}% of sentences are emotional (happy, sad, anger, fear). Use neutral and clear for most of them.", tab="narration"))
    if kinds == 1:
        fixes.append(_fix("Every sentence has the same emotion. Mark the one or two real turning moments.", tab="narration"))
    if not quiet:
        fixes.append(_fix("There is no pause of 0.8 seconds or more. Add one after the reveal so it can land.", tab="narration"))
    return _dim("emotional_coherence", "Emotional coherence", score, f"{len(switchy)} part(s) switch emotion more than once; {intense:.0f}% of sentences are emotional; {kinds} different emotion(s); "
                f"{'has' if quiet else 'lacks'} a quiet pause.", fixes, {"switchy_segments": len(switchy), "intense_share": round(intense, 1), "emotions_used": kinds, "has_quiet_pause": quiet})


def visual_relevance(c: Ctx) -> dict:
    n = len(c.scenes)
    if not n:
        return _dim("visual_relevance", "Visual relevance and variety", 0, "There is no storyboard yet.", [_fix("Design the storyboard first.", tab="storyboard")])
    types = Counter(s["data"]["visual_type"] for s in c.scenes)
    repeats = c.issues(c.sb, "repeat")
    runs = c.issues(c.sb, "variety")
    no_new = [s for s in c.scenes if not s["data"]["narrative"].get("new_information", "").strip()]
    atmos = _pct(types.get("atmospheric", 0) + types.get("minimalist", 0), n)
    score = 100 - 3 * len(repeats) - 8 * len(runs) - 4 * len(no_new) - max(0, atmos - 40) - (15 if len(types) < min(4, n) else 0)
    fixes = []
    if repeats:
        fixes.append(_fix(f"{len(repeats)} scene(s) repeat the previous camera. Use “Fix camera repeats”.", [i["where"] for i in repeats], "storyboard"))
    if runs:
        fixes.append(_fix("Several scenes in a row are the same kind of picture. Change one.", [i["where"] for i in runs], "storyboard"))
    if no_new:
        fixes.append(_fix(f"{len(no_new)} scene(s) do not say what the viewer learns that the last picture did not show.", [s["id"] for s in no_new], "storyboard"))
    if atmos > 40:
        fixes.append(_fix(f"{atmos:.0f}% of scenes are mood pictures. Replace some with pictures that show something specific from the story.", tab="storyboard"))
    return _dim("visual_relevance", "Visual relevance and variety", score, f"{n} scenes use {len(types)} kinds of picture; {len(repeats)} camera repeat(s); {len(no_new)} scene(s) without a stated purpose for the viewer.",
                fixes, {"scenes": n, "types": dict(types), "camera_repeats": len(repeats), "without_new_information": len(no_new), "mood_share": round(atmos, 1)})


def comprehension_pacing(c: Ctx) -> dict:
    n = len(c.scenes)
    if not n:
        return _dim("comprehension_pacing", "Comprehension and pacing", 0, "There is no storyboard yet.", [_fix("Design the storyboard first.", tab="storyboard")])
    out = [s for s in c.scenes if not (storyboard.MIN_SCENE_S <= s["duration_s"] <= storyboard.MAX_SCENE_S)]
    target = float(c.plan["settings"].get("minutes", 0)) * 60
    off = abs(c.total_s - target) / target * 100 if target else 0
    avg = sum(s["duration_s"] for s in c.scenes) / n
    fast = 0
    for a, b in zip(c.scenes, c.scenes[1:]):
        fast += a["duration_s"] < 3 and b["duration_s"] < 3
    score = 100 - 6 * len(out) - max(0, off - 20) - 4 * fast - (10 if avg < 4 else 0)
    fixes = []
    if out:
        fixes.append(_fix(f"{len(out)} scene(s) are shorter than {storyboard.MIN_SCENE_S:g}s or longer than {storyboard.MAX_SCENE_S:g}s.", [s["id"] for s in out], "storyboard"))
    if off > 20:
        fixes.append(_fix(f"The video runs {c.total_s / 60:.1f} min against a target of {target / 60:.1f} min.", tab="plan"))
    if fast:
        fixes.append(_fix(f"{fast} place(s) where two quick cuts follow each other; give important evidence time to be read.", tab="storyboard"))
    return _dim("comprehension_pacing", "Comprehension and pacing", score, f"Scenes average {avg:.1f}s; {len(out)} out of range; runs {c.total_s / 60:.1f} min against {target / 60:.1f} min wanted.",
                fixes, {"avg_scene_s": round(avg, 1), "out_of_range": len(out), "duration_s": round(c.total_s, 1), "target_s": target, "fast_cut_pairs": fast})


def ending_quality(c: Ctx) -> dict:
    if not c.segs:
        return _dim("ending_quality", "Ending quality", 0, "There is no narration yet.", [_fix("Write the narration first.", tab="narration")])
    last = c.segs[-1]
    ls = last["sentences"][-1] if last["sentences"] else {"emotion": "neutral", "text": ""}
    last_scene = c.scenes[-1] if c.scenes else None
    outcome = bool(c.story["public"]["outcome"])
    sentences_ok = len(last["sentences"]) >= 2
    calm = ls["emotion"] in ("neutral", "clear", "sad")
    scene_ok = bool(last_scene and last_scene["data"]["narrative"].get("new_information") and last_scene["data"]["visual_type"] not in NEEDS_ASSET)
    hold = (ls.get("pause_after_s") or 0) >= 0.4 or (last_scene and last_scene["duration_s"] >= 4)
    score = (25 if sentences_ok else 8) + (20 if calm else 8) + (20 if scene_ok else 6) + (15 if hold else 5) + (20 if outcome else 12)
    fixes = []
    if not sentences_ok:
        fixes.append(_fix("The last part is a single sentence. Give the ending two or three sentences to land.", [last["id"]], "narration"))
    if not calm:
        fixes.append(_fix(f"The video ends on “{ls['emotion']}”. A neutral, clear or quiet last line usually lands better.", [last["id"]], "narration"))
    if not scene_ok:
        fixes.append(_fix("The final picture is a chart or has no stated purpose. End on an image that carries the point.", [last_scene["id"]] if last_scene else [], "storyboard"))
    if not hold:
        fixes.append(_fix("Nothing holds after the last line. Add a short pause or a longer final scene.", tab="narration"))
    if not outcome:
        fixes.append(_fix("The story has no known outcome. Make sure the ending says what is still unknown instead of implying a result.", tab="narration"))
    return _dim("ending_quality", "Ending quality", score, f"Last part has {len(last['sentences'])} sentence(s), final emotion {ls['emotion']}, "
                f"{'holds after the last line' if hold else 'does not hold'}, outcome {'known' if outcome else 'not known'}.", fixes,
                {"last_part_sentences": len(last["sentences"]), "final_emotion": ls["emotion"], "outcome_known": outcome})


def platform_suitability(c: Ctx) -> dict:
    fmt = c.plan["format"]
    w, h = ASPECTS.get(fmt, ASPECTS["16:9"])
    wrong = [s for s in c.scenes if (s["data"]["output"]["width"], s["data"]["output"]["height"]) != (w, h)]
    long_text = [s for s in c.scenes for t in s["data"]["text_on_screen"] if len(t["text"].split()) > 8]
    mins = c.total_s / 60
    if fmt == "16:9":
        length_ok, rule = 3 <= mins <= 30, "3 to 30 minutes for a long-form video"
    else:
        length_ok, rule = mins <= 1.5, "at most 90 seconds for a Short or Reel"
    score = 100 - 25 * bool(wrong) - 10 * len(long_text) - (0 if length_ok else 25) - (0 if fmt in ("16:9", "9:16") else 40)
    fixes = []
    if wrong:
        fixes.append(_fix(f"{len(wrong)} scene(s) are not {w}x{h}. Design them again for this format.", [s["id"] for s in wrong], "storyboard"))
    if long_text:
        fixes.append(_fix("On-screen text longer than 8 words competes with the narration.", [s["id"] for s in long_text], "storyboard"))
    if not length_ok:
        fixes.append(_fix(f"Running time {mins:.1f} min is outside {rule}.", tab="plan"))
    return _dim("platform_suitability", "Platform suitability", score, f"{fmt} plan, {mins:.1f} min ({'within' if length_ok else 'outside'} {rule}); {len(wrong)} scene(s) in the wrong size; {len(long_text)} long on-screen text(s).",
                fixes, {"format": fmt, "minutes": round(mins, 2), "wrong_size": len(wrong), "long_text": len(long_text)})


def generation_feasibility(c: Ctx) -> dict:
    n = len(c.scenes)
    if not n:
        return _dim("generation_feasibility", "Generation feasibility", 0, "There is no storyboard yet.", [_fix("Design the storyboard first.", tab="storyboard")])
    need = [s for s in c.scenes if s["data"]["feasibility"]["level"] == "needs_asset"]
    compiled = sum(1 for s in c.scenes if (s["data"].get("prompts") or {}).get("qwen"))
    perr = [i for i in c.issues(c.pr) if i.get("level") == "error"]
    stale = c.issues(c.pr, "stale")
    miss_refs = {m["asset_id"] for s in c.scenes for m in ((s["data"].get("prompts") or {}).get("qwen") or {}).get("missing_references", [])}
    used = {providers.model_for(s["data"], c.plan["settings"]) for s in c.scenes}
    lic = providers.settings_for(c.plan["settings"])["licence_checks"]
    unlic = [m for m in used if providers.get(m)["licence"]["status"] != "verified" and not lic.get(m)]
    score = 100 - 0.4 * _pct(len(need), n) - 30 * (1 - compiled / n) - 10 * len(perr) - 6 * len(stale) - 3 * len(miss_refs) - 8 * len(unlic)
    fixes = []
    if compiled < n:
        fixes.append(_fix(f"Image prompts are missing for {n - compiled} scene(s).", tab="prompts"))
    if perr:
        fixes.append(_fix(f"{len(perr)} image prompt error(s).", [i["where"] for i in perr], "prompts"))
    if stale:
        fixes.append(_fix("Some scenes changed after their prompts were written.", [i["where"] for i in stale], "prompts"))
    if need:
        fixes.append(_fix(f"{len(need)} scene(s) are charts, documents, maps or screens: the image model only makes the backdrop; a later step must build the real graphic from verified facts.", [s["id"] for s in need], "storyboard"))
    if miss_refs:
        fixes.append(_fix(f"{len(miss_refs)} recurring asset(s) have no approved reference image yet; create and approve them before the scenes that reuse them.", tab="continuity"))
    if unlic:
        fixes.append(_fix("Licence not confirmed for: " + ", ".join(providers.get(m)["label"] for m in unlic) + ".", tab="models"))
    return _dim("generation_feasibility", "Generation feasibility", score, f"{compiled} of {n} scenes have prompts; {len(need)} need a built graphic; {len(miss_refs)} asset(s) lack a reference image; {len(unlic)} model licence(s) unconfirmed.",
                fixes, {"scenes": n, "compiled": compiled, "needs_asset": len(need), "prompt_errors": len(perr), "missing_reference_assets": len(miss_refs), "unconfirmed_licences": unlic})


def continuity(c: Ctx) -> dict:
    n = len(c.scenes)
    if not c.assets:
        return _dim("continuity", "Continuity", 40, "No recurring people, places or style are listed yet.", [_fix("List the recurring assets so every scene stays consistent.", tab="continuity")])
    unknown = [(s["id"], u) for s in c.scenes for u in s["data"]["continuity"].get("unknown", [])]
    style = any(a["kind"] == "style" for a in c.assets)
    usage = Counter(a for s in c.scenes for a in s["data"]["continuity"]["assets"])
    unused = [a for a in c.assets if a["kind"] not in ("style", "narrator") and usage[a["id"]] == 0]
    people_bad = [a for a in c.assets if a["kind"] == "person" and a["data"].get("fictionalisation") not in ("generic_reconstruction", "source_supported", "real_person_no_likeness", "fictional")]
    recurring = [a for a in c.assets if a["kind"] != "style" and usage[a["id"]] >= 2]
    noref = [a for a in recurring if not [r for r in a["data"].get("reference_images", []) if r.get("approved")]]
    no_assets = _pct(sum(1 for s in c.scenes if not s["data"]["continuity"]["assets"]), n) if n else 0
    score = 100 - 6 * len(unknown) - (20 if not style else 0) - 3 * len(unused) - 8 * len(people_bad) - 2 * len(noref) - max(0, no_assets - 60) * 0.3
    fixes = []
    if unknown:
        fixes.append(_fix(f"{len(unknown)} scene(s) use assets that are not in the registry: {', '.join(sorted({u for _, u in unknown}))}.", [i for i, _ in unknown], "storyboard"))
    if not style:
        fixes.append(_fix("There is no style asset, so scenes may drift in look.", tab="continuity"))
    if people_bad:
        fixes.append(_fix("A person has no fictionalisation status; say whether the look is a generic reconstruction or source-supported.", tab="continuity"))
    if unused:
        fixes.append(_fix(f"{len(unused)} listed asset(s) appear in no scene: {', '.join(a['name'] for a in unused)}.", tab="continuity"))
    if noref:
        fixes.append(_fix(f"{len(noref)} asset(s) recur in two or more scenes without an approved reference image: {', '.join(a['name'] for a in noref)}.", tab="continuity"))
    return _dim("continuity", "Continuity", score, f"{len(c.assets)} assets listed, {len(recurring)} recurring; {len(unknown)} unknown reference(s); {len(noref)} recurring asset(s) without a reference image.",
                fixes, {"assets": len(c.assets), "recurring": len(recurring), "unknown_references": len(unknown), "recurring_without_reference": len(noref), "style_present": style})


def originality(c: Ctx) -> dict:
    plain = " ".join(s["plain"] for s in c.segs)
    share = leak.overlap_share(plain, c.story["evidence"]["passages"]) if plain else 0.0
    scene_text = " ".join(f"{s['data']['subject']} {s['data']['action']} {s['data'].get('generation_intent', '')}" for s in c.scenes)
    scene_share = leak.overlap_share(scene_text, c.story["evidence"]["passages"]) if scene_text else 0.0
    kinds = ("title", "author", "credit", "self_reference", "part_title", "paragraph_tag", "copied_wording")
    findings = [i for i in c.issues(c.narr, *kinds)] + [i for i in c.issues(c.sb, "source_leak")] + [i for i in c.issues(c.pr, "source_leak")]
    title = c.story["evidence"]["working_title"]
    tfind = leak.check(title, c.prof)
    score = 100 - 250 * share - 150 * scene_share - 15 * len(findings) - (10 if tfind else 0)
    fixes = []
    if findings:
        fixes.append(_fix(f"{len(findings)} place(s) point back to the source or copy its wording.", [i["where"] for i in findings], "narration"))
    if share > 0.02:
        fixes.append(_fix(f"{share * 100:.1f}% of the narration repeats runs of {leak.NGRAM}+ words from the source passages; retell them in fresh words.", tab="narration"))
    if tfind:
        fixes.append(_fix("The working title resembles the source's wording. Rename it before publishing.", tab="plan"))
    return _dim("originality", "Originality of treatment", score, f"{share * 100:.1f}% of narration and {scene_share * 100:.1f}% of scene text sit inside runs copied from the source; "
                f"{len(findings)} reference(s) to the source; working title {'resembles' if tfind else 'does not resemble'} the source.", fixes,
                {"narration_copied_share": share, "scene_copied_share": scene_share, "source_references": len(findings), "title_resembles_source": bool(tfind)})


DIMENSIONS = (evidence_fidelity, narrative_clarity, opening_strength, progression_payoff, emotional_coherence, visual_relevance, comprehension_pacing,
              ending_quality, platform_suitability, generation_feasibility, continuity, originality)


def score(plan_id: str) -> dict:
    """Score the plan on twelve dimensions from its stored check reports. Run the checks first (`run_checks`) so the reports are current."""
    c = Ctx(plan_id)
    dims = [fn(c) for fn in DIMENSIONS]
    weakest = sorted((d for d in dims if d["band"] != "good"), key=lambda d: d["score"])[:3]
    out = {"computed_at": db.now(), "content_hash": content_hash(c.plan), "dimensions": dims, "disclaimer": DISCLAIMER,
           "summary": {"good": sum(d["band"] == "good" for d in dims), "ok": sum(d["band"] == "ok" for d in dims), "weak": sum(d["band"] == "weak" for d in dims),
                       "weakest": [d["key"] for d in weakest]}}
    return out


# ── checks, sign-off, approval ──────────────────────────────────────────────

def run_checks(plan_id: str) -> dict:
    """Every automatic check, in order, each saving its own report. No model is called."""
    n = planner.validate_plan(plan_id)
    s = storyboard.validate_storyboard(plan_id)
    p = imgplan.validate_prompts(plan_id) if any((sc["data"].get("prompts")) for sc in storyboard.get_scenes(plan_id)) else None
    return {"narration": n, "storyboard": s, "prompts": p}


def signoff(plan_id: str) -> dict:
    """What stands between this plan and approval. Blockers stop approval; warnings are shown and recorded with the approval."""
    reports = run_checks(plan_id)
    plan = planner.get_plan(plan_id)
    sc = score(plan_id)
    blockers, warns = [], []
    nrep, srep, prep = reports["narration"], reports["storyboard"], reports["prompts"]
    beats = (plan["blueprint"] or {}).get("beats", [])
    if not plan["blueprint"]:
        blockers.append({"code": "blueprint", "text": "The story is not planned yet.", "tab": "plan"})
    missing = [b for b in beats if b["id"] not in {s["beat"] for s in plan["segments"]}]
    if beats and missing:
        blockers.append({"code": "narration", "text": f"Narration is missing for {len(missing)} part(s).", "tab": "narration"})
    covered = {s["segment_id"] for s in plan["scenes"]}
    if plan["segments"] and any(s["id"] not in covered for s in plan["segments"]):
        blockers.append({"code": "storyboard", "text": "Some narration parts have no scenes.", "tab": "storyboard"})
    errs = [i for i in nrep["issues"] if i.get("level") != "warn"] + [i for i in srep["issues"] if i["level"] == "error"] + ([i for i in prep["issues"] if i["level"] == "error"] if prep else [])
    if errs:
        blockers.append({"code": "errors", "text": f"{len(errs)} error(s) must be fixed: " + ", ".join(sorted({i['kind'].replace('_', ' ') for i in errs})) + ".", "tab": "results"})
    if plan["scenes"] and not prep:
        blockers.append({"code": "prompts", "text": "Image prompts are not written yet.", "tab": "prompts"})
    if prep and any(i["kind"] in ("stale", "not_compiled") for i in prep["issues"]):
        blockers.append({"code": "prompts_stale", "text": "Some scenes have no current image prompts. Write them again.", "tab": "prompts"})
    pend_seg = [s for s in plan["segments"] if s["status"] != "approved" and not s["locked"]]
    pend_sc = [s for s in plan["scenes"] if s["status"] != "approved" and not s["locked"]]
    if pend_seg or pend_sc:
        blockers.append({"code": "unapproved", "text": f"{len(pend_seg)} narration part(s) and {len(pend_sc)} scene(s) are not approved yet.", "tab": "narration" if pend_seg else "storyboard"})
    weak = [d for d in sc["dimensions"] if d["band"] == "weak"]
    if weak:
        warns.append({"code": "weak", "text": "Weak on: " + ", ".join(d["label"] for d in weak) + ".", "tab": "review"})
    for d in sc["dimensions"]:
        if d["key"] == "generation_feasibility" and d["measured"].get("unconfirmed_licences"):
            warns.append({"code": "licence", "text": "A person has not confirmed the licence for " + ", ".join(providers.get(m)["label"] for m in d["measured"]["unconfirmed_licences"]) + ".", "tab": "models"})
    if plan["verification"] == "unverified":
        warns.append({"code": "unverified", "text": "The facts are not independently verified.", "tab": "plan"})
    warn_n = sum(1 for r in (nrep, srep, prep) if r for i in r["issues"] if i.get("level") == "warn")
    if warn_n:
        warns.append({"code": "warnings", "text": f"{warn_n} warning(s) in the checks.", "tab": "results"})
    out = {"ok": not blockers, "blockers": blockers, "warnings": warns, "scores": sc, "content_hash": sc["content_hash"]}
    plan = planner.get_plan(plan_id)                                  # reload: the checks above saved their reports
    summary = {"ok": out["ok"], "blockers": blockers, "warnings": warns, "content_hash": sc["content_hash"], "at": sc["computed_at"]}
    db.ex("UPDATE plans SET validation=?, updated_at=? WHERE id=?", (db.jdump({**(plan["validation"] or {}), "scores": sc, "signoff": summary}), db.now(), plan_id))
    return out


def approval_state(plan: dict) -> dict:
    a = (plan["settings"].get("approval") or {})
    if plan["status"] != "approved" or not a:
        return {"state": "draft"}
    same = a.get("content_hash") == content_hash(plan)
    return {"state": "approved" if same else "changed", **a}


def approve(plan_id: str, note: str = "") -> dict:
    so = signoff(plan_id)
    if not so["ok"]:
        raise planner.PlanError("cannot approve yet: " + " ".join(b["text"] for b in so["blockers"]))
    plan = planner.get_plan(plan_id)
    rec = {"at": db.now(), "content_hash": so["content_hash"], "note": note.strip()[:500], "warnings": [w["text"] for w in so["warnings"]],
           "scores": {d["key"]: d["score"] for d in so["scores"]["dimensions"]}}
    st = {**plan["settings"], "approval": rec}
    db.ex("UPDATE plans SET status='approved', settings=?, validation=?, updated_at=? WHERE id=?",
          (db.jdump(st), db.jdump({**(plan["validation"] or {}), "scores": so["scores"]}), db.now(), plan_id))
    store.log(plan_id, "approved", {"content_hash": so["content_hash"], "warnings": len(so["warnings"]), "note": rec["note"]})
    return approval_state(planner.get_plan(plan_id))


def unapprove(plan_id: str) -> dict:
    plan = planner.get_plan(plan_id)
    st = {k: v for k, v in plan["settings"].items() if k != "approval"}
    db.ex("UPDATE plans SET status='draft', settings=?, updated_at=? WHERE id=?", (db.jdump(st), db.now(), plan_id))
    store.log(plan_id, "unapproved", {})
    return approval_state(planner.get_plan(plan_id))


def history(plan_id: str, limit: int = 200) -> list[dict]:
    store.ensure()
    rows = db.q("SELECT id, ts, what, detail FROM plan_revisions WHERE plan_id=? ORDER BY id DESC LIMIT ?", (plan_id, limit))
    for r in rows:
        r["detail"] = db.jload(r["detail"], {})
    return rows
