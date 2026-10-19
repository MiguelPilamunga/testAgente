# ADR-0003 — Despliegue serverless en AWS (HTTP API + Lambda + DynamoDB, SAM)

- **Estado:** Aceptado · 2026-10-19

## Contexto
Carga irregular (picos por campañas), equipo pequeño, necesidad de estado durable entre `/start` y
`/resolve` (que puede ocurrir horas después) y de manejar keys LLM de forma segura.

## Decisión
- **API Gateway HTTP API** (stage `$default`, throttling) → **Lambda Python 3.12** con FastAPI + **Mangum**.
- Estado en **DynamoDB** (PK `onboarding_id`, on-demand, PITR, cifrado) vía `STATE_BACKEND=dynamodb`.
- Keys LLM en **Secrets Manager**; la Lambda solo tiene `GetSecretValue` sobre ese ARN (`LlmSecretArn`).
- Observabilidad en **CloudWatch** (logs con retención, access logs, X-Ray, alarma de errores).
- IaC con **AWS SAM** (`infra/template.yaml`).

## Alternativas descartadas
- ECS/Fargate: más operación y coste base para un tráfico bajo/irregular.
- Step Functions para la máquina de estados: buena opción futura para esperas humanas largas, pero añade
  complejidad; hoy la pausa se modela como estado persistido + `/resolve`.

## Consecuencias
- ✅ Pago por uso, sin servidores, escalado automático; Lambda stateless.
- ✅ Misma app FastAPI en local (uvicorn, `STATE_BACKEND=memory`) y en AWS.
- ⚠️ Cold starts (mitigable con arm64, paquete pequeño o provisioned concurrency).
- ⚠️ Límite de 29–30 s de integración → las llamadas LLM deben tener timeout corto y fallback a plantilla.
