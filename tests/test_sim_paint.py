"""Pictures of a story: cinematic painted style, references by edit, fallbacks, captions, old marking, the API. The gateway is replaced by a function that returns a small picture."""
import asyncio
import io
import time
from pathlib import Path

import pytest

from sim import paint, store
from sim_fakes import SimFake
from test_sim import cfg, go, make, run, sm  # noqa: F401  (fixtures and helpers of the core tests)


def png(size=(64, 36), colour=(40, 60, 90)) -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", size, colour).save(b, "PNG")
    return b.getvalue()


class Gate:
    """A stand-in for the image endpoint: remembers each request and answers with a picture."""

    def __init__(self, fail_edit=False):
        self.reqs = []
        self.fail_edit = fail_edit

    async def __call__(self, req, base, key):
        self.reqs.append(req)
        return png()


def painted(sm):
    pid, fake = make()
    ch = go(pid, fake)
    gate = Gate()
    note = run(paint.paint_chapter(pid, ch["id"], fake, cfg(), "k", send=gate))
    return pid, fake, ch["id"], gate, note


def test_a_chapter_gets_references_then_panels(sm):
    pid, fake, cid, gate, note = painted(sm)
    ch = store.chapter(cid)
    assert len(ch["panels"]) == 3 and all(p["file"] and p["media_id"] for p in ch["panels"]) and "3 pictures painted" in note
    refs = [r for r in gate.reqs if r["how"] == "draw" and r["body"]["size"] == paint.REF_SIZE]
    edits = [r for r in gate.reqs if r["how"] == "edit"]
    assert len(refs) == 4 and len(edits) == 3                              # Ravi, Meera, Aisle One, Pharmacy; every panel has references to edit from
    assert all(1 <= len(r["refs"]) <= 3 for r in edits)
    from story3 import store as media
    assert {m["kind"] for m in media.items(pid)} == {"sim_ref", "sim_panel"}
    for p in ch["panels"]:
        assert (media.media_dir(pid) / p["file"]).is_file() and (media.media_dir(pid) / p["capfile"]).is_file()


def test_every_request_is_a_painting_never_a_photograph(sm):
    pid, fake, cid, gate, note = painted(sm)
    for r in gate.reqs:
        text = r["body"]["prompt"]
        assert paint.STYLE in text and paint.KEEP_OUT in text
        assert "photo" not in text.replace(paint.KEEP_OUT, "").lower()
        assert len(text) <= 3900
    assert gate.reqs[-1]["body"]["size"] == paint.SIZES["wide"]


def test_a_tall_story_paints_tall_and_captions_can_be_off(sm):
    pid, fake = make()
    store.save_project(pid, settings={"panel_shape": "tall", "captions": False})
    ch = go(pid, fake)
    gate = Gate()
    run(paint.paint_chapter(pid, ch["id"], fake, cfg(), "k", send=gate))
    assert gate.reqs[-1]["body"]["size"] == "720x1280"
    assert all(p["capfile"] == "" for p in store.chapter(ch["id"])["panels"])


def test_without_references_the_panel_is_drawn_from_the_look_texts(sm):
    pid, fake = make()
    ch = go(pid, fake)
    ents = {e["name"]: e for e in store.entities(pid)}
    p = {"n": 1, "shot": "close", "who": ["Ravi"], "place": "Pharmacy", "action": "Ravi reads a label.", "mood": "cold blue"}
    req = paint.panel_request(pid, p, ents, store.project(pid)["settings"], 1, 1)
    assert req["how"] == "draw" and "a tired adult in a work uniform" in req["body"]["prompt"] and "A close-up:" in req["body"]["prompt"]


def test_a_failed_edit_falls_back_to_the_text(sm, monkeypatch):
    from shorts import stills
    calls = []

    async def fake_send(req, base, key):
        calls.append(req["how"])
        if req["how"] == "edit":
            raise RuntimeError("edit endpoint down")
        return png()
    monkeypatch.setattr(stills, "send", fake_send)
    out = run(paint._send({"how": "edit", "body": {}, "refs": []}, "b", "k"))
    assert calls == ["edit", "draw"] and out


def test_panel_planning_is_checked_by_code(sm):
    pid, fake = make()
    ch = go(pid, fake)
    bad = lambda user, n: {"panels": [{"shot": "wide", "who": ["Ravi", "Meera", "Dev"], "place": "Nowhere", "action": "Ravi is not afraid", "caption": " ".join(["w"] * 20)}] * 3} if n == 1 else fake._sm_panels(user)
    fake.answers["sm_panels"] = bad
    panels = run(paint.plan_panels(pid, ch["id"], fake, cfg()))
    assert fake.count("sm_panels") == 2 and len(panels) == 3
    assert all(len(p["who"]) <= 2 and len(p["caption"].split()) <= 12 and " not " not in p["action"] for p in panels)
    only_bad = {"panels": [{"shot": "wide", "who": ["Ravi", "Meera", "Dev"], "place": "Nowhere", "action": "Ravi is not afraid", "caption": " ".join(["w"] * 20)}] * 3}
    fake.answers["sm_panels"] = only_bad
    panels = run(paint.plan_panels(pid, ch["id"], fake, cfg()))                       # the last attempt is accepted, but names and lengths are still cleaned
    assert panels[0]["who"] == ["Ravi", "Meera"] and panels[0]["place"] == "" and len(panels[0]["caption"].split()) == 12


def test_changing_a_look_makes_pictures_old_and_a_repaint_makes_a_new_reference(sm):
    pid, fake, cid, gate, note = painted(sm)
    ravi = next(e for e in store.entities(pid) if e["name"] == "Ravi")
    assert not paint.ref_is_old(pid, ravi, store.project(pid)["settings"])
    store.save_entity(pid, {**ravi, "look": "Ravi, now with a thick grey beard and a red jacket"})
    paint.mark_old(pid)
    ch = store.chapter(cid)
    assert any(p["old"] for p in ch["panels"]) and not all(p["old"] for p in ch["panels"])         # only the panels he is in
    assert paint.ref_is_old(pid, store.entity(pid, ravi["id"]), store.project(pid)["settings"])
    gate2 = Gate()
    run(paint.paint_chapter(pid, cid, fake, cfg(), "k", only=[1], send=gate2))
    assert len([r for r in gate2.reqs if r["body"]["size"] == paint.REF_SIZE]) == 1                 # one new reference, not four
    from story3 import store as media
    assert [m["attempt"] for m in media.items(pid, "sim_ref", ravi["id"])] == [1, 2]
    assert not paint.ref_is_old(pid, store.entity(pid, ravi["id"]), store.project(pid)["settings"])


def test_editing_the_chapter_text_marks_its_pictures_old_via_the_api_and_a_failure_is_kept(sm):
    pid, fake, cid, gate, note = painted(sm)
    sent = []

    class Boom(Gate):
        async def __call__(self, req, base, key):
            raise RuntimeError("gpu busy")
    note = run(paint.paint_chapter(pid, cid, fake, cfg(), "k", only=[2], send=Boom()))
    assert "1 failed" in note
    from story3 import store as media
    assert media.items(pid, "sim_panel", f"{cid}:2")[-1]["status"] == "failed"
    assert store.chapter(cid)["panels"][1]["file"]                                  # the earlier picture is still there


def test_the_paint_module_does_not_use_character_studio():
    src = (Path(paint.__file__)).read_text(encoding="utf-8")
    assert "characters" not in src.replace("Character Studio", "")


def test_a_caption_is_lettered_on_the_picture():
    from PIL import Image
    out = paint.with_caption(png((640, 360)), "The doors would have to hold until morning, whatever came.")
    img = Image.open(io.BytesIO(out))
    assert img.size == (640, 360)
    px = img.getpixel((320, 355))
    assert px != (40, 60, 90)                                                         # the strip darkens the bottom


# ── API ───────────────────────────────────────────────────────────────────────

@pytest.fixture
def client(env, monkeypatch):
    import auth
    import config
    import main
    from fastapi.testclient import TestClient
    import sim.api as sapi
    monkeypatch.setattr(config, "DATA_DIR", env)
    fake = SimFake()
    gate = Gate()
    monkeypatch.setattr(sapi.llm, "ChatBackend", lambda s, k: fake)
    monkeypatch.setattr(paint, "_send", gate)
    with TestClient(main.app) as c:
        c.cookies.set("yt_session", auth.make_token())
        c.fake, c.gate = fake, gate
        yield c


def wait(c, pid):
    end = time.time() + 60
    while time.time() < end:
        r = c.get(f"/api/sim/{pid}/run").json()
        if r.get("state") != "running":
            assert r.get("state") != "error", r
            return r
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def started(c):
    pid = c.post("/api/sim", json={"idea": "A salesman, a supermarket"}).json()["id"]
    c.post(f"/api/sim/{pid}/seed/all", json={})
    wait(c, pid)
    c.post(f"/api/sim/{pid}/start")
    wait(c, pid)
    return pid


def test_api_paint_edit_upload_redraw_and_delete(client, env):
    c = client
    pid = started(c)
    cid = c.get(f"/api/sim/{pid}").json()["project"]["head_id"]
    assert c.post(f"/api/sim/{pid}/chapters/{cid}/paint", json={}).status_code == 200
    r = wait(c, pid)
    assert "3 pictures painted" in r["note"]
    d = c.get(f"/api/sim/{pid}").json()
    ch = d["chapters"][0]
    assert len(ch["panels"]) == 3 and ch["panels"][0]["file"]
    assert c.get(f"/api/sim/file/{pid}/{ch['panels'][0]['capfile']}").status_code == 200
    assert any(e["ref_file"] for e in d["entities"])
    assert c.patch(f"/api/sim/{pid}/chapters/{cid}/panels/1", json={"caption": "A brand new caption for the picture"}).status_code == 200
    assert "-cap" in c.get(f"/api/sim/{pid}").json()["chapters"][0]["panels"][0]["capfile"]
    before = len(c.gate.reqs)
    assert c.post(f"/api/sim/{pid}/chapters/{cid}/panels/2/redraw", json={"prompt": "A lone figure at a shutter in blue dusk"}).status_code == 200
    wait(c, pid)
    assert len(c.gate.reqs) == before + 1 and "A lone figure at a shutter" in c.gate.reqs[-1]["body"]["prompt"]
    up = c.post(f"/api/sim/{pid}/chapters/{cid}/panels/3/upload", files={"file": ("mine.png", png(), "image/png")})
    assert up.status_code == 200
    p3 = c.get(f"/api/sim/{pid}").json()["chapters"][0]["panels"][2]
    assert p3["uploaded"] and p3["file"].startswith("upload/")
    assert c.post(f"/api/sim/{pid}/chapters/{cid}/panels/3/upload", files={"file": ("x.png", b"not a picture", "image/png")}).status_code == 400
    assert c.patch(f"/api/sim/{pid}/chapters/{cid}", json={"prose": "A different story text entirely. " * 20}).status_code == 200
    assert all(p["old"] for p in c.get(f"/api/sim/{pid}").json()["chapters"][0]["panels"])
    assert c.delete(f"/api/sim/{pid}/chapters/{cid}/panels/1").status_code == 200
    assert len(c.get(f"/api/sim/{pid}").json()["chapters"][0]["panels"]) == 2
    ent = c.get(f"/api/sim/{pid}").json()["entities"][0]["id"]
    assert c.post(f"/api/sim/{pid}/entities/{ent}/paint").status_code == 200
    wait(c, pid)
    assert c.delete(f"/api/sim/{pid}").status_code == 200
    assert not (env / "media" / pid).exists()


def test_auto_images_paints_after_each_chapter_and_a_failure_does_not_fail_the_story(client):
    c = client
    pid = c.post("/api/sim", json={"idea": "A salesman, a supermarket"}).json()["id"]
    c.post(f"/api/sim/{pid}/seed/all", json={})
    wait(c, pid)
    c.patch(f"/api/sim/{pid}", json={"settings": {"auto_images": True}})
    c.post(f"/api/sim/{pid}/start")
    wait(c, pid)
    ch = c.get(f"/api/sim/{pid}").json()["chapters"][0]
    assert len(ch["panels"]) == 3 and all(p["file"] for p in ch["panels"])

    async def boom(req, base, key):
        raise RuntimeError("gpu busy")
    paint._send = boom
    c.post(f"/api/sim/{pid}/chapters", json={"kind": "option", "option_id": "o1"})
    wait(c, pid)
    d = c.get(f"/api/sim/{pid}").json()
    assert len(d["chapters"]) == 2 and d["chapters"][1]["status"] == "done"


def test_deleting_a_chapter_deletes_its_lettered_copies(sm):
    pid, fake, cid, gate, note = painted(sm)
    from story3 import store as media
    files = [media.media_dir(pid) / p[k] for p in store.chapter(cid)["panels"] for k in ("file", "capfile")]
    assert all(f.is_file() for f in files)
    store.delete_chapter(pid, cid)
    assert not any(f.exists() for f in files)


def test_the_storage_page_sees_stories_and_prunes_their_pictures(sm):
    from admin import storage
    pid, fake, cid, gate, note = painted(sm)
    ov = storage.overview()
    rows = ov["projects"] if isinstance(ov, dict) else ov
    mine = next(p for p in rows if p["id"] == pid)
    assert mine["kind"] == "story" and mine["title"] == store.project(pid)["title"] and mine["bytes"] > 0 and not mine["orphan"]
    assert {f["name"] for f in mine["folders"]} >= {"panels", "refs"}
    storage.clear(pid, "folders", ["panels"], dry_run=False)
    ch = store.chapter(cid)
    assert all(not p["file"] and not p["capfile"] for p in ch["panels"])
    from story3 import store as media
    assert not media.items(pid, "sim_panel") and media.items(pid, "sim_ref")
    run(paint.paint_chapter(pid, cid, fake, cfg(), "k", only=[1], send=Gate()))                 # references survive, so only the panel is drawn
    assert store.chapter(cid)["panels"][0]["file"]


def test_the_picture_style_is_a_story_setting_that_changes_every_request_and_marks_old_pictures(sm):
    from sim import store as st
    assert set(paint.STYLES) == set(st.IMAGE_STYLES) and paint.style_of({}) is paint.STYLES["painted"] and paint.style_of({"image_style": "nonsense"}) is paint.STYLES["painted"]
    pid, fake = make()
    ch = go(pid, fake)
    for name in ("comic", "flat"):
        gate = Gate()
        st.save_project(pid, settings={"image_style": name})
        run(paint.paint_chapter(pid, ch["id"], fake, cfg(), "k", send=gate))
        text = " ".join(r["body"]["prompt"] for r in gate.reqs)
        assert paint.STYLES[name]["style"] in text and paint.STYLES[name]["keep"] in text and paint.STYLE not in text and "not a photograph and not a painting" in text
        assert "photo" not in text.replace(paint.STYLES[name]["keep"], "").lower()
    e = st.entities(pid)[0]
    assert paint.ref_hash(e, {**cfg(), "image_style": "comic"}) != paint.ref_hash(e, cfg()) and paint.ref_hash(e, cfg()) == paint.ref_hash(e, {**cfg(), "image_style": "painted"})   # painted stays as it was
    assert st.save_project(pid, settings={"image_style": "flat"})["settings"]["image_style"] == "flat"
    with pytest.raises(st.SimError):
        st.save_project(pid, settings={"image_style": "oil"})


def test_each_picture_sits_after_the_paragraph_it_illustrates(sm):
    assert paint.placement([{"after": 1}, {"after": 3}, {"after": 3}], 5) == [1, 3, 3]
    assert paint.placement([{"after": 4}, {"after": 2}], 5) == [4, 4]                                   # never before the one that came first
    assert paint.placement([{}, {}, {}], 8) == [2, 4, 6] and paint.placement([{"after": 99}], 4) == [4] and paint.placement([{}, {}], 0) == [0, 0]
    assert paint.paragraphs("One.\n\nTwo.\n   \nThree.") == ["One.", "Two.", "Three."]
    pid, fake = make()
    ch = go(pid, fake)
    run(paint.paint_chapter(pid, ch["id"], fake, cfg(), "k", send=Gate()))
    saved = store.chapter(ch["id"])["panels"]
    assert [p["after"] for p in saved] == [1, 0, 0]                                                       # the planner's number is kept when it is in range, else left for the code to spread
    assert "[1] " in fake.last("sm_panels")["user"]                                                       # the planner sees numbered paragraphs


def test_the_chapter_view_and_exports_place_pictures_among_the_paragraphs(client, env):
    c = client
    pid, fake = make()
    ch = go(pid, fake)
    store.update_chapter(ch["id"], prose="First paragraph here.\nSecond paragraph here.\nThird paragraph here.\nFourth paragraph here.\nFifth paragraph here.\nSixth paragraph here.")
    run(paint.paint_chapter(pid, ch["id"], fake, cfg(), "k", send=Gate()))
    view = next(x for x in c.get(f"/api/sim/{pid}").json()["chapters"] if x["id"] == ch["id"])
    ats = [p["at"] for p in view["panels"]]
    assert ats == sorted(ats) and ats[0] == 1 and all(1 <= a <= 6 for a in ats) and len(set(ats)) > 1          # spread through the chapter, not stacked on top
    md = c.get(f"/api/sim/{pid}/export?format=md").text
    assert md.index("First paragraph") < md.index("![") < md.index("Sixth paragraph")                         # the first picture is inside the text, not above it
    assert md.index("![") > md.index("## Chapter 1")
    js = c.get(f"/api/sim/{pid}/export?format=json").json()
    assert [p["after"] for p in js["chapters"][0]["panels"]] == ats
