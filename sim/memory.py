"""What each model call sees (docs/PLAN_simulation.md section 9). A bounded packet built from the chosen line of the story only: the world, the rules, the state, the people, the story so far,
the last chapter's ending, matched fact cards and the open threads. Over budget, the lowest-priority parts are dropped first; no part is ever cut in the middle."""
from story import settings as settings_mod
from story.tokens import Budget

from . import content, state as S, store

PACKET_TOKENS = 6500
SUMMARY_KEEP = 8                    # chapter summaries kept word for word after the story-so-far
ROLLUP_AT = 12                      # roll up when this many summaries follow the last roll-up ...
ROLLUP_TAKE = 8                     # ... and merge the oldest of them
MAX_FACTS = 8
MAX_THREADS = 8


def fired_ids(path: list[dict]) -> set[str]:
    return {d for c in path for d in c.get("fired", [])}


def pending_directives(pid: str, path: list[dict]) -> list[dict]:
    """Instructions not cancelled and not yet fired on THIS line of the story (firing is stored on chapters, so a branch never inherits another branch's firing)."""
    done = fired_ids(path)
    return [d for d in store.directives(pid) if d["status"] != "cancelled" and d["id"] not in done]


def open_threads(pid: str, path: list[dict]) -> list[dict]:
    ids = {c["id"] for c in path}
    out = []
    for t in store.threads(pid):
        if t["opened_in"] in ids and not (t["closed_in"] and t["closed_in"] in ids):
            out.append(t)
    return out


def path_facts(pid: str, path: list[dict]) -> list[dict]:
    ids = {c["id"] for c in path}
    return [f for f in store.facts(pid) if f["chapter_id"] in ids]


def story_so_far(path: list[dict]) -> tuple[str, list[dict]]:
    """(the latest roll-up on the line, the chapters after it)."""
    roll_at = -1
    text = ""
    for i, c in enumerate(path):
        if c["flags"].get("rollup"):
            roll_at, text = i, c["flags"]["rollup"]
    return text, path[roll_at + 1:]


def due_for_rollup(path: list[dict]) -> tuple[str, list[dict]] | None:
    text, after = story_so_far(path)
    done = [c for c in after if c["status"] == "done"]
    if len(done) >= ROLLUP_AT:
        return text, done[:ROLLUP_TAKE]
    return None


def rules_text(pid: str) -> tuple[str, dict[str, str]]:
    """The enabled rules numbered R1.. (and the map back to their ids)."""
    rows = store.guidelines(pid, enabled_only=True)
    labels = {f"R{i}": g["id"] for i, g in enumerate(rows, 1)}
    lines = [f"R{i} [{g['grp']}] {g['text']}" for i, g in enumerate(rows, 1)]
    return "\n".join(lines) or "(no rules)", labels


def world_text(world: dict) -> str:
    keys = (("goal", "THE STORY IS ABOUT"), ("place", "Place"), ("period", "Period"), ("tone", "Tone"), ("pacing", "Pacing"), ("exists", "What exists here"), ("craft", "Making and finding here"))
    return "\n".join(f"{label}: {world[k]}" for k, label in keys if world.get(k))


def carry_map(ents: list[dict]) -> dict:
    return {e["name"]: int(e["carry"]) for e in ents if e["kind"] == "character" and str(e.get("carry", "")).strip().lstrip("-").isdigit()}


def card(e: dict, st: dict) -> str:
    if e["kind"] == "character":
        s = st.get("entities", {}).get(e["name"], {})
        live = "DEAD" if s and not s.get("alive", True) else "alive"
        bits = [e.get("role", ""), f"wants: {e['goal']}" if e.get("goal") else "", f"fears: {e['fear']}" if e.get("fear") else "", f"speaks: {e['voice']}" if e.get("voice") else "",
                f"secret: {e['secret']}" if e.get("secret") else "", f"skills: {', '.join(s.get('skills') or e.get('skills') or [])}" if (s.get("skills") or e.get("skills")) else "",
                s.get("status") or e.get("starting_condition") or ""]
        return f"- {e['name']} ({live}): " + "; ".join(b for b in bits if b)
    return f"- {e['name']} ({e['kind']}): {e.get('description', '')}"


class Packet:
    def __init__(self):
        self.fixed: list[tuple[str, str]] = []
        self.drop: list[tuple[int, str, str]] = []          # (priority: lower is dropped first, title, text)
        self.trimmed: list[str] = []
        self.rule_labels: dict[str, str] = {}
        self.thread_labels: dict[str, str] = {}

    def text(self, cap: int, est) -> str:
        parts = list(self.drop)
        total = sum(est(t) for _, t in self.fixed) + sum(est(t) for _, _, t in parts)
        for item in sorted(parts, key=lambda x: x[0]):
            if total <= cap:
                break
            parts.remove(item)
            total -= est(item[2])
            self.trimmed.append(item[1])
        keep = {(p, t) for p, t, _ in parts}
        blocks = [f"## {title}\n{body}" for title, body in self.fixed]
        blocks += [f"## {title}\n{body}" for p, title, body in self.drop if (p, title) in keep]
        return "\n\n".join(blocks)


def build(pid: str, path: list[dict], st: dict, focus: list[str] | None = None, scene: str = "", s: dict | None = None) -> Packet:
    """The packet for the chapter that comes after `path` (the whole line so far), given the current state."""
    pk = Packet()
    world = store.world(pid)
    rules, pk.rule_labels = rules_text(pid)
    pk.fixed.append(("CONTENT", content.text(store.project(pid)["settings"])))
    pk.fixed.append(("WORLD", world_text(world)))
    pk.fixed.append(("RULES", rules))
    cfg = store.project(pid)["settings"]
    pk.fixed.append(("STATE", S.describe(st, store.trackers(pid), carry_map(store.entities(pid)), int(cfg.get("carry_limit", 0) or 0))))
    recipes = S.recipes_text(st)
    if recipes:
        pk.drop.append((2, "RECIPES KNOWN", recipes))
    found = S.found_text(st)
    if found:
        pk.drop.append((1, "FOUND LATELY", found))
    last = path[-1] if path else None
    if last and last.get("prose"):
        paras = [p for p in last["prose"].split("\n") if p.strip()]
        pk.fixed.append(("LAST CHAPTER (its ending)", f"{last['title']} ({last['story_time']})\n" + "\n".join(paras[-2:])))
    ents = store.entities(pid)
    foc = {x.lower() for x in (focus or [])}
    hay = (scene or "").lower()
    chars = [e for e in ents if e["kind"] == "character"]
    core = [e for e in chars if e["name"].lower() in foc] if foc else chars
    pk.fixed.append(("PEOPLE", "\n".join(card(e, st) for e in core)))
    others = [e for e in ents if e not in core]
    if others:
        pk.drop.append((3, "OTHER PEOPLE AND PLACES", "\n".join(card(e, st) for e in others)))
    rolled, after = story_so_far(path)
    if rolled:
        pk.fixed.append(("STORY SO FAR", rolled))
    summ = [f"Ch {c['idx']}: {c['summary']}" for c in after if c["summary"]]
    if summ:
        pk.fixed.append(("RECENT CHAPTERS", "\n".join(summ[-3:])))
        if len(summ) > 3:
            pk.drop.append((2, "EARLIER CHAPTERS", "\n".join(summ[-SUMMARY_KEEP:-3])))
    th = open_threads(pid, path)[:MAX_THREADS]
    pk.thread_labels = {f"T{i}": t["id"] for i, t in enumerate(th, 1)}
    if th:
        pk.fixed.append(("OPEN THREADS", "\n".join(f"T{i} {t['text']}" for i, t in enumerate(th, 1))))
    facts = path_facts(pid, path)
    scored = []
    for f in facts:
        hit = sum(1 for n in f["entity_names"] if n.lower() in foc or n.lower() in hay) + sum(1 for t in f["tags"] if t.lower() in hay)
        scored.append((hit, f["created_at"], f))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    if scored:
        pk.drop.append((1, "REMEMBERED FACTS", "\n".join(f"- {f['text']}" for _, _, f in scored[:MAX_FACTS])))
    return pk


def render(pk: Packet, s: dict | None = None) -> str:
    s = s or settings_mod.get()
    b = Budget.from_settings(s)
    cap = min(PACKET_TOKENS, b.input_limit(3000))
    return pk.text(cap, b.est)
