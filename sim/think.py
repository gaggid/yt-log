"""How much the model may think before each kind of reply (the gateway's `thinking_budget`, measured in docs/RUN_LOG.md). Thinking is on by default at the gateway and costs 3 to 4 times the time;
planning, state changes and the referee gain from it, prose and picking gain little. The story's setting `thinking` scales the table: off, balanced (default), deep. An owner override in the app's
sampling settings for a task always wins."""
from contextvars import ContextVar

MODES = ("off", "balanced", "deep")
BUDGET = {"sm_world": 1024, "sm_cast": 2048, "sm_trackers": 2048, "sm_rules": 1024, "sm_suggest": 512, "sm_items": 0,
          "sm_plan": 2048, "sm_minds": 0, "sm_delta": 1536, "sm_write": 512, "sm_referee": 2048, "sm_archive": 1024,
          "sm_polish": 512, "sm_bible": 3072, "sm_beats": 3072, "sm_pick": 256, "sm_condition": 256, "sm_rollup": 0, "sm_reread": 1024, "sm_panels": 512}
DEEP_FACTOR, DEEP_MAX = 2, 8192

mode: ContextVar[str] = ContextVar("sim_thinking", default="balanced")      # set by the job runner from the story's setting
boost: ContextVar[bool] = ContextVar("sim_thinking_boost", default=False)   # set by the engine when a chapter is about making, finding or learning something
BOOSTED = ("sm_plan", "sm_delta")
BOOST_FACTOR = 1.5


def budget(task: str, how: str | None = None) -> int:
    how = how or mode.get()
    if how == "off":
        return 0
    n = BUDGET.get(task, 0)
    if boost.get() and task in BOOSTED:
        n = int(n * BOOST_FACTOR)
    return min(DEEP_MAX, n * DEEP_FACTOR) if how == "deep" else n


def apply(s: dict, how: str | None = None) -> dict:
    """Settings for one JsonCaller: the table's budget for every sm_* task, under the owner's own per-task overrides."""
    own = s.get("sampling") or {}
    merged = {t: {"thinking_budget": budget(t, how), **{k: v for k, v in own.get(t, {}).items() if not (how == "off" and k == "thinking_budget")}} for t in BUDGET}
    return {**s, "sampling": {**own, **merged}}


# Room for the reply. max_tokens at the gateway covers the thinking AND the answer, and a cut-off reply kills the chapter step, so the story simulator asks for more room than the app's
# default, and a slow deep-thinking call is allowed to take longer. A cut-off reply is asked again once with thinking off and still more room (engine._json).
RESERVE, RESERVE_MAX, TIMEOUT_S = 16000, 24000, 600


def room(s: dict, more: bool = False) -> dict:
    ctx = int(s.get("context_limit", 65536))
    cap = max(1000, int(ctx * 0.45))                                  # settings refuse a reserve above 70% of the window; stay well under it
    want = RESERVE_MAX if more else RESERVE
    return {**s, "output_reserve": min(cap, max(int(s.get("output_reserve", 0)), want)), "timeout_s": max(int(s.get("timeout_s", 0)), TIMEOUT_S)}
