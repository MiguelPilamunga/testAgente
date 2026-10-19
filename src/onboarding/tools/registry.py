"""Registro de tools con allowlist por agente: el orquestador decide qué puede usar cada sub-agente."""
from collections.abc import Callable
from typing import Any

from onboarding.models import OnboardingState


class ToolNotPermittedError(PermissionError):
    pass


class ToolError(RuntimeError):
    """Falla de un servicio externo (simulada en los mocks)."""


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., dict]] = {}
        self._grants: dict[str, set[str]] = {}

    def register(self, name: str, fn: Callable[..., dict]) -> None:
        self._tools[name] = fn

    def grant(self, agent: str, *tools: str) -> None:
        self._grants.setdefault(agent, set()).update(tools)

    def allowed(self, agent: str) -> set[str]:
        return set(self._grants.get(agent, set()))

    def call(self, agent: str, tool: str, state: OnboardingState, **kwargs: Any) -> dict:
        if tool not in self._grants.get(agent, set()):
            state.log(agent, "tool_denied", tool=tool)
            raise ToolNotPermittedError(f"{agent} no tiene permiso para usar {tool}")
        state.log(agent, "tool_call", tool=tool, args=kwargs)
        result = self._tools[tool](**kwargs)
        state.log(agent, "tool_result", tool=tool, result=result)
        return result
