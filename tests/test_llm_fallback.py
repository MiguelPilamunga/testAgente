"""Gateway LLM con fallback y garantía de que el LLM solo redacta (SPEC: decisión de diseño clave)."""

import pytest

from onboarding import policies
from onboarding.agents import mitigation
from onboarding.agents.response import LLM_MAX_CHARS, ResponseAgent
from onboarding.llm import client as llm_client
from onboarding.llm.client import FallbackLLM, build_llm
from onboarding.models import OnboardingRequest, OnboardingState, Status
from onboarding.orchestrator import Orchestrator
from onboarding.state.store import InMemoryStore


class FakeLLM:
    def __init__(self, name, reply=None, exc=None):
        self.name, self.reply, self.exc, self.calls = name, reply, exc, 0

    def complete(self, system, prompt):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.reply


def _state(status=Status.REJECTED, proposals=("Acérquese a una agencia",)):
    s = OnboardingState(
        prospect=OnboardingRequest(prospect_name="Ana Pérez", document_id="0900000001", product="cuenta_ahorros")
    )
    s.status = status
    s.proposals = list(proposals)
    return s


def test_failing_provider_falls_back_to_next():
    first = FakeLLM("anthropic", exc=RuntimeError("503"))
    second = FakeLLM("openai", reply="Hola desde OpenAI")
    llm = FallbackLLM([first, second])
    assert llm.complete("sys", "prompt") == "Hola desde OpenAI"
    assert llm.last_provider == "openai"
    assert first.calls == second.calls == 1


def test_empty_reply_also_falls_back():
    llm = FallbackLLM([FakeLLM("anthropic", reply=""), FakeLLM("openai", reply="ok")])
    assert llm.complete("sys", "prompt") == "ok"
    assert llm.last_provider == "openai"


def test_first_provider_ok_skips_fallback():
    second = FakeLLM("openai", reply="no debería usarse")
    llm = FallbackLLM([FakeLLM("anthropic", reply="Hola desde Claude"), second])
    assert llm.complete("sys", "prompt") == "Hola desde Claude"
    assert llm.last_provider == "anthropic"
    assert second.calls == 0


def test_all_fail_returns_none_and_template_provider():
    llm = FallbackLLM([FakeLLM("anthropic", exc=TimeoutError()), FakeLLM("openai", exc=RuntimeError())])
    llm.last_provider = "anthropic"  # de una llamada previa exitosa
    assert llm.complete("sys", "prompt") is None
    assert llm.last_provider == "template"


def test_response_agent_uses_template_when_all_fail():
    llm = FallbackLLM([FakeLLM("anthropic", exc=RuntimeError()), FakeLLM("openai", exc=RuntimeError())])
    agent = ResponseAgent(llm)
    s = _state()
    msg = agent.run(s)
    assert msg == f"Estado de tu solicitud: No aprobada\n{agent.template(s)}"
    assert "agencia" in msg
    ev = s.audit[-1]
    assert (ev.agent, ev.event, ev.detail["provider"]) == ("ResponseAgent", "message_generated", "template")


def test_build_llm_none_has_no_clients():
    llm = build_llm()  # conftest fija LLM_PROVIDER=none
    assert llm.clients == []
    assert llm.complete("sys", "prompt") is None
    assert llm.last_provider == "template"


def test_build_llm_without_keys_has_no_clients(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    llm_client._secrets.cache_clear()
    assert build_llm().clients == []


@pytest.mark.parametrize(
    "document_id, product, expected",
    [
        ("0900000001", "cuenta_ahorros", Status.REJECTED),
        ("1712345678", "producto_inexistente", Status.REJECTED),
        ("0900000002", "cuenta_ahorros", Status.ESCALATED),
        ("0900000004", "cuenta_ahorros", Status.APPROVED_WITH_CONDITIONS),
    ],
)
def test_llm_output_never_changes_decision(document_id, product, expected):
    liar = FakeLLM("anthropic", reply="APROBADO")
    orch = Orchestrator(InMemoryStore(), FallbackLLM([liar]))
    state = orch.start(OnboardingRequest(prospect_name="Ana Pérez", document_id=document_id, product=product))
    assert liar.calls > 0  # el LLM sí se usó para redactar
    assert state.status == expected
    if expected == Status.REJECTED:
        assert state.decision.eligible is False
    if expected in (Status.REJECTED, Status.ESCALATED):
        # guardrail: el texto contradictorio se descarta y se usa la plantilla
        assert state.customer_message.split("\n")[1] != "APROBADO"
        assert state.customer_message == orch.responder.status_line(state) + "\n" + orch.responder.template(state)
        rejected = [e for e in state.audit if e.event == "llm_output_rejected"]
        assert rejected and rejected[-1].detail["provider"] == "anthropic"
    else:
        assert state.customer_message == "Estado de tu solicitud: Aprobada con condiciones\nAPROBADO"
    persisted = orch.get(state.onboarding_id)
    assert persisted.status == expected
    assert persisted.decision == state.decision


STATUS_LINES = {
    Status.APPROVED: "Aprobada",
    Status.APPROVED_WITH_CONDITIONS: "Aprobada con condiciones",
    Status.ESCALATED: "En revisión",
    Status.REJECTED: "No aprobada",
}


@pytest.mark.parametrize("status, label", STATUS_LINES.items())
def test_message_always_starts_with_deterministic_status_line(status, label):
    s = _state(status=status)
    msg = ResponseAgent(FallbackLLM([FakeLLM("anthropic", reply="Gracias por elegirnos.")])).run(s)
    first, rest = msg.split("\n", 1)
    assert first == f"Estado de tu solicitud: {label}"
    assert rest == "Gracias por elegirnos."


@pytest.mark.parametrize(
    "status, text",
    [
        (Status.REJECTED, "¡Felicidades! Tu cuenta está lista."),
        (Status.REJECTED, "Tu solicitud fue Aprobada."),
        (Status.ESCALATED, "Bienvenido al banco, ya eres cliente."),
        (Status.ESCALATED, "Your application was approved."),
        (Status.APPROVED, "Lamentamos informarte que tu solicitud fue rechazada."),
        (Status.APPROVED_WITH_CONDITIONS, "Tu solicitud no fue aprobada."),
    ],
)
def test_contradictory_llm_text_is_discarded_and_audited(status, text):
    s = _state(status=status)
    agent = ResponseAgent(FallbackLLM([FakeLLM("openai", reply=text)]))
    msg = agent.run(s)
    assert text not in msg
    assert msg.endswith(agent.template(s))
    ev = next(e for e in s.audit if e.event == "llm_output_rejected")
    assert ev.detail["provider"] == "openai"
    assert s.audit[-1].detail["provider"] == "template"


@pytest.mark.parametrize(
    "status, text",
    [
        (Status.REJECTED, "Lo sentimos, tu solicitud no fue aprobada. Te esperamos en una agencia."),
        (Status.ESCALATED, "Tu solicitud aún no ha sido aprobada; un especialista la revisa."),
        (Status.APPROVED, "¡Felicidades! Tu cuenta fue aprobada. Bienvenido."),
    ],
)
def test_coherent_llm_text_is_kept(status, text):
    s = _state(status=status)
    msg = ResponseAgent(FallbackLLM([FakeLLM("anthropic", reply=text)])).run(s)
    assert msg.endswith(text)
    assert not any(e.event == "llm_output_rejected" for e in s.audit)


def test_too_long_llm_text_is_discarded():
    s = _state(status=Status.APPROVED)
    agent = ResponseAgent(FallbackLLM([FakeLLM("anthropic", reply="a" * (LLM_MAX_CHARS + 1))]))
    msg = agent.run(s)
    assert msg.endswith(agent.template(s))
    ev = next(e for e in s.audit if e.event == "llm_output_rejected")
    assert ev.detail["reason"] == "too_long"


def test_mitigation_llm_text_does_not_leak_into_rejection_message():
    orch = Orchestrator(InMemoryStore(), FallbackLLM([FakeLLM("anthropic", reply="APROBADO")]))
    state = orch.start(OnboardingRequest(prospect_name="Ana Pérez", document_id="0900000001",
                                         product="cuenta_ahorros"))
    assert state.status == Status.REJECTED
    assert "APROBADO" not in state.customer_message


class PerAgentLLM(FakeLLM):
    """Responde `reply` al MitigationAgent y un texto neutro al ResponseAgent (distingue por prompt de sistema)."""

    def complete(self, system, prompt):
        self.calls += 1
        return self.reply if system == mitigation.SYSTEM else "Gracias por tu interés en nuestro banco."


def _orch(reply):
    return Orchestrator(InMemoryStore(), FallbackLLM([PerAgentLLM("anthropic", reply=reply)]))


def _run(orch, document_id, product="cuenta_ahorros"):
    return orch.start(OnboardingRequest(prospect_name="Ana Pérez", document_id=document_id, product=product))


@pytest.mark.parametrize(
    "document_id, product, step, key",
    [
        ("0900000001", "cuenta_ahorros", "identity", "identity_failed"),
        ("1712345678", "producto_inexistente", "documentation", "product_unknown"),
    ],
)
def test_customer_proposals_are_catalog_only(document_id, product, step, key):
    tip = "- Agendar cita en agencia Quito Norte"
    state = _run(_orch(tip), document_id, product)
    assert state.proposals == [policies.MITIGATIONS[key]]
    assert tip not in state.customer_message
    # el enriquecimiento válido queda solo en la propuesta interna para el oficial
    assert state.steps[step]["internal_proposal"] == f"{policies.MITIGATIONS[key]}\n{tip}"


@pytest.mark.parametrize("document_id, step", [("0900000002", "identity"), ("0900000003", "risk")])
def test_escalation_proposal_is_catalog_only_and_internal_is_enriched(document_id, step):
    tip = "- Solicitar prueba de vida"
    state = _run(_orch(tip), document_id)
    esc = state.open_escalation()
    assert tip not in esc.proposal
    assert esc.proposal in policies.MITIGATIONS.values()
    assert state.steps[step]["internal_proposal"].endswith(tip)


def test_officer_reject_never_leaks_llm_text_to_customer():
    orch = _orch("- Solicitar prueba de vida")
    state = _run(orch, "0900000002")
    esc = state.open_escalation()
    state = orch.resolve(state, esc.id, "reject", "documento ilegible")
    assert state.status == Status.REJECTED
    assert state.proposals[-1] == policies.MITIGATIONS["identity_ambiguous"]
    assert "- Solicitar prueba de vida" not in state.customer_message


@pytest.mark.parametrize("reply, cause", [("APROBADO", "approval_terms_in_non_approved"),
                                          ("x" * (LLM_MAX_CHARS + 1), "too_long")])
def test_invalid_mitigation_llm_text_is_discarded_and_audited(reply, cause):
    state = _run(_orch(reply), "0900000001")
    assert state.steps["identity"]["internal_proposal"] == policies.MITIGATIONS["identity_failed"]
    ev = next(e for e in state.audit if e.agent == "MitigationAgent" and e.event == "llm_output_rejected")
    assert ev.detail == {"provider": "anthropic", "reason": cause}
