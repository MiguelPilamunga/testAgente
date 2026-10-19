# ADR-0004 — Autenticación JWT (Cognito) en API Gateway y rol `compliance` para /resolve

- **Estado:** Aceptado · 2026-10-19

## Contexto
Revisión de seguridad (HIGH): la HTTP API no tenía autenticación y `POST /resolve` — una acción de oficial
de cumplimiento que puede aprobar a un prospecto escalado por OFAC o identidad ambigua — quedaba pública.
Además `/{proxy+}` exponía cualquier ruta que la app llegara a definir.

## Decisión
- **Cognito User Pool** (alta solo por administrador, password fuerte) + **app client** del canal digital
  (sin secreto, SRP/password, tokens de 1 h) + **grupo `compliance`**.
- **JWT authorizer** de API Gateway como `DefaultAuthorizer` (issuer = User Pool, audience = client).
- **Rutas explícitas** en lugar de `/{proxy+}`:
  `GET /health` (`Authorizer: NONE`), `POST /api/v1/onboarding/start`, `GET /api/v1/onboarding/{id}`,
  `POST /api/v1/onboarding/{id}/resolve` — las tres últimas exigen JWT válido.
- **Autorización por rol en la app** (`AUTH_MODE=apigw`): API Gateway valida firma/expiración/audiencia;
  la app lee los claims del `requestContext.authorizer.jwt` y exige `cognito:groups ∋ compliance` en
  `/resolve` (403 si no). En local `AUTH_MODE` no se define ⇒ sin auth (desarrollo/tests).

## Alternativas descartadas
- API keys / usage plans: no identifican al oficial (auditoría) y HTTP API no las soporta.
- Lambda authorizer propio: más código y latencia para lo que Cognito + JWT authorizer ya resuelve.
- Scopes OAuth por ruta: válido, pero los grupos de Cognito modelan mejor "rol de oficial" para usuarios humanos.

## Consecuencias
- ✅ Superficie pública mínima (solo `/health`); rutas desconocidas → 404 en API Gateway sin invocar Lambda.
- ✅ El `sub`/`username` del token puede registrarse en `audit[]` como autor de la resolución.
- ⚠️ La verificación del grupo depende de la app → requiere test (pendiente para la sesión de `api.py`).
- ⚠️ Nuevas rutas deben declararse en la plantilla (fricción intencional, igual que el allowlist de tools).

## Perfiles de prueba (deploy dev)
`infra/bootstrap/seed-test-users.sh` crea dos usuarios en el User Pool del stack. Es idempotente y las passwords
aleatorias solo se guardan en Secrets Manager `onboarding-agent/test-users`:

| Usuario | Grupo | Representa | Esperado |
|---|---|---|---|
| `canal-digital@test.onboarding` | — | Canal digital del banco | `start`/`get` 200, `resolve` **403** |
| `oficial-cumplimiento@test.onboarding` | `compliance` | Oficial de cumplimiento | `start`/`get`/`resolve` 200 |

`infra/bootstrap/get-token.sh canal|oficial` imprime solo el **IdToken**, que lleva `cognito:groups` y
`aud = ClientId`, lo que valida el JWT authorizer. La Lambda no puede leer `test-users`: su boundary solo permite
`llm-keys` (ADR-0007).
