"""
Direct face-swap test — mirrors test_voice.py but for images/edits.
Hits the gateway DIRECTLY (no app code in the HTTP path) so we can
confirm the request format independently of the app.

Usage:
  .venv\Scripts\python.exe debug_swap.py <image1_path> <image2_path>

  image1 = target photo  (scene to keep — e.g. office girl)
  image2 = face source   (face to use  — e.g. green kurta portrait)

Result saved to debug_swap_result.png

Example:
  .venv\Scripts\python.exe debug_swap.py "C:/Users/.../Downloads/office.jpg" "C:/Users/.../Downloads/portrait.png"
"""
import asyncio
import base64
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from story import settings as settings_mod

BASE_URL: str = settings_mod.get()["base_url"].rstrip("/")
API_KEY:  str = settings_mod.api_key()

LORA   = "bfs-head-swap"
MODEL  = "qwen-image-2.1"
PROMPT = (
    "Change only the face. Keep the clothes, jewellery, neck, body, pose, "
    "lighting and background of image 1 exactly as they are. "
    "Do not copy any clothes or jewellery from image 2."
)
POLL_S  = 4
LIMIT_S = 300


def _mime(path: Path) -> str:
    return "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"


async def _wait_job(client: httpx.AsyncClient, job_id: str) -> bytes:
    url = BASE_URL + "/jobs/" + job_id
    t0 = time.time()
    while time.time() - t0 < LIMIT_S:
        r = await client.get(url, headers={"Authorization": f"Bearer {API_KEY}"})
        j = r.json()
        st = j.get("status", "")
        elapsed = time.time() - t0
        print(f"  [{elapsed:.0f}s] status={st}")
        if st == "succeeded":
            data = (j.get("result") or j)["data"][0]
            return base64.b64decode(data["b64_json"])
        if st in ("failed", "cancelled", "canceled", "error"):
            raise RuntimeError(f"job {st}: {j.get('error', '')}")
        await asyncio.sleep(POLL_S)
    raise RuntimeError("timed out")


async def swap(img1: Path, img2: Path) -> bytes:
    """POST images/edits with bfs-head-swap LoRA, Prefer: respond-async."""
    data = {
        "model":           MODEL,
        "n":               "1",
        "response_format": "b64_json",
        "prompt":          PROMPT,
        "lora":            LORA,
    }
    files = [
        ("image[]", (img1.name, img1.read_bytes(), _mime(img1))),
        ("image[]", (img2.name, img2.read_bytes(), _mime(img2))),
    ]
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Prefer":        "respond-async",
    }

    print(f"Gateway : {BASE_URL}")
    print(f"API key : {API_KEY[:20]}...")
    print(f"Fields  : {list(data.keys())}")
    print(f"Image 1 : {img1.name}  ({img1.stat().st_size // 1024} KB)  {_mime(img1)}")
    print(f"Image 2 : {img2.name}  ({img2.stat().st_size // 1024} KB)  {_mime(img2)}")
    print()

    t0 = time.time()
    async with httpx.AsyncClient(timeout=LIMIT_S) as client:
        r = await client.post(
            BASE_URL + "/images/edits",
            headers=headers,
            data=data,
            files=files,
        )
        print(f"Response: HTTP {r.status_code}  ({time.time() - t0:.1f}s)")

        if r.status_code == 202:
            job_id = r.json()["id"]
            print(f"Job id  : {job_id}")
            print("Polling ...")
            return await _wait_job(client, job_id)

        if r.status_code == 200:
            print("→ Sync 200 (no async job — server processed immediately)")
            j = r.json()
            return base64.b64decode(j["data"][0]["b64_json"])

        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")


async def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    img1 = Path(sys.argv[1])
    img2 = Path(sys.argv[2])
    for p in (img1, img2):
        if not p.exists():
            print(f"ERROR: file not found: {p}")
            sys.exit(1)

    result = await swap(img1, img2)

    out = Path("debug_swap_result.png")
    out.write_bytes(result)
    print(f"\n✓  Saved → {out.resolve()}  ({len(result) // 1024} KB)")


if __name__ == "__main__":
    asyncio.run(main())
