"""The second music engine of the Rain Channel: ACE-Step 1.5 (gateway model `acestep`, XL turbo, MIT licence), owner decision 2026-11-20.

Findings behind the recipe (measured against the YuE2 takes the owner liked, docs/RUN_LOG.md and the memory note on ACE-Step):
  * calm comes from words that remove the beat and darken the sound ("ambient, sleep music, tranquil ... beatless, dark, muffled, distant, soft dynamics, no vocals"), a MINOR key and
    56 bpm (the owner chose 56 over 64-76); naming one instrument as the lead of a melody makes it bright and pulsed again, so the instruments are layers named in the section tags;
  * a take is about 10 minutes (about one minute to make); section tags do not make it progress, but they do put a quiet intro first;
  * a seed can open with a loud, bass-heavy, clipping drone for 25 seconds (a 'scary grind' the owner heard): `assess` finds it and the cut is made when the takes are joined;
  * a seed can also come out too bright or too busy (upbeat): `make_take` tries up to ACE_TRIES seeds and keeps the one closest to the calm profile.
The caption and the sections are built in code from the session's music plan (models.ace_*), never by a chat model."""
import asyncio
import hashlib
import json
import subprocess

import numpy as np

import config
from story3 import music as music_mod, store as media
from story3.voice import MediaError

from . import models as M

SR = 22050
PROFILE = {"centroid": 730.0, "pulse": 0.48}          # the YuE2 takes the owner liked (brightness in Hz, how regular the onsets are 0..1)


def request(plan: dict, seed: int, k: int, total_s: float) -> dict:
    """The gateway request of take `k`: the caption names the layers, the lyrics field holds only section tags (the order of the layers rotates from take to take)."""
    dur = int(min(M.ACE_TAKE_S, max(60, total_s + 30)))
    return {"model": M.ACE_MODEL, "caption": plan.get("caption") or M.ace_caption(plan), "lyrics": M.ace_lyrics(plan, k), "instrumental": False, "bpm": int(plan.get("bpm") or M.ACE_BPM),
            "key_scale": plan.get("key") or M.ACE_KEYS[0], "time_signature": 4, "duration": dur, "seed": int(seed), "shift": 3, "thinking": False, "response_format": "mp3", "wait": False}


def _decode(path) -> np.ndarray:
    p = subprocess.run([config.FFMPEG, "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True)
    return np.frombuffer(p.stdout, np.float32)


def grind(x: np.ndarray) -> float:
    """Seconds to cut from the start when the take opens with a loud, clipping drone that then settles (0 = nothing to cut)."""
    if len(x) < SR * 60:
        return 0.0
    sec = np.array([float(np.sqrt(np.mean(x[i * SR:(i + 1) * SR] ** 2))) for i in range(60)])
    opening, rest = float(np.median(sec[:20])), float(np.median(sec[30:60]))
    if float(np.abs(x[:25 * SR]).max()) >= 0.98 and opening > 1.8 * rest:
        for t in range(15, 45):
            if float(sec[t:t + 5].max()) < 0.7 * opening:               # quiet for five seconds in a row: a low second inside a throbbing drone does not count
                return float(t)
        return 25.0
    return 0.0


def profile(x: np.ndarray) -> dict:
    """Brightness (centre of the spectrum, Hz) and pulse (how strongly note onsets repeat at one period, 45-120 bpm) of a take."""
    hop, win = 512, 2048
    fr = np.lib.stride_tricks.sliding_window_view(x, win)[::hop] * np.hanning(win)
    S = np.abs(np.fft.rfft(fr, axis=1))
    f = np.fft.rfftfreq(win, 1 / SR)
    centroid = float((S * f).sum() / (S.sum() + 1e-9))
    flux = np.maximum(0, np.diff(np.log1p(10 * S), axis=0)).sum(axis=1)
    flux = flux - flux.mean()
    ac = np.correlate(flux, flux, "full")[len(flux) - 1:]
    ac /= ac[0] + 1e-9
    fps = SR / hop
    lo, hi = int(fps * 60 / 120), int(fps * 60 / 45)
    return {"centroid": centroid, "pulse": float(ac[lo:hi].max())}


def assess(path) -> dict:
    """{trim_s, centroid, pulse, score, calm}: score 0 = the YuE2 profile; calm = not too bright and not too busy."""
    x = _decode(path)
    if len(x) < SR * 20:
        return {"trim_s": 0.0, "centroid": 0.0, "pulse": 0.0, "score": 9.0, "calm": False}
    p = profile(x)
    score = abs(p["centroid"] - PROFILE["centroid"]) / PROFILE["centroid"] + abs(p["pulse"] - PROFILE["pulse"]) / 0.5
    return {"trim_s": grind(x), "centroid": round(p["centroid"]), "pulse": round(p["pulse"], 2), "score": round(score, 2),
            "calm": p["centroid"] <= M.ACE_MAX_BRIGHT and p["pulse"] <= M.ACE_MAX_PULSE}


def _hash(body: dict) -> str:
    return hashlib.sha1(json.dumps({k: v for k, v in body.items() if k != "wait"}, sort_keys=True).encode()).hexdigest()[:12]


def _load_problem(err: str) -> bool:
    low = err.lower()
    return "failed to load" in low or "not ready" in low


async def _one(body: dict, s: dict, api_key: str) -> bytes:
    """One song from the gateway. A cold start of the model can fail (it took 3 to 6 minutes and the gateway gives up after 300 s; the next start finds the files in memory and is faster):
    that is waited out and tried again; any other error is final."""
    from shorts import wan
    for n in range(M.ACE_LOAD_TRIES):
        try:
            ans = await wan.submit(body, s["base_url"], api_key, True, "/audio/music")
            res = wan._result(ans) if ans.get("status") == "succeeded" or not ans.get("id") else await wan.wait(ans["id"], s["base_url"], api_key, 1800)
            return await wan.fetch(res, s["base_url"], api_key)
        except wan.WanError as e:
            if _load_problem(str(e)) and n < M.ACE_LOAD_TRIES - 1:
                await asyncio.sleep(M.ACE_LOAD_WAIT_S)
                continue
            raise MediaError(f"the music could not be made: {e}") from e


async def make_take(session_id: str, plan: dict, total_s: float, k: int, seed: int, s: dict, api_key: str, force: bool = False) -> dict:
    """Take `k` of the session's music as a media row (the same kind as the YuE2 takes, so the mix does not care which engine made it). Up to ACE_TRIES seeds are tried and the calmest wins."""
    body0 = request(plan, seed, k, total_s)
    h = _hash({**body0, "seed": 0})
    if not force:
        for it in media.items(session_id, music_mod.KIND, music_mod.KEY):
            if it["status"] == "done" and it["file"] and it["meta"].get("input_hash") == h and it["meta"].get("take") == k and it["meta"].get("seed0") == int(seed):
                return it
    it = media.add(session_id, music_mod.KIND, music_mod.KEY, 0, "running", {"input_hash": h, "engine": "acestep", "take": k, "seed0": int(seed), "caption": body0["caption"]})
    best = None
    try:
        for n in range(M.ACE_TRIES):
            body = {**body0, "seed": int(seed) + n * 104729}
            data = await _one(body, s, api_key)
            tmp = media.media_dir(session_id, "music") / f"bgm-a{it['attempt']}-try{n}.mp3"
            tmp.write_bytes(data)
            a = await asyncio.to_thread(assess, tmp)
            if best is None or (a["calm"], -a["score"]) > (best[1]["calm"], -best[1]["score"]):
                best = (tmp, a, body["seed"])
            if a["calm"]:                                    # a grind at the start is cut when the takes are joined, so a calm take is enough
                break
        tmp, a, used = best
        name = f"bgm-a{it['attempt']}.mp3"
        final = media.media_dir(session_id, "music") / name
        tmp.replace(final)
        for extra in media.media_dir(session_id, "music").glob(f"bgm-a{it['attempt']}-try*.mp3"):
            extra.unlink(missing_ok=True)
        return media.update(it["id"], status="done", file=f"music/{name}", meta={"seed": used, "trim_s": a["trim_s"], "centroid": a["centroid"], "pulse": a["pulse"], "calm": a["calm"], "score": a["score"],
                                                                              "duration_s": float(body0["duration"])})
    except (MediaError, OSError) as e:
        media.update(it["id"], status="failed", meta={"error": str(e)[:300]})
        raise MediaError(f"the music could not be made: {e}") from e


async def make_takes(session_id: str, plan: dict, settings: dict, total_s: float, s: dict, api_key: str, progress=None) -> tuple[list[dict], str]:
    """All takes of a video (M.ace_take_count): the ones that worked and the last error (empty when all worked)."""
    n = M.ace_take_count(total_s)
    seed0 = int(settings.get("music_seed") or settings.get("seed") or 7)
    takes, err = [], ""
    for k in range(n):
        if progress:
            progress(0, 3, f"generating ambient music (ACE-Step), take {k + 1} of {n}")
        try:
            takes.append(await make_take(session_id, plan, total_s, k, seed0 + k * 7919, s, api_key))
        except MediaError as e:
            err = str(e)[:300]
            if _load_problem(err) and not takes:          # the model does not start: the other takes would fail the same way, so stop and let the caller use the other engine
                break
    return takes, err
