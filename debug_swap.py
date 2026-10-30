"""
Diagnostic: runs exactly what the app runs for a face_into swap.
Shows every field sent to the gateway and the raw response.

Usage (on the remote server, app does NOT need to be running):
  .venv\Scripts\python.exe debug_swap.py <char_id> <ref_media_id> <portrait_media_id>

  char_id       — the character's id (ch-...)
  ref_media_id  — media id of the uploaded office-girl reference (mr-..., kind=char_ref)
  portrait_media_id — media id of the character portrait (mr-..., kind=gen)

Example: get the IDs from the DB or the URL in the browser.
"""
import asyncio, sys, time, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from story import settings as settings_mod
from story3 import store as media
from characters import edits, store as char_store

# ── patch _post_job to dump everything ──────────────────────────────────────
import httpx
import characters.studio as studio_mod

_orig_post_job = studio_mod._post_job

async def _debug_post_job(c, base, key, data, files, poll_s=4.0):
    print("\n=== REQUEST TO GATEWAY ===")
    print(f"  URL: {base}/images/edits")
    print(f"  Headers: Authorization: Bearer {key[:20]}... | Prefer: respond-async")
    print("  FORM FIELDS (data dict):")
    for k, v in data.items():
        print(f"    {k} = {v!r}")
    print("  FILES:")
    for field_name, (fname, fbytes, ctype) in files:
        print(f"    [{field_name}] filename={fname!r}, size={len(fbytes)} bytes, content_type={ctype!r}")

    t0 = time.time()
    hdr = {"Authorization": f"Bearer {key}", "Prefer": "respond-async"}
    r = await c.post(base + "/images/edits", headers=hdr, data=data, files=files)
    elapsed = time.time() - t0

    print(f"\n=== GATEWAY RESPONSE ({elapsed:.1f}s) ===")
    print(f"  Status: {r.status_code}")
    if r.status_code == 200:
        print("  → Sync 200: server processed immediately (NOT async job)")
        body = r.json()
        print(f"  Body keys: {list(body.keys())}")
        d = (body.get("data") or [{}])[0]
        if d.get("b64_json"):
            print(f"  Image returned: {len(d['b64_json'])} chars of b64 (~{len(d['b64_json'])*3//4//1024} KB)")
        else:
            print(f"  No image in data[0]: {d}")
        return d
    elif r.status_code == 202:
        job = r.json()["id"]
        print(f"  → Async 202: job id = {job}")
        print("  Polling...")
        url = base + "/jobs/" + job
        while True:
            await asyncio.sleep(poll_s)
            j = await c.get(url, headers={"Authorization": f"Bearer {key}"})
            body = j.json()
            st = body.get("status")
            elapsed2 = time.time() - t0
            print(f"    [{elapsed2:.0f}s] status={st}")
            if st == "succeeded":
                result = (body.get("result") or {})["data"][0]
                print(f"  ✓ DONE in {elapsed2:.0f}s, image size: ~{len(result.get('b64_json',''))*3//4//1024} KB")
                return result
            if st in ("failed", "cancelled"):
                err = str(body.get("error") or "")
                print(f"  ✗ FAILED: {err}")
                raise RuntimeError(f"job {st}: {err}")
    else:
        print(f"  ✗ Unexpected status: {r.text[:300]}")
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")

studio_mod._post_job = _debug_post_job

# ── also patch _post_image to print what it gets ────────────────────────────
from story3 import scenes

_orig_form = scenes._form

def _debug_form(model, prompt, size, seed, files, steps=None, lora=None):
    data, parts = _orig_form(model, prompt, size, seed, files, steps, lora)
    return data, parts

scenes._form = _debug_form

# ────────────────────────────────────────────────────────────────────────────

async def main():
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)

    char_id, ref_id, portrait_id = sys.argv[1], sys.argv[2], sys.argv[3]

    s = settings_mod.get()
    key = settings_mod.api_key()
    print(f"Gateway: {s['base_url']}")
    print(f"API key: {key[:20]}...")

    char = char_store.get(char_id)
    print(f"Character: {char['name']} | model: {char['render']['model']}")

    ref = media.get(ref_id)
    portrait = media.get(portrait_id)
    if not ref:
        print(f"ERROR: media id {ref_id!r} not found")
        sys.exit(1)
    if not portrait:
        print(f"ERROR: media id {portrait_id!r} not found")
        sys.exit(1)

    print(f"Ref photo: {ref['file']} (kind={ref['kind']})")
    print(f"Portrait:  {portrait['file']} (kind={portrait['kind']})")

    ref_path = media.path_of(ref)
    portrait_path = media.path_of(portrait)
    print(f"Ref path exists: {ref_path.exists()} ({ref_path})")
    print(f"Portrait path exists: {portrait_path.exists()} ({portrait_path})")

    req = edits.build(
        char,
        base=ref,           # image 1 = target (office girl, body kept)
        preset="custom",
        value="My face into reference photo",
        attempt=99,
        extra=[portrait],   # image 2 = face source (green kurta, face taken)
        swap="bfs-head-swap",
    )

    print(f"\nBuild result:")
    print(f"  how = {req['how']}")
    print(f"  body = {json.dumps({k: v for k, v in req['body'].items() if k != 'prompt'}, indent=2)}")
    print(f"  prompt (first 100): {req['body'].get('prompt','')[:100]!r}")
    print(f"  refs: {[str(p) for p in req['refs']]}")

    base_url = s["base_url"].rstrip("/")
    from characters import studio as stu
    import base64
    result_bytes = await stu._post_image(req["how"], req["body"], req["refs"], base_url, key)
    out = Path("debug_swap_result.png")
    out.write_bytes(result_bytes)
    print(f"\n✓ Result saved to {out.resolve()} ({len(result_bytes)//1024} KB)")


if __name__ == "__main__":
    asyncio.run(main())
