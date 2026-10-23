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
    settings_mod.update({"retry_backoff_s": 0, "retries": 2})
    return tmp_path


def pytest_collection_modifyitems(config, items):
    import os
    if os.environ.get("LIVE_LLM") == "1":
        return
    skip = pytest.mark.skip(reason="set LIVE_LLM=1 to run against the real model")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
