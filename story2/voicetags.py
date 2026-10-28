"""AI voice direction for Maya: one model call per narration segment decides how the narrator sounds, sentence by sentence, from the whole video's arc,
the beat's suspense plan and what the storyboard put on screen. The result is written onto each sentence as `tag` and reaches the voice as an inline
Maya tag (`story2/maya.py`). Tags are outside the content hash: this never un-approves a plan, and the editor can change any of them afterwards."""
from story import llm, settings as settings_mod

from . import maya, planner, prompts as P, storyboard, store
from .schemas import M, Str

MAX_CHANGES = 2                      # style changes inside one segment
MAX_SHARE = 0.6                      # of the sentences carrying a style tag at all


class TagOut(M):
    n: int = 0
    tag: Str = "neutral"
    why: Str = ""


class TagsOut(M):
    sentences: list[TagOut]


def _arc(plan: dict) -> str:
    bp = plan["blueprint"] or {}
    rows = [f"{lbl}: {bp[k]}" for lbl, k in (("Viewer promise", "viewer_promise"), ("Central question", "central_question"), ("Cold open", "cold_open"), ("Stakes", "stakes"),
                                            ("Wrong answer first", "false_answer"), ("Dark moment", "dark_moment"), ("Turning point", "turning_point"), ("Payoff", "payoff"),
                                            ("Ending", "ending")) if bp.get(k)]
    return "\n".join(rows) or "none"


def _beat(plan: dict, beat_id: str) -> str:
    b = next((x for x in (plan["blueprint"] or {}).get("beats", []) if x["id"] == beat_id), {})
    return "\n".join(f"{lbl}: {b[k]}" for lbl, k in (("Beat", "name"), ("Purpose", "purpose"), ("Feeling", "feeling"), ("Reveals", "reveal"), ("Ends on", "ends_on")) if b.get(k)) or "none"


def problems(tags: list[str]) -> list[str]:
    """What is wrong with the tags chosen for one segment (sent back to the model; the last attempt is accepted as it is)."""
    styled = [t for t in tags if t in maya.STYLE_TAGS]
    changes = sum(1 for a, b in zip(["neutral", *tags], tags) if b != a and b in maya.STYLE_TAGS)
    out = []
    if changes > MAX_CHANGES:
        out.append(f"the voice changes {changes} times; change at most {MAX_CHANGES} times, only at real turns")
    if tags and len(styled) > max(2, round(MAX_SHARE * len(tags))):
        out.append("most sentences carry a style tag; keep plain 'neutral' for explanation and evidence")
    if sum(1 for t in tags if t in maya.SOUND_TAGS) > 1:
        out.append("use at most one sound tag (sighs, laughs, clears throat) in a segment")
    return out


def _tags_for(out: TagsOut, n: int) -> list[str]:
    by_n = {x.n: maya.norm_tag(x.tag) or "neutral" for x in out.sentences if 1 <= x.n <= n}
    if not by_n and len(out.sentences) == n:                               # the model left the numbers out: take them in order
        by_n = {i: maya.norm_tag(x.tag) or "neutral" for i, x in enumerate(out.sentences, 1)}
    return [by_n.get(i, "neutral") for i in range(1, n + 1)]


async def suggest(plan_id: str, backend, s: dict | None = None, segment_ids: list[str] | None = None, progress=None) -> dict:
    """Choose a voice tag for every sentence of the segments (all of them by default). Locked segments are left alone."""
    s = s or settings_mod.get()
    plan = planner.get_plan(plan_id)
    if not plan["segments"]:
        raise planner.PlanError("write the narration first")
    segs = sorted(plan["segments"], key=lambda x: (x["seq"], x["id"]))
    todo = [x for x in segs if (not segment_ids or x["id"] in segment_ids) and not x["locked"]]
    scenes = storyboard.get_scenes(plan_id)
    arc = _arc(plan)
    caller = llm.JsonCaller(backend, s)
    prev_tag, done = "neutral", 0
    for i, seg in enumerate(todo):
        if progress:
            progress(i, len(todo), f"voice direction {i + 1} of {len(todo)}")
        n = len(seg["sentences"])
        if not n:
            continue
        pos = segs.index(seg) + 1
        lines = "\n".join(f"{k}. {x['text']}" for k, x in enumerate(seg["sentences"], 1))
        shown = "\n".join(f"- sentences {sc['s_from']}-{sc['s_to']}: {sc['data']['narrative'].get('emotional_effect') or '-'}"
                          f" (storyboard suggests: {sc['data'].get('voice_tag') or 'none'})" for sc in scenes if sc["segment_id"] == seg["id"]) or "- no scenes yet"
        where = " (the opening of the video)" if pos == 1 else " (the ending of the video)" if pos == len(segs) else ""
        user = (f"THE WHOLE VIDEO:\n{arc}\n\nTHIS BEAT:\n{_beat(plan, seg['beat'])}\n\n"
                f"WHERE THIS SEGMENT SITS: part {pos} of {len(segs)}{where}\n"
                f"HOW THE PREVIOUS SEGMENT ENDED: {prev_tag}\n\nWHAT IS ON SCREEN (scene feelings):\n{shown}\n\n"
                f"THE SEGMENT, {n} sentence(s):\n{lines}\n\nChoose the tag for each sentence now.")

        def check(out: TagsOut, n=n) -> None:
            if caller.last_attempt:
                return
            if bad := problems(_tags_for(out, n)):
                raise ValueError("The voice direction is not right yet:\n- " + "\n- ".join(bad))

        res = await caller.call(P.VOICE_TAGS, user, TagsOut, check)
        tags = _tags_for(res.value, n)
        planner.set_sentence_tags(seg["id"], tags)
        prev_tag = next((t for t in reversed(tags) if t != "neutral"), "neutral")
        done += 1
    if progress:
        progress(len(todo), len(todo), "done")
    store.log(plan_id, "voicetags", {"segments": done})
    return {"segments": done}
