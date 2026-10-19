# ADR-0002 — Allowlist de tools por agente en un ToolRegistry central

- **Estado:** Aceptado · 2026-10-19

## Contexto
Varios sub-agentes comparten proceso. Si cualquiera pudiera invocar cualquier tool, un bug o una salida
manipulada del LLM podría ejecutar acciones fuera de su responsabilidad (p.ej. el agente de respuesta
consultando listas de riesgo).

## Decisión
Un `ToolRegistry` único mantiene un allowlist declarativo `agente → {tools}`. Los agentes solo invocan
tools a través de `registry.call(agent, tool, ...)`. Una llamada fuera del allowlist lanza
`ToolNotPermittedError` y registra un evento en auditoría. Response y Mitigation no tienen tools.

## Consecuencias
- ✅ Mínimo privilegio verificable con un test por agente; permisos visibles en un solo archivo.
- ✅ Auditoría de cada llamada (permitida o denegada).
- ⚠️ Añadir una tool exige actualizar el allowlist (fricción intencional).
- El mismo principio se replica en IAM (ver ADR-0003).
