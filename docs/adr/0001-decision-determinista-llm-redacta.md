# ADR-0001 — Decisión de aptitud determinista; el LLM solo redacta

- **Estado:** Aceptado · 2026-10-19

## Contexto
El onboarding bancario exige decisiones auditables, reproducibles y explicables ante regulador. Un modelo
generativo es no determinista, puede alucinar y es vulnerable a prompt injection vía datos del prospecto.

## Decisión
La aptitud (`status`, `decision.eligible`, `reasons`) la calcula un **motor de políticas determinista**
(`policies.py`). El LLM (Claude principal → OpenAI fallback → plantilla sin keys) solo **redacta** el
`customer_message` y **enriquece** propuestas de mitigación que parten de un catálogo determinista.

## Consecuencias
- ✅ Misma entrada ⇒ misma decisión; tests deterministas; auditoría clara.
- ✅ El sistema funciona sin keys ni red (modo plantilla), útil en CI y ante caídas del proveedor.
- ⚠️ Menos flexibilidad ante casos no previstos → se cubren con **escalamiento humano**, no con el LLM.
- ⚠️ Cambiar políticas requiere despliegue de código (versionado y revisado, deseable en banca).
