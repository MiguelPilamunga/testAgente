#!/usr/bin/env bash
# Demo con curl de todos los escenarios y del flujo con estado (escala → resolve → GET).
# Uso: scripts/demo-curl.sh [BASE_URL]        (default http://localhost:8099)
#      AUTH_TOKEN=... OFFICER_TOKEN=... scripts/demo-curl.sh https://<api>.execute-api.us-east-1.amazonaws.com
set -euo pipefail
B="${1:-http://localhost:8099}"; B="${B%/}"
AUTH=(); [ -n "${AUTH_TOKEN:-}" ] && AUTH=(-H "Authorization: Bearer $AUTH_TOKEN")
OFF=(); [ -n "${OFFICER_TOKEN:-${AUTH_TOKEN:-}}" ] && OFF=(-H "Authorization: Bearer ${OFFICER_TOKEN:-$AUTH_TOKEN}")

start() { curl -sS -X POST "$B/api/v1/onboarding/start" ${AUTH[@]+"${AUTH[@]}"} \
  -H 'Content-Type: application/json' -d "{\"prospect_name\":\"Juan Perez\",\"document_id\":\"$1\",\"product\":\"$2\"}"; }

echo "== GET /health"
curl -sS "$B/health"; echo

echo; echo "== Escenarios POST /start"
for doc in 1712345678 0900000001 0900000002 0900000003 0900000004 0900000005; do
  printf '%s  ' "$doc"; start "$doc" cuenta_ahorros | jq -c '{status, current_step, escalation: .escalations[0].reason}'
done
printf 'hipoteca    '; start 1712345678 hipoteca | jq -c '{status, proposals}'
printf 'doc "12"    '; curl -sS -o /dev/null -w 'HTTP %{http_code}\n' -X POST "$B/api/v1/onboarding/start" \
  ${AUTH[@]+"${AUTH[@]}"} -H 'Content-Type: application/json' -d '{"prospect_name":"Juan Perez","document_id":"12","product":"x"}'

echo; echo "== Flujo con estado: start (escala) → resolve approve → GET"
R=$(start 0900000002 cuenta_ahorros)
ID=$(printf '%s' "$R" | jq -r .onboarding_id)
ESC=$(printf '%s' "$R" | jq -r '.escalations[0].id')
printf '%s' "$R" | jq -c '{onboarding_id, status, current_step, escalation_id: .escalations[0].id}'
curl -sS -X POST "$B/api/v1/onboarding/$ID/resolve" ${OFF[@]+"${OFF[@]}"} -H 'Content-Type: application/json' \
  -d "{\"escalation_id\":\"$ESC\",\"action\":\"approve\",\"notes\":\"Identidad confirmada por biometria\"}" \
  | jq '{status, customer_message}'
curl -sS "$B/api/v1/onboarding/$ID" ${AUTH[@]+"${AUTH[@]}"} \
  | jq '{status, current_step, conversation, audit_events: (.audit | length)}'
