# ADR-0005 — Sin CI/CD: despliegue manual con gate local `verify`

- **Estado:** Aceptado · 2026-10-19 (decisión del usuario)

## Contexto
Prueba técnica con un solo responsable, una cuenta AWS y entrega acotada en tiempo. Un pipeline
(GitHub Actions + OIDC hacia AWS) añade configuración de credenciales e infraestructura que no aporta
valor proporcional en este alcance. Remote: `git@github.com:MiguelPilamunga/testAgente.git` (rama `main`).

## Decisión
- **No** se agregan workflows de GitHub Actions ni pipelines.
- **Gate local obligatorio**: el skill `verify` (deps, tests, lint, smoke de escenarios del SPEC y allowlist
  de tools, reporte PASS/FAIL) debe estar en PASS antes de integrar (skill `integrate`) o desplegar.
- **Despliegue manual** con SAM y el perfil AWS `ecopacific`:
  ```bash
  sam validate --lint -t infra/template.yaml
  sam build -t infra/template.yaml && sam deploy --guided --profile ecopacific
  ```
  El perfil `personal` tiene credenciales inválidas (pendiente del usuario); no usarlo.

## Consecuencias
- ✅ Cero secretos de despliegue en GitHub; menos superficie de ataque y de configuración.
- ✅ El mismo gate (`verify`) se ejecuta siempre en la máquina que integra/despliega.
- ⚠️ Depende de la disciplina humana: nada impide técnicamente un `sam deploy` sin `verify`.
- ⚠️ Sin despliegues reproducibles desde un entorno limpio; si el proyecto crece, migrar a CI con OIDC
  (nuevo ADR que reemplace a este).
