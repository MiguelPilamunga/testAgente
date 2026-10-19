# 03 — Épicas e historias de usuario

> Priorización **MoSCoW** (Must / Should / Could / Won't en esta entrega). Estado según el código actual:
> ✅ implementado (con tests) · 🟡 parcial · ⬜ pendiente. RF/RNF/POL refieren a [02-requisitos](02-requisitos.md).
> Restricción de entrega: sin CI/CD — cada historia se cierra con `verify` en verde y despliegue manual `sam deploy`.

## Resumen

| Épica | Historias | Must | Estado |
|---|---|---|---|
| EP-1 Recepción de solicitud | HU-01, HU-02 | 2 | ✅ |
| EP-2 Verificaciones agénticas | HU-03 – HU-06 | 4 | ✅ |
| EP-3 Decisión por políticas | HU-07 – HU-09 | 3 | ✅ |
| EP-4 Mitigación y escalamiento | HU-10 – HU-13 | 3 | ✅ / ⬜ (HU-13) |
| EP-5 Estado conversacional y respuesta | HU-14 – HU-16 | 3 | ✅ |
| EP-6 Gobierno, seguridad y datos | HU-17 – HU-22 | 3 | ✅ / 🟡 / ⬜ |
| EP-7 Operación (sin CI/CD) | HU-23 – HU-24 | 1 | ✅ / 🟡 |

---

## EP-1 — Recepción de solicitud de onboarding

**HU-01 · Iniciar onboarding** — Must · ✅ (`api.py` `start`, `tests/test_api.py`) · RF-01
Como **canal digital**, quiero enviar nombre, cédula y producto del prospecto, para iniciar su vinculación en una sola llamada.
- Given datos válidos, When `POST /api/v1/onboarding/start`, Then 200 con `onboarding_id`, `status` y `customer_message`.

**HU-02 · Validar datos de entrada** — Must · ✅ (`models.OnboardingRequest`) · RF-01
Como **Banco**, quiero rechazar solicitudes mal formadas, para no consultar proveedores con datos basura.
- Given `document_id` ≠ 10 dígitos, Then 422.
- Given nombre < 3 caracteres, Then 422.
- *Mejora ⬜ (Could):* validar dígito verificador de la cédula ecuatoriana (módulo 10) — ver P-04.

## EP-2 — Verificaciones agénticas con herramientas controladas

**HU-03 · Verificar identidad** — Must · ✅ (`agents/identity.py`) · RF-02, POL-01..03
Como **oficial de cumplimiento**, quiero que la identidad se valide con un puntaje de confianza, para no vincular suplantadores.
- Given confianza ≥ 0.8 y verificado, Then continúa a riesgo.
- Given confianza < 0.8, Then ESCALATED.
- Given `verified=false` con confianza ≥ 0.8, Then REJECTED + propuesta de verificación presencial.

**HU-04 · Consultar listas de riesgo** — Must · ✅ (`agents/risk.py`) · RF-03, POL-04..06
Como **oficial de cumplimiento**, quiero conocer coincidencias en listas (OFAC, PEP), para aplicar la debida diligencia que corresponda.
- Given `high`, Then ESCALATED; Given `medium`, Then condiciones; Given `low`, Then continúa.

**HU-05 · Preparar documentación según producto** — Must · ✅ (`agents/documentation.py`, `policies.PRODUCTS`) · RF-04
Como **prospecto**, quiero saber exactamente qué documentos entregar, para completar mi apertura sin idas y vueltas.
- Given `cuenta_corriente`, Then `required_documents` incluye referencia bancaria y certificado de ingresos.
- Given riesgo `medium`, Then incluye declaración de origen de fondos y formulario PEP.

**HU-06 · Allowlist de herramientas por agente** — Must · ✅ (`tools/registry.py`, `tests/test_tool_permissions.py`) · RNF-04
Como **seguridad de la información**, quiero que cada agente solo pueda usar su herramienta, para limitar el daño de un agente comprometido o mal instruido.
- Given un agente llama una tool no otorgada, Then `ToolNotPermittedError` y evento `tool_denied` en auditoría.
- Given ResponseAgent y MitigationAgent, Then no tienen ninguna tool.

## EP-3 — Decisión de aptitud bajo políticas

**HU-07 · Decisión determinista** — Must · ✅ (`orchestrator._decide`, ADR-0001) · RF-05, RNF-03
Como **auditor/SB**, quiero que la aptitud la decida un motor de reglas y no el LLM, para que sea reproducible y explicable.
- Given mismos insumos con LLM o plantilla, Then mismo `status`.

**HU-08 · Aprobación con condiciones** — Must · ✅ · POL-05
Como **Banco**, quiero aprobar prospectos de riesgo medio con condiciones, para no perder clientes legítimos (p. ej. PEP) cumpliendo debida diligencia reforzada.
- Given `0900000004`, Then `APPROVED_WITH_CONDITIONS` con docs EDD y propuesta en `proposals`.

**HU-09 · Producto no ofertado** — Should · ✅ · RF-11, POL-08
Como **prospecto**, quiero que si pido un producto inexistente me sugieran los disponibles, para no quedarme sin opción.

## EP-4 — Mitigación de incertidumbre y escalamiento humano

**HU-10 · Escalar casos inciertos** — Must · ✅ · RF-07
Como **oficial de cumplimiento**, quiero recibir los casos ambiguos con motivo, severidad y propuesta, para decidir rápido y con contexto.
- Given `0900000002` / `0900000003`, Then `ESCALATED`, escalamiento `OPEN` con `proposal` no vacía.

**HU-11 · Reintento ante falla de servicio** — Must · ✅ (`_call_with_retry`) · POL-07, RNF-07
Como **canal digital**, quiero que una caída momentánea no rechace al cliente, para no perder la solicitud.
- Given `0900000005`, Then 2 intentos auditados y ESCALATED con propuesta `retry`.

**HU-12 · Resolver y reanudar** — Must · ✅ (`resolve`, `auth.py`, `tests/test_auth.py`) · RF-08, RNF-05
Como **oficial de cumplimiento**, quiero aprobar, rechazar o reintentar un escalamiento, para que el flujo continúe desde donde se pausó y quede registrado a mi nombre.
- Given `approve`, Then continúa desde el siguiente paso; Given `reject`, Then REJECTED; Given `retry`, Then re-ejecuta el paso.
- Given escalamiento resuelto, Then 409; sin grupo `compliance`, Then 403; auditoría con `sub` del oficial.

**HU-13 · Bandeja de pendientes** — Should · ⬜ · RF-12
Como **oficial de cumplimiento**, quiero listar los escalamientos abiertos por severidad y antigüedad, para atender primero lo crítico y cumplir el SLA (O6).
- Given 3 casos abiertos, When consulto la bandeja, Then los veo ordenados por severidad y fecha.

## EP-5 — Estado conversacional y respuesta al cliente

**HU-14 · Persistir estado entre pasos** — Must · ✅ (`state/store.py` memoria/DynamoDB) · RF-09, E-04
Como **orquestador**, quiero guardar el estado tras cada ejecución, para reanudar después de un escalamiento aunque pasen horas.
- Given un caso escalado, When se resuelve en otra invocación Lambda, Then se recupera el estado completo.

**HU-15 · Consultar estado** — Must · ✅ · RF-09
Como **canal digital**, quiero consultar el estado de una solicitud, para mostrar avances al cliente.

**HU-16 · Mensaje claro y seguro al cliente** — Must · ✅ (`agents/response.py`, `tests/test_llm_fallback.py`) · RF-10
Como **prospecto**, quiero un mensaje breve que diga el estado real y el siguiente paso, para saber qué hacer.
- Given LLM que dice "aprobado" en un REJECTED, Then se descarta y se usa la plantilla.
- Given sin API keys, Then plantilla determinista.
- Then el mensaje nunca menciona listas de sanciones.

## EP-6 — Gobierno, seguridad y protección de datos

**HU-17 · Auditoría completa** — Must · ✅ · RNF-01
Como **auditor**, quiero ver cada llamada de herramienta, resultado, decisión y actor humano con timestamp, para reconstruir el caso.

**HU-18 · Autenticación y rol de cumplimiento** — Must · ✅ (ADR-0004, sin commit aún) · RNF-05
Como **seguridad**, quiero JWT en todas las rutas y grupo `compliance` para `/resolve`, para que nadie más pueda aprobar casos escalados.

**HU-19 · Explicación de la decisión** — Must · ✅ · RNF-02
Como **prospecto/regulador**, quiero motivos y referencias de política, para entender y, si aplica, impugnar.

**HU-20 · Minimización de datos en auditoría y LLM** — Should · 🟡 · RNF-09
Como **DPO**, quiero que la cédula se enmascare en logs/auditoría y que al LLM solo vaya lo indispensable, para cumplir LOPDP.
- Given un caso, Then `audit[].detail` muestra `******5678`. *(Hoy se guardan args completos.)*

**HU-21 · Retención del expediente** — Should · ⬜ · RNF-11
Como **DPO/Cumplimiento**, quiero un plazo de retención y borrado/anonimización, para cumplir conservación regulatoria y LOPDP. *(Plazo por confirmar, P-06.)*

**HU-22 · Consentimiento del titular** — Could · ⬜ · RN-07
Como **Banco**, quiero registrar el consentimiento/base legal del tratamiento en la solicitud, para evidenciar licitud ante la autoridad de datos.

## EP-7 — Operación (sin CI/CD)

**HU-23 · Gate de verificación antes de desplegar** — Must · ✅ (skill `verify`) · RNF-12
Como **equipo de desarrollo**, quiero correr tests + smoke antes de `sam deploy` manual, para compensar la ausencia de CI/CD.

**HU-24 · Métricas de negocio** — Could · 🟡 · RNF-14
Como **product owner**, quiero tasas de auto-resolución, escalamiento y contradicciones LLM, para ajustar umbrales.

## Won't (esta entrega)
- Integración real con Registro Civil, OFAC/UAFE, buró de crédito.
- Biometría/prueba de vida, firma electrónica, apertura en core bancario.
- Reportes ROS/RESU a UAFE.
- Pipeline CI/CD (restricción del usuario).
- Idempotencia de `start` (RNF-13) — candidata a siguiente sprint.
