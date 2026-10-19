# SPEC — Agente Orquestador de Onboarding Digital

Fuente de verdad del caso (Evaluación Práctica B). Todas las sesiones trabajan contra este contrato.

## Problema
El banco necesita un **orquestador** que coordine sub-agentes especializados en el onboarding digital:
identidad, listas de riesgo, documentación (según políticas) y respuesta al cliente.
El orquestador controla **qué tools puede usar cada agente**, **maneja estado entre pasos** y **mitiga incertidumbre**.

## Requisitos funcionales
- RF1: Recibir solicitud de onboarding con datos del prospecto.
- RF2: Determinar bajo las políticas si el cliente es **apto** o no.
- RF3: Si una verificación falla o es ambigua → **proponer una solución** (no solo rechazar).

## Decisión de diseño clave
La **decisión de aptitud es determinista** (motor de políticas, auditable). El LLM (Claude principal,
OpenAI fallback, plantilla si no hay keys) solo **redacta** la respuesta al cliente y enriquece propuestas.
Un banco no puede delegar la aprobación a un modelo generativo.

## API
| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/v1/onboarding/start` | Inicia onboarding. Body: `{"prospect_name","document_id","product"}` |
| GET | `/api/v1/onboarding/{onboarding_id}` | Estado completo (pasos, auditoría, mensajes) |
| POST | `/api/v1/onboarding/{onboarding_id}/resolve` | Resuelve un escalamiento y **reanuda** el flujo. Body: `{"escalation_id","action":"approve"\|"reject"\|"retry","notes":str}` |
| GET | `/health` | Salud |

Validación: `document_id` = 10 dígitos numéricos (422 si no). `product` ∈ políticas (si no existe → REJECTED con propuesta de productos alternativos).

### Respuesta (start / get / resolve)
```json
{
  "onboarding_id": "uuid",
  "status": "IN_PROGRESS (transitorio) | APPROVED | APPROVED_WITH_CONDITIONS | REJECTED | ESCALATED",
  "current_step": "identity | risk | documentation | decision | response | done",
  "decision": {"eligible": true, "reasons": ["..."]},
  "steps": {"identity": {...}, "risk": {...}, "documentation": {...}},
  "escalations": [{"id","step","reason","severity","proposal","status":"OPEN|RESOLVED"}],
  "proposals": ["solución propuesta en rechazos definitivos y aprobaciones con condiciones (RF3)"],
  "required_documents": ["..."],
  "conversation": [{"role": "customer|bank|officer", "content": "..."}],
  "customer_message": "texto",
  "audit": [{"ts","agent","event","detail"}]
}
```

## Tools (mocks deterministas) y permisos
| Agente | Tools permitidas |
|---|---|
| IdentityAgent | `verify_identity(document_id)` → `{"verified":bool,"confidence":0..1}` |
| RiskAgent | `check_risk_lists(name, document_id)` → `{"risk_level":"low\|medium\|high","matches":[]}` |
| DocumentationAgent | `prepare_documentation(product, client_data)` → `{"product","required_documents":[],"policy_refs":[]}` |
| ResponseAgent | ninguna (solo LLM) |
| MitigationAgent | ninguna (solo LLM + catálogo de mitigaciones) |

Cualquier llamada fuera del allowlist → `ToolNotPermittedError` + evento en auditoría.

### Escenarios mock por `document_id`
| document_id | Comportamiento |
|---|---|
| `1712345678` y cualquier otro | identidad ok (0.97), riesgo low → APPROVED |
| `0900000001` | `verified=false, confidence=0.93` → REJECTED + propuesta (verificación presencial) |
| `0900000002` | `verified=true, confidence=0.62` → ESCALATED (identidad ambigua <0.8) |
| `0900000003` | `risk_level=high` matches OFAC → ESCALATED (cumplimiento) |
| `0900000004` | `risk_level=medium` match PEP → APPROVED_WITH_CONDITIONS (+docs debida diligencia reforzada) |
| `0900000005` | `verify_identity` lanza error de servicio → reintento 1 vez → ESCALATED (servicio no disponible) |

## Políticas (src/onboarding/policies.py)
- `IDENTITY_MIN_CONFIDENCE = 0.8` — por debajo → escalamiento.
- `verified=false` con confianza ≥ 0.8 → no apto, propuesta: verificación presencial en agencia.
- risk `high` → escalamiento a Cumplimiento (no se aprueba automáticamente).
- risk `medium` → apto con condiciones (debida diligencia reforzada).
- Productos: `cuenta_ahorros`, `cuenta_corriente`, `tarjeta_credito`, cada uno con documentos requeridos.

## Máquina de estados del orquestador
`identity → risk → documentation → decision → response → done`. Un escalamiento **pausa** el flujo
(`status=ESCALATED`, `current_step` = paso pausado). `resolve` con `approve` continúa desde el siguiente paso;
`retry` re-ejecuta el paso (si vuelve a fallar se abre un escalamiento nuevo; el anterior queda RESOLVED); `reject` termina en REJECTED. Estado persistido en `StateStore`
(memoria local / DynamoDB en AWS).

## Despliegue AWS
API Gateway (HTTP API) → Lambda (FastAPI + Mangum, Python 3.12) → DynamoDB (estado) ; keys LLM en
Secrets Manager. IaC con SAM (`infra/template.yaml`).

## Estructura
```
src/onboarding/
  api.py            FastAPI app + handler Lambda
  orchestrator.py   Orquestador (máquina de estados)
  policies.py       Políticas del banco
  models.py         Pydantic (request/state/escalation)
  agents/           identity.py risk.py documentation.py response.py mitigation.py base.py
  tools/            registry.py (permisos) mocks.py
  llm/              client.py (anthropic | openai | template)
  state/            store.py (memory | dynamodb)
tests/              pytest
infra/template.yaml SAM
docs/               SPEC.md ARCHITECTURE.md (diagrama) ADRs
```
