"""The Story Architect (docs/PLAN_architect.md): the backbone, the beats, chapters that play them, re-planning, stories without a plan."""
from sim import architect, models as m, store
from sim_fakes import words
from test_sim_api import client, new_story, wait  # noqa: F401
from test_sim_things_api import detail


def bible_out(**kw):
    base = {"logline": "L", "pov": "You", "voice": "v", "secret": {"truth": "T", "who": "w", "reveal_beat": 2, "clues": [{"beat": 9, "clue": "late clue"}, {"beat": 1, "clue": "early clue"}]},
            "rules": [{"name": "", "text": "do x", "beat": 99}], "motifs": [{"name": "bell", "first_beat": 1, "payoffs": 5}], "facts": [{"fact": "f", "beat": 3}], "ending": {"outcome": "o"}}
    base.update(kw)
    return m.BibleOut.model_validate(base)


def test_the_backbone_is_repaired_into_a_plan_that_plants_before_it_reveals():
    b = architect.clean_bible(bible_out(), 1, 12)
    assert b["pov"] == "second" and 8 <= b["secret"]["reveal_beat"] <= 12                          # the reveal sits in the last third
    assert all(c["beat"] < b["secret"]["reveal_beat"] for c in b["secret"]["clues"]) and b["secret"]["clues"][0]["clue"] == "early clue"
    assert b["rules"][0]["name"] == "Rule 1" and b["rules"][0]["beat"] == 12 and b["motifs"][0]["payoffs"] == [5]
    beats = [m.BeatIn(event="e", problem="p", purpose="problem") for _ in range(12)]
    out = architect.clean_beats(beats, b, 1, 12)
    assert [x["n"] for x in out] == list(range(1, 13)) and out[-1]["purpose"] == "ending" and out[b["secret"]["reveal_beat"] - 1]["purpose"] == "reveal"
    assert "early clue" in out[0]["clues"] and out[0]["motif"] == "bell" and out[2]["fact"] == "f" and out[11]["rule"] == "Rule 1"
    assert out[0]["label"].startswith("Part 1") and architect.problems(b, out, 12) == []
    assert any("exactly 12" in x for x in architect.problems(b, out[:5], 12)) and any("hidden truth" in x for x in architect.problems({**b, "secret": {**b["secret"], "truth": ""}}, out, 12))
    lab = architect.clean_beats([m.BeatIn(label="Day 5: The Water Heater", event="e", problem="p")], b, 5, 1)[0]
    assert lab["time"] == "Day 5" and lab["title"] == "The Water Heater" and lab["n"] == 5


def test_setup_writes_the_plan_with_one_beat_per_chapter(client):
    c = client
    pid = new_story(c)
    b = store.bible(pid)
    assert architect.has_plan(b) and len(b["beats"]) == 12 and b["beats"][0]["n"] == 1 and b["secret"]["truth"] and b["pov"] == "second"
    assert "The plan covers 12 beats, numbered 1 to 12" in c.fake.last("sm_bible")["user"] and "Write exactly 12 beats numbered 1 to 12" in c.fake.last("sm_beats")["user"]
    p2 = c.post("/api/sim", json={"idea": "x", "template_id": ""}).json()["id"]
    c.patch(f"/api/sim/{p2}", json={"settings": {"length": 8, "plan": False}})
    c.post(f"/api/sim/{p2}/seed/all", json={})
    wait(c, p2)
    assert store.bible(p2) == {}                                                                         # the setting turns the plan off


def test_a_chapter_plays_its_beat_and_the_writer_keeps_the_secret(client):
    c = client
    pid = new_story(c)
    c.post(f"/api/sim/{pid}/start")
    wait(c, pid)
    p = c.fake.last("sm_plan")["user"]
    assert "## STORY PLAN (chapter 1 plays this beat)" in p and "Event: The people secure the doors" in p and "the intercom knows which aisle" in p and "never say or hint it outright" in p
    w = c.fake.last("sm_write")["user"]
    assert "## STORY PLAN FOR THE WRITER" in w and "Point of view: second person" in w and "Voice: Short sentences" in w and "End on: a knock on the shutter" in w and "Never reveal the hidden truth" in w
    assert "HIDDEN TRUTH (must not be revealed" in c.fake.last("sm_referee")["user"]
    assert "## NEXT BEAT" in c.fake.last("sm_archive")["user"] and "Beat 2" in c.fake.last("sm_archive")["user"]
    ch = detail(c, pid)["chapters"][-1]
    assert ch["title"] == "Beat 1" and ch["story_time"] == "Day 1" and ch["flags"]["beat"]["label"] == "Day 1: Beat 1"          # the plan names the chapter and says when it is
    for _ in range(11):                                                                                  # the reveal chapter says the truth out loud; the last one is the ending
        c.post(f"/api/sim/{pid}/chapters", json={"kind": "auto"})
        wait(c, pid)
    reveal = store.bible(pid)["secret"]["reveal_beat"]
    texts = [x["user"] for x in c.fake.calls if x["task"] == "sm_write" and f"This chapter is beat {reveal}:" in x["user"]]
    assert texts and "Reveal the hidden truth here: The voice on the intercom is leaving them behind." in texts[-1]
    last = [x["user"] for x in c.fake.calls if x["task"] == "sm_write" and "This is the ending." in x["user"]]
    assert last and "Closing line: Stay in your room." in last[-1]


def test_a_plan_that_ignores_its_beat_is_sent_back_once(client):
    c = client
    pid = new_story(c)
    n = c.fake.count("sm_plan")
    c.fake.answers["sm_plan"] = lambda user, k: {**c.fake._sm_plan(user), **({"scene": "They wander off to look at the shelves of tea.", "intent": "Browse the tea.", "pressure": "none", "opposition": "nothing"} if k == n + 1 else {})}
    c.post(f"/api/sim/{pid}/start")
    wait(c, pid)
    assert c.fake.count("sm_plan") == n + 2
    assert "secure the doors" in detail(c, pid)["chapters"][-1]["plan"]["scene"]


def test_revealing_the_truth_early_is_a_rule_break(client):
    c = client
    pid = new_story(c)
    c.fake.answers["sm_referee"] = lambda user, k: {"ok": False, "violations": [{"rule": "plan", "quote": "the voice is leaving them", "fix": "do not say it yet"}]}
    c.post(f"/api/sim/{pid}/start")
    wait(c, pid)
    ch = detail(c, pid)["chapters"][-1]
    assert ch["flags"]["referee"] == "broken" and ch["flags"]["rule_break"][0]["rule"] == "plan"


def test_the_players_own_action_rewrites_the_beats_after_this_chapter_but_keeps_the_backbone(client):
    c = client
    pid = new_story(c)
    c.post(f"/api/sim/{pid}/start")
    wait(c, pid)
    before = store.bible(pid)
    n = c.fake.count("sm_beats")
    c.post(f"/api/sim/{pid}/chapters", json={"kind": "option", "option_id": "o1"})
    wait(c, pid)
    assert c.fake.count("sm_beats") == n                                                                  # choosing an offered option keeps the plan
    c.post(f"/api/sim/{pid}/chapters", json={"kind": "text", "text": "barricade the doors with pallets", "who": "Ravi"})
    wait(c, pid)
    assert c.fake.count("sm_beats") == n + 1 and "Write exactly 9 beats numbered 4 to 12" in c.fake.last("sm_beats")["user"]
    assert "WHAT ALREADY HAPPENED" in c.fake.last("sm_beats")["user"] and "keep the hidden truth" in c.fake.last("sm_beats")["user"].lower().replace("keep the hidden truth, rules", "keep the hidden truth")
    after = store.bible(pid)
    assert after["secret"] == before["secret"] and after["ending"] == before["ending"] and len(after["beats"]) == 12 and [b["n"] for b in after["beats"]] == list(range(1, 13))
    assert detail(c, pid)["chapters"][-1]["flags"].get("replanned")
    assert c.post(f"/api/sim/{pid}/seed/bible", json={"instruction": "more menace"}).status_code == 200
    wait(c, pid)
    assert "The plan covers 12 beats, numbered 4 to 15" in c.fake.last("sm_bible")["user"]                  # a plan written for a running story starts at its next chapter


def test_a_story_without_a_plan_runs_exactly_as_before(client):
    c = client
    pid = c.post("/api/sim", json={"idea": "A salesman, a supermarket, an outbreak", "template_id": "tp-survival"}).json()["id"]
    c.patch(f"/api/sim/{pid}", json={"settings": {"plan": False}})
    c.post(f"/api/sim/{pid}/seed/all", json={})
    wait(c, pid)
    c.post(f"/api/sim/{pid}/start")
    wait(c, pid)
    for task in ("sm_plan", "sm_write", "sm_referee", "sm_archive"):
        assert "STORY PLAN" not in c.fake.last(task)["user"] and "NEXT BEAT" not in c.fake.last(task)["user"]
    ch = detail(c, pid)["chapters"][-1]
    assert ch["title"] == "Barricade" and ch["story_time"] == "Day 1, 23:40" and "beat" not in ch["flags"]


def test_the_plan_is_in_the_detail_with_the_secret_hidden_and_can_be_edited(client):
    c = client
    pid = new_story(c)
    c.post(f"/api/sim/{pid}/start")
    wait(c, pid)
    pl = detail(c, pid)["plan"]
    assert pl["logline"] and pl["done"] == 1 and pl["secret"] == {"hidden": True, "clues": 3} and "truth" not in str(pl["secret"])
    assert pl["beats"][0]["status"] == "done" and pl["beats"][1]["status"] == "next" and pl["beats"][2]["status"] == "later"
    assert all(b["clues"] == [] for b in pl["beats"]) and "reveal" not in [b["purpose"] for b in pl["beats"]]                 # no spoilers in the beats either
    full = c.get(f"/api/sim/{pid}/bible?spoilers=true").json()["plan"]
    assert full["secret"]["truth"].startswith("The voice") and any(b["purpose"] == "reveal" for b in full["beats"]) and any(b["clues"] for b in full["beats"])
    assert c.put(f"/api/sim/{pid}/bible", json={"pov": "fourth"}).status_code == 400
    assert c.put(f"/api/sim/{pid}/bible", json={"logline": "New line", "pov": "first", "ending": {"outcome": "They leave", "final_image": "x", "closing_line": "y"}}).status_code == 200
    assert store.bible(pid)["logline"] == "New line" and store.bible(pid)["pov"] == "first" and store.bible(pid)["secret"]["truth"]
    assert c.put(f"/api/sim/{pid}/bible/beats/3", json={"label": "Day 9: The Water Heater", "event": "Drain the tank", "purpose": "problem"}).status_code == 200
    b3 = architect.beat_for(store.bible(pid), 3)
    assert b3["time"] == "Day 9" and b3["title"] == "The Water Heater" and b3["event"] == "Drain the tank"
    assert c.put(f"/api/sim/{pid}/bible/beats/3", json={"purpose": "nonsense"}).status_code == 400 and c.put(f"/api/sim/{pid}/bible/beats/99", json={"event": "x"}).status_code == 404
    n = c.fake.count("sm_beats")
    assert c.post(f"/api/sim/{pid}/replan", json={"instruction": "more menace"}).status_code == 200
    wait(c, pid)
    assert c.fake.count("sm_beats") == n + 1 and "more menace" in c.fake.last("sm_beats")["user"] and len(store.bible(pid)["beats"]) == 12
    assert architect.beat_for(store.bible(pid), 1)["label"] == "Day 1: Beat 1"                                 # the beat already played is kept
    nop = c.post("/api/sim", json={"idea": "x"}).json()["id"]
    assert detail(c, nop)["plan"] is None and c.put(f"/api/sim/{nop}/bible", json={"logline": "x"}).status_code == 400 and c.post(f"/api/sim/{nop}/replan", json={}).status_code == 400


def test_the_plan_travels_with_exports_the_film_template_and_the_chapter_data(client):
    from sim import templates
    c = client
    pid = new_story(c)
    c.post(f"/api/sim/{pid}/start")
    wait(c, pid)
    data = c.get(f"/api/sim/{pid}/export?format=story&full=true").json()
    new = c.post("/api/sim/import", json=data).json()["id"]
    assert store.bible(new) == store.bible(pid)
    dup = c.post(f"/api/sim/{pid}/duplicate?full=false").json()["id"]
    assert store.bible(dup)["secret"] == store.bible(pid)["secret"]
    j = c.get(f"/api/sim/{pid}/export?format=json").json()
    assert j["plan"]["facts"] and j["plan"]["ending"]["closing_line"] == "Stay in your room." and j["chapters"][0]["beat"] == "Day 1: Beat 1" and "secret" not in j["plan"]
    film = templates.get("tp-film")
    assert film["settings"]["length"] == 12 and film["settings"]["chapter_words"] == 160 and film["settings"]["plan"] and 'as "you"' in templates.hint_text(film)
    f = c.post("/api/sim", json={"idea": "A student locked in a school", "template_id": "tp-film"}).json()["id"]
    d = detail(c, f)
    assert d["project"]["settings"]["chapter_words"] == 160 and d["project"]["settings"]["length"] == 12 and any("second person" in g["text"] for g in d["guidelines"])
    js = open("static/sim.js", encoding="utf-8").read()
    assert "drawPlan" in js and "Show the secret" in js and "Write the story plan with AI" in js and "Write a story plan at setup" in js


def test_health_notices_a_chapter_that_did_not_play_its_beat(client):
    from sim_fakes import words
    c = client
    pid = new_story(c)
    c.post(f"/api/sim/{pid}/start")
    wait(c, pid)
    h = detail(c, pid)["health"]
    assert h["plan"]["total"] == 12 and h["plan"]["beats"][0]["hit"] is False and h["plan"]["beats"][0]["clues_missing"]                  # the fake prose says nothing about the beat
    assert any("did not play its beat" in v["text"] for v in h["verdicts"]) and any("clue planted in beat 1" in v["text"] for v in h["verdicts"])
    good = words(300) + " They secure the doors while the noise outside grows. The intercom knows which aisle you are in. Pallets block the doors."
    c.fake.answers["sm_write"] = lambda user, k: {"title": "x", "prose": good, "story_time": "Day 2"}
    c.post(f"/api/sim/{pid}/chapters", json={"kind": "auto"})
    wait(c, pid)
    row = detail(c, pid)["health"]["plan"]["beats"][-1]
    assert row["n"] == 2 and row["hit"] is True


def test_clues_written_as_objects_are_read_as_text_and_the_prompts_ask_for_grounded_plans():
    from sim import prompts as P
    b = m.BeatIn.model_validate({"event": "e", "clues": [{"beat": 2, "clue": "a pencil rolls"}, "a plain clue", {"text": "from text"}, {}]})
    assert b.clues == ["a pencil rolls", "a plain clue", "from text"]
    out = architect.clean_beats([b], {"secret": {"clues": [{"beat": 1, "clue": "a pencil rolls"}]}}, 1, 1)[0]
    assert out["clues"] == ["a pencil rolls", "a plain clue", "from text"]                      # the backbone's own clue is not added twice
    assert "not out of a new supernatural, scientific or cosmic explanation" in P.BIBLE and "Never invent science" in P.BIBLE and "hidden in plain sight" in P.BIBLE
    assert "never a crowd" in P.CAST and "concrete situation with amounts and a deadline" in P.BEATS


def test_words_of_the_model_about_its_own_task_are_kept_out_of_the_story(client):
    from sim import engine
    from sim_fakes import words
    assert engine.meta_text('"I can provide the knowledge, but I must stop reasoning and give the final answer now." Mr. Thorne sighs.')
    assert engine.meta_text("The word count of this chapter is fine.") and not engine.meta_text("The door held. Nobody spoke.")
    assert engine.strip_meta("The door held. I must stop reasoning and give the final answer now. Nobody spoke.") == "The door held. Nobody spoke."
    c = client
    pid = new_story(c)
    bad = words(340) + ' "I must stop reasoning and give the final answer now." Footsteps.'
    n = c.fake.count("sm_write")
    c.fake.answers["sm_write"] = lambda user, k: {"title": "x", "prose": bad if k <= n + 2 else words(340) + " Footsteps.", "story_time": "Day 1"}
    c.post(f"/api/sim/{pid}/start")
    wait(c, pid)
    assert "final answer" not in detail(c, pid)["chapters"][-1]["prose"] and c.fake.count("sm_write") >= n + 2


def test_a_chapter_full_of_stock_words_is_sent_back_once(client):
    from sim import engine
    from sim_fakes import words
    assert engine.stock_words("The heavy door, a heavy sound, a rhythmic thrum.") == ["heavy", "heavy", "rhythmic", "thrum"] and engine.stock_words("The door held.") == []
    c = client
    pid = new_story(c)
    n = c.fake.count("sm_write")
    stock = words(340) + " The heavy door. A heavy sound. A rhythmic thrum."
    c.fake.answers["sm_write"] = lambda user, k: {"title": "x", "prose": stock if k == n + 1 else words(340) + " The door held.", "story_time": "Day 1"}
    c.post(f"/api/sim/{pid}/start")
    wait(c, pid)
    assert c.fake.count("sm_write") == n + 2 and "thrum" not in detail(c, pid)["chapters"][-1]["prose"]
    assert "stock words" in __import__("sim.prompts", fromlist=["WRITE"]).WRITE


def test_the_optional_polish_pass_keeps_the_original_and_drops_a_bad_rewrite(client):
    from sim_fakes import words
    c = client
    pid = new_story(c)
    c.post(f"/api/sim/{pid}/start")
    wait(c, pid)
    assert c.fake.count("sm_polish") == 0 and not detail(c, pid)["chapters"][-1]["flags"].get("polished")                       # off by default
    c.patch(f"/api/sim/{pid}", json={"settings": {"polish": True}})
    c.post(f"/api/sim/{pid}/chapters", json={"kind": "auto"})
    wait(c, pid)
    ch = detail(c, pid)["chapters"][-1]
    assert c.fake.count("sm_polish") == 1 and ch["prose"].startswith("polished ") and ch["flags"]["polished"] and ch["flags"]["prose_before_polish"].startswith("w0 ")
    u = c.fake.last("sm_polish")["user"]
    assert "VOICE: Short sentences" in u and "BEAT: Day 2: Beat 2" in u and "CHAPTER (350 words)" in u
    c.fake.answers["sm_polish"] = lambda user, k: {"title": "x", "prose": "far too short", "story_time": "Day 1"}                  # a rewrite that cuts the chapter is dropped
    c.post(f"/api/sim/{pid}/chapters", json={"kind": "auto"})
    wait(c, pid)
    ch = detail(c, pid)["chapters"][-1]
    assert ch["prose"].startswith("w0 ") and ch["flags"]["polished"] is False
    c.fake.answers["sm_polish"] = lambda user, k: {"title": "x", "prose": words(340) + " I must stop reasoning and give the final answer now.", "story_time": "Day 1"}
    c.post(f"/api/sim/{pid}/chapters", json={"kind": "auto"})
    wait(c, pid)
    assert "final answer" not in detail(c, pid)["chapters"][-1]["prose"]
    from sim import templates
    assert templates.get("tp-film")["settings"]["polish"] is True
    assert "story editor" in __import__("sim.prompts", fromlist=["POLISH"]).POLISH
    assert "Polish every chapter" in open("static/sim.js", encoding="utf-8").read()
