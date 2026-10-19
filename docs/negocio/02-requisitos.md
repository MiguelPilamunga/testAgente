# 02 — Requisitos (negocio, funcionales, no funcionales y reglas de política)

> PRD (BMAD `bmad-prd`, modo autónomo/fast path). Cada requisito traza a un fragmento del enunciado (E-xx) o a un supuesto (S-xx, ver [04](04-supuestos-y-preguntas.md)).
> Estado: ✅ implementado · 🟡 parcial · ⬜ pendiente (según el código actual en `src/onboarding/`).

## Fragmentos del enunciado (trazabilidad)

| ID | Texto del enunciado |
|---|---|
| E-01 | "agente orquestador que coordine múltiples agentes especializados durante el onboarding digital" |
| E-02 | "Un agente verifica identidad, otro consulta listas de riesgo, otro prepara la documentación en base a las políticas, otro genera la respuesta al cliente" |
| E-03 | "controlar qué herramientas puede usar cada agente" |
| E-04 | "manejar el estado entre pasos" |
| E-05 | "mitigar si hay incertidumbre" |
| E-06 | RF "recibir solicitud de onboarding con datos del prospecto" |
| E-07 | RF "determinar bajo las políticas si el cliente es apto o no" |
| E-08 | RF "si alguna verificación agéntica falla o es ambigua, proponer una solución" |
| E-09 | RT `POST /api/v1/onboarding/start {prospect_name, document_id, product}` |
| E-10 | RT `verify_identity(document_id) → {verified, confidence}`; confianza < 0.8 escala |
| E-11 | RT `check_risk_lists(name, document_id) → {risk_level, matches}`; `high` escala |
| E-12 | RT `prepare_documentation(product, client_data) → documentos` |
| E-13 | Entregas: diagrama, código (orquestador, sub-agentes, estado conversacional), repo git |

---

## Requisitos de negocio (RN)

| ID | Requisito | Traza |
|---|---|---|
| RN-01 | El Banco debe poder vincular clientes por canal digital cumpliendo KYC/AML antes de activar un producto. | E-01, E-07 |
| RN-02 | Ninguna aprobación puede contradecir las políticas del Banco; las reglas deben ser explícitas, versionables y auditables. | E-07 |
| RN-03 | Los casos con incertidumbre (identidad ambigua, riesgo alto, servicio caído) deben pasar a un humano de Cumplimiento, no resolverse solos. | E-05, E-10, E-11 |
| RN-04 | Todo resultado negativo o incierto debe ofrecer al prospecto una vía de solución (no rechazos secos). | E-08 |
| RN-05 | Cada agente opera con el mínimo privilegio: solo las herramientas de su especialidad. | E-03 |
| RN-06 | La decisión y la evidencia deben conservarse para supervisión (SB/UAFE/auditoría interna). | E-04, S-03 |
| RN-07 | El tratamiento de datos personales cumple la LOPDP (finalidad, minimización, seguridad, intervención humana). | S-04 |

## Requisitos funcionales (RF)

### RF-01 Recibir solicitud de onboarding ✅ — Traza E-06, E-09
- **Given** un canal autenticado, **When** envía `POST /api/v1/onboarding/start` con `prospect_name` (3–120 car.), `document_id` y `product`, **Then** se crea un `onboarding_id` (UUID) y la respuesta incluye estado, pasos, auditoría y mensaje al cliente.
- **Given** `document_id` que no tiene exactamente 10 dígitos numéricos, **When** se envía, **Then** responde **422** y no se crea estado.

### RF-02 Verificar identidad ✅ — Traza E-02, E-10
- **Given** una solicitud válida, **When** el IdentityAgent invoca `verify_identity(document_id)`, **Then** el resultado `{verified, confidence}` se guarda en `steps.identity` y en auditoría (`tool_call`, `tool_result`).

### RF-03 Consultar listas de riesgo ✅ — Traza E-02, E-11
- **Given** identidad superada, **When** el RiskAgent invoca `check_risk_lists(name, document_id)`, **Then** se registra `risk_level` y `matches` en `steps.risk`.

### RF-04 Preparar documentación según políticas ✅ — Traza E-02, E-12
- **Given** un producto ofertado, **When** el DocumentationAgent invoca `prepare_documentation(product, client_data)`, **Then** `required_documents` contiene los documentos del producto y `policy_refs` las políticas aplicadas.
- **Given** riesgo `medium`, **Then** se añaden los documentos de debida diligencia reforzada.

### RF-05 Determinar aptitud bajo políticas ✅ — Traza E-07
- **Given** todos los pasos completados sin escalamiento abierto, **When** el orquestador ejecuta `decision`, **Then** `status` ∈ {`APPROVED`, `APPROVED_WITH_CONDITIONS`, `REJECTED`} y `decision.reasons` explica el porqué. La decisión la toma el motor de políticas, **nunca el LLM**.

### RF-06 Proponer solución ante falla o ambigüedad ✅ — Traza E-05, E-08
- **Given** una verificación fallida, ambigua o un servicio caído, **When** el orquestador lo detecta, **Then** se agrega una propuesta del catálogo de mitigaciones (`policies.MITIGATIONS`), opcionalmente enriquecida por LLM, en `escalations[].proposal` o `proposals[]`.

### RF-07 Escalar a oficial de cumplimiento ✅ — Traza E-05, E-10, E-11
- **Given** confianza < 0.8, riesgo `high` o servicio no disponible tras reintento, **When** ocurre, **Then** `status=ESCALATED`, `current_step` = paso pausado, se crea `escalations[]` con `status=OPEN`, severidad y propuesta, y el cliente recibe "En revisión".

### RF-08 Resolver escalamiento y reanudar ✅ — Traza E-04, E-05
- **Given** un escalamiento `OPEN`, **When** un oficial del grupo `compliance` envía `POST /{id}/resolve` con `approve`, **Then** el flujo continúa desde el paso siguiente y la decisión registra "Aprobación manual en: <paso>".
- **When** `reject` → `REJECTED` con propuesta. **When** `retry` → se re-ejecuta el paso; si vuelve a fallar se abre un escalamiento nuevo y el anterior queda `RESOLVED`.
- **Given** un escalamiento ya resuelto → **409**; inexistente → **404**; usuario sin grupo `compliance` → **403**.

### RF-09 Consultar estado conversacional ✅ — Traza E-04, E-13
- **Given** un `onboarding_id` existente, **When** `GET /api/v1/onboarding/{id}`, **Then** retorna estado completo (pasos, escalamientos, conversación cliente/banco/oficial, auditoría). Inexistente → **404**.

### RF-10 Generar respuesta al cliente ✅ — Traza E-02
- **Given** cualquier estado final o escalado, **When** el ResponseAgent redacta, **Then** el mensaje inicia con una línea de estado determinista, no menciona listas de sanciones ni detalles internos de riesgo, y si el texto del LLM contradice la decisión se usa la plantilla.

### RF-11 Producto no ofertado ✅ — Traza E-07, E-08
- **Given** `product` fuera del catálogo, **Then** `REJECTED` con propuesta de productos disponibles.

### RF-12 Bandeja de escalamientos pendientes ⬜ — Traza E-05, S-08
- **Given** un oficial autenticado, **When** consulta escalamientos `OPEN`, **Then** obtiene la lista ordenada por severidad y antigüedad. *(No existe endpoint; hoy el oficial debe conocer el `onboarding_id`.)*

## Requisitos no funcionales (RNF)

| ID | Atributo | Requisito | Criterio de aceptación (Given/When/Then) | Estado |
|---|---|---|---|---|
| RNF-01 | **Auditabilidad** | Todo evento relevante (inicio, tool_call/result/denied/error, escalamiento, resolución con `sub` del oficial, decisión) queda en `audit[]` con timestamp UTC. | Given un caso cualquiera, When se consulta, Then puede reconstruirse paso a paso quién (agente/oficial) hizo qué y con qué resultado. | ✅ |
| RNF-02 | **Explicabilidad** | Toda decisión lleva `decision.reasons` legibles y referencias de política (`policy_refs`). | Given un REJECTED o APPROVED_WITH_CONDITIONS, Then `reasons` y `proposals` no están vacíos. | ✅ |
| RNF-03 | **Determinismo** | Misma entrada + mismas respuestas de tools ⇒ misma decisión, con o sin LLM. | Given LLM deshabilitado (plantilla), Then el `status` es idéntico al obtenido con LLM. | ✅ |
| RNF-04 | **Seguridad — mínimo privilegio** | Cada agente solo usa su tool; intento fuera del allowlist ⇒ `ToolNotPermittedError` + `tool_denied`. | Given RiskAgent intenta `verify_identity`, Then se bloquea y se audita. | ✅ |
| RNF-05 | **Seguridad — autenticación/autorización** | JWT (Cognito) en todas las rutas salvo `/health`; `/resolve` exige grupo `compliance`; fail-closed. | Given token sin grupo, When `/resolve`, Then 403. | ✅ (pendiente commit) |
| RNF-06 | **Latencia** | p95 `start` ≤ 3 s con mocks; timeout Lambda 29 s; LLM con fallback rápido a plantilla. | Given carga nominal, Then p95 cumple meta. | 🟡 sin medición |
| RNF-07 | **Disponibilidad / resiliencia** | Reintento 1 vez ante error de servicio; luego escalamiento; caída de LLM no bloquea. | Given `0900000005`, Then ESCALATED con propuesta `retry`. | ✅ |
| RNF-08 | **Protección de datos (LOPDP) — seguridad** | Cifrado en reposo (DynamoDB SSE) y en tránsito (HTTPS); secretos en Secrets Manager. | — | ✅ |
| RNF-09 | **LOPDP — minimización** | La auditoría y los prompts al LLM no deben contener cédula completa ni datos no necesarios (enmascarar `document_id`, nombre solo de pila al LLM). | Given un caso, Then `audit[].detail` muestra cédula enmascarada. | 🟡 (auditoría guarda args completos) |
| RNF-10 | **LOPDP — intervención humana** | Decisiones adversas automatizadas deben ser revisables por un humano a solicitud del titular. | Given REJECTED automático, Then existe vía de revisión (propuesta + escalamiento manual). | 🟡 |
| RNF-11 | **LOPDP — retención** | Expediente conservado el plazo regulatorio y luego eliminado/anonimizado. | Given caso cerrado, Then tiene fecha de expiración/retención definida. | ⬜ (sin TTL) |
| RNF-12 | **Operación sin CI/CD** | Despliegue manual `sam deploy` desde local solo tras pasar `verify` (pytest + smoke). | Given un cambio, When se integra, Then hay evidencia de `verify` en verde. | ✅ proceso |
| RNF-13 | **Idempotencia** | Reintentos del canal no duplican expedientes. | Given dos `start` idénticos en ventana corta, Then se devuelve el mismo `onboarding_id`. | ⬜ |
| RNF-14 | **Observabilidad** | Métricas de O1–O6 (tasa auto-resolución, escalamientos, latencia, contradicciones LLM). | — | 🟡 logs/auditoría, sin métricas |

## Reglas de política (fuente: `src/onboarding/policies.py`)

| ID | Regla | Resultado | Escenario mock | Traza |
|---|---|---|---|---|
| POL-01 | `verified=true` y `confidence ≥ 0.8` | Identidad OK, continúa | `1712345678` (0.97) | E-10 |
| POL-02 | `confidence < 0.8` (`IDENTITY_MIN_CONFIDENCE`) | **ESCALATED** (identidad ambigua) + propuesta re-validación biométrica / revisión manual | `0900000002` (0.62) | E-10 |
| POL-03 | `verified=false` con `confidence ≥ 0.8` | **REJECTED** + propuesta verificación presencial en agencia | `0900000001` | E-08, S-05 |
| POL-04 | `risk_level=low` | Apto sin condiciones → **APPROVED** | default | E-11 |
| POL-05 | `risk_level=medium` (p. ej. PEP) | **APPROVED_WITH_CONDITIONS** + documentos de debida diligencia reforzada + monitoreo intensificado | `0900000004` | E-11, S-06 |
| POL-06 | `risk_level=high` (p. ej. OFAC) | **ESCALATED** a Cumplimiento; nunca auto-aprobación | `0900000003` | E-11 |
| POL-07 | Error de servicio en tool | Reintento 1 vez (`TOOL_MAX_ATTEMPTS=2`) → **ESCALATED** `tool_unavailable` | `0900000005` | E-05 |
| POL-08 | Producto fuera de catálogo (`cuenta_ahorros`, `cuenta_corriente`, `tarjeta_credito`) | **REJECTED** + productos alternativos | — | E-07, E-08 |
| POL-09 | Aprobación manual de un escalamiento | Continúa; condiciones dependen solo del riesgo | — | S-07 |

**Criterios de aceptación de política (muestra):**
- **Given** confianza 0.79, **When** se evalúa identidad, **Then** ESCALATED (el umbral es inclusivo en 0.8: 0.80 pasa).
- **Given** riesgo `high`, **When** un oficial aprueba, **Then** el estado final es `APPROVED_WITH_CONDITIONS` (riesgo ≠ low) y la auditoría registra el `sub` del oficial.
- **Given** cualquier combinación, **Then** jamás se produce `APPROVED` automático con identidad < 0.8 o riesgo `high` (meta O3).
