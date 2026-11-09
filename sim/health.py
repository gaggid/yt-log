"""Story health (docs/PLAN_drama.md part A): numbers and plain verdicts computed by code from the chapters of the current line, no model call. It looks at what the people went through (costs and failed
acts), who is in the story, whether the material of the cast (goals, fears, secrets) and the open threads are used, how chapters end, and what repeats. The drama director (sim/drama.py) reads the same numbers."""
import re
from collections import Counter

from . import state as S, store

WORDS = re.compile(r"[A-Za-z']+")
STOP = set("""about above after again against almost along already also although always among another around because been before behind being below between both brought cannot could
did does doing done down during each either else even ever every first from further gets give goes going gone have having here hers herself himself into itself just keep last least less like made make many might more most much must myself never next none only onto other ours ourselves over own
same several shall should since some still such take than that their theirs them themselves then there these they this those though through thus together toward under until upon very want wants were what when where whether which while whom whose will with within without would your yours yourself
their there's don't didn't isn't wasn't couldn't wouldn't can't won't it's he's she's they're we're i'm you're that's what's""".split())
MENU = re.compile(r"\bto (?:the|his|her|their|your|its) (?:left|right)\b|\bon (?:the|his|her|their) (?:left|right)\b|\bleft or right\b|\b(?:either|one path|the other path|two paths|two ways|a choice between|choose between|or the other)\b", re.I)
REVEAL = re.compile(r"\b(realiz|realis|understood|the truth|it was (?:him|her|them|a|the)|discover|learn(?:s|ed)|revealed|turns? out|was never)", re.I)
DECISION = re.compile(r"\b(must decide|has to choose|have to choose|no choice|now or never|had to decide|decide)\b", re.I)
HOOK = re.compile(r"\b(suddenly|a scream|a shot|a knock|footsteps|too late|missing|silence|then the|behind (?:him|her|them)|the door|a shadow|a voice|went dark|goes dark|stopped|vanished|gone)\b", re.I)
ERRAND = re.compile(r"\b(collect|gather|pick (?:out|up)|select|browse|tidy|fetch|shop|grab a|sort|restock|snack|taste)\b", re.I)
HIGH_IS_BAD = ("danger_above",)
STALE_AFTER = 3
FREE_POINTS = 3                      # a chapter whose only costs are the background drift of a clock and a meter or two counts as free


def words(text: str) -> list[str]:
    return [w.lower().strip("'") for w in WORDS.findall(text or "")]


def keywords(text: str) -> set[str]:
    return {w for w in words(text) if len(w) >= 5 and w not in STOP}


def ending_kind(prose: str) -> str:
    """How a chapter closes: menu (a list of routes), question, reveal, decision, hook or plain."""
    sents = [s for s in re.split(r"(?<=[.!?])\s+", (prose or "").strip()) if s.strip()]
    tail = " ".join(sents[-2:])
    if MENU.search(tail):
        return "menu"
    if tail.strip().endswith("?"):
        return "question"
    if REVEAL.search(tail):
        return "reveal"
    if DECISION.search(tail):
        return "decision"
    if HOOK.search(tail):
        return "hook"
    return "plain"


# ── what a chapter cost the people ────────────────────────────────────────────

def diff_costs(before: dict, after: dict, trackers: list[dict]) -> list[str]:
    """What got worse between two states, in plain words with a weight each (from the trackers, so it holds for any genre)."""
    out: list[tuple[int, str]] = []
    for t in trackers:
        b, a = (before.get("trackers") or {}).get(t["id"]), (after.get("trackers") or {}).get(t["id"])
        if b is None or a is None:
            continue
        k = t["kind"]
        if k == "meter":
            span = max(1.0, float(t["max"]) - float(t["min"]))
            d = float(a) - float(b)
            bad = d > 0 if (t.get("danger_above") is not None and t.get("danger_below") is None) else d < 0
            if bad and abs(d) > 0:
                out.append((max(1, min(3, round(abs(d) / span * 10))), f"{t['name']} {'rose' if d > 0 else 'fell'} by {abs(d):g}"))
        elif k == "clock":
            if int(a) > int(b):
                out.append((int(a) - int(b), f"{t['name']} moved to {a}/{t['max']}"))
        elif k == "relation":
            if a["trust"] < b["trust"]:
                out.append((b["trust"] - a["trust"], f"trust fell in {t['name']}"))
            if a["tension"] > b["tension"]:
                out.append((a["tension"] - b["tension"], f"tension rose in {t['name']}"))
        elif k == "items":
            lost = [n for n in b if n not in a or a[n]["qty"] < b[n]["qty"]]
            worse = [n for n in a if n in b and (a[n].get("props") or {}).get("condition") in ("damaged", "broken", "crude") and (b[n].get("props") or {}).get("condition") not in ("damaged", "broken", "crude")]
            if lost:
                out.append((min(3, len(lost)), f"lost {', '.join(lost[:3])}"))
            if worse:
                out.append((min(2, len(worse)), f"{', '.join(worse[:2])} got damaged"))
    for n, e in (after.get("entities") or {}).items():
        was = (before.get("entities") or {}).get(n, {})
        if was.get("alive", True) and not e.get("alive", True):
            out.append((4, f"{n} died"))
        elif e.get("status") and e.get("status") != was.get("status"):
            out.append((1, f"{n}: {e['status']}"))
    return [f"{w}|{txt}" for w, txt in out]


def chapter_numbers(c: dict, trackers: list[dict]) -> dict:
    rolls = c.get("rolls") or []
    tiers = Counter(r.get("tier") for r in rolls)
    costs = diff_costs(c.get("state_before") or {}, c.get("state_after") or {}, trackers)
    points = sum(int(x.split("|")[0]) for x in costs) + 2 * tiers.get("fail", 0) + 3 * tiers.get("disaster", 0) + tiers.get("partial", 0)
    pressure = len(S.pressure(c.get("state_after") or {"trackers": {}}, trackers)) if c.get("state_after") else 0
    after = c.get("state_after") or {"trackers": {}}
    for t in trackers:                                                      # a meter sitting at its bad end is pressure even when it did not move this chapter
        v = (after.get("trackers") or {}).get(t["id"])
        if t["kind"] == "meter" and v is not None:
            span = max(1.0, float(t["max"]) - float(t["min"]))
            high_bad = t.get("danger_above") is not None and t.get("danger_below") is None
            if ((float(t["max"]) - float(v)) if high_bad else (float(v) - float(t["min"]))) / span <= 0.1:
                pressure += 1
    return {"idx": c["idx"], "title": c.get("title", ""), "tiers": dict(tiers), "costs": [x.split("|", 1)[1] for x in costs], "points": points,
            "intensity": max(0, min(10, points + pressure)), "free": points <= FREE_POINTS and not (tiers.get("fail") or tiers.get("disaster") or tiers.get("partial")), "ending": ending_kind(c.get("prose", "")), "words": len((c.get("prose") or "").split())}


# ── the whole story ───────────────────────────────────────────────────────────

def report(pid: str, path: list[dict] | None = None) -> dict:
    path = [c for c in (path if path is not None else store.path(pid)) if c.get("status") == "done"]
    trackers = store.trackers(pid)
    ents = store.entities(pid)
    chars = [e for e in ents if e["kind"] == "character"]
    names = {e["name"] for e in ents}
    n = len(path)
    chs = [chapter_numbers(c, trackers) for c in path]
    out: dict = {"chapters": n, "per_chapter": chs}
    if not n:
        out["verdicts"] = []
        return out
    tiers = Counter()
    for c in chs:
        tiers.update(c["tiers"])
    rolls = sum(tiers.values())
    streak = 0
    for c in reversed(chs):
        if not c["free"]:
            break
        streak += 1
    out["dice"] = {"rolls": rolls, "tiers": dict(tiers), "free_streak": streak}
    out["intensity"] = [c["intensity"] for c in chs]
    out["endings"] = [c["ending"] for c in chs]
    # who is in the story
    last_state = path[-1].get("state_after") or {}
    alive = [e for e in chars if (last_state.get("entities") or {}).get(e["name"], {}).get("alive", True)]
    spot = {}
    for e in alive:
        ment = [len(re.findall(re.escape(e["name"]), c.get("prose") or "")) for c in path]
        foc = [i for i, c in enumerate(path) if e["name"] in (c.get("focus") or [])]
        seen = [i for i, m in enumerate(ment) if m >= 2 or i in foc]
        spot[e["name"]] = {"mentions": ment, "last_seen": (seen[-1] + 1) if seen else 0, "away": n - (seen[-1] + 1 if seen else 0), "share": 0.0}
    total = sum(sum(s["mentions"]) for s in spot.values()) or 1
    for s in spot.values():
        s["share"] = round(sum(s["mentions"]) / total, 2)
    out["spotlight"] = spot
    # the cast's own material
    mat = []
    for e in alive:
        for key in ("goal", "fear", "secret"):
            kw = keywords(e.get(key, ""))
            if not kw:
                continue
            need = min(2, len(kw))
            hit = [i for i, c in enumerate(path) if len(kw & keywords(c.get("prose", ""))) >= need]
            mat.append({"who": e["name"], "kind": key, "text": e.get(key, ""), "last": (hit[-1] + 1) if hit else 0, "age": n - (hit[-1] + 1 if hit else 0)})
    out["material"] = mat
    # threads
    ids = {c["id"]: i + 1 for i, c in enumerate(path)}
    th = [{"text": t["text"], "age": n - ids[t["opened_in"]]} for t in store.threads(pid) if t["opened_in"] in ids and not (t["closed_in"] and t["closed_in"] in ids)]
    out["threads"] = th
    # repetition
    allw = [w for c in path for w in words(c.get("prose", ""))]
    cnt = Counter(w for w in allw if len(w) >= 5 and w not in STOP and w.title() not in names and w not in {x.lower() for x in names})
    out["repeated"] = [{"word": w, "count": k, "per_1000": round(k / max(1, len(allw)) * 1000, 1)} for w, k in cnt.most_common(6) if k >= 4 and k / max(1, len(allw)) > 0.006]
    # options
    opts = {"duplicates": 0, "errands": 0, "per_person": Counter()}
    for c in path:
        os_ = c.get("options") or []
        for i, o in enumerate(os_):
            opts["per_person"][o.get("who", "")] += 1
            if ERRAND.search(o.get("label", "")):
                opts["errands"] += 1
            for p in os_[i + 1:]:
                wa, wb = keywords(o.get("label", "")), keywords(p.get("label", ""))
                if wa and wb and len(wa & wb) / min(len(wa), len(wb)) > 0.6:
                    opts["duplicates"] += 1
    opts["per_person"] = dict(opts["per_person"])
    out["options"] = opts
    # pace: a countdown clock against the number of chapters
    clocks = []
    for t in trackers:
        if t["kind"] == "clock":
            v = int((last_state.get("trackers") or {}).get(t["id"], 0))
            clocks.append({"name": t["name"], "at": v, "max": int(t["max"]), "per_chapter": round(v / n, 2), "full_in": (round((int(t["max"]) - v) / (v / n)) if v else None)})
    out["clocks"] = clocks
    out["verdicts"] = verdicts(out, chs, alive, n)
    return out


def verdicts(r: dict, chs: list[dict], alive: list[dict], n: int) -> list[dict]:
    v: list[dict] = []

    def add(level, text):
        v.append({"level": level, "text": text})

    d = r["dice"]
    if n >= 2 and d["free_streak"] >= 2:
        add("bad", f"{d['free_streak']} chapters in a row with no failed or partial roll and no cost: the story is flat.")
    if d["rolls"] >= 5 and not d["tiers"].get("fail") and not d["tiers"].get("disaster") and not d["tiers"].get("partial"):
        add("bad", f"All {d['rolls']} rolls succeeded: nothing the people tried has gone wrong yet.")
    inten = r["intensity"]
    if n >= 3 and max(inten[-3:]) < 4 and inten[-1] <= inten[-3]:
        add("warn", f"Tension is not rising (last chapters: {', '.join(str(x) for x in inten[-3:])} out of 10).")
    ends = r["endings"]
    if n >= 2 and ends[-1] == "menu" and ends[-2] == "menu":
        add("bad", "The last two chapters end on a menu of routes, not on a hook, a decision or a reveal.")
    elif ends[-1] == "menu":
        add("warn", "The last chapter ends on a menu of routes.")
    elif n >= 3 and len(set(ends[-3:])) == 1 and ends[-1] == "plain":
        add("warn", "The last three chapters close the same plain way.")
    for name, s in r["spotlight"].items():
        if n >= 3 and s["away"] >= STALE_AFTER:
            add("warn", f"{name} has not been in the story for {s['away']} chapters.")
    top = max(r["spotlight"].items(), key=lambda kv: kv[1]["share"], default=None)
    if top and len(r["spotlight"]) >= 3 and top[1]["share"] > 0.55 and n >= 2:
        add("warn", f"{top[0]} carries the story ({round(top[1]['share'] * 100)} per cent of the names).")
    stale = [m for m in r["material"] if m["age"] >= STALE_AFTER and n >= STALE_AFTER]
    if stale:
        m = stale[0]
        add("warn", f"{m['who']}'s {m['kind']} has not surfaced for {m['age']} chapters" + (f" (and {len(stale) - 1} more things of the cast)" if len(stale) > 1 else "") + ".")
    old = [t for t in r["threads"] if t["age"] >= 4]
    if old:
        add("warn", f"{len(old)} open thread(s) are 4 or more chapters old, for example: {old[0]['text']}")
    for w in r["repeated"][:2]:
        add("warn", f"The word '{w['word']}' appears {w['count']} times ({w['per_1000']} per 1000 words).")
    o = r["options"]
    if o["duplicates"] >= 2:
        add("warn", f"{o['duplicates']} pairs of options offered the same move.")
    if n >= 2 and o["errands"] >= n:
        add("warn", f"{o['errands']} of the options were small errands (collecting, picking, sorting).")
    for c in r["clocks"]:
        if c["full_in"] is not None and c["full_in"] > 30:
            add("warn", f"'{c['name']}' moves {c['per_chapter']} a chapter: it would take about {c['full_in']} more chapters to fill.")
    if not v:
        add("ok", "Nothing stands out: the story has costs, movement and variety so far.")
    return v
