"""Fixtures comunes: LLM desactivado (plantilla) y StateStore en memoria fresco por test."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "none")
    monkeypatch.setenv("STATE_BACKEND", "memory")
    # auth fail-closed: los tests corren en modo local explícito (tests/test_auth.py cubre apigw)
    monkeypatch.setenv("AUTH_MODE", "none")
    monkeypatch.setenv("ALLOW_INSECURE_LOCAL", "1")
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LLM_SECRET_ARN", "STATE_TABLE"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def orchestrator(monkeypatch):
    from onboarding import api
    from onboarding.llm.client import build_llm
    from onboarding.orchestrator import Orchestrator
    from onboarding.state.store import InMemoryStore

    orch = Orchestrator(InMemoryStore(), build_llm())
    monkeypatch.setattr(api, "orchestrator", orch)
    return orch


@pytest.fixture
def client(orchestrator):
    from onboarding.api import app

    with TestClient(app) as c:
        yield c
