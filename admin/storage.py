"""Storage clean-up, only on demand: see what every long-form project, short and character has put on disk (data/media/<id>/) and free it. Nothing here runs by itself and nothing is
deleted without the person asking for exactly that project and those folders. A project's text, plan, approvals and exports stay (they are small and are what the work is); what goes is
media that can be made again: pictures, voice, clips, drafts, finished videos. Three ways to free space for one project:

* `folders`  - the folders the person ticked (scenes, refs, voice, video, ...)
* `older`    - only superseded attempts: for every picture/take/clip keep the approved one (else the newest finished one) and remove the rest, including failed attempts
* `all`      - every media file of the project

Files the person supplied and the app cannot make again (uploaded pictures, likeness photos, downloaded source video, a character's source photo) are marked `irreplaceable`: they are never
touched by `older`, and the screen asks again before a folder with them is removed."""
import os
import re
import shutil
import sqlite3
import time
from pathlib import Path

import config
from story import db
from story3 import store as media

ID_RE = re.compile(r"^(?:pl|sh|ch)-[0-9a-f]{6,16}$")
SPECIAL = {"wardrobe": "Wardrobe (garment pictures)"}
# folder -> (what it holds, can the app make it again?)
FOLDERS = {
    "scenes": ("Scene pictures", True), "refs": ("Reference pictures of characters and places", True), "voice": ("Voice takes", True), "video": ("Draft and final videos", True),
    "graphics": ("Charts, tables and documents", True), "thumbnail": ("Thumbnails", True), "clip": ("Motion clips", True), "publish": ("Publish pack", True),
    "key": ("Start pictures (storyboard)", True), "final": ("Final short videos", True), "frames": ("Cut frames", True), "remix": ("Remix motion guide and parts", False),
    "upload": ("Pictures you uploaded", False), "likeness": ("Photos used for a real person's likeness", False), "source": ("Photo a character was started from", False),
    "char_gen": ("Character pictures drawn from text", True), "char_sheet": ("Character sheet pictures", True), "char_edit": ("Character edits, looks and try-ons", True),
    "garment": ("Garment pictures", False),
}
OTHER = {                                           # folders under data/ that only hold test output; the timing files the estimates read are kept
    "characters_probe": ("Character studio probe pictures", ("timings.json",)), "shorts_probe": ("Shorts probe clips", ("timings.json",)),
    "tts_test": ("Voice test clips", ()), "bench": ("Prompt bench output", ()),
}


class StorageError(Exception):
    pass


def media_root() -> Path:
    return config.DATA_DIR / "media"


def _size(path: Path) -> tuple[int, int]:
    total = files = 0
    for root, _d, names in os.walk(path):
        for n in names:
            try:
                total += os.path.getsize(os.path.join(root, n))
                files += 1
            except OSError:
                pass
    return total, files


def kind_of(pid: str) -> str:
    return {"pl": "long", "sh": "short", "ch": "character"}.get(pid[:2], "special")


def _titles() -> dict[str, dict]:
    out: dict[str, dict] = {}
    try:
        for r in db.q("SELECT p.id, p.status, p.updated_at, COALESCE(c.title, pr.title) title FROM plans p LEFT JOIN projects pr ON pr.id=p.project_id LEFT JOIN candidates c ON c.id=p.candidate_id"):
            out[r["id"]] = {"title": r["title"] or r["id"], "status": r["status"], "updated_at": r["updated_at"]}
    except Exception:  # noqa: BLE001 - a table may not exist yet on a fresh install
        pass
    for table, key in (("shorts", "title"), ("chars", "name")):
        try:
            for r in db.q(f"SELECT id, {key} AS t, status, updated_at FROM {table}"):
                out[r["id"]] = {"title": r["t"] or r["id"], "status": r["status"], "updated_at": r["updated_at"]}
        except Exception:  # noqa: BLE001
            pass
    return out


def _rows(pid: str) -> list[dict]:
    return media.items(pid)


def older_rows(pid: str) -> list[dict]:
    """The attempts a clean-up of superseded work would remove: failed ones, and for every (kind, key) all but the approved one (else the newest finished one). Characters are skipped: their
    edits share one key and are chosen by canon, looks and 'kept', which the studio shows."""
    if pid.startswith("ch-"):
        return []
    groups: dict[tuple, list[dict]] = {}
    for r in _rows(pid):
        groups.setdefault((r["kind"], r["key"]), []).append(r)
    drop = []
    for rows in groups.values():
        done = [r for r in rows if r["status"] == "done" and r["file"]]
        keep = {r["id"] for r in done if r["approved"]} or ({done[-1]["id"]} if done else set())
        drop += [r for r in rows if r["id"] not in keep and r["status"] != "running"]
    return drop


def _row_bytes(pid: str, rows: list[dict]) -> int:
    base = media.media_dir(pid)
    total = 0
    for r in rows:
        if r["file"]:
            try:
                total += (base / r["file"]).stat().st_size
            except OSError:
                pass
    return total


def project_view(pid: str, titles: dict) -> dict:
    d = media_root() / pid
    folders = []
    rows = _rows(pid)
    for sub in sorted(p for p in d.iterdir() if p.is_dir()):
        b, n = _size(sub)
        label, again = FOLDERS.get(sub.name, (sub.name, True))
        folders.append({"name": sub.name, "label": label, "bytes": b, "files": n, "irreplaceable": not again, "rows": sum(1 for r in rows if r["file"].startswith(sub.name + "/"))})
    loose = sum(f.stat().st_size for f in d.iterdir() if f.is_file())
    older = older_rows(pid)
    t = titles.get(pid)
    return {"id": pid, "kind": kind_of(pid), "title": (t or {}).get("title") or SPECIAL.get(pid) or pid, "status": (t or {}).get("status", ""), "updated_at": (t or {}).get("updated_at"),
            "orphan": t is None and pid not in SPECIAL, "bytes": sum(f["bytes"] for f in folders) + loose, "folders": folders, "older_bytes": _row_bytes(pid, older), "older_count": len(older),
            "running": _running(pid)}


def _running(pid: str) -> bool:
    try:
        from story2 import jobs
        return bool(jobs.busy() and jobs.status(pid).get("state") == "running")
    except Exception:  # noqa: BLE001
        return False


def overview() -> dict:
    root = media_root()
    root.mkdir(parents=True, exist_ok=True)
    titles = _titles()
    projects = [project_view(p.name, titles) for p in root.iterdir() if p.is_dir() and (ID_RE.match(p.name) or p.name in SPECIAL)]
    projects.sort(key=lambda p: -p["bytes"])
    other = []
    for key, (label, keep) in OTHER.items():
        d = config.DATA_DIR / key
        if d.is_dir():
            b, n = _size(d)
            kept = sum((d / k).stat().st_size for k in keep if (d / k).is_file())
            other.append({"key": key, "label": label, "bytes": b - kept, "files": n, "keeps": list(keep)})
    usage = shutil.disk_usage(config.DATA_DIR)
    return {"projects": projects, "other": other, "media_bytes": sum(p["bytes"] for p in projects), "disk_total": usage.total, "disk_free": usage.free, "scanned_at": time.time()}


# ── clearing ────────────────────────────────────────────────────────────────

def _prune_after(pid: str) -> None:
    """Take references to removed files out of the records that held them, so no screen points at a missing picture."""
    base = media.media_dir(pid)
    if pid.startswith("pl-"):
        try:
            assets = db.q("SELECT id, data FROM assets WHERE plan_id=?", (pid,))
        except sqlite3.OperationalError:                                   # no plan tables yet: nothing refers to these files
            assets = []
        for a in assets:
            data = db.jload(a["data"], {})
            keep = [r for r in data.get("reference_images", []) if (base / str(r.get("file", ""))).is_file()]
            if len(keep) != len(data.get("reference_images", [])):
                data["reference_images"] = keep
                db.ex("UPDATE assets SET data=?, rev=rev+1, updated_at=? WHERE id=?", (db.jdump(data), db.now(), a["id"]))
    elif pid.startswith("ch-"):
        from characters import store as cstore
        try:
            c = cstore.get(pid)
        except cstore.CharError:
            return
        ok = lambda iid: bool(iid) and (media.get(iid) or {}).get("status") == "done" and (base / media.get(iid)["file"]).is_file()      # noqa: E731
        canon = {v: i for v, i in c["canon"].items() if ok(i)}
        looks = [x for x in c["looks"] if ok(x.get("item"))]
        photo = c.get("source_photo") if (base / (c.get("source_photo") or "-")).is_file() else ""
        if canon != c["canon"] or looks != c["looks"] or photo != c.get("source_photo"):
            c["canon"], c["looks"], c["source_photo"] = canon, looks, photo
            c["version"] += 1
            cstore.save(c)


def _delete_rows(ids: list[str]) -> None:
    for i in range(0, len(ids), 400):
        chunk = ids[i:i + 400]
        db.ex(f"DELETE FROM media WHERE id IN ({','.join('?' * len(chunk))})", chunk)


def clear(pid: str, mode: str, folders: list[str] | None = None, dry_run: bool = False) -> dict:
    if not (ID_RE.match(pid) or pid in SPECIAL):
        raise StorageError("not a project id")
    base = media_root() / pid
    if not base.is_dir():
        raise StorageError("this project has no media folder")
    if _running(pid):
        raise StorageError("a job is running for this project; stop it or wait before freeing its space")
    if mode == "older":
        rows = older_rows(pid)
        freed, files = _row_bytes(pid, rows), sum(1 for r in rows if r["file"])
        if not dry_run:
            for r in rows:
                if r["file"]:
                    (base / r["file"]).unlink(missing_ok=True)
            _delete_rows([r["id"] for r in rows])
    elif mode in ("folders", "all"):
        subs = sorted(p.name for p in base.iterdir() if p.is_dir())
        want = subs if mode == "all" else [f for f in (folders or []) if f in subs]
        if mode == "folders" and not want:
            raise StorageError("choose at least one folder that exists")
        freed = files = 0
        for name in want:
            b, n = _size(base / name)
            freed, files = freed + b, files + n
        if mode == "all":
            freed += sum(f.stat().st_size for f in base.iterdir() if f.is_file())
        if not dry_run:
            for name in want:
                shutil.rmtree(base / name, ignore_errors=True)
            if mode == "all":
                for f in base.iterdir():
                    if f.is_file():
                        f.unlink(missing_ok=True)
                db.ex("DELETE FROM media WHERE plan_id=?", (pid,))
            else:
                ids = [r["id"] for r in _rows(pid) if any(r["file"].startswith(n + "/") for n in want)]
                _delete_rows(ids)
    else:
        raise StorageError("mode is folders, older or all")
    if not dry_run:
        _prune_after(pid)
    return {"freed_bytes": freed, "files": files, "dry_run": dry_run, "project": project_view(pid, _titles()) if (media_root() / pid).is_dir() else None}


def clear_other(key: str, dry_run: bool = False) -> dict:
    if key not in OTHER:
        raise StorageError("unknown folder")
    d = config.DATA_DIR / key
    keep = set(OTHER[key][1])
    freed = files = 0
    if d.is_dir():
        for p in sorted(d.iterdir()):
            if p.name in keep:
                continue
            b, n = _size(p) if p.is_dir() else (p.stat().st_size, 1)
            freed, files = freed + b, files + n
            if not dry_run:
                shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
    return {"freed_bytes": freed, "files": files, "dry_run": dry_run}
