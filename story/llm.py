"""Model access: an OpenAI-compatible chat backend plus a JSON caller that enforces the context budget,
validates replies against a schema, retries a bounded number of times, and keeps failed replies."""
import asyncio
import json
import re
import time
from dataclasses import dataclass, field

import httpx
from pydantic import BaseModel

from . import settings as settings_mod
from .tokens import Budget, BudgetExceeded


class LLMError(Exception):
    pass


class ValidationFailed(LLMError):
    def __init__(self, msg: str, raw: list[dict], truncated: bool = False):
        super().__init__(msg)
        self.raw = raw
        self.truncated = truncated


@dataclass
class LLMResult:
    text: str
    finish_reason: str = "stop"
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class CallResult:
    value: BaseModel
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: int = 0
    attempts: int = 1
    raw_failed: list[dict] = field(default_factory=list)


_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_json(text: str):
    t = _THINK_RE.sub("", text.encode("utf-8", "replace").decode("utf-8")).strip()
    t = _FENCE_RE.sub("", t).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        a, b = t.find("{"), t.rfind("}")
        if a != -1 and b > a:
            return json.loads(t[a:b + 1])
        raise ValueError(f"no JSON object in reply: {t[:200]!r}")


def model_field(s: dict) -> dict:
    """The chat model goes into a request only when one was set in Settings; empty means the model server's own default is used."""
    m = (s.get("model") or "").strip()
    return {"model": m} if m else {}


class ChatBackend:
    """OpenAI-compatible /chat/completions. Endpoint, model and key come from settings, never hardcoded."""

    def __init__(self, s: dict, api_key: str):
        self.s = s
        self.base = s["base_url"].rstrip("/")
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    async def complete(self, messages: list[dict], max_tokens: int) -> LLMResult:
        payload = {**model_field(self.s), "messages": messages, "max_tokens": max_tokens,
                   "temperature": self.s["temperature"], "stream": False}
        if self.s.get("json_mode") == "on":
            payload["response_format"] = {"type": "json_object"}
        tries = max(1, int(self.s["transport_retries"]))
        err: Exception | None = None
        for attempt in range(tries):
            try:
                async with httpx.AsyncClient(timeout=self.s["timeout_s"]) as c:
                    r = await c.post(f"{self.base}/chat/completions", headers=self.headers, json=payload)
                if r.status_code == 429 or r.status_code >= 500:
                    err = LLMError(f"server returned {r.status_code}: {r.text[:200]}")
                elif r.status_code >= 400:
                    raise LLMError(f"model request rejected ({r.status_code}): {r.text[:300]}")
                else:
                    j = r.json()
                    ch = j["choices"][0]
                    u = j.get("usage") or {}
                    return LLMResult(ch["message"].get("content") or "", ch.get("finish_reason") or "stop",
                                     int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0))
            except (httpx.TransportError, httpx.TimeoutException) as e:
                err = LLMError(f"cannot reach model endpoint: {type(e).__name__}: {e}")
            if attempt < tries - 1:
                await asyncio.sleep(float(self.s["retry_backoff_s"]) * (attempt + 1))
        raise err or LLMError("model request failed")

    async def models(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{self.base}/models", headers=self.headers)
        r.raise_for_status()
        return r.json().get("data", [])


async def connection_test(s: dict, api_key: str, probe_json: bool = True) -> dict:
    """Health check: list models, run a tiny completion, and probe response_format support."""
    be = ChatBackend({**s, "transport_retries": 1, "json_mode": "off"}, api_key)
    out: dict = {"ok": False, "base_url": s["base_url"], "model": s["model"]}
    try:
        models = await be.models()
        ids = [m.get("id") for m in models]
        out["models"] = [{"id": m.get("id"), "type": m.get("type", ""), "state": m.get("state", "")}
                         for m in models]
        out["model_listed"] = (s["model"] in ids) if s.get("model") else None             # None: no model named, the server default answers
    except Exception as e:  # noqa: BLE001
        out["models_error"] = f"{type(e).__name__}: {e}"
    t0 = time.time()
    try:
        r = await be.complete([{"role": "user", "content": "Reply with the single word: ok"}], 16)
        out.update(ok=True, latency_s=round(time.time() - t0, 2), reply=r.text.strip()[:80])
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)
        return out
    if probe_json:
        be2 = ChatBackend({**s, "transport_retries": 1, "json_mode": "on"}, api_key)
        try:
            r = await be2.complete([{"role": "user", "content": 'Return JSON {"ok": true}'}], 40)
            parse_json(r.text)
            out["json_mode_supported"] = True
        except Exception:  # noqa: BLE001
            out["json_mode_supported"] = False
    return out


class JsonCaller:
    def __init__(self, backend, s: dict | None = None):
        self.backend = backend
        self.s = s or settings_mod.get()
        self.budget = Budget.from_settings(self.s)
        self.last_attempt = False

    async def call(self, system: str, user: str, model_cls: type[BaseModel], validate=None) -> CallResult:
        est = self.budget.est
        base = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        self.budget.check(est(system) + est(user))          # raises BudgetExceeded: never silently truncate
        messages = list(base)
        raws: list[dict] = []
        tin = tout = 0
        t0 = time.time()
        for attempt in range(int(self.s["retries"]) + 1):
            self.last_attempt = attempt >= int(self.s["retries"])           # a validator may stop insisting on its last attempt
            res = await self.backend.complete(messages, self.budget.output_reserve)
            tin += res.prompt_tokens or sum(est(m["content"]) for m in messages)
            tout += res.completion_tokens or est(res.text)
            if res.finish_reason == "length":
                raws.append({"response": res.text[:20000], "error": "reply cut off at the output limit"})
                raise ValidationFailed("reply was cut off at the output token limit", raws, truncated=True)
            try:
                value = model_cls.model_validate(parse_json(res.text))
                if validate:
                    validate(value)
                return CallResult(value, tin, tout, int((time.time() - t0) * 1000), attempt + 1, raws)
            except ValueError as e:                         # includes pydantic.ValidationError, JSONDecodeError
                raws.append({"response": res.text[:20000], "error": str(e)[:1500]})
                messages = base + [
                    {"role": "assistant", "content": res.text[:6000]},
                    {"role": "user", "content": f"That reply was invalid: {str(e)[:700]}\n"
                                                "Reply again with ONLY the corrected JSON object."}]
                try:
                    self.budget.check(sum(est(m["content"]) for m in messages))
                except BudgetExceeded:
                    break
        raise ValidationFailed(f"no valid reply after {len(raws)} attempts: {raws[-1]['error'][:300]}", raws)
