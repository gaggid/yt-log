"""Storage clean-up (admin/storage.py): measuring, the three modes, dry runs, the guards, and the records pruned after files go."""
import pytest
from fastapi.testclient import TestClient

import config
from story import db
from story2 import store as plan_store
from story3 import store as media

from admin import storage
from characters import store as cstore
from shorts import store as sstore


def put(pid, kind, key, name, size, status="done", approved=False, sub=None):
    """A media row with a real file of `size` bytes under data/media/<pid>/<sub or kind folder>/."""
    folder = sub or kind
    it = media.add(pid, kind, key, 0, "running", {})
    path = media.media_dir(pid, folder) / name
    path.write_bytes(b"x" * size)
    media.update(it["id"], status=status, file=f"{folder}/{name}" if status == "done" else "")
    if approved:
        media.approve(it["id"], True)
    return media.get(it["id"])


@pytest.fixture
def lib(env):
    plan_store.ensure()
    pid = "pl-abc12345"
    put(pid, "scene_image", "sc1", "sc1-a1.png", 4000, sub="scenes")
    put(pid, "scene_image", "sc1", "sc1-a2.png", 5000, sub="scenes", approved=True)
    put(pid, "scene_image", "sc1", "sc1-a3.png", 6000, sub="scenes")
    put(pid, "scene_image", "sc2", "sc2-a1.png", 3000, sub="scenes")
    put(pid, "scene_image", "sc2", "bad", 0, status="failed", sub="scenes")
    put(pid, "voice", "seg1", "seg1.wav", 2000, sub="voice")
    put(pid, "video", "draft", "draft-a1.mp4", 8000, sub="video")
    put(pid, "reference", "as1", "as1-a1.png", 1000, sub="refs")
    db.ex("INSERT INTO assets(id, plan_id, kind, name, data, rev, updated_at) VALUES(?,?,?,?,?,?,?)", ("as1", pid, "person", "Raju",
          db.jdump({"reference_images": [{"id": "r1", "file": "refs/as1-a1.png", "approved": True}, {"id": "r2", "file": "refs/gone.png", "approved": False}]}), 1, db.now()))
    return pid


def test_overview_measures_each_project_by_folder_and_flags_orphans(lib):
    media.media_dir("pl-dead0000", "scenes")
    (media.media_dir("pl-dead0000", "scenes") / "a.png").write_bytes(b"x" * 100)
    o = storage.overview()
    p = next(x for x in o["projects"] if x["id"] == lib)
    assert p["bytes"] == 29000 and p["kind"] == "long" and {f["name"]: f["bytes"] for f in p["folders"]} == {"scenes": 18000, "voice": 2000, "video": 8000, "refs": 1000}
    assert p["older_count"] == 3 and p["older_bytes"] == 4000 + 6000, "the older attempts of sc1 and the failed one (no file): everything but the approved one"
    assert next(x for x in o["projects"] if x["id"] == "pl-dead0000")["orphan"] is True and o["disk_free"] > 0


def test_a_dry_run_removes_nothing(lib):
    r = storage.clear(lib, "all", dry_run=True)
    assert r["freed_bytes"] == 29000 and r["dry_run"] and len(media.items(lib)) == 8 and (media.media_dir(lib, "voice") / "seg1.wav").is_file()


def test_folders_mode_removes_the_chosen_folders_and_only_their_rows(lib):
    r = storage.clear(lib, "folders", ["video", "voice", "../../etc"], dry_run=False)
    assert r["freed_bytes"] == 10000 and not (media.media_dir(lib) / "video").exists() and not (media.media_dir(lib) / "voice").exists()
    assert {i["kind"] for i in media.items(lib)} == {"scene_image", "reference"} and (media.media_dir(lib, "scenes") / "sc1-a2.png").is_file()
    with pytest.raises(storage.StorageError):
        storage.clear(lib, "folders", ["nothing"], dry_run=False)


def test_older_mode_keeps_the_approved_or_newest_finished_attempt_of_each(lib):
    storage.clear(lib, "older", dry_run=False)
    left = {(i["key"], i["attempt"]) for i in media.items(lib, "scene_image")}
    assert left == {("sc1", 2), ("sc2", 1)}, "the approved one of sc1; the only finished one of sc2; the failed one is gone"
    assert not (media.media_dir(lib, "scenes") / "sc1-a1.png").exists() and (media.media_dir(lib, "scenes") / "sc1-a2.png").is_file()
    assert len(media.items(lib, "voice")) == 1 and len(media.items(lib, "video")) == 1


def test_all_mode_removes_every_file_and_row_and_prunes_the_reference_records(lib):
    storage.clear(lib, "folders", ["refs"], dry_run=False)
    a = db.jload(db.one("SELECT data FROM assets WHERE id='as1'")["data"], {})
    assert a["reference_images"] == [], "no record may point at a picture that is gone"
    r = storage.clear(lib, "all", dry_run=False)
    assert media.items(lib) == [] and r["project"]["bytes"] == 0


def test_guards_bad_ids_a_running_job_and_unknown_modes(lib, monkeypatch):
    for bad in ("../x", "pl-../..", "scenes", "pl-zz"):
        with pytest.raises(storage.StorageError):
            storage.clear(bad, "all", dry_run=True)
    monkeypatch.setattr(storage, "_running", lambda pid: True)
    with pytest.raises(storage.StorageError, match="job is running"):
        storage.clear(lib, "all", dry_run=False)
    monkeypatch.setattr(storage, "_running", lambda pid: False)
    with pytest.raises(storage.StorageError):
        storage.clear(lib, "everything", dry_run=True)
    assert len(media.items(lib)) == 8


def test_a_character_loses_canon_and_looks_whose_pictures_are_removed(env):
    cstore.ensure()
    c = cstore.create("Raju", "person", {"gender": "man"})
    it = put(c["id"], cstore.GEN, "portrait", "portrait-a1.png", 700, sub=cstore.GEN)
    c["canon"] = {"portrait": it["id"]}
    c["looks"] = [{"id": "lk-1", "name": "Office", "item": it["id"], "version": 1, "recipe": {}}]
    cstore.save(c)
    assert storage.older_rows(c["id"]) == [], "character edits share one key: the older mode leaves them to the studio"
    storage.clear(c["id"], "folders", [cstore.GEN], dry_run=False)
    c2 = cstore.get(c["id"])
    assert c2["canon"] == {} and c2["looks"] == [] and c2["status"] == "draft" and c2["version"] == c["version"] + 1


def test_other_folders_keep_the_timing_files_and_the_api_defaults_to_measuring_only(env):
    d = config.DATA_DIR / "characters_probe"
    (d / "run1").mkdir(parents=True)
    (d / "run1" / "a.png").write_bytes(b"x" * 500)
    (d / "timings.json").write_text("{}")
    assert storage.overview()["other"][0] == {"key": "characters_probe", "label": "Character studio probe pictures", "bytes": 500, "files": 2, "keeps": ["timings.json"]}
    assert storage.clear_other("characters_probe", dry_run=True)["freed_bytes"] == 500 and (d / "run1").exists()
    storage.clear_other("characters_probe", dry_run=False)
    assert not (d / "run1").exists() and (d / "timings.json").is_file()
    with pytest.raises(storage.StorageError):
        storage.clear_other("data", dry_run=False)


def test_api_overview_and_clear(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    import main
    with TestClient(main.app) as c:
        c.post("/login", data={"username": config.APP_USER, "password": config.APP_PASSWORD})
        put("pl-1111aaaa", "voice", "s1", "s1.wav", 2048, sub="voice")
        o = c.get("/api/storage").json()
        assert o["projects"][0]["id"] == "pl-1111aaaa" and o["projects"][0]["bytes"] == 2048
        r = c.post("/api/storage/clear", json={"project": "pl-1111aaaa", "mode": "all"}).json()
        assert r["dry_run"] is True and r["freed_bytes"] == 2048 and (tmp_path / "media" / "pl-1111aaaa" / "voice" / "s1.wav").is_file(), "a request that does not say otherwise only measures"
        r = c.post("/api/storage/clear", json={"project": "pl-1111aaaa", "mode": "all", "dry_run": False}).json()
        assert r["freed_bytes"] == 2048 and not (tmp_path / "media" / "pl-1111aaaa" / "voice" / "s1.wav").exists()
        assert c.post("/api/storage/clear", json={"project": "../etc", "mode": "all", "dry_run": False}).status_code == 400
