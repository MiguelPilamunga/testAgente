# 04 — Glosario, supuestos, ambigüedades y preguntas abiertas

## Glosario

| Término | Definición |
|---|---|
| **Onboarding digital** | Proceso de vinculación de un nuevo cliente sin presencia física: identificación, evaluación de riesgo, expediente y activación. |
| **KYC (Know Your Customer / Conozca a su Cliente)** | Política obligatoria de identificar y verificar al cliente, conocer su actividad y origen de fondos y construir su perfil de riesgo. |
| **AML / PLA-FT** | Anti-Money Laundering / Prevención de Lavado de Activos y Financiamiento del Terrorismo (y otros delitos). |
| **Debida diligencia (DD)** | Conjunto de verificaciones proporcional al riesgo: simplificada, estándar o **reforzada**. |
| **Debida diligencia reforzada (EDD)** | Medidas adicionales para clientes de mayor riesgo (p. ej. PEP): declaración de origen lícito de fondos, formulario PEP, aprobación de nivel superior y monitoreo intensificado. |
| **PEP** | Persona Expuesta Políticamente: ejerce o ejerció funciones públicas destacadas (y sus familiares/colaboradores cercanos). No implica prohibición, sino EDD. |
| **OFAC / SDN** | Office of Foreign Assets Control (Tesoro de EE. UU.) y su lista de nacionales especialmente designados; coincidencia ⇒ no vincular sin revisión de Cumplimiento. |
| **Listas de riesgo** | Listas de sanciones (OFAC, ONU), listas UAFE/internas, PEP, medios adversos. |
| **Homonimia** | Coincidencia de nombre con una persona listada sin ser la misma persona; causa falsos positivos. |
| **UAFE** | Unidad de Análisis Financiero y Económico del Ecuador; recibe reportes de operaciones inusuales/sospechosas. |
| **SB** | Superintendencia de Bancos del Ecuador; supervisa a las entidades financieras y su política KYC. |
| **LOPDP** | Ley Orgánica de Protección de Datos Personales del Ecuador (2021). |
| **Oficial de cumplimiento** | Responsable de PLA-FT en el Banco; aquí, usuario del grupo Cognito `compliance` que resuelve escalamientos. |
| **Escalamiento** | Pausa del flujo para decisión humana, con motivo, severidad y propuesta. |
| **Mitigación** | Acción propuesta para resolver una verificación fallida/ambigua (catálogo `MITIGATIONS`). |
| **Allowlist de tools** | Lista explícita de herramientas que cada agente puede invocar. |
| **Confianza (confidence)** | Puntaje 0–1 del proveedor de identidad sobre la coincidencia cédula/persona. |

## Supuestos tomados (S-xx)

| ID | Supuesto | Por qué |
|---|---|---|
| S-01 | Solo personas naturales ecuatorianas con cédula de 10 dígitos. | El RT pide `document_id`; la cédula es el documento estándar. |
| S-02 | Productos ofertados: cuenta de ahorros, cuenta corriente, tarjeta de crédito, con documentos por producto definidos en `policies.py`. | El enunciado habla de "políticas del banco" sin detallarlas. |
| S-03 | El expediente y la traza deben conservarse para supervisión. | Obligación general KYC/AML. |
| S-04 | Aplica LOPDP: decisiones automatizadas adversas deben tener revisión humana posible. | Derecho del titular. |
| S-05 | `verified=false` con alta confianza es un **no** claro (rechazo con propuesta presencial), no una ambigüedad. | El enunciado solo define escalar por confianza < 0.8. |
| S-06 | `medium` ⇒ apto con condiciones (EDD), no escalamiento. | El enunciado solo exige escalar en `high`. |
| S-07 | Una aprobación manual de un escalamiento de identidad no agrega condiciones; las condiciones dependen solo del riesgo. | Evita penalizar al cliente por limitaciones del proveedor. |
| S-08 | Habrá un equipo de Cumplimiento con SLA de atención (≤ 24 h hábiles). | Necesario para que el escalamiento no sea un callejón sin salida. |
| S-09 | Los servicios externos se simulan con mocks deterministas por `document_id`. | No hay integraciones reales en la evaluación. |
| S-10 | El LLM (Claude, fallback OpenAI, plantilla) solo redacta y enriquece propuestas. | Un banco no puede delegar la aprobación a un modelo generativo (ADR-0001). |
| S-11 | Despliegue manual con `sam deploy`, sin CI/CD; `verify` como gate. | Restricción explícita del usuario. |
| S-12 | Umbral de identidad inclusivo: 0.80 pasa, 0.79 escala. | El enunciado dice "< 0.8 escala". |

## Ambigüedades del enunciado y resolución

| # | Ambigüedad | Resolución adoptada |
|---|---|---|
| A-01 | "Determinar si es apto o no" — ¿binario? | Tres resultados finales: APPROVED, APPROVED_WITH_CONDITIONS, REJECTED; más ESCALATED como estado intermedio. |
| A-02 | "Escala" — ¿a quién y luego qué? | A un oficial de cumplimiento vía `POST /resolve` (approve/reject/retry); el flujo se reanuda con el estado persistido. |
| A-03 | Qué hacer con `medium` | Aprobar con condiciones + EDD (S-06). |
| A-04 | `verified=false` con confianza ≥ 0.8 | Rechazo con propuesta de verificación presencial (S-05). |
| A-05 | "Proponer una solución" — ¿generada por IA? | Propuesta base del catálogo de políticas (determinista) + enriquecimiento opcional por LLM. |
| A-06 | Falla técnica (servicio caído) vs ambigüedad | Ambas son incertidumbre: reintento 1 vez y luego escalamiento con acción `retry`. |
| A-07 | "Estado conversacional" | Historial `conversation[]` (customer/bank/officer) + `steps`, `audit` y `current_step` persistidos (memoria/DynamoDB). |
| A-08 | `client_data` de `prepare_documentation` no está definido | Se pasa nombre, cédula y nivel de riesgo (para decidir docs EDD). |
| A-09 | "Controlar qué herramientas puede usar cada agente" | Registry con `grant` explícito; Response/Mitigation sin tools; intento indebido ⇒ excepción + auditoría. |
| A-10 | Producto inexistente | REJECTED con propuesta de productos alternativos (no 422), para dar salida al cliente. |
| A-11 | Orden de reglas si confianza < 0.8 **y** `verified=false` | Prima la ambigüedad: se escala (la confianza baja hace dudoso el "false"). |

## Preguntas abiertas para el negocio

| ID | Pregunta | Dueño sugerido | Impacto si no se responde |
|---|---|---|---|
| P-01 | ¿El umbral 0.8 es definitivo y único para todos los productos (p. ej. más alto para tarjeta de crédito)? | Cumplimiento / Riesgo | Riesgo de fraude o exceso de escalamientos. |
| P-02 | ¿Riesgo `medium` siempre aprueba con condiciones, o algunos productos (cuenta corriente, TC) deben escalar? | Cumplimiento | Posible incumplimiento de EDD (aprobación de nivel superior para PEP). |
| P-03 | ¿Un PEP requiere aprobación de alta gerencia antes de activar el producto? | Cumplimiento | `APPROVED_WITH_CONDITIONS` podría no bastar. |
| P-04 | ¿Se debe validar el dígito verificador de la cédula y aceptar pasaporte/extranjeros? | Producto | Consultas innecesarias a proveedores; exclusión de segmentos. |
| P-05 | ¿SLA y horario del equipo de Cumplimiento; qué pasa si un escalamiento vence? | Operaciones | Casos colgados, abandono del cliente. |
| P-06 | Plazo de retención del expediente y de la auditoría (normativa SB/UAFE vs minimización LOPDP). | Legal / DPO | Incumplimiento por exceso o por defecto. |
| P-07 | ¿Está autorizado enviar datos del prospecto (nombre) a proveedores de LLM externos (transferencia internacional)? ¿Se requiere región/acuerdo de tratamiento? | DPO / Legal | Riesgo LOPDP; alternativa: solo plantilla o LLM sin PII. |
| P-08 | ¿Qué consentimiento/aviso de privacidad acepta el prospecto antes de iniciar? | Legal / Producto | Falta de base legal del tratamiento. |
| P-09 | ¿Un rechazo por `verified=false` debe notificarse a Cumplimiento (posible intento de suplantación / reporte UAFE)? | Cumplimiento | Pérdida de señal de fraude. |
| P-10 | ¿Se requiere tarjeta de crédito con evaluación de buró/capacidad de pago dentro del mismo flujo? | Riesgo de crédito | Aprobaciones sin scoring. |
| P-11 | ¿El canal reintenta solicitudes? ¿Se necesita idempotencia por cédula+producto? | Canal digital | Expedientes duplicados. |
| P-12 | ¿Quién puede ver la auditoría completa (incluye datos de riesgo) y por cuánto tiempo? | Seguridad / DPO | Acceso excesivo a datos sensibles. |
