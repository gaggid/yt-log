"""B8: named people. The editor confirms a public figure, a photo is found or uploaded and approved, the character sheet is painted from it, and the leak gate lets the
person's name through. Every step is wired to the screen's API and to the places that read the result."""
import asyncio
import io

import httpx
import pytest
from PIL import Image

from story import db
from story2 import editorial, leak, planner, storyboard
from story3 import api as media_api, likeness, refs
from story3.voice import MediaError
from test_phase3f import SETTINGS, Gateway, planned


def photo_bytes(size=(400, 500), colour=(120, 90, 70)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, "JPEG")
    return buf.getvalue()


def a_person(plan_id):
    return next(a for a in storyboard.get_assets(plan_id) if a["kind"] == "person")


def test_a_likeness_needs_the_editor_to_confirm_a_public_figure(env):
    plan_id = planned(env)
    pid = a_person(plan_id)["id"]
    with pytest.raises(MediaError):
        likeness.set_mode(plan_id, pid, "researched")
    out = likeness.set_mode(plan_id, pid, "researched", public_figure=True)
    assert next(p for p in out["people"] if p["id"] == pid)["mode"] == "researched"
    assert a_person(plan_id)["data"]["fictionalisation"] == "real_person_likeness"
    likeness.set_mode(plan_id, pid, "silhouette")
    assert a_person(plan_id)["data"]["fictionalisation"] == "real_person_no_likeness"


def test_search_results_are_kept_with_their_licence_and_only_the_approved_one_is_used(env, monkeypatch):
    plan_id = planned(env)
    pid = a_person(plan_id)["id"]
    likeness.set_mode(plan_id, pid, "researched", public_figure=True)
    commons = {"query": {"pages": {
        "1": {"index": 1, "title": "File:A.jpg", "imageinfo": [{"mime": "image/jpeg", "thumburl": "https://upload.wikimedia.org/a.jpg", "width": 900, "height": 1100,
                                                               "descriptionurl": "https://commons.wikimedia.org/wiki/File:A.jpg",
                                                               "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"}, "Artist": {"value": "<b>Jo</b> Doe"}}}]},
        "2": {"index": 2, "title": "File:B.svg", "imageinfo": [{"mime": "image/svg+xml", "thumburl": "https://upload.wikimedia.org/b.png", "width": 900}]}}}}
    monkeypatch.setattr(likeness.httpx, "get", lambda *a, **k: httpx.Response(200, json=commons, request=httpx.Request("GET", "https://x")))
    monkeypatch.setattr(likeness, "_download", lambda url: photo_bytes())
    out = likeness.find_photos(plan_id, pid)
    assert out["added"] == 1                                                                  # the svg is skipped
    ph = likeness.photos(a_person(plan_id))[0]
    assert ph["licence"] == "CC BY-SA 4.0" and ph["author"] == "Jo Doe" and "commons.wikimedia.org" in ph["page"] and not ph["approved"]
    assert likeness.approved_path(plan_id, a_person(plan_id)) is None                         # nothing is used until the editor approves
    likeness.approve_photo(plan_id, pid, ph["id"])
    assert likeness.approved_path(plan_id, a_person(plan_id)).is_file()
    likeness.reject_photo(plan_id, pid, ph["id"])
    assert likeness.approved_path(plan_id, a_person(plan_id)) is None
    assert a_person(plan_id)["data"]["fictionalisation"] == "real_person_stylised"            # no photo left: falls back to a near-likeness


def test_upload_is_checked_and_a_private_or_local_photo_link_is_refused(env):
    plan_id = planned(env)
    pid = a_person(plan_id)["id"]
    with pytest.raises(MediaError):
        likeness.add_photo(plan_id, pid, b"not a picture", {"origin": "upload"})
    with pytest.raises(MediaError):
        likeness.add_photo(plan_id, pid, photo_bytes((100, 100)), {"origin": "upload"})        # too small
    with pytest.raises(MediaError):
        likeness._download("http://127.0.0.1:8905/x.jpg")
    with pytest.raises(MediaError):
        likeness._download("https://localhost/x.jpg")
    ph = likeness.add_photo(plan_id, pid, photo_bytes(), {"origin": "upload", "url": "me.jpg", "licence": "supplied by the editor"})
    assert ph["origin"] == "upload"


class EditGateway(Gateway):
    """Also answers the edit endpoint (multipart), remembering what was sent."""

    def client(self):
        base = super().client()
        gw = self

        class C(base):
            async def post(self, url, json=None, headers=None, data=None, files=None):
                if url.endswith("/images/edits"):
                    gw.requests.append({"url": url, "data": data, "files": files})
                    from test_phase3f import png
                    return httpx.Response(200, json={"data": [{"b64_json": png(84, 48), "seed": 1, "width": 1344, "height": 768}]})
                return await super().post(url, json=json, headers=headers)
        return C


def test_the_character_sheet_is_painted_from_the_approved_photo(env, monkeypatch):
    plan_id = planned(env)
    pid = a_person(plan_id)["id"]
    likeness.set_mode(plan_id, pid, "researched", public_figure=True)
    ph = likeness.add_photo(plan_id, pid, photo_bytes(), {"origin": "upload"})
    gw = EditGateway()
    monkeypatch.setattr(refs.httpx, "AsyncClient", gw.client())

    async def nosleep(_):
        return None
    monkeypatch.setattr(refs.asyncio, "sleep", nosleep)
    asyncio.run(refs.generate(plan_id, [pid], 1, s=SETTINGS, key="k", score=False))
    assert not [r for r in gw.requests if r["url"].endswith("/images/edits")]                  # no approved photo yet: drawn from the description
    likeness.approve_photo(plan_id, pid, ph["id"])
    asyncio.run(refs.generate(plan_id, [pid], 1, only_missing=False, s=SETTINGS, key="k", score=False))
    edits = [r for r in gw.requests if r["url"].endswith("/images/edits")]
    assert len(edits) == 1 and "reference photo" in edits[0]["data"]["prompt"] and edits[0]["files"][0][0] == "image"


def test_stylised_and_silhouette_prompts_differ_and_neither_uses_a_photo(env):
    plan_id = planned(env)
    pid = a_person(plan_id)["id"]
    likeness.set_mode(plan_id, pid, "stylised", public_figure=True)
    st = refs.build_prompt(a_person(plan_id), "style", "qwen-image-2.1")["prompt"]
    assert "resembles a real public figure" in st and "silhouette" not in st
    likeness.set_mode(plan_id, pid, "silhouette")
    assert "silhouette" in refs.build_prompt(a_person(plan_id), "style", "qwen-image-2.1")["prompt"]


def test_recreating_the_characters_keeps_the_editors_choices_about_real_people(env):
    from test_describe import SlotFake
    from test_phase2b import approved_story, written_plan
    pid_, cid = approved_story(env)
    be = SlotFake()
    p = written_plan(cid, be)
    asyncio.run(storyboard.make_registry(p["id"], be))
    person = a_person(p["id"])
    likeness.set_mode(p["id"], person["id"], "researched", public_figure=True)
    likeness.add_photo(p["id"], person["id"], photo_bytes(), {"origin": "upload"})
    asyncio.run(storyboard.make_registry(p["id"], be))
    again = next(a for a in storyboard.get_assets(p["id"]) if a["name"] == person["name"])
    assert again["data"]["fictionalisation"] == "real_person_likeness" and again["data"]["public_figure"] and len(again["data"]["likeness_photos"]) == 1


def test_the_leak_gate_lets_a_confirmed_public_figure_be_named_but_not_the_author(env):
    plan_id = planned(env)
    proj = planner.get_plan(plan_id)["project_id"]
    db.ex("UPDATE projects SET title='Steve Harbour', author='Walter Writer' WHERE id=?", (proj,))
    text = "Steve Harbour built the pier. Walter Writer says so."

    def kinds():
        return {(f.kind, f.text.lower()) for f in leak.check(text, leak.profile(proj))}
    assert ("title", "steve harbour") in kinds() and ("author", "walter writer") in kinds()
    pid = a_person(plan_id)["id"]
    db.ex("UPDATE assets SET data=? WHERE id=?", (db.jdump(a_person(plan_id)["data"] | {"name": "Steve Harbour"}), pid))
    likeness.set_mode(plan_id, pid, "stylised", public_figure=True)
    left = kinds()
    assert ("title", "steve harbour") not in left and ("author", "walter writer") in left     # the subject may be named; the author never


def test_the_export_records_where_the_photo_came_from_and_photos_do_not_change_the_approval_hash(env):
    plan_id = planned(env)
    pid = a_person(plan_id)["id"]
    likeness.set_mode(plan_id, pid, "researched", public_figure=True)
    ph = likeness.add_photo(plan_id, pid, photo_bytes(), {"origin": "search", "url": "https://u/x.jpg", "page": "https://commons/x", "licence": "CC BY 4.0", "author": "A"})
    h1 = editorial.content_hash(planner.get_plan(plan_id))
    likeness.approve_photo(plan_id, pid, ph["id"])
    assert editorial.content_hash(planner.get_plan(plan_id)) == h1                           # same mode; the photo list is outside the hash like reference pictures
    ev = likeness.evidence(plan_id)
    assert ev and ev[0]["photo"]["licence"] == "CC BY 4.0" and "not published" in ev[0]["use"]


def test_the_api_walks_the_whole_flow(env):
    plan_id = planned(env)
    pid = a_person(plan_id)["id"]
    out = asyncio.run(media_api.likeness_mode(plan_id, pid, media_api.LikenessMode(mode="researched", public_figure=True)))
    assert out["people"]
    ph = likeness.add_photo(plan_id, pid, photo_bytes(), {"origin": "upload"})
    got = asyncio.run(media_api.likeness_approve(plan_id, pid, ph["id"], None))
    assert next(p for p in got["people"] if p["id"] == pid)["has_photo"]
    assert asyncio.run(media_api.media_state(plan_id))["likeness"]["people"]
    asyncio.run(media_api.likeness_reject(plan_id, pid, ph["id"]))
    assert not next(p for p in likeness.state(plan_id)["people"] if p["id"] == pid)["has_photo"]


def test_the_export_evidence_lists_the_photo_source(env):
    from story2 import export
    from test_phase2d import make_exportable
    pid, cid = make_exportable(env)
    plan_id = planner.get_plan(pid)["id"]
    person = a_person(plan_id)
    likeness.set_mode(plan_id, person["id"], "researched", public_figure=True)
    ph = likeness.add_photo(plan_id, person["id"], photo_bytes(), {"origin": "search", "page": "https://commons/x", "licence": "CC BY 4.0", "author": "A"})
    likeness.approve_photo(plan_id, person["id"], ph["id"])
    doc = export.build(plan_id)
    assert doc["evidence"]["likeness"][0]["photo"]["licence"] == "CC BY 4.0"
    assert "commons/x" not in str(doc["public"])                                              # the source of the photo is evidence only, never public
