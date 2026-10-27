"""Runtime settings: env/config defaults overlaid with values saved in the DB (editable from the UI)."""
import config
from . import db

LEGACY_MODEL = "gemma4-12b-qat-uncensored-hauhaucs-balanced"

DEFAULTS: dict = {
    "base_url": config.BASE_URL,
    "model": config.CHAT_MODEL,           # "" = let the model server choose (it is never named by this app unless the owner types one in Settings)
    "context_limit": 65536,       # tokens the model is configured for (model supports more; raise after testing)
    "output_reserve": 10000,      # tokens held back for the reply (also sent as max_tokens)
    "chunk_tokens": 8000,         # source tokens per analysis chunk
    "chunk_overlap": 600,         # tokens of preceding text repeated as read-only context
    "safety_margin": 0.10,        # fraction of the window never filled
    "chars_per_token": 3.5,
    "concurrency": 1,             # the gateway serves one request at a time
    "retries": 2,                 # extra attempts when the reply is not valid JSON for the schema
    "transport_retries": 3,       # connection errors / 5xx
    "retry_backoff_s": 5,
    "timeout_s": 300,
    "temperature": 0.2,
    "json_mode": "off",           # "on" sends response_format=json_object (set by the connection test if supported)
    "max_candidates": 30,         # story drafts per source; further leads stay listed and can be expanded
    "weights": {"hook": 25, "narrative": 20, "payoff": 20, "emotion": 15, "standalone": 20},
    "evidence_influence": 0.4,    # 0 = priority ignores evidence quality, 1 = priority scales fully with it
    "completeness_influence": 0.4,  # how much a missing turn/outcome or scattered evidence lowers priority (0 = ignore)
    "discover_window_chapters": 3,  # chapters (or sections) shown to one story-discovery call; smaller = more thorough
    "ocr": False,
}

_INT = {"context_limit", "output_reserve", "chunk_tokens", "chunk_overlap", "concurrency", "retries",
        "transport_retries", "timeout_s", "max_candidates", "discover_window_chapters"}
_FLOAT = {"safety_margin", "chars_per_token", "temperature", "evidence_influence", "completeness_influence", "retry_backoff_s"}
_STR = {"base_url", "model", "json_mode"}
_BOOL = {"ocr"}


class SettingsError(ValueError):
    pass


def _saved() -> dict:
    return {r["key"]: db.jload(r["value"]) for r in db.q("SELECT key, value FROM settings")}


def get() -> dict:
    s = {**DEFAULTS, **{k: v for k, v in _saved().items() if k in DEFAULTS}}
    s["weights"] = {**DEFAULTS["weights"], **(s.get("weights") or {})}
    if s.get("model") == LEGACY_MODEL:
        s["model"] = ""                  # an earlier version saved its default name into the database; the server's own default is used now
    return s


def api_key() -> str:
    return db.jload((db.one("SELECT value FROM settings WHERE key='api_key'") or {}).get("value"), "") or config.API_KEY


def validate(patch: dict) -> dict:
    out = {}
    for k, v in patch.items():
        if k not in DEFAULTS:
            raise SettingsError(f"unknown setting {k!r}")
        try:
            if k in _INT:
                v = int(v)
            elif k in _FLOAT:
                v = float(v)
            elif k in _STR:
                v = str(v).strip()
            elif k in _BOOL:
                v = bool(v)
            elif k == "weights":
                v = {n: float(x) for n, x in dict(v).items()}
                if set(v) != set(DEFAULTS["weights"]) or any(x < 0 for x in v.values()) or sum(v.values()) <= 0:
                    raise SettingsError("weights must cover " + ", ".join(DEFAULTS["weights"]) + " with a positive sum")
        except (TypeError, ValueError) as e:
            if isinstance(e, SettingsError):
                raise
            raise SettingsError(f"bad value for {k}: {v!r}") from e
        out[k] = v
    merged = {**get(), **out}
    if merged["context_limit"] < 4096:
        raise SettingsError("context_limit must be at least 4096")
    if not 1000 <= merged["output_reserve"] < merged["context_limit"] * 0.7:
        raise SettingsError("output_reserve must be >= 1000 and below 70% of the context limit")
    if not 0 <= merged["safety_margin"] < 0.5:
        raise SettingsError("safety_margin must be between 0 and 0.5")
    if not 0 <= merged["evidence_influence"] <= 1:
        raise SettingsError("evidence_influence must be between 0 and 1")
    if not 0 <= merged["completeness_influence"] <= 1:
        raise SettingsError("completeness_influence must be between 0 and 1")
    if merged["discover_window_chapters"] < 1:
        raise SettingsError("discover_window_chapters must be at least 1")
    if merged["chunk_tokens"] < 500 or merged["chunk_overlap"] < 0 or merged["chunk_overlap"] >= merged["chunk_tokens"]:
        raise SettingsError("chunk_tokens must be >= 500 and larger than chunk_overlap")
    if merged["concurrency"] < 1 or merged["retries"] < 0 or merged["timeout_s"] < 5:
        raise SettingsError("concurrency >= 1, retries >= 0, timeout_s >= 5")
    if merged["json_mode"] not in ("on", "off"):
        raise SettingsError("json_mode must be 'on' or 'off'")
    return out


def update(patch: dict) -> dict:
    patch = dict(patch)
    key = patch.pop("api_key", None)
    clean = validate(patch)
    with db.tx() as c:
        for k, v in clean.items():
            c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (k, db.jdump(v)))
        if key is not None:
            c.execute("INSERT INTO settings(key,value) VALUES('api_key',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (db.jdump(key),))
    return get()


def public() -> dict:
    s = get()
    s["api_key_set"] = bool(api_key())
    return s
