"""Gateway LLM: Claude principal, OpenAI fallback, plantilla determinista si no hay keys o fallan ambos."""
import json
import logging
import os
from functools import lru_cache
from typing import Protocol

log = logging.getLogger(__name__)


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

        self._c = anthropic.Anthropic(api_key=api_key, timeout=20)
        self._model = os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5")

    def complete(self, system: str, prompt: str) -> str | None:
        r = self._c.messages.create(model=self._model, max_tokens=600, system=system,
                                    messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in r.content if b.type == "text").strip() or None


class OpenAIClient:
    name = "openai"

    def __init__(self, api_key: str) -> None:
        import openai

        self._c = openai.OpenAI(api_key=api_key, timeout=20)
        self._model = os.getenv("OPENAI_MODEL", "gpt-5-mini")

    def complete(self, system: str, prompt: str) -> str | None:
        r = self._c.chat.completions.create(model=self._model, messages=[
            {"role": "system", "content": system}, {"role": "user", "content": prompt}])
        return (r.choices[0].message.content or "").strip() or None


class FallbackLLM:
    """Prueba cada proveedor en orden; devuelve None si todos fallan (el agente usa su plantilla)."""

    def __init__(self, clients: list[LLMClient]) -> None:
        self.clients = clients
        self.last_provider = "template"

    def complete(self, system: str, prompt: str) -> str | None:
        for c in self.clients:
            try:
                out = c.complete(system, prompt)
                if out:
                    self.last_provider = c.name
                    return out
            except Exception as e:  # noqa: BLE001 — cualquier fallo del proveedor activa el fallback
                log.warning("LLM %s falló: %s", c.name, e)
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
