"""LOPDP: minimización de PII en auditoría (RNF-09) y retención con TTL en DynamoDB (RNF-11)."""

import json
import time

import pytest

from onboarding.models import OnboardingRequest, OnboardingState, mask_document_id, mask_name, mask_pii
from onboarding.state import store as store_mod
from onboarding.state.store import DynamoDBStore

DOC, NAME = "1712345678", "Juan Carlos Pérez"


def test_mask_helpers():
    assert mask_document_id(DOC) == "******5678"
    assert mask_name("Juan Pérez") == "J. P."
    nested = {"args": {"client_data": {"name": NAME, "document_id": DOC}}, "items": [{"prospect_name": NAME}],
              "tool": "verify_identity", "confidence": 0.97}
    assert mask_pii(nested) == {"args": {"client_data": {"name": "J. C. P.", "document_id": "******5678"}},
                                "items": [{"prospect_name": "J. C. P."}], "tool": "verify_identity",
                                "confidence": 0.97}


@pytest.mark.parametrize("document_id", ["1712345678", "0900000002", "0900000004"])
def test_audit_never_contains_full_pii(orchestrator, document_id):
    state = orchestrator.start(OnboardingRequest(prospect_name=NAME, document_id=document_id,
                                                 product="tarjeta_credito"))
    dump = json.dumps([e.model_dump() for e in state.audit], ensure_ascii=False)
    assert document_id not in dump
    assert NAME not in dump and "Pérez" not in dump
    assert any(e.event == "tool_call" for e in state.audit)
    assert "******" + document_id[-4:] in dump
    # el dato operativo completo se conserva fuera de la auditoría
    assert state.prospect.document_id == document_id and state.prospect.prospect_name == NAME


def test_audit_masking_survives_persistence(orchestrator):
    state = orchestrator.start(OnboardingRequest(prospect_name=NAME, document_id=DOC, product="cuenta_ahorros"))
    persisted = orchestrator.get(state.onboarding_id)
    assert DOC not in json.dumps([e.model_dump() for e in persisted.audit])


class FakeTable:
    def __init__(self):
        self.items = {}

    def put_item(self, Item):  # firma de boto3
        self.items[Item["onboarding_id"]] = Item

    def get_item(self, Key):
        return {"Item": self.items[Key["onboarding_id"]]} if Key["onboarding_id"] in self.items else {}


def _dynamo_store():
    s = DynamoDBStore.__new__(DynamoDBStore)
    s._t = FakeTable()
    return s


@pytest.mark.parametrize("env, days", [(None, 90), ("30", 30), ("abc", 90)])
def test_dynamodb_item_has_ttl(monkeypatch, env, days):
    if env is None:
        monkeypatch.delenv("STATE_TTL_DAYS", raising=False)
    else:
        monkeypatch.setenv("STATE_TTL_DAYS", env)
    store = _dynamo_store()
    state = OnboardingState(prospect=OnboardingRequest(prospect_name=NAME, document_id=DOC, product="cuenta_ahorros"))
    before = int(time.time())
    store.save(state)
    item = store._t.items[state.onboarding_id]
    assert isinstance(item["expires_at"], int)
    assert before + days * 86400 <= item["expires_at"] <= int(time.time()) + days * 86400
    assert store.get(state.onboarding_id).onboarding_id == state.onboarding_id


def test_state_ttl_days_default(monkeypatch):
    monkeypatch.delenv("STATE_TTL_DAYS", raising=False)
    assert store_mod.state_ttl_days() == 90
