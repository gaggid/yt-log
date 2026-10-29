"""The visual events ledger (docs/AUDIT_2026-10-29.md sections 3.5, 14.2 and 14.4; task 3.1): what the camera sees, planned from the narration and the Material Pack BEFORE any
picture is designed. Each event is one filmable moment under a run of consecutive narration sentences, grounded in story details, different from every other event, and in a
place the story really goes. The storyboard (v2) turns events into scenes, so a scene always shows something that happens in the story and never just a mood for the words.

Events are written per narration part, in order, each call seeing the places and events already used, so the film moves through many places and never shows one thing twice."""
import re
from typing import Annotated

from pydantic import BeforeValidator, field_validator

from story import db, llm, settings as settings_mod
from story.schemas import Str, StrList

from . import director, material, planner, prompts as P, store, storyboard
from .scene_schemas import M, _range

KINDS = ("place", "person", "reaction", "hands", "object", "document", "map", "crowd", "texture", "phone")
FACE_KINDS = ("person", "reaction")
MAX_EVENT_S = 8.0
MAX_SAME_PLACE_RUN = 2
MAX_FACE_SHARE = 0.5
MAX_UNGROUNDED_SHARE = 1 / 6
STOP = set("the a an of and or to in on at with for from by is are was were be as it its this that his her their over under into out up down he she they him them who".split())


def _kind(v) -> str:
    v = re.sub(r"[^a-z]", "", str(v or "").lower())
    alias = {"face": "person", "portrait": "person", "closeup": "person", "establishing": "place", "wide": "place", "location": "place", "detail": "object", "insert": "object", "prop": "object",
             "hand": "hands", "paper": "document", "screen": "phone", "chat": "phone", "route": "map", "street": "crowd", "background": "texture", "atmosphere": "texture"}
    v = alias.get(v, v)
    return v if v in KINDS else "place"


def _bool(v) -> bool:
    return v if isinstance(v, bool) else str(v).strip().lower() in ("true", "yes", "1")


class EventOut(M):
    sentences: Annotated[list[int], BeforeValidator(_range)] = []
    kind: Annotated[str, BeforeValidator(_kind)] = "place"
    who: StrList = []
    where: Str = ""
    doing: Str = ""
    key_object: Str = ""
    foreground: Str = ""
    period: Str = ""
    ledger: StrList = []
    reveal: Annotated[bool, BeforeValidator(_bool)] = False
    clue: Annotated[bool, BeforeValidator(_bool)] = False

    @field_validator("doing")
    @classmethod
    def _d(cls, v):
        if len(v.split()) < 3:
            raise ValueError("each event needs a plain description of what is happening")
        return v


class EventsOut(M):
    events: list[EventOut]

    @field_validator("events")
    @classmethod
    def _e(cls, v):
        if not v:
            raise ValueError("no events were planned")
        return v


def _words(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", (t or "").lower()) if w not in STOP}


def sameness(a: dict, b: dict) -> float:
    """How alike two events are, by the words of place, people, action and object (0 to 1)."""
    wa = _words(" ".join([a.get("where", ""), a.get("doing", ""), a.get("key_object", ""), " ".join(a.get("who", []))]))
    wb = _words(" ".join([b.get("where", ""), b.get("doing", ""), b.get("key_object", ""), " ".join(b.get("who", []))]))
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


def same_place(a: dict, b: dict) -> bool:
    """Two events are in the same place when what they say about it shares at least half its distinctive words."""
    wa, wb = _words(a.get("where", "")), _words(b.get("where", ""))
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) >= 0.5


def problems(evs: list[dict], seconds: list[float], earlier: list[dict], valid_ids: set[str]) -> list[str]:
    """What sends a part's events back: uncovered or too long events, repeats, runs in one place, too many faces, events with no detail behind them."""
    out: list[str] = []
    n = len(seconds)
    covered = [0] * n
    for k, e in enumerate(evs, 1):
        a, b = e["sentences"][0], e["sentences"][-1]
        for i in range(max(1, a), min(n, b) + 1):
            covered[i - 1] += 1
        span = sum(seconds[max(1, a) - 1:min(n, b)])
        if span > MAX_EVENT_S + 1.5:
            out.append(f"event {k} plays for {span:.0f} s (sentences {a} to {b}); an event is at most {MAX_EVENT_S:.0f} s: split it into events that show different things")
    miss = [str(i + 1) for i, c in enumerate(covered) if c == 0]
    if miss:
        out.append("sentences with no event: " + ", ".join(miss))
    for k, e in enumerate(evs):
        for j, prev in enumerate(evs[:k] + earlier[-12:]):
            if sameness(e, prev) >= 0.7:
                out.append(f"event {k + 1} ({e['doing'][:50]}) shows the same thing as an earlier one ({prev['doing'][:50]}): show something else")
                break
    run = 0
    for k in range(1, len(evs)):
        run = run + 1 if same_place(evs[k], evs[k - 1]) else 0
        if run >= MAX_SAME_PLACE_RUN:
            out.append(f"more than {MAX_SAME_PLACE_RUN} events in a row are in the same place ({evs[k]['where'][:40]}): move to another place")
            break
    faces = sum(1 for e in evs if e["kind"] in FACE_KINDS)
    if len(evs) >= 3 and faces / len(evs) > MAX_FACE_SHARE:
        out.append(f"{faces} of {len(evs)} events are faces; at most half may be: show hands, objects, documents, places")
    bare = [k for k, e in enumerate(evs, 1) if not [x for x in e["ledger"] if x in valid_ids] and e["kind"] not in ("texture", "crowd")]
    if len(bare) > max(1, len(evs) * MAX_UNGROUNDED_SHARE):
        out.append(f"events {', '.join(map(str, bare[:6]))} are not grounded in any story detail: give each the ids of the details it shows, or make it a texture or world shot (at most one in six)")
    return out


def repair_ranges(raw: list[dict], n: int) -> list[dict]:
    """Make the events' sentence ranges cover 1..n once, in order (gaps are taken by the event before them, overlaps trimmed)."""
    fixed = storyboard.repair_coverage([e["sentences"] or [1, 1] for e in raw], n)
    return [{**e, "sentences": r} for e, r in zip(raw, fixed)]


def _summary(evs: list[dict]) -> str:
    return "\n".join(f"- {e['where']}: {e['doing']}" for e in evs[-10:]) or "- none yet: this is the first part of the video"


def _places_used(evs: list[dict]) -> str:
    c: dict[str, int] = {}
    for e in evs:
        c[e["where"]] = c.get(e["where"], 0) + 1
    return "; ".join(f"{k} ({v})" for k, v in sorted(c.items(), key=lambda kv: -kv[1])[:14]) or "none yet"


def user_text(plan: dict, seg: dict, secs: list[float], idx: int, total: int, earlier: list[dict], items: list[dict]) -> str:
    beat = next((b for b in (plan["blueprint"] or {}).get("beats", []) if b["id"] == seg["beat"]), {})
    lines = "\n".join(f"{i}. ({secs[i - 1]:.1f}s) {x['text']}" for i, x in enumerate(seg["sentences"], 1))
    mine = [it for it in items if it["id"] in set(beat.get("use", [])) | set(beat.get("show", []))]
    rest = [it for it in items if it not in mine]
    return (f"THE FILM: {plan['blueprint'].get('viewer_promise', '')}\nPART {idx} of {total} ({beat.get('name', '')}): {beat.get('purpose', '')}\nthe turn of this part: {beat.get('turn', '')}\n\n"
            f"STORY DETAILS FOR THIS PART (use their ids in \"ledger\"):\n{material.text_for({'settings': {'material': {'items': mine}}})}\n\n"
            f"OTHER STORY DETAILS (for places, people and objects to show; mostly told in other parts):\n{material.text_for({'settings': {'material': {'items': rest}}})[:2500]}\n\n"
            f"PLACES USED SO FAR IN THE VIDEO (count): {_places_used(earlier)}\nTHE LAST EVENTS:\n{_summary(earlier)}\n\n"
            f"THE NARRATION OF THIS PART, {len(seg['sentences'])} sentence(s), {sum(secs):.0f} s:\n{lines}\n\nPlan the events now.")


async def make_events(plan_id: str, backend, s: dict | None = None, segment_ids: list[str] | None = None, progress=None) -> dict:
    """Plan the events of every narration part (or the given ones), part by part. Events of parts not asked for are kept."""
    s = s or settings_mod.get()
    plan = planner.get_plan(plan_id)
    if not plan["segments"]:
        raise planner.PlanError("write the narration first")
    if not material.has(plan):
        raise planner.PlanError("collect the story material first")
    segs = sorted(plan["segments"], key=lambda x: x["seq"])
    items = material.pack(plan)["items"]
    valid = {it["id"] for it in items}
    wpm = plan["settings"].get("wpm", planner.WPM)
    real = storyboard.real_audio(plan_id)
    keep = [e for e in (plan["settings"].get("events") or []) if segment_ids and e["segment_id"] not in segment_ids]
    todo = [x for x in segs if not segment_ids or x["id"] in segment_ids]
    out = list(keep)
    for k, seg in enumerate(todo):
        if progress:
            progress(k, len(todo), f"events for part {k + 1} of {len(todo)}")
        before = [e for e in out if e["segment_id"] != seg["id"]]
        earlier = [e for e in before if next((i for i, x in enumerate(segs) if x["id"] == e["segment_id"]), 99) < segs.index(seg)]
        secs = storyboard.sentence_seconds(seg, wpm, real.get(seg["id"]))
        n = len(seg["sentences"])
        caller = llm.JsonCaller(backend, s)

        def check(res: EventsOut, secs=secs, earlier=earlier, n=n, caller=caller) -> None:
            evs = repair_ranges([e.model_dump() for e in res.events], n)
            bad = problems(evs, secs, earlier, valid)
            if bad and not caller.last_attempt:
                raise ValueError("The events are not right yet:\n- " + "\n- ".join(bad[:8]))

        res = await caller.call(P.EVENTS, user_text(plan, seg, secs, segs.index(seg) + 1, len(segs), earlier, items), EventsOut, check)
        evs = repair_ranges([e.model_dump() for e in res.value.events], n)
        out = [e for e in out if e["segment_id"] != seg["id"]]
        base = len(out)
        out += [{**e, "id": f"e{base + i + 1}", "segment_id": seg["id"], "ledger": [x for x in e["ledger"] if x in valid]} for i, e in enumerate(evs)]
        out.sort(key=lambda e: (next((i for i, x in enumerate(segs) if x["id"] == e["segment_id"]), 99), e["sentences"][0]))
    for i, e in enumerate(out, 1):
        e["id"] = f"e{i}"
    st = {**planner.get_plan(plan_id)["settings"], "events": out, "events_narration": director.narration_key(segs)}
    db.ex("UPDATE plans SET settings=?, updated_at=? WHERE id=?", (db.jdump(st), db.now(), plan_id))
    store.log(plan_id, "events", {"events": len(out), "segments": len(todo)})
    if progress:
        progress(len(todo), len(todo), "done")
    return planner.get_plan(plan_id)


def of(plan: dict) -> list[dict]:
    return list((plan.get("settings") or {}).get("events") or [])


def current(plan: dict) -> bool:
    """Events exist for this narration (the wording has not changed since)."""
    segs = sorted(plan["segments"], key=lambda x: x["seq"])
    st = plan.get("settings") or {}
    return bool(st.get("events") and st.get("events_narration") == director.narration_key(segs))


def for_segment(plan: dict, seg_id: str) -> list[dict]:
    return [e for e in of(plan) if e["segment_id"] == seg_id]


def world(plan: dict) -> dict:
    """What the events need drawn: the distinct places (near-duplicates merged), the people by name or role, the objects used by two or more events, the years shown."""
    evs = of(plan)
    places: list[dict] = []
    for e in evs:
        hit = next((p for p in places if same_place(p, e)), None)
        if hit:
            hit["count"] += 1
        else:
            places.append({"where": e["where"], "count": 1})
    people: dict[str, int] = {}
    objects: dict[str, int] = {}
    years: dict[str, int] = {}
    for e in evs:
        for w in e["who"]:
            people[w.strip()] = people.get(w.strip(), 0) + 1
        if e["key_object"].strip():
            objects[e["key_object"].strip().lower()] = objects.get(e["key_object"].strip().lower(), 0) + 1
        if e["period"].strip():
            years[e["period"].strip()] = years.get(e["period"].strip(), 0) + 1
    return {"places": places, "people": people, "objects": {k: v for k, v in objects.items() if v >= 2}, "periods": years, "events": len(evs)}


def world_text(plan: dict) -> str:
    w = world(plan)
    return ("THE EVENTS THE CAMERA WILL SEE (planned from the narration; the picture list must hold everything they need):\n"
            f"- {len(w['places'])} distinct places: " + "; ".join(f"{p['where']} ({p['count']})" for p in w["places"]) + "\n"
            f"- people, by how many events they are in: " + "; ".join(f"{k} ({v})" for k, v in sorted(w["people"].items(), key=lambda kv: -kv[1])) + "\n"
            f"- objects that return in two or more events: " + ("; ".join(f"{k} ({v})" for k, v in w["objects"].items()) or "none") + "\n"
            f"- years or periods shown: " + ("; ".join(f"{k} ({v})" for k, v in w["periods"].items()) or "not stated"))


def key(plan: dict) -> str:
    """A short identity of the planned events, so the shot plan and the scenes made from them can tell when the events changed."""
    import hashlib
    return hashlib.sha1("|".join(f"{e['id']}:{e['sentences']}:{e['where']}:{e['doing']}" for e in of(plan)).encode("utf-8")).hexdigest()[:10]
