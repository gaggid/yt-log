"""What the model answers at each step of the simulator (docs/PLAN_simulation.md sections 4, 5 and 10). Tolerant on input (strings for lists, missing fields), strict in the code that uses them."""
from typing import Any

from pydantic import BeforeValidator
from typing_extensions import Annotated

from story.schemas import Str, StrList
from story2.schemas import M

BEATS = ("escalate", "setback", "discovery", "respite", "choice", "reversal", "reveal")
DIFFICULTY = ("easy", "normal", "hard")
RISKS = ("low", "medium", "high")
OPS = ("item_add", "item_remove", "item_move", "meter_set", "meter_change", "clock_advance", "clock_set", "relation_change", "move", "lock", "unlock", "learn", "flag_set", "entity_status",
       "entity_dies", "discover", "craft", "item_give", "item_take", "item_use", "item_change", "skill_learn")
ACT_KINDS = ("search", "make", "use", "persuade", "take", "fight", "move", "learn", "other")


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


Num = Annotated[float, BeforeValidator(_num)]


ALIASES = {"clock_change": "clock_advance", "clock_increase": "clock_advance", "clock_tick": "clock_advance", "add_item": "item_add", "remove_item": "item_remove", "move_item": "item_move", "set_flag": "flag_set"}


def _ops(v):
    """The real model sometimes writes {"move": {"target": ..}} or {"operation": "move", ..} instead of {"op": "move", ..}; all of these are read as the same operation."""
    out = []
    for it in v or []:
        if isinstance(it, dict) and it.get("op") in ALIASES:
            it = {**it, "op": ALIASES[it["op"]]}
        if isinstance(it, dict) and "op" not in it:
            key = next((k for k in it if k in OPS), None)
            if key and isinstance(it[key], dict):
                it = {"op": key, **it[key]}
            elif key:
                it = {"op": key, "target": str(it[key]), **{k: x for k, x in it.items() if k != key}}
            else:
                alt = next((a for a in ("operation", "type", "action", "name") if it.get(a) in OPS), None)
                if alt:
                    it = {**it, "op": it[alt]}
        out.append(it)
    return out


# ── seed ──────────────────────────────────────────────────────────────────────

class WorldOut(M):
    place: Str
    period: Str = ""
    tone: Str = ""
    pacing: Str = ""
    exists: Str = ""                 # what exists in this world, as free text: the stock list, the evidence, the staff, the money
    craft: Str = ""                  # what can and cannot be made or found here (limits of technology, magic, money)
    goal: Str = ""                   # what the story is about: what the people must achieve or avoid, and what happens if they fail
    start_scene: Str = ""
    start_time: Str = ""
    title: Str = ""


class EntityOut(M):
    kind: Str = "character"
    name: Str
    role: Str = ""
    goal: Str = ""
    fear: Str = ""
    secret: Str = ""
    voice: Str = ""
    look: Str = ""
    description: Str = ""
    starting_condition: Str = ""
    connects_to: StrList = []
    relations: dict[str, str] = {}
    member_of: Str = ""
    skills: StrList = []             # two to four things this person is good at, as plain phrases


class CastOut(M):
    entities: list[EntityOut]


class TrackerOut(M):
    name: Str
    kind: Str
    description: Str = ""
    owner: Str = ""
    min: Num = 0
    max: Num = 10
    unit: Str = ""
    start: Any = None
    danger_below: Any = None
    danger_above: Any = None
    rises: Str = ""
    ends: Str = ""
    a: Str = ""
    b: Str = ""
    place: Str = ""
    secret: Str = ""


class TrackersOut(M):
    trackers: list[TrackerOut]


class ItemIn(M):
    name: Str
    qty: Num = 1
    at: Str = ""


class ItemsOut(M):
    items: list[ItemIn]


class GuidelineOut(M):
    group: Str = "hard"
    text: Str


class RulesOut(M):
    rules: list[GuidelineOut]


# ── a chapter ─────────────────────────────────────────────────────────────────

class CraftIn(M):
    makes: Str = ""                  # what the person tries to make
    parts: StrList = []              # things used up
    tools: StrList = []              # things needed but not used up
    skill: Str = ""                  # what the person would need to know
    reasoning: Str = ""              # why this is possible with what they hold and know


class RiskIn(M):
    who: Str = ""
    act: Str
    stats: StrList = []              # names of meter / relation trackers that help or hurt this act
    items: StrList = []              # items that are being used
    difficulty: Str = "normal"
    kind: Str = "other"              # search, make, use, persuade, take, fight, move, learn, other
    target: Str = ""                 # the person an act of persuading or taking is aimed at
    craft: CraftIn | None = None


class ChapterPlan(M):
    focus: StrList
    where: Str = ""
    scene: Str
    intent: Str
    pressure: Str = ""
    risks: list[RiskIn] = []
    beat: Str = "escalate"
    time_passes: Str = ""
    addresses: StrList = []          # ids of the due instructions this chapter handles
    wait_reason: Str = ""            # why a conditional instruction waits one more chapter
    opposition: Str = ""             # what the opposing force (threat, rival, deadline, a secret about to come out) does this chapter on its own


class Op(M):
    op: Str
    tracker: Str = ""
    target: Str = ""
    to: Str = ""
    qty: Num = 1
    amount: Num = 0
    value: Any = None
    who: Str = ""
    source: Str = ""
    parts: StrList = []
    why: Str = ""
    kind: Str = ""
    name: Str = ""
    where: Str = ""                  # discover: the place it is found
    text: Str = ""                   # discover: what a clue says, what a place is like
    tools: StrList = []              # craft: needed, not used up
    skill: Str = ""                  # craft, discover recipe, skill_learn
    props: dict = {}                 # item_add, craft, discover: condition, uses, size, tags


class DeltaOut(M):
    ops: Annotated[list[Op], BeforeValidator(_ops)] = []


class WriteOut(M):
    title: Str
    prose: Str
    story_time: Str = ""


class ActorOut(M):
    name: Str
    intent: Str    # what they want to achieve this moment
    attempt: Str   # what they will physically try to do
    reasoning: Str # why: their goal, fear, or what they just saw


class Violation(M):
    rule: Str = "continuity"
    quote: Str = ""
    fix: Str = ""


class RefereeOut(M):
    ok: bool = True
    violations: list[Violation] = []


class FactIn(M):
    text: Str
    names: StrList = []
    tags: StrList = []


class OptionIn(M):
    who: Str = ""
    label: Str
    hint: Str = ""                   # what it might gain
    cost: Str = ""                   # what it might cost or put at risk
    risk: Str = "medium"


class ArchiveOut(M):
    summary: Str
    facts: list[FactIn] = []
    threads_opened: StrList = []
    threads_closed: StrList = []      # ids of open threads that this chapter paid off
    options: list[OptionIn]


class PickOut(M):
    option: Str
    why: Str = ""


class CondOut(M):
    met: bool
    why: Str = ""


class RollupOut(M):
    text: Str


class RereadOut(M):
    ops: Annotated[list[Op], BeforeValidator(_ops)] = []
    note: Str = ""


class PanelIn(M):
    shot: Str = "medium"
    who: StrList = []
    place: Str = ""
    action: Str
    mood: Str = ""
    caption: Str = ""
    after: Num = 0                        # the paragraph (counting from 1) this picture illustrates; it shows right after it


class PanelsOut(M):
    panels: list[PanelIn]


class RuleSuggest(M):
    rules: list[GuidelineOut]


# ── the story plan (docs/PLAN_architect.md) ───────────────────────────────────

class ClueIn(M):
    beat: Num = 0
    clue: Str = ""


def _num_list(v):
    if isinstance(v, (int, float, str)) and not isinstance(v, bool):
        v = [v]
    return [x for x in (v or []) if isinstance(x, (int, float, str)) and not isinstance(x, bool)]


NumList = Annotated[list[Num], BeforeValidator(_num_list)]


class RulePlanIn(M):
    name: Str = ""
    text: Str = ""
    beat: Num = 0
    kind: Str = "stated"                  # stated (said aloud), discovered (learned from what happens) or policy (never said, shown by what happens)
    uses: NumList = []                    # later beats where it is used again (the refrain)
    shown: Str = ""                       # for a policy: how it shows without being said
    broken_beat: Num = 0                  # a beat where it is broken on purpose (0 = never)


class MotifIn(M):
    name: Str = ""
    what: Str = ""
    first_beat: Num = 0
    payoffs: Annotated[list[Num], BeforeValidator(lambda v: [v] if isinstance(v, (int, float, str)) and not isinstance(v, bool) else (v or []))] = []


class FactPlanIn(M):
    fact: Str = ""
    use: Str = ""
    beat: Num = 0


class SecretIn(M):
    truth: Str = ""
    who: Str = ""
    reveal_beat: Num = 0
    clues: list[ClueIn] = []
    kind: Str = ""                        # authority_lie, trap, hidden_resource, betrayal, identity or other
    lie: Str = ""                         # what the authority publicly says (the number or rule that is not true)
    found_by: Str = ""                    # how the person finds out (a list turned into a map, a measurement)
    method_beat: Num = 0


class OpeningIn(M):
    line: Str = ""
    action: Str = ""
    belief: Str = ""


class CountStepIn(M):
    beat: Num = 0
    value: Num = 0
    note: Str = ""


class CountdownIn(M):
    name: Str = ""
    unit: Str = ""
    steps: list[CountStepIn] = []


class ObjectIn(M):
    name: Str = ""
    what: Str = ""
    plant_beat: Num = 0
    payoff_beat: Num = 0
    payoff: Str = ""


class MarkIn(M):
    beat: Num = 0
    change: Str = ""
    loss: Str = ""


class EndingIn(M):
    outcome: Str = ""
    final_image: Str = ""
    closing_line: Str = ""
    inversion: Str = ""                   # how the ending turns the opening action, rule or belief around


class BibleOut(M):
    logline: Str
    pov: Str = "second"
    voice: Str = ""
    secret: SecretIn = SecretIn()
    rules: list[RulePlanIn] = []
    motifs: list[MotifIn] = []
    facts: list[FactPlanIn] = []
    ending: EndingIn = EndingIn()
    opening: OpeningIn = OpeningIn()
    countdown: CountdownIn = CountdownIn()
    objects: list[ObjectIn] = []
    midpoint: MarkIn = MarkIn()
    low_point: MarkIn = MarkIn()


def _clue_texts(v):
    out = []
    for x in v or []:
        if isinstance(x, dict):
            x = x.get("clue") or x.get("text") or ""
        if str(x).strip():
            out.append(str(x).strip())
    return out


class BeatIn(M):
    n: Num = 0
    label: Str = ""
    title: Str = ""
    time: Str = ""
    event: Str = ""
    problem: Str = ""
    turn: Str = ""
    hook: Str = ""
    purpose: Str = "problem"
    challenge: Str = ""
    clues: Annotated[list[str], BeforeValidator(_clue_texts)] = []
    rule: Str = ""
    motif: Str = ""
    fact: Str = ""
    solved_by: Str = ""


class SecretCandidate(M):
    kind: Str = "other"
    truth: Str = ""
    who: Str = ""
    lie: Str = ""
    found_by: Str = ""
    clues: StrList = []


class SecretsOut(M):
    candidates: list[SecretCandidate]


class BeatsOut(M):
    beats: list[BeatIn]
