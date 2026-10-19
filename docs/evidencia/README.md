# Evidencia de pruebas — Onboarding Agent

Fecha de ejecución: 2026-10-19 · commit base `1241670` · fuente de verdad: [`docs/SPEC.md`](../SPEC.md)

## Resumen

| Suite | Herramienta | Resultado |
|---|---|---|
| E2E contrato HTTP (local) | Postman Collection v2.1 + newman 6 | **27/27 requests OK, 143/143 assertions OK, 0 fallos** (1 request solo-AWS saltada a propósito) |
| Unitarios + integración | pytest | **143 passed, 0 failed** |

## Archivos

| Archivo | Contenido |
|---|---|
| [`postman/onboarding-agent.postman_collection.json`](../../postman/onboarding-agent.postman_collection.json) | Colección (importable en Postman), 28 requests en 4 carpetas |
| [`postman/local.postman_environment.json`](../../postman/local.postman_environment.json) | `base_url=http://localhost:8099`, tokens vacíos |
| [`postman/aws.postman_environment.json`](../../postman/aws.postman_environment.json) | `base_url` de ejemplo, `token_channel`/`token_officer` vacíos (sin secretos) |
| `newman-local.html` | Reporte htmlextra navegable (por request y assertion) |
| `newman-local.json` | Reporte JSON completo de newman |
| `newman-local-junit.xml` | Reporte JUnit (consumible por CI) |

## Cobertura de la colección

| Carpeta | Requests | Qué valida |
|---|---|---|
| 01 Health | 1 | `GET /health` → 200 `{"status":"ok"}` (sin auth) |
| 02 Escenarios start | 10 | Tabla de `document_id` del SPEC: `1712345678` APPROVED · `0900000001` REJECTED + `proposals` "presencial" · `0900000002` ESCALATED en identity · `0900000003` ESCALATED en risk (severity high) · `0900000004` APPROVED_WITH_CONDITIONS + documentos de debida diligencia reforzada (EDD) · `0900000005` ESCALATED con exactamente 2 llamadas a `verify_identity` (reintento único) · producto inexistente REJECTED + productos alternativos · 422 por `document_id` inválido (x2) y body incompleto |
| 03 Estado conversacional | 13 | start ESCALATED → guarda `onboarding_id`/`escalation_id` en variables de colección → GET persistido → resolve **approve** reanuda desde risk hasta APPROVED → GET persistido → resolve repetido **409** → escalamiento inexistente **404** → onboarding inexistente **404**; flujo **reject** → REJECTED sin llegar a documentation; flujo **retry** → re-ejecuta identity (4 llamadas) y crea una nueva escalación OPEN; action inválida **422**; resolve con `token_channel` → **403** *(solo AWS)* |
| 04 Guardrails | 4 | Primera línea de `customer_message` según status ("Aprobada", "No aprobada", "En revisión", "Aprobada con condiciones"); auditoría con cédula enmascarada (`******0001`); propuesta al cliente solo del catálogo |

**Tests comunes (script a nivel de colección, se aplican a cada request):** tiempo de respuesta < 29000 ms (límite de API Gateway). En cada respuesta 200 de `/api/v1/onboarding/*` se valida además:

- los campos del contrato del SPEC y los enums de `status` y `current_step`;
- la forma de `escalations[]` y `audit[]`;
- que toda escalación tenga `proposal` (RF3);
- que `customer_message` empiece con `Estado de tu solicitud:`;
- que la auditoría no contenga la cédula completa (ni ninguna secuencia de 10 dígitos).

**Autenticación:** `start` y `get` usan `{{token_channel}}` (canal digital); `resolve` usa `{{token_officer}}` (oficial del grupo Cognito `compliance`); `/health` va sin auth. La request del 403 llama a `pm.execution.skipRequest()` cuando `base_url` es localhost, porque en local corre con `AUTH_MODE=none`.

## Cómo correrlo

### Local

```bash
# 1. API local sin auth ni LLM (plantilla determinista)
AUTH_MODE=none ALLOW_INSECURE_LOCAL=1 LLM_PROVIDER=none \
  uv run uvicorn onboarding.api:app --app-dir src --port 8099

# 2. En otra terminal
npx -y -p newman@6 -p newman-reporter-htmlextra@1 newman run postman/onboarding-agent.postman_collection.json \
  -e postman/local.postman_environment.json \
  -r cli,json,htmlextra,junit \
  --reporter-json-export docs/evidencia/newman-local.json \
  --reporter-htmlextra-export docs/evidencia/newman-local.html \
  --reporter-junit-export docs/evidencia/newman-local-junit.xml
```

### AWS

```bash
# Tokens de los usuarios Cognito de prueba. get-token.sh lo crea arch (aún no existe en 1241670);
# se asume que imprime solo el ID token por stdout.
export TOKEN_CHANNEL=$(infra/bootstrap/get-token.sh canal)
export TOKEN_OFFICER=$(infra/bootstrap/get-token.sh oficial)

npx -y newman@6 run postman/onboarding-agent.postman_collection.json \
  -e postman/aws.postman_environment.json \
  --env-var "base_url=https://<api-id>.execute-api.<region>.amazonaws.com" \
  --env-var "token_channel=$TOKEN_CHANNEL" --env-var "token_officer=$TOKEN_OFFICER" \
  -r cli,junit --reporter-junit-export docs/evidencia/newman-aws-junit.xml
```

> Pasa los tokens con `--env-var`, nunca editándolos en `aws.postman_environment.json`. El reporter JSON de newman guarda los headers enviados (incluido `Authorization`), así que **no publiques un `newman-aws.json`** sin quitar los tokens. El ejemplo usa solo `cli` y `junit`. En Postman Desktop, importa la colección y el entorno, y escribe los tokens en *Current value*.
>
> Contra AWS el estado persiste en DynamoDB y el LLM puede estar activo: las assertions dependen solo de la decisión determinista y de la línea de estado, no del texto que redacta el LLM.

## Unitarios e integración (pytest)

```text
$ uv run pytest -q
.......................................................................  [100%]
143 passed, 1 warning in 0.59s
```

El warning es un `DeprecationWarning` de asyncio en `mangum`; es de la librería, no del proyecto.

| Archivo | Tests | Cubre |
|---|---|---|
| `tests/test_api.py` | 28 | Contrato HTTP: escenarios, 422/404/409, GET, resolve approve/reject |
| `tests/test_orchestrator.py` | 11 | Reintento único, retry, propuestas, decisión determinista |
| `tests/test_tool_permissions.py` | 7 | Allowlist por agente → `ToolNotPermittedError` + auditoría |
| `tests/test_llm_fallback.py` | 33 | Fallback Claude → OpenAI → plantilla; guardrails de salida LLM; propuestas al cliente solo del catálogo |
| `tests/test_llm_budget.py` | 23 | Presupuesto LLM en ventana deslizante (reloj inyectable); configuración finita y > 0 |
| `tests/test_llm_pii.py` | 17 | RNF-09: prompts a proveedores LLM sin nombre completo ni cédula |
| `tests/test_auth.py` | 15 | Auth fail-closed y grupo `compliance` en `/resolve` |
| `tests/test_privacy.py` | 9 | Enmascarado de PII en auditoría y TTL |

## Revisión de secretos

Busqué en los reportes patrones de JWT (`eyJ…`), keys de Anthropic/OpenAI (`sk-…`), credenciales AWS (`AKIA…`) y nombres de variables de API keys: **no hay coincidencias**. Las menciones de `bearer` son solo la configuración de auth con las variables `{{token_channel}}`/`{{token_officer}}`; en local los tokens van vacíos. Los únicos números de 10 dígitos son las cédulas **ficticias** de los escenarios mock del SPEC, en los bodies de las requests.
