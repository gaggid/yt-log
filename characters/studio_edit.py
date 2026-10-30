"""The studio's edit side (C2, C3): free edits, try-on from a garment picture, the flat lay of a worn garment, the character in a place, the consistency check, looks, and the
expression/look matrix. Same rules as studio.py: one gateway request at a time, each picture saved on arrival as a numbered attempt, a failed one recorded and the job goes on."""
import asyncio
import io
import time

from PIL import Image

from story3 import store as media
from story3.voice import MediaError

from . import check, edits, reqlog, requests as R, store, studio, wardrobe

MAX_MATRIX = 12


def _item(char_id: str, item_id: str, what: str = "picture") -> dict:
    it = media.get(item_id)
    if not it or it["plan_id"] != char_id or it["status"] != "done" or not it["file"]:
        raise store.CharError(f"that {what} is not a finished picture of this character")
    return it


async def _run(char_id: str, kind: str, key: str, make_req, n: int, label: str, progress, s: dict | None, api_key: str, do_check: bool = False) -> dict:
    """Make `n` attempts from `make_req(attempt)`; optionally score each against the canon (a failed check never fails the picture)."""
    base, api_key = studio._ctx(s, api_key)
    made, failed = 0, []
    for i in range(n):
        if progress:
            progress(i, n, f"{label} ({i + 1} of {n})")
        attempt = len(media.items(char_id, kind, key)) + 1
        try:
            req = make_req(attempt)
        except store.CharError as e:
            failed.append({"error": str(e)})
            break
        it = media.add(char_id, kind, key, 0, "running", req["meta"])
        t0 = time.time()
        try:
            data = await studio._post_image(req["how"], req["body"], req["refs"], base, api_key)
            reqlog.record(it, req, data, seconds=time.time() - t0)
            (store.media_dir(char_id, kind) / f"{key}-a{it['attempt']}.png").write_bytes(data)
            it = media.update(it["id"], status="done", file=f"{kind}/{key}-a{it['attempt']}.png", meta={"seconds_taken": round(time.time() - t0, 1)})
            made += 1
            if do_check:
                try:
                    char = store.get(char_id)
                    media.update(it["id"], meta={"check": await check.look(char, it, s, api_key, allowed=req["meta"].get("value", ""))})
                except (MediaError, ValueError, KeyError):
                    pass
        except asyncio.CancelledError:
            media.update(it["id"], status="failed", meta={"error": "stopped before it finished"})
            raise
        except Exception as e:  # noqa: BLE001
            reqlog.record(it, req, None, error=str(e)[:300], seconds=time.time() - t0)
            media.update(it["id"], status="failed", meta={"error": str(e)[:300], "seconds_taken": round(time.time() - t0, 1)})
            failed.append({"error": str(e)[:200]})
            if "not reachable" in str(e):
                break
    if progress:
        progress(n, n, "done")
    return {"made": made, "failed": failed}


async def make_edit(char_id: str, base_id: str, preset: str, value: str = "", extra_ids: list[str] | None = None, garment_id: str = "", scope: str = "outfit", n: int = 1,
                    override: str = "", progress=None, s: dict | None = None, key: str = "", do_check: bool = True, lora: list[dict] | None = None, swap: str = "", both: bool = False, swap_note: str = "") -> dict:
    if both and swap and override.strip():                                 # compare: the head-swap LoRA first, then the same swap by prompt only
        a = await make_edit(char_id, base_id, preset, value, extra_ids, garment_id, scope, n, swap_note, progress, s, key, do_check, lora, swap)
        b = await make_edit(char_id, base_id, preset, value, extra_ids, garment_id, scope, n, override, progress, s, key, do_check, lora, "")
        return {"made": a["made"] + b["made"], "failed": a["failed"] + b["failed"]}
    char = store.get(char_id)
    base = _item(char_id, base_id)
    extra = [_item(char_id, x) for x in (extra_ids or [])]
    garment = wardrobe.usable(garment_id) if garment_id else None
    return await _run(char_id, store.EDIT, "edit", lambda a: edits.build(char, base, preset, value, a, extra, garment["path"] if garment else None, scope if garment else "",
                                                                           override=override, garment_worn=bool(garment and garment["worn"]), lora=lora, swap=swap),
                      n, "Dress the character" if garment else ("Swap the head" if swap else "Edit"), progress, s, key, do_check)


def place_picture(place_id: str) -> dict:
    c = store.get(place_id)
    if c["kind"] != "place":
        raise store.CharError("that is not a place")
    it = store.canon_items(c).get("place")
    if not it:
        raise store.CharError(f"approve a picture of {c['name']} first")
    return it


async def make_place(char_id: str, place_id: str, action: str, base_id: str = "", n: int = 1, override: str = "", progress=None, s: dict | None = None, key: str = "",
                     do_check: bool = True) -> dict:
    char = store.get(char_id)
    place = place_picture(place_id)
    base = _item(char_id, base_id) if base_id else None
    return await _run(char_id, store.EDIT, "edit", lambda a: edits.build_place(char, place, action, a, base, override=override), n, "Place the character", progress, s, key, do_check)


async def make_flatlay(garment_id: str, progress=None, s: dict | None = None, key: str = "") -> dict:
    """A worn-garment photo becomes a flat lay with no person in it, kept as its own garment (source = the photo), so a try-on can never carry the model across."""
    src = wardrobe.get(garment_id)
    base, api_key = studio._ctx(s, key)
    path = media.path_of(src)
    if progress:
        progress(0, 1, "Making a flat lay of the clothing")
    body = {"model": "qwen-image-2.1", "size": edits.size_of_picture(path), "n": 1, "seed": 7, "response_format": "b64_json", "prompt": edits.FLATLAY}
    data = await studio._post_image("edit", body, [path], base, api_key)
    out = wardrobe.add(data, (src["meta"].get("name") or "Garment") + " (flat lay)", src["meta"].get("basis") or "invented", src["meta"].get("tags"), worn=False, source=garment_id)
    if progress:
        progress(1, 1, "done")
    return {"made": 1, "garment": out["id"]}


async def check_item(char_id: str, item_id: str, s: dict | None = None, key: str = "") -> dict:
    char = store.get(char_id)
    it = _item(char_id, item_id)
    res = await check.look(char, it, s, key, allowed=it["meta"].get("value", "") if it["kind"] == store.EDIT else "")
    media.update(item_id, meta={"check": res})
    return res


def save_look(char_id: str, item_id: str, name: str) -> dict:
    """Keep any finished picture of this character as a named look. The look remembers the canon version it was made from, so it shows as old when the canon changes."""
    char = store.get(char_id)
    it = _item(char_id, item_id)
    lid = "lk-" + it["id"][-6:]
    char["looks"] = [x for x in char["looks"] if x["id"] != lid] + [{"id": lid, "name": name.strip() or "Look", "item": item_id, "version": char["version"],
                                                                      "recipe": {k: it["meta"].get(k) for k in ("preset", "value", "garment_scope", "op")}}]
    return store.save(char)


def delete_look(char_id: str, look_id: str) -> dict:
    char = store.get(char_id)
    char["looks"] = [x for x in char["looks"] if x["id"] != look_id]
    return store.save(char)


def look_item(char: dict, look_id: str) -> dict | None:
    lk = next((x for x in char["looks"] if x["id"] == look_id), None)
    it = media.get(lk["item"]) if lk else None
    return it if it and it["status"] == "done" and it["file"] else None


async def make_matrix(char_id: str, look_ids: list[str], expressions: list[str], progress=None, s: dict | None = None, key: str = "") -> dict:
    """Every chosen look (or the canon when none) in every chosen expression, one picture per cell, at most MAX_MATRIX cells."""
    char = store.get(char_id)
    bases = [look_item(char, x) for x in look_ids] if look_ids else [store.canon_items(char).get("portrait")]
    bases = [b for b in bases if b]
    cells = [(b, e) for b in bases for e in expressions if e in R.EXPRESSIONS]
    if not cells:
        raise store.CharError("choose at least one look (or the canon) and one expression")
    if len(cells) > MAX_MATRIX:
        raise store.CharError(f"at most {MAX_MATRIX} pictures at a time: {len(cells)} chosen")
    made, failed = 0, []
    for i, (b, e) in enumerate(cells):
        res = await _run(char_id, store.EDIT, "edit", lambda a, b=b, e=e: edits.build(char, b, "expression", R.EXPRESSIONS[e], a, extra_meta={"matrix": e}), 1,
                         f"{e} on {b['id'][-4:]}", None, s, key, False)
        made += res["made"]
        failed += res["failed"]
        if progress:
            progress(i + 1, len(cells), f"{e} ({i + 1} of {len(cells)})")
    return {"made": made, "failed": failed}


def set_canon_view(char_id: str, item_id: str, view: str) -> dict:
    """Promote an edited picture to the canon of `view` (portrait or body), for example the body in a new fixed outfit."""
    char = store.get(char_id)
    it = _item(char_id, item_id)
    if view not in store.CANON_VIEWS[char["kind"]]:
        raise store.CharError("canon views are " + ", ".join(store.CANON_VIEWS[char["kind"]]))
    if char["canon"].get(view) != item_id:
        char["canon"][view] = item_id
        char["version"] += 1
    return store.save(char)


def keep(char_id: str, item_id: str, on: bool = True) -> dict:
    """Mark an edited picture as kept (edits all share one key, so this is a flag on the picture, not the one-approved-per-key approval)."""
    it = _item(char_id, item_id)
    return media.update(it["id"], meta={"kept": bool(on)})
