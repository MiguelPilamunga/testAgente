from onboarding.agents.base import Agent, StepOutcome
from onboarding.models import OnboardingState
from onboarding.policies import MITIGATIONS, PRODUCTS


class DocumentationAgent(Agent):
    name = "DocumentationAgent"

    def run(self, state: OnboardingState) -> StepOutcome:
        product = state.prospect.product
        if product not in PRODUCTS:
            return StepOutcome({"product": product}, reject_reason=f"Producto '{product}' no ofertado",
                               proposal=MITIGATIONS["product_unknown"])
        risk = state.steps.get("risk", {}).get("risk_level", "low")
        r = self.tool("prepare_documentation", state, product=product,
                      client_data={"name": state.prospect.prospect_name,
                                   "document_id": state.prospect.document_id, "risk_level": risk})
        return StepOutcome(r)
