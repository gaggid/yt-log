import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
from story import db, settings as settings_mod  # noqa: E402


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Fresh data dir + DB per test; fast retries."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    db.init(tmp_path / "test.db")
    from story2 import planner
    monkeypatch.setattr(planner, "LONG_BEAT_FACTOR", 1000)                                 # the test doubles write one long beat; the length rule has its own test
    monkeypatch.setattr(planner, "MAX_FIRST_SENTENCE_WORDS", 10_000)          # the test doubles write one long sentence; the opening-length rule has its own test
    settings_mod.update({"retry_backoff_s": 0, "retries": 2, "context_limit": 32768, "output_reserve": 6000,
                         "chunk_tokens": 9000, "chunk_overlap": 600})
    return tmp_path


@pytest.fixture(autouse=True)
def no_model_discovery(monkeypatch):
    """The gateway's model list must never change the set of image models inside a test (the dev machine's gateway may be running)."""
    from story2 import providers
    keep = dict(providers.PROVIDERS)
    monkeypatch.setattr(providers, "refresh", lambda *a, **k: [])
    yield
    for k in list(providers.PROVIDERS):
        if k not in keep:
            del providers.PROVIDERS[k]


def pytest_collection_modifyitems(config, items):
    import os
    if os.environ.get("LIVE_LLM") == "1":
        return
    skip = pytest.mark.skip(reason="set LIVE_LLM=1 to run against the real model")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
