"""The sound bed (docs/TASKS_quality_overhaul.md task 5.3): a quiet music pad and a room-tone under the voice, so the film is not a voice on silence. It is made here with ffmpeg
from a few sine tones (a slow chord that changes with every part of the film, a tremolo pulse in the set piece, a softly filtered noise for air), needs no model and no download,
and is ducked under the voice (sidechain compression) so it never competes with the words. A music model from the gateway can replace it later without changing the mix step.

Plan setting `audio`: {"enabled": true, "music_level": -30} (dB before ducking)."""
import subprocess
from pathlib import Path

DEFAULTS = {"enabled": True, "music_level": -30}
ROOTS = (110.0, 98.0, 87.31, 98.0, 82.41, 98.0)                 # A2, G2, F2, G2, E2, G2: a slow minor-leaning cycle, one root per part
FADE_S = 0.9
MIX_VERSION = "b1"                                              # part of the video's cache key: bump when the bed or the ducking changes


def settings(plan: dict) -> dict:
    return {**DEFAULTS, **((plan.get("settings") or {}).get("audio") or {})}


def _run(ffmpeg: str, args: list[str], cwd: Path | None = None) -> None:
    r = subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *args], capture_output=True, text=True, cwd=cwd, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip().splitlines()[-1][:240] if (r.stderr or r.stdout).strip() else str(r.returncode))


def pad(ffmpeg: str, out: Path, seconds: float, root: float, pulse: bool, level_db: float) -> None:
    """One part of the bed: a root, its fifth and a minor third as soft sines, low-passed, with air under them; `pulse` adds a slow throb for the set piece."""
    secs = max(1.0, seconds)
    third, fifth = root * 1.2, root * 1.5
    tones = "".join(f"sine=f={f:.2f}:r=24000:d={secs:.2f}[t{k}];" for k, f in enumerate((root, third, fifth, root * 2)))
    graph = (tones + "[t0][t1][t2][t3]amix=inputs=4:normalize=0,lowpass=f=900," + (f"tremolo=f=2.2:d=0.55," if pulse else "tremolo=f=0.12:d=0.35,")
             + f"volume={level_db}dB[pad];anoisesrc=color=brown:r=24000:d={secs:.2f}:a=0.5,lowpass=f=500,volume={level_db - 8}dB[air];"
             f"[pad][air]amix=inputs=2:normalize=0,afade=t=in:d={FADE_S},afade=t=out:st={max(0.0, secs - FADE_S):.2f}:d={FADE_S}[o]")
    _run(ffmpeg, ["-filter_complex", graph, "-map", "[o]", "-c:a", "pcm_s16le", "-ar", "24000", "-ac", "1", str(out)])


def roots_for(family: int) -> tuple:
    """The root cycle of the pads for a music family (story2/variety.py): the same slow idea in four different keys, so two films do not sound alike."""
    shift = (1.0, 1.122, 1.26, 0.89)[family % 4]
    return tuple(round(r * shift, 2) for r in ROOTS)


def build_bed(ffmpeg: str, parts: list[dict], work: Path, level_db: float = -30, pulse_parts: set[int] | None = None, family: int = 0) -> Path | None:
    """The bed for the whole film: one pad per part (`parts` are the voice parts with `duration_s`), joined in order. Returns the file, or None when it cannot be made (the film is then
    built without a bed and says so)."""
    files = []
    try:
        for n, a in enumerate(parts):
            f = work / f"bed{n:03d}.wav"
            roots = roots_for(family)
            pad(ffmpeg, f, float(a["duration_s"]) + 0.05, roots[n % len(roots)] if n < len(parts) - 1 else roots[0], n in (pulse_parts or set()), level_db)
            files.append(f)
        if not files:
            return None
        lst = work / "bed.txt"
        lst.write_text("".join(f"file '{f.name}'\n" for f in files), encoding="utf-8")
        out = work / "bed.wav"
        _run(ffmpeg, ["-f", "concat", "-safe", "0", "-i", lst.name, "-c", "copy", str(out)], cwd=work)
        return out
    except (RuntimeError, OSError):
        return None


def mix_args(bed_input: int = 2) -> str:
    """The filter graph that lays the bed under the voice: the bed is ducked while the voice speaks (sidechain compression), then both are summed. Voice is input 1, the bed
    `bed_input`; output label [mix]."""
    return (f"[{bed_input}:a]aresample=24000[bed];[bed][1:a]sidechaincompress=threshold=0.015:ratio=10:attack=15:release=450:makeup=1[ducked];"
            f"[1:a][ducked]amix=inputs=2:duration=first:normalize=0[mix]")
