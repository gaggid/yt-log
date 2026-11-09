"""The story simulator's API: setup, jobs, steering, branches, export and import, delete. The model is the scripted fake of tests/sim_fakes.py."""
import io
import time
import zipfile

import pytest

from sim import store
from sim_fakes import SimFake


@pytest.fixture
def client(env, monkeypatch):
    import auth
    import config
    import main
    from fastapi.testclient import TestClient
    import sim.api as sapi
    monkeypatch.setattr(config, "DATA_DIR", env)
    fake = SimFake()
    monkeypatch.setattr(sapi.llm, "ChatBackend", lambda s, k: fake)
    with TestClient(main.app) as c:
        c.cookies.set("yt_session", auth.make_token())
        c.fake = fake
        yield c


def wait(c, pid, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        r = c.get(f"/api/sim/{pid}/run").json()
        if r.get("state") != "running":
            assert r.get("state") != "error", r
            return r
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def new_story(c):
    pid = c.post("/api/sim", json={"idea": "A salesman, a supermarket, an outbreak", "template_id": "tp-survival"}).json()["id"]
    assert c.post(f"/api/sim/{pid}/seed/all", json={}).status_code == 200
    wait(c, pid)
    return pid


def test_create_seed_start_and_continue(client):
    c = client
    pid = new_story(c)
    d = c.get(f"/api/sim/{pid}").json()
    assert d["project"]["status"] == "setup" and len(d["entities"]) == 8 and d["missing"] == []
    assert any(g["origin"] == "owner" for g in d["guidelines"]) and any(g["origin"] == "ai" for g in d["guidelines"])        # the template's rules and the AI's
    assert c.post(f"/api/sim/{pid}/chapters", json={"kind": "auto"}).status_code == 400                           # not started
    assert c.post(f"/api/sim/{pid}/start").status_code == 200
    r = wait(c, pid)
    assert "chapter 1" in r["note"]
    d = c.get(f"/api/sim/{pid}").json()
    assert len(d["chapters"]) == 1 and d["project"]["status"] == "running" and d["chapters"][0]["options"]
    assert c.post(f"/api/sim/{pid}/chapters", json={"kind": "option", "option_id": "o9"}).status_code == 400
    assert c.post(f"/api/sim/{pid}/chapters", json={"kind": "text", "text": "  "}).status_code == 400
    assert c.post(f"/api/sim/{pid}/chapters", json={"kind": "option", "option_id": "o1"}).status_code == 200
    wait(c, pid)
    assert c.post(f"/api/sim/{pid}/chapters", json={"kind": "text", "text": "barricade the doors", "who": "Ravi"}).status_code == 200
    wait(c, pid)
    d = c.get(f"/api/sim/{pid}").json()
    assert [x["idx"] for x in d["chapters"]] == [1, 2, 3]
    lst = c.get("/api/sim").json()
    assert lst["stories"][0]["chapters"] == 3 and len(lst["templates"]) >= 8


def test_a_second_job_is_refused_and_stop_with_nothing_running_is_harmless(client):
    c = client
    pid = new_story(c)
    from story2 import jobs
    jobs._current["task"] = type("T", (), {"done": lambda self: False})()
    try:
        assert c.post(f"/api/sim/{pid}/start").status_code == 409
    finally:
        jobs._current["task"] = None
    assert c.post(f"/api/sim/{pid}/stop").json() == {"stopping": False}


def test_start_needs_a_complete_setup(client):
    c = client
    pid = c.post("/api/sim", json={"idea": "empty"}).json()["id"]
    r = c.post(f"/api/sim/{pid}/start")
    assert r.status_code == 400 and "character" in r.json()["detail"]
    assert c.post("/api/sim", json={"idea": "  "}).status_code == 400


def test_setup_editing(client):
    c = client
    pid = new_story(c)
    assert c.patch(f"/api/sim/{pid}", json={"settings": {"difficulty": "brutal", "dice": False, "chapter_words": 400, "seed": 1}}).status_code == 200
    s = c.get(f"/api/sim/{pid}").json()["project"]["settings"]
    assert s["difficulty"] == "brutal" and not s["dice"] and s["chapter_words"] == 400 and s["seed"] != 1
    assert c.patch(f"/api/sim/{pid}", json={"settings": {"difficulty": "wild"}}).status_code == 400
    assert c.patch(f"/api/sim/{pid}", json={"world": {"place": "A mall"}}).status_code == 200
    e = c.post(f"/api/sim/{pid}/entities", json={"kind": "character", "name": "Tara", "data": {"role": "stock boy", "goal": "hide"}}).json()
    assert e["name"] == "Tara" and e["alive"]
    assert c.post(f"/api/sim/{pid}/entities", json={"kind": "character", "name": "tara"}).status_code == 400
    t = c.post(f"/api/sim/{pid}/trackers", json={"kind": "meter", "name": "Cash", "data": {"min": 0, "max": 100, "start": 500}}).json()
    assert t["tracker"]["start"] == 100
    t2 = c.post(f"/api/sim/{pid}/trackers", json={"kind": "relation", "name": "Tara and Ghost", "data": {"a": "Tara", "b": "Ghost"}}).json()
    assert t2["problems"]
    g = c.post(f"/api/sim/{pid}/guidelines", json={"grp": "hard", "text": "No phones work."}).json()
    assert c.post(f"/api/sim/{pid}/guidelines", json={"grp": "odd", "text": "x"}).status_code == 400
    assert c.delete(f"/api/sim/{pid}/guidelines/{g['id']}").status_code == 200
    assert g["id"] not in [x["id"] for x in c.get(f"/api/sim/{pid}").json()["guidelines"]]
    assert c.post(f"/api/sim/{pid}/guidelines/suggest", json={}).status_code == 200
    wait(c, pid)
    assert c.delete(f"/api/sim/{pid}/entities/{e['id']}").status_code == 200


def test_directives_branches_rewrite_and_hand_edit(client):
    c = client
    pid = new_story(c)
    c.post(f"/api/sim/{pid}/start")
    wait(c, pid)
    d = c.post(f"/api/sim/{pid}/directives", json={"kind": "event", "text": "Raiders arrive", "timing": {"mode": "next"}}).json()
    assert c.post(f"/api/sim/{pid}/directives", json={"kind": "event", "text": "x", "timing": {"mode": "when"}}).status_code == 400
    c.post(f"/api/sim/{pid}/chapters", json={"kind": "option", "option_id": "o1"})
    wait(c, pid)
    det = c.get(f"/api/sim/{pid}").json()
    assert det["directives"][0]["fired_in"] == 2 and not det["directives"][0]["pending"]
    assert c.delete(f"/api/sim/{pid}/directives/{d['id']}").status_code == 400                 # already used: stays in the history
    ch2 = det["chapters"][1]["id"]
    assert c.post(f"/api/sim/{pid}/chapters/{ch2}/rewrite", json={"instruction": ""}).status_code == 400
    assert c.post(f"/api/sim/{pid}/chapters/{ch2}/rewrite", json={"instruction": "make it quieter"}).status_code == 200
    wait(c, pid)
    assert "make it quieter" in c.fake.last("sm_plan")["user"]
    det = c.get(f"/api/sim/{pid}").json()
    new2 = det["chapters"][1]
    assert new2["id"] != ch2 and len(new2["siblings"]) == 2 and {s["label"] for s in new2["siblings"]} >= {"earlier version"}
    assert det["branches"] == 1
    assert c.post(f"/api/sim/{pid}/head", json={"chapter_id": ch2}).status_code == 200
    assert c.get(f"/api/sim/{pid}").json()["chapters"][1]["id"] == ch2
    assert c.post(f"/api/sim/{pid}/chapters/{ch2}/reroll").status_code == 200
    wait(c, pid)
    head = c.get(f"/api/sim/{pid}").json()["project"]["head_id"]
    r = c.patch(f"/api/sim/{pid}/chapters/{head}", json={"prose": "A new version of the chapter text. " * 20}).json()
    assert r["edited_prose"]
    assert c.post(f"/api/sim/{pid}/chapters/{head}/reread").status_code == 200
    wait(c, pid)
    assert c.get(f"/api/sim/{pid}").json()["chapters"][-1]["flags"]["reread"]["note"]
    assert c.post(f"/api/sim/{pid}/chapters/{head}/reread/apply").status_code == 200
    assert "reread" not in store.chapter(head)["flags"]
    first = c.get(f"/api/sim/{pid}").json()["chapters"][0]["id"]
    assert c.delete(f"/api/sim/{pid}/chapters/{first}").status_code == 400                    # has chapters after it


def test_a_failed_chapter_is_shown_and_retried(client):
    c = client
    pid = new_story(c)

    def boom(user, n):
        raise RuntimeError("down")
    c.fake.answers["sm_write"] = boom
    c.post(f"/api/sim/{pid}/start")
    for _ in range(300):
        if c.get(f"/api/sim/{pid}/run").json().get("state") != "running":
            break
        time.sleep(0.05)
    d = c.get(f"/api/sim/{pid}").json()
    assert d["failed"] and d["failed"]["stage"] == "write" and not d["chapters"]
    del c.fake.answers["sm_write"]
    assert c.post(f"/api/sim/{pid}/chapters/{d['failed']['id']}/retry").status_code == 200
    wait(c, pid)
    assert len(c.get(f"/api/sim/{pid}").json()["chapters"]) == 1


def test_auto_run_export_import_duplicate_and_templates(client):
    c = client
    pid = new_story(c)
    c.post(f"/api/sim/{pid}/start")
    wait(c, pid)
    assert c.post(f"/api/sim/{pid}/auto", json={"n": 2}).status_code == 200
    r = wait(c, pid)
    assert "2 chapters made" in r["note"]
    md = c.get(f"/api/sim/{pid}/export?format=md")
    assert md.status_code == 200 and "## Chapter 3: Beat 3" in md.text
    js = c.get(f"/api/sim/{pid}/export?format=json").json()
    assert [x["n"] for x in js["chapters"]] == [1, 2, 3] and js["cast"][0]["name"] == "Ravi"
    z = zipfile.ZipFile(io.BytesIO(c.get(f"/api/sim/{pid}/export?format=zip").content))
    assert {"story.md", "chapters.json"} <= set(z.namelist())
    full = c.get(f"/api/sim/{pid}/export?format=story&full=true").json()
    new = c.post("/api/sim/import", json=full).json()["id"]
    d = c.get(f"/api/sim/{new}").json()
    assert [x["idx"] for x in d["chapters"]] == [1, 2, 3] and d["project"]["head_id"]
    assert set(d["state"]["trackers"]) == {t["id"] for t in d["trackers"]}                              # saved states point at the new tracker ids
    assert c.post(f"/api/sim/{new}/chapters", json={"kind": "option", "option_id": "o1"}).status_code == 200
    wait(c, new)
    assert len(c.get(f"/api/sim/{new}").json()["chapters"]) == 4 and len(c.get(f"/api/sim/{pid}").json()["chapters"]) == 3
    n2 = c.post("/api/sim/import", json=c.get(f"/api/sim/{pid}/export?format=story").json()).json()["id"]
    assert c.get(f"/api/sim/{n2}").json()["chapters"] == [] and len(c.get(f"/api/sim/{n2}").json()["entities"]) == 8
    dup = c.post(f"/api/sim/{pid}/duplicate").json()["id"]
    assert c.get(f"/api/sim/{dup}").json()["project"]["title"].endswith("(copy)")
    assert c.post("/api/sim/import", json={"format": 9}).status_code == 400
    t = c.post(f"/api/sim/{pid}/save-template", json={"name": "My survival"}).json()
    assert t["id"] in [x["id"] for x in c.get("/api/sim/templates").json()["templates"]]
    mine = c.post("/api/sim", json={"idea": "again", "template_id": t["id"]}).json()["id"]
    assert c.get(f"/api/sim/{mine}").json()["guidelines"]


def test_delete_and_the_file_route_is_fenced(client, env):
    c = client
    pid = new_story(c)
    c.post(f"/api/sim/{pid}/start")
    wait(c, pid)
    from story3 import store as media
    media.media_dir(pid).joinpath("a.png").write_bytes(b"png")
    (env / "secret.txt").write_text("no")
    assert c.get(f"/api/sim/file/{pid}/a.png").content == b"png"
    assert c.get(f"/api/sim/file/{pid}/%2e%2e/%2e%2e/secret.txt").status_code == 404
    assert c.delete(f"/api/sim/{pid}").status_code == 200
    assert c.get(f"/api/sim/{pid}").status_code == 404 and not (env / "media" / pid).exists()
