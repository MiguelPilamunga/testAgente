"""Métricas EMF: forma del registro, catálogo emitido por escenario y ausencia de PII."""

import json

import pytest

from onboarding import metrics
from onboarding.llm.client import FallbackLLM
from onboarding.models import OnboardingRequest
from onboarding.orchestrator import Orchestrator
from onboarding.state.store import InMemoryStore
from onboarding.tools import mocks
from onboarding.tools.registry import ToolNotPermittedError, ToolRegistry

NAME, DOC = "Ana Pérez Villacís", "0900000004"


class FakeLLM:
    def __init__(self, name, reply=None, exc=None):
        self.name, self.reply, self.exc = name, reply, exc

    def complete(self, system, prompt):
        if self.exc:
            raise self.exc
        return self.reply


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("METRICS_ENABLED", "1")


def _records(capsys):
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith('{"_aws"')]


def _points(records):
    """{(métrica, ((dim, valor), ...)): valor} para cada conjunto de dimensiones declarado."""
    out = {}
    for rec in records:
        directive = rec["_aws"]["CloudWatchMetrics"][0]
        for m in directive["Metrics"]:
            for dset in directive["Dimensions"]:
                out[(m["Name"], tuple((d, rec[d]) for d in dset))] = rec[m["Name"]]
    return out


def _orch(llm=None, registry=None):
    return Orchestrator(InMemoryStore(), llm or FallbackLLM([]), registry)


def _start(orch, doc="1712345678", product="cuenta_ahorros", name=NAME):
    return orch.start(OnboardingRequest(prospect_name=name, document_id=doc, product=product))


def test_desactivado_fuera_de_lambda_por_defecto(monkeypatch, capsys):
    monkeypatch.delenv("METRICS_ENABLED", raising=False)
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    _start(_orch())
    assert _records(capsys) == []
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "onboarding-agent-api")
    assert metrics.enabled() is True
    monkeypatch.setenv("METRICS_ENABLED", "0")
    assert metrics.enabled() is False


def test_formato_emf_valido(on, capsys):
    _start(_orch())
    records = _records(capsys)
    assert records
    for rec in records:
        directive = rec["_aws"]["CloudWatchMetrics"][0]
        assert directive["Namespace"] == "OnboardingAgent"
        assert isinstance(rec["_aws"]["Timestamp"], int)
        for m in directive["Metrics"]:
            assert m["Name"] in rec and m["Unit"] in {"Count", "Milliseconds", "Seconds"}
        for dset in directive["Dimensions"]:
            assert all(d in rec for d in dset)


def test_aprobado_emite_catalogo_basico(on, capsys):
    _start(_orch())
    p = _points(_records(capsys))
    assert p[("OnboardingStarted", (("Product", "cuenta_ahorros"),))] == 1
    assert p[("OnboardingDecision", (("Source", "start"), ("Status", "APPROVED")))] == 1
    for tool in ("verify_identity", "check_risk_lists", "prepare_documentation"):
        assert p[("ToolCalls", (("Tool", tool),))] == 1
    for step in ("identity", "risk", "documentation", "decision", "response"):
        assert p[("StepLatencyMs", (("Step", step),))] >= 0
    assert p[("EndToEndLatencyMs", (("Source", "start"),))] >= 0
    assert p[("LLMCalls", (("Provider", "template"),))] >= 1
    assert ("LLMFallbacks", ()) not in p  # sin proveedores configurados la plantilla no es fallback


def test_sin_pii_y_producto_fuera_de_catalogo(on, capsys):
    _start(_orch(), doc=DOC, product="Ana Villacis 1712345678")
    out = json.dumps(_records(capsys), ensure_ascii=False)
    for secret in (NAME, "Pérez", "Villac", DOC, "1712345678"):
        assert secret not in out
    assert '"Product": "unknown"' in out


def test_servicio_caido_reintento_y_escalamiento(on, capsys):
    _start(_orch(), doc="0900000005")
    p = _points(_records(capsys))
    assert p[("ToolErrors", (("Tool", "verify_identity"),))] == 2
    assert p[("ToolRetries", (("Tool", "verify_identity"),))] == 1
    assert p[("Escalations", (("Severity", "medium"), ("Step", "identity")))] == 1
    assert p[("OnboardingDecision", (("Source", "start"), ("Status", "ESCALATED")))] == 1


def test_resolve_emite_resolucion_y_tiempo(on, capsys):
    orch = _orch()
    state = _start(orch, doc="0900000002")
    capsys.readouterr()
    orch.resolve(state, state.escalations[0].id, "approve", "ok")
    p = _points(_records(capsys))
    assert p[("EscalationResolved", (("Action", "approve"),))] == 1
    assert p[("TimeToResolveSeconds", (("Action", "approve"),))] >= 0
    assert p[("OnboardingDecision", (("Source", "resolve"), ("Status", "APPROVED")))] == 1
    assert ("OnboardingStarted", ()) not in p


def test_tool_denegada_se_mide_aunque_corte_el_flujo(on, capsys):
    reg = ToolRegistry()
    reg.register("verify_identity", mocks.verify_identity)  # registrada pero sin grant
    with pytest.raises(ToolNotPermittedError):
        _start(_orch(registry=reg))
    p = _points(_records(capsys))
    assert p[("ToolDenied", (("Agent", "IdentityAgent"),))] == 1


def test_llm_fallback_y_salida_rechazada(on, capsys):
    llm = FallbackLLM([FakeLLM("anthropic", exc=RuntimeError()), FakeLLM("openai", reply="APROBADO")])
    _start(_orch(llm), doc="0900000001")
    p = _points(_records(capsys))
    assert p[("LLMFallbacks", ())] >= 1
    assert p[("LLMOutputRejected", (("Reason", "approval_terms_in_non_approved"),))] >= 1


def test_llm_proveedor_secundario_cuenta_como_fallback(on, capsys):
    llm = FallbackLLM([FakeLLM("anthropic", exc=RuntimeError()), FakeLLM("openai", reply="Gracias.")])
    _start(_orch(llm))
    p = _points(_records(capsys))
    assert p[("LLMCalls", (("Provider", "openai"),))] == 1
    assert p[("LLMFallbacks", ())] == 1


def test_presupuesto_llm_agotado(on, capsys):
    _start(_orch(FallbackLLM([FakeLLM("anthropic", reply="hola")], budget=0.0)))
    p = _points(_records(capsys))
    assert p[("LLMBudgetExhausted", ())] >= 1
