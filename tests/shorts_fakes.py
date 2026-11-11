"""Stand-ins for the Shorts tests: a video gateway (httpx mock transport), a chat model that answers the two Shorts tasks, a voice that speaks a tone of the right length, and tiny
real MP4 files made by ffmpeg."""
import io
import base64
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


CAMERAS = ["pushes in until his face fills the frame", "pans left across the wet street", "tilts down from his face to the wallet", "pulls back to show the whole road", "sweeps around him to the other side"]   # a different camera move for neighbouring shots


class VideoGateway:
    """The video endpoint: POST /video/generations answers 202 with a job, GET /jobs/{id} says running once then succeeded, GET /video/{id}.mp4 returns a tiny real clip."""

    def __init__(self, tmp: Path, fail_first: int = 0, video_under_api: bool = False, listed=("wan-2.2-ti2v-5b", "wan-2.2-t2v-a14b", "wan-2.2-i2v-a14b", "wan-2.2-animate-2")):
        self.tmp, self.requests, self.jobs, self.fail_first, self.under_api, self.listed = tmp, [], {}, fail_first, video_under_api, listed
        self.cache: dict[tuple, bytes] = {}
        self.status_code = 202
        self.images: list[dict] = []                    # the picture requests (POST /images/generations)
        self.upscales: list[dict] = []                  # the upscale requests (POST /video/upscale)
        self.pic_edits: list[dict] = []                 # the picture edit requests (POST /images/edits): prompt, number of pictures, size

    def mp4(self, frames: int, fps: int) -> bytes:
        k = (frames, fps)
        if k not in self.cache:
            self.cache[k] = tiny_mp4(self.tmp / f"gw-{frames}-{fps}.mp4", frames, fps).read_bytes()
        return self.cache[k]

    def handler(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if req.method == "GET" and path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": m, "type": "video"} for m in self.listed] + [{"id": "gemma", "type": "chat"}]})
        if req.method == "POST" and path.endswith("/images/generations"):
            body = json.loads(req.content)
            self.images.append(body)
            w, h = (int(v) for v in body["size"].split("x"))
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(png_bytes(w // 8, h // 8)).decode()}]})
        if req.method == "POST" and path.endswith("/images/edits"):
            raw = req.content
            size = re.search(rb'name="size"\r\n\r\n([^\r]*)\r\n', raw).group(1).decode()
            prompt = re.search(rb'name="prompt"\r\n\r\n(.*?)\r\n--', raw, re.S).group(1).decode()
            self.pic_edits.append({"prompt": prompt, "images": raw.count(b'name="image'), "size": size})
            w, h = (int(v) for v in size.split("x"))
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(png_bytes(w // 8, h // 8)).decode()}]})
        if req.method == "POST" and path.endswith("/video/upscale"):
            body = json.loads(req.content)
            self.upscales.append(body)
            jid = f"job_{900 + len(self.upscales)}"
            self.jobs[jid] = {"body": {"upscale": True, "fps": 30}, "polls": 0}
            return httpx.Response(202, json={"id": jid, "status": "queued"})
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
            if b.get("upscale"):
                return httpx.Response(200, json={"id": m.group(1), "status": "succeeded", "result": {"url": f"/video/{m.group(1)}.mp4", "input_width": 480, "input_height": 832, "output_width": 1440, "output_height": 2496, "generation_s": 1.0}})
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
            if b.get("upscale"):
                return httpx.Response(200, content=self.mp4(10, 30))
            fps = int(b.get("fps") or 16)
            return httpx.Response(200, content=self.mp4(int(b.get("num_frames") or round(float(b.get("duration", 5)) * fps)), fps))
        return httpx.Response(404, json={"error": "not found " + path})

    def install(self, monkeypatch) -> "VideoGateway":
        from shorts import wan
        transport = httpx.MockTransport(self.handler)
        monkeypatch.setattr(wan, "_client", lambda timeout: REAL_CLIENT(transport=transport, timeout=timeout))
        monkeypatch.setattr(wan, "POLL_S", 0)
        from shorts import stills
        monkeypatch.setattr(stills, "_client", lambda timeout: REAL_CLIENT(transport=transport, timeout=timeout))
        return self


class FakeChat:
    """Answers [TASK:p4_plan] with five beats of Hinglish and [TASK:p4_shots] with exactly the number of shots asked for."""

    def __init__(self, narration=None, extra_shots=0, plan_extra=None, shot_extra=None, no_director=False, room=False, scores=(9,), punch_words=None, long=0, stills=False, still_text=None, moves=False, move_text=None, review=False, review_overrides=None, review_fn=None):
        self.calls, self.narration, self.extra_shots, self.plan_extra, self.shot_extra = [], narration or HINDI, extra_shots, plan_extra or {}, shot_extra or {}
        self.no_director = no_director
        self.moves, self.move_text = moves, move_text                                       # moves: answers the motion writer (otherwise it fails and the shots keep the planner's prompt)
        self.review_fn, self.review_calls = review_fn, 0                                        # review_fn(ids, call number) -> shot id -> fields: a review that changes between calls
        self.review, self.review_overrides = review, review_overrides or {}                    # review: answers the picture review (otherwise it fails and the pictures are simply not reviewed); overrides: shot id -> fields
        self.stills, self.still_text = stills, still_text                                    # stills: answers the picture writer (otherwise it fails and the shots keep the planner's stills)
        self.room, self.scores, self.punch_words = room, list(scores), punch_words          # room: answers the writers' room tasks; otherwise they fail and the planner uses the one-call plan
        self.script: dict[str, list[dict]] = {}
        self.k = 0
        self.long = long                                                                    # a number of beats: the room then writes filler words to the asked budget (for long shorts)
        if long:
            self.narration = [[] for _ in range(long)]

    def count(self, task):
        return sum(1 for c in self.calls if c["task"] == task)

    async def complete(self, messages, max_tokens, params=None):
        from story.llm import LLMResult
        system = messages[0]["content"]
        task = re.match(r"\[TASK:(\w+)\]", system).group(1)
        if task == "p4_move" and not self.moves:
            from story.llm import LLMError
            raise LLMError("the motion writer is off in this test")
        if task == "p4_review" and not self.review:
            from story.llm import LLMError
            raise LLMError("the picture review is off in this test")
        if task == "p4_still" and not self.stills:
            from story.llm import LLMError
            raise LLMError("the picture writer is off in this test")
        if task in ("p4_bible", "p4_map", "p4_draft", "p4_punch") and not self.room:
            from story.llm import LLMError
            self.room_refused = getattr(self, "room_refused", 0) + 1
            raise LLMError("the writers' room is off in this test")
        user_msg = messages[1]["content"]
        n_images = 0 if isinstance(user_msg, str) else sum(1 for p in user_msg if p.get("type") == "image_url")
        messages = [{**m, "content": m["content"] if isinstance(m["content"], str) else " ".join(p.get("text", "") for p in m["content"])} for m in messages]      # a question with pictures: the words are what the fake reads
        self.calls.append({"task": task, "user": messages[-1]["content"], "system": system, "images": n_images})
        if task in ("p4_bible", "p4_map", "p4_draft", "p4_punch"):
            return LLMResult(json.dumps(self._room(task, system, messages[1]["content"]), ensure_ascii=False))
        if task == "p4_plan":
            beats = [{"name": f"Beat {i + 1}", "feeling": "tense", "tag": ["curious", "nervous", "surprised", "serious", "happy"][i % 5], "narration": n} for i, n in enumerate(self.narration)]
            body = {"format": "story", "title": "The wallet", "logline": "A courier finds a wallet and makes a choice.", "character": "A 24 year old Indian man, lean, short black hair, yellow delivery jacket and blue jeans.",
                    "place": "A rainy city street at night with orange streetlights.", "look": "cinematic, shallow depth of field, handheld", "beats": beats, **self.plan_extra}
        elif task == "p4_shots":
            n = int(re.search(r"EXACTLY (\d+) shots", system).group(1)) + self.extra_shots
            body = {"shots": [{"prompt": f"The courier stops and looks down at a wallet on the wet road, shot {i + 1}.", "still": f"A courier stands over a dropped wallet on a wet road at night, orange light, frame {i + 1}.", "camera": ["slow push in", "static", "pan left", "close-up"][i % 4], "character": i % 2 == 0,
                               "continues": i % 3 == 1, "setting": "", **self.shot_extra} for i in range(n)]}
        elif task == "p4_move":
            ids = re.search(r"Write the motion of: ([^.]+)\.", messages[1]["content"]).group(1).split(", ")
            body = {"shots": [{"id": i, "move": self.move_text or f"The courier lifts the wallet toward his chest in shot {i}. The camera {CAMERAS[int(re.sub(r'[^0-9]', '', i) or 0) % len(CAMERAS)]}."} for i in ids]}
        elif task == "p4_review":
            ids = [x.strip() for x in re.search(r"left to right and top row first: (.+)", messages[1]["content"]).group(1).split(",")]
            body = {"shots": [{"id": i, "place": "street", "setting_type": "outdoor", "people_count": 1, "objects": ["wallet"], "readable_text": "none", "style": "painted", "background": "a wet road at night",
                               "shot_size": "close-up", "arrangement": "one man in the centre", "face_visible": True, "read": n % 3, "pull": (n + 1) % 3, **self.review_overrides.get(i, {}), **((self.review_fn(ids, self.review_calls) or {}).get(i, {}) if self.review_fn else {})} for n, i in enumerate(ids)]}
            self.review_calls += 1
        elif task == "p4_still":
            ids = re.search(r"Write the pictures of: ([^.]+)\.", messages[1]["content"]).group(1).split(", ")
            body = {"shots": [{"id": i, "still": self.still_text or f"Close-up of one courier holding one wallet beside a rusty bus stop, picture {i}, a single streetlight behind him.", "must_show": ["exactly 1 courier", "wallet in his hand"]} for i in ids]}
        elif task == "p4_publish":
            body = {"title": "Why a courier returned the wallet with one lakh rupees inside",
                    "description": ("A courier finds a wallet with one lakh rupees on a rainy street. What he does next is the real story. " * 3) + "\n\nWould you give it back? Follow for more true stories.\n#Shorts #story",
                    "hashtags": ["shorts", "#Wallet Story", "courier"],
                    "tags": ["courier story", "lost wallet", "honesty story", "hindi story", "short story", "rainy night", "one lakh rupees", "moral story"]}
        elif task == "music_plan":
            body = {"genre": "ambient", "moods": ["gentle"], "bpm": 78, "instruments": ["soft piano", "warm pad"], "why": "A gentle bed under the story."}
        elif task == "p4_shotlist":
            if getattr(self, "no_director", False):
                raise RuntimeError("director is down")
            counts = [int(n) for n in re.findall(r"\[(\d+) shots\]", messages[-1]["content"])]
            body = {"subjects": [{"name": "Pilot", "kind": "person", "visual": "An Indian air force pilot in a green flight suit and white helmet, seen from the side in a cockpit."}],
                    "beats": [{"ideas": [{"idea": f"Idea {b + 1}.{i + 1}: a different picture", "subjects": ["Pilot"] if i == 0 else []} for i in range(n)]} for b, n in enumerate(counts)]}
        else:
            raise AssertionError("unexpected task " + task)
        return LLMResult(json.dumps(body, ensure_ascii=False))


def _room_method(self, task, system, user):
    n = len(self.narration)
    if task == "p4_bible":
        return {"premise": "A courier finds a wallet and must choose.", "promise": "dread", "hero": "Rahul wants rent money, fears the debt.", "secret": "The wallet belongs to his landlord.", "world": ["It rains all night."],
                "wow": ["The photo is of him."], "question": "Would you keep it?", "voice": "Rahul, first person, dry.", "motifs": ["rain"], "avoid": ["lottery"]}
    if task == "p4_map":
        t = float(re.search(r"for ([\d.]+) seconds", system).group(1))
        jobs = ["hook"] + ["escalate", "reveal", "rehook", "twist", "breather", "escalate", "reveal"] * 3
        return {"beats": [{"name": f"Beat {i + 1}", "job": jobs[i] if i < n - 1 else "sting", "feeling": "tense", "seconds": t / n, "carries": f"thing {i + 1}", "cliff": "" if i == n - 1 else "what next?"} for i in range(n)]}
    if task == "p4_draft":
        i = int(re.search(r"NOW WRITE BEAT (\d+)", user).group(1)) - 1
        lo, hi = (int(x) for x in re.search(r"between (\d+) and (\d+) words", system).groups())
        if "THE PRODUCER'S INSTRUCTION" in user:                                           # a rewrite: new words inside the asked budget, never the old text
            n, out, k = (lo + hi) // 2, [], 0
            while n > 0:
                w = min(n, 5 + 3 * (k % 2))
                out.append({"text": " ".join(["अंधेरा", "दरवाज़ा", "आवाज़", "ठंडी", "रात", "साँस", "क़दम", "खामोशी"][(j + k + i) % 8] for j in range(w)) + "।", "tag": "whispers"})
                n -= w
                k += 1
            self.script[f"b{i + 1}"] = out
            return {"sentences": out}
        return {"sentences": self._lines(i, lo, hi)}
    texts = re.findall(r"^(b\d+) \(", user, re.M)
    score = self.scores.pop(0) if len(self.scores) > 1 else self.scores[0]
    lo, hi = (int(x) for x in re.search(r"between (\d+) and (\d+) words", system).groups())
    beats = []
    for bid in texts:
        base = self.script.get(bid, [])
        if self.punch_words is not None:
            sents = [{"text": " ".join(["sharper"] * self.punch_words), "tag": "whispers"}]
        else:
            sents = [{**s, "text": s["text"]} for s in base]
        beats.append({"id": bid, "sentences": sents})
    return {"score": score, "problems": ["beat b2 is flat"], "beats": beats}


def _room_lines(self, i, lo, hi):
    """Beat i of the narration when it is given, else filler words (letters only) for a budget of lo..hi words, in lines of five to nine words."""
    if self.long:
        words, out, k = (lo + hi) // 2, [], self.k
        while words > 0:
            w = min(words, 5 + k % 5)
            out.append({"text": " ".join(["door", "rain", "phone", "cold", "step", "light", "hand", "night", "voice"][(k + j) % 9] for j in range(w)) + ".", "tag": ["whispers", "scared", "neutral", "loudly"][k % 4]})
            words -= w
            k += 1
        self.script[f"b{i + 1}"] = out
        self.k = k
        return out
    out = [{"text": t, "tag": ["whispers", "nervous"][j % 2]} for j, t in enumerate(self.narration[i])]
    self.script[f"b{i + 1}"] = out
    return out


FakeChat._room, FakeChat._lines = _room_method, _room_lines


async def fake_speak_all(client, base, key, bodies):
    """The voice: a tone as long as the words would take to say."""
    words = sum(len(re.sub(r"\[[a-z ]+\]", "", b["input"]).split()) for b in bodies)
    return tone_wav(max(0.5, words / 2.47))
