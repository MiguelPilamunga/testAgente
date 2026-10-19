from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


def now() -> str:
    return datetime.now(UTC).isoformat()


# LOPDP (RNF-09, minimización): la auditoría no guarda cédula ni nombre completos; el dato operativo
# sigue en OnboardingState.prospect.
_ID_KEYS = {"document_id"}
_NAME_KEYS = {"name", "prospect_name"}


def mask_document_id(value: str) -> str:
    return "*" * max(len(value) - 4, 0) + value[-4:]


def mask_name(value: str) -> str:
    return " ".join(f"{w[0].upper()}." for w in value.split())


def mask_pii(value: Any, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {k: mask_pii(v, k) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [mask_pii(v) for v in value]
    if isinstance(value, str) and key in _ID_KEYS:
        return mask_document_id(value)
    if isinstance(value, str) and key in _NAME_KEYS:
        return mask_name(value)
    return value


class Status(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    APPROVED = "APPROVED"
    APPROVED_WITH_CONDITIONS = "APPROVED_WITH_CONDITIONS"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"


STEPS = ["identity", "risk", "documentation", "decision", "response", "done"]


class OnboardingRequest(BaseModel):
    prospect_name: str = Field(min_length=3, max_length=120)
    document_id: str = Field(pattern=r"^\d{10}$")
    product: str = Field(min_length=1, max_length=50)


class ResolveRequest(BaseModel):
    escalation_id: str
    action: Literal["approve", "reject", "retry"]
    notes: str = ""


class Escalation(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    step: str
    reason: str
    severity: Literal["low", "medium", "high"]
    proposal: str
    status: Literal["OPEN", "RESOLVED"] = "OPEN"
    resolution: str | None = None


class AuditEvent(BaseModel):
    ts: str = Field(default_factory=now)
    agent: str
    event: str
    detail: dict[str, Any] = {}


class Decision(BaseModel):
    eligible: bool | None = None
    reasons: list[str] = []


class OnboardingState(BaseModel):
    onboarding_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    prospect: OnboardingRequest
    status: Status = Status.IN_PROGRESS
    current_step: str = "identity"
    decision: Decision = Decision()
    steps: dict[str, Any] = {}
    escalations: list[Escalation] = []
    proposals: list[str] = []
    required_documents: list[str] = []
    customer_message: str = ""
    conversation: list[dict[str, str]] = []
    audit: list[AuditEvent] = []
    created_at: str = Field(default_factory=now)
    updated_at: str = Field(default_factory=now)

    def log(self, agent: str, event: str, **detail: Any) -> None:
        self.audit.append(AuditEvent(agent=agent, event=event, detail=mask_pii(detail)))
        self.updated_at = now()

    def open_escalation(self) -> Escalation | None:
        return next((e for e in self.escalations if e.status == "OPEN"), None)
