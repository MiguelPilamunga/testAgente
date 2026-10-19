# STATE — onboarding-agent (2026-10-19)

## Hecho
- Orquestador multi-agente (identidad, riesgo, documentación, respuesta, mitigación) con allowlist de tools por agente,
  máquina de estados con pausa por escalamiento y `/resolve` (estado conversacional persistido).
- Decisión determinista por políticas; LLM (Claude → OpenAI → plantilla) solo redacta, con guardrail anti-contradicción.
- Seguridad: JWT Cognito, `/resolve` solo grupo `compliance`, auth fail-closed (prohibido `AUTH_MODE=none` en Lambda),
  PII enmascarada en auditoría y prompts, TTL 90 días en DynamoDB.
- Métricas CloudWatch EMF + dashboard `onboarding-agent-dev-ops` + 8 alarmas (SNS).
- AWS: stack `onboarding-agent-dev` (cuenta 774305616818, us-east-1), desplegado con IAM `onboarding-deployer`
  con permissions boundary. API: https://o8pjot00p9.execute-api.us-east-1.amazonaws.com
- Evidencia: pytest 156 passed; newman local 27/27 (143 assertions); newman AWS 28/28 (145 assertions, p95 241 ms).

## Pendiente
- Cargar keys LLM nuevas en Secrets Manager `onboarding-agent/llm-keys` (hoy vacío → modo plantilla).
- Decidir IAM Access Analyzer de acceso externo (cuenta compartida).
- Al cerrar la evaluación: borrar access key de `onboarding-deployer`; `aws logout` de la sesión root.
- Backlog: bandeja de escalamientos para oficiales (RF-12); idempotencia de `/start` (RNF-13); NER para PII en texto libre.

## Cómo trabajar
- Gate local obligatorio (sin CI/CD): skill `verify`. Integración: skill `integrate`. Deploy manual: ver README / ADR-0005.
- Sesiones paralelas: `scripts/launch-sessions.sh` (prompts en `scripts/prompts/`).
