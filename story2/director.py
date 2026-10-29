"""The director: one pass over the whole narration that plans how the video is shot (emotion, place, and a shot list with size, angle and camera
move for every segment) before any scene is designed. The storyboard model then receives the whole story's map and its own segment's shots, each
scene names the shot it follows, and the shot's size, angle and move are written into the scene, so the plan reaches the pictures and the video."""
import hashlib
import re
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, field_validator

from story import db, llm, settings as settings_mod, storytypes
from story.schemas import Str

from . import intake, planner, prompts as P, store, styles

SIZES = ("extreme wide", "wide", "medium", "close", "extreme close")
ANGLES = ("eye level", "low", "high", "overhead", "side", "over the shoulder")
MOVES = ("push in", "pull back", "pan right", "pan left", "tilt up", "tilt down", "drift", "hold")
KINDS = ("person", "reaction", "hands", "object", "place", "establishing", "texture")
PEOPLE_KINDS = ("person", "reaction")
MAX_PEOPLE_SHARE = 0.45
MAX_HOLD_SHARE = 0.15


# what kind of shot an event is (the event decides it, the director decides how it is shot)
EVENT_KIND = {"place": "place", "person": "person", "reaction": "reaction", "hands": "hands", "object": "object", "document": "object", "map": "object", "crowd": "place", "texture": "texture", "phone": "object"}


def _pick(v, options, default, aliases=()):
    t = re.sub(r"[-_]+", " ", str(v or "")).lower().strip()
    for a, b in aliases:
        if a in t:
            return b
    for o in sorted(options, key=len, reverse=True):          # "extreme close" before "close"
        if o in t:
            return o
    return default


def _size(v):
    return _pick(v, SIZES, "medium", (("long", "wide"), ("full", "wide"), ("detail", "extreme close"), ("macro", "extreme close")))


def _angle(v):
    return _pick(v, ANGLES, "eye level", (("bird", "overhead"), ("top", "overhead"), ("worm", "low"), ("shoulder", "over the shoulder"), ("profile", "side")))


# ── act-level camera language and point-of-view shots (task 3.14) ─────────────────────────────────────────────────────────────────────────────────────────
# The film is told in three acts and the camera behaves differently in each: calm and locked while the world is set up, closer and moving while it tightens, decisive in the last act.
ACT_MOVES = {1: ("hold", "push in", "pan right", "pan left", "drift"), 2: ("drift", "pan right", "pan left", "push in", "tilt up", "tilt down"), 3: ("push in", "pull back", "tilt up", "hold")}
ACT_EDGES = (0.25, 0.75)                      # shares of the running time where act 2 and act 3 begin
POV_THROUGH = (("phone", "a phone screen"), ("screen", "a phone screen"), ("car window", "a car window"), ("bus window", "a bus window"), ("window", "a window"), ("door", "a doorway"), ("cctv", "a CCTV camera"), ("camera", "a CCTV camera"),
               ("binocular", "binoculars"), ("car", "a car window"), ("keyhole", "a keyhole"), ("bus", "a bus window"))
MAX_POV = 8


def act_of(index: int, total: int) -> int:
    """The act (1 to 3) of segment `index` (1-based) out of `total`."""
    pos = (index - 0.5) / max(1, total)
    return 1 if pos < ACT_EDGES[0] else 2 if pos < ACT_EDGES[1] else 3


def apply_acts(by: dict, total: int) -> None:
    """Give every segment its act and bring each shot's camera move into the grammar of that act (a shot keeps its move when the act allows it; otherwise it takes the act's moves
    in turn, never the same twice in a row). The very last shot of the film pulls back. Reveal shots in act 3 push in."""
    last = None
    for key in sorted(by, key=int):
        seg = by[key]
        act = act_of(int(key), total)
        seg["act"] = act
        for sh in seg["shots"]:
            sh["act"] = act
            allowed = ACT_MOVES[act]
            if sh.get("move") not in allowed:
                pool = [m for m in allowed if m != last] or list(allowed)
                sh["move"] = pool[(int(key) + seg["shots"].index(sh)) % len(pool)]
            elif sh["move"] == last:
                sh["move"] = next((m for m in allowed if m != last), sh["move"])
            last = sh["move"]
    if by:
        final = by[max(by, key=int)]["shots"]
        if final:
            final[-1]["move"] = "pull back"


def mark_pov(by: dict, evs: list[dict]) -> int:
    """Mark up to MAX_POV shots as seen through an object (a phone screen, a window, a CCTV camera...) when their event is about one, spread over the film. Returns how many."""
    by_event = {e["id"]: e for e in evs}
    cands = []
    for key in sorted(by, key=int):
        for sh in by[key]["shots"]:
            e = by_event.get(sh.get("event", ""))
            if not e or e.get("reveal"):
                continue
            text = f"{e.get('key_object', '')} {e.get('doing', '')}".lower()
            through = next((v for k, v in POV_THROUGH if k in text), "")
            if through and sh.get("kind") in ("object", "hands", "person", "reaction", "place"):
                cands.append((sh, through, e))
    if not cands:
        return 0
    step = max(1, len(cands) // MAX_POV)
    n = 0
    for sh, through, e in cands[::step][:MAX_POV]:
        who = (e.get("who") or ["someone"])[0] if isinstance(e.get("who"), list) else str(e.get("who") or "someone")
        sh["pov"] = {"through": through, "of": who}
        n += 1
    return n


def _move(v):
    return _pick(v, MOVES, "drift", (("zoom in", "push in"), ("dolly in", "push in"), ("creep", "push in"), ("zoom out", "pull back"), ("dolly out", "pull back"),
                                      ("reveal", "pull back"), ("static", "hold"), ("still", "hold"), ("crane up", "tilt up"), ("rise", "tilt up")))


def _kind(v):
    return _pick(v, KINDS, "person", (("face", "person"), ("character", "person"), ("portrait", "person"), ("wide", "establishing")))


class M(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ShotOut(M):
    focus: Str = ""
    kind: Annotated[str, BeforeValidator(_kind)] = "person"
    size: Annotated[str, BeforeValidator(_size)] = "medium"
    angle: Annotated[str, BeforeValidator(_angle)] = "eye level"
    move: Annotated[str, BeforeValidator(_move)] = "drift"
    why: Str = ""
    event: Str = ""                                          # the visual event this shot shows (story2/events.py); empty for shots planned without events


class DirSegOut(M):
    segment: int = 0
    emotion: Str = ""
    place: Str = ""
    state: Str = ""
    shots: list[ShotOut] = []


class DirectorOut(M):
    arc: Str = ""
    segments: list[DirSegOut]

    @field_validator("segments")
    @classmethod
    def _s(cls, v):
        if not v:
            raise ValueError("no segments were planned")
        return v


def problems(shots: list[dict], n_segments: int, planned: set[int], seconds: dict[int, float], events: dict[int, int] | None = None) -> list[str]:
    """What a director would not accept: missing segments, too few shots, a face in every frame, the same frame twice in a row. With events planned, a segment has exactly
    one shot per event."""
    out = []
    missing = [i for i in range(1, n_segments + 1) if i not in planned]
    if missing:
        out.append(f"segments {', '.join(map(str, missing))} have no shots: plan every segment from 1 to {n_segments}")
    if events:
        off = [f"segment {i} has {sum(1 for x in shots if x['segment'] == i)} shot(s) for {k} events" for i, k in events.items() if i in planned and sum(1 for x in shots if x["segment"] == i) != k]
        if off:
            out.append("plan exactly one shot for each event: " + "; ".join(off))
    thin = [] if events else [i for i, s in seconds.items() if i in planned and sum(1 for x in shots if x["segment"] == i) < max(1, round(s / 8))]
    if thin:
        out.append(f"too few shots in segment(s) {', '.join(map(str, thin))}: plan about one shot per 4 to 6 seconds")
    if shots:
        share = sum(1 for x in shots if x["kind"] in PEOPLE_KINDS) / len(shots)
        if share > MAX_PEOPLE_SHARE:
            out.append(f"{round(share * 100)}% of the shots are a person's face or body (limit {round(MAX_PEOPLE_SHARE * 100)}%): make more of them hands, objects, places, establishing shots")
    # per-segment check: a segment where every shot is a person is visually suffocating
    seg_shots: dict[int, list[dict]] = {}
    for x in shots:
        seg_shots.setdefault(x["segment"], []).append(x)
    for seg_i, seg_s in seg_shots.items():
        if len(seg_s) >= 3 and all(x["kind"] in PEOPLE_KINDS for x in seg_s):
            out.append(f"segment {seg_i}: all {len(seg_s)} shots are a person's face or body; add at least one place, hands, object or texture shot")
    held = sum(1 for x in shots if x["move"] == "hold")
    if shots and held / len(shots) > MAX_HOLD_SHARE:
        out.append(f"{held} of {len(shots)} shots are \"hold\" (a still frame); at most {round(MAX_HOLD_SHARE * 100)}% may be. Give most shots a push in, pull back, pan, tilt or drift")
    for a, b in zip(shots, shots[1:]):
        if (a["size"], a["angle"]) == (b["size"], b["angle"]):
            out.append(f"segment {b['segment']}: two shots in a row have the same size and angle (after '{a['focus'][:30]}'): change one")
            break
    for a, b, c in zip(shots, shots[1:], shots[2:]):
        if a["size"] == b["size"] == c["size"]:
            out.append(f"three {a['size']} shots in a row near segment {b['segment']}: change the size of one")
            break
    if len({x["size"] for x in shots}) < 3 and len(shots) >= 6:
        out.append("use at least three different shot sizes in the video")
    return out


def narration_key(segs: list[dict]) -> str:
    return hashlib.sha1("|".join(sg["plain"] for sg in segs).encode("utf-8")).hexdigest()[:10]


def current(plan: dict) -> bool:
    """Is there a shot plan, made for this narration and this visual direction?"""
    d = (plan["settings"] or {}).get("director")
    from . import events as events_mod                                       # late import: events builds on this module
    ev_ok = (d or {}).get("events", "") == (events_mod.key(plan) if events_mod.current(plan) else "")        # a shot plan made for other events (or none) is not this plan's
    return bool(d and d.get("by_segment") and d.get("direction") == styles.DIRECTION and d.get("narration") == narration_key(sorted(plan["segments"], key=lambda x: x["seq"])) and ev_ok)


def _hook_brief(bp: dict) -> str:
    """Mandatory first-shot instruction from the blueprint's hook_scene_brief field."""
    h = (bp.get("hook_scene_brief") or "").strip()
    return f"\n\nHOOK (first shot of segment 1 — mandatory): {h}" if h else ""


def _beat_visual_brief(bp: dict, segs: list[dict]) -> str:
    """One line per segment that has a visual brief in its beat. Empty string when the blueprint has none."""
    beats = {b["id"]: b for b in (bp.get("beats") or [])}
    lines = []
    for i, sg in enumerate(segs, 1):
        b = beats.get(sg["beat"], {})
        pv = (b.get("primary_visual") or "").strip()
        unf = [x for x in (b.get("unfilmable") or []) if x]
        vd = (b.get("visual_device") or "").strip()
        rh = (b.get("retention_hook") or "").strip()
        if pv or unf or rh:
            line = f"  Segment {i} (beat {sg['beat']}): show first — {pv}."
            if unf:
                line += f" Cannot film directly: {'; '.join(unf)}."
            if vd:
                line += f" Visual device: {vd}."
            if rh:
                line += f" Retention hook: {rh}."
            lines.append(line)
    return ("\n\nVISUAL BRIEF (what each segment must show — plan shots that deliver this before character reaction shots):\n" + "\n".join(lines)) if lines else ""


async def make(plan_id: str, backend, s: dict | None = None) -> dict:
    from . import storyboard
    s = s or settings_mod.get()
    plan = planner.get_plan(plan_id)
    if not plan["segments"]:
        raise planner.PlanError("write the narration first")
    story = planner._story_for(plan)
    segs = sorted(plan["segments"], key=lambda x: x["seq"])
    wpm = plan["settings"].get("wpm", planner.WPM)
    real = storyboard.real_audio(plan_id)
    secs = {i: sum(storyboard.sentence_seconds(sg, wpm, real.get(sg["id"]))) for i, sg in enumerate(segs, 1)}
    bp = plan["blueprint"] or {}
    narration = "\n".join(f"SEGMENT {i} (beat {sg['beat']}, {secs[i]:.0f} s): {sg['plain']}" for i, sg in enumerate(segs, 1))
    from . import events as events_mod                                       # late import: events builds on this module
    ev_by_seg = {i: events_mod.for_segment(plan, sg["id"]) for i, sg in enumerate(segs, 1)} if events_mod.current(plan) else {}
    counts = {i: len(v) for i, v in ev_by_seg.items() if v}
    if counts:
        narration += "\n\nTHE EVENTS OF EACH SEGMENT (one shot for each, in order):\n" + "\n".join(
            f"SEGMENT {i}: " + " || ".join(f"{e['id']} [{e['kind']}] {e['where']}: {e['doing']}" + (" (REVEAL)" if e["reveal"] else "") for e in evs) for i, evs in ev_by_seg.items() if evs)
    user = ("STORY FACTS:\n" + intake.facts_text(story["public"]) + "\n\nVIDEO PLAN: " + (bp.get("viewer_promise", "") + " Structure: " + bp.get("structure", "")).strip()
            + "\n\nCONTINUITY (use these place names):\n" + storyboard._asset_lines(storyboard.get_assets(plan_id)) + f"\n\nNARRATION:\n{narration}"
            + _beat_visual_brief(bp, segs)
            + _hook_brief(bp)
            + f"\n\nVISUAL STYLE: {styles.for_plan(plan['settings'])['short']}.\nPlan the film now: {len(segs)} segments.")
    tries: list[int] = []
    caller = llm.JsonCaller(backend, s)

    def check(out: DirectorOut) -> None:
        tries.append(1)
        rows = [dict(sh.model_dump(), segment=sg.segment) for sg in sorted(out.segments, key=lambda x: x.segment) for sh in sg.shots]
        bad = problems(rows, len(segs), {sg.segment for sg in out.segments if sg.shots}, secs, counts or None)
        if bad and len(tries) <= 2 and not caller.last_attempt:
            raise ValueError("The shot plan is not accepted yet:\n- " + "\n- ".join(bad))

    res = await caller.call(P.DIRECTOR + (P.DIRECTOR_EVENTS if counts else "") + storytypes.director_note(storytypes.of_plan(plan)), user, DirectorOut, check)
    by = {}
    for sg in res.value.segments:
        if 1 <= sg.segment <= len(segs) and sg.shots:
            shots = [x.model_dump() for x in sg.shots]
            evs = ev_by_seg.get(sg.segment) or []
            if evs and len(shots) == len(evs):                              # one shot per event: the shot carries the event's id, and what the event is decides the kind of shot
                for shot, e in zip(shots, evs):
                    shot["event"], shot["kind"] = e["id"], EVENT_KIND.get(e["kind"], shot["kind"])
            by[str(sg.segment)] = {"segment_id": segs[sg.segment - 1]["id"], "emotion": sg.emotion, "place": sg.place, "state": sg.state, "shots": shots}
    apply_acts(by, len(segs))
    pov = mark_pov(by, events_mod.of(plan)) if counts else 0
    plan = planner.get_plan(plan_id)
    db.ex("UPDATE plans SET settings=?, updated_at=? WHERE id=?",
          (db.jdump({**plan["settings"], "director": {"arc": res.value.arc, "by_segment": by, "direction": styles.DIRECTION, "narration": narration_key(segs), "events": events_mod.key(plan) if counts else ""}}), db.now(), plan_id))
    store.log(plan_id, "director", {"segments": len(by), "shots": sum(len(v["shots"]) for v in by.values()), "pov": pov})
    return planner.get_plan(plan_id)


def story_map(plan: dict, current_index: int) -> str:
    """The whole story in one line per segment, so a scene is designed knowing what came before and what comes next."""
    d = plan["settings"]["director"]
    segs = sorted(plan["segments"], key=lambda x: x["seq"])
    lines = [f"Emotional arc of the video: {d.get('arc', '')}"]
    for i, sg in enumerate(segs, 1):
        v = d["by_segment"].get(str(i)) or {}
        first = (sg["sentences"][0]["text"] if sg["sentences"] else "")[:90]
        lines.append(f"{'>> ' if i == current_index else '   '}{i}. [{v.get('emotion', '')} / {v.get('place', '')}] {first}")
    return "\n".join(lines)


def shots_for(plan: dict, index: int) -> list[dict]:
    return list(((plan["settings"].get("director") or {}).get("by_segment", {}).get(str(index)) or {}).get("shots", []))


def shot_list(plan: dict, index: int) -> str:
    v = plan["settings"]["director"]["by_segment"].get(str(index)) or {}
    rows = [f"{n}. {x['kind']}: {x['focus']}. {x['size']}, {x['angle']}, camera move: {x['move']}. ({x['why']})" for n, x in enumerate(v.get("shots", []), 1)]
    return (f"Emotion: {v.get('emotion', '')}. Place: {v.get('place', '')}. State: {v.get('state', '')}\n" + "\n".join(rows)) if rows else ""
