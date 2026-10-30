"""Live validation of the Character Studio on the real gateway, in a throw-away data folder (nothing touches the real library)."""
import asyncio
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, r"d:\yt-log")
import config

tmp = Path(tempfile.mkdtemp(prefix="char_live_"))
config.DATA_DIR = tmp
from story import db, llm, settings as settings_mod

db.init(tmp / "live.db")
from characters import check, edits, pack, requests as R, store, studio, studio_edit, wardrobe
from shorts import cast, clips, stills, store as sstore
from story3 import store as media

S = settings_mod.get()
KEY = settings_mod.api_key()
T0 = time.time()


def say(*a):
    print(f"[{time.time() - T0:5.0f}s]", *a, flush=True)


async def main():
    be = llm.ChatBackend(S, KEY)
    c = store.create("Raju", "person", None, {"idea": "a tired thirty-year-old delivery rider in a yellow jacket, quiet humour"})
    out = await studio.suggest_slots(c["idea"], "person", be, S)
    c["slots"], c["name"], c["personality"] = out["slots"], out["name"] or "Raju", out["personality"]
    store.save(c)
    say("slots written, gaps:", out["gaps"], "| name:", c["name"])
    print("   identity:", R.identity_text(store.get(c["id"]))[:240])
    res = await studio.make_views(c["id"], ["portrait", "body"], 1, s=S, key=KEY)
    say("drawn", res)
    for v in ("portrait", "body"):
        studio.set_canon(c["id"], media.items(c["id"], store.GEN, v)[-1]["id"])
    c = store.get(c["id"])
    say("canon set, status", c["status"], "version", c["version"], "| lora in request:", media.items(c["id"], store.GEN, "portrait")[0]["meta"]["loras"])
    base = store.canon_items(c)["body"]
    res = await studio_edit.make_edit(c["id"], base["id"], "outfit", "a dark green kurta with beige trousers and brown sandals", s=S, key=KEY, do_check=True)
    e1 = media.items(c["id"], store.EDIT)[-1]
    say("edit", res, "| check:", (e1["meta"].get("check") or {}).get("score"), (e1["meta"].get("check") or {}).get("differences"))
    g = wardrobe.add((Path(r"d:\yt-log\data\characters_probe\20261030-094703\garment.png")).read_bytes(), "Maroon sherwani", "invented")
    res = await studio_edit.make_edit(c["id"], base["id"], "outfit", "", garment_id=g["id"], scope="outfit", s=S, key=KEY, do_check=True)
    e2 = media.items(c["id"], store.EDIT)[-1]
    say("try-on", res, "| check:", (e2["meta"].get("check") or {}).get("score"), (e2["meta"].get("check") or {}).get("differences"))
    c = studio_edit.save_look(c["id"], e2["id"], "Wedding")
    pl = store.create("Platform", "place", {"type": "railway platform at dusk", "signature": "yellow edge line, steel pillars, green benches", "architecture": "open platform with a long tin roof",
                                          "materials": "concrete, steel, green paint", "light": "warm lamps and a dark blue sky", "objects": "six green benches", "size": "empty and long"})
    await studio.make_views(pl["id"], ["place"], 1, s=S, key=KEY)
    studio.set_canon(pl["id"], media.items(pl["id"], store.GEN, "place")[-1]["id"])
    say("place drawn")
    # a short with the cast
    short = sstore.create("Live", "keyframe", {"kind": "idea", "text": "x", "candidate_id": "", "facts": ""}, {"cast": [{"character_id": c["id"], "look_id": c["looks"][0]["id"]}], "place_id": pl["id"]})
    short["plan"] = {"character": cast.block(short).replace("\n", " "), "place": cast.place_text(short), "look": cast.look_text(short), "title": "t", "logline": "l"}
    short["shots"] = [{"id": "s1", "beat": "b1", "prompt": "walks", "still": "He stands at the edge of the platform at dusk, looking down the track, shoulders slumped, holding a thermos.", "camera": "slow push in",
                       "character": True, "cast": [c["id"]], "continues": False, "setting": "", "seconds": 2.5, "frames": 75}]
    short = sstore.save(short)
    say("cast problems:", cast.problems(short))
    res = await clips.make_keyframes(short["id"], s=S, key=KEY)
    kf = clips.chosen_keyframe(sstore.get(short["id"]), short["shots"][0])
    say("storyboard still", res, "| how:", kf["meta"]["how"], "refs:", kf["meta"]["refs"])
    print("   still:", sstore.media_dir(short["id"]) / kf["file"])
    chk = await check.look(store.get(c["id"]), kf, S, KEY)
    say("still vs canon:", chk["score"], chk["features"], chk["differences"])
    zipped = pack.export(c["id"])
    copy = pack.import_pack(zipped)
    say("pack", len(zipped) // 1024, "KB ->", copy["id"], copy["status"], len(copy["looks"]))
    print("FOLDER", tmp)


asyncio.run(main())
