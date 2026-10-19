"""Allowlist de tools por agente (SPEC: Tools y permisos)."""

import pytest

from onboarding.models import OnboardingRequest, OnboardingState
from onboarding.tools import mocks
from onboarding.tools.registry import ToolNotPermittedError, ToolRegistry


@pytest.fixture
def state():
    return OnboardingState(
        prospect=OnboardingRequest(prospect_name="Ana Pérez", document_id="1712345678", product="cuenta_ahorros")
    )


@pytest.fixture
def registry():
    reg = ToolRegistry()
    reg.register("verify_identity", mocks.verify_identity)
    reg.register("check_risk_lists", mocks.check_risk_lists)
    reg.register("prepare_documentation", mocks.prepare_documentation)
    reg.grant("IdentityAgent", "verify_identity")
    reg.grant("RiskAgent", "check_risk_lists")
    reg.grant("DocumentationAgent", "prepare_documentation")
    return reg


def test_allowed_tool_call_succeeds_and_is_audited(registry, state):
    result = registry.call("IdentityAgent", "verify_identity", state, document_id="1712345678")
    assert result == {"verified": True, "confidence": 0.97}
    events = [(e.agent, e.event) for e in state.audit]
    assert ("IdentityAgent", "tool_call") in events
    assert ("IdentityAgent", "tool_result") in events


@pytest.mark.parametrize(
    "agent, tool, kwargs",
    [
        ("IdentityAgent", "check_risk_lists", {"name": "x", "document_id": "1712345678"}),
        ("RiskAgent", "verify_identity", {"document_id": "1712345678"}),
        ("ResponseAgent", "verify_identity", {"document_id": "1712345678"}),
        ("MitigationAgent", "prepare_documentation", {"product": "cuenta_ahorros", "client_data": {}}),
    ],
)
def test_not_permitted_tool_raises_and_is_audited(registry, state, agent, tool, kwargs):
    with pytest.raises(ToolNotPermittedError):
        registry.call(agent, tool, state, **kwargs)
    denied = [e for e in state.audit if e.agent == agent and e.event == "tool_denied"]
    assert denied and denied[0].detail.get("tool") == tool
    # nunca se ejecutó la tool
    assert not any(e.event == "tool_call" for e in state.audit)


def test_agents_without_tools_have_empty_allowlist(registry):
    assert registry.allowed("ResponseAgent") == set()
    assert registry.allowed("MitigationAgent") == set()


def test_tool_not_permitted_is_a_permission_error():
    assert issubclass(ToolNotPermittedError, PermissionError)
