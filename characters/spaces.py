"""Space image generation for Virtual Life characters.

Main view: text-to-image from space description + character context.
Corner views: image-to-image edits from the approved main view — 4 diagonal
camera positions showing all walls of the same room.

Images stored as media rows (plan_id = char_id):
  kind "space_gen",    key "space-{slug}-main"
  kind "space_gen",    key "space-{slug}-c1" … "space-{slug}-c4"
"""
import asyncio
import base64
import time

from story3 import store as media

from . import profile as profile_mod, store

_CORNERS = [
    ("c1", "northwest corner, camera aimed southeast across the room"),
    ("c2", "northeast corner, camera aimed southwest across the room"),
    ("c3", "southeast corner, camera aimed northwest across the room"),
    ("c4", "southwest corner, camera aimed northeast across the room"),
]

SIZE_MAIN   = "1280x720"   # landscape room shot
SIZE_CORNER = "1280x720"

NO_TEXT = "No text, letters, numbers, watermark, logo. No people. A single picture."
STYLE   = ("Interior photograph. Natural and warm artificial light. Upper-middle-class Indian urban home, "
           "contemporary style, clean lines, muted palette with one warm accent colour. "
           "Reel-worthy composition, strong depth, leading lines. Photorealistic.")


def _slug(name: str) -> str:
    return name.lower().replace(" ", "_")[:30]


def _main_key(name: str) -> str:
    return f"space-{_slug(name)}-main"


def _corner_key(name: str, tag: str) -> str:
    return f"space-{_slug(name)}-{tag}"


def _build_prompt(space: dict, char: dict) -> str:
    """Text-to-image prompt for the main view of a space."""
    name  = space.get("name", "room")
    desc  = (space.get("description") or "").strip()
    city  = (profile_mod.get(char).get("city") or "Delhi").strip()
    desc_part = f" {desc}." if desc else "."
    return (
        f"Interior photography of a {name} in a {city} apartment.{desc_part} "
        f"Wide establishing shot, whole room visible, empty of people. "
        f"{STYLE} {NO_TEXT}"
    )


def _corner_prompt(space: dict, corner_desc: str) -> str:
    name = space.get("name", "room")
    return (
        f"The same {name}. Camera placed at the {corner_desc}. "
        f"Keep all furniture, decor, colours and lighting identical to the reference picture. "
        f"Empty of people. {NO_TEXT}"
    )


def _get_space(char: dict, space_name: str) -> dict:
    prof = profile_mod.get(char)
    for s in (prof.get("spaces") or []):
        if s.get("name", "").lower() == space_name.lower():
            return s
    raise store.CharError(f"space '{space_name}' not in profile")


def _approved_main(char_id: str, space_name: str) -> dict | None:
    key = _main_key(space_name)
    rows = [r for r in media.items(char_id, "space_gen", key) if r["approved"] and r["status"] == "done"]
    return rows[-1] if rows else None


async def generate_main(char_id: str, space_name: str, s: dict, key: str, progress=None,
                        instruction: str = "") -> dict:
    """Draw one new main-view candidate. Returns the media row."""
    from characters import studio as studio_mod

    char  = store.get(char_id)
    space = _get_space(char, space_name)
    mk    = _main_key(space_name)
    model = s.get("image_model") or "qwen-image-2.1"
    base, api_key = studio_mod._ctx(s, key)

    prompt = _build_prompt(space, char)
    if instruction:
        prompt = prompt.rstrip(". ") + f". {instruction.strip()}."
    body   = {"model": model, "prompt": prompt, "size": SIZE_MAIN, "n": 1}

    it = media.add(char_id, "space_gen", mk, status="running", meta={"prompt": prompt, "model": model})
    t0 = time.time()
    try:
        if progress:
            progress(0, 1, f"Drawing {space_name}…")
        data = await studio_mod._post_image("draw", body, [], base, api_key)
        rel  = f"space_gen/{mk}-a{it['attempt']}.png"
        (store.media_dir(char_id, "space_gen") / f"{mk}-a{it['attempt']}.png").write_bytes(data)
        it = media.update(it["id"], status="done", file=rel,
                          meta={"seconds_taken": round(time.time() - t0, 1), "prompt": prompt, "model": model})
        if progress:
            progress(1, 1, "done")
    except asyncio.CancelledError:
        media.update(it["id"], status="failed", meta={"error": "stopped"})
        raise
    except Exception as e:
        media.update(it["id"], status="failed",
                     meta={"error": str(e)[:300], "seconds_taken": round(time.time() - t0, 1)})
        raise
    return it


async def generate_corners(char_id: str, space_name: str, s: dict, key: str, progress=None,
                           instruction: str = "") -> dict:
    """Draw 4 corner views from the approved main image. Requires an approved main."""
    from characters import studio as studio_mod

    char  = store.get(char_id)
    space = _get_space(char, space_name)
    main  = _approved_main(char_id, space_name)
    if not main:
        raise store.CharError("approve the main view first before generating corner views")

    import config
    main_path = config.DATA_DIR / "media" / char_id / main["file"]
    if not main_path.exists():
        raise store.CharError("approved main image file missing — regenerate the main view")

    model  = s.get("image_model") or "qwen-image-2.1"
    base, api_key = studio_mod._ctx(s, key)

    made, failed = 0, []
    total = len(_CORNERS)
    for i, (tag, corner_desc) in enumerate(_CORNERS):
        ck = _corner_key(space_name, tag)
        prompt = _corner_prompt(space, corner_desc)
        if instruction:
            prompt = prompt.rstrip(". ") + f". {instruction.strip()}."
        body   = {"model": model, "prompt": prompt, "size": SIZE_CORNER, "n": 1}

        it = media.add(char_id, "space_gen", ck, status="running",
                       meta={"prompt": prompt, "model": model, "corner": tag})
        t0 = time.time()
        try:
            if progress:
                progress(i, total, f"Corner {i + 1}/4…")
            ref_bytes = main_path.read_bytes()
            data = await studio_mod._post_image("edit", body, [ref_bytes], base, api_key)
            rel  = f"space_gen/{ck}-a{it['attempt']}.png"
            (store.media_dir(char_id, "space_gen") / f"{ck}-a{it['attempt']}.png").write_bytes(data)
            media.update(it["id"], status="done", file=rel,
                         meta={"seconds_taken": round(time.time() - t0, 1), "prompt": prompt, "model": model})
            made += 1
        except asyncio.CancelledError:
            media.update(it["id"], status="failed", meta={"error": "stopped"})
            raise
        except Exception as e:
            media.update(it["id"], status="failed",
                         meta={"error": str(e)[:300], "seconds_taken": round(time.time() - t0, 1)})
            failed.append({"corner": tag, "error": str(e)[:200]})

    if progress:
        progress(total, total, "done")
    return {"made": made, "failed": failed}


def approve_image(char_id: str, space_name: str, item_id: str) -> dict:
    """Approve a space image. If it is a main view, write ref_image to the profile space entry."""
    it = media.get(item_id)
    if not it or it["plan_id"] != char_id:
        raise store.CharError("picture not found")
    media.approve(item_id, True)
    # write ref_image on the profile space entry when approving the main view
    if it["key"] == _main_key(space_name):
        char = store.get(char_id)
        prof = profile_mod.get(char)
        spaces = prof.get("spaces") or []
        for sp in spaces:
            if sp.get("name", "").lower() == space_name.lower():
                sp["ref_image"] = it["file"]
                break
        profile_mod.patch(char, {"spaces": spaces})
        store.save(char)
    return media.get(item_id)


def list_images(char_id: str, space_name: str) -> dict:
    """Return {main: [...], corners: [...]} for a space."""
    mk  = _main_key(space_name)
    all_rows = media.items(char_id, "space_gen")
    main    = [r for r in all_rows if r["key"] == mk]
    corners = [r for r in all_rows if r["key"].startswith(f"space-{_slug(space_name)}-c")]
    corners.sort(key=lambda r: r["key"])
    return {"main": main, "corners": corners}
