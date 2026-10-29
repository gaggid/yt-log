"""Model judges and the persona panel (docs/TASKS_quality_overhaul.md tasks 8.1 and 8.7). There is no human review, so a judge reads what was made against a fixed rubric and gives
scores from 1 to 5 with a reason for each; the persona panel reads the film as eight kinds of Indian viewer and says where each would leave.

Both are weak stand-ins for real viewers (a small model judging a small model), so they are used to find the worst defects and to send a part back, never to approve a film on their
word alone. A judge runs at low temperature, and the worse of two runs is the one that counts. Results are stored in `plan.settings.judges` and `plan.settings.panel`."""
import json

from story import db, llm, settings as settings_mod
from story.schemas import Str

from . import planner
from .schemas import M

RUBRICS = {
    "narration": [("concrete", "every part starts inside a concrete moment and gives a new fact, person, object or number in nearly every sentence"),
                  ("natural", "it sounds like a person telling a story in spoken Hinglish, not a translation or a report"),
                  ("tone", "the tone fits the facts: calm and exact over a death or a loss, never glamorising an offender"),
                  ("payoff", "the opening question is answered before the last minute and the ending closes it"),
                  ("variety", "sentences differ in length and shape; no phrase is repeated")],
    "storyboard": [("variety", "the scenes show many different places and people, not the same face or room again and again"),
                   ("moment", "each scene shows one specific filmable moment of the narration, not an idea or a symbol"),
                   ("world", "the world feels big and real: ordinary life around the plot"),
                   ("accuracy", "objects and places fit the period and the region of the story")],
    "packaging": [("curiosity", "the title makes a viewer want the answer without lying about it"),
                  ("specific", "the title names something specific, not a vague promise"),
                  ("honest", "everything the title claims is in the film")],
    "thumbnail": [("focus", "one clear focal point and one face"), ("emotion", "the emotion is readable at a glance"), ("legible", "the headline is readable at the size of a suggested video")],
}
PERSONAS = {
    "P1": ("metro_young", "a 22-year-old in a metro city, watches on a phone in short breaks, comfortable with English words, leaves after ten seconds if nothing happens"),
    "P2": ("hindi_belt_family", "a 40-year-old in a small Hindi-belt town, watches on a shared phone with his family in the evening, wants plain Hindi and a story he can retell"),
    "P3": ("senior", "a 62-year-old retired teacher, watches slowly, dislikes English words and fast cuts, cares that facts are right"),
    "P4": ("working_woman", "a 34-year-old working woman, watches at night, sensitive to how women and victims are shown, wants something she can use"),
    "P5": ("regional", "a 29-year-old from Punjab or Gujarat or Bengal, notices when clothes, streets, scripts and food are wrong for her state"),
    "P6": ("student", "a 19-year-old student preparing for exams, wants to learn something, leaves when the video repeats itself"),
    "P7": ("cautious", "a 45-year-old who has been cheated once, wants to know what to do next and distrusts exaggeration"),
    "P8": ("sensitive", "a 38-year-old who watches for any community, caste, religion or gender stereotype and for cruelty shown for effect"),
}


class Score(M):
    key: Str = ""
    score: float = 3
    reason: Str = ""


class JudgeOut(M):
    scores: list[Score] = []


def prompt(name: str) -> str:
    rows = "\n".join(f"- {k}: {d}" for k, d in RUBRICS[name])
    return (f"[TASK:p2_rate_{name}]\nYou are a strict reviewer of a {name}. Score each point from 1 (poor) to 5 (excellent); 3 is merely acceptable, and 5 is rare. Give a short concrete reason for each score.\n{rows}\n"
            'Return ONLY: {"scores": [{"key": "", "score": 3, "reason": ""}]}')


async def judge(plan_id: str, name: str, subject: str, backend, s: dict | None = None, runs: int = 2) -> dict:
    """Score `subject` (text) with the rubric of `name`, `runs` times, keeping the worse score of each point. Stored in plan.settings.judges[name]."""
    s = s or settings_mod.get()
    keys = [k for k, _ in RUBRICS[name]]
    worst: dict[str, Score] = {}
    for _ in range(max(1, runs)):
        try:
            res = (await llm.JsonCaller(backend, s).call(prompt(name), subject[:12000], JudgeOut)).value
        except llm.LLMError:
            continue
        for sc in res.scores:
            if sc.key in keys and (sc.key not in worst or sc.score < worst[sc.key].score):
                worst[sc.key] = sc
    scores = {k: {"score": max(1.0, min(5.0, worst[k].score)), "reason": worst[k].reason} for k in keys if k in worst}
    out = {"scores": scores, "total": round(sum(v["score"] for v in scores.values()) / len(scores), 2) if scores else None, "weakest": min(scores, key=lambda k: scores[k]["score"]) if scores else ""}
    plan = planner.get_plan(plan_id)
    st = plan["settings"]
    db.ex("UPDATE plans SET settings=? WHERE id=?", (db.jdump({**st, "judges": {**(st.get("judges") or {}), name: out}}), plan_id))
    return out


def narration_text(plan: dict) -> str:
    return "\n".join(f"[{i}] {s['plain']}" for i, s in enumerate(plan["segments"], 1))


def timeline(plan: dict) -> str:
    t, rows = 0.0, []
    for seg in sorted(plan["segments"], key=lambda x: x["seq"]):
        for s in seg["sentences"]:
            rows.append(f"{int(t // 60)}:{int(t % 60):02d} {s['text']}")
            t += max(1.5, len(s["text"].split()) / 2.4)
    return "\n".join(rows)


class Answer(M):
    click: Str = ""
    leave_at: Str = ""
    leave_why: Str = ""
    not_understood: Str = ""
    unfair: Str = ""
    share: Str = ""
    would_click: bool = True
    would_leave: bool = False


class PanelOut(M):
    answer: Answer = Answer()


def persona_prompt(code: str) -> str:
    name, who = PERSONAS[code]
    return (f"[TASK:p2_judge_persona]\nYou are {who}. You are shown the title, the narration with timestamps and the list of scenes of a Hindi YouTube video. React as that person would, honestly and briefly.\n"
            'Return ONLY: {"answer": {"would_click": true, "click": "why or why not", "would_leave": false, "leave_at": "m:ss or empty", "leave_why": "", "not_understood": "", "unfair": "anything that felt untrue or unfair '
            'to your community, region or gender, or empty", "share": "would you share it, with whom"}}')


async def panel(plan_id: str, backend, s: dict | None = None, personas: list[str] | None = None, runs: int = 2) -> dict:
    """Every persona reads the film twice; the worse reaction counts (would leave beats would not). Summarised as where viewers would leave and what felt unfair."""
    s = s or settings_mod.get()
    plan = planner.get_plan(plan_id)
    scenes = "\n".join(f"- {sc['data'].get('subject', '')} ({(sc['data'].get('setting') or {}).get('location', '')})" for sc in plan["scenes"][:60])
    body = f"TITLE: {plan['settings'].get('video_title', '')}\n\nNARRATION WITH TIMESTAMPS:\n{timeline(plan)}\n\nSCENES:\n{scenes}"[:14000]
    results = {}
    for code in personas or list(PERSONAS):
        worst = None
        for _ in range(max(1, runs)):
            try:
                a = (await llm.JsonCaller(backend, s).call(persona_prompt(code), body, PanelOut)).value.answer
            except llm.LLMError:
                continue
            if worst is None or (a.would_leave, not a.would_click) > (worst.would_leave, not worst.would_click):
                worst = a
        if worst is not None:
            results[code] = {**worst.model_dump(), "persona": PERSONAS[code][0]}
    leave = sorted([(r["leave_at"], c) for c, r in results.items() if r["would_leave"] and r["leave_at"]])
    out = {"personas": results, "would_click": sum(1 for r in results.values() if r["would_click"]), "of": len(results), "leave_points": [{"at": a, "persona": c} for a, c in leave],
           "unfair": [{"persona": c, "text": r["unfair"]} for c, r in results.items() if r["unfair"].strip()]}
    st = planner.get_plan(plan_id)["settings"]
    db.ex("UPDATE plans SET settings=? WHERE id=?", (db.jdump({**st, "panel": out}), plan_id))
    return out
