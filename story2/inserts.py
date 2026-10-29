"""World inserts (docs/TASKS_quality_overhaul.md task 3.12): short cutaways of ordinary life in the story's region and period (a tea stall at dawn, a shutter going up, laundry on a
terrace, rain on a tin roof) placed between the scenes of the plot, so the film shows a big, specific world and not only the few rooms where the story happens.

An insert takes the last sentence of a long scene, so the timeline stays what the narration says: the host scene keeps the sentences before it, the insert plays under the last
one. Each picture of the pool is used once per film. Inserts are scenes like any other (they get a prompt, a picture and a camera move) with `data.insert` set; `remove` gives
the sentence back to the host."""
import uuid

from story import db

from . import planner, region, safety, storyboard, store
from .scene_schemas import Compose, SceneOut

PER_MINUTE = 1.5                  # 9 inserts in a 6-minute film
MIN_HOST_S = 6.0                  # a scene shorter than this is not cut into
MAX_INSERT_S = 6.0                # the sentence the insert takes must not be longer than this
MIN_INSERT_S = 1.2
LEAD_IN_S = 15.0                  # no insert in the opening seconds
TAIL_S = 25.0                     # nor in the closing ones
_DISTANCES = ("wide", "medium", "wide", "close")
_ANGLES = ("eye level", "low", "eye level", "high")
_MOVES = ("slow push in", "slow pan right", "slow pull back", "slow pan left")


def is_insert(scene: dict) -> bool:
    return bool(scene["data"].get("insert"))


def existing(plan_id: str) -> list[dict]:
    return [s for s in storyboard.get_scenes(plan_id) if is_insert(s)]


def remove(plan_id: str) -> int:
    """Delete the unlocked inserts and give each one's sentence back to the scene it was cut from."""
    n = 0
    with db.tx() as c:
        for ins in existing(plan_id):
            if ins["locked"]:
                continue
            host = db.one("SELECT id, s_to FROM scenes WHERE id=?", (ins["data"]["insert"].get("host", ""),))
            if host and host["s_to"] == ins["s_from"] - 1:
                c.execute("UPDATE scenes SET s_to=?, rev=rev+1, updated_at=? WHERE id=?", (ins["s_to"], db.now(), host["id"]))
            c.execute("DELETE FROM scenes WHERE id=?", (ins["id"],))
            n += 1
    if n:
        storyboard.retime(plan_id)
    return n


def _hosts(plan: dict, scenes: list[dict], total_s: float) -> list[dict]:
    """The scenes an insert can be cut from, in film order, each with the seconds of its last sentence."""
    wpm = plan["settings"].get("wpm", planner.WPM)
    real = storyboard.real_audio(plan["id"])
    segs = {s["id"]: s for s in plan["segments"]}
    out = []
    for sc in scenes:
        seg = segs.get(sc["segment_id"])
        d = sc["data"]
        if not seg or sc["locked"] or is_insert(sc) or sc["s_to"] - sc["s_from"] < 1 or sc["duration_s"] < MIN_HOST_S:
            continue
        if sc["start_s"] < LEAD_IN_S or sc["end_s"] > total_s - TAIL_S or d.get("breath"):
            continue
        sd = storyboard.sentence_seconds(seg, wpm, real.get(seg["id"]))
        last = sd[sc["s_to"] - 1] if sc["s_to"] - 1 < len(sd) else 0
        text = seg["sentences"][sc["s_to"] - 1]["text"] if sc["s_to"] - 1 < len(seg["sentences"]) else ""
        if not (MIN_INSERT_S <= last <= MAX_INSERT_S) or safety.grave(text) or safety.loss(text):
            continue                                                       # never a cheerful cutaway over a death or a loss
        out.append({"scene": sc, "last_s": last, "boundary": sc["s_to"] >= len(seg["sentences"])})
    return out


def pick(hosts: list[dict], count: int, total_s: float) -> list[dict]:
    """`count` hosts spread evenly over the film; a scene that ends its segment (a beat boundary) is preferred within its stretch."""
    if not hosts or count <= 0:
        return []
    gap = total_s / (count + 1) * 0.6
    chosen: list[dict] = []
    for k in range(1, count + 1):
        target = total_s * k / (count + 1)
        near = [h for h in hosts if h not in chosen and abs(h["scene"]["start_s"] - target) <= total_s / (count + 1) / 2 + gap / 2]
        near = [h for h in near if all(abs(h["scene"]["start_s"] - c["scene"]["start_s"]) >= gap for c in chosen)]
        if not near:
            continue
        near.sort(key=lambda h: (not h["boundary"], abs(h["scene"]["start_s"] - target)))
        chosen.append(near[0])
    return sorted(chosen, key=lambda h: h["scene"]["start_s"])


def _scene(ins: dict, k: int, host_data: dict, plan: dict, label: str) -> dict:
    sc = SceneOut(purpose=f"a moment of ordinary life in {label}", new_information=f"the world of the story: {ins['subject'].lower()}", takeaway="the story happens in a real, busy place",
                  emotional_effect="the world goes on", visual_type="atmospheric", subject=ins["subject"], action=ins["action"], location=ins["location"],
                  period=str((host_data.get("setting") or {}).get("period") or ""), props=list(ins.get("props", [])),
                  composition=Compose(distance=_DISTANCES[k % 4], camera_angle=_ANGLES[k % 4], position="centre", framing="the subject placed on a third, the rest of the frame full of the place"),
                  lighting=ins.get("light", ""), atmosphere="lived-in and specific", motion_intent=_MOVES[k % 4], event=f"ins-{k + 1}")
    data, _ = storyboard.build_scene(sc, [], plan, [])
    data["insert"] = {"id": ins["id"], "region": ins.get("region", ""), "host": ""}
    data["voice_tag"] = ""
    return data


def add(plan_id: str, count: int | None = None) -> int:
    """Cut the inserts into the storyboard (replacing earlier ones). Returns how many were added."""
    plan = planner.get_plan(plan_id)
    st = plan["settings"]
    if (st.get("inserts") or {}).get("enabled") is False:
        return 0
    remove(plan_id)
    scenes = storyboard.get_scenes(plan_id)
    total = max((s["end_s"] for s in scenes), default=0.0)
    count = count if count is not None else max(0, round((st.get("inserts") or {}).get("per_minute", PER_MINUTE) * total / 60))
    pool = region.pool(plan)
    chosen = pick(_hosts(plan, scenes, total), min(count, len(pool)), total)
    if not chosen:
        return 0
    added = 0
    with db.tx() as c:
        for k, h in enumerate(chosen):
            host = h["scene"]
            ins = pool[k]
            data = _scene(ins, k, host["data"], plan, region.table()[ins["region"]]["label"])
            data["insert"]["host"] = host["id"]
            c.execute("UPDATE scenes SET s_to=?, rev=rev+1, updated_at=? WHERE id=?", (host["s_to"] - 1, db.now(), host["id"]))
            c.execute("INSERT INTO scenes(id,plan_id,seq,segment_id,s_from,s_to,data,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                      ("sc-" + uuid.uuid4().hex[:8], plan_id, host["seq"] + 0.00003, host["segment_id"], host["s_to"], host["s_to"], db.jdump(data), db.now()))
            added += 1
    if added:
        db.ex("UPDATE plans SET settings=?, updated_at=? WHERE id=?", (db.jdump({**planner.get_plan(plan_id)["settings"], "inserts": {**(st.get("inserts") or {}), "used": [i["id"] for i in pool[:added]]}}), db.now(), plan_id))
        storyboard.retime(plan_id)
        store.log(plan_id, "inserts", {"added": added, "regions": region.detect(plan)})
    return added
