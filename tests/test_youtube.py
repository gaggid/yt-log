"""YouTube analytics: sign-in, sync, linking videos to shorts, and the windows of views. Google is a mock transport."""
import asyncio
import time
from datetime import datetime, timezone

import httpx
import pytest

from shorts import ideas as ideas_mod, store as sstore
from story import db
from youtube import client, oauth, store, sync


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def day(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


class Google:
    """A tiny fake of the token, Data and Analytics endpoints."""

    def __init__(self, videos, per_day=100):
        self.videos, self.per_day, self.calls, self.refresh_ok = videos, per_day, [], True

    def __call__(self, req: httpx.Request) -> httpx.Response:
        u = str(req.url)
        self.calls.append(req.url.path)
        if req.url.host == "oauth2.googleapis.com" and req.url.path == "/token":
            body = dict(x.split("=", 1) for x in req.content.decode().split("&"))
            if body["grant_type"] == "authorization_code":
                return httpx.Response(200, json={"access_token": "at1", "refresh_token": "rt1", "expires_in": 3600, "scope": "s"})
            if not self.refresh_ok:
                return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Token has been expired or revoked."})
            return httpx.Response(200, json={"access_token": "at2", "expires_in": 3600})
        if req.url.path == "/revoke":
            return httpx.Response(200)
        assert req.headers["authorization"].startswith("Bearer at")
        if u.startswith(client.DATA + "/channels"):
            return httpx.Response(200, json={"items": [{"id": "UC1", "snippet": {"title": "My Channel"}, "contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]})
        if u.startswith(client.DATA + "/playlistItems"):
            return httpx.Response(200, json={"items": [{"contentDetails": {"videoId": v["id"]}} for v in self.videos]})
        if u.startswith(client.DATA + "/videos"):
            return httpx.Response(200, json={"items": [{"id": v["id"], "snippet": {"title": v["title"], "publishedAt": iso(v["at"])}, "contentDetails": {"duration": "PT45S"},
                                                         "statistics": {"viewCount": str(v["views"]), "likeCount": "9", "commentCount": "2"}} for v in self.videos]})
        if u.startswith(client.ANALYTICS):
            vid = req.url.params["filters"].split("==")[1]
            v = next(x for x in self.videos if x["id"] == vid)
            start = datetime.fromisoformat(req.url.params["startDate"])
            n = int((datetime.fromtimestamp(time.time(), timezone.utc).replace(tzinfo=None) - start).days) + 1
            cols = ["day", *client.METRICS]
            rows = [[(start.replace(tzinfo=None) + __import__("datetime").timedelta(days=k)).strftime("%Y-%m-%d"), self.per_day, 5, 20, 80, 3, 1, 0, 2] for k in range(n)]
            return httpx.Response(200, json={"columnHeaders": [{"name": c} for c in cols], "rows": rows})
        return httpx.Response(404, json={"error": {"message": "unexpected " + u}})


@pytest.fixture
def g(env, monkeypatch):
    monkeypatch.setenv("YT_CLIENT_ID", "cid")
    monkeypatch.setenv("YT_CLIENT_SECRET", "sec")
    monkeypatch.setenv("YT_REDIRECT_URI", "https://app.example/api/youtube/callback")
    mock = Google([])
    monkeypatch.setattr(oauth, "TRANSPORT", httpx.MockTransport(mock))
    return mock


def connect():
    asyncio.run(oauth.exchange("code"))


def make_short(title, published_title, score=8.5, style="realism", age_days=30):
    idea = ideas_mod.add(title, "hook " + title, ["curiosity_gap"], "p", "w")
    ideas_mod.save_score(idea["id"], score, {})
    sh = sstore.create(title, "keyframe", {"kind": "idea", "text": "t"}, {"visual_style": style, "tone_id": "bigbro"})
    sh["publish"] = {"title": published_title, "description": "d", "hashtags": [], "tags": [], "for": ""}
    sstore.save(sh)
    ideas_mod.set_status(idea["id"], "done", sh["id"])
    db.ex("UPDATE shorts SET created_at=? WHERE id=?", (time.time() - age_days * 86400, sh["id"]))          # made before the video was uploaded
    return idea, sh


def test_state_is_signed_and_expires(env):
    s = oauth.make_state(1000)
    assert oauth.check_state(s, 1100) and not oauth.check_state(s, 1000 + oauth.STATE_TTL_S + 1)
    assert not oauth.check_state(s[:-1] + ("0" if s[-1] != "0" else "1"), 1100) and not oauth.check_state("") and not oauth.check_state("a.b")


def test_auth_url_asks_for_read_only_scopes_and_a_refresh_token(g):
    from urllib.parse import parse_qs, urlparse
    q = parse_qs(urlparse(oauth.auth_url()).query)
    assert q["access_type"] == ["offline"] and q["prompt"] == ["consent"] and q["redirect_uri"] == ["https://app.example/api/youtube/callback"]
    assert all(sc.endswith(".readonly") for sc in q["scope"][0].split()) and len(q["scope"][0].split()) == 2


def test_not_configured_is_reported(env, monkeypatch):
    monkeypatch.setenv("YT_CLIENT_ID", "")
    assert not oauth.configured()
    with pytest.raises(oauth.YTError):
        oauth.auth_url()


def test_tokens_are_kept_renewed_and_a_withdrawn_grant_asks_to_connect_again(g):
    connect()
    assert store.get_auth()["refresh_token"] == "rt1"
    assert asyncio.run(oauth.access_token()) == "at1"
    a = store.get_auth(); a["expires_at"] = 0; store.set_auth(a)
    assert asyncio.run(oauth.access_token()) == "at2" and store.get_auth()["refresh_token"] == "rt1"
    a = store.get_auth(); a["expires_at"] = 0; store.set_auth(a)
    g.refresh_ok = False
    with pytest.raises(oauth.YTAuthError):
        asyncio.run(oauth.access_token())
    assert store.get_auth()["broken"]
    asyncio.run(oauth.revoke())
    assert store.get_auth() == {}


def test_a_video_is_linked_to_its_short_by_title_and_a_hand_link_wins(g):
    now = time.time()
    a, sa = make_short("Alpha", "Why the bridge fell in nine seconds")
    b, sb = make_short("Beta", "The secret train that never stops")
    g.videos = [{"id": "AAAAAAAAAAA", "title": "Why the bridge fell in nine seconds!", "at": now - 10 * 86400, "views": 5000},
                {"id": "BBBBBBBBBBB", "title": "Something unrelated entirely", "at": now - 9 * 86400, "views": 70}]
    connect()
    r = asyncio.run(sync.run())
    assert r["videos"] == 2 and r["analytics_failed"] == 0
    assert {l["video_id"]: l["short_id"] for l in store.links()} == {"AAAAAAAAAAA": sa["id"]}
    assert store.get_auth()["channel_title"] == "My Channel"
    sync.link_by_hand(sb["id"], "https://youtube.com/shorts/BBBBBBBBBBB?feature=share")
    sync.auto_link()
    assert {l["video_id"]: (l["short_id"], l["how"]) for l in store.links()}["BBBBBBBBBBB"] == (sb["id"], "manual")
    assert sync.video_id_of("https://youtu.be/AAAAAAAAAAA") == "AAAAAAAAAAA" and sync.video_id_of("nope") == ""


def test_a_short_made_after_the_video_is_not_linked(g):
    now = time.time()
    make_short("Gamma", "Same title as an older video", age_days=0)
    g.videos = [{"id": "CCCCCCCCCCC", "title": "Same title as an older video", "at": now - 400 * 86400, "views": 1}]
    connect()
    asyncio.run(sync.run())
    assert store.links() == []


def test_windows_count_only_complete_days_and_groups_average_the_week(g):
    now = time.time()
    make_short("Alpha", "Alpha title here today", score=9.2, style="realism")
    make_short("Beta", "Beta title here today", score=6.0, style="noir")
    make_short("Fresh", "Fresh title here today", score=8.0, style="realism")
    g.videos = [{"id": "AAAAAAAAAAA", "title": "Alpha title here today", "at": now - 12 * 86400, "views": 9000},
                {"id": "BBBBBBBBBBB", "title": "Beta title here today", "at": now - 12 * 86400, "views": 1000},
                {"id": "FFFFFFFFFFF", "title": "Fresh title here today", "at": now - 1 * 86400, "views": 50}]
    g.per_day = 100
    connect()
    asyncio.run(sync.run())
    p = sync.performance(now)
    rows = {r["video_id"]: r for r in p["rows"]}
    assert rows["AAAAAAAAAAA"]["v7"] == 700 and rows["AAAAAAAAAAA"]["v7_done"] and rows["AAAAAAAAAAA"]["v2"] == 200
    assert rows["AAAAAAAAAAA"]["v28"] == 1300 and not rows["AAAAAAAAAAA"]["v28_done"], "the 28 days are not over yet"
    assert not rows["FFFFFFFFFFF"]["v2_done"] and rows["FFFFFFFFFFF"]["views"] == 50
    assert rows["AAAAAAAAAAA"]["style"] == "realism" and rows["AAAAAAAAAAA"]["tone"] == "bigbro" and rows["AAAAAAAAAAA"]["hook"].startswith("hook")
    gr = p["groups"]
    assert gr["n"] == 2 and {x["key"] for x in gr["score"]} == {"9 and up", "under 7"} and {x["key"] for x in gr["style"]} == {"realism", "noir"}
    assert gr["mechanism"][0]["key"] == "curiosity_gap" and gr["mechanism"][0]["n"] == 2
    assert sync.band(0) == "no score" and sync.band(8.0) == "8 to 9"


def test_the_api_reports_status_refuses_a_foreign_callback_and_links_by_hand(env, monkeypatch):
    import main
    from fastapi.testclient import TestClient
    monkeypatch.setenv("YT_CLIENT_ID", "cid"); monkeypatch.setenv("YT_CLIENT_SECRET", "sec"); monkeypatch.setenv("YT_REDIRECT_URI", "https://app.example/api/youtube/callback")
    import config
    monkeypatch.setattr(config, "DATA_DIR", env)
    with TestClient(main.app, follow_redirects=False) as c:                  # the app opens its own database in DATA_DIR
        idea, sh = make_short("Alpha", "Alpha title here today")
        c.cookies.set("yt_session", __import__("auth").make_token())
        s = c.get("/api/youtube/status").json()
        assert s["configured"] and not s["connected"]
        r = c.get("/api/youtube/connect")
        assert r.status_code in (302, 307) and r.headers["location"].startswith("https://accounts.google.com/")
        r = c.get("/api/youtube/callback", params={"code": "x", "state": "forged"})
        assert "error=" in r.headers["location"] and not store.get_auth()
        assert c.post("/api/youtube/sync").status_code == 400
        assert c.post("/api/youtube/link", json={"short_id": sh["id"], "video": "garbage"}).status_code == 400
        assert c.post("/api/youtube/link", json={"short_id": "sh-none", "video": "AAAAAAAAAAA"}).status_code == 404
        assert c.post("/api/youtube/link", json={"short_id": sh["id"], "video": "AAAAAAAAAAA"}).json() == {"video_id": "AAAAAAAAAAA"}
        assert store.link_of_short(sh["id"])["how"] == "manual"
        assert c.get("/api/youtube/performance").json()["linked"] == 0, "the video is not synced yet"
        c.delete("/api/youtube/link/AAAAAAAAAAA")
        assert store.links() == []
