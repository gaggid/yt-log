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

    def _sm_bible(self, user):
        n, start = (int(x) for x in re.search(r"The plan covers (\d+) beats, numbered (\d+) to", user).groups())
        end = start + n - 1
        mid = start + (n - 1) // 2
        return {"logline": "A night, a store and a voice that always knows where you are.", "pov": "second", "voice": "Short sentences, present tense, dry humor, real numbers.",
                "opening": {"line": "Stay in your room, says the intercom.", "action": "locks the door and waits for the voice", "belief": "whoever talks on the intercom is on your side"},
                "secret": {"truth": "The voice on the intercom is leaving them behind.", "kind": "authority_lie", "lie": "The intercom says help is coming at dawn.", "who": "the manager", "reveal_beat": end - 1,
                           "found_by": "the person turns the list of intercom orders into a map of the store", "method_beat": end - 2,
                           "clues": [{"beat": start, "clue": "the intercom knows which aisle you are in"}, {"beat": start + 1, "clue": "the intercom never mentions the exit"}, {"beat": start + 2, "clue": "the manager's coat is missing"}]},
                "countdown": {"name": "Water", "unit": "days", "steps": [{"beat": start, "value": 22, "note": "start"}, {"beat": mid, "value": 14, "note": "a leak"}, {"beat": end - 1, "value": 3, "note": "the tank is empty"}]},
                "objects": [{"name": "The cake", "what": "a cake box in the freezer", "plant_beat": start + 1, "payoff_beat": end, "payoff": "it is eaten at the end"}],
                "midpoint": {"beat": mid, "change": "the lights go out for good"}, "low_point": {"beat": max(mid + 1, end - 2), "loss": "the door is lost"},
                "rules": [{"name": "Rule one", "text": "Move when the noise moves.", "beat": start + 1, "kind": "stated", "uses": [mid, end]},
                          {"name": "Rule two", "text": "They push; they cannot pull.", "beat": start + 2, "kind": "discovered", "broken_beat": end},
                          {"name": "Staff list", "text": "Staff sleep nearest the door.", "beat": start + 3, "kind": "policy", "shown": "the manager puts the cook by the door"}],
                "motifs": [{"name": "The bell", "what": "a bell that rings every 50 minutes", "first_beat": start, "payoffs": [end]}],
                "facts": [{"fact": "A person needs about a gallon of water a day.", "use": "counting the days the water lasts", "beat": start}],
                "ending": {"outcome": "They are alone.", "final_image": "the intercom clicks on", "closing_line": "Stay in your room.", "inversion": "the person unlocks the door and walks out instead of waiting"}}

    def _sm_beats(self, user):
        n, start = (int(x) for x in re.search(r"Write exactly (\d+) beats numbered (\d+) to", user).groups())
        return {"beats": [{"n": start + i, "label": f"Day {start + i}: Beat {start + i}", "time": f"Day {start + i}", "title": f"Beat {start + i}", "event": "The people secure the doors while the noise outside grows",
                           "problem": "barricade the doors with pallets before the noise draws them in", "turn": "the noise changes", "hook": "a knock on the shutter", "purpose": "problem", "challenge": "barricade the doors", "solved_by": "pallets stacked against the doors hold"} for i in range(n)]}

    def _sm_secrets(self, user):
        return {"candidates": [{"kind": "authority_lie", "truth": f"The manager lies about help {i}.", "who": "the manager", "lie": "help comes at dawn", "found_by": "count the radio calls", "clues": ["a coat is missing", "the radio is silent"]} for i in range(5)]}

    def _sm_items(self, user):
        return {"items": [{"name": "Crowbar", "qty": 1, "at": "Aisle Two"}, {"name": "Rope", "qty": 2, "at": "Aisle Two"}, {"name": "Bandages", "qty": 4, "at": "Pharmacy"}]}

    def _sm_rules(self, user):
        return {"rules": [{"group": "hard", "text": "Only items that exist in the store may be used."}, {"group": "hard", "text": "Nobody can leave the building safely before dawn."},
                          {"group": "world", "text": "Noise draws the dead."}, {"group": "tone", "text": "Keep it grounded and tense."}, {"group": "style", "text": "Third person, past tense."},
                          {"group": "craft", "text": "Things are made only from parts at hand."}]}

    def _sm_suggest(self, user):
        return {"rules": [{"group": "world", "text": "The dead are slow but never tire."}]}

    # ── a chapter ──
    def _sm_actor(self, user):
        m = re.search(r"CHARACTER: ([^—\n]+)", user)
        name = m.group(1).strip() if m else "Unknown"
        return {"name": name, "intent": f"{name} wants to secure the situation", "attempt": f"{name} moves carefully toward the nearest exit", "reasoning": "survival first, stay low, stay quiet"}

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

    def _sm_polish(self, user):
        return {"title": "Polished", "prose": "polished " + words(self.prose_words), "story_time": "Day 1"}

    def _sm_referee(self, user):
        return {"ok": True, "violations": []}

    def _sm_archive(self, user):
        n = self.count("sm_archive")
        alive = [x.strip() for x in re.search(r"Alive: (.*)", user).group(1).split(",")]
        return {"summary": "The doors were barricaded as the noise grew.", "facts": [{"text": f"{alive[0]} used pallets to block the doors.", "names": [alive[0]], "tags": ["barricade"]}],
                "threads_opened": [f"Chapter {n}: what is knocking on the loading bay shutter?"], "threads_closed": [],
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
        return {"panels": [{"shot": "wide", "who": ["Ravi"], "place": "Aisle One", "action": "Ravi stacks pallets against the glass doors under flickering light", "mood": "cold blue", "caption": "The doors would have to hold.", "after": 1},
                           {"shot": "close", "who": ["Meera"], "place": "Aisle One", "action": "Meera listens at the shutter with a hand pressed to the metal", "mood": "dim amber", "caption": "Something moved outside.", "after": 99},
                           {"shot": "medium", "who": ["Ravi", "Meera"], "place": "Pharmacy", "action": "Ravi and Meera share a look over a torn box of bandages", "mood": "warm shadow", "caption": "Trust came slowly."}]}
