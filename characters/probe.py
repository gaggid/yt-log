"""C0: measure what the gateway's image models really do for characters, before the studio's defaults are trusted.

    .venv\\Scripts\\python.exe -m characters.probe                  # everything (about 15 pictures, 10-20 minutes)
    .venv\\Scripts\\python.exe -m characters.probe --only base,edit # chosen groups: base, edit, multi, drift, flux, tryon
    .venv\\Scripts\\python.exe -m characters.probe --model qwen-image-2.1

It draws one invented character, then edits that picture the ways the studio will (outfit, age, expression, a new environment), with one, two and three reference pictures, and
edits three times in a row against three times from the original to see how fast the face drifts. The chat model with vision answers "is this the same person?" for every result.
Pictures and `report.json` go to data/characters_probe/<time>/, and seconds per picture to data/characters_probe/timings.json. The gateway serves one request at a time."""
import argparse
import asyncio
import base64
import json
import time
from pathlib import Path

import httpx

import config
from story import llm, settings as settings_mod
from story2 import providers
from story3 import scenes

CHARACTER = ("A 30 year old Indian man, lean build of average height, medium brown skin, oval face with a short trimmed black beard, short wavy black hair, dark brown eyes, "
             "a mustard yellow delivery jacket over a grey t-shirt, dark blue jeans, white sneakers, a black wristwatch. A calm, tired expression.")
LOOK = "Cinematic painted film still, realistic proportions and natural face, soft grounded light, shallow depth of field. No text, letters, logos or watermarks."
KEEP = "Keep exactly the same man: same face, same beard, same hair, same skin tone and same build."
PLACE = ("An empty railway platform at dusk with a yellow painted edge line, steel pillars, a long row of green benches, warm lamps coming on and a dark blue sky. "
         "No people, no signs with words.")
SIZES = {"portrait": "1024x1024", "body": "720x1280", "place": "720x1280"}
EDITS = {                                  # name -> (which picture it is made from, the instruction)
    "outfit": ("body", f"Change only his clothes: he wears a dark green kurta and beige trousers with brown sandals, no jacket. {KEEP} Keep the background and the pose."),
    "age": ("portrait", "Make him about sixty years old: grey hair and beard, deeper lines, same warm light. Same man, only older. Keep the background and the framing."),
    "expression": ("portrait", f"Change only his expression to a wide, genuine laugh. {KEEP} Keep the clothes, the background and the framing."),
    "pose": ("body", f"Show the same man walking away from the camera and glancing back over his left shoulder. {KEEP} Keep the clothes."),
    "environment": ("body", f"Put the same man on a crowded railway platform at dusk, people blurred in the background, warm lamps. {KEEP} Keep the same clothes."),
}
GARMENT = ("A flat lay product photograph of a deep maroon silk sherwani with gold embroidery on the collar and cuffs and matching cream trousers, laid flat on a plain light grey surface, "
           "nothing else in the frame. No people, no mannequin, no text.")
TRYON = ("Dress the man from the first picture in the clothing shown in the second picture, exactly as it appears: same colours, fabric, embroidery and cut. Replace his old clothes completely. "
         f"{KEEP} Keep the background and the pose.")
MULTI_2 = f"Put the man from the first picture into the place from the second picture: he stands on the platform near the yellow line, looking at the track. {KEEP} Keep his clothes."
MULTI_3 = f"Using the man's face from the first picture and his full body from the second, put him in the place from the third picture, leaning on a steel pillar. {KEEP} Keep his clothes."
CHAIN = ["outfit", "environment", "expression"]       # drift test: these three, one after the other
CHAIN_STEP = {"outfit": EDITS["outfit"][1], "environment": EDITS["environment"][1],
              "expression": f"Change only his expression to a wide, genuine laugh. {KEEP} Keep the clothes and the background."}


def base_prompt(which: str) -> str:
    frame = {"portrait": "Head and shoulders portrait, facing the camera, plain soft grey studio background.",
             "body": "Full body standing front view, whole figure visible from head to feet, plain soft grey studio background."}[which]
    return f"{frame} {CHARACTER} {LOOK}"


def place_prompt() -> str:
    return f"{PLACE} {LOOK}"


def latest_base(name: str) -> Path | None:
    """The newest picture called `name` from an earlier run, so one group can be run alone."""
    found = sorted((config.DATA_DIR / "characters_probe").glob(f"*/{name}"))
    return found[-1] if found else None


def out_dir() -> Path:
    d = config.DATA_DIR / "characters_probe" / time.strftime("%Y%m%d-%H%M%S")
    d.mkdir(parents=True, exist_ok=True)
    return d


def summarise(report: list[dict]) -> dict:
    """Seconds per kind of picture and the mean identity score per edit kind, for the run log and the studio's estimates."""
    secs: dict[str, list[float]] = {}
    ident: dict[str, list[float]] = {}
    for r in report:
        if not r.get("ok"):
            continue
        secs.setdefault(r["kind"], []).append(r["seconds"])
        if r.get("identity") and r["identity"].get("score") is not None:
            ident.setdefault(r["kind"], []).append(r["identity"]["score"])
    return {"seconds": {k: round(sum(v) / len(v), 1) for k, v in secs.items()}, "identity": {k: round(sum(v) / len(v), 1) for k, v in ident.items()}}


class Probe:
    def __init__(self, s: dict, key: str, d: Path, model: str):
        self.s, self.key, self.d, self.model = s, key, d, model
        self.base = s["base_url"].rstrip("/")
        self.report: list[dict] = []
        self.pics: dict[str, Path | None] = {}
        self.loras: dict[str, dict] = {}

    async def _call(self, model: str, prompt: str, size: str, refs: list[Path], seed: int, lora=None) -> bytes:
        """One picture. The gateway serves one request per key, so when the app is busy with its own job this waits for a free slot (up to an hour) and times only the request itself."""
        waited = 0
        while True:
            self.t_start = time.time()
            try:
                async with httpx.AsyncClient(timeout=900) as c:
                    if refs:
                        data, files = scenes._form(model, prompt, size, seed, refs)
                        if lora:
                            data["lora"] = lora if isinstance(lora, str) else json.dumps(lora)
                        img = await scenes._post(c, self.base + "/images/edits", self.key, data=data, files=files)
                    else:
                        img = await scenes._post(c, self.base + "/images/generations", self.key,
                                                 json={"model": model, "prompt": prompt, "size": size, "n": 1, "seed": seed, "response_format": "b64_json", **({"lora": lora} if lora else {})})
                return base64.b64decode(img["b64_json"])
            except scenes.MediaError as e:
                if "concurrency_limit" not in str(e) or waited >= 3600:
                    raise
                waited += 20
                await asyncio.sleep(20)

    async def _send(self, kind: str, name: str, model: str, prompt: str, size: str, refs: list[Path], seed: int, canon: Path | None, lora=None) -> Path | None:
        print(f"[{name}] {kind} on {model} ({size}, {len(refs)} reference{'s' if len(refs) != 1 else ''}) ...", flush=True)
        try:
            raw = await self._call(model, prompt, size, refs, seed, lora)
        except Exception as e:  # noqa: BLE001 - the report says what failed
            print(f"[{name}] FAILED: {e}", flush=True)
            self.report.append({"name": name, "kind": kind, "model": model, "ok": False, "error": str(e)[:300]})
            return None
        secs = time.time() - self.t_start
        path = self.d / f"{name}.png"
        path.write_bytes(raw)
        row = {"name": name, "kind": kind, "model": model, "ok": True, "seconds": round(secs, 1), "size": size, "refs": len(refs), "bytes": len(raw), "prompt": prompt[:400]}
        if canon is not None:
            row["identity"] = await self.identity(canon, path)
        self.report.append(row)
        print(f"[{name}] {secs:.0f}s" + (f", same person {row['identity'].get('score')}/10" if row.get("identity") else ""), flush=True)
        return path

    async def identity(self, canon: Path, pic: Path) -> dict:
        """The chat model with vision compares the face, hair, beard and build of two pictures (clothes and background are allowed to differ)."""
        msg = [{"role": "user", "content": [
            {"type": "text", "text": "Picture 1 is the reference character. Picture 2 should show the SAME man, possibly in other clothes, another place, another age or expression. "
                                     "Compare only the person: face shape, eyes, nose, beard, hair, skin tone, build. Ignore clothes and background. Be strict. "
                                     'Reply with JSON only: {"same_person": true or false, "score": 0-10, "differences": ["short, concrete"]}. '
                                     "10 = clearly identical person, 7 = same person with small changes, 4 = looks related, 0 = a different person. "
                                     "If picture 2 is meant to be older, judge whether it is the same man aged."},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(canon.read_bytes()).decode()}},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(pic.read_bytes()).decode()}}]}]
        t0 = time.time()
        try:
            for _ in range(180):                                                  # the gateway serves one request per key: wait while the app is using it
                async with httpx.AsyncClient(timeout=300) as c:
                    r = await c.post(self.base + "/chat/completions", headers={"Authorization": f"Bearer {self.key}"},
                                     json={**llm.model_field(self.s), "messages": msg, "max_tokens": 1500, "temperature": 0})
                if r.status_code != 429:
                    break
                await asyncio.sleep(20)
            if r.status_code != 200:
                return {"error": f"{r.status_code} {r.text[:120]}"}
            j = llm.parse_json(r.json()["choices"][0]["message"].get("content") or "")
            return {"same_person": bool(j.get("same_person")), "score": max(0.0, min(10.0, float(j.get("score", 0)))),
                    "differences": [str(x) for x in (j.get("differences") or [])][:5], "vision_s": round(time.time() - t0, 1)}
        except Exception as e:  # noqa: BLE001
            return {"error": f"{type(e).__name__}: {e}"[:200]}

    async def base_group(self) -> None:
        for which in ("portrait", "body"):
            self.pics[which] = await self._send("generate_" + SIZES[which], which, self.model, base_prompt(which), SIZES[which], [], 7, None)
        self.pics["place"] = await self._send("generate_place", "place", self.model, place_prompt(), SIZES["place"], [], 11, None)

    async def edit_group(self) -> None:
        for name, (src, text) in EDITS.items():
            canon = self.pics.get(src)
            if canon:
                self.pics["edit_" + name] = await self._send("edit_1ref", "edit-" + name, self.model, text, SIZES[src], [canon], 21, canon)

    async def multi_group(self) -> None:
        p, b, pl = self.pics.get("portrait"), self.pics.get("body"), self.pics.get("place")
        if b and pl:
            await self._send("edit_2ref", "multi-2refs", self.model, MULTI_2, SIZES["body"], [b, pl], 31, b)
        if p and b and pl:
            await self._send("edit_3ref", "multi-3refs", self.model, MULTI_3, SIZES["body"], [p, b, pl], 32, b)

    async def drift_group(self) -> None:
        """Each step edits the previous result (chain). The step-3 picture is compared with the original; the same three changes made from the original in one go are the control."""
        cur = self.pics.get("body")
        if not cur:
            return
        for i, step in enumerate(CHAIN, 1):
            cur = await self._send(f"chain_{i}", f"chain-{i}-{step}", self.model, CHAIN_STEP[step], SIZES["body"], [cur], 40 + i, self.pics["body"])
            if not cur:
                return
        control = ("Change his clothes to a dark green kurta and beige trousers, put him on a crowded railway platform at dusk with people blurred in the background, "
                   f"and give him a wide genuine laugh. {KEEP}")
        await self._send("control_all_at_once", "control-all-from-canon", self.model, control, SIZES["body"], [self.pics["body"]], 45, self.pics["body"])

    async def flux_group(self, flux: str) -> None:
        canon = self.pics.get("body")
        if canon:
            await self._send("edit_1ref_flux", "flux-outfit", flux, EDITS["outfit"][1], SIZES["body"], [canon], 21, canon)

    async def tryon_group(self, garment: Path | None) -> None:
        """Clothes from a picture: the character's full-body canon plus a picture of a garment (the user's own, else one drawn flat on a table) -> the character wearing it."""
        body = self.pics.get("body") or latest_base("body.png")
        if not body:
            print("[tryon] skipped: no body.png (run the base group first)", flush=True)
            return
        self.pics["body"] = body
        if garment is None:
            garment = await self._send("generate_garment", "garment", self.model, f"{GARMENT} {LOOK}", SIZES["place"], [], 51, None)
        if garment:
            await self._send("tryon_2ref", "tryon-garment", self.model, TRYON, SIZES["body"], [body, garment], 52, body)

    async def lora_group(self, name: str, strength: float) -> None:
        """A realism (or any) LoRA: the same prompt and seed with and without it, drawn with the `lora` field; then an edit with the inline tag, because the docs show `lora` only for generations."""
        control = self.pics.get("body") or latest_base("body.png")
        if not control:
            print("[lora] skipped: no body.png (run the base group first)", flush=True)
            return
        self.pics["body"] = control
        trigger = (self.loras.get(name) or {}).get("trigger", "")
        drawn = await self._send("generate_lora_field", f"lora-{name}-draw", self.model, f"{trigger} {base_prompt('body')}".strip(), SIZES["body"], [], 7, control, lora=[{"name": name, "strength": strength}])
        edited = await self._send("edit_lora_tag", f"lora-{name}-edit-tag", self.model, f"{trigger} {EDITS['outfit'][1]} <lora:{name}:{strength}>".strip(), SIZES["body"], [control], 21, control)
        print("[lora] compare by eye: body.png (no extra LoRA), the -draw and -edit-tag pictures; ok" if drawn and edited else "[lora] something failed, see the report", flush=True)

    async def lorafield_group(self, name: str) -> None:
        """Do edits keep a realistic picture realistic, and does the `lora` form field of /images/edits apply a LoRA? Edit the realistic picture from the lora group twice: plain, and with the field."""
        src = latest_base(f"lora-{name}-draw.png")
        if not src:
            print("[lorafield] skipped: run --only lora first", flush=True)
            return
        trigger = (self.loras.get(name) or {}).get("trigger", "")
        await self._send("edit_real_plain", "realedit-plain", self.model, EDITS["outfit"][1], SIZES["body"], [src], 21, src)
        await self._send("edit_real_field", "realedit-field", self.model, f"{trigger} {EDITS['outfit'][1]}".strip(), SIZES["body"], [src], 21, src, lora=name)

    def save(self, models_seen: list[str]) -> None:
        summary = summarise(self.report)
        (self.d / "report.json").write_text(json.dumps({"models": models_seen, "rows": self.report, "summary": summary}, indent=1, ensure_ascii=False), encoding="utf-8")
        path = config.DATA_DIR / "characters_probe" / "timings.json"
        cur = {}
        try:
            cur = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        cur.update({"measured": time.strftime("%Y-%m-%d"), "model": self.model, **summary})
        path.write_text(json.dumps(cur, indent=1), encoding="utf-8")


async def main(args) -> None:
    s = settings_mod.get()
    key = settings_mod.api_key()
    base = s["base_url"].rstrip("/")
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(base + "/models", headers={"Authorization": f"Bearer {key}"})
    listed = r.json().get("data", []) if r.status_code == 200 else []
    images = [m for m in listed if "images.generations" in (m.get("capabilities") or [])]
    print("image models the key can use:", ", ".join(f"{m['id']} ({'edit' if 'images.edits' in (m.get('capabilities') or []) else 'no edit'})" for m in images) or "(none listed)", flush=True)
    model = args.model or providers.DEFAULT_MODEL
    only = set(args.only.split(",")) if args.only else {"base", "edit", "multi", "drift", "flux", "tryon"}
    pr_loras: dict[str, dict] = {}
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            lr = await c.get(base + "/images/loras", params={"model": args.model or providers.DEFAULT_MODEL}, headers={"Authorization": f"Bearer {key}"})
        pr_loras = {x["name"]: x for x in lr.json().get("data", [])}
        print("LoRAs attached to the model:", ", ".join(f"{x['name']} (strength {x.get('strength')}, trigger '{x.get('trigger', '')}')" for x in lr.json().get("data", [])) or "(none)",
              "| on by default:", lr.json().get("default"), flush=True)
    except Exception as e:  # noqa: BLE001
        print("LoRA listing failed:", e, flush=True)
    pr = Probe(s, key, out_dir(), model)
    pr.loras = pr_loras
    if only & {"base", "edit", "multi", "drift", "flux"}:
        await pr.base_group()
    if "edit" in only:
        await pr.edit_group()
    if "multi" in only:
        await pr.multi_group()
    if "drift" in only:
        await pr.drift_group()
    if "lora" in only:
        if not args.lora:
            print("[lora] skipped: give the LoRA's name with --lora (see GET /v1/images/loras?model=...)", flush=True)
        else:
            await pr.lora_group(args.lora, args.lora_strength)
    if "lorafield" in only:
        await pr.lorafield_group(args.lora or "purelens-realism")
    if "tryon" in only:
        await pr.tryon_group(Path(args.garment) if args.garment else None)
    flux = next((m["id"] for m in images if "flux" in m["id"] and "images.edits" in (m.get("capabilities") or [])), "")
    if "flux" in only and flux:
        await pr.flux_group(flux)
    pr.save([m["id"] for m in images])
    print("\nreport:", pr.d / "report.json")
    for r in pr.report:
        ident = r.get("identity") or {}
        print(" ", r["name"], "-", (f"{r['seconds']}s" + (f", identity {ident.get('score')}/10 {ident.get('differences', [])[:2]}" if ident else "") if r["ok"] else "FAILED " + r["error"][:100]))
    print("summary:", json.dumps(summarise(pr.report)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="comma list of: base,edit,multi,drift,flux,tryon (tryon alone reuses the newest body.png)")
    ap.add_argument("--lora", help="the name of a LoRA attached to the model (for the lora group: --only lora --lora NAME)")
    ap.add_argument("--lora-strength", type=float, default=0.8)
    ap.add_argument("--garment", help="a picture of clothes for the tryon test (else one is drawn)")
    ap.add_argument("--model", help="the image model to test (default: the app's default)")
    asyncio.run(main(ap.parse_args()))
