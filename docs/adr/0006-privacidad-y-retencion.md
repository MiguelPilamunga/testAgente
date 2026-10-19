# ADR-0006 — Privacidad (LOPDP): PII enmascarada en auditoría y retención con TTL

- **Estado:** Aceptado · 2026-10-19 · Requisitos: RNF-09 (minimización), RNF-11 (retención) en
  [`docs/negocio/02-requisitos.md`](../negocio/02-requisitos.md)

## Contexto
La Ley Orgánica de Protección de Datos Personales (Ecuador) exige minimizar los datos tratados y conservarlos
solo el plazo necesario. La auditoría (`audit[].detail`) guardaba la cédula y el nombre completos en cada
`tool_call` y el expediente en DynamoDB no tenía fecha de expiración.

## Decisión
- **Minimización en auditoría:** `OnboardingState.log` aplica `mask_pii` recursivo (dicts y listas) al `detail`:
  `document_id` → `******5678` (últimos 4 dígitos), `name`/`prospect_name` → iniciales (`J. P.`).
  Se aplica en un único punto, así ningún agente/tool puede olvidarlo.
- **Dato operativo intacto:** `state.prospect` conserva los datos completos (necesarios para reintentos,
  `resolve` y el expediente); solo la traza se minimiza.
- **Retención:** `DynamoDBStore.save` escribe `expires_at` = ahora + `STATE_TTL_DAYS` (default 90) en epoch s;
  la tabla activa `TimeToLiveSpecification` sobre `expires_at` (parámetro SAM `StateTtlDays`). El plazo cuenta
  desde la última actualización, así un caso escalado no expira mientras se trabaja.

## Consecuencias
- ✅ La auditoría puede exportarse/consultarse sin exponer identificadores completos.
- ✅ Eliminación automática y sin coste por DynamoDB (borrado asíncrono, típicamente < 48 h tras expirar).
- ⚠️ La auditoría ya no permite correlacionar por cédula completa → se correlaciona por `onboarding_id`.
- ⚠️ El plazo de 90 días es un default técnico; el plazo regulatorio real lo fija Cumplimiento/Legal
  (ajustable sin código vía `StateTtlDays`). PITR y backups conservan copias hasta su propia retención (35 días).
- ⚠️ Los prompts al LLM siguen fuera de este ADR (alcance de `agents/`/`llm/`, RNF-09 parcial).
