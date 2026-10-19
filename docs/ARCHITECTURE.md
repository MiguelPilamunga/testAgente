# Arquitectura — Agente Orquestador de Onboarding Digital

> Contrato funcional: [`SPEC.md`](SPEC.md) (fuente de verdad). Decisiones: [`adr/`](adr/).

## 1. Principios

1. **La decisión es determinista, el LLM solo redacta** ([ADR-0001](adr/0001-decision-determinista-llm-redacta.md)).
   El motor de políticas (`policies.py`) decide la aptitud; el LLM redacta el mensaje al cliente y enriquece
   propuestas. Sin keys el sistema funciona igual (plantillas).
2. **Mínimo privilegio por agente** ([ADR-0002](adr/0002-allowlist-tools-por-agente.md)). Cada sub-agente
   solo puede invocar las tools de su allowlist; el `ToolRegistry` lo hace cumplir y audita.
3. **Incertidumbre ⇒ escalar con propuesta, nunca adivinar.** Un resultado ambiguo o un fallo de servicio
   pausa el flujo (`ESCALATED`) con una propuesta concreta; un humano lo resuelve con `/resolve`.
4. **Estado explícito y persistido** entre pasos (`StateStore`: memoria local / DynamoDB), lo que permite
   reanudar tras un escalamiento y auditar todo el recorrido.
5. **Serverless en AWS** ([ADR-0003](adr/0003-serverless-aws.md)): API Gateway HTTP API → Lambda → DynamoDB.
6. **Autenticación JWT + rol de cumplimiento** ([ADR-0004](adr/0004-autenticacion.md)): Cognito + JWT
   authorizer en todas las rutas salvo `/health`; `/resolve` exige grupo `compliance`.
7. **Sin CI/CD** ([ADR-0005](adr/0005-sin-ci-cd.md)): despliegue manual `sam build && sam deploy --guided
   --profile ecopacific`, con el skill `verify` como gate local obligatorio.

## 2. Componentes

```mermaid
flowchart LR
    Client([Cliente / Canal digital]) -->|HTTP JSON| API["API FastAPI<br/>api.py"]
    API --> ORCH["Orquestador<br/>orchestrator.py<br/>(máquina de estados)"]
    ORCH <--> STORE[("StateStore<br/>memory | dynamodb")]
    ORCH --> POL["Motor de políticas<br/>policies.py<br/>(determinista)"]

    subgraph Agents["Sub-agentes (agents/)"]
        IA[IdentityAgent]
        RA[RiskAgent]
        DA[DocumentationAgent]
        MA[MitigationAgent]
        RSA[ResponseAgent]
    end
    ORCH --> IA & RA & DA & MA & RSA

    subgraph Tools["tools/"]
        REG{{"ToolRegistry<br/>allowlist por agente"}}
        M1["verify_identity"]
        M2["check_risk_lists"]
        M3["prepare_documentation"]
    end
    IA -->|call| REG
    RA -->|call| REG
    DA -->|call| REG
    MA -. sin tools .-> REG
    RSA -. sin tools .-> REG
    REG -->|permitido| M1 & M2 & M3
    REG -->|denegado: ToolNotPermittedError + audit| ORCH

    subgraph LLM["llm/client.py — LLM gateway"]
        GW{{"selector de proveedor"}}
        C1[Claude / Anthropic<br/>principal]
        C2[OpenAI<br/>fallback]
        C3[Plantilla determinista<br/>sin keys / error]
        GW --> C1
        GW -->|error/timeout| C2
        GW -->|sin keys / error| C3
    end
    MA --> GW
    RSA --> GW
```

| Componente | Responsabilidad | No hace |
|---|---|---|
| `api.py` | Validación (Pydantic: `document_id` 10 dígitos → 422), rutas, `handler = Mangum(app)` | Lógica de negocio |
| `orchestrator.py` | `build_registry()` (registra tools + allowlist), máquina de estados (`_run`), reintento (`TOOL_MAX_ATTEMPTS=2`), escalamientos/reanudación (`resolve`), decisión (`_decide`), persistencia | Llamar tools directamente |
| `policies.py` | Umbrales y reglas (`IDENTITY_MIN_CONFIDENCE=0.8`, `TOOL_MAX_ATTEMPTS`, `PRODUCTS`, `ENHANCED_DUE_DILIGENCE_DOCS`, catálogo `MITIGATIONS`) | I/O |
| `agents/*` | Identity/Risk/Documentation heredan de `Agent` y devuelven `StepOutcome(data, escalation, reject_reason, proposal)`; Mitigation (`propose`/`enrich`) y Response (`run`) solo usan el LLM | Decidir aptitud final |
| `tools/registry.py` | `register`/`grant`/`call(agent, tool, state, **kw)`; lanza `ToolNotPermittedError`, audita `tool_call`/`tool_result`/`tool_denied`; `ToolError` = fallo de servicio | — |
| `tools/mocks.py` | Servicios externos simulados, deterministas por `document_id` | — |
| `llm/client.py` | `build_llm()` → `FallbackLLM` (Claude → OpenAI → `None` ⇒ plantilla del agente); keys de entorno o de Secrets Manager (`LLM_SECRET_ARN`) | Decidir |
| `state/store.py` | `build_store()`: `InMemoryStore` o `DynamoDBStore` (`STATE_BACKEND`, `STATE_TABLE`); `get/save`, ítem `{onboarding_id, status, state(JSON), updated_at}` | — |
| `models.py` | `OnboardingState` (incl. `proposals`, `conversation` customer/bank/officer), `Escalation`, `Status` (+ `IN_PROGRESS` interno), `STEPS` | — |

## 3. Secuencia — `/start` con escalamiento y `/resolve`

Ejemplo `document_id=0900000002` (identidad ambigua, confianza 0.62 < 0.8).

```mermaid
sequenceDiagram
    autonumber
    actor C as Cliente
    participant API as API (FastAPI)
    participant O as Orquestador
    participant S as StateStore
    participant IA as IdentityAgent
    participant R as ToolRegistry
    participant T as Mocks
    participant MA as MitigationAgent
    participant RA as RiskAgent / DocumentationAgent
    participant RS as ResponseAgent
    participant L as LLM gateway
    actor Op as Operador (Cumplimiento)

    C->>API: POST /api/v1/onboarding/start {prospect_name, document_id, product}
    API->>O: start(request)
    O->>O: state.conversation += customer · audit started
    O->>IA: run(state)
    IA->>R: call("IdentityAgent", "verify_identity", state, document_id)
    R->>R: allowlist ✔ + audit tool_call
    R->>T: verify_identity("0900000002")
    T-->>IA: {verified: true, confidence: 0.62}
    IA-->>O: StepOutcome(escalation: 0.62 < IDENTITY_MIN_CONFIDENCE)
    O->>MA: enrich(escalation) — base MITIGATIONS["identity_ambiguous"]
    MA->>L: enriquecer propuesta
    L-->>MA: texto (o plantilla)
    O->>RS: run(state) — mensaje de revisión pendiente
    RS->>L: redactar (o plantilla)
    O->>S: save(status=ESCALATED, current_step=identity, escalations=[OPEN])
    O-->>API: estado
    API-->>C: 200 {status: ESCALATED, escalations:[{id, proposal, status: OPEN}]}

    Note over Op,API: Revisión humana (p.ej. videollamada de verificación)
    Op->>API: POST /{id}/resolve {escalation_id, action: "approve", notes}
    API->>O: resolve(id, ...)
    O->>S: get(id)
    O->>O: escalation RESOLVED · steps.identity.manual_override · conversation += officer
    O->>RA: risk → documentation (continúa desde el paso siguiente)
    RA->>R: check_risk_lists / prepare_documentation (allowlist ✔)
    R->>T: mocks
    O->>O: _decide (determinista, risk low ⇒ APPROVED)
    O->>RS: run(state) — mensaje final
    RS->>L: redactar
    O->>S: save(status=APPROVED, current_step=done)
    API-->>Op: 200 {status: APPROVED, required_documents, customer_message}
```

Variantes de `resolve`: `retry` vuelve a ejecutar el paso pausado (p.ej. tras caída del servicio en
`0900000005`); `reject` salta a `decision` y termina en `REJECTED` con la propuesta del escalamiento.
Errores: escalamiento inexistente → 404; ya resuelto → 409; onboarding inexistente → 404.

## 4. Máquina de estados

Pasos (`current_step`) y estados globales (`status`):

```mermaid
stateDiagram-v2
    [*] --> identity : POST /start
    identity --> risk : verificado y confianza ≥ 0.8
    identity --> decision : verified=false y confianza ≥ 0.8 (no apto + propuesta presencial)
    documentation --> decision : producto no ofertado (no apto + alternativas)
    identity --> PausedIdentity : confianza < 0.8 · error de servicio tras 1 reintento
    risk --> documentation : low / medium
    risk --> PausedRisk : high (match OFAC)
    documentation --> decision
    decision --> response
    response --> done
    done --> [*]

    state "ESCALATED (pausa)" as Esc {
        PausedIdentity
        PausedRisk
    }
    PausedIdentity --> risk : resolve approve
    PausedIdentity --> identity : resolve retry
    PausedRisk --> documentation : resolve approve
    PausedRisk --> risk : resolve retry
    Esc --> decision : resolve reject (status=REJECTED)
```

Estado final (`status`) que fija el paso `decision`:

| Condición (motor de políticas) | `status` |
|---|---|
| Identidad ok, riesgo `low`, producto válido | `APPROVED` |
| Riesgo `medium` (PEP) | `APPROVED_WITH_CONDITIONS` + documentos de debida diligencia reforzada |
| `verified=false` con confianza ≥ 0.8 · producto inexistente · `resolve reject` | `REJECTED` + propuesta |
| Confianza < 0.8 · riesgo `high` · servicio no disponible | `ESCALATED` (pausa en el paso) |

Producto inexistente: lo detecta `DocumentationAgent` sin invocar `prepare_documentation`; `REJECTED` con
propuesta de productos alternativos. Todo rechazo definitivo o aprobación con condiciones deja la solución
propuesta en `proposals[]` (RF3). Mientras corre, el estado interno es `IN_PROGRESS`.

## 5. Manejo de incertidumbre

| Fuente de incertidumbre | Detección | Mitigación |
|---|---|---|
| Identidad ambigua | `confidence < IDENTITY_MIN_CONFIDENCE (0.8)` | Escalamiento `severity` media con propuesta (verificación biométrica/videollamada); el humano decide |
| Identidad negativa con alta confianza | `verified=false`, conf ≥ 0.8 | No apto **con propuesta** (verificación presencial en agencia) — RF3 |
| Riesgo alto | `risk_level=high` / match OFAC | Nunca se aprueba automáticamente → escalamiento a Cumplimiento |
| Riesgo medio | `risk_level=medium` / PEP | Apto con condiciones + documentos extra |
| Servicio externo caído | `ToolError` en la tool | `TOOL_MAX_ATTEMPTS=2` (1 reintento, auditado `tool_error`); si persiste → escalamiento "servicio no disponible" con `retry` posible |
| LLM no disponible / lento / alucinación | error, timeout (`LLM_TIMEOUT`=6 s, sin reintentos del SDK), presupuesto agotado (`LLM_BUDGET`=15 s por ventana de 29 s) o sin keys | Fallback Claude → OpenAI → plantilla; peor caso ≈ presupuesto + 1 llamada < 29 s. El LLM **no** puede cambiar `status` ni `decision`: solo produce texto; la propuesta base sale del catálogo determinista |
| Entrada inválida | Pydantic | 422 antes de tocar el orquestador |

Todo evento (llamada a tool, denegación, reintento, escalamiento, resolución, decisión) queda en
`audit[]` con `ts`, `agent`, `event`, `detail`; el diálogo cliente/banco/oficial queda en `conversation[]`.
Por LOPDP ([ADR-0006](adr/0006-privacidad-y-retencion.md)) `detail` enmascara cédula (`******5678`) y
nombres (iniciales); el expediente en DynamoDB expira por TTL (`expires_at`, `STATE_TTL_DAYS`=90).

## 6. Permisos de tools

```mermaid
flowchart LR
    IA[IdentityAgent] --> V[verify_identity]
    RA[RiskAgent] --> K[check_risk_lists]
    DA[DocumentationAgent] --> P[prepare_documentation]
    RS[ResponseAgent] -.-> N1((ninguna))
    MA[MitigationAgent] -.-> N2((ninguna))
```

- El allowlist se define en **un solo lugar**: `orchestrator.build_registry()` hace `register(tool)` y
  `grant(agent, tool)`; el `ToolRegistry` guarda `{agent: {tools}}` (deny by default).
- Los agentes no importan los mocks: heredan `Agent.tool()`, que delega en
  `registry.call(self.name, tool, state, **kwargs)`.
- Llamada fuera del allowlist → `ToolNotPermittedError` + evento `tool_denied` en auditoría (defensa ante
  prompt injection o bug: un agente con LLM nunca obtiene capacidades nuevas).
- Los agentes con LLM (Response, Mitigation) **no reciben el registry**: su salida es texto, nunca acciones.
- En AWS el mismo principio se aplica a nivel IAM: la Lambda solo puede CRUD sobre su tabla y
  `GetSecretValue` sobre un único secreto.

## 7. Despliegue AWS

```mermaid
flowchart LR
    U([Canal digital / Oficial]) -->|login| COG[["Cognito User Pool<br/>grupo compliance"]]
    COG -->|JWT| U
    U -->|"HTTPS + Bearer JWT"| APIGW["API Gateway HTTP API ($default)<br/>JWT authorizer · throttling<br/>rutas explícitas"]
    APIGW -.->|valida issuer/audience| COG
    APIGW -->|"start · get · resolve · health"| L["Lambda Python 3.12 arm64<br/>FastAPI + Mangum<br/>onboarding.api.handler"]
    L -->|CRUD PK onboarding_id| DDB[("DynamoDB<br/>onboarding-state-{stage}<br/>on-demand · PITR · SSE")]
    L -->|GetSecretValue| SM[["Secrets Manager<br/>LlmSecretArn<br/>ANTHROPIC/OPENAI keys"]]
    L -->|HTTPS| EXT["Anthropic API / OpenAI API"]
    L --> CW["CloudWatch<br/>Logs · X-Ray · alarma Errors"]
    APIGW --> CW
```

IaC: [`infra/template.yaml`](../infra/template.yaml) (SAM). Variables de entorno de la Lambda:
`AUTH_MODE=apigw`, `STATE_BACKEND=dynamodb`, `STATE_TABLE`, `LLM_PROVIDER`, `LLM_SECRET_ARN`, `ANTHROPIC_MODEL`, `OPENAI_MODEL`.
Si `LlmSecretArn` está vacío, `LLM_PROVIDER=none` y la política IAM del secreto no se crea.

Escalabilidad/coste: todo es pago por uso; el estado en DynamoDB hace a la Lambda stateless, por lo que
`/resolve` puede caer en cualquier instancia.

## 8. Autenticación y autorización

| Ruta | API Gateway | App (`AUTH_MODE=apigw`) |
|---|---|---|
| `GET /health` | pública (`Authorizer: NONE`) | — |
| `POST /api/v1/onboarding/start` | JWT válido (Cognito) | — |
| `GET /api/v1/onboarding/{id}` | JWT válido | — |
| `POST /api/v1/onboarding/{id}/resolve` | JWT válido | `cognito:groups` contiene `compliance`, si no 403 |

API Gateway rechaza (401) tokens ausentes, expirados o de otra audiencia **antes** de invocar la Lambda;
rutas no declaradas devuelven 404 sin coste de cómputo. En local no hay `AUTH_MODE` ⇒ sin autenticación.
