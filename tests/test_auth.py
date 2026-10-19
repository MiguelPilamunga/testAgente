"""Defensa en profundidad de /resolve: grupo `compliance` exigido con AUTH_MODE=apigw."""

import pytest
from fastapi.testclient import TestClient

from onboarding.auth import _parse_groups

START = "/api/v1/onboarding/start"
ACCOUNT = "111122223333"


@pytest.fixture(autouse=True)
def _expected_account(monkeypatch):
    monkeypatch.setenv("EXPECTED_ACCOUNT_ID", ACCOUNT)


def _client_with_claims(claims, account=ACCOUNT):
    """Envuelve la app inyectando el evento de API Gateway en el scope, como hace Mangum."""
    from onboarding.api import app

    async def asgi(scope, receive, send):
        if claims is not None:
            ctx = {"authorizer": {"jwt": {"claims": claims}}}
            if account is not None:
                ctx["accountId"] = account
            scope["aws.event"] = {"requestContext": ctx}
        await app(scope, receive, send)

    return TestClient(asgi)


def _escalated(client):
    body = client.post(
        START, json={"prospect_name": "Ana Pérez", "document_id": "0900000002", "product": "cuenta_ahorros"}
    ).json()
    esc = next(e for e in body["escalations"] if e["status"] == "OPEN")
    return body["onboarding_id"], esc["id"]


def _resolve(client, oid, eid):
    return client.post(
        f"/api/v1/onboarding/{oid}/resolve", json={"escalation_id": eid, "action": "approve", "notes": "ok"}
    )


@pytest.mark.parametrize(
    "claims",
    [
        None,  # sin evento de API Gateway
        {"sub": "u-1", "cognito:groups": "[ventas]"},
        {"sub": "u-1"},
        {"cognito:groups": "[compliance]"},  # sin sub
    ],
)
def test_apigw_rechaza_sin_grupo_compliance(orchestrator, monkeypatch, claims):
    monkeypatch.setenv("AUTH_MODE", "apigw")
    client = _client_with_claims(claims)
    oid, eid = _escalated(client)
    assert _resolve(client, oid, eid).status_code == 403
    assert orchestrator.get(oid).status == "ESCALATED"


def test_apigw_compliance_resuelve_y_audita_sub(orchestrator, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "apigw")
    client = _client_with_claims({"sub": "officer-42", "cognito:groups": "[compliance auditores]"})
    oid, eid = _escalated(client)
    resp = _resolve(client, oid, eid)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "APPROVED"
    assert any(
        a["event"] == "officer_authenticated" and a["detail"]["sub"] == "officer-42" for a in body["audit"]
    )
    assert "officer-42" in next(e for e in body["escalations"] if e["id"] == eid)["resolution"]


def test_auth_mode_ausente_es_fail_closed(orchestrator, monkeypatch):
    monkeypatch.delenv("AUTH_MODE", raising=False)
    client = _client_with_claims(None)
    oid, eid = _escalated(client)
    assert _resolve(client, oid, eid).status_code == 403


@pytest.mark.parametrize("allow, expected", [("1", 200), (None, 403), ("0", 403), ("true", 403)])
def test_auth_mode_none_requiere_allow_insecure_local(orchestrator, monkeypatch, allow, expected):
    monkeypatch.setenv("AUTH_MODE", "none")
    if allow is None:
        monkeypatch.delenv("ALLOW_INSECURE_LOCAL", raising=False)
    else:
        monkeypatch.setenv("ALLOW_INSECURE_LOCAL", allow)
    client = _client_with_claims(None)
    oid, eid = _escalated(client)
    assert _resolve(client, oid, eid).status_code == expected


def test_auth_mode_invalido_da_500(orchestrator, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "cognito")
    client = _client_with_claims({"sub": "officer-42", "cognito:groups": "[compliance]"})
    oid, eid = _escalated(client)
    resp = _resolve(client, oid, eid)
    assert resp.status_code == 500
    assert resp.json()["detail"] == "invalid AUTH_MODE"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("[compliance ventas]", ("compliance", "ventas")),
        ("compliance,ventas", ("compliance", "ventas")),
        (["compliance"], ("compliance",)),
        (None, ()),
    ],
)
def test_parse_groups(raw, expected):
    assert _parse_groups(raw) == expected


@pytest.mark.parametrize("allow", ["1", None])
def test_auth_mode_none_prohibido_en_lambda(orchestrator, monkeypatch, allow):
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "onboarding-agent-orchestrator")
    monkeypatch.setenv("AUTH_MODE", "none")
    if allow is None:
        monkeypatch.delenv("ALLOW_INSECURE_LOCAL", raising=False)
    else:
        monkeypatch.setenv("ALLOW_INSECURE_LOCAL", allow)
    client = _client_with_claims(None)
    oid, eid = _escalated(client)
    resp = _resolve(client, oid, eid)
    assert resp.status_code == 500
    assert orchestrator.get(oid).status == "ESCALATED"


def test_apigw_en_lambda_sigue_funcionando(orchestrator, monkeypatch):
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "onboarding-agent-orchestrator")
    monkeypatch.setenv("AUTH_MODE", "apigw")
    client = _client_with_claims({"sub": "officer-42", "cognito:groups": "[compliance]"})
    oid, eid = _escalated(client)
    assert _resolve(client, oid, eid).status_code == 200


OFFICER = {"sub": "officer-42", "cognito:groups": "[compliance]"}


@pytest.mark.parametrize("account", ["999988887777", "", None])
def test_apigw_rechaza_evento_de_otra_cuenta(orchestrator, monkeypatch, account):
    monkeypatch.setenv("AUTH_MODE", "apigw")
    client = _client_with_claims(OFFICER, account=account)
    oid, eid = _escalated(client)
    resp = _resolve(client, oid, eid)
    assert resp.status_code == 403
    assert orchestrator.get(oid).status == "ESCALATED"


@pytest.mark.parametrize("value", [None, "", "  "])
def test_apigw_sin_expected_account_id_es_error_de_configuracion(orchestrator, monkeypatch, value):
    monkeypatch.setenv("AUTH_MODE", "apigw")
    if value is None:
        monkeypatch.delenv("EXPECTED_ACCOUNT_ID", raising=False)
    else:
        monkeypatch.setenv("EXPECTED_ACCOUNT_ID", value)
    client = _client_with_claims(OFFICER)
    oid, eid = _escalated(client)
    resp = _resolve(client, oid, eid)
    assert resp.status_code == 500
    assert orchestrator.get(oid).status == "ESCALATED"


def test_auth_mode_none_local_no_exige_expected_account(orchestrator, monkeypatch):
    monkeypatch.delenv("EXPECTED_ACCOUNT_ID", raising=False)
    client = _client_with_claims(None)
    oid, eid = _escalated(client)
    assert _resolve(client, oid, eid).status_code == 200
