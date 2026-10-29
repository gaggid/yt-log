"""Dead-air trimming for voice takes (docs/AUDIT_2026-10-29.md section 13 point 1, and the owner's report of long blank pauses).

The voice engine leaves a gap after almost every sentence and now and then a long dead stretch (6.7 and 6.9 seconds were measured inside two takes). Every silence is
shortened to `max_gap_s` except the pauses the narration asked for (`pause_after_s`), which keep their length. Pure Python on 16-bit PCM wav: no numpy, no ffmpeg."""
import array
import io
import math
import wave

DEFAULT_MAX_GAP_S = 0.40
THRESHOLD_DB = -38.0            # a window quieter than this is silence (same level the audit measures with ffmpeg silencedetect)
WINDOW_S = 0.02
KEEP_AT_LEAST_S = 0.12          # a gap is never cut below this, so words do not run into each other


def _levels(samples: array.array, rate: int, channels: int) -> list[float]:
    """dBFS of each 20 ms window (all channels together)."""
    win = max(1, int(rate * WINDOW_S)) * channels
    out = []
    for i in range(0, len(samples), win):
        chunk = samples[i:i + win]
        if not chunk:
            break
        ms = sum(x * x for x in chunk) / len(chunk)
        out.append(-120.0 if ms <= 0 else 10 * math.log10(ms / (32768.0 ** 2)))
    return out


def silences(levels: list[float], min_s: float, thresh_db: float = THRESHOLD_DB) -> list[tuple[int, int]]:
    """(first window, one past the last window) of every run of silence at least `min_s` long."""
    need = max(1, int(round(min_s / WINDOW_S)))
    out, start = [], None
    for i, db_ in enumerate(levels + [0.0]):
        if db_ < thresh_db:
            start = i if start is None else start
        elif start is not None:
            if i - start >= need:
                out.append((start, i))
            start = None
    return out


def allowances(runs: list[tuple[int, int]], planned: list[float], max_gap_s: float) -> list[float]:
    """How long each silence may stay, in seconds. The longest silences are matched with the longest planned pauses: a silence that is roughly as long as a planned pause keeps
    that pause (plus a little), every other silence keeps `max_gap_s`."""
    want = sorted((p for p in planned if p >= 0.3), reverse=True)
    order = sorted(range(len(runs)), key=lambda k: runs[k][1] - runs[k][0], reverse=True)
    allow = [max_gap_s] * len(runs)
    for rank, k in enumerate(order):
        length = (runs[k][1] - runs[k][0]) * WINDOW_S
        if rank < len(want) and length >= 0.5 * want[rank]:
            allow[k] = min(length, max(max_gap_s, want[rank] + 0.15))
    return allow


def trim(wav: bytes, planned_pauses: list[float] | None = None, max_gap_s: float = DEFAULT_MAX_GAP_S) -> tuple[bytes, dict]:
    """The wav with its dead air shortened, and a report: seconds before and after, how much was removed, the longest silence removed, and the silences that were cut by
    more than 1.5 seconds. Audio that is not 16-bit PCM is returned unchanged."""
    with wave.open(io.BytesIO(wav)) as w:
        params, frames = w.getparams(), w.readframes(w.getnframes())
    rate, ch = params.framerate, params.nchannels
    before = params.nframes / rate
    if params.sampwidth != 2:
        return wav, {"before_s": round(before, 2), "after_s": round(before, 2), "removed_s": 0.0, "longest_removed_s": 0.0, "cut": [], "note": "not 16-bit audio: left as it is"}
    samples = array.array("h")
    samples.frombytes(frames)
    lv = _levels(samples, rate, ch)
    runs = silences(lv, max_gap_s + 0.06)
    allow = allowances(runs, planned_pauses or [], max_gap_s)
    win = max(1, int(rate * WINDOW_S)) * ch
    out = array.array("h")
    pos, cut = 0, []
    for (a, b), keep_s in zip(runs, allow):
        length = (b - a) * WINDOW_S
        if length <= keep_s + 0.05:
            continue
        keep = max(int(max(keep_s, KEEP_AT_LEAST_S) / WINDOW_S), 1)
        head = keep // 2 + keep % 2
        out.extend(samples[pos:(a + head) * win])
        pos = (b - (keep - head)) * win
        cut.append({"at_s": round(a * WINDOW_S, 1), "was_s": round(length, 2), "kept_s": round(keep * WINDOW_S, 2)})
    out.extend(samples[pos:])
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setparams(params)
        w.writeframes(out.tobytes())
    after = len(out) / ch / rate
    return buf.getvalue(), {"before_s": round(before, 2), "after_s": round(after, 2), "removed_s": round(before - after, 2),
                            "longest_removed_s": round(max((c["was_s"] - c["kept_s"] for c in cut), default=0.0), 2), "cut": [c for c in cut if c["was_s"] - c["kept_s"] > 1.5],
                            "gaps_trimmed": len(cut)}
