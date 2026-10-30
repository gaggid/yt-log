"""A fake image gateway for the Character Studio tests: /images/generations, /images/edits (multipart) and the LoRA listing; plus a chat double that writes slots."""
import base64
import json
import re

import httpx

from shorts_fakes import REAL_CLIENT, png_bytes

LORAS = {"qwen2.1-detail-fix-2.0": {"name": "qwen2.1-detail-fix-2.0", "strength": 1.0, "trigger": ""},
         "purelens-realism": {"name": "purelens-realism", "strength": 1.0, "trigger": "p3r4l4ns"},
         "raw-photo-v3": {"name": "raw-photo-v3", "strength": 1.0, "trigger": ""}, "__default__": {"names": ["qwen2.1-detail-fix-2.0"]}}
SLOTS = {"ethnicity": "Indian", "gender": "man", "age": "30", "build": "lean, average height", "skin": "medium brown", "face": "oval face with a short trimmed black beard",
         "hair": "short wavy black hair", "eyes": "dark brown", "top": "mustard yellow delivery jacket over a grey t-shirt", "bottom": "dark blue jeans", "footwear": "white sneakers",
         "accessories": "black wristwatch", "expression": "calm and tired"}


class ImageGateway:
    def __init__(self, fail_edits: bool = False):
        self.draws, self.edits, self.fail_edits = [], [], fail_edits

    def handler(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path.endswith("/images/generations"):
            body = json.loads(req.content)
            self.draws.append(body)
            w, h = (int(v) for v in body["size"].split("x"))
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(png_bytes(w // 8, h // 8)).decode()}]})
        if path.endswith("/images/edits"):
            if self.fail_edits:
                return httpx.Response(400, json={"error": {"message": "bad edit"}})
            raw = req.content
            fields = dict(re.findall(rb'name="(\w+)"\r\n\r\n([^\r]*)\r\n', raw))
            prompt = re.search(rb'name="prompt"\r\n\r\n(.*?)\r\n--', raw, re.S)
            self.edits.append({"fields": {k.decode(): v.decode() for k, v in fields.items()}, "images": raw.count(b'name="image"'), "prompt": prompt.group(1).decode() if prompt else ""})
            w, h = (int(v) for v in fields[b"size"].decode().split("x"))
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(png_bytes(w // 8, h // 8)).decode()}]})
        return httpx.Response(404, json={"error": "not found " + path})

    def install(self, monkeypatch) -> "ImageGateway":
        from characters import studio
        transport = httpx.MockTransport(self.handler)
        monkeypatch.setattr(studio, "_client", lambda timeout: REAL_CLIENT(transport=transport, timeout=timeout))
        monkeypatch.setattr(studio, "lora_listing", lambda model, s=None, key="", ttl=60.0: LORAS)
        return self


class SlotsChat:
    """Answers [TASK:char_slots]: the first reply has vague slots when `vague_first`, then good ones."""

    def __init__(self, vague_first: bool = False):
        self.calls, self.vague_first = [], vague_first

    async def complete(self, messages, max_tokens, params=None):
        from story.llm import LLMResult
        self.calls.append(messages[-1]["content"])
        slots = dict(SLOTS)
        if self.vague_first and len(self.calls) == 1:
            slots["top"], slots["hair"] = "casual clothes", "normal"
        return LLMResult(json.dumps({"name": "Raju", "personality": "quietly funny", "slots": slots}))
