from onboarding.agents.response import LLM_MAX_CHARS, contradiction, scrub_pii
from onboarding.llm.client import FallbackLLM
from onboarding.metrics import llm_flags
from onboarding.models import Escalation, OnboardingState, Status

SYSTEM = ("Eres analista de cumplimiento de un banco. Dada una verificación fallida o ambigua de onboarding, "
          "propone en máximo 3 viñetas acciones concretas para resolverla, respetando la política dada. "
          "No apruebes ni rechaces: solo propone.")


class MitigationAgent:
    """Sin tools. La propuesta al cliente sale SOLO del catálogo de políticas; el LLM enriquece una propuesta
    interna para el oficial (state.steps[step]["internal_proposal"]) que nunca llega al cliente."""

    name = "MitigationAgent"

    def __init__(self, llm: FallbackLLM) -> None:
        self.llm = llm

    def _validated_extra(self, state: OnboardingState, base: str, reason: str) -> tuple[str | None, str | None]:
        """(texto validado o None, salida cruda del LLM para métricas)."""
        raw = self.llm.complete(SYSTEM, scrub_pii(state, f"Motivo: {reason}\nPolítica/propuesta base: {base}"))
        if not raw:
            return None, raw
        # Una mitigación nunca acompaña una aprobación: se valida como caso no aprobado.
        cause = "too_long" if len(raw) > LLM_MAX_CHARS else contradiction(Status.ESCALATED, raw)
        if cause:
            state.log(self.name, "llm_output_rejected", provider=self.llm.last_provider, reason=cause)
            return None, raw
        return raw, raw

    def propose(self, state: OnboardingState, base: str, reason: str, step: str | None = None) -> str:
        """Devuelve la propuesta para el cliente (solo base) y guarda la interna enriquecida en el paso."""
        extra, raw = self._validated_extra(state, base, reason)
        internal = f"{base}\n{extra}" if extra else base
        state.steps.setdefault(step or state.current_step, {})["internal_proposal"] = internal
        provider = self.llm.last_provider if extra else "template"
        state.log(self.name, "proposal", provider=provider, reason=reason,
                  **llm_flags(self.llm, raw, provider))
        return base

    def enrich(self, state: OnboardingState, esc: Escalation) -> Escalation:
        # esc.proposal se mantiene con el texto del catálogo: si el oficial rechaza, el orquestador lo copia a
        # proposals (lo que ve el cliente).
        esc.proposal = self.propose(state, esc.proposal, esc.reason, step=esc.step)
        return esc
