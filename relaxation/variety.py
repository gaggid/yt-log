"""What makes each rain video different from the last ones: the theme (scene), the instrument, the mood, the tempo and the seed.

Every choice looks at the sessions already made (newest first), so nothing repeats before it has to:
  - theme: one that was never used, else the one used longest ago;
  - instrument: one of the theme's own instruments that is not among the last RECENT_INSTRUMENTS videos (never the same as the previous video);
  - mood: not one of the last two moods;
  - tempo: a slow BPM from MUSIC_BPM; seed: new for every video (the same seed would draw the same picture and the same music).
The music caption is built from these in code (models.music_caption), never by a model, so it always stays calm, instrumental and without drums."""
import random

from . import models as M, store

RECENT_INSTRUMENTS = 7


def history() -> list[dict]:
    """Sessions made so far, newest first, as {scene, instrument, mood}."""
    out = []
    for s in store.list_all():
        st = s.get("settings") or {}
        mp = st.get("music_plan") or {}
        out.append({"scene": st.get("scene", ""), "instrument": mp.get("instrument", ""), "mood": mp.get("mood", "")})
    return out


def pick_scene(hist: list[dict], rng: random.Random) -> str:
    """A theme that was never used; else the one used longest ago."""
    last = {}
    for i, h in enumerate(hist):
        last.setdefault(h["scene"], i)                    # 0 = the newest session
    never = [k for k in M.SCENES if k not in last]
    if never:
        return rng.choice(never)
    oldest = max(last[k] for k in M.SCENES)
    return rng.choice([k for k in M.SCENES if last[k] == oldest])


def pick_music(scene: str, hist: list[dict], rng: random.Random) -> dict:
    options = list((M.SCENES.get(scene) or M.SCENES[M.DEFAULT_SCENE])["instruments"])
    recent = [h["instrument"] for h in hist[:RECENT_INSTRUMENTS] if h["instrument"]]
    fresh = [i for i in options if i not in recent]
    if not fresh:                                         # all used lately: the one used longest ago, never the previous video's
        previous = recent[0] if recent else ""
        age = {i: (recent.index(i) if i in recent else 99) for i in options if i != previous}
        fresh = [max(age, key=age.get)] if age else options
    instrument = rng.choice(fresh)
    secondary = rng.choice([s for s in M.MUSIC_SECONDARY])
    moods = [m for m in M.MUSIC_MOODS if m not in [h["mood"] for h in hist[:2]]]
    mood = rng.choice(moods or M.MUSIC_MOODS)
    bpm = rng.randint(*M.MUSIC_BPM)
    return {"instrument": instrument, "secondary": secondary, "mood": mood, "bpm": bpm,
            "caption": M.music_caption(instrument, secondary, mood, bpm)}


def choose(scene: str | None = None, rng: random.Random | None = None) -> dict:
    """The variable parts of a new session: {scene, seed, music_plan}. `scene` fixes the theme (the person chose it)."""
    rng = rng or random.Random()
    hist = history()
    scene = scene if scene in M.SCENES else pick_scene(hist, rng)
    return {"scene": scene, "seed": rng.randrange(1, 2 ** 31 - 1), "music_plan": pick_music(scene, hist, rng)}
