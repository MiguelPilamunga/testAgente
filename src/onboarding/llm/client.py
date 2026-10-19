"""Gateway LLM: Claude principal, OpenAI fallback, plantilla determinista si no hay keys o fallan ambos."""
import json
import logging
import math
import os
import time
from collections import deque
from collections.abc import Callable
from functools import lru_cache
from typing import Protocol

log = logging.getLogger(__name__)


def _float_env(name: str, default: float) -> float:
    """Lee segundos desde el entorno; solo acepta valores finitos y > 0 (nan/inf/≤0 romperían el límite de 29 s)."""
    try:
        value = float(os.getenv(name, default))
    except ValueError:
        return default
    return value if math.isfinite(value) and value > 0 else default


# Una petición hace hasta 2 llamadas LLM (mitigación + respuesta) × 2 proveedores; con estos topes el peor caso
# (presupuesto agotado + una llamada en curso) cabe en el timeout de 29 s de API Gateway/Lambda.
LLM_TIMEOUT = _float_env("LLM_TIMEOUT", 6.0)  # por llamada, sin reintentos del SDK
LLM_BUDGET = _float_env("LLM_BUDGET", 15.0)  # segundos de LLM permitidos dentro de la ventana
LLM_BUDGET_WINDOW = _float_env("LLM_BUDGET_WINDOW", 29.0)  # ≈ duración máxima de una petición


class LLMClient(Protocol):
    name: str

    def complete(self, system: str, prompt: str) -> str | None: ...


@lru_cache
def _secrets() -> dict:
    """En AWS las keys viven en Secrets Manager (LLM_SECRET_ARN); localmente en .env/entorno."""
    arn = os.getenv("LLM_SECRET_ARN")
    if not arn:
        return {}
    import boto3

    raw = boto3.client("secretsmanager").get_secret_value(SecretId=arn)["SecretString"]
    return json.loads(raw)


def _key(name: str) -> str | None:
    return os.getenv(name) or _secrets().get(name)


class AnthropicClient:
    name = "anthropic"

    def __init__(self, api_key: str) -> None:
        import anthropic

        self._c = anthropic.Anthropic(api_key=api_key, timeout=LLM_TIMEOUT, max_retries=0)
        self._model = os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5")

    def complete(self, system: str, prompt: str) -> str | None:
        r = self._c.messages.create(model=self._model, max_tokens=600, system=system,
                                    messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in r.content if b.type == "text").strip() or None


class OpenAIClient:
    name = "openai"

    def __init__(self, api_key: str) -> None:
        import openai

        self._c = openai.OpenAI(api_key=api_key, timeout=LLM_TIMEOUT, max_retries=0)
        self._model = os.getenv("OPENAI_MODEL", "gpt-5-mini")

    def complete(self, system: str, prompt: str) -> str | None:
        r = self._c.chat.completions.create(model=self._model, messages=[
            {"role": "system", "content": system}, {"role": "user", "content": prompt}])
        return (r.choices[0].message.content or "").strip() or None


class FallbackLLM:
    """Prueba cada proveedor en orden; devuelve None si todos fallan (el agente usa su plantilla).

    Presupuesto de latencia: si en la última ventana (`budget_window` s, ≈ una petición) ya se gastaron
    `budget` s en llamadas LLM, no se llama a ningún proveedor y se va directo a plantilla.
    """

    def __init__(self, clients: list[LLMClient], budget: float = LLM_BUDGET,
                 budget_window: float = LLM_BUDGET_WINDOW,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.clients = clients
        self.last_provider = "template"
        self.budget, self.budget_window, self._clock = budget, budget_window, clock
        self._spent: deque[tuple[float, float]] = deque()  # (inicio, duración) de cada llamada

    def spent(self) -> float:
        cutoff = self._clock() - self.budget_window
        while self._spent and self._spent[0][0] < cutoff:
            self._spent.popleft()
        return sum(d for _, d in self._spent)

    def complete(self, system: str, prompt: str) -> str | None:
        for c in self.clients:
            if self.spent() >= self.budget:
                log.warning("Presupuesto LLM agotado (%.1f s); se usa plantilla", self.budget)
                break
            start = self._clock()
            try:
                out = c.complete(system, prompt)
                if out:
                    self.last_provider = c.name
                    return out
            except Exception as e:  # noqa: BLE001 — cualquier fallo del proveedor activa el fallback
                log.warning("LLM %s falló: %s", c.name, e)
            finally:
                self._spent.append((start, self._clock() - start))
        self.last_provider = "template"
        return None


def build_llm() -> FallbackLLM:
    provider = os.getenv("LLM_PROVIDER", "anthropic")
    if provider == "none":
        return FallbackLLM([])
    order = ["openai", "anthropic"] if provider == "openai" else ["anthropic", "openai"]
    factories = {"anthropic": ("ANTHROPIC_API_KEY", AnthropicClient), "openai": ("OPENAI_API_KEY", OpenAIClient)}
    clients: list[LLMClient] = []
    for p in order:
        env, cls = factories[p]
        if key := _key(env):
            clients.append(cls(key))
    return FallbackLLM(clients)
