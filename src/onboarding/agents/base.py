from dataclasses import dataclass, field
from typing import Any

from onboarding.models import Escalation, OnboardingState
from onboarding.tools.registry import ToolRegistry


@dataclass
class StepOutcome:
    data: dict[str, Any] = field(default_factory=dict)
    escalation: Escalation | None = None
    reject_reason: str | None = None  # fallo definitivo (no ambiguo)
    proposal: str | None = None


class Agent:
    name = "agent"

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def tool(self, tool: str, state: OnboardingState, **kwargs: Any) -> dict:
        """Toda llamada pasa por el registry, que aplica el allowlist del agente."""
        return self.registry.call(self.name, tool, state, **kwargs)

    def run(self, state: OnboardingState) -> StepOutcome:
        raise NotImplementedError
