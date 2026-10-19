---
name: integrate
description: Integración ágil del proyecto de onboarding — escaneo de secretos, gate verify, merge --no-ff de ramas de feature, commit Conventional Commits y actualización de docs/STATE.md. Úsalo cuando el usuario diga "integra", "cierra la historia", "integrate", "haz el commit de la historia" o "mergea la rama".
---

# integrate

Resultado: el trabajo de la historia queda en `main` con un commit Conventional Commits, verify en verde, sin secretos, y `docs/STATE.md` al día. **Nunca hagas `git push`** salvo que el usuario lo pida explícitamente en este turno.

## Pasos

1. **Secretos** — detente si alguno falla:
   - `git grep -nE 'sk-ant-|sk-proj-|AKIA[0-9A-Z]{16}' -- . ':!uv.lock'` y lo mismo sobre archivos sin trackear a añadir (`git ls-files -o --exclude-standard | xargs grep -nE …`). Cualquier coincidencia real = bloqueo; muéstrala enmascarada.
   - `git check-ignore -q .env` debe tener éxito y `.env` no debe estar en `git ls-files`.
2. **Gate** — ejecuta el skill `verify`. Si no queda VERDE, no integres: reporta y para.
3. **Ramas** — proyecto pequeño, normalmente se trabaja directo en `main`. Si hay rama de feature: verify en la rama, `git switch main && git merge --no-ff <rama>`, y verify otra vez sobre `main` si hubo conflictos. No borres ramas sin preguntar.
4. **Commit** — `git add` solo de los archivos de la historia (nunca `.env`, `.venv`, artefactos de `.aws-sam/`). Mensaje Conventional Commits: `feat(orchestrator): …`, `fix(api): …`, `test: …`, `docs: …`, `chore: …`; cuerpo breve con el qué/por qué y la historia cerrada.
5. **docs/STATE.md** — créalo si no existe. Mantén secciones `## Hecho` y `## Pendiente` (historias con una línea cada una, fecha y hash corto del commit en Hecho) y `## Último gate` con la tabla de verify. Inclúyelo en el mismo commit (o un `docs(state): …` inmediatamente después).

## Cierre

Informa: commit(s) creados (`git log --oneline -n 3`), resultado del gate, historias hechas/pendientes, y recuerda que no se hizo push.
