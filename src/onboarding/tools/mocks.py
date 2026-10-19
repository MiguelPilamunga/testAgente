"""Mocks deterministas de servicios externos (ver tabla de escenarios en docs/SPEC.md)."""
from onboarding.policies import ENHANCED_DUE_DILIGENCE_DOCS, PRODUCTS
from onboarding.tools.registry import ToolError

_IDENTITY = {
    "0900000001": {"verified": False, "confidence": 0.93},
    "0900000002": {"verified": True, "confidence": 0.62},
}
_RISK = {
    "0900000003": {"risk_level": "high", "matches": ["OFAC-SDN: coincidencia nombre+documento"]},
    "0900000004": {"risk_level": "medium", "matches": ["PEP: funcionario público 2019-2023"]},
}


def verify_identity(document_id: str) -> dict:
    if document_id == "0900000005":
        raise ToolError("Registro Civil: servicio no disponible (timeout)")
    return dict(_IDENTITY.get(document_id, {"verified": True, "confidence": 0.97}))


def check_risk_lists(name: str, document_id: str) -> dict:
    return dict(_RISK.get(document_id, {"risk_level": "low", "matches": []}))


def prepare_documentation(product: str, client_data: dict) -> dict:
    policy = PRODUCTS[product]
    docs = list(policy["documents"])
    if client_data.get("risk_level") == "medium":
        docs += ENHANCED_DUE_DILIGENCE_DOCS
    return {"product": product, "required_documents": docs, "policy_refs": policy["policy_refs"]}
