import pytest
from pydantic_ai import models

from dataset_store import DatasetStore


@pytest.fixture(autouse=True)
def no_network_models(monkeypatch):
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)


@pytest.fixture
def store(tmp_path):
    return DatasetStore(tmp_path)
