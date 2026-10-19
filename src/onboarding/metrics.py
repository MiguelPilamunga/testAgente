"""Métricas operativas en CloudWatch Embedded Metric Format (EMF): una línea JSON por grupo a stdout.

Lambda envía stdout a CloudWatch Logs y CloudWatch extrae las métricas sin llamadas a la API ni dependencias.
La mayoría se deriva del slice de auditoría de cada ejecución del motor (`RunMetrics.finish`), así registry y
cliente LLM no necesitan hooks. Sin PII: las dimensiones son solo valores de catálogo (producto conocido, paso,
severidad, estado, tool, agente, proveedor, motivo); nunca nombre ni document_id.

Activación: METRICS_ENABLED=1/0 explícito; si no está, solo dentro de Lambda (AWS_LAMBDA_FUNCTION_NAME).
"""

import json
import os
import sys
import time
from datetime import datetime
from typing import Any

from onboarding.models import OnboardingState, Status
from onboarding.policies import PRODUCTS, TOOL_MAX_ATTEMPTS

NAMESPACE = "OnboardingAgent"
OUTCOMES = {Status.APPROVED, Status.APPROVED_WITH_CONDITIONS, Status.REJECTED, Status.ESCALATED}

COUNT, MS, SECONDS = "Count", "Milliseconds", "Seconds"


def enabled() -> bool:
    flag = os.getenv("METRICS_ENABLED")
    if flag is not None:
        return flag == "1"
    return bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME"))


def product_dim(product: str) -> str:
    # `product` es texto libre del cliente: fuera de catálogo se agrupa para no crear dimensiones arbitrarias.
    return product if product in PRODUCTS else "unknown"


def llm_flags(llm: Any, raw: str | None, provider: str) -> dict[str, bool]:
    """Campos de auditoría para métricas LLM: `provider` es quien produjo el texto final (o "template")."""
    clients = getattr(llm, "clients", [])
    primary = clients[0].name if clients else None
    exhausted = bool(clients) and raw is None and llm.spent() >= llm.budget
    return {"llm_fallback": primary is not None and provider != primary, "llm_budget_exhausted": exhausted}


class Emitter:
    """Acumula datapoints agrupados por dimensiones y los imprime como registros EMF."""

    def __init__(self, **properties: Any) -> None:
        self.properties = properties  # propiedades no indexadas (p. ej. onboarding_id), nunca PII
        self._groups: dict[tuple, dict[str, tuple[str, list[float]]]] = {}

    def add(
        self,
        name: str,
        value: float,
        unit: str = COUNT,
        dims: dict[str, str] | None = None,
        rollup: bool = True,
        sum_: bool = True,
    ) -> None:
        dims = dims or {}
        sets = [sorted(dims)] + ([[]] if dims and rollup else [])
        key = (tuple(sorted(dims.items())), tuple(tuple(s) for s in sets))
        metrics = self._groups.setdefault(key, {})
        _, values = metrics.setdefault(name, (unit, []))
        if sum_ and values:
            values[0] += value
        else:
            values.append(value)

    def records(self) -> list[dict]:
        ts = int(time.time() * 1000)
        out = []
        for (dims, sets), metrics in self._groups.items():
            out.append(
                {
                    "_aws": {
                        "Timestamp": ts,
                        "CloudWatchMetrics": [
                            {
                                "Namespace": NAMESPACE,
                                "Dimensions": [list(s) for s in sets],
                                "Metrics": [{"Name": n, "Unit": u} for n, (u, _) in metrics.items()],
                            }
                        ],
                    },
                    **self.properties,
                    **dict(dims),
                    **{n: v[0] if len(v) == 1 else v for n, (_, v) in metrics.items()},
                }
            )
        return out

    def flush(self) -> None:
        if enabled():
            for rec in self.records():
                print(json.dumps(rec, ensure_ascii=False), file=sys.stdout, flush=True)
        self._groups.clear()


class RunMetrics:
    """Métricas de una ejecución del motor (start o resolve), derivadas del estado y su auditoría."""

    def __init__(self, state: OnboardingState, source: str) -> None:
        self.source = source
        self.audit_mark = len(state.audit)
        self.esc_mark = len(state.escalations)
        self.t0 = time.perf_counter()
        self.emitter = Emitter(onboarding_id=state.onboarding_id)

    def step(self, step: str, started: float) -> None:
        self.emitter.add(
            "StepLatencyMs", (time.perf_counter() - started) * 1000, MS, {"Step": step}, sum_=False
        )

    def finish(self, state: OnboardingState) -> None:
        em, product = self.emitter, product_dim(state.prospect.product)
        if self.source == "start":
            em.add("OnboardingStarted", 1, dims={"Product": product})
        if state.status in OUTCOMES:
            em.add(
                "OnboardingDecision",
                1,
                dims={"Status": state.status.value, "Source": self.source},
                rollup=False,
            )
            em.add(
                "OnboardingDecision",
                1,
                dims={"Status": state.status.value, "Source": self.source, "Product": product},
                rollup=False,
            )
        for esc in state.escalations[self.esc_mark :]:
            em.add("Escalations", 1, dims={"Step": esc.step, "Severity": esc.severity})
        self._from_audit(state)
        em.add(
            "EndToEndLatencyMs",
            (time.perf_counter() - self.t0) * 1000,
            MS,
            {"Source": self.source},
            sum_=False,
        )
        em.flush()

    def _from_audit(self, state: OnboardingState) -> None:
        em, last_tool = self.emitter, "unknown"
        for ev in state.audit[self.audit_mark :]:
            d = ev.detail
            match ev.event:
                case "tool_call":
                    last_tool = d.get("tool", "unknown")
                    em.add("ToolCalls", 1, dims={"Tool": last_tool})
                case "tool_error":
                    em.add("ToolErrors", 1, dims={"Tool": last_tool})
                    if d.get("attempt", TOOL_MAX_ATTEMPTS) < TOOL_MAX_ATTEMPTS:
                        em.add("ToolRetries", 1, dims={"Tool": last_tool})
                case "tool_denied":
                    em.add("ToolDenied", 1, dims={"Agent": ev.agent})
                case "llm_output_rejected":
                    em.add("LLMOutputRejected", 1, dims={"Reason": d.get("reason", "unknown")})
                case "message_generated" | "proposal" if "provider" in d:
                    em.add("LLMCalls", 1, dims={"Provider": d["provider"]})
                    if d.get("llm_fallback"):
                        em.add("LLMFallbacks", 1)
                    if d.get("llm_budget_exhausted"):
                        em.add("LLMBudgetExhausted", 1)


def escalation_resolved(state: OnboardingState, escalation_id: str, step: str, action: str) -> None:
    """EscalationResolved + TimeToResolveSeconds (desde el evento `escalated` de esa escalación)."""
    em = Emitter(onboarding_id=state.onboarding_id)
    em.add("EscalationResolved", 1, dims={"Action": action})
    opened = next(
        (
            e.ts
            for e in reversed(state.audit)
            if e.event == "escalated"
            and e.detail.get("escalation_id", escalation_id) == escalation_id
            and e.detail.get("step") == step
        ),
        None,
    )
    if opened:
        seconds = datetime.now(datetime.fromisoformat(opened).tzinfo) - datetime.fromisoformat(opened)
        em.add("TimeToResolveSeconds", seconds.total_seconds(), SECONDS, {"Action": action}, sum_=False)
    em.flush()
