"""A record of what went to the image model and what came back, one JSON line per picture in data/logs/char_requests.jsonl (to check a result against its inputs).
Pictures are named by media id and file path with a hash, never copied; the "diff" numbers say how close the result is to each picture sent (0 = identical; a correct swap is close to picture 1 and far from picture 2, so a result near 0 against picture 1 means the original came back)."""
import hashlib
import json
import time
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

LOG = Path(__file__).resolve().parent.parent / "data" / "logs" / "char_requests.jsonl"


def _sha(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()[:12]


def _thumb(src) -> Image.Image:
    im = Image.open(src).convert("L")
    return im.resize((96, 96))


def _diff(a: Image.Image, b: Image.Image) -> float:
    return round(ImageStat.Stat(ImageChops.difference(a, b)).mean[0], 1)


def record(item: dict, req: dict, data: bytes | None, error: str = "", seconds: float = 0.0) -> None:
    """Never raises: a log problem must not fail a picture."""
    try:
        import io
        refs = []
        for rid, p in zip(req["ref_ids"] + [""] * len(req["refs"]), req["refs"]):
            b = Path(p).read_bytes()
            with Image.open(io.BytesIO(b)) as im:
                size = im.size
            refs.append({"position": len(refs) + 1, "id": rid, "file": str(p), "sha1": _sha(b), "bytes": len(b), "size": list(size)})
        body = {k: v for k, v in req["body"].items() if k != "prompt"}
        rec = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "item": item["id"], "plan": item["plan_id"], "kind": item["kind"], "key": item["key"], "attempt": item["attempt"],
               "op": req["meta"].get("op") or req["meta"].get("view"), "swap": req["meta"].get("swap"), "body": body, "prompt": req["body"].get("prompt", ""),
               "sent": refs, "seconds": round(seconds, 1), "error": error}
        if data:
            out = Image.open(io.BytesIO(data))
            rec["result"] = {"sha1": _sha(data), "bytes": len(data), "size": list(out.size)}
            small = out.convert("L").resize((96, 96))
            rec["diff_to_sent"] = [_diff(small, _thumb(r["file"])) for r in refs]
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass
