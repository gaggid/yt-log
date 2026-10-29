"""Stand-ins for the Shorts tests: a video gateway (httpx mock transport), a chat model that answers the two Shorts tasks, a voice that speaks a tone of the right length, and tiny
real MP4 files made by ffmpeg."""
import io
import json
import math
import re
import struct
import subprocess
import wave
from pathlib import Path

import httpx
import pytest

from story3 import video

REAL_CLIENT = httpx.AsyncClient          # other tests swap httpx.AsyncClient for a fake and may not restore it; the video gateway mock always uses the real class
FFMPEG_OK = Path(video.FFMPEG).is_file()
needs_ffmpeg = pytest.mark.skipif(not FFMPEG_OK, reason="ffmpeg is not installed")

HINDI = [
    ["सड़क पर एक वॉलेट पड़ा था।", "अंदर कितने पैसे थे?"],
    ["राहुल डिलीवरी करके लौट रहा था, थका हुआ।", "उसने वॉलेट उठाया और चौंक गया।"],
    ["अंदर पूरे एक लाख रुपये थे, और एक पुराना फोटो।", "फोन में बस बीस परसेंट बैटरी बची थी।"],
    ["उसे पता था कि लालच बहुत बुरा है।", "फिर भी उसके हाथ काँप रहे थे।"],
    ["उसने फोटो के पीछे लिखा नंबर मिलाया।", "उधर से एक बूढ़ी आवाज़ आई, और राहुल मुस्कुरा दिया।"],
]


def tiny_mp4(path: Path, frames: int = 20, fps: int = 16, size: str = "64x112") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([video.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size={size}:rate={fps}", "-frames:v", str(frames), "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def tone_wav(seconds: float, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        n = int(seconds * rate)
        w.writeframes(b"".join(struct.pack("<h", int(9000 * math.sin(2 * math.pi * 220 * i / rate) * (0.6 + 0.4 * math.sin(2 * math.pi * 3 * i / rate)))) for i in range(n)))
    return buf.getvalue()


def png_bytes(w: int = 90, h: int = 160, color=(180, 90, 40)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


class VideoGateway:
    """The video endpoint: POST /video/generations answers 202 with a job, GET /jobs/{id} says running once then succeeded, GET /video/{id}.mp4 returns a tiny real clip."""

    def __init__(self, tmp: Path, fail_first: int = 0, video_under_api: bool = False, listed=("wan-2.2-ti2v-5b", "wan-2.2-t2v-a14b", "wan-2.2-i2v-a14b", "wan-2.2-animate-2")):
        self.tmp, self.requests, self.jobs, self.fail_first, self.under_api, self.listed = tmp, [], {}, fail_first, video_under_api, listed
        self.cache: dict[tuple, bytes] = {}
        self.status_code = 202

    def mp4(self, frames: int, fps: int) -> bytes:
        k = (frames, fps)
        if k not in self.cache:
            self.cache[k] = tiny_mp4(self.tmp / f"gw-{frames}-{fps}.mp4", frames, fps).read_bytes()
        return self.cache[k]

    def handler(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if req.method == "GET" and path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": m, "type": "video"} for m in self.listed] + [{"id": "gemma", "type": "chat"}]})
        if req.method == "POST" and path.endswith("/video/generations"):
            body = json.loads(req.content)
            if self.fail_first > 0:
                self.fail_first -= 1
                return httpx.Response(502, json={"error": {"code": "video_generation_failed", "message": "backend failed"}}, headers={"Retry-After": "0"})
            if body.get("prompt") == "REFUSE":
                return httpx.Response(400, json={"error": {"code": "invalid_size", "message": "bad size"}})
            self.requests.append(body)
            jid = f"job_{len(self.requests)}"
            self.jobs[jid] = {"body": body, "polls": 0}
            return httpx.Response(202, json={"id": jid, "status": "queued"})
        m = re.search(r"/jobs/(job_\d+)$", path)
        if req.method == "GET" and m:
            j = self.jobs.get(m.group(1))
            if not j:
                return httpx.Response(404, json={"error": "unknown job"})
            j["polls"] += 1
            if j["polls"] < 2:
                return httpx.Response(200, json={"id": m.group(1), "status": "running"})
            b = j["body"]
            w, h = (int(v) for v in b.get("size", "480x832").split("x"))
            fps = int(b.get("fps") or 16)
            frames = int(b.get("num_frames") or round(float(b.get("duration", 5)) * fps))
            return httpx.Response(200, json={"id": m.group(1), "status": "succeeded", "result": {"url": f"/video/{m.group(1)}.mp4", "width": w, "height": h, "frames": frames, "fps": fps,
                                                                                                 "duration_s": frames / fps, "seed": b.get("seed"), "generation_s": 1.0}})
        m = re.search(r"/video/(job_\d+)\.mp4$", path)
        if req.method == "GET" and m:
            if self.under_api and not path.startswith("/v1/"):
                return httpx.Response(404)
            if not self.under_api and path.startswith("/v1/"):
                return httpx.Response(404)
            b = self.jobs[m.group(1)]["body"]
            fps = int(b.get("fps") or 16)
            return httpx.Response(200, content=self.mp4(int(b.get("num_frames") or round(float(b.get("duration", 5)) * fps)), fps))
        return httpx.Response(404, json={"error": "not found " + path})

    def install(self, monkeypatch) -> "VideoGateway":
        from shorts import wan
        transport = httpx.MockTransport(self.handler)
        monkeypatch.setattr(wan, "_client", lambda timeout: REAL_CLIENT(transport=transport, timeout=timeout))
        monkeypatch.setattr(wan, "POLL_S", 0)
        return self


class FakeChat:
    """Answers [TASK:p4_plan] with five beats of Hinglish and [TASK:p4_shots] with exactly the number of shots asked for."""

    def __init__(self, narration=None, extra_shots=0):
        self.calls, self.narration, self.extra_shots = [], narration or HINDI, extra_shots

    def count(self, task):
        return sum(1 for c in self.calls if c["task"] == task)

    async def complete(self, messages, max_tokens, params=None):
        from story.llm import LLMResult
        system = messages[0]["content"]
        task = re.match(r"\[TASK:(\w+)\]", system).group(1)
        self.calls.append({"task": task, "user": messages[-1]["content"], "system": system})
        if task == "p4_plan":
            beats = [{"name": f"Beat {i + 1}", "feeling": "tense", "tag": ["curious", "nervous", "surprised", "serious", "happy"][i], "narration": n} for i, n in enumerate(self.narration)]
            body = {"title": "The wallet", "logline": "A courier finds a wallet and makes a choice.", "character": "A 24 year old Indian man, lean, short black hair, yellow delivery jacket and blue jeans.",
                    "place": "A rainy city street at night with orange streetlights.", "look": "cinematic, shallow depth of field, handheld", "beats": beats}
        elif task == "p4_shots":
            n = int(re.search(r"EXACTLY (\d+) shots", system).group(1)) + self.extra_shots
            body = {"shots": [{"prompt": f"The courier stops and looks down at a wallet on the wet road, shot {i + 1}.", "camera": ["slow push in", "static", "pan left", "close-up"][i % 4], "character": i % 2 == 0,
                               "continues": i % 3 == 1, "setting": ""} for i in range(n)]}
        else:
            raise AssertionError("unexpected task " + task)
        return LLMResult(json.dumps(body, ensure_ascii=False))


async def fake_speak_all(client, base, key, bodies):
    """The voice: a tone as long as the words would take to say."""
    words = sum(len(re.sub(r"\[[a-z ]+\]", "", b["input"]).split()) for b in bodies)
    return tone_wav(max(0.5, words / 2.47))
