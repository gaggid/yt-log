"""Automated step chain for a relaxation session.

Steps (in order):
  1. scene   — Qwen room image
  2. rain    — Wan I2V rain animation
  3. upscale — 2K upscale of the rain clip (old Wan sessions only; the code-drawn rain is 4K already)
  4. audio   — rain SFX + YuE2 music mix
  5. video   — 3-hour ffmpeg loop assembly
  6. publish — generate YouTube title/description/tags

Each step checks if the result already exists and skips if so, unless force=True.
The whole chain runs as a single background job via story2/jobs.py.
"""
import asyncio

from story import settings as settings_mod
from story3.voice import MediaError

from . import audio, director, image, models as M, publish, rain, store, thumb, video


async def run(session_id: str, force: bool = False, progress=None) -> str:
    """Run all pending steps for a session. Returns a human-readable summary."""
    s = settings_mod.get()
    key = settings_mod.api_key()
    done: list[str] = []

    def _prog(step: str):
        def _p(d, t, label=""):
            if progress:
                progress(d, t, f"{step}: {label}" if label else step)
        return _p

    # keep step name visible in job status
    def _step(name: str):
        try:
            sess = store.get(session_id)
            sess["step"] = name
            sess["status"] = store.RUNNING
            sess["error"] = ""
            store.save(sess)
        except Exception:  # noqa: BLE001
            pass

    try:
        _step("plan")
        try:
            await director.plan(session_id, s, force=False)          # the prompt, the thumbnail concept and the upload text of THIS video; the stand-ins carry a model failure
        except Exception:  # noqa: BLE001 - never stops a run
            pass

        _step("scene")
        item = await image.generate(session_id, s, key, force=force)
        done.append("scene image")

        _step("rain")
        item = await rain.generate(session_id, s, key, force=force)
        done.append("rain clip")

        sess = store.get(session_id)
        if rain.engine(session_id) == "wan" and (sess.get("settings") or {}).get("upscale") == "2k":        # code rain is drawn at 4K already
            _step("upscale")
            await rain.upscale(session_id, s, key, force=force)
            done.append("2K upscale")

        if force or not store.chosen(session_id, M.KIND_FINAL):        # a finished video holds its sound; the mix file is removed after it
            _step("audio")
            await audio.make(session_id, s, key, progress=_prog("audio"), force=force)
            done.append("audio mix")

            _step("video")
            await video.make(session_id, s, key, progress=_prog("video"), force=force)
            done.append("3-hour video")
            await asyncio.to_thread(audio.drop_mix, session_id)

        _step("publish")
        await publish.generate(session_id, s, force=force)
        done.append("metadata")

        _step("thumbnail")
        try:
            try:
                await thumb.picture(session_id, s, key, force=force)            # a happy person by the rainy window; failing, the scene picture is used
            except MediaError:
                pass
            thumb.make(session_id, force=force)
            done.append("thumbnail")
        except Exception:  # noqa: BLE001 - the video is complete without it
            pass

        sess = store.get(session_id)
        sess["status"] = store.READY
        sess["step"] = ""
        sess["error"] = ""
        store.save(sess)

        return "Done: " + ", ".join(done)

    except MediaError as e:
        store.set_error(session_id, str(e))
        raise
