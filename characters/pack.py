"""Character packs: one character with every finished picture in a zip (character.json + the files), for backup or for moving it to another machine. Importing always makes a NEW character with
a new id (nothing is overwritten); the pictures keep their numbering, recipes and checks, and the look and canon links are rewritten to the new picture ids."""
import io
import json
import zipfile

from story3 import store as media

from . import store

VERSION = 1
KINDS = (store.GEN, store.SHEET, store.EDIT)


def export(char_id: str) -> bytes:
    c = store.get(char_id)
    items = [i for k in KINDS for i in media.items(char_id, k) if i["status"] == "done" and i["file"]]
    doc = {"pack": VERSION, "character": {k: v for k, v in c.items() if k not in store.COLUMNS and k != "source_photo"}, "name": c["name"], "kind": c["kind"],
           "items": [{"id": i["id"], "kind": i["kind"], "key": i["key"], "attempt": i["attempt"], "file": i["file"], "meta": i["meta"], "approved": i["approved"]} for i in items]}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        z.writestr("character.json", json.dumps(doc, ensure_ascii=False, indent=1))
        for i in items:
            p = media.path_of(i)
            if p.is_file():
                z.write(p, "files/" + i["file"])
    return buf.getvalue()


def import_pack(raw: bytes) -> dict:
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        doc = json.loads(z.read("character.json"))
    except (zipfile.BadZipFile, KeyError, ValueError):
        raise store.CharError("that is not a character pack")
    if doc.get("pack") != VERSION or doc.get("kind") not in store.KINDS:
        raise store.CharError("this pack was made by another version of the studio")
    data = doc["character"]
    c = store.create(doc.get("name") or "Imported", doc["kind"], data.get("slots"), {k: data[k] for k in ("idea", "personality", "render", "tags", "notes", "rights", "recipes") if k in data})
    ids: dict[str, str] = {}
    names = set(z.namelist())
    for it in sorted(doc["items"], key=lambda x: (x["kind"], x["key"], x["attempt"])):
        src = "files/" + it["file"]
        if src not in names or ".." in it["file"] or it["file"].startswith(("/", "\\")):
            continue
        new = media.add(c["id"], it["kind"], it["key"], 0, "running", it["meta"])
        dest = store.media_dir(c["id"], it["kind"]) / f"{it['key']}-a{new['attempt']}.png"
        dest.write_bytes(z.read(src))
        media.update(new["id"], status="done", file=f"{it['kind']}/{dest.name}", approved=1 if it.get("approved") else 0)
        ids[it["id"]] = new["id"]
    c = store.get(c["id"])
    c["canon"] = {v: ids[i] for v, i in (data.get("canon") or {}).items() if i in ids}
    c["version"] = data.get("version", 1)
    c["looks"] = [{**lk, "item": ids[lk["item"]]} for lk in data.get("looks", []) if lk.get("item") in ids]
    return store.save(c)
