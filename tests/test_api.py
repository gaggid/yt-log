import time

import pytest
from fastapi.testclient import TestClient

import config
from fakellm import FakeBackend
from story import llm
from story.pipeline import manager
from test_pipeline import make_book


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    import main
    fake = FakeBackend()
    monkeypatch.setattr(manager, "backend_factory", lambda s: fake)
    with TestClient(main.app) as c:
        c.post("/login", data={"username": config.APP_USER, "password": config.APP_PASSWORD})
        c.fake = fake
        yield c


def wait_done(c, pid, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        p = c.get(f"/api/projects/{pid}/progress").json()
        if p["status"] in ("done", "error", "paused", "cancelled"):
            return p
        time.sleep(0.1)
    raise AssertionError("timed out")


def test_login_required(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    import main
    with TestClient(main.app) as c:
        assert c.get("/api/projects").status_code == 401
        assert c.get("/internal/busy").status_code == 401


def test_full_workflow_over_http(client):
    r = client.post("/api/projects/text", json={"text": make_book(3, 12), "title": "HTTP Book", "author": "Me"})
    assert r.status_code == 200
    pid = r.json()["id"]
    assert client.get("/api/projects").json()[0]["title"] == "HTTP Book"
    assert client.get(f"/api/projects/{pid}/paras?limit=5").json()["total"] > 30
    assert client.patch(f"/api/projects/{pid}", json={"title": "Renamed"}).json()["title"] == "Renamed"

    assert client.post(f"/api/projects/{pid}/process").json() == {"started": True}
    prog = wait_done(client, pid)
    assert prog["status"] == "done"
    assert all(s["state"] in ("done", "waiting") for s in prog["stages"]) and prog["tokens_in"] > 0

    stories = client.get(f"/api/projects/{pid}/stories?sort=priority").json()
    assert len(stories) >= 2 and stories[0]["priority"] >= stories[-1]["priority"]
    sid = stories[0]["id"]
    detail = client.get(f"/api/stories/{sid}").json()
    assert detail["refs"] and detail["data"]["claims"]
    assert client.patch(f"/api/stories/{sid}", json={"status": "approved", "notes": "good"}).json()["status"] == "approved"
    assert client.patch(f"/api/stories/{sid}", json={"bogus": 1}).status_code == 400

    ex = client.get(f"/api/projects/{pid}/export?statuses=approved").json()
    assert ex["schema_version"] == "1.1" and [s["id"] for s in ex["stories"]] == [sid]
    csv = client.get(f"/api/projects/{pid}/export?format=csv&statuses=all")
    assert csv.headers["content-type"].startswith("text/csv") and sid in csv.text

    merged = client.post("/api/stories/merge", json={"ids": [stories[0]["id"], stories[1]["id"]]}).json()
    assert merged["origin"] == "merge"
    assert client.get(f"/api/projects/{pid}/analysis").json()["index"]["overview"]
    assert client.delete(f"/api/projects/{pid}").json() == {"ok": True}
    assert client.get(f"/api/projects/{pid}").status_code == 404


def test_upload_rejects_bad_files(client):
    r = client.post("/api/projects/upload", files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400
    r = client.post("/api/projects/text", json={"text": "too short"})
    assert r.status_code == 400
    r = client.post("/api/projects/url", json={"url": "http://127.0.0.1/x"})
    assert r.status_code == 400


def test_settings_roundtrip_and_validation(client):
    s = client.get("/api/settings").json()
    assert s["context_limit"] == 65536 and s["derived"]["usable_tokens"] == int(65536 * 0.9) and "api_key" not in s
    assert client.put("/api/settings", json={"context_limit": 65536}).json()["context_limit"] == 65536
    assert client.put("/api/settings", json={"context_limit": 10}).status_code == 400


def test_connection_test_reports_unreachable(client, monkeypatch):
    client.put("/api/settings", json={"base_url": "http://127.0.0.1:9/v1", "transport_retries": 1})
    r = client.post("/api/llm/test").json()
    assert r["ok"] is False and r["error"]


@pytest.mark.live
def test_live_model_end_to_end(env):
    """Optional: LIVE_LLM=1 runs a short article through the real configured model."""
    import asyncio
    from story import projects, review, settings as settings_mod
    from story.pipeline import Pipeline
    res = asyncio.run(llm.connection_test(settings_mod.get(), settings_mod.api_key(), probe_json=False))
    assert res["ok"], res
    text = ("In 1928 the St. Francis Dam in California failed just before midnight on March 12. The flood killed at least "
            "431 people. Chief engineer William Mulholland had inspected cracks in the dam that morning and declared "
            "it safe. A coroner's jury blamed the design and the failure to heed warnings. " * 6)
    pid = projects.import_text(text, title="Dam failure")
    backend = llm.ChatBackend(settings_mod.get(), settings_mod.api_key())
    assert asyncio.run(Pipeline(pid, backend).run()) == "done"
    assert review.list_candidates(pid)
