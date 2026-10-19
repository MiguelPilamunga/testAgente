# 01 — Problema y contexto de negocio

> Product brief (BMAD, modo autónomo). Fuente de verdad: enunciado de la evaluación. Contrato técnico: [`docs/SPEC.md`](../SPEC.md).
> Las referencias regulatorias son de contexto y deben ser validadas por el área de Cumplimiento/Legal del Banco.

## 1. Contexto

El Banco quiere abrir productos (cuenta de ahorros, cuenta corriente, tarjeta de crédito) a **nuevos clientes por canal digital**, sin que el prospecto vaya a una agencia. Abrir una relación comercial obliga a cumplir **Conozca a su Cliente (KYC)** y **prevención de lavado de activos y financiamiento de delitos (PLA/FT, AML)** antes de activar cualquier producto.

### Marco regulatorio ecuatoriano relevante (contexto)

| Ente / norma | Qué implica para el onboarding |
|---|---|
| **Superintendencia de Bancos (SB)** — normativa de prevención de lavado de activos para entidades del sistema financiero (Codificación de normas de la SB / Junta de Política y Regulación Financiera) | Política "Conozca a su Cliente": identificar y verificar al cliente, perfil de riesgo, **debida diligencia** simplificada/estándar/**reforzada** según riesgo, conservación de expedientes, oficial de cumplimiento responsable. |
| **UAFE** (Unidad de Análisis Financiero y Económico) — Ley Orgánica de Prevención, Detección y Erradicación del Delito de Lavado de Activos y del Financiamiento de Delitos | Reportes a la UAFE (operaciones inusuales/sospechosas, RESU), consulta de listas; obligación de no vincular a personas en listas de sanciones sin revisión. |
| **Listas internacionales** (OFAC/SDN, ONU) y **PEP** | Coincidencia → no se aprueba automáticamente; PEP → debida diligencia reforzada. |
| **LOPDP** — Ley Orgánica de Protección de Datos Personales (2021) y Superintendencia de Protección de Datos Personales | Base legal y finalidad del tratamiento, minimización, seguridad, transparencia, derechos del titular (incl. **no ser objeto de decisiones basadas únicamente en tratamiento automatizado**), transferencias a terceros (p. ej. proveedores de LLM). |
| **Registro Civil (DIGERCIC)** | Fuente oficial para validar la cédula (10 dígitos) y datos biométricos. |

## 2. Actores

| Actor | Rol | Necesidad principal |
|---|---|---|
| **Prospecto** | Persona natural que solicita un producto desde el canal digital. | Saber rápido y con claridad si fue aceptado, qué le falta y qué hacer si algo falla. |
| **Canal digital** (app/web del Banco) | Consumidor de la API `POST /api/v1/onboarding/start`; muestra el mensaje al cliente. | API estable, respuesta en una sola llamada, estado consultable. |
| **Oficial de cumplimiento** | Humano del grupo `compliance`; resuelve escalamientos (`approve` / `reject` / `retry`). | Contexto completo del caso (pasos, motivos, propuesta, auditoría) y que su decisión quede registrada a su nombre. |
| **Sistema (orquestador + sub-agentes)** | Identity, Risk, Documentation, Mitigation, Response. | Herramientas acotadas por agente, estado persistente entre pasos, reglas de política deterministas. |
| *Secundarios:* Auditoría interna / SB, Seguridad de la información, Delegado de protección de datos (DPO) | Revisan trazas y cumplimiento. | Evidencia reproducible de por qué se decidió cada caso. |

## 3. Problema

Hoy (supuesto) el onboarding exige verificaciones manuales o integraciones dispersas: identidad, listas de riesgo y armado de expediente se hacen en secuencia por personas distintas. Esto genera:

1. **Tiempos largos** de apertura y abandono del prospecto digital.
2. **Inconsistencia** al aplicar políticas (cada analista interpreta umbrales).
3. **Poca trazabilidad** de por qué se aprobó o rechazó.
4. **Rechazos secos**: cuando algo falla o es ambiguo, el cliente no recibe una salida (alternativa) y se pierde.

Se busca un **agente orquestador** que coordine agentes especializados, **controle qué herramienta usa cada uno**, **mantenga el estado** entre pasos y **mitigue la incertidumbre** (escalando a un humano o proponiendo una solución) — sin delegar la decisión regulatoria a un modelo generativo.

## 4. Objetivos medibles

| # | Objetivo | Métrica | Meta propuesta [SUPUESTO] |
|---|---|---|---|
| O1 | Resolver automáticamente los casos limpios | % solicitudes con decisión final sin intervención humana | ≥ 70 % |
| O2 | Respuesta inmediata al canal | p95 latencia de `start` (mocks / proveedores reales) | ≤ 3 s / ≤ 10 s |
| O3 | Cero aprobaciones automáticas indebidas | Aprobaciones automáticas con identidad < 0.8 o riesgo `high` | **0** (regla dura) |
| O4 | Ningún rechazo sin salida | % de REJECTED/ESCALATED con propuesta (RF3) | 100 % |
| O5 | Auditabilidad total | % de casos con traza completa (tool_call, tool_result, decisión, actor humano) | 100 % |
| O6 | Atención oportuna de escalamientos | Tiempo a resolución de escalamiento por oficial | ≤ 24 h hábiles |

**Contra-métricas:** tasa de escalamiento (si sube demasiado, el umbral o los proveedores no sirven), tasa de falsos positivos en listas (homonimia), quejas de clientes por mensajes confusos, contradicciones LLM vs decisión detectadas.

## 5. Alcance

### Dentro
- Recepción de solicitud (`prospect_name`, `document_id`, `product`) por API REST.
- Orquestación secuencial: identidad → riesgo → documentación → decisión → respuesta.
- Allowlist de tools por agente (mínimo privilegio) y registro en auditoría de cualquier intento no permitido.
- Motor de políticas determinista (umbral 0.8, niveles de riesgo, documentos por producto).
- Mitigación: reintento de servicio, escalamiento a oficial con propuesta, propuestas en rechazo/condiciones.
- Estado conversacional persistente y consultable; reanudación tras resolución humana.
- Mensaje al cliente redactado por LLM (Claude → OpenAI → plantilla) con salvaguardas.
- Despliegue serverless AWS **manual** (`sam deploy` desde local, **sin CI/CD**), verificación con skill `verify`.

### Fuera
- Integración real con Registro Civil, proveedores de listas (OFAC/UAFE) o buró: se usan **mocks deterministas**.
- Captura de documentos/biometría (selfie, prueba de vida) y firma electrónica del contrato.
- Apertura efectiva del producto en el core bancario.
- Reportes regulatorios a UAFE (ROS/RESU) y scoring crediticio para tarjeta.
- Personas jurídicas, menores de edad, extranjeros sin cédula.
- Frontend del canal digital y consola del oficial (solo API).
- Pipeline CI/CD (restricción explícita del usuario).

## 6. Riesgos de negocio

| Riesgo | Impacto | Mitigación en la solución |
|---|---|---|
| Aprobar a alguien en lista de sanciones | Sanción regulatoria, reputacional | `high` nunca se auto-aprueba; solo un oficial autenticado (grupo `compliance`) puede aprobar. |
| El LLM "decide" o contradice la decisión | Decisión no explicable, incumplimiento LOPDP | Decisión determinista; LLM solo redacta; detector de contradicciones + línea de estado fija + fallback a plantilla. |
| Suplantación de identidad | Fraude | Umbral de confianza 0.8 y `verified=false` → rechazo con verificación presencial. |
| Indisponibilidad de proveedores | Abandono, casos colgados | Reintento 1 vez y escalamiento `tool_unavailable` con acción `retry`. |
| Exceso de escalamientos | Cuello de botella en Cumplimiento | Métrica de tasa de escalamiento; propuestas concretas para resolver rápido. |
| Exposición de datos personales (logs, LLM de terceros) | Multas LOPDP | Cifrado en reposo (DynamoDB SSE), auth JWT; **pendiente**: minimización/enmascaramiento en auditoría y prompts, retención (ver 04). |
| Despliegue manual sin CI/CD | Errores humanos al desplegar | Gate `verify` (tests + smoke) obligatorio antes de `sam deploy`; ADRs y checklist. |
| Falsos positivos por homonimia | Mala experiencia, pérdida de clientes | Propuesta de confirmar/descartar homonimia en escalamiento `risk_high`. |
