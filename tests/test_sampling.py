"""Per-task sampling: creative tasks run warmer than JSON extraction, optional fields are sent only when the server took them."""
import asyncio
import json

from pydantic import BaseModel

from story import llm, settings as settings_mod
from story.llm import LLMResult


class Out(BaseModel):
    ok: bool = True


class Rec:
    """A backend that takes `params` and records what it was given."""
    def __init__(self):
        self.params = []

    async def complete(self, messages, max_tokens, params=None):
        self.params.append(params)
        return LLMResult(json.dumps({"ok": True}))


class Old:
    """A test double with the old signature (no params): it must still be called."""
    def __init__(self):
        self.n = 0

    async def complete(self, messages, max_tokens):
        self.n += 1
        return LLMResult(json.dumps({"ok": True}))


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_table_and_global_default(env):
    s = settings_mod.get()
    assert settings_mod.sampling("p2_narrate", s)["temperature"] == 0.7
    assert settings_mod.sampling("p2_narrate_tag", s)["temperature"] == 0.1
    assert settings_mod.sampling("analyze_chunk", s) == {"temperature": s["temperature"]}      # Phase 1 tasks keep the global value


def test_optional_fields_need_the_probe(env):
    s = settings_mod.get()
    assert "top_p" not in settings_mod.sampling("p2_narrate", s)
    settings_mod.update({"sampling_probe": {"top_p": True, "frequency_penalty": False}})
    s = settings_mod.get()
    got = settings_mod.sampling("p2_narrate", s)
    assert got["top_p"] == 0.95 and "frequency_penalty" not in got


def test_owner_override_wins(env):
    settings_mod.update({"sampling": {"p2_narrate": {"temperature": 0.9}}})
    assert settings_mod.sampling("p2_narrate")["temperature"] == 0.9


def test_caller_sends_the_task_temperature(env):
    be = Rec()
    caller = llm.JsonCaller(be)
    run(caller.call("[TASK:p2_narrate] system", "user", Out))
    assert be.params[-1]["temperature"] == 0.7 and caller.sampling["temperature"] == 0.7


def test_old_style_backend_still_works(env):
    be = Old()
    run(llm.JsonCaller(be).call("[TASK:p2_narrate] system", "user", Out))
    assert be.n == 1


def test_chat_backend_payload_merges_params(env, monkeypatch):
    sent = {}

    class R:
        status_code = 200
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}], "usage": {}}

    class C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            sent.update(json)
            return R()

    monkeypatch.setattr(llm.httpx, "AsyncClient", C)
    be = llm.ChatBackend(settings_mod.get(), "k")
    run(be.complete([{"role": "user", "content": "x"}], 10, {"temperature": 0.9, "top_p": 0.9}))
    assert sent["temperature"] == 0.9 and sent["top_p"] == 0.9
