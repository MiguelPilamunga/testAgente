from fastapi import FastAPI, HTTPException
from mangum import Mangum

from onboarding.llm.client import build_llm
from onboarding.models import OnboardingRequest, OnboardingState, ResolveRequest
from onboarding.orchestrator import EscalationNotFound, EscalationNotOpen, Orchestrator
from onboarding.state.store import build_store

app = FastAPI(title="Onboarding Orchestrator", version="0.1.0")
orchestrator = Orchestrator(build_store(), build_llm())


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/v1/onboarding/start", response_model=OnboardingState)
def start(req: OnboardingRequest) -> OnboardingState:
    return orchestrator.start(req)


@app.get("/api/v1/onboarding/{onboarding_id}", response_model=OnboardingState)
def get_state(onboarding_id: str) -> OnboardingState:
    state = orchestrator.get(onboarding_id)
    if not state:
        raise HTTPException(404, "onboarding no encontrado")
    return state


@app.post("/api/v1/onboarding/{onboarding_id}/resolve", response_model=OnboardingState)
def resolve(onboarding_id: str, body: ResolveRequest) -> OnboardingState:
    state = get_state(onboarding_id)
    try:
        return orchestrator.resolve(state, body.escalation_id, body.action, body.notes)
    except EscalationNotFound:
        raise HTTPException(404, "escalamiento no encontrado") from None
    except EscalationNotOpen:
        raise HTTPException(409, "escalamiento ya resuelto") from None


handler = Mangum(app)
