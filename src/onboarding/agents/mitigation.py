from onboarding.llm.client import FallbackLLM
from onboarding.models import Escalation, OnboardingState

SYSTEM = ("Eres analista de cumplimiento de un banco. Dada una verificación fallida o ambigua de onboarding, "
          "propone en máximo 3 viñetas acciones concretas para resolverla, respetando la política dada. "
          "No apruebes ni rechaces: solo propone.")


class MitigationAgent:
    """Sin tools. La propuesta base sale del catálogo de políticas; el LLM solo la enriquece."""

    name = "MitigationAgent"

    def __init__(self, llm: FallbackLLM) -> None:
        self.llm = llm

    def propose(self, state: OnboardingState, base: str, reason: str) -> str:
        extra = self.llm.complete(SYSTEM, f"Motivo: {reason}\nPolítica/propuesta base: {base}")
        state.log(self.name, "proposal", provider=self.llm.last_provider, reason=reason)
        return f"{base}\n{extra}" if extra else base

    def enrich(self, state: OnboardingState, esc: Escalation) -> Escalation:
        esc.proposal = self.propose(state, esc.proposal, esc.reason)
        return esc
