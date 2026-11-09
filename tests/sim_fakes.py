"""A scripted chat model for the story simulator tests. It answers by the [TASK:sm_*] tag and reads names from the prompt, so the same fake runs any genre (a supermarket outbreak, a courtroom)."""
import json
import re

from story.llm import LLMResult


def words(n: int, seed: str = "w") -> str:
    return " ".join(f"{seed}{i % 17}" for i in range(n))


class SimFake:
    def __init__(self, prose_words: int = 350, **answers):
        self.calls: list[dict] = []
        self.answers = answers                     # task -> dict or function(user, call_no) -> dict
        self.prose_words = prose_words
        self.plan_n = 0

    def count(self, task):
        return sum(1 for c in self.calls if c["task"] == task)

    def last(self, task):
        return [c for c in self.calls if c["task"] == task][-1]

    async def complete(self, messages, max_tokens, params=None):
        system, user = messages[0]["content"], messages[1]["content"]            # the first user message (a retry appends the complaint after it)
        task = re.match(r"\[TASK:(\w+)\]", system).group(1)
        self.calls.append({"task": task, "system": system, "user": user, "params": params or {}, "max_tokens": max_tokens})
        a = self.answers.get(task)
        if a is not None:
            out = a(user, self.count(task)) if callable(a) else a
        else:
            out = getattr(self, "_" + task)(user)
        return LLMResult(json.dumps(out))

    # ── seed ──
    def _sm_world(self, user):
        return {"title": "The Long Night", "place": "Fairview Supermarket", "period": "a winter night", "tone": "tense", "pacing": "minutes to hours",
                "exists": "Aisle One food: canned beans, bottled water, rice. Aisle Two hardware: crowbar, rope, duct tape, kitchen knives. Pharmacy: bandages, painkillers. Loading Bay: steel shutter, pallets.",
                "craft": "Makeshift tools only; nothing electronic works.", "goal": "Survive until dawn: every chapter must move the group closer to or further from living through the night.", "start_scene": "The lights flicker as the first scream comes from the street.", "start_time": "Day 1, 23:00"}

    def _sm_cast(self, user):
        people = [("Ravi", "night salesman", "survive until dawn"), ("Meera", "cashier", "get home to her daughter"), ("Dev", "security guard", "protect the store"), ("Sana", "customer", "find her brother")]
        ents = [{"kind": "character", "name": n, "role": r, "goal": g, "fear": "being alone", "voice": "plain", "look": f"{n}, a tired adult in a work uniform with a distinctive scar", "skills": [f"{r} work", "improvising"],
                 "relations": {"Ravi": "colleague"} if n != "Ravi" else {}} for n, r, g in people]
        ents += [{"kind": "place", "name": p, "description": f"{p} of the supermarket", "look": f"{p}, harsh white light", "connects_to": ["Aisle One"]} for p in ("Aisle One", "Aisle Two", "Pharmacy", "Loading Bay")]
        return {"entities": ents}

    def _sm_trackers(self, user):
        return {"trackers": [
            {"name": "Supplies", "kind": "items", "start": [{"name": "Canned beans", "qty": 6, "at": "Aisle One"}, {"name": "Crowbar", "qty": 1, "at": "Aisle Two"}, {"name": "Bandages", "qty": 4, "at": "Pharmacy"}]},
            {"name": "Group morale", "kind": "meter", "min": 0, "max": 10, "start": 6, "danger_below": 2, "owner": "group"},
            {"name": "Horde nears", "kind": "clock", "max": 6, "start": 1, "rises": "noise", "ends": "the horde breaks in"},
            {"name": "Ravi and Meera", "kind": "relation", "a": "Ravi", "b": "Meera", "start": {"trust": 1, "tension": 0}},
            {"name": "Where everyone is", "kind": "location", "start": {"at": {"Ravi": "Aisle One", "Meera": "Aisle One", "Dev": "Loading Bay", "Sana": "Pharmacy"}, "locked": []}},
            {"name": "Why the dead walk", "kind": "knowledge", "start": {"The source": ["Dev"]}},
            {"name": "Power is on", "kind": "flag", "start": True}]}

    def _sm_items(self, user):
        return {"items": [{"name": "Crowbar", "qty": 1, "at": "Aisle Two"}, {"name": "Rope", "qty": 2, "at": "Aisle Two"}, {"name": "Bandages", "qty": 4, "at": "Pharmacy"}]}

    def _sm_rules(self, user):
        return {"rules": [{"group": "hard", "text": "Only items that exist in the store may be used."}, {"group": "hard", "text": "Nobody can leave the building safely before dawn."},
                          {"group": "world", "text": "Noise draws the dead."}, {"group": "tone", "text": "Keep it grounded and tense."}, {"group": "style", "text": "Third person, past tense."},
                          {"group": "craft", "text": "Things are made only from parts at hand."}]}

    def _sm_suggest(self, user):
        return {"rules": [{"group": "world", "text": "The dead are slow but never tire."}]}

    # ── a chapter ──
    def _people(self, user):
        sec = user.split("## PEOPLE")[1].split("##")[0] if "## PEOPLE" in user else ""
        return [m.group(1) for m in re.finditer(r"^- ([^(\n]+?) \(alive\)", sec, re.M)]

    def _sm_plan(self, user):
        self.plan_n += 1
        alive = self._people(user) or ["Ravi"]
        due = re.findall(r"D\d+ \(id ([\w-]+)\)", user)
        mp = re.search(r"^\[([^\]]+)\] \(meter\)", user, re.M)
        beats = ["escalate", "setback", "discovery", "respite", "choice", "reversal", "reveal"]
        return {"focus": alive[:2], "where": "Aisle One", "scene": f"{alive[0]} moves to secure the doors while the noise outside grows.", "intent": f"{alive[0]} tries to barricade the doors with pallets.",
                "pressure": "the clock", "risks": [{"who": alive[0], "act": "barricade the doors", "stats": [mp.group(1)] if mp else [], "items": ["Crowbar"], "difficulty": "normal"}],
                "beat": beats[self.plan_n % len(beats)], "time_passes": "40 minutes", "addresses": due, "opposition": "The noise outside grows and something tests the doors."}

    def _sm_minds(self, user):
        return {"wants": {n: "keeps watch" for n in re.findall(r"Others: (.*)", user)[0].split(", ")}}

    def _sm_delta(self, user):
        mp = re.search(r"^\[([^\]]+)\] \(meter\)", user, re.M)
        cp = re.search(r"^\[([^\]]+)\] \(clock\)", user, re.M)
        ops = []
        if mp:
            ops.append({"op": "meter_change", "tracker": mp.group(1), "amount": -1, "why": "fear"})
        if cp:
            ops.append({"op": "clock_advance", "tracker": cp.group(1), "amount": 1, "why": "noise"})
        ops.append({"op": "item_add", "target": "Rocket launcher", "qty": 1, "why": "found it"})         # no source: must be refused
        return {"ops": ops}

    def _sm_write(self, user):
        return {"title": "Barricade", "prose": words(self.prose_words), "story_time": "Day 1, 23:40"}

    def _sm_referee(self, user):
        return {"ok": True, "violations": []}

    def _sm_archive(self, user):
        alive = [x.strip() for x in re.search(r"Alive: (.*)", user).group(1).split(",")]
        return {"summary": "The doors were barricaded as the noise grew.", "facts": [{"text": f"{alive[0]} used pallets to block the doors.", "names": [alive[0]], "tags": ["barricade"]}],
                "threads_opened": ["Who is knocking on the loading bay shutter?"], "threads_closed": [],
                "options": [{"who": alive[i % len(alive)], "label": f"{alive[i % len(alive)]} tries plan number {i} to {w}", "hint": "uncertain", "risk": r}
                            for i, (w, r) in enumerate([("search the pharmacy", "low"), ("check the shutter", "medium"), ("signal the street", "high"), ("hide in the stockroom", "low")], 1)]}

    def _sm_pick(self, user):
        return {"option": "o2", "why": "fits the character"}

    def _sm_condition(self, user):
        return {"met": False, "why": "not yet"}

    def _sm_rollup(self, user):
        return {"text": "The night began with doors barricaded and fear rising."}

    def _sm_reread(self, user):
        return {"ops": [{"op": "entity_status", "target": "Ravi", "value": "limping", "why": "edit"}], "note": "Ravi now limps."}

    def _sm_panels(self, user):
        return {"panels": [{"shot": "wide", "who": ["Ravi"], "place": "Aisle One", "action": "Ravi stacks pallets against the glass doors under flickering light", "mood": "cold blue", "caption": "The doors would have to hold."},
                           {"shot": "close", "who": ["Meera"], "place": "Aisle One", "action": "Meera listens at the shutter with a hand pressed to the metal", "mood": "dim amber", "caption": "Something moved outside."},
                           {"shot": "medium", "who": ["Ravi", "Meera"], "place": "Pharmacy", "action": "Ravi and Meera share a look over a torn box of bandages", "mood": "warm shadow", "caption": "Trust came slowly."}]}
