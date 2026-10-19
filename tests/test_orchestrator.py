"""Comportamiento del orquestador: reintento único, propuestas y reanudación (SPEC: máquina de estados)."""

import pytest

from onboarding import policies

START = "/api/v1/onboarding/start"


def _start(client, document_id, product="cuenta_ahorros"):
    resp = client.post(START, json={"prospect_name": "Ana Pérez", "document_id": document_id, "product": product})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _identity_calls(body):
    return [
        e for e in body["audit"]
        if e["event"] == "tool_call" and (e.get("detail") or {}).get("tool") == "verify_identity"
    ]


def test_tool_error_retried_exactly_once_then_escalates(client):
    body = _start(client, "0900000005")
    assert body["status"] == "ESCALATED"
    assert body["current_step"] == "identity"
    # 1 intento + 1 reintento
    assert len(_identity_calls(body)) == policies.TOOL_MAX_ATTEMPTS == 2
    esc = next(e for e in body["escalations"] if e["status"] == "OPEN")
    assert esc["step"] == "identity"
    assert esc["proposal"]
    assert "retry" in esc["proposal"].lower() or "reintent" in esc["proposal"].lower()


def test_successful_tool_is_not_retried(client):
    body = _start(client, "1712345678")
    assert len(_identity_calls(body)) == 1


def test_retry_action_reexecutes_step(client):
    body = _start(client, "0900000005")
    esc = next(e for e in body["escalations"] if e["status"] == "OPEN")
    resp = client.post(
        f"/api/v1/onboarding/{body['onboarding_id']}/resolve",
        json={"escalation_id": esc["id"], "action": "retry", "notes": "reintentar"},
    )
    assert resp.status_code == 200, resp.text
    after = resp.json()
    # el mock sigue fallando: re-ejecuta identity (2 llamadas más) y vuelve a escalar
    assert len(_identity_calls(after)) == 4
    assert after["status"] == "ESCALATED"
    assert after["current_step"] == "identity"


@pytest.mark.parametrize(
    "document_id, product",
    [
        ("0900000001", "cuenta_ahorros"),
        ("0900000002", "cuenta_ahorros"),
        ("0900000003", "cuenta_ahorros"),
        ("0900000005", "cuenta_ahorros"),
        ("1712345678", "producto_inexistente"),
    ],
)
def test_every_escalation_or_rejection_has_proposal(client, document_id, product):
    body = _start(client, document_id, product)
    assert body["status"] in ("ESCALATED", "REJECTED")
    # RF3: proponer una solución, no solo rechazar. Escalamientos (pausa) llevan `proposal`;
    # los rechazos definitivos la exponen en `proposals`.
    if body["status"] == "ESCALATED":
        assert any(e["status"] == "OPEN" for e in body["escalations"])
        for esc in body["escalations"]:
            assert isinstance(esc["proposal"], str) and esc["proposal"].strip()
            assert esc["severity"] in ("low", "medium", "high")
    else:
        assert body["proposals"] and all(isinstance(p, str) and p.strip() for p in body["proposals"])


def test_high_risk_never_auto_approved(client):
    body = _start(client, "0900000003")
    assert body["status"] == "ESCALATED"
    assert body["decision"]["eligible"] is not True
    assert "documentation" not in body["steps"]  # flujo pausado en risk


def test_approve_continues_from_next_step(client):
    body = _start(client, "0900000003")  # pausa en risk
    esc = next(e for e in body["escalations"] if e["status"] == "OPEN")
    after = client.post(
        f"/api/v1/onboarding/{body['onboarding_id']}/resolve",
        json={"escalation_id": esc["id"], "action": "approve", "notes": "homonimia descartada"},
    ).json()
    assert after["current_step"] == "done"
    assert "documentation" in after["steps"]
    # riesgo high aprobado manualmente por Cumplimiento → con condiciones, nunca APPROVED limpio
    assert after["status"] == "APPROVED_WITH_CONDITIONS"
    # risk no se re-ejecutó
    risk_calls = [e for e in after["audit"] if e["event"] == "tool_call"
                  and (e.get("detail") or {}).get("tool") == "check_risk_lists"]
    assert len(risk_calls) == 1


def test_decision_is_deterministic(client):
    a = _start(client, "0900000004")
    b = _start(client, "0900000004")
    assert a["status"] == b["status"] == "APPROVED_WITH_CONDITIONS"
    assert a["decision"] == b["decision"]
    assert a["required_documents"] == b["required_documents"]
    for doc in policies.ENHANCED_DUE_DILIGENCE_DOCS:
        assert doc in a["required_documents"]
