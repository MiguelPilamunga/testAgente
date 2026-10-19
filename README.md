# Onboarding Agent — Orquestador multi-agente de onboarding digital

## Problema

El banco necesita un **orquestador** que coordine sub-agentes especializados en el onboarding digital
(identidad, listas de riesgo, documentación según políticas y respuesta al cliente), que:

- controle **qué tools puede usar cada agente** (allowlist + auditoría),
- **mantenga estado** entre pasos (y lo reanude tras un escalamiento humano),
- **mitigue la incertidumbre**: si una verificación falla o es ambigua, **propone una solución** en vez de solo rechazar.

La **decisión de aptitud es determinista** (motor de políticas auditable). El LLM — Claude principal, OpenAI
como fallback, plantilla si no hay keys — solo **redacta** la respuesta al cliente y enriquece propuestas.

- Contrato funcional: [`docs/SPEC.md`](docs/SPEC.md)
- Arquitectura y diagramas: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- Decisiones: [`docs/adr/`](docs/adr/) (0001 decisión determinista · 0002 allowlist · 0003 serverless · 0004 autenticación · 0005 sin CI/CD)

## Arquitectura (resumen)

```
API (FastAPI) → Orquestador (máquina de estados) → Identity / Risk / Documentation / Mitigation / Response
                     │                                   │
                     ├─ Motor de políticas (determinista) └─ ToolRegistry (allowlist) → mocks
                     ├─ StateStore (memory | DynamoDB)
                     └─ LLM gateway (Claude → OpenAI → plantilla)
```

Flujo: `identity → risk → documentation → decision → response → done`. Un escalamiento pausa el flujo
(`ESCALATED`); `POST /resolve` con `approve | retry | reject` lo reanuda.

## Correr en local

Requisitos: Python 3.12 y [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env          # opcional: sin keys funciona en modo plantilla
uv run uvicorn onboarding.api:app --app-dir src --reload
uv run pytest                 # tests
```

## Ejemplos (un escenario por `document_id`)

```bash
API=http://localhost:8000
start() { curl -s -X POST $API/api/v1/onboarding/start -H 'Content-Type: application/json' \
  -d "{\"prospect_name\":\"Ana Pérez\",\"document_id\":\"$1\",\"product\":\"${2:-cuenta_ahorros}\"}"; }

curl -s $API/health

start 1712345678                    # APPROVED
start 0900000001                    # REJECTED + propuesta: verificación presencial en agencia
start 0900000002                    # ESCALATED: identidad ambigua (confianza 0.62 < 0.8)
start 0900000003                    # ESCALATED: riesgo alto (match OFAC) → Cumplimiento
start 0900000004 tarjeta_credito    # APPROVED_WITH_CONDITIONS: PEP → debida diligencia reforzada
start 0900000005                    # ESCALATED: servicio de identidad no disponible (tras 1 reintento)
start 1712345678 hipoteca           # REJECTED + propuesta de productos alternativos
start 123                           # 422: document_id debe tener 10 dígitos
```

Consultar y resolver un escalamiento (requiere `jq`):

```bash
R=$(start 0900000002)
ID=$(echo "$R" | jq -r .onboarding_id)
ESC=$(echo "$R" | jq -r '.escalations[0].id')

curl -s $API/api/v1/onboarding/$ID | jq '{status, current_step, escalations}'

# approve → continúa desde el siguiente paso | retry → re-ejecuta el paso | reject → REJECTED
curl -s -X POST $API/api/v1/onboarding/$ID/resolve -H 'Content-Type: application/json' \
  -d "{\"escalation_id\":\"$ESC\",\"action\":\"approve\",\"notes\":\"Identidad confirmada por videollamada\"}" \
  | jq '{status, current_step, required_documents, customer_message}'
```

## Desplegar en AWS (SAM)

API Gateway HTTP API (JWT authorizer de Cognito) → Lambda Python 3.12 (FastAPI + Mangum) → DynamoDB;
keys en Secrets Manager; logs, trazas y alarma en CloudWatch. Plantilla: [`infra/template.yaml`](infra/template.yaml).

```bash
# 1) (opcional) crear el secreto con las keys LLM — nunca en el repo
aws secretsmanager create-secret --name onboarding/llm \
  --secret-string '{"ANTHROPIC_API_KEY":"...","OPENAI_API_KEY":"..."}'

# 2) gate local obligatorio: skill `verify` en PASS (en Claude Code: "verifica")
# 3) validar, construir y desplegar (perfil AWS ecopacific)
sam validate --lint -t infra/template.yaml
sam build -t infra/template.yaml && sam deploy --guided --profile ecopacific
#    en --guided: stack onboarding-agent, Stage=dev, LlmSecretArn=<ARN del paso 1 o vacío>,
#    capabilities CAPABILITY_IAM; guarda la config en samconfig.toml (ignorado por git)
```

**Sin CI/CD** ([ADR-0005](docs/adr/0005-sin-ci-cd.md)): no hay GitHub Actions ni pipelines; el despliegue es
manual y el skill `verify` es el gate obligatorio antes de integrar o desplegar. El perfil `personal` tiene
credenciales inválidas (pendiente); usar `ecopacific`.

Sin `LlmSecretArn` el stack se despliega en modo determinista (`LLM_PROVIDER=none`).

### Autenticación en AWS

Todas las rutas salvo `/health` exigen un JWT de Cognito; `/resolve` además exige el grupo `compliance`
([ADR-0004](docs/adr/0004-autenticacion.md)). En local no hay autenticación.

```bash
POOL=<UserPoolId>; CLIENT=<UserPoolClientId>      # outputs del stack
aws cognito-idp admin-create-user --user-pool-id $POOL --username oficial1 --message-action SUPPRESS
aws cognito-idp admin-set-user-password --user-pool-id $POOL --username oficial1 --password '<Password-Fuerte-1!>' --permanent
aws cognito-idp admin-add-user-to-group --user-pool-id $POOL --username oficial1 --group-name compliance
TOKEN=$(aws cognito-idp initiate-auth --client-id $CLIENT --auth-flow USER_PASSWORD_AUTH \
  --auth-parameters USERNAME=oficial1,PASSWORD='<Password-Fuerte-1!>' --query AuthenticationResult.IdToken --output text)

API=<ApiUrl>
curl -s -X POST $API/api/v1/onboarding/start -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"prospect_name":"Ana Pérez","document_id":"1712345678","product":"cuenta_ahorros"}'
```

## Sesiones paralelas de Claude Code

El proyecto se construyó con varias sesiones de Claude Code en paralelo (BMAD, entrega incremental),
cada una con un prompt y un alcance de archivos acotado en `scripts/prompts/<nombre>.md`:

```bash
scripts/launch-sessions.sh            # lanza todas (una pestaña de iTerm por sesión)
scripts/launch-sessions.sh arch qa    # solo algunas
MODEL=sonnet scripts/launch-sessions.sh
```

Cada sesión deja su entrega en `scripts/status/<nombre>.done` (archivos, cómo verificar, pendientes).

## Seguridad de keys

- `.env` está en `.gitignore`; solo se versiona `.env.example` sin valores.
- Sin keys el sistema es plenamente funcional (plantillas): no hay dependencia dura del LLM.
- En AWS las keys viven en **Secrets Manager**; la Lambda recibe solo el ARN (`LLM_SECRET_ARN`) y su rol IAM
  permite `secretsmanager:GetSecretValue` únicamente sobre ese secreto. Nada de keys en variables de
  entorno, plantillas ni logs.
- La API exige JWT de Cognito (salvo `/health`) y solo el grupo `compliance` puede resolver escalamientos.
- El rol de la Lambda solo tiene CRUD sobre su tabla DynamoDB (mínimo privilegio, igual que el allowlist de tools).
