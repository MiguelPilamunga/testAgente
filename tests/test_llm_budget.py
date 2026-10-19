"""Presupuesto de latencia LLM en ventana deslizante (bajo el límite de 29 s de API Gateway)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from onboarding.llm import client as llm_client
from onboarding.llm.client import FallbackLLM

SRC = Path(__file__).resolve().parents[1] / "src"


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class SlowLLM:
    """Cliente falso que "tarda" `seconds` avanzando el reloj falso."""

    def __init__(self, name, clock, seconds, reply="ok", exc=None):
        self.name, self.clock, self.seconds, self.reply, self.exc, self.calls = name, clock, seconds, reply, exc, 0

    def complete(self, system, prompt):
        self.calls += 1
        self.clock.now += self.seconds
        if self.exc:
            raise self.exc
        return self.reply


def _llm(clock, *clients):
    return FallbackLLM(list(clients), budget=15.0, budget_window=29.0, clock=clock)


def test_budget_exhausted_skips_all_clients():
    clock = FakeClock()
    a = SlowLLM("anthropic", clock, seconds=8)
    llm = _llm(clock, a)
    assert llm.complete("s", "p") == "ok"
    assert llm.complete("s", "p") == "ok"
    assert llm.spent() == 16.0
    calls = a.calls
    assert llm.complete("s", "p") is None
    assert a.calls == calls  # no se llamó a ningún proveedor
    assert llm.last_provider == "template"


def test_budget_checked_before_each_fallback_provider():
    clock = FakeClock()
    a = SlowLLM("anthropic", clock, seconds=16, exc=TimeoutError())
    b = SlowLLM("openai", clock, seconds=1)
    llm = _llm(clock, a, b)
    assert llm.complete("s", "p") is None
    assert (a.calls, b.calls) == (1, 0)  # el fallback no se intenta si ya se agotó el presupuesto
    assert llm.last_provider == "template"


def test_failed_calls_also_consume_budget():
    clock = FakeClock()
    a = SlowLLM("anthropic", clock, seconds=6, exc=RuntimeError("timeout"))
    llm = _llm(clock, a)
    llm.complete("s", "p")
    llm.complete("s", "p")
    llm.complete("s", "p")
    assert llm.spent() == 18.0
    assert llm.complete("s", "p") is None
    assert a.calls == 3


def test_budget_recovers_after_window():
    clock = FakeClock()
    a = SlowLLM("anthropic", clock, seconds=16)
    llm = _llm(clock, a)
    llm.complete("s", "p")
    assert llm.complete("s", "p") is None
    clock.now += 29.5  # la llamada anterior sale de la ventana de 29 s
    assert llm.spent() == 0
    assert llm.complete("s", "p") == "ok"
    assert llm.last_provider == "anthropic"
    assert a.calls == 2


def test_budget_still_exhausted_inside_window():
    clock = FakeClock()
    a = SlowLLM("anthropic", clock, seconds=16)
    llm = _llm(clock, a)
    llm.complete("s", "p")
    clock.now += 10  # 26 s desde el inicio de la llamada: sigue dentro de la ventana
    assert llm.complete("s", "p") is None
    assert a.calls == 1


def test_defaults_fit_api_gateway_limit():
    assert llm_client.LLM_BUDGET + llm_client.LLM_TIMEOUT < 29.0
    llm = FallbackLLM([])
    assert (llm.budget, llm.budget_window) == (llm_client.LLM_BUDGET, llm_client.LLM_BUDGET_WINDOW)


@pytest.mark.parametrize("value", ["abc", "", "6s", "nan", "NaN", "inf", "-inf", "-1", "0", "0.0", "-0.5"])
def test_float_env_invalid_falls_back_to_default(monkeypatch, value):
    monkeypatch.setenv("LLM_TIMEOUT", value)
    assert llm_client._float_env("LLM_TIMEOUT", 6.0) == 6.0


def test_float_env_valid_value(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT", "3.5")
    assert llm_client._float_env("LLM_TIMEOUT", 6.0) == 3.5


@pytest.mark.parametrize("value", ["no-es-numero", "nan", "inf", "-1", "0"])
def test_invalid_env_at_import_uses_defaults(value):
    # Las constantes se leen al importar: se comprueba en un proceso limpio para no recargar el módulo compartido.
    env = {**os.environ, "LLM_TIMEOUT": value, "LLM_BUDGET": value, "LLM_BUDGET_WINDOW": value,
           "PYTHONPATH": str(SRC)}
    code = "from onboarding.llm import client as c; print(c.LLM_TIMEOUT, c.LLM_BUDGET, c.LLM_BUDGET_WINDOW)"
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
    assert out.stdout.split() == ["6.0", "15.0", "29.0"]
