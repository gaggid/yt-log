"""Audit task 1.6: private victims and not-yet-convicted people are renamed in everything a model reads, and a crime is never stated as plain fact."""
from story2 import planner, safety

PUBLIC = {"people": [
    {"name": "Chavi Lal Verma", "role": "Murder suspect and fugitive"}, {"name": "Geeta Suri", "role": "Landlady and murder victim"},
    {"name": "Montu", "role": "Geeta Suri's son and murder victim"}, {"name": "Manmeet Malik", "role": "Inspector"},
    {"name": "Pradeep Das", "role": "Retired scientist and victim of the scam"}, {"name": "Amarjeet Suri", "role": "Owner of the house"}],
    "overview": "Chavi Lal Verma attacked Geeta Suri. Montu survived. Inspector Manmeet Malik traced Verma.", "chronology": [{"what": "Verma fled; Suri family called police"}]}


def test_classify_by_role():
    kinds = {p["name"]: safety.classify(p) for p in PUBLIC["people"]}
    assert kinds == {"Chavi Lal Verma": "suspect", "Geeta Suri": "victim", "Montu": "victim", "Manmeet Malik": "official", "Pradeep Das": "victim", "Amarjeet Suri": "other"}


def test_default_map_renames_victims_and_suspects_not_officials():
    m = safety.suggest_name_map(PUBLIC)
    assert set(m) == {"Chavi Lal Verma", "Geeta Suri", "Montu", "Pradeep Das"}
    assert m["Geeta Suri"] in safety.NAMES_F and m["Chavi Lal Verma"] in safety.NAMES_M and m["Montu"] in safety.NAMES_M
    assert safety.suggest_name_map(PUBLIC) == m                                    # the same story always gets the same names
    assert set(safety.suggest_name_map(PUBLIC, "victims")) == {"Geeta Suri", "Montu", "Pradeep Das"}
    assert safety.suggest_name_map(PUBLIC, "off") == {}


def test_apply_names_replaces_full_names_and_parts_everywhere():
    m = {"Chavi Lal Verma": "Mahesh", "Geeta Suri": "Sunita", "Montu": "Rakesh"}
    out = safety.apply_names(PUBLIC, m)
    text = str(out)
    assert "Mahesh attacked Sunita" in text and "Rakesh survived" in text and "traced Mahesh" in text      # "Verma" alone is also hidden
    assert "Suri" not in text.replace("Amarjeet Suri", "")                              # the surname of the renamed victim is gone ("The Suri Home" becomes "The Sunita Home")
    assert "Manmeet Malik" in text                                                      # an official keeps their name
    assert safety.apply_names("Geeta Suri's home", m) == "Sunita's home"
    assert safety.apply_names("मोंटू", m) == "मोंटू"


def test_real_names_still_present_are_found():
    m = {"Geeta Suri": "Sunita"}
    assert safety.real_names_in(["Sunita ghar gayi", "Geeta ne kaha"], m) == ["Geeta"]
    assert safety.real_names_in(["Sunita"], m) == []


def test_accusations_need_an_attribution():
    said = safety.accusations(["उसने Geeta को मार दिया.", "पुलिस के मुताबिक उसने Geeta को मार दिया.", "वह शहर छोड़कर चला गया.", "He stole five lakh rupees.", "Police say he stole five lakh rupees."])
    assert said == ["उसने Geeta को मार दिया.", "He stole five lakh rupees."]
    assert safety.accusations(["पुलिस के मुताबिक वह घर में घुसा. उसने Geeta को मार दिया."]) == []          # the attribution covers the next sentence
    assert len(safety.accusations(["पुलिस के मुताबिक वह घर में घुसा. फिर कुछ नहीं हुआ. उसने Geeta को मार दिया."])) == 1


def test_story_for_applies_the_plan_name_map_only_when_there_is_one(env):
    from test_phase2a import approved_story
    pid, cid = approved_story(env)
    plan = planner.create_plan(cid, minutes=2)
    assert "name_map" not in plan["settings"]
    story = planner._story_for(plan)
    assert story["public"]["overview"]
    plan["settings"]["name_map"] = {"Ada": "Sunita"}
    assert "Ada" not in str(planner._story_for(plan)["public"]) and "Sunita" in str(planner._story_for(plan)["public"])
    nm = planner.ensure_name_map(plan["id"])
    assert planner.get_plan(plan["id"])["settings"]["anonymise"] == "victims_and_suspects" and nm == planner.get_plan(plan["id"])["settings"]["name_map"]
    assert planner.ensure_name_map(plan["id"]) == nm                                  # a second call leaves the map (and the owner's edits) alone
