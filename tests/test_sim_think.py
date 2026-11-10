"""Thinking per task (sim/think.py): the budget table, the story's setting, owner overrides, and that the budget reaches the model request in a real job."""
from sim import think
from test_sim_api import client, new_story, wait  # noqa: F401


def test_table_modes_and_overrides():
    assert think.budget("sm_write", "balanced") == 512 and think.budget("sm_plan", "balanced") == 2048
    assert think.budget("sm_plan", "off") == 0 and think.budget("sm_rollup", "deep") == 0
    assert think.budget("sm_referee", "deep") == 4096 and think.budget("sm_plan", "deep") <= think.DEEP_MAX
    s = think.apply({"sampling": {"sm_plan": {"temperature": 0.5, "thinking_budget": 100}, "p4_x": {"top_p": 1}}})["sampling"]
    assert s["sm_plan"] == {"thinking_budget": 100, "temperature": 0.5} and s["p4_x"] == {"top_p": 1} and s["sm_delta"] == {"thinking_budget": 1536}
    assert all(t in think.BUDGET for t in __import__("story.settings", fromlist=["SAMPLING"]).SAMPLING if t.startswith("sm_"))      # every task has a budget


def test_the_stories_setting_reaches_the_model_request(client):
    c = client
    pid = new_story(c)
    assert c.get(f"/api/sim/{pid}").json()["project"]["settings"]["thinking"] == "balanced"
    assert c.patch(f"/api/sim/{pid}", json={"settings": {"thinking": "sometimes"}}).status_code == 400
    c.post(f"/api/sim/{pid}/start")
    wait(c, pid)
    plan = c.fake.last("sm_plan")["params"]
    assert plan["thinking_budget"] == 2048 and plan["temperature"] == 0.8
    assert c.fake.last("sm_write")["params"]["thinking_budget"] == 512
    assert c.patch(f"/api/sim/{pid}", json={"settings": {"thinking": "off"}}).status_code == 200
    c.post(f"/api/sim/{pid}/chapters", json={"kind": "auto"})
    wait(c, pid)
    assert c.fake.last("sm_plan")["params"]["thinking_budget"] == 0 and c.fake.last("sm_delta")["params"]["thinking_budget"] == 0


def test_replies_get_room_and_a_cut_off_reply_is_asked_again_without_thinking():
    import asyncio
    import json
    from sim import engine, models as m, prompts as P
    from story.llm import LLMResult
    from story import settings as sm

    class Cut:
        def __init__(self):
            self.calls = []

        async def complete(self, messages, max_tokens, params=None):
            self.calls.append((max_tokens, dict(params or {})))
            if len(self.calls) == 1:
                return LLMResult('{"ops": [', "length")                 # the thinking ate the budget
            return LLMResult(json.dumps({"ops": []}))

    s = {**sm.get(), "retries": 0, "retry_backoff_s": 0}
    be = Cut()
    out = asyncio.run(engine._json(be, s, P.DELTA, "STATE", m.DeltaOut))
    assert out.ops == []
    (m1, p1), (m2, p2) = be.calls
    assert m1 >= 16000 and p1["thinking_budget"] == 1536                     # more room than the app default of 10000
    assert m2 > m1 and p2["thinking_budget"] == 0                            # second ask: no thinking, still more room
    r = think.room({"output_reserve": 10000, "context_limit": 65536, "timeout_s": 300})
    assert r["output_reserve"] == 16000 and r["timeout_s"] == 600
    assert think.room({"output_reserve": 30000, "context_limit": 65536, "timeout_s": 900})["output_reserve"] == 29491      # never lowers what the owner set, up to 45% of the window


def test_content_level_reaches_setup_and_chapter_prompts(client):
    from sim import content
    c = client
    pid = new_story(c)
    assert c.get(f"/api/sim/{pid}").json()["project"]["settings"]["content"] == "unfiltered"
    assert "CONTENT: " + content.TEXT["unfiltered"][:60] in c.fake.last("sm_cast")["user"]
    assert c.patch(f"/api/sim/{pid}", json={"settings": {"content": "anything"}}).status_code == 400
    c.post(f"/api/sim/{pid}/start")
    wait(c, pid)
    for task in ("sm_plan", "sm_write", "sm_archive"):
        assert "## CONTENT\n" + content.TEXT["unfiltered"][:60] in c.fake.last(task)["user"], task
    assert "never violations" in c.fake.last("sm_referee")["system"] and "unlawful" in c.fake.last("sm_archive")["system"]
    assert c.patch(f"/api/sim/{pid}", json={"settings": {"content": "clean"}}).status_code == 200
    c.post(f"/api/sim/{pid}/chapters", json={"kind": "auto"})
    wait(c, pid)
    assert "Keep the language clean" in c.fake.last("sm_write")["user"]


def test_mild_adult_romance_is_allowed_with_limits():
    from sim import content
    for lv in ("mature", "unfiltered"):
        assert "romance" in content.TEXT[lv].lower() and "before explicit detail" in content.TEXT[lv]
    assert "Only adults (18 or older)" in content.TEXT["unfiltered"] and "romance" not in content.TEXT["clean"].lower()


def test_a_scratch_copy_of_the_app_can_never_call_the_text_model(monkeypatch):
    import config
    import pytest
    from story import llm
    monkeypatch.setattr(config, "SCRATCH", True)
    with pytest.raises(RuntimeError, match="scratch copy"):
        llm.ChatBackend({"base_url": "http://127.0.0.1:8810/v1"}, "key")
    monkeypatch.setattr(config, "SCRATCH", False)
    assert llm.ChatBackend({"base_url": "http://127.0.0.1:8810/v1"}, "key").base.endswith("/v1")
