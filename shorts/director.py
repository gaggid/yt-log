"""The Director (plan: docs/PLAN_scene_director.md, layer 4). It reads the scene review and fixes what is OBJECTIVELY wrong in a picture, nothing else:

  extra_object, wrong_place, text_in_picture, style_break, blank_background, wrong_count   (a defect the review found)
  duplicate                                                                                   (a scene that is a near-copy of an earlier one: the duplicate floor)

Taste (engagement, repeat, faces, places, composition) is never acted on. The model keeps the creative part: the Director names the problem in a note to the picture writer and never says what to draw.

Modes (setting `director`; a short made before it has no such key and stays `off`):
  off      nothing
  shadow   write down what it WOULD fix and why (the default for a new short: the review is new, so a person compares its list with their own eyes before it may change anything)
  defects  fix the defects

Every fix is a trial: the prompt is tidied by code and/or rewritten by the picture writer, the picture is drawn again, ONLY that picture is described again by the review, and the change is kept only when the
defects it was for are gone and no new kind of defect appeared. Otherwise it is set aside: the shot gets its old prompt back, so its old picture is the current one again (the trial picture stays as a
failed attempt that says why). Limits: 2 rounds, at most 30% of the shots per round, a shot that failed twice is left for a person, a time budget, one change per shot per round. A shot with a picture of the
person's own, an approved picture, a talking avatar or a clip already made is never touched. A failure anywhere never stops a short."""
import math
import time

from story import settings as settings_mod
from story3 import store as media

from . import clips, lint, pipelines as P, review, stillwriter, store

SETTING = "director"
MODES = ("off", "shadow", "defects")
MAX_ROUNDS = 2
MAX_SHARE = 0.3
MAX_TRIALS = 2
BUDGET_S = 25 * 60
FIXABLE = ("extra_object", "wrong_place", "text_in_picture", "style_break", "blank_background", "wrong_count")
NOTES = {
    "extra_object": "The picture shows an object that this shot does not ask for. Keep the picture to the things the shot idea names, each with its place.",
    "wrong_place": "The picture is set in the wrong place. Set it in {place}, as the shot says, with a real background.",
    "text_in_picture": "The picture must show no readable text or numbers. Show a screen as a soft glow, a banknote as plain coloured paper, a sign as a blank board.",
    "style_break": "The picture came out in a different look from the rest. Describe a real, recognisable place behind the subject and keep the same painted look as the other pictures.",
    "blank_background": "The background came out empty. Put a real, recognisable place behind the subject, in the same painted look as the other pictures.",
    "wrong_count": "The number of people is wrong. Say exactly how many people there are and where each one stands.",
    "duplicate": "This picture repeats scene {closest}. Show a different place and a different arrangement of the same idea, and keep what the line says.",
}


def mode(short: dict) -> str:
    m = (short.get("settings") or {}).get(SETTING)
    return m if m in MODES else "off"


def protected(short: dict, shot: dict) -> str:
    """Why a shot must not be touched (empty when it may be): the person's own picture, an approved picture, a talking avatar, a clip already made."""
    if P.start_source(short, shot) in ("upload", "anchor"):
        return "its picture is the person's own"
    if shot.get("avatar"):
        return "it is a talking avatar"
    if any(i["approved"] for i in media.items(short["id"], store.KEY, shot["id"])):
        return "its picture is approved by a person"
    if clips.chosen_clip(short, shot):
        return "its clip is already made"
    return ""


def actions(short: dict) -> list[dict]:
    """What the Director would fix, worst shot first: one action per shot with the defect kinds it is for, the plain-words defects and the note the picture writer gets."""
    rv = short.get("review") or {}
    scenes = rv.get("scenes") or {}
    dup = {i for f in rv.get("floors") or [] if f["floor"] == "duplicate" for i in f["shots"]}
    failed = (short.get("director") or {}).get("failed") or {}
    out = []
    for sid in rv.get("order") or []:
        sc, shot = scenes.get(sid), next((x for x in short["shots"] if x["id"] == sid), None)
        if not sc or not shot:
            continue
        kinds = [d["kind"] for d in sc["defects"] if d["kind"] in FIXABLE]
        if sid in dup:
            kinds.append("duplicate")
        kinds = list(dict.fromkeys(kinds))
        if not kinds:
            continue
        why = protected(short, shot)
        left = int(failed.get(sid, 0)) >= MAX_TRIALS
        place = lint.scene_place(shot.get("still") or "") or lint.place_of(shot.get("setting") or "") or lint.place_of((short.get("plan") or {}).get("place") or "")
        note = " ".join(NOTES[k].format(place=(place[1].strip() if place else "the place the shot names"), closest=sc["repeat"].get("closest") or "an earlier one") for k in kinds)
        out.append({"shot": sid, "kinds": kinds, "defects": [d["text"] for d in sc["defects"] if d["kind"] in kinds] + (["a near-duplicate of " + sc["repeat"]["closest"]] if "duplicate" in kinds else []), "note": note,
                    "skip": why or ("it failed two trials, a person should look" if left else "")})
    return sorted(out, key=lambda a: (bool(a["skip"]), -len(a["kinds"]), int(a["shot"][1:])))


# ── one trial ─────────────────────────────────────────────────────────────────────────

FIELDS = ("still", "subjects", "setting", "must_show", "still_by")


def _snapshot(shot: dict) -> dict:
    import copy
    return {k: copy.deepcopy(shot.get(k)) for k in FIELDS if k in shot} | {"_missing": [k for k in FIELDS if k not in shot]}


def _restore(shot: dict, snap: dict) -> None:
    import copy
    for k in FIELDS:
        if k in snap:
            shot[k] = copy.deepcopy(snap[k])
    for k in snap["_missing"]:
        shot.pop(k, None)


async def trial(short_id: str, act: dict, backend, s: dict, key: str, round_no: int) -> dict:
    """Fix one shot and keep the fix only if it removed the defects it was for and brought no new kind. Returns the log entry."""
    short = store.get(short_id)
    shot = store.shot_by_id(short, act["shot"])
    beat = next(b for b in short["beats"] if b["id"] == shot["beat"])
    beat_shots = [x for sid in beat["shot_ids"] for x in short["shots"] if x["id"] == sid]
    before = [d["kind"] for d in (short["review"]["scenes"][act["shot"]]["defects"])]
    snap = _snapshot(shot)
    before_ids = {i["id"] for i in media.items(short_id, store.KEY, act["shot"])}
    entry = {"shot": act["shot"], "round": round_no, "kinds": act["kinds"], "before": before, "how": [], "at": time.time()}
    try:
        if lint.enabled(short) and lint.tidy_shot(short, shot):
            entry["how"].append("code")
        if await stillwriter.write_beat(short, beat, beat_shots, backend, s, only={act["shot"]}, note=act["note"]):
            entry["how"].append("writer")
        store.save(short)
        res = await clips.make_keyframes(short_id, shot_ids=[act["shot"]], only_missing=False, s=s, key=key)
        if res["failed"]:
            raise RuntimeError(res["failed"][0]["error"])
        short = store.get(short_id)
        shot = store.shot_by_id(short, act["shot"])
        new = clips.chosen_keyframe(short, shot)
        items = [(shot, new, media.path_of(new))]
        seen = await review.describe(short, items, backend, s)
        if act["shot"] not in seen:
            raise RuntimeError("the new picture could not be described")
        found, notes = review.defects(short, shot, seen[act["shot"]])
        after = [d["kind"] for d in found]
        left = [k for k in act["kinds"] if k in after]
        fresh = [k for k in after if k not in before]
        entry.update(after=after, seen=seen[act["shot"]], notes=notes)
        if "duplicate" in act["kinds"] and not [k for k in act["kinds"] if k != "duplicate"]:
            left = []                                           # a duplicate is judged again by the whole-short review at the end of the round
        if not left and not fresh:
            entry["result"] = "kept"
            entry["why"] = "the defects are gone" + (" and nothing new appeared" if not fresh else "")
            entry["picture"] = new["id"]
            return entry
        entry["why"] = ("still there: " + ", ".join(left) if left else "") + ("; new: " + ", ".join(fresh) if fresh else "")
        entry["result"] = "reverted"
    except Exception as e:  # noqa: BLE001
        entry.update(result="failed", why=str(e)[:160])
    short = store.get(short_id)                                  # set the trial aside: the old prompt is back, so the old picture is the current one again
    shot = store.shot_by_id(short, act["shot"])
    _restore(shot, snap)
    store.save(short)
    for it in media.items(short_id, store.KEY, act["shot"]):
        if it["id"] not in before_ids:                          # the pictures this trial drew stay as failed attempts that say why
            media.update(it["id"], status="failed", meta={"error": f"set aside by the Director: {entry.get('why', '')}"})
    return entry


# ── the run ──────────────────────────────────────────────────────────────────────────────

def stamp(short: dict) -> str:
    return review.stamp(short)


def current(short: dict) -> bool:
    return bool((short.get("director") or {}).get("stamp") == stamp(short))


def waiting() -> int:
    """How many shorts are stopped before their clips waiting for a person's look (the autopilot lets a third one through with a warning)."""
    return sum(1 for x in store.listing() if x.get("needs_look") and not x.get("keyframes_confirmed") and x.get("status") != "made")


def defect_count(short: dict) -> int:
    return sum(len([d for d in sc["defects"] if d["kind"] in FIXABLE]) for sc in (short.get("review") or {}).get("scenes", {}).values())


async def _refresh(short_id: str, backend, s: dict, changed: set[str]) -> None:
    """The review of the whole short again from what is known: the pictures that changed are described again, the rest keep their description."""
    short = store.get(short_id)
    items = review.pictures(short)
    seen = {sid: sc["seen"] for sid, sc in (short.get("review") or {}).get("scenes", {}).items() if sid not in changed}
    new_items = [x for x in items if x[0]["id"] in changed]
    if new_items:
        seen.update(await review.describe(short, new_items, backend, s))
    res = review.review_scenes(short, items, seen)
    short["review"] = {"at": time.time(), "stamp": review.stamp(short), **res}
    store.save(short)


async def run(short_id: str, backend, s: dict | None = None, key: str = "", override: str = "", progress=None) -> dict:
    """The Director on one short: shadow writes down what it would fix; defects fixes it. The scene review is made first when it is missing or old."""
    s = s or settings_mod.get()
    short = store.get(short_id)
    m = override if override in MODES else mode(short)
    if m == "off":
        return report(short)
    if not review.current(short):
        await review.run(short_id, backend, s)
        short = store.get(short_id)
    planned = actions(short)
    short["director"] = {**(short.get("director") or {}), "mode": m, "at": time.time(), "planned": planned, "log": (short.get("director") or {}).get("log", []), "failed": (short.get("director") or {}).get("failed", {}),
                         "before": defect_count(short), "after": None, "rounds": 0, "budget_used_s": 0, "stamp": ""}
    if m == "shadow":
        short["director"]["stamp"] = stamp(short)
        store.save(short)
        return report(short)
    store.save(short)
    t0 = time.monotonic()
    budget = float(s.get("director_budget_s") or BUDGET_S)
    cap = max(1, math.ceil(MAX_SHARE * len(short["shots"])))
    for rnd in range(1, MAX_ROUNDS + 1):
        short = store.get(short_id)
        todo = [a for a in actions(short) if not a["skip"]][:cap]
        if not todo:
            break
        start = defect_count(short)
        changed: set[str] = set()
        for i, act in enumerate(todo):
            if time.monotonic() - t0 > budget:
                break
            if progress:
                progress(i, len(todo), f"fixing {act['shot']} (round {rnd})")
            entry = await trial(short_id, act, backend, s, key, rnd)
            short = store.get(short_id)
            d = short["director"]
            d["log"].append(entry)
            if entry["result"] != "kept":
                d["failed"][act["shot"]] = int(d["failed"].get(act["shot"], 0)) + 1
            d["rounds"] = rnd
            store.save(short)
            if entry["result"] == "kept":
                changed.add(act["shot"])                            # a set-aside shot keeps its old picture AND its old description: describing it again only adds noise (the same picture read differently) and would hide the defect that is still there
        await _refresh(short_id, backend, s, changed)
        short = store.get(short_id)
        if defect_count(short) >= start or time.monotonic() - t0 > budget:
            break
    short = store.get(short_id)
    d = short["director"]
    d.update(after=defect_count(short), budget_used_s=round(time.monotonic() - t0), planned=actions(short), stamp=stamp(short))
    hard = [f for f in (short.get("review") or {}).get("floors", []) if f["floor"] in ("hook", "dead_stretch")]
    if hard:
        short["needs_look"] = {"floors": hard, "at": time.time()}
    else:
        short.pop("needs_look", None)
    store.save(short)
    return report(short)


def report(short: dict) -> dict:
    d = short.get("director") or {}
    return {"mode": mode(short), "ran": d.get("mode", ""), "ready": review.ready(short) if mode(short) != "off" else False, "current": current(short) if d else False, "at": d.get("at"), "planned": d.get("planned", []),
            "log": d.get("log", []), "before": d.get("before"), "after": d.get("after"), "rounds": d.get("rounds", 0), "budget_used_s": d.get("budget_used_s", 0),
            "needs_look": short.get("needs_look"), "failed": d.get("failed", {})}
