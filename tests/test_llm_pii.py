"""RNF-09 LOPDP: los prompts enviados a proveedores LLM externos no llevan PII del prospecto."""

import re

import pytest

from onboarding.llm.client import FallbackLLM
from onboarding.models import OnboardingRequest
from onboarding.orchestrator import Orchestrator
from onboarding.state.store import InMemoryStore

FULL_NAME = "María José Andrade Villacís"
SURNAMES = ["José", "Andrade", "Villacís"]  # todo salvo el primer nombre
SCENARIOS = ["1712345678", "0900000001", "0900000002", "0900000003", "0900000004", "0900000005"]


class CapturingLLM:
    name = "anthropic"

    def __init__(self):
        self.sent: list[str] = []

    def complete(self, system, prompt):
        self.sent.append(f"{system}\n{prompt}")
        return "Gracias por tu interés en nuestro banco."


def _assert_no_pii(sent, document_id):
    assert sent, "el LLM debería haberse usado"
    for text in sent:
        assert FULL_NAME.lower() not in text.lower()
        assert document_id not in text
        assert not re.search(r"\d{10}", text), "ninguna cédula completa sale hacia el LLM"
        for surname in SURNAMES:
            assert not re.search(rf"\b{surname}\b", text, re.IGNORECASE), surname


def _start(llm, document_id, product="cuenta_ahorros", name=FULL_NAME):
    orch = Orchestrator(InMemoryStore(), FallbackLLM([llm]))
    state = orch.start(OnboardingRequest(prospect_name=name, document_id=document_id, product=product))
    return orch, state


@pytest.mark.parametrize("document_id", SCENARIOS)
def test_prompts_have_no_full_name_or_document_id(document_id):
    llm = CapturingLLM()
    _start(llm, document_id)
    _assert_no_pii(llm.sent, document_id)


@pytest.mark.parametrize("document_id", SCENARIOS)
def test_response_prompt_uses_only_first_name(document_id):
    llm = CapturingLLM()
    _start(llm, document_id)
    response_prompts = [t for t in llm.sent if "asistente de onboarding" in t]
    assert response_prompts
    assert all("'nombre': 'María'" in t for t in response_prompts)


@pytest.mark.parametrize("document_id, action", [("0900000002", "approve"), ("0900000003", "reject"),
                                                 ("0900000005", "retry")])
def test_prompts_after_resolve_have_no_pii(document_id, action):
    llm = CapturingLLM()
    orch, state = _start(llm, document_id)
    esc = state.open_escalation()
    orch.resolve(state, esc.id, action, f"revisado {FULL_NAME} {document_id}")
    _assert_no_pii(llm.sent, document_id)


def test_pii_in_free_text_product_is_scrubbed():
    # `product` es texto libre: un producto inexistente llega al motivo del rechazo y a los hechos.
    llm = CapturingLLM()
    _, state = _start(llm, "1712345678", product="Andrade 0912345678")
    assert state.status == "REJECTED"
    _assert_no_pii(llm.sent, "1712345678")
    assert not any("0912345678" in t for t in llm.sent)
    assert any("******5678" in t for t in llm.sent)


def test_customer_message_still_greets_by_first_name():
    llm = CapturingLLM()
    llm.complete = lambda system, prompt: None  # fuerza la plantilla
    _, state = _start(llm, "0900000001")
    assert "Hola María," in state.customer_message
