from onboarding.agents.base import Agent, StepOutcome
from onboarding.models import Escalation, OnboardingState
from onboarding.policies import MITIGATIONS


class RiskAgent(Agent):
    name = "RiskAgent"

    def run(self, state: OnboardingState) -> StepOutcome:
        p = state.prospect
        r = self.tool("check_risk_lists", state, name=p.prospect_name, document_id=p.document_id)
        if r["risk_level"] == "high":
            return StepOutcome(r, escalation=Escalation(
                step="risk", severity="high", proposal=MITIGATIONS["risk_high"],
                reason="Riesgo alto: " + "; ".join(r["matches"])))
        if r["risk_level"] == "medium":
            return StepOutcome(r, proposal=MITIGATIONS["risk_medium"])
        return StepOutcome(r)
