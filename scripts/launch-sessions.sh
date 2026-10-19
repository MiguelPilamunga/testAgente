#!/usr/bin/env bash
# Abre una pestaña de iTerm por sesión de Claude Code, cada una con su prompt.
# Uso: scripts/launch-sessions.sh [nombre ...]   (sin args = todas las de scripts/prompts/)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODEL="${MODEL:-opus}"
names=("$@")
if [ ${#names[@]} -eq 0 ]; then
  for f in "$ROOT"/scripts/prompts/*.md; do names+=("$(basename "$f" .md)"); done
fi
for n in "${names[@]}"; do
  prompt="$ROOT/scripts/prompts/$n.md"
  [ -f "$prompt" ] || { echo "falta $prompt"; exit 1; }
  cmd="cd '$ROOT' && claude --dangerously-skip-permissions --name 'iaengineer-$n' --model $MODEL \"\$(cat '$prompt')\""
  osascript <<OSA
tell application "iTerm"
  activate
  if (count of windows) = 0 then
    create window with default profile
  else
    tell current window to create tab with default profile
  end if
  tell current session of current window to write text "$(printf '%s' "$cmd" | sed 's/\\/\\\\/g; s/"/\\"/g')"
end tell
OSA
  echo "lanzada iaengineer-$n"
done
