from onboarding.agents.base import Agent, StepOutcome
from onboarding.models import Escalation, OnboardingState
from onboarding.policies import IDENTITY_MIN_CONFIDENCE, MITIGATIONS


class IdentityAgent(Agent):
    name = "IdentityAgent"

    def run(self, state: OnboardingState) -> StepOutcome:
        r = self.tool("verify_identity", state, document_id=state.prospect.document_id)
        if r["confidence"] < IDENTITY_MIN_CONFIDENCE:
            return StepOutcome(r, escalation=Escalation(
                step="identity", severity="medium", proposal=MITIGATIONS["identity_ambiguous"],
                reason=f"Confianza {r['confidence']:.2f} < umbral {IDENTITY_MIN_CONFIDENCE}"))
        if not r["verified"]:
            return StepOutcome(r, reject_reason="Identidad no verificada contra Registro Civil",
                               proposal=MITIGATIONS["identity_failed"])
        return StepOutcome(r)
