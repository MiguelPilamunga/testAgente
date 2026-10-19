---
name: verify
description: Gate de verificación del agente de onboarding — deps, tests, lint, smoke de la API contra los escenarios de docs/SPEC.md y allowlist de tools, con reporte PASS/FAIL. Úsalo cuando el usuario diga "verifica", "corre el gate", "verify", "¿está verde?", o antes de integrar/commitear (lo invoca el skill integrate).
---

# verify

Resultado: una tabla PASS/FAIL por paso y un veredicto único (VERDE solo si todo pasa). No arregles código dentro de este skill: reporta qué falló y la salida relevante.

`docs/SPEC.md` es el contrato. Si un resultado contradice la SPEC, el fallo es del código, no de la SPEC.

## Pasos (desde la raíz del repo)

1. `uv sync`
2. `uv run pytest -q`
3. `uv run ruff check src tests`
4. **Allowlist de tools** — `uv run pytest -q -k "allowlist or permitted or permission"`. Debe recolectar ≥1 test y pasar; si recolecta 0, es FAIL ("falta test de ToolNotPermittedError"). Si existe el registro, confirma además en vivo, p. ej. con `uv run python -c` invocando una tool ajena desde un agente (RiskAgent → `verify_identity`) y comprobando que lanza `ToolNotPermittedError` y deja evento en auditoría (SPEC § Tools y permisos).
5. **Smoke de la API**:
   ```bash
   LLM_PROVIDER=none AUTH_MODE=none ALLOW_INSECURE_LOCAL=1 uv run uvicorn onboarding.api:app --app-dir src --port 8099 >/tmp/verify-uvicorn.log 2>&1 &
   PID=$!; for i in $(seq 1 30); do curl -sf localhost:8099/health >/dev/null && break; sleep 0.5; done
   .claude/skills/verify/scripts/smoke.sh http://localhost:8099; RC=$?
   kill $PID
   ```
   El script cubre los 6 `document_id` de la SPEC, 422 por `document_id` inválido, producto inexistente → REJECTED, `proposals` con "presencial" y `conversation` en `0900000001`, docs extra y `proposals` en `0900000004` y `resolve` approve/reject. Sale ≠0 si algo falla. Mata siempre el servidor, también si falla. Si el puerto 8099 está ocupado, usa otro y pásalo como BASE_URL.

Corre todos los pasos aunque uno falle (salvo `uv sync`, que bloquea el resto), para que el reporte sea completo.

## Reporte

```
| Paso       | Resultado | Detalle            |
|------------|-----------|--------------------|
| uv sync    | PASS      |                    |
| pytest     | FAIL      | 2 failed: test_x…  |
| ruff       | PASS      |                    |
| allowlist  | PASS      | 3 tests            |
| smoke      | PASS      | 15/15              |
Veredicto: ROJO
```
