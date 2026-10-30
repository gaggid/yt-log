"""What the studio does: fill a character's slots from an idea or a picture (chat model), draw candidates, make the sheet from the canon, approve canon, duplicate. Gateway calls are one at
a time (the app's job lock); each picture is saved the moment it arrives as a numbered attempt, a failed one is recorded and the job goes on."""
import asyncio
import base64
import io
import time

import httpx
from pydantic import BaseModel, ConfigDict
from PIL import Image

from story import llm, settings as settings_mod
from story2 import describe
from story3 import scenes, store as media
from story3.voice import MediaError

from . import render, requests as R, store

TIMEOUT_S = 900
_listing_cache: dict[str, tuple[float, dict]] = {}


def _client(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout)


def _ctx(s: dict | None, key: str) -> tuple[str, str]:
    s = s or settings_mod.get()
    return s["base_url"].rstrip("/"), key or settings_mod.api_key()


# ── what the gateway offers ─────────────────────────────────────────────────

def lora_listing(model: str, s: dict | None = None, key: str = "", ttl: float = 60.0) -> dict:
    """{name: {strength, trigger, description}} of the LoRAs attached to `model` on the gateway ({} when it cannot be asked). Cached for a minute."""
    hit = _listing_cache.get(model)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    base, api_key = _ctx(s, key)
    try:
        r = httpx.get(base + "/images/loras", params={"model": model}, headers={"Authorization": f"Bearer {api_key}"}, timeout=5)
        r.raise_for_status()
        data = {x["name"]: x for x in r.json().get("data", [])}
        data["__default__"] = {"names": r.json().get("default", [])}
    except Exception:  # noqa: BLE001 - the studio works without the listing
        data = {}
    _listing_cache[model] = (time.time(), data)
    return data


def lora_names(listing: dict) -> list[str]:
    return [k for k in listing if k != "__default__"]


# ── slots from an idea or a picture ─────────────────────────────────────────

class SlotsOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    slots: dict[str, str]
    name: str = ""
    personality: str = ""


SLOTS_SYSTEM = """[TASK:char_slots]
You design one {kind} for a video studio from a short idea. Reply with ONLY a JSON object: {{"name": "...", "personality": "one line", "slots": {{{keys}}}}}.
Every slot gets a concrete value an image model can draw exactly (colours, materials, counts, lengths); never a vague word such as normal, average, typical, casual, nice or beautiful.
Slots:
{hints}
Rules: invented people are Indian unless the idea says otherwise; "accessories" may be the word none; no brand names, no logos, no readable text on clothes; nothing graphic.
"personality" is a short phrase for the mood the face and posture usually carry (it is not drawn as text)."""


async def suggest_slots(idea: str, kind: str, backend, s: dict | None = None, current: dict | None = None) -> dict:
    """The chat model fills every slot from the idea (and keeps the slots the person already wrote when `current` is given)."""
    hints = describe.hints(kind)
    system = SLOTS_SYSTEM.replace("{kind}", kind).replace("{keys}", ", ".join(f'"{k}": "..."' for k in hints)).replace("{hints}", "\n".join(f"- {k}: {h}" for k, h in hints.items())).replace("{{", "{").replace("}}", "}")
    caller = llm.JsonCaller(backend, s)

    def check(out: SlotsOut) -> None:
        gaps = describe.missing(kind, out.slots)
        if gaps and not caller.last_attempt:
            raise ValueError("fill these slots with concrete values: " + ", ".join(gaps))

    kept = describe.clean(current)
    user = f"IDEA: {idea.strip()}" + (f"\nAlready decided by the person (keep exactly): {kept}" if kept else "")
    res = await caller.call(system, user, SlotsOut, validate=check)
    slots = describe.clean({k: v for k, v in res.value.slots.items() if k in hints})
    slots.update(kept)
    return {"slots": slots, "name": res.value.name.strip(), "personality": res.value.personality.strip(), "gaps": describe.missing(kind, slots)}


PHOTO_PROMPT = ("Read the person in this picture into a design sheet for an artist. Reply with ONLY JSON: {{\"slots\": {{{keys}}}, \"personality\": \"one line\"}}. "
                "Slots:\n{hints}\nUse concrete values (colours, lengths). Describe only what is visible; if something is not visible write a plausible concrete value.")


async def read_photo(path, s: dict | None = None, key: str = "") -> dict:
    """The chat model with vision reads a photo into slots."""
    s = s or settings_mod.get()
    hints = describe.hints("person")
    text = PHOTO_PROMPT.replace("{keys}", ", ".join(f'"{k}": "..."' for k in hints)).replace("{hints}", "\n".join(f"- {k}: {h}" for k, h in hints.items())).replace("{{", "{").replace("}}", "}")
    b64 = base64.b64encode(open(path, "rb").read()).decode()
    msg = [{"role": "user", "content": [{"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}}]}]
    async with _client(300) as c:
        r = await c.post(s["base_url"].rstrip("/") + "/chat/completions", headers={"Authorization": f"Bearer {key or settings_mod.api_key()}"},
                         json={**llm.model_field(s), "messages": msg, "max_tokens": 2000, "temperature": 0.2})
    if r.status_code != 200:
        raise MediaError(f"the picture could not be read ({r.status_code}): {r.text[:160]}")
    j = llm.parse_json(r.json()["choices"][0]["message"].get("content") or "")
    return {"slots": describe.clean({k: v for k, v in (j.get("slots") or {}).items() if k in hints}), "personality": str(j.get("personality") or "").strip()}


def save_photo(char_id: str, raw: bytes) -> str:
    """Keep an uploaded picture of a person (JPEG, at most 2048 px) under the character's folder; returns its path relative to that folder."""
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    im.thumbnail((2048, 2048))
    rel = f"source/photo-{int(time.time())}.jpg"
    p = store.media_dir(char_id, "source") / rel.split("/", 1)[1]
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=94)
    p.write_bytes(buf.getvalue())
    return rel


# ── drawing ─────────────────────────────────────────────────────────────────

async def _post_image(how: str, body: dict, refs: list, base: str, key: str) -> bytes:
    async with _client(TIMEOUT_S) as c:
        if how == "edit":
            data, files = scenes._form(body["model"], body["prompt"], body["size"], body["seed"], refs)
            img = await scenes._post(c, base + "/images/edits", key, data=data, files=files)
        else:
            img = await scenes._post(c, base + "/images/generations", key, json=body)
    if not img.get("b64_json"):
        raise MediaError("the image model sent no picture")
    return base64.b64decode(img["b64_json"])


def _kind_of(view: str) -> str:
    return store.GEN if R.VIEWS[view]["how"] == "draw" else store.SHEET


async def make_views(char_id: str, views: list[str], n: int = 1, progress=None, s: dict | None = None, key: str = "", seed: int | None = None, extra: str = "") -> dict:
    """Draw `n` new attempts of each view, one request at a time. A failed picture is recorded and the job goes on (it stops when the gateway is not reachable)."""
    base, api_key = _ctx(s, key)
    char = store.get(char_id)
    listing = lora_listing(char["render"]["model"], s, key) if char["render"]["loras"] else {}
    missing = [x for x in char["render"]["loras"] if listing and x["name"] not in lora_names(listing)]
    if missing:
        raise store.CharError("the gateway does not list the LoRA " + ", ".join(x["name"] for x in missing) + " for " + char["render"]["model"])
    total, done, made, failed = len(views) * n, 0, 0, []
    for view in views:
        for _ in range(n):
            if progress:
                progress(done, total, f"{R.VIEWS[view]['label']} ({done + 1} of {total})")
            done += 1
            kind = _kind_of(view)
            attempt = len(media.items(char_id, kind, view)) + 1
            try:
                req = R.build(char, view, attempt, listing, seed=None if seed is None else seed + attempt - 1, extra=extra)
            except store.CharError as e:
                failed.append({"view": view, "error": str(e)})
                break
            it = media.add(char_id, kind, view, 0, "running", req["meta"])
            t0 = time.time()
            try:
                data = await _post_image(req["how"], req["body"], req["refs"], base, api_key)
                rel = f"{kind}/{view}-a{it['attempt']}.png"
                (store.media_dir(char_id, kind) / f"{view}-a{it['attempt']}.png").write_bytes(data)
                media.update(it["id"], status="done", file=rel, meta={"seconds_taken": round(time.time() - t0, 1)})
                made += 1
            except asyncio.CancelledError:
                media.update(it["id"], status="failed", meta={"error": "stopped before it finished"})
                raise
            except Exception as e:  # noqa: BLE001 - recorded on the picture, shown on the screen
                media.update(it["id"], status="failed", meta={"error": str(e)[:300], "seconds_taken": round(time.time() - t0, 1)})
                failed.append({"view": view, "error": str(e)[:200]})
                if "not reachable" in str(e):
                    if progress:
                        progress(total, total, "stopped")
                    return {"made": made, "failed": failed}
    if progress:
        progress(total, total, "done")
    return {"made": made, "failed": failed}


def set_canon(char_id: str, item_id: str) -> dict:
    """Approve a picture. A portrait or full-body draw becomes the canon of that view (the render setting locks and the version goes up when the canon changes); a sheet picture is only approved."""
    char = store.get(char_id)
    it = media.get(item_id)
    if not it or it["plan_id"] != char_id or it["status"] != "done":
        raise store.CharError("that picture is not a finished picture of this character")
    media.approve(item_id, True)
    if it["kind"] == store.GEN and it["key"] in store.CANON_VIEWS[char["kind"]] and char["canon"].get(it["key"]) != item_id:
        char["canon"][it["key"]] = item_id
        char["version"] += 1
    return store.save(char)


def clear_canon(char_id: str, view: str) -> dict:
    char = store.get(char_id)
    iid = char["canon"].pop(view, None)
    if iid:
        media.approve(iid, False)
        char["version"] += 1
    return store.save(char)


def duplicate(char_id: str, name: str = "") -> dict:
    """A copy with the same slots and render setting but no pictures (a sibling, an older or younger version); the copy starts unlocked."""
    c = store.get(char_id)
    keep = {k: c[k] for k in ("idea", "slots", "personality", "render", "tags", "notes", "rights")}
    out = store.create(name or c["name"] + " (copy)", c["kind"], c["slots"], {k: v for k, v in keep.items() if k != "slots"})
    photo = store.photo_path(c)
    if photo:
        out["source_photo"] = save_photo(out["id"], photo.read_bytes())
        out = store.save(out)
    return out
