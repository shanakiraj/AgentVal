import json
from pathlib import Path

import pytest

from agentval.db import init_db, make_engine, set_engine

SAMPLE = Path(__file__).resolve().parents[1] / "agentval" / "sample_data"


@pytest.fixture()
def db(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    engine = make_engine(url)
    set_engine(engine)
    init_db(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def sample_dataset() -> dict:
    return json.loads((SAMPLE / "customer_service.json").read_text())


def fast_config(name: str) -> dict:
    cfg = json.loads((SAMPLE / "configs" / f"{name}.json").read_text())
    cfg["agent"]["speed"] = 0
    cfg["retry_base_delay"] = 0
    return cfg
