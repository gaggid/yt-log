"""Things through the engine and the API with the scripted model: a make that flows through a chapter, thinking step-up, undo, owner edits, instructions that grant, take and unbind, setup of skills and craft."""
from sim import store, think
from test_sim_api import client, new_story, wait  # noqa: F401


def start(c, dice=False):
    pid = new_story(c)
    c.patch(f"/api/sim/{pid}", json={"settings": {"dice": dice}})
    c.post(f"/api/sim/{pid}/start")
    wait(c, pid)
    return pid


def make_plan(c, risks):
    def plan(user, n):
        p = c.fake._sm_plan(user)
        p["risks"] = [{"who": p["focus"][0], **r} for r in risks]
        return p
    c.fake.answers["sm_plan"] = plan


def detail(c, pid):
    return c.get(f"/api/sim/{pid}").json()


def bean_alarm(who_key="Ravi"):
    return {"op": "craft", "who": who_key, "target": "Bean can alarm", "qty": 1, "parts": ["Canned beans"], "tools": [], "skill": "improvising", "props": {"uses": 2}, "why": "cans on a string"}


def test_setup_gives_everyone_skills_the_world_a_craft_line_and_a_craft_rule_group(client):
    c = client
    pid = new_story(c)
    d = detail(c, pid)
    assert all(e["skills"] for e in d["entities"] if e["kind"] == "character")
    assert d["world"]["craft"].startswith("Makeshift")
    assert any(g["grp"] == "craft" for g in d["guidelines"])
    assert d["carry"]["default"] == 8
    assert c.post(f"/api/sim/{pid}/guidelines", json={"grp": "craft", "text": "No electronics."}).status_code == 200
    assert c.patch(f"/api/sim/{pid}", json={"settings": {"carry_limit": 3}}).status_code == 200 and detail(c, pid)["carry"]["default"] == 3
    assert c.post(f"/api/sim/{pid}/entities", json={"kind": "character", "name": "Zed", "data": {"skills": ["welding"], "carry": 12}}).status_code == 200
    assert detail(c, pid)["carry"]["people"]["Zed"] == 12


def test_a_make_runs_through_a_chapter_and_shows_in_the_next_prompts(client):
    c = client
    pid = start(c)
    make_plan(c, [{"act": "rig an alarm from cans", "kind": "make", "craft": {"makes": "Bean can alarm", "parts": ["Canned beans"], "tools": [], "skill": "improvising", "reasoning": "cans on a string rattle"}}])
    craft = {"sm_delta": lambda user, n: {"ops": [bean_alarm(next(x for x in ("Ravi", "Meera", "Dev", "Sana") if f"{x} (alive)" in user))]}}
    c.fake.answers.update(craft)
    assert c.post(f"/api/sim/{pid}/chapters", json={"kind": "text", "text": "make an alarm from the cans", "who": "Ravi"}).status_code == 200
    wait(c, pid)
    d = detail(c, pid)
    ch = d["chapters"][-1]
    made = [a for a in ch["applied"] if a["op"] == "craft"]
    assert made and "made Bean can alarm" in made[0]["text"] and made[0]["undo"]
    items = next(v for k, v in ch["state_after"]["trackers"].items() if "Bean can alarm" in v) if any("Bean can alarm" in v for v in ch["state_after"]["trackers"].values() if isinstance(v, dict)) else {}
    assert items["Bean can alarm"]["props"]["uses"] == 2 and items["Canned beans"]["qty"] == 5
    assert "Bean can alarm" in ch["state_after"]["recipes"]
    assert ch["plan"]["risks"][0]["craft"]["reasoning"] == "cans on a string rattle" and ch["rolls"][0]["kind"] == "make"
    # thinking steps up for a chapter about making something
    assert c.fake.last("sm_plan")["params"]["thinking_budget"] == int(think.BUDGET["sm_plan"] * think.BOOST_FACTOR)
    assert c.fake.last("sm_delta")["params"]["thinking_budget"] == int(think.BUDGET["sm_delta"] * think.BOOST_FACTOR)
    # the recipe and the new thing reach the next chapter's prompts
    c.fake.answers.pop("sm_plan"), c.fake.answers.pop("sm_delta")
    c.post(f"/api/sim/{pid}/chapters", json={"kind": "auto"})
    wait(c, pid)
    assert "## RECIPES KNOWN\n- Bean can alarm" in c.fake.last("sm_plan")["user"] and "Bean can alarm x1" in c.fake.last("sm_write")["user"]
    assert c.fake.last("sm_plan")["params"]["thinking_budget"] == think.BUDGET["sm_plan"]                      # an ordinary chapter: no step-up


def test_a_failed_roll_blocks_a_find_and_a_make_with_dice_on(client):
    c = client
    pid = start(c, dice=True)
    make_plan(c, [{"act": "search the shelves for a flare gun", "kind": "search"}])
    c.fake.answers["sm_delta"] = lambda user, n: {"ops": [{"op": "discover", "kind": "item", "target": "Flare gun", "where": "Aisle One", "who": "Ravi", "why": "a locker"}]}
    c.post(f"/api/sim/{pid}/chapters", json={"kind": "text", "text": "look around", "who": "Ravi"})
    wait(c, pid)
    ch = detail(c, pid)["chapters"][-1]
    tier = ch["rolls"][0]["tier"]
    found = any(a["op"] == "discover" for a in ch["applied"])
    assert found == (tier in ("great", "success", "partial"))
    if not found:
        assert any(d["op"] == "discover" for d in ch["dropped"])


def test_undo_and_owner_edits(client):
    c = client
    pid = start(c)
    make_plan(c, [{"act": "rig an alarm from cans", "kind": "make", "craft": {"makes": "Bean can alarm", "parts": ["Canned beans"]}}])
    c.fake.answers["sm_delta"] = lambda user, n: {"ops": [bean_alarm(next(x for x in ("Ravi", "Meera", "Dev", "Sana") if f"{x} (alive)" in user))]}
    c.post(f"/api/sim/{pid}/chapters", json={"kind": "text", "text": "make something", "who": "Ravi"})
    wait(c, pid)
    c.post(f"/api/sim/{pid}/chapters", json={"kind": "auto"})                                           # a later chapter, which becomes stale when the first is changed
    wait(c, pid)
    d = detail(c, pid)
    first = d["chapters"][1]
    idx = next(i for i, a in enumerate(first["applied"]) if a["op"] == "craft")
    assert c.post(f"/api/sim/{pid}/chapters/{first['id']}/undo", json={"index": 99}).status_code == 400
    r = c.post(f"/api/sim/{pid}/chapters/{first['id']}/undo", json={"index": idx})
    assert r.status_code == 200 and r.json()["stale"] >= 1
    d2 = detail(c, pid)
    st = d2["chapters"][1]["state_after"]
    assert not any("Bean can alarm" in v for v in st["trackers"].values() if isinstance(v, dict)) and "Bean can alarm" not in st["recipes"]
    assert any(a.get("undone") for a in d2["chapters"][1]["applied"]) and d2["chapters"][2]["flags"].get("stale")
    assert c.post(f"/api/sim/{pid}/chapters/{first['id']}/undo", json={"index": idx}).status_code == 400   # only once
    # owner edits act on the story as it stands now
    r = c.post(f"/api/sim/{pid}/things", json={"action": {"do": "set_thing", "name": "Lantern", "fields": {"at": "Meera", "uses": 4, "bound_to": "Meera"}}})
    assert r.status_code == 200
    head = detail(c, pid)["chapters"][-1]
    lan = next(v["Lantern"] for v in head["state_after"]["trackers"].values() if isinstance(v, dict) and "Lantern" in v)
    assert lan["bound_to"] == "Meera" and lan["props"]["uses"] == 4 and head["applied"][-1]["op"] == "owner_edit"
    assert c.post(f"/api/sim/{pid}/things", json={"action": {"do": "set_thing", "name": "Lantern", "fields": {"at": "Moon"}}}).status_code == 400
    assert c.post(f"/api/sim/{pid}/things", json={"action": {"do": "add_skill", "who": "Dev", "skill": "driving"}}).status_code == 200
    assert "driving" in detail(c, pid)["state"]["entities"]["Dev"]["skills"]


def test_instructions_can_grant_take_and_unbind_things(client):
    c = client
    pid = start(c)
    bad = c.post(f"/api/sim/{pid}/directives", json={"kind": "grant", "text": "x", "timing": {"mode": "next"}, "thing": {"item": ""}})
    assert bad.status_code == 400
    assert c.post(f"/api/sim/{pid}/directives", json={"kind": "grant", "text": "Meera finds a flare gun", "timing": {"mode": "next"}, "thing": {"item": "Flare gun", "to": "Meera"}}).status_code == 200
    c.post(f"/api/sim/{pid}/chapters", json={"kind": "auto"})
    wait(c, pid)
    ch = detail(c, pid)["chapters"][-1]
    assert any("Flare gun" in a["text"] for a in ch["applied"]), ch["applied"]
    inv = next(v for v in ch["state_after"]["trackers"].values() if isinstance(v, dict) and "Flare gun" in v)
    assert inv["Flare gun"]["at"] == "Meera"
    assert c.post(f"/api/sim/{pid}/things", json={"action": {"do": "set_thing", "name": "Flare gun", "fields": {"bound_to": "Meera"}}}).status_code == 200
    c.post(f"/api/sim/{pid}/directives", json={"kind": "take", "text": "Raiders grab the flare gun", "timing": {"mode": "next"}, "thing": {"item": "Flare gun", "to": "Loading Bay"}})
    c.post(f"/api/sim/{pid}/chapters", json={"kind": "auto"})
    wait(c, pid)
    ch = detail(c, pid)["chapters"][-1]
    inv = next(v for v in ch["state_after"]["trackers"].values() if isinstance(v, dict) and "Flare gun" in v)
    assert inv["Flare gun"]["at"] == "Loading Bay"                                                         # an instruction beats the binding
    c.post(f"/api/sim/{pid}/directives", json={"kind": "unbind", "text": "Meera lets go", "timing": {"mode": "next"}, "thing": {"item": "Flare gun"}})
    c.post(f"/api/sim/{pid}/chapters", json={"kind": "auto"})
    wait(c, pid)
    ch = detail(c, pid)["chapters"][-1]
    inv = next(v for v in ch["state_after"]["trackers"].values() if isinstance(v, dict) and "Flare gun" in v)
    assert inv["Flare gun"]["bound_to"] == ""


def test_the_prompts_know_the_new_rules(client):
    c = client
    pid = start(c)
    assert "kind" in c.fake.last("sm_plan")["system"] and "craft" in c.fake.last("sm_plan")["system"]
    assert "discover" in c.fake.last("sm_delta")["system"] and "item_give" in c.fake.last("sm_delta")["system"]
    assert "nowhere" in c.fake.last("sm_referee")["system"] and "condition" in c.fake.last("sm_referee")["system"]
    assert "recipe" in c.fake.last("sm_archive")["system"]
    assert "craft" in c.fake.last("sm_world")["system"] or "craft" in c.fake.last("sm_rules")["system"]
    assert "skills" in c.fake.last("sm_cast")["system"]
    assert "Making and finding here" in c.fake.last("sm_plan")["user"]


def test_templates_carry_craft_text_and_carry_limits(client):
    from sim import templates
    c = client
    court = templates.get("tp-courtroom")
    assert court["settings"]["carry_limit"] == 0 and court["craft"] and any(g == "craft" for g, _ in court["rules"])
    pid = c.post("/api/sim", json={"idea": "A trial", "template_id": "tp-courtroom"}).json()["id"]
    d = detail(c, pid)
    assert d["project"]["settings"]["carry_limit"] == 0 and any(g["grp"] == "craft" for g in d["guidelines"])
    assert "Evidence, statements" in templates.hint_text(court)
    surv = c.post("/api/sim", json={"idea": "A shop", "template_id": "tp-survival"}).json()["id"]
    t = c.post(f"/api/sim/{surv}/save-template", json={"name": "Mine"}).json()
    assert store.templates()[-1]["data"]["settings"]["carry_limit"] == 8


def test_things_travel_with_exports_imports_and_duplicates(client):
    c = client
    pid = start(c)
    make_plan(c, [{"act": "rig an alarm from cans", "kind": "make", "craft": {"makes": "Bean can alarm", "parts": ["Canned beans"]}}])
    c.fake.answers["sm_delta"] = lambda user, n: {"ops": [bean_alarm(next(x for x in ("Ravi", "Meera", "Dev", "Sana") if f"{x} (alive)" in user))]}
    c.post(f"/api/sim/{pid}/chapters", json={"kind": "text", "text": "make something", "who": "Ravi"})
    wait(c, pid)
    c.post(f"/api/sim/{pid}/things", json={"action": {"do": "add_skill", "who": "Dev", "skill": "driving"}})
    c.post(f"/api/sim/{pid}/directives", json={"kind": "grant", "text": "x", "timing": {"mode": "next"}, "thing": {"item": "Flare gun", "to": "Meera"}})
    data = c.get(f"/api/sim/{pid}/export?format=story&full=true").json()
    new = c.post("/api/sim/import", json=data).json()["id"]
    d, d0 = detail(c, new), detail(c, pid)
    assert [e["skills"] for e in d["entities"] if e["kind"] == "character"] == [e["skills"] for e in d0["entities"] if e["kind"] == "character"]
    assert d["world"]["craft"] == d0["world"]["craft"] and d["project"]["settings"]["carry_limit"] == 8
    assert "Bean can alarm" in d["chapters"][-1]["state_after"]["recipes"] and "driving" in d["state"]["entities"]["Dev"]["skills"]
    assert any(x["kind"] == "grant" and x["pending"] for x in d["directives"])
    assert d["directives"][-1]["timing"]["thing"]["item"] == "Flare gun"
    j = c.get(f"/api/sim/{pid}/export?format=json").json()
    assert j["cast"][0]["skills"] and any("made Bean can alarm" in t for t in j["chapters"][-1]["things"])
    dup = c.post(f"/api/sim/{pid}/duplicate?full=true").json()["id"]
    assert "Bean can alarm" in detail(c, dup)["chapters"][-1]["state_after"]["recipes"]


def test_a_thing_nobody_found_is_in_no_prompt_and_old_states_still_run(client):
    c = client
    pid = start(c)
    c.fake.answers["sm_delta"] = lambda user, n: {"ops": [{"op": "discover", "kind": "item", "target": "Flare gun", "where": "Aisle One", "who": "Ravi", "why": "a locker"}]}
    c.post(f"/api/sim/{pid}/chapters", json={"kind": "auto"})
    wait(c, pid)
    ch = detail(c, pid)["chapters"][-1]
    assert any(d["op"] == "discover" and "nothing earned it" in d["why"] for d in ch["dropped"])               # no search was rolled, so nothing is found
    c.fake.answers.pop("sm_delta")
    n0 = len(c.fake.calls)
    c.post(f"/api/sim/{pid}/chapters", json={"kind": "auto"})
    wait(c, pid)
    later = [x for x in c.fake.calls[n0:] if x["task"] in ("sm_plan", "sm_delta", "sm_write", "sm_referee", "sm_archive")]
    assert later and not any("Flare gun" in x["user"] for x in later)
    # an old state (saved before things existed) is read as if the new fields were empty
    head = store.path(pid)[-1]
    old = {k: v for k, v in head["state_after"].items() if k not in ("world_add", "recipes")}
    for e in old["entities"].values():
        e.pop("skills", None)
    for t in old["trackers"].values():
        if isinstance(t, dict):
            for i in t.values():
                if isinstance(i, dict) and "qty" in i:
                    for k in ("props", "origin", "bound_to"):
                        i.pop(k, None)
    store.update_chapter(head["id"], state_after=old)
    c.post(f"/api/sim/{pid}/chapters", json={"kind": "auto"})
    wait(c, pid)
    st = detail(c, pid)["chapters"][-1]["state_after"]
    assert st["recipes"] == {} and st["world_add"] == [] and all("skills" in e for e in st["entities"].values())


def test_the_story_goal_steers_the_planner_and_the_options(client):
    c = client
    pid = start(c)
    d = detail(c, pid)
    assert d["world"]["goal"].startswith("Survive until dawn")
    assert "THE STORY IS ABOUT: Survive until dawn" in c.fake.last("sm_plan")["user"] and "THE STORY IS ABOUT" in c.fake.last("sm_archive")["user"]
    assert "put it under strain" in c.fake.last("sm_plan")["system"] and "fail with a real cost" in c.fake.last("sm_plan")["system"]
    assert "never two ways of the same move" in c.fake.last("sm_archive")["system"] and "deal with what the chapter ended on" in c.fake.last("sm_archive")["system"]
    assert "PRESSURE clock or meter" in c.fake.last("sm_trackers")["system"] and "goal" in c.fake.last("sm_world")["system"]
    assert c.patch(f"/api/sim/{pid}", json={"world": {**d["world"], "goal": "Keep Silas alive."}}).status_code == 200 and detail(c, pid)["world"]["goal"] == "Keep Silas alive."
