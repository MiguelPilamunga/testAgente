"""Orquestador: máquina de estados que coordina sub-agentes, aplica políticas y pausa ante incertidumbre."""
import time

from onboarding import metrics
from onboarding.agents.base import Agent, StepOutcome
from onboarding.agents.documentation import DocumentationAgent
from onboarding.agents.identity import IdentityAgent
from onboarding.agents.mitigation import MitigationAgent
from onboarding.agents.response import ResponseAgent
from onboarding.agents.risk import RiskAgent
from onboarding.llm.client import FallbackLLM
from onboarding.models import STEPS, Escalation, OnboardingRequest, OnboardingState, Status
from onboarding.policies import MITIGATIONS, TOOL_MAX_ATTEMPTS
from onboarding.state.store import StateStore
from onboarding.tools import mocks
from onboarding.tools.registry import ToolError, ToolRegistry


class EscalationNotFound(LookupError):
    pass


class EscalationNotOpen(ValueError):
    pass


def build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register("verify_identity", mocks.verify_identity)
    reg.register("check_risk_lists", mocks.check_risk_lists)
    reg.register("prepare_documentation", mocks.prepare_documentation)
    # Allowlist: cada sub-agente ve solo la tool de su especialidad (mínimo privilegio).
    reg.grant(IdentityAgent.name, "verify_identity")
    reg.grant(RiskAgent.name, "check_risk_lists")
    reg.grant(DocumentationAgent.name, "prepare_documentation")
    return reg


class Orchestrator:
    name = "Orchestrator"

    def __init__(self, store: StateStore, llm: FallbackLLM, registry: ToolRegistry | None = None) -> None:
        self.store = store
        self.registry = registry or build_registry()
        self.agents: dict[str, Agent] = {
            "identity": IdentityAgent(self.registry),
            "risk": RiskAgent(self.registry),
            "documentation": DocumentationAgent(self.registry),
        }
        self.mitigation = MitigationAgent(llm)
        self.responder = ResponseAgent(llm)

    # ---- API pública -------------------------------------------------------------------------------
    def start(self, req: OnboardingRequest) -> OnboardingState:
        state = OnboardingState(prospect=req)
        state.conversation.append({"role": "customer", "content": f"Solicito {req.product}"})
        state.log(self.name, "started", product=req.product)
        return self._run(state)

    def get(self, onboarding_id: str) -> OnboardingState | None:
        return self.store.get(onboarding_id)

    def resolve(self, state: OnboardingState, escalation_id: str, action: str, notes: str) -> OnboardingState:
        esc = next((e for e in state.escalations if e.id == escalation_id), None)
        if esc is None:
            raise EscalationNotFound(escalation_id)
        if esc.status != "OPEN":
            raise EscalationNotOpen(escalation_id)
        esc.status, esc.resolution = "RESOLVED", f"{action}: {notes}".strip()
        state.conversation.append({"role": "officer", "content": f"{action} — {notes}"})
        state.log(self.name, "escalation_resolved", escalation_id=esc.id, action=action)
        metrics.escalation_resolved(state, esc.id, esc.step, action)
        state.status = Status.IN_PROGRESS
        if action == "approve":
            state.steps.setdefault(esc.step, {})["manual_override"] = notes or "aprobado por oficial"
            state.current_step = STEPS[STEPS.index(esc.step) + 1]
        elif action == "reject":
            self._reject(state, f"Rechazado por oficial: {notes}".strip(), esc.proposal)
        # retry: current_step se mantiene y el paso se re-ejecuta
        return self._run(state, source="resolve")

    # ---- motor -------------------------------------------------------------------------------------
    def _run(self, state: OnboardingState, source: str = "start") -> OnboardingState:
        run = metrics.RunMetrics(state, source)
        try:
            while state.current_step != "done":
                step = state.current_step
                started = time.perf_counter()
                try:
                    if step in self.agents:
                        if not self._run_agent_step(state, step):
                            break  # pausado por escalamiento
                    elif step == "decision":
                        self._decide(state)
                    elif step == "response":
                        self._respond(state)
                finally:
                    run.step(step, started)
                if state.current_step == step:
                    state.current_step = STEPS[STEPS.index(step) + 1]
            self.store.save(state)
            return state
        finally:
            run.finish(state)  # también si una excepción (p. ej. ToolNotPermittedError) corta el flujo

    def _call_with_retry(self, state: OnboardingState, step: str) -> StepOutcome:
        agent = self.agents[step]
        for attempt in range(1, TOOL_MAX_ATTEMPTS + 1):
            try:
                return agent.run(state)
            except ToolError as e:
                state.log(self.name, "tool_error", step=step, attempt=attempt, error=str(e))
        return StepOutcome({"error": "service_unavailable"}, escalation=Escalation(
            step=step, severity="medium", reason=f"Servicio de {step} no disponible tras "
                                                 f"{TOOL_MAX_ATTEMPTS} intentos",
            proposal=MITIGATIONS["tool_unavailable"]))

    def _run_agent_step(self, state: OnboardingState, step: str) -> bool:
        out = self._call_with_retry(state, step)
        state.steps[step] = {**state.steps.get(step, {}), **out.data}
        if out.escalation:
            state.escalations.append(self.mitigation.enrich(state, out.escalation))
            state.status = Status.ESCALATED
            state.log(self.name, "escalated", step=step, reason=out.escalation.reason,
                      escalation_id=state.escalations[-1].id)
            self._respond(state)
            return False
        if out.reject_reason:
            self._reject(state, out.reject_reason,
                         self.mitigation.propose(state, out.proposal or "", out.reject_reason))
        elif out.proposal:
            state.proposals.append(out.proposal)
        if step == "documentation":
            state.required_documents = out.data.get("required_documents", [])
        return True

    def _reject(self, state: OnboardingState, reason: str, proposal: str) -> None:
        state.decision.eligible = False
        state.decision.reasons.append(reason)
        state.proposals.append(proposal)
        state.current_step = "decision"
        state.log(self.name, "rejected", reason=reason)

    def _decide(self, state: OnboardingState) -> None:
        if state.decision.eligible is False:
            state.status = Status.REJECTED
            return
        risk = state.steps.get("risk", {}).get("risk_level", "low")
        overrides = [s for s, d in state.steps.items() if isinstance(d, dict) and "manual_override" in d]
        state.decision.eligible = True
        state.decision.reasons.append("Cumple políticas KYC y de riesgo del producto")
        if overrides:
            state.decision.reasons.append(f"Aprobación manual en: {', '.join(overrides)}")
        # Las condiciones dependen del riesgo; una identidad confirmada por un oficial no agrega condiciones.
        state.status = Status.APPROVED_WITH_CONDITIONS if risk != "low" else Status.APPROVED
        state.log(self.name, "decision", status=state.status.value)

    def _respond(self, state: OnboardingState) -> None:
        state.customer_message = self.responder.run(state)
        state.conversation.append({"role": "bank", "content": state.customer_message})
