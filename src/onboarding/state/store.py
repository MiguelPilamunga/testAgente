"""Persistencia del estado conversacional entre pasos: memoria (local/tests) o DynamoDB (AWS)."""
import os
import time
from typing import Protocol

from onboarding.models import OnboardingState


class StateStore(Protocol):
    def get(self, onboarding_id: str) -> OnboardingState | None: ...

    def save(self, state: OnboardingState) -> None: ...


class InMemoryStore:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get(self, onboarding_id: str) -> OnboardingState | None:
        raw = self._data.get(onboarding_id)
        return OnboardingState.model_validate_json(raw) if raw else None

    def save(self, state: OnboardingState) -> None:
        self._data[state.onboarding_id] = state.model_dump_json()


def state_ttl_days() -> int:
    try:
        return int(os.getenv("STATE_TTL_DAYS", "90"))
    except ValueError:
        return 90


class DynamoDBStore:
    """`expires_at` (epoch s) alimenta el TTL de DynamoDB (LOPDP RNF-11): el expediente se elimina
    STATE_TTL_DAYS después de su última actualización."""

    def __init__(self, table: str) -> None:
        import boto3

        self._t = boto3.resource("dynamodb").Table(table)

    def get(self, onboarding_id: str) -> OnboardingState | None:
        item = self._t.get_item(Key={"onboarding_id": onboarding_id}).get("Item")
        return OnboardingState.model_validate_json(item["state"]) if item else None

    def save(self, state: OnboardingState) -> None:
        self._t.put_item(Item={"onboarding_id": state.onboarding_id, "status": state.status.value,
                               "state": state.model_dump_json(), "updated_at": state.updated_at,
                               "expires_at": int(time.time()) + state_ttl_days() * 86400})


def build_store() -> StateStore:
    if os.getenv("STATE_BACKEND") == "dynamodb":
        return DynamoDBStore(os.environ["STATE_TABLE"])
    return InMemoryStore()
