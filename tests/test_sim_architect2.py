"""Story Architect 2 (docs/PLAN_architect2.md): the framework of the reference films as plan data: ladder, number on screen, authority-lie secret with a method, opening and ending turned around,
acts, planted objects, long films in parts, rules of four kinds."""
from sim import architect, health, models as m, store
from sim_fakes import words
from test_sim_api import client, new_story, wait  # noqa: F401
from test_sim_things_api import detail


def bible_out(**kw):
    base = {"logline": "L", "pov": "you", "voice": "v",
            "opening": {"line": "Hold the door.", "action": "holds the door", "belief": "doors must stay open"},
            "secret": {"truth": "T", "kind": "Authority Lie", "lie": "one year of food", "who": "w", "reveal_beat": 10, "found_by": "count the marks", "method_beat": 99,
                       "clues": [{"beat": 2, "clue": "a"}, {"beat": 5, "clue": "b"}, {"beat": 6, "clue": "c"}]},
            "countdown": {"name": "Days", "unit": "days", "steps": [{"beat": 9, "value": 3}, {"beat": 1, "value": 22}, {"beat": 1, "value": 21}, {"beat": 5, "value": 10.5}]},
            "objects": [{"name": "Cake", "what": "in the freezer", "plant_beat": 3, "payoff_beat": 1, "payoff": "eaten"}, {"name": "Key", "plant_beat": 2, "payoff_beat": 7, "payoff": "opens"}, {"name": ""}],
            "midpoint": {"beat": 1, "change": "lights out"}, "low_point": {"beat": 10, "loss": "the door"},
            "rules": [{"name": "R1", "text": "never stop", "beat": 3, "kind": "STATED", "uses": [2, 5, 99], "broken_beat": 11},
                      {"name": "R2", "text": "staff by the door", "beat": 2, "kind": "policy", "shown": "the list", "broken_beat": 1}],
            "ending": {"outcome": "o", "inversion": "pushes the door"}}
    base.update(kw)
    return m.BibleOut.model_validate(base)


def test_the_backbone_gets_acts_a_method_after_the_clues_objects_that_pay_off_and_a_number_that_steps():
    b = architect.clean_bible(bible_out(), 1, 12)
    assert b["secret"]["kind"] == "authority_lie" and b["secret"]["lie"] and 6 <= b["secret"]["method_beat"] <= b["secret"]["reveal_beat"] - 1       # the method comes after the last clue, before the reveal
    assert 5 <= b["midpoint"]["beat"] <= 7 and b["midpoint"]["change"] == "lights out"                                                              # 40 to 60 per cent
    assert b["low_point"]["beat"] > b["midpoint"]["beat"] and b["low_point"]["beat"] != b["secret"]["reveal_beat"] and b["low_point"]["beat"] <= 11
    assert [s["beat"] for s in b["countdown"]["steps"]] == [1, 5, 9] and b["countdown"]["steps"][0]["value"] == 21 and b["countdown"]["steps"][1]["value"] == 10.5   # sorted, one per beat, whole numbers stay whole
    assert [o["name"] for o in b["objects"]] == ["Cake", "Key"] and b["objects"][0]["payoff_beat"] == 12 and b["objects"][1]["payoff_beat"] == 7        # a payoff before the plant moves to the end
    r1, r2 = b["rules"]
    assert r1["kind"] == "stated" and r1["uses"] == [5] and r1["broken_beat"] == 11 and r2["kind"] == "policy" and r2["shown"] == "the list" and r2["broken_beat"] == 0   # uses come after the rule; broken only after it is learned
    assert b["opening"]["line"] == "Hold the door." and b["ending"]["inversion"] == "pushes the door"
    short = architect.clean_bible(bible_out(), 1, 4)
    assert short["midpoint"] == {} and short["low_point"] == {}                                                                                      # a tiny plan has no acts
    assert architect.clean_bible(bible_out(countdown={"name": "Days", "steps": [{"beat": 1, "value": 3}]}), 1, 12)["countdown"] == {}                # one step is not a countdown


def beats12(b, **extra):
    return architect.decorate({**b, "beats": architect.clean_beats([m.BeatIn(event="e", problem="p", purpose="problem", title=f"T{i}", solved_by="s") for i in range(12)], b, 1, 12)})


def test_decorate_numbers_the_problems_and_works_out_what_each_beat_carries():
    full = beats12(architect.clean_bible(bible_out(), 1, 12))
    by = {x["n"]: x for x in full["beats"]}
    ladder = [x for x in full["beats"] if x["problem_no"]]
    assert [x["problem_no"] for x in ladder] == list(range(1, len(ladder) + 1)) and ladder[0]["signpost"] == "First problem: T0" and ladder[1]["signpost"].startswith("Second problem")
    assert by[12]["problem_no"] == 0 and by[12]["signpost"] == "" and by[10]["purpose"] == "reveal" and by[10]["problem_no"] == 0
    assert by[1]["count"] == 21 and by[1]["count_was"] is None and by[4]["count"] == 21 and by[5]["count"] == 10.5 and by[5]["count_was"] == 21 and by[12]["count"] == 3        # carried forward
    mid, low = full["midpoint"]["beat"], full["low_point"]["beat"]
    assert by[mid]["role"] == "midpoint" and by[low]["role"] == "low_point" and by[1]["act"] == "setup" and by[12]["act"] == "climax" and by[mid + 1]["act"] == "complications"
    assert by[3]["plant"] == ["Cake"] and by[7]["pay"] == ["Key"] and by[12]["pay"] == ["Cake"]
    assert by[5]["rule_uses"] == ["R1"] and by[full["secret"]["method_beat"]]["method"] == "count the marks"
    assert all(x["purpose"] != "problem" for x in [by[full["secret"]["method_beat"]]]) or by[full["secret"]["method_beat"]]["purpose"] in ("clue", "reveal")


def test_a_plan_with_unsolved_problems_or_no_ending_turn_is_sent_back():
    b = architect.clean_bible(bible_out(), 1, 12)
    bare = architect.clean_beats([m.BeatIn(event="e", problem="p", purpose="problem") for _ in range(12)], b, 1, 12)
    assert any("solved_by" in x for x in architect.problems(b, bare, 12))
    one = architect.clean_beats([m.BeatIn(event="e", problem="p", purpose="problem", fact="water") for _ in range(12)], b, 1, 12)
    assert architect.problems(b, one, 12) == [] or all("solved_by" not in x for x in architect.problems(b, one, 12))                    # a beat that carries a fact is solved by it
    weak = architect.clean_bible(bible_out(ending={"outcome": "o"}, opening={}, secret={"truth": "T", "clues": []}), 1, 12)
    assert len(architect.bible_problems(weak)) == 3 and architect.bible_problems(b) == []


def test_audit_says_in_plain_words_what_the_plan_lacks():
    assert architect.audit({}) == []
    old = {"beats": [{"n": 1, "purpose": "problem"}], "secret": {}, "rules": []}
    assert [a["key"] for a in architect.audit(old)] == ["old"]
    thin = architect.decorate({**architect.clean_bible(bible_out(opening={}, ending={"outcome": "o"}, countdown={}, objects=[], midpoint={}, low_point={}, secret={"truth": "T", "clues": []}, rules=[{"name": "R", "text": "x", "beat": 2}]), 1, 12),
                               "beats": architect.clean_beats([m.BeatIn(event="e", problem="p", purpose="problem") for _ in range(12)], {}, 1, 12)})
    keys = {a["key"] for a in architect.audit(thin)}
    assert {"opening", "inversion", "method", "countdown", "ladder", "midpoint", "low_point", "objects", "policy", "uses"} <= keys
    good = beats12(architect.clean_bible(bible_out(), 1, 12))
    assert not [a for a in architect.audit(good) if a["level"] == "warn"]


def test_the_writer_is_told_the_opening_the_number_the_signpost_and_the_objects(client):
    c = client
    pid = new_story(c)
    c.post(f"/api/sim/{pid}/start")
    wait(c, pid)
    w = c.fake.last("sm_write")["user"]
    assert "Open on this: Stay in your room, says the intercom." in w and "locks the door and waits for the voice" in w
    assert "Say the number out loud in the narration: Water: 22 days" in w and "signpost" not in w                             # signposts are off in a story that did not ask for them
    p = c.fake.last("sm_plan")["user"]
    assert "What solves the problem: pallets stacked against the doors hold" in p and "The number on screen: Water: 22 days" in p
    c.patch(f"/api/sim/{pid}", json={"settings": {"signposts": True}})
    c.post(f"/api/sim/{pid}/chapters", json={"kind": "auto"})
    wait(c, pid)
    w2 = c.fake.last("sm_write")["user"]
    assert 'as a signpost, in these words or very close: "Second problem: Beat 2"' in w2
    assert "Put the object The cake in the scene" in w2 and "Use Rule one again" not in w2
    bible = store.bible(pid)
    assert "Show the person learning Staff list (never announced by the narrator: show it by what happens (the manager puts the cook by the door))" in architect.write_block(bible, architect.beat_for(bible, 4))
    last = architect.write_block(bible, architect.beat_for(bible, 12))
    assert "Turn the beginning around" in last and "walks out instead of waiting" in last and "Pay off the object The cake: it is eaten at the end" in last
    mid = architect.write_block(bible, architect.beat_for(bible, bible["midpoint"]["beat"]), True)
    assert "This is the midpoint: the lights go out for good" in mid and "Use Rule one again and repeat its words as a refrain: Move when the noise moves." in mid
    meth = architect.write_block(bible, architect.beat_for(bible, bible["secret"]["method_beat"]))
    assert "finding out by this method" in meth and "turns the list of intercom orders into a map" in meth and "a step short of the whole truth" in meth
    reveal = architect.write_block(bible, architect.beat_for(bible, bible["secret"]["reveal_beat"]))
    assert "Name the lie everyone has believed: The intercom says help is coming at dawn." in reveal
    assert "Must put the object The cake in the scene" in architect.referee_block(bible, architect.beat_for(bible, 2))


def test_story_health_notices_a_missing_number_object_signpost_and_a_weak_ending(client):
    c = client
    pid = new_story(c)
    c.patch(f"/api/sim/{pid}", json={"settings": {"signposts": True}})
    c.post(f"/api/sim/{pid}/start")
    wait(c, pid)
    row = detail(c, pid)["health"]["plan"]["beats"][0]
    assert row["count_missing"] is True and row["signpost_missing"] is True
    assert health.has_number("There are 22 days left", 22) and health.has_number("Twenty-two days", 22) and health.has_number("twenty two days", 22) and health.has_number("2,200 gallons", 2200) and not health.has_number("There are 220", 22)
    good = words(200) + " First problem: the pallets. Water: 22 days left. The intercom knows which aisle you are in."
    c.fake.answers["sm_write"] = lambda user, k: {"title": "x", "prose": good, "story_time": "Day 2"}
    c.post(f"/api/sim/{pid}/chapters", json={"kind": "auto"})
    wait(c, pid)
    pl = detail(c, pid)["health"]["plan"]
    assert pl["beats"][-1]["count_missing"] is False and pl["ending"] is None                                                  # the ending is only judged once the last chapter exists
    texts = [v["text"] for v in detail(c, pid)["health"]["verdicts"]]
    assert any("never says the number on screen" in t for t in texts)
    bible = store.bible(pid)
    store.set_bible(pid, {**bible, "beats": [b for b in bible["beats"]]})


def test_the_plan_view_shows_the_audit_and_hides_the_method_until_the_secret_is_shown(client):
    c = client
    pid = new_story(c)
    c.post(f"/api/sim/{pid}/start")
    wait(c, pid)
    pl = detail(c, pid)["plan"]
    assert pl["audit"] is not None and all("method" not in str(b.get("method")) for b in pl["beats"]) and all(b["method"] == "" for b in pl["beats"])
    assert all(b["purpose"] != "clue" for b in pl["beats"])                                                                    # the method beat does not give itself away
    full = c.get(f"/api/sim/{pid}/bible?spoilers=true").json()["plan"]
    assert any(b["method"] for b in full["beats"]) and full["countdown"]["name"] == "Water" and full["objects"][0]["name"] == "The cake"
    assert c.put(f"/api/sim/{pid}/bible", json={"countdown": {"name": "Water", "unit": "days", "steps": [{"beat": 1, "value": 30, "note": ""}, {"beat": 6, "value": 5, "note": ""}]}}).status_code == 200
    assert architect.beat_for(store.bible(pid), 1)["count"] == 30 and architect.beat_for(store.bible(pid), 7)["count"] == 5                       # editing the backbone recomputes the beats
    assert c.put(f"/api/sim/{pid}/bible/beats/2", json={"solved_by": "a ladder"}).status_code == 200 and architect.beat_for(store.bible(pid), 2)["solved_by"] == "a ladder"


def test_four_secrets_are_proposed_and_the_one_picked_reaches_the_plan(client):
    c = client
    pid = c.post("/api/sim", json={"idea": "A salesman, a supermarket, an outbreak", "template_id": "tp-survival"}).json()["id"]
    c.post(f"/api/sim/{pid}/seed/world", json={})
    wait(c, pid)
    assert c.post(f"/api/sim/{pid}/secrets", json={}).status_code == 200
    wait(c, pid)
    opts = detail(c, pid)["secret_options"]
    assert len(opts) == 4 and opts[0]["kind"] == "authority_lie" and opts[0]["lie"] and opts[0]["found_by"] and detail(c, pid)["plan"] is None        # five came back, four are kept
    pick = {**opts[2], "truth": "The manager sold the keys."}
    c.post(f"/api/sim/{pid}/seed/bible", json={"instruction": "", "secret": pick})
    wait(c, pid)
    u = c.fake.last("sm_bible")["user"]
    assert "THE OWNER CHOSE THIS SECRET" in u and "<owner>" in u and "The manager sold the keys." in u and "found out by: count the radio calls" in u
    assert "candidates" not in store.bible(pid) and architect.has_plan(store.bible(pid))
    assert "THE OWNER CHOSE" not in (c.fake.calls[-1]["user"] if c.fake.calls[-1]["task"] == "sm_beats" else "")


def test_a_long_film_is_planned_in_parts_with_one_ending(client):
    c = client
    pid = c.post("/api/sim", json={"idea": "x", "template_id": ""}).json()["id"]
    c.patch(f"/api/sim/{pid}", json={"settings": {"length": 40, "plan": True}})
    c.post(f"/api/sim/{pid}/seed/all", json={})
    wait(c, pid)
    assert c.fake.count("sm_beats") == 4 and architect.chunk_sizes(40) == [10, 10, 10, 10] and architect.chunk_sizes(12) == [12] and architect.chunk_sizes(13) == [7, 6] and sum(architect.chunk_sizes(99)) == 99
    calls = [x for x in c.fake.calls if x["task"] == "sm_beats"]
    assert "Write exactly 10 beats numbered 1 to 10" in calls[0]["user"] and "BEATS ALREADY WRITTEN" not in calls[0]["user"]
    assert "Write exactly 10 beats numbered 11 to 20" in calls[1]["user"] and "BEATS ALREADY WRITTEN" in calls[1]["user"] and "10 Day 10: Beat 10" in calls[1]["user"]
    assert "beat 40 is the ending" in calls[0]["user"]
    b = store.bible(pid)
    assert [x["n"] for x in b["beats"]] == list(range(1, 41)) and [x["purpose"] for x in b["beats"]].count("ending") == 1 and b["beats"][-1]["purpose"] == "ending"
    nums = [x["problem_no"] for x in b["beats"] if x["problem_no"]]
    assert nums == list(range(1, len(nums) + 1))                                                                                        # the ladder is numbered across the parts
    assert len(b["rules"]) <= 8 and 18 <= b["midpoint"]["beat"] <= 25 and b["secret"]["reveal_beat"] >= 24


def test_a_plan_from_before_the_framework_still_works_and_says_so(client):
    c = client
    pid = new_story(c)
    b = store.bible(pid)
    old = {k: v for k, v in b.items() if k not in ("opening", "countdown", "objects", "midpoint", "low_point")}
    old["beats"] = [{k: v for k, v in x.items() if k in ("n", "label", "time", "title", "event", "problem", "turn", "hook", "purpose", "challenge", "clues", "rule", "motif", "fact")} for x in b["beats"]]
    store.set_bible(pid, old)
    assert [a["key"] for a in detail(c, pid)["plan"]["audit"]] == ["old"]
    c.post(f"/api/sim/{pid}/start")
    wait(c, pid)
    w = c.fake.last("sm_write")["user"]
    assert "## STORY PLAN FOR THE WRITER" in w and "Open on this" not in w and "number out loud" not in w
