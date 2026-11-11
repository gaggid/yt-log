"""The storyboard check (shorts/lint.py): the contradictions found in the audit of sh-16824387, fixed in code, wired into planning, auto-run, the checks and the API."""
import asyncio
import copy

import pytest
from fastapi.testclient import TestClient

import config
from shorts_fakes import FakeChat, png_bytes
from story import settings as settings_mod

from shorts import auto, checks, clips, lint, planner, stillwriter, stills, store

S = {**settings_mod.DEFAULTS, "base_url": "http://gw/v1", "retry_backoff_s": 0}


def run(coro):
    return asyncio.run(coro)


def make_short(lint_on=True, **settings):
    s = store.create("Audit", "keyframe", {"kind": "idea", "text": "a family and their money", "candidate_id": "", "facts": ""}, {"storyboard_lint": lint_on, **settings})
    s["plan"] = {"title": "t", "logline": "l", "place": "A modern, bright Indian living room with warm wooden furniture and soft daylight.", "look": "painted", "character": "",
                 "subjects": [
                     {"name": "Middle-class Indian family", "kind": "group", "visual": "A young Indian couple in casual cotton clothes on a sofa."},
                     {"name": "Smartphone", "kind": "product", "visual": "A premium smartphone with a glowing screen."},
                     {"name": "Indian Rupees", "kind": "object", "visual": "A large pile of 500 and 2000 Rupee notes and shiny gold coins on a polished wooden table."},
                     {"name": "Wealthy Indian man", "kind": "person", "visual": "A man in his 40s in a silk kurta with a gold watch."},
                     {"name": "Indian street market", "kind": "place", "visual": "A vibrant, crowded Indian market with colorful cloth stalls."},
                 ]}
    s["beats"] = [{"id": "b1", "name": "One", "feeling": "x", "tag": "", "sentences": [{"text": "line one", "tag": ""}], "shot_ids": ["s1", "s2", "s3"]}]
    s["shots"] = [
        {"id": "s1", "beat": "b1", "prompt": "idea", "seconds": 2.0, "camera": "static", "subjects": ["Middle-class Indian family (group)"], "setting": "", "character": False, "cast": [],
         "still": "Wide shot of one middle-class Indian family of three people sitting on one sofa in a bright living room. One person holds one smartphone in the center.", "must_show": ["three people on one sofa"]},
        {"id": "s2", "beat": "b1", "prompt": "idea", "seconds": 2.0, "camera": "static", "subjects": ["Wealthy Indian man", "Indian Rupees"], "setting": "Indian street market", "character": False, "cast": [],
         "still": "Low-angle close-up of one wealthy Indian man in one plush chair. The man faces forward. One gold watch is on his left wrist.", "must_show": ["one wealthy Indian man", "low-angle"]},
        {"id": "s3", "beat": "b1", "prompt": "idea", "seconds": 2.0, "camera": "static", "subjects": ["Indian Rupees"], "setting": "", "character": False, "cast": [],
         "still": "Close-up of one pile of Indian Rupees on one polished wooden table.", "must_show": ["one pile of rupees"]},
    ]
    return store.save(s)


# ── the root cause of the stray objects and the wrong places ──────────────────────

def test_a_plan_subject_is_not_pulled_in_by_the_word_indian():
    """The audit: "Indian Rupees" and the "Indian street market" were added to every shot that said "Indian" (the first word of their names)."""
    short = make_short()
    shot = short["shots"][0]
    prompt = stills.prompt(short, shot)
    assert "Indian Rupees:" not in prompt and "colorful cloth stalls" not in prompt, "the family shot shows neither the money nor the market"
    assert "Middle-class Indian family" in prompt and "living room" in prompt
    old = make_short(lint_on=False)                                            # a short made before the check keeps the old rule, so its pictures stay valid
    legacy = stills.prompt(old, old["shots"][0])
    assert "Indian Rupees:" in legacy and "colorful cloth stalls" in legacy, "the old behaviour is untouched"


def test_a_subject_is_still_pulled_in_when_the_picture_text_names_it():
    short = make_short()
    assert "Indian Rupees:" in stills.prompt(short, short["shots"][2]), "named in the text"
    shot = copy.deepcopy(short["shots"][0])
    shot["still"] = "Wide shot of one Indian street market. One person walks in the center."
    prompt = stills.prompt(short, shot)
    assert "Setting: A vibrant, crowded Indian market" in prompt


# ── the code fixes ───────────────────────────────────────────────────────────────────

def test_tidy_takes_out_a_prop_the_text_never_names_and_keeps_people():
    short = make_short()
    shot = short["shots"][1]
    what = lint.tidy_shot(short, shot)
    assert shot["subjects"] == ["Wealthy Indian man"], "the money is out; the person stays as the planner listed it"
    assert any("Indian Rupees" in w for w in what)
    s1 = short["shots"][0]
    assert lint.tidy_shot(short, s1) == [] and s1["subjects"] == ["Middle-class Indian family (group)"], "a bracketed kind does not hide a subject"


def test_tidy_makes_the_setting_agree_with_the_picture_text():
    short = make_short()
    shot = copy.deepcopy(short["shots"][0])
    shot["setting"] = "A vibrant, crowded Indian market with colorful cloth stalls."
    what = lint.tidy_shot(short, shot)
    assert shot["setting"] == "A living room." and any("living room" in w for w in what)
    shot2 = copy.deepcopy(short["shots"][0])
    shot2["still"] = "Wide shot of one Indian street market."
    shot2["setting"] = "Indian street market"
    assert lint.tidy_shot(short, shot2) == [] and shot2["setting"] == "Indian street market", "market and street are the same place"
    worker = copy.deepcopy(short["shots"][0])
    worker.update(still="Wide shot of one young office worker sitting at one wooden desk.", setting="A busy market")
    assert lint.place_of(worker["still"]) is None, "an office worker is not an office"


def test_a_camera_angle_becomes_a_sentence_once():
    t = "Low-angle close-up of one poor man. The man holds one piece of bread."
    fixed = lint.normalise_still(t)
    assert fixed.startswith("Close-up of one poor man.") and "placed low and looks up" in fixed and "Low-angle" not in fixed
    assert lint.normalise_still(fixed) == fixed, "running it again changes nothing"
    assert "placed high and looks down" in lint.normalise_still("High-angle wide shot of one street market. Five stalls are in rows.")
    assert lint.normalise_still("Wide shot of one street market.") == "Wide shot of one street market."


def test_numbers_come_out_of_a_subjects_look_and_money_is_plain_paper():
    out = lint.clean_visual("A large pile of 500 and 2000 Rupee notes and shiny gold coins on a polished wooden table.")
    assert "500" not in out and "2000" not in out and "of and" not in out and "plain coloured paper" in out
    assert lint.clean_visual("A man in a silk kurta.") == "A man in a silk kurta."
    assert lint.clean_visual(out) == out


def test_text_and_vague_groups_are_found():
    short = make_short()
    shot = short["shots"][0]
    shot["still"] = "Close-up of one hand holding one smartphone. The screen of the smartphone displays a large number for a bank balance."
    shot["must_show"] = ["large number on the screen"]
    rules = {f["rule"] for f in lint.findings(short, {"s1"})}
    assert "text_in_picture" in rules
    shot["still"] = "Wide shot of one middle-class Indian family standing behind one polished wooden table. The family faces forward."
    shot["must_show"] = []
    assert {f["rule"] for f in lint.findings(short, {"s1"})} == {"group_count"}
    shot["still"] = "Wide shot of one middle-class Indian family of three people standing behind one table: a man on the left, a woman in the middle, a child on the right."
    assert lint.findings(short, {"s1"}) == []


def test_places_and_looks_that_repeat_are_only_notes():
    short = make_short()
    for sh in short["shots"]:
        sh["still"] = "Wide shot of one man in one living room."
        sh["subjects"], sh["setting"] = [], ""
    n = {x["rule"] for x in lint.notes(short)}
    assert {"place_repeat", "composition_repeat"} <= n
    assert lint.findings(short) == [], "a note is never a finding"
    before = copy.deepcopy(short["shots"])
    run(lint.apply_to(short, None, S, protect=False))
    assert [sh["still"] for sh in short["shots"]] == [sh["still"] for sh in before], "nothing is changed for a note"


# ── the writer ─────────────────────────────────────────────────────────────────────────

def test_the_picture_writer_is_sent_back_for_text_and_a_vague_group():
    item = stillwriter.StillOut(id="s1", still="Wide shot of one family standing behind one table. The screen shows a number for a balance.", must_show=[])
    assert stillwriter.problems(item) == [] or all("head count" not in p and "text" not in p for p in stillwriter.problems(item)), "the old rules are unchanged when the check is off"
    msgs = " ".join(stillwriter.problems(item, strict=True))
    assert "asks for text or a number" in msgs and "head count" in msgs


def test_a_remaining_text_problem_is_rewritten_once_by_the_writer(monkeypatch):
    short = make_short()
    short["shots"][0]["still"] = "Close-up of one hand holding one smartphone. The screen of the smartphone displays a large number for a bank balance."
    short["shots"][0]["must_show"] = []
    chat = FakeChat(stills=True, still_text="Close-up of one hand holding one smartphone, the screen a soft blue glow, one wooden table behind it.")
    rep = run(lint.apply_to(short, chat, S, protect=False))
    assert "s1" in rep["rewritten"] and "number" not in short["shots"][0]["still"]
    assert not [f for f in rep["unresolved"] if f["rule"] == "text_in_picture"]
    assert len([c for c in chat.calls if c["task"] == "p4_still"]) == 1, "one call, not a loop"


def test_a_failed_writer_call_never_stops_the_check():
    short = make_short()
    short["shots"][0]["still"] = "Close-up of one smartphone. The screen displays a large number."
    short["shots"][0]["must_show"] = []
    rep = run(lint.apply_to(short, FakeChat(stills=False), S, protect=False))        # the picture writer is off: it raises
    assert any(f["rule"] == "text_in_picture" for f in rep["unresolved"]), "left as a finding for the person"


# ── protecting what is drawn ─────────────────────────────────────────────────────────

def test_a_shot_with_a_drawn_picture_is_left_alone_unless_asked(monkeypatch):
    short = make_short()
    monkeypatch.setattr(lint, "drawn", lambda sh_short, sh: sh["id"] == "s2")                # s2 has its picture
    rep = run(lint.apply_to(short, None, S, protect=True))
    assert "s2" in rep["skipped"] and "s2" not in rep["changed"]
    assert short["shots"][1]["subjects"] == ["Wealthy Indian man", "Indian Rupees"], "unchanged"
    assert "plan" in rep["skipped"], "the subjects' looks are shared, so they wait too"
    rep2 = run(lint.apply_to(short, None, S, protect=False))
    assert "s2" in rep2["changed"] and short["shots"][1]["subjects"] == ["Wealthy Indian man"]


def test_running_it_again_changes_nothing_and_the_stamp_is_current():
    short = make_short()
    run(lint.apply_to(short, None, S, protect=False))
    assert lint.current(short)
    stamp = short["lint"]["stamp"]
    rep = run(lint.apply_to(short, None, S, protect=False))
    assert sum(len(v) for v in rep["changed"].values()) == 0 and short["lint"]["stamp"] == stamp
    short["shots"][0]["still"] += " One lamp is on the left."
    assert not lint.current(short), "a changed prompt makes the check stale"


def test_a_short_made_before_the_check_is_never_touched():
    short = make_short(lint_on=False)
    before = copy.deepcopy(short["shots"])
    rep = run(lint.apply_to(short, None, S, protect=False))
    assert rep["enabled"] is False and short["shots"] == before and "lint" not in short
    assert lint.findings(short) != [] and lint.report(short)["unresolved"] == [], "findings are only reported while the check is on"
    assert "lint" not in [x["id"] for x in auto.steps(short)]


# ── wiring: planning, checks, auto-run, API ───────────────────────────────────────────

def test_planning_runs_the_check_and_a_new_short_has_it_on():
    s = store.create("T", "keyframe", {"kind": "idea", "text": "a courier finds a wallet", "candidate_id": "", "facts": ""}, {})
    assert s["settings"]["storyboard_lint"] is True
    short = run(planner.make_plan(s["id"], FakeChat(), S))
    assert short["lint"]["stamp"] and lint.current(short), "make_plan ran the check on the fresh plan"
    assert next(x for x in auto.steps(short) if x["id"] == "lint")["done"]


def test_what_is_left_shows_in_the_checks_as_a_warning_with_a_fix_button():
    short = make_short()
    short["shots"][0]["still"] = "Close-up of one smartphone. The screen displays a large number."
    short["shots"][0]["must_show"] = []
    res = checks.run(short)
    issue = next(i for i in res["issues"] if i["code"] == "lint_text_in_picture")
    assert issue["level"] == "warn" and issue["fix"] == "lint" and issue["shots"] == ["s1"]
    assert not [i for i in res["issues"] if i["code"].startswith("lint_") and i["level"] == "block"], "never a blocker"


def test_auto_run_does_the_check_after_the_plan(monkeypatch):
    short = make_short()
    store.save(short)
    seen = []

    async def fake_apply(short_id, backend, s, protect=True):
        seen.append(protect)
        sh = store.get(short_id)
        sh["lint"] = {"stamp": lint.stamp(sh), "changed": {"s2": ["x"]}, "skipped": {}, "rewritten": [], "unresolved": [], "notes": []}
        store.save(sh)
        return lint.report(sh)
    monkeypatch.setattr(lint, "apply", fake_apply)

    async def stop(*a, **k):
        raise RuntimeError("stop after the check")
    monkeypatch.setattr(auto.svoice, "missing", lambda s: True)
    monkeypatch.setattr(auto.svoice, "make", stop)
    with pytest.raises(RuntimeError):
        run(auto.run(short["id"], FakeChat(), S, lambda *a, **k: None))
    assert seen == [True], "auto-run protects drawn pictures"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    import main
    from shorts import api as shorts_api
    monkeypatch.setattr(shorts_api, "_backend", lambda: ({**settings_mod.get(), "retry_backoff_s": 0}, FakeChat(stills=True)))
    with TestClient(main.app) as c:
        c.post("/login", data={"username": config.APP_USER, "password": config.APP_PASSWORD})
        yield c


def wait_job(c, sid, timeout=30):
    import time
    t0 = time.time()
    while time.time() - t0 < timeout:
        if c.get(f"/api/shorts/{sid}/job").json().get("state") in ("done", "error", "cancelled"):
            return
        time.sleep(0.05)
    raise AssertionError("the job did not finish")


def test_the_api_runs_the_check_and_the_state_shows_it(client, monkeypatch):
    short = make_short()
    sid = short["id"]
    st = client.get(f"/api/shorts/{sid}").json()
    assert st["lint"]["enabled"] is True and {f["rule"] for f in st["lint"]["unresolved"]} >= {"stray_subject", "angle_wording"} and st["lint"]["current"] is False
    r = client.post(f"/api/shorts/{sid}/lint", json={"protect": False})
    assert r.status_code in (200, 202), r.text
    wait_job(client, sid)
    after = store.get(sid)
    assert after["shots"][1]["subjects"] == ["Wealthy Indian man"] and lint.current(after)
    rep = client.get(f"/api/shorts/{sid}").json()["lint"]
    assert rep["changed"]["s2"] and rep["unresolved"] == [] and rep["current"] is True


def test_the_api_refuses_and_switches_on(client):
    old = make_short(lint_on=False)
    assert client.post(f"/api/shorts/{old['id']}/lint", json={}).status_code == 400, "off for this short"
    assert client.get(f"/api/shorts/{old['id']}").json()["lint"]["enabled"] is False
    r = client.post(f"/api/shorts/{old['id']}/lint", json={"enable": True, "protect": True})
    assert r.status_code in (200, 202), r.text
    wait_job(client, old["id"])
    assert store.get(old["id"])["settings"]["storyboard_lint"] is True
    empty = store.create("E", "keyframe", {"kind": "idea", "text": "a courier finds a wallet", "candidate_id": "", "facts": ""}, {})
    assert client.post(f"/api/shorts/{empty['id']}/lint", json={}).status_code == 400, "plan first"
    assert client.patch(f"/api/shorts/{empty['id']}/settings", json={"storyboard_lint": False}).status_code == 200
    assert store.get(empty["id"])["settings"]["storyboard_lint"] is False


def test_the_check_asks_the_writer_at_most_once_per_beat(monkeypatch):
    """The writer is sent back for text and vague groups while it writes; the check then asks once more per beat with a problem, never in a loop."""
    chat = FakeChat(stills=True, still_text="Wide shot of one big crowd over the hills at sunset today, one sun low in the sky above them.")
    s = store.create("T", "keyframe", {"kind": "idea", "text": "a courier finds a wallet", "candidate_id": "", "facts": ""}, {})
    short = run(planner.make_plan(s["id"], chat, {**S, "retries": 1}))
    beats = len(short["beats"])
    assert chat.count("p4_still") <= beats * 4, "two attempts while writing and two in the check, per beat"
    assert any(f["rule"] == "group_count" for f in lint.findings(short)), "a writer that cannot fix it leaves a finding for the person"


def test_what_a_screen_shows_is_not_the_place_of_the_scene():
    t = "Close-up of one smartphone held in one hand. The screen of the smartphone shows one green forest with one blue lake. The background is the soft daylight of the living room."
    assert lint.place_of(t)[0] == "forest" and lint.scene_place(t)[0] == "living room"
    assert lint.scene_place("The screen shows one forest.") is None
    short = make_short()
    shot = copy.deepcopy(short["shots"][0])
    shot["still"], shot["setting"] = t, "A modern living room."
    assert lint.tidy_shot(short, shot) == [] and not [f for f in lint.findings({**short, "shots": [shot]}) if f["rule"] == "setting_conflict"]
