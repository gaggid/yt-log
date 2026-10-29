"""YouTube titles (docs/TASKS_quality_overhaul.md tasks 6.1 and 6.7). The model writes nine options in three registers (Hinglish in Latin letters, Hindi in Devanagari, English); code
checks length, the claim check against the film, the number and name limits and the community-term list, and ranks what is left for the audience profile of the plan. The best
becomes `plan.settings.video_title` unless the editor already set one by hand."""
import re

from story import db, llm, settings as settings_mod
from story.schemas import Str

from . import claimcheck, leak, material, planner, prompts as P, intake, store
from .schemas import M

MAX_LEN = 60
REGISTERS = ("hinglish", "hindi", "english")
PROFILE_ORDER = {"metro_hinglish": ("hinglish", "english", "hindi"), "hindi_first": ("hindi", "hinglish", "english"), "senior_friendly": ("hindi", "hinglish", "english")}


class Option(M):
    title: Str
    kind: Str = "hinglish"                      # the register: hinglish (Latin letters), hindi (Devanagari) or english
    why: Str = ""


class TitlesOut(M):
    options: list[Option]


def indian_style(text: str) -> str:
    """Rupee amounts as Indians write them: ₹64 crore, ₹5 lakh."""
    return re.sub(r"(?<![\w₹])(\d[\d,.]*)\s*(crore|lakh)\b", lambda m: f"₹{m.group(1)} {m.group(2)}", text, flags=re.I)


def register_of(title: str) -> str:
    if re.search(r"[ऀ-ॿ]", title):
        return "hindi"
    return "hinglish" if re.search(r"\b(kya|kyun|kaise|kaun|aakhir|ek|hai|nahi|gaya|tha|ka|ki)\b", title, re.I) else "english"


def score(title: str, plan: dict, order: tuple) -> float:
    """Higher is better: a curiosity gap (a question or an unfinished claim), one specific number, a length that fits the tile, and the register the audience prefers."""
    s = 0.0
    s += 2 if re.search(r"\?|क्यों|कैसे|आखिर|kyun|kaise|aakhir|why|how", title, re.I) else 0
    s += 1 if re.search(r"\d", title) else 0
    s += 1 if 28 <= len(title) <= 55 else 0
    s -= 0.5 * max(0, len(re.findall(r"\d[\d,.]*", title)) - 1)
    s += {order[0]: 1.5, order[1]: 0.7}.get(register_of(title), 0)
    return s


def problems(opt: Option, plan: dict, prof) -> list[str]:
    t = opt.title.strip()
    out = []
    if len(t) > MAX_LEN:
        out.append(f"longer than {MAX_LEN} characters ({len(t)})")
    out += claimcheck.check(t, plan)
    if prof is not None and leak.check(t, prof, scene=True):
        out.append("carries wording from the source")
    if re.search(r"[!]{2,}|SHOCKING|YOU WON'T BELIEVE", t, re.I):
        out.append("clickbait wording")
    return out


async def make(plan_id: str, backend, s: dict | None = None) -> dict:
    s = s or settings_mod.get()
    plan = planner.get_plan(plan_id)
    bp = plan.get("blueprint") or {}
    if not plan["segments"]:
        raise planner.PlanError("write the narration first")
    pack = material.pack(plan) if material.has(plan) else {"items": []}
    best = sorted(pack["items"], key=lambda i: -i.get("weight", 0))[:4]
    user = (f"CENTRAL QUESTION: {bp.get('central_question', '')}\nCOLD OPEN: {bp.get('cold_open', '')}\nSTAKES: {bp.get('stakes', '')}\nFOR THE INDIAN VIEWER: {bp.get('indian_hook', '')}\n"
            "THE MOST SURPRISING DETAILS:\n" + "\n".join(f"- {i['detail']}" for i in best) + f"\n\nOPENING LINE OF THE FILM: {plan['segments'][0]['sentences'][0]['text'] if plan['segments'][0]['sentences'] else ''}\n\nWrite the titles now.")
    story = planner._story_for(plan)
    prof = leak.profile(story["evidence"]["project_id"], story["evidence"]["passages"])
    res = await llm.JsonCaller(backend, s).call(P.TITLES, user, TitlesOut)
    order = PROFILE_ORDER.get(((plan["settings"].get("audience") or {}).get("profile")) or "metro_hinglish", PROFILE_ORDER["metro_hinglish"])
    rows, kept = [], []
    for o in res.value.options:
        o.title = indian_style(o.title.strip())
        bad = problems(o, plan, prof)
        row = {"title": o.title, "register": o.kind if o.kind in REGISTERS else register_of(o.title), "why": o.why, "problems": bad, "score": score(o.title, plan, order)}
        rows.append(row)
        if not bad:
            kept.append(row)
    kept.sort(key=lambda r: -r["score"])
    st = plan["settings"]
    chosen = kept[0]["title"] if kept else ""
    new = {**st, "titles": {"options": rows, "chosen": chosen}}
    if chosen and (not st.get("video_title") or st.get("video_title_auto")):
        new["video_title"], new["video_title_auto"] = chosen, True                    # a title typed by the editor is never replaced
    db.ex("UPDATE plans SET settings=?, updated_at=? WHERE id=?", (db.jdump(new), db.now(), plan_id))
    store.log(plan_id, "titles", {"options": len(rows), "kept": len(kept), "chosen": chosen})
    return {"options": rows, "chosen": chosen}
