"""Talking avatar shots (InfiniteTalk): a shot marked `avatar` starts from its storyboard picture, which shows a library character, and that picture speaks the slice of the beat's voice
that plays during the shot. Lip sync, head, body and hands come from the model; the clip's own sound is dropped when the short is put together (the voice track is ours).

Each avatar shot is its own request of at most three seconds, so the owner rule (no shot longer than 3 s) and the picture-per-shot storyboard stay as they are."""
import base64
import subprocess
import tempfile
from pathlib import Path

from story3 import store as media

from characters import avatar as cavatar

from . import cast, models, timeline, voice as svoice

MODEL = models.TALK


def is_avatar(shot: dict) -> bool:
    return bool(shot.get("avatar"))


def beat_of(short: dict, shot: dict) -> dict | None:
    return next((b for b in short["beats"] if b["id"] == shot.get("beat")), None)


def slice_info(short: dict, shot: dict) -> dict | None:
    """Where in the voice this shot plays: the beat's take, the speed change applied to it, and the shot's offset inside the beat. None while the beat has no voice yet."""
    beat = beat_of(short, shot)
    take = svoice.chosen(short, beat) if beat else None
    if not take:
        return None
    tl = timeline.build(short, {k: v for k, v in svoice.real_seconds(short).items()})
    tb = next((b for b in tl["beats"] if b["id"] == beat["id"]), None)
    ts = next((s for s in tl["shots"] if s["id"] == shot["id"]), None)
    if not tb or not ts:
        return None
    return {"take": take, "tempo": tl["tempo"], "span": tb["span"], "offset": max(0.0, round(ts["start"] - tb["start"], 3)), "seconds": ts["seconds"]}


def token(info: dict) -> str:
    return f"voice:{info['take']['id']}:{info['tempo']}:{info['offset']}:{info['seconds']}"


def audio_wav(info: dict) -> bytes:
    """The shot's slice of the beat's voice at the speed it will have in the short (the same filter the final cut uses), as a wav."""
    from . import stitch                                           # stitch imports clips, which imports this module
    with tempfile.TemporaryDirectory() as td:
        full, part = Path(td) / "beat.wav", Path(td) / "part.wav"
        stitch.beat_audio(media.path_of(info["take"]), info["tempo"], info["span"], full)
        stitch._ffmpeg(["-ss", f"{info['offset']:.3f}", "-t", f"{info['seconds'] + 0.2:.3f}", "-i", str(full), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(part)])
        return part.read_bytes()


def audio_url(info: dict) -> str:
    return "data:audio/wav;base64," + base64.b64encode(audio_wav(info)).decode()


def problems(short: dict) -> list[dict]:
    """What stops an avatar shot, in plain words (merged into the checks list)."""
    out = []
    for sh in short["shots"]:
        if not is_avatar(sh):
            continue
        n = short["shots"].index(sh) + 1
        if not sh.get("cast"):
            out.append({"level": "block", "code": "avatar_cast", "shot": sh["id"], "text": f"Shot {n} is a talking avatar but no library character is in it: put a cast character in the shot."})
        for m in cast.members(short):
            if m.get("char") and m["char"]["id"] in (sh.get("cast") or []):
                r = cavatar.ready_state(m["char"])
                if r["state"] != "pass" or r["stale"]:
                    why = "has not passed the avatar test" if not r["state"] else "is weak in the avatar test" if r["state"] == "weak" else "changed since its avatar test"
                    out.append({"level": "warn", "code": "avatar_ready", "shot": sh["id"], "text": f"{m['char']['name']} {why}: run the 3 s test on the Characters screen so the lips and hands are known to be good."})
        beat = beat_of(short, sh)
        if beat and not svoice.chosen(short, beat):
            out.append({"level": "block", "code": "avatar_voice", "shot": sh["id"], "text": f"Shot {n} is a talking avatar: make the voice of its beat first, the avatar speaks it."})
    return out
