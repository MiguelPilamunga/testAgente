"""Tests de contrato HTTP contra docs/SPEC.md."""

import pytest

START = "/api/v1/onboarding/start"


def _start(client, document_id="1712345678", product="cuenta_ahorros", name="Ana Pérez"):
    return client.post(START, json={"prospect_name": name, "document_id": document_id, "product": product})


def _open_escalation(body):
    return next(e for e in body["escalations"] if e["status"] == "OPEN")


def test_health(client):
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize(
    "document_id, expected_status",
    [
        ("1712345678", "APPROVED"),
        ("1799999999", "APPROVED"),  # "cualquier otro"
        ("0900000001", "REJECTED"),
        ("0900000002", "ESCALATED"),
        ("0900000003", "ESCALATED"),
        ("0900000004", "APPROVED_WITH_CONDITIONS"),
        ("0900000005", "ESCALATED"),
    ],
)
def test_scenarios_by_document_id(client, document_id, expected_status):
    resp = _start(client, document_id=document_id)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == expected_status
    assert body["onboarding_id"]
    assert isinstance(body["audit"], list) and body["audit"]
    assert isinstance(body["customer_message"], str) and body["customer_message"]


def test_response_shape(client):
    body = _start(client).json()
    for key in (
        "onboarding_id", "status", "current_step", "decision", "steps",
        "escalations", "required_documents", "customer_message", "audit",
    ):
        assert key in body, key
    assert body["current_step"] == "done"
    assert body["decision"]["eligible"] is True
    assert {"identity", "risk", "documentation"} <= set(body["steps"])
    assert body["required_documents"]
    for ev in body["audit"]:
        assert {"ts", "agent", "event", "detail"} <= set(ev)


def test_identity_ambiguous_pauses_at_identity(client):
    body = _start(client, document_id="0900000002").json()
    assert body["current_step"] == "identity"
    esc = _open_escalation(body)
    assert esc["step"] == "identity"
    assert esc["proposal"]


def test_high_risk_escalates_to_compliance(client):
    body = _start(client, document_id="0900000003").json()
    assert body["current_step"] == "risk"
    assert _open_escalation(body)["step"] == "risk"


def test_medium_risk_adds_enhanced_due_diligence_docs(client):
    base = _start(client, document_id="1712345678").json()
    pep = _start(client, document_id="0900000004").json()
    assert pep["decision"]["eligible"] is True
    assert len(pep["required_documents"]) > len(base["required_documents"])


def test_identity_not_verified_rejected_with_proposal(client):
    body = _start(client, document_id="0900000001").json()
    assert body["decision"]["eligible"] is False
    assert body["decision"]["reasons"]
    assert body["proposals"]
    text = " ".join(body["proposals"])
    assert "presencial" in text.lower() or "agencia" in text.lower()


@pytest.mark.parametrize("document_id", ["123", "12345678901", "17123456ab", "", "171234567 "])
def test_invalid_document_id_returns_422(client, document_id):
    assert _start(client, document_id=document_id).status_code == 422


def test_missing_fields_returns_422(client):
    assert client.post(START, json={"document_id": "1712345678"}).status_code == 422


def test_unknown_product_rejected_with_alternatives(client):
    resp = _start(client, product="hipoteca_lunar")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "REJECTED"
    assert body["proposals"]
    text = " ".join(body["proposals"])
    assert any(p in text for p in ("cuenta_ahorros", "cuenta_corriente", "tarjeta_credito"))


def test_get_returns_state(client):
    started = _start(client, document_id="0900000002").json()
    resp = client.get(f"/api/v1/onboarding/{started['onboarding_id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["onboarding_id"] == started["onboarding_id"]
    assert body["status"] == "ESCALATED"
    assert body["escalations"] == started["escalations"]


def test_get_unknown_returns_404(client):
    assert client.get("/api/v1/onboarding/00000000-0000-0000-0000-000000000000").status_code == 404


def _resolve(client, oid, esc_id, action, notes="revisado por analista"):
    return client.post(
        f"/api/v1/onboarding/{oid}/resolve",
        json={"escalation_id": esc_id, "action": action, "notes": notes},
    )


def test_resolve_approve_resumes_to_approved(client):
    started = _start(client, document_id="0900000002").json()
    esc = _open_escalation(started)
    resp = _resolve(client, started["onboarding_id"], esc["id"], "approve")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "APPROVED"
    assert body["current_step"] == "done"
    assert all(e["status"] == "RESOLVED" for e in body["escalations"] if e["id"] == esc["id"])
    # reanudó: ejecutó risk y documentation después del escalamiento
    assert "risk" in body["steps"] and "documentation" in body["steps"]
    # persistido
    again = client.get(f"/api/v1/onboarding/{started['onboarding_id']}").json()
    assert again["status"] == "APPROVED"


def test_resolve_reject_ends_rejected(client):
    started = _start(client, document_id="0900000003").json()
    esc = _open_escalation(started)
    body = _resolve(client, started["onboarding_id"], esc["id"], "reject").json()
    assert body["status"] == "REJECTED"
    assert body["decision"]["eligible"] is False


def test_resolve_unknown_escalation_returns_404_or_409(client):
    started = _start(client, document_id="0900000002").json()
    resp = _resolve(client, started["onboarding_id"], "no-existe", "approve")
    assert resp.status_code in (404, 409)


def test_resolve_already_resolved_escalation_returns_404_or_409(client):
    started = _start(client, document_id="0900000002").json()
    esc = _open_escalation(started)
    assert _resolve(client, started["onboarding_id"], esc["id"], "approve").status_code == 200
    assert _resolve(client, started["onboarding_id"], esc["id"], "approve").status_code in (404, 409)


def test_resolve_on_unknown_onboarding_returns_404(client):
    resp = _resolve(client, "00000000-0000-0000-0000-000000000000", "x", "approve")
    assert resp.status_code == 404


def test_resolve_invalid_action_returns_422(client):
    started = _start(client, document_id="0900000002").json()
    esc = _open_escalation(started)
    assert _resolve(client, started["onboarding_id"], esc["id"], "maybe").status_code == 422
