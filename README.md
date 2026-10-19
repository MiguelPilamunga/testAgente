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

API Gateway HTTP API (JWT authorizer de Cognito) → Lambda Python 3.12 (FastAPI + Mangum) → DynamoDB (TTL);
keys LLM en Secrets Manager; logs, X-Ray, dashboard, 9 alarmas y tópico SNS en CloudWatch.
Plantilla: [`infra/template.yaml`](infra/template.yaml).

### Despliegue actual (dev)

| Output | Valor |
|---|---|
| Stack | `onboarding-agent-dev` · cuenta `774305616818` · `us-east-1` |
| `ApiUrl` | https://o8pjot00p9.execute-api.us-east-1.amazonaws.com |
| `UserPoolId` | `us-east-1_IwM4C49Lr` |
| `UserPoolClientId` | `2s24fcilu3lekvoip4tq4ue7cf` |
| `StateTableName` | `onboarding-agent-dev-state` |
| `FunctionName` | `onboarding-agent-dev-orchestrator` |
| `AlarmTopicArn` | `arn:aws:sns:us-east-1:774305616818:onboarding-agent-dev-alarms` |
| Dashboard | [`onboarding-agent-dev-ops`](https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards:name=onboarding-agent-dev-ops) |
| Secreto LLM | `onboarding-agent/llm-keys` (hoy con valores vacíos ⇒ modo plantilla) |

Las keys LLM se cargan sin tocar el repo:
`aws secretsmanager put-secret-value --secret-id onboarding-agent/llm-keys --secret-string file://<json-local>`.

### Cómo desplegar (manual, sin CI/CD, nunca con root)

```bash
# 0) Una sola vez por stage, con credenciales de administrador: boundary, rol de la Lambda (pre-creado),
#    usuario onboarding-deployer y perfil local. El deployer no puede crear roles.
ADMIN_PROFILE=default STAGE=dev infra/bootstrap/create-deployer.sh   # ADR-0007

# 1) Gate local obligatorio: skill `verify` en PASS (en Claude Code: "verifica")
# 2) Validar, construir y desplegar con el perfil acotado
sam validate --lint -t infra/template.yaml
sam build -t infra/template.yaml
sam deploy --template-file .aws-sam/build/template.yaml --profile onboarding-deployer --region us-east-1 \
  --stack-name onboarding-agent-dev --resolve-s3 --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --no-confirm-changeset --tags project=onboarding-agent \
  --parameter-overrides Stage=dev LlmSecretArn=<ARN de onboarding-agent/llm-keys> \
    FunctionRoleArn=arn:aws:iam::774305616818:role/onboarding-agent-dev-function-role [AlarmEmail=<email>]
```

- **Sin CI/CD** ([ADR-0005](docs/adr/0005-sin-ci-cd.md)): despliegue manual; `verify` es el gate obligatorio.
- **IAM** ([ADR-0007](docs/adr/0007-iam-deployer-boundary.md)): `onboarding-deployer` solo opera recursos
  `onboarding-agent-*` o con tag `project=onboarding-agent`. El rol de la Lambda lo pre-crea el bootstrap (`onboarding-agent-dev-function-role`, trust solo Lambda, boundary).
  El tag `--tags project=onboarding-agent` es obligatorio.
- Un create fallido deja la tabla retenida (`DeletionPolicy: Retain`): bórrala antes de reintentar.

### Autenticación y usuarios de prueba

Todas las rutas salvo `/health` exigen un JWT de Cognito; `/resolve` exige además el grupo `compliance`
([ADR-0004](docs/adr/0004-autenticacion.md)). En local no hay autenticación.

| Perfil | Usuario | Grupo | `start`/`get` | `resolve` |
|---|---|---|---|---|
| Canal digital | `canal-digital@test.onboarding` | — | 200 | 403 |
| Oficial de cumplimiento | `oficial-cumplimiento@test.onboarding` | `compliance` | 200 | 200 |

```bash
infra/bootstrap/seed-test-users.sh                 # idempotente; passwords solo en Secrets Manager onboarding-agent/test-users
export AUTH_TOKEN=$(infra/bootstrap/get-token.sh oficial)   # o: canal  (imprime solo el IdToken)

API=https://o8pjot00p9.execute-api.us-east-1.amazonaws.com
curl -s -X POST $API/api/v1/onboarding/start -H "Authorization: Bearer $AUTH_TOKEN" -H 'Content-Type: application/json' \
  -d '{"prospect_name":"Ana Pérez","document_id":"1712345678","product":"cuenta_ahorros"}'

AUTH_TOKEN=$AUTH_TOKEN .claude/skills/verify/scripts/smoke.sh $API   # smoke remoto: 17/17
```

Postman: `postman/aws.postman_environment.json` ya trae `base_url`. Los tokens (`token_channel`, `token_officer`)
se pegan localmente desde `get-token.sh` y nunca se commitean.

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
