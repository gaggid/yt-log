"""Duplicate and near-duplicate pictures (docs/TASKS_quality_overhaul.md task 4.5). Two scenes that came out as almost the same picture are the same shot shown twice, which is what a
viewer calls repetitive. Each picture gets a small perceptual fingerprint (a 16x16 grey average hash and a coarse colour histogram); a pair is a duplicate when both are close.
`find` returns the pairs; the later scene of a pair is the one to draw again, with a note that says what to change."""
from PIL import Image

from story2 import storyboard

from . import store

HASH_SIDE = 16
MAX_BITS = 18                       # of 256 bits: pictures that differ in more than this are not the same picture
MAX_HIST = 0.10                     # mean absolute difference of the normalised colour histograms


def fingerprint(path) -> tuple[int, list[float]]:
    im = Image.open(path).convert("RGB")
    g = im.convert("L").resize((HASH_SIDE, HASH_SIDE), Image.BILINEAR)
    px = list(g.getdata())
    mean = sum(px) / len(px)
    bits = 0
    for v in px:
        bits = (bits << 1) | (1 if v >= mean else 0)
    small = im.resize((32, 32), Image.BILINEAR)
    hist = [0.0] * 12                                                   # 4 bins per colour channel
    for r, gr, b in small.getdata():
        hist[r // 64] += 1
        hist[4 + gr // 64] += 1
        hist[8 + b // 64] += 1
    n = 32 * 32
    return bits, [h / n for h in hist]


def distance(a: tuple, b: tuple) -> tuple[int, float]:
    return bin(a[0] ^ b[0]).count("1"), sum(abs(x - y) for x, y in zip(a[1], b[1])) / len(a[1])


def same(a: tuple, b: tuple) -> bool:
    bits, hist = distance(a, b)
    return bits <= MAX_BITS and hist <= MAX_HIST


def _pic(plan_id: str, scene_id: str):
    done = [i for i in store.items(plan_id, "scene", scene_id) if i["status"] == "done" and i["file"] and store.path_of(i).is_file()]
    done.sort(key=lambda i: (bool(i["approved"]), i["attempt"]), reverse=True)
    return done[0] if done else None


def find(plan_id: str) -> list[dict]:
    """Pairs of scenes whose pictures are near-duplicates, as {scene, earlier, bits, hist, why}; `scene` is the later one (the one to draw again)."""
    scenes = sorted(storyboard.get_scenes(plan_id), key=lambda s: (s["start_s"], s["seq"]))
    prints = []
    for sc in scenes:
        it = _pic(plan_id, sc["id"])
        if it:
            prints.append((sc, fingerprint(store.path_of(it))))
    out = []
    for i, (sc, fp) in enumerate(prints):
        for earlier, fe in prints[:i]:
            if sc["data"].get("variant_of") == earlier["id"]:
                continue                                                # a second angle of the same moment is meant to look alike
            if same(fp, fe):
                bits, hist = distance(fp, fe)
                out.append({"scene": sc["id"], "earlier": earlier["id"], "bits": bits, "hist": round(hist, 3),
                            "why": "almost the same picture as the scene at %d:%02d: change the place, the camera distance or angle, or what happens" % (earlier["start_s"] // 60, earlier["start_s"] % 60)})
                break
    return out


def note_for(plan_id: str, scene_id: str) -> str:
    """The change request for redrawing a scene that duplicates another picture."""
    hit = next((d for d in find(plan_id) if d["scene"] == scene_id), None)
    return hit["why"] if hit else ""
