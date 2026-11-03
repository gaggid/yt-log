"""The director's shot list of a short: one call that sees the whole narration and plans every picture before any shot is written, so that the pictures tell the story instead of repeating the
safest subject (the per-beat shot calls cannot see each other). Also the variety check (`problems`): one subject on most shots, or two shots that are nearly the same picture."""
import re

from story import llm, settings as settings_mod
from story.schemas import Str
from story2.schemas import M

from . import subjects as subj

MAX_SHARE = 0.4                    # one subject on more than this share of the shots is a warning
SIMILAR = 0.6                     # word overlap of two start-picture prompts (same subjects) that makes them the same picture
STOP = set("a an the of in on at to with and or is are its it this that from by as for into over under while during sits stands showing shows shot frame framing light mood natural soft clear wide medium close".split())


class IdeaOut(M):
    idea: Str
    subjects: list[Str] = []


class BeatIdeasOut(M):
    ideas: list[IdeaOut] = []


class ListOut(M):
    subjects: list[subj.SubjectOut] = []
    beats: list[BeatIdeasOut]


SYSTEM = """[TASK:p4_shotlist]
You are the director of a {seconds}-second vertical video short for Indian viewers. The narration is written. Plan the PICTURES of the whole short before any shot is written, so that no two shots look alike and the pictures tell the story.

Return ONLY a JSON object: {"subjects": [{"name": "...", "kind": "...", "visual": "..."}], "beats": [{"ideas": [{"idea": "...", "subjects": ["exact subject name"]}]}]}

- One entry in "beats" for each beat, in order, with EXACTLY as many ideas as the beat has shots (the counts are given).
- An idea is ONE picture, English, 12 to 25 words: what is seen, from where, and what it proves. One subject or one pair, one place, one framing.
- Show the CLAIM of the beat, not only its topic. If the beat says thin air cuts the payload, show the proof: a jet on a high dusty runway carrying a single missile while another jet at a low base carries a full rack; do not just show a jet.
- Variety is the job. Over the whole short: no subject on more than a third of the ideas; no two ideas with the same subject in the same place and framing; every idea differs from the one before it in subject, place or framing.
  Mix the kinds of picture: a wide establishing view, a close detail that proves a point, people at work (pilots, crew, engineers, soldiers, ordinary people), a place, an A-against-B pair, a moment from the past when the story has history, and the payoff.
- The first idea stops the scroll. The middle ideas show cause and effect, one step per picture. The last idea is the payoff or the open question.
- Cover every fact of the beat's narration, including a central question or a piece of history the facts mention.
- Everything is physical and can be photographed by a real camera. No diagrams, charts, glowing effects or readable text. A map may appear only as a printed paper map on a table with nothing readable on it.
- "subjects" (top level): the new subjects your ideas need that are not in THE SUBJECTS yet. If THE SUBJECTS has only machines or places, you MUST add the missing kinds: people at work (a pilot, a ground crew member, an engineer, a soldier, a commander), a place, an object or a person from the period of history the facts mention (never the period itself: an era or an idea cannot be drawn), and an object that proves a point (a loaded or empty weapon rack, a fuel gauge, a worn runway). Use them in your ideas.
  Same format as THE SUBJECTS, "visual" 20 to 45 words, concrete, every person and machine says whose it is by what can be seen (uniform colours, roundel); Indian people unless the facts say otherwise. At most {room} new ones. Nothing graphic: no gore, no weapons aimed at anyone.
- An idea's "subjects" are exact names from THE SUBJECTS or your new ones; empty when the picture shows none.
"""


def room(short: dict) -> int:
    return max(0, subj.MAX_SUBJECTS - len(subj.of(short)))


def system(short: dict, target_s: float) -> str:
    return SYSTEM.replace("{seconds}", f"{target_s:g}").replace("{room}", str(room(short)))


async def make(short: dict, counts: list[int], backend, s: dict | None, target_s: float) -> dict:
    """Ask for the pictures of every beat. Returns {"ideas": [[{"idea", "subjects"}, ...] per beat], "subjects": [new subject dicts]}. Never raises on a model that disagrees with the counts: a beat with the wrong
    number of ideas simply gets none (its shots are written without a list)."""
    from . import planner
    s = s or settings_mod.get()
    caller = llm.JsonCaller(backend, s)
    lines = [f"WHOLE SHORT: {short['plan'].get('title', '')} - {short['plan'].get('logline', '')}", planner.source_text(short)]
    if subj.of(short):
        lines.append("THE SUBJECTS:\n" + "\n".join(f"- {x['name']} ({x['kind'] or 'subject'}): {x['visual']}" for x in subj.of(short)))
    lines.append("THE BEATS (narration, and how many shots each has):\n" + "\n".join(
        f"{i + 1}. ({b['name']}) {' '.join(x['text'] for x in b['sentences']) or '-'}  [{n} shots]" for i, (b, n) in enumerate(zip(short["beats"], counts))))

    def check(out: ListOut) -> None:
        if caller.last_attempt:
            return
        if len(out.beats) != len(counts):
            raise ValueError(f"write one entry in \"beats\" for each of the {len(counts)} beats, not {len(out.beats)}")
        bad = [f"beat {i + 1} needs {n} ideas, not {len(b.ideas)}" for i, (b, n) in enumerate(zip(out.beats, counts)) if len(b.ideas) != n]
        if bad:
            raise ValueError("; ".join(bad[:4]))
        have = {subj._norm(x["name"]) for x in subj.of(short)} | {subj._norm(x.name) for x in out.subjects}
        unknown = sorted({n for b in out.beats for x in b.ideas for n in x.subjects if subj._norm(n) not in have})
        if unknown:
            raise ValueError("these subjects are used in ideas but not listed: " + ", ".join(unknown[:4]) + ". Add each to the top-level \"subjects\" with its \"visual\", or use a name from THE SUBJECTS")
        total = sum(counts)
        use: dict[str, int] = {}
        for b in out.beats:
            for x in b.ideas:
                for n in set(x.subjects):
                    use[n] = use.get(n, 0) + 1
        top = max(use.items(), key=lambda kv: kv[1], default=("", 0))
        if total >= 6 and top[1] > MAX_SHARE * total:
            raise ValueError(f"\"{top[0]}\" is in {top[1]} of {total} ideas; keep it to {int(MAX_SHARE * total)} at most and use other subjects, people, places and objects for the rest")

    res = await caller.call(system(short, target_s), "\n".join(lines) + "\n\nPlan the pictures now.", ListOut, validate=check)
    out = res.value
    known = {subj._norm(x["name"]) for x in subj.of(short)} | {subj._norm(x.name) for x in out.subjects[:room(short)]}
    ideas = []
    for i, n in enumerate(counts):
        got = out.beats[i].ideas if i < len(out.beats) else []
        ideas.append([{"idea": x.idea.strip(), "subjects": [y.strip() for y in x.subjects if subj._norm(y) in known]} for x in got if x.idea.strip()] if len(got) == n else [])
    return {"ideas": ideas, "subjects": [x.model_dump() for x in out.subjects][:room(short)]}


def apply(short: dict, brief: dict) -> None:
    """Keep the new subjects the director asked for (up to the limit) and the idea list of each beat (shots are written from it)."""
    if brief["subjects"]:
        short["plan"]["subjects"] = subj.clean(subj.of(short) + brief["subjects"])
    for b, ideas in zip(short["beats"], brief["ideas"]):
        b["ideas"] = ideas


def drawn(short: dict, skip_beat: str = "") -> list[str]:
    """One line per shot already planned in other beats, so a beat's shots do not repeat them."""
    out = []
    for sh in short.get("shots", []):
        if sh.get("beat") == skip_beat:
            continue
        names = ", ".join(x["name"] for x in subj.in_shot(short, sh)) or "no listed subject"
        out.append(f"- {names}; {sh.get('setting') or 'main place'}; {sh.get('camera', 'static')}: {(sh.get('still') or sh.get('prompt') or '')[:110]}")
    return out


_SIZE_RE = re.compile(r"\b(extreme[\s-]close[\s-]?up|close[\s-]?up|medium|wide|establishing|overhead|bird[\s-]?s[\s-]?eye|low[\s-]?angle|high[\s-]?angle)\b", re.I)


def _shot_size(text: str) -> str:
    """The first shot-size keyword in the first 60 characters of a still prompt, normalised."""
    m = _SIZE_RE.search((text or "")[:60])
    return re.sub(r"[\s-]+", " ", m.group(1).lower()) if m else ""


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in STOP and len(w) > 2}


def _same(a: dict, b: dict) -> float:
    # Different shot sizes = visually distinct regardless of shared subject words
    sa = _shot_size(a.get("still") or a.get("prompt", ""))
    sb = _shot_size(b.get("still") or b.get("prompt", ""))
    if sa and sb and sa != sb:
        return 0.0
    wa, wb = _words(a.get("still") or a.get("prompt")), _words(b.get("still") or b.get("prompt"))
    return len(wa & wb) / max(1, min(len(wa), len(wb)))


def problems(short: dict) -> list[dict]:
    """Variety problems of the shots: [{"code", "text", "shots": [ids]}]. Warnings only."""
    shots = short.get("shots") or []
    if len(shots) < 4:
        return []
    out: list[dict] = []
    known = {x["name"] for x in subj.of(short)}
    names = [{n for n in sh.get("subjects") or [] if n in known} for sh in shots]            # the subjects the planner named for the shot; a mountain in the background does not count
    count: dict[str, list[str]] = {}
    for sh, ns in zip(shots, names):
        for n in ns:
            count.setdefault(n, []).append(sh["id"])
    if count:
        top, ids = max(count.items(), key=lambda kv: len(kv[1]))
        if len(ids) / len(shots) > MAX_SHARE and len(ids) >= 4:
            out.append({"code": "one_subject", "shots": ids, "text": f"{top} is on {len(ids)} of {len(shots)} shots; the pictures will feel the same. Redo some shots with other subjects, people or places"})
    pairs = []
    for i in range(len(shots)):
        for j in range(i + 1, len(shots)):
            a, b = (shots[i].get("setting") or "").strip().lower(), (shots[j].get("setting") or "").strip().lower()
            if names[i] == names[j] and (not a or not b or a == b) and _same(shots[i], shots[j]) >= SIMILAR:
                pairs.append((shots[i]["id"], shots[j]["id"]))
    if pairs:
        out.append({"code": "similar_shots", "shots": sorted({x for p in pairs for x in p}), "text": "nearly the same picture: " + "; ".join(f"{a} and {b}" for a, b in pairs[:5]) + ". Redo one of each pair"})
    return out
