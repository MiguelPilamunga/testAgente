#!/usr/bin/env bash
# Smoke test de la API contra los escenarios de docs/SPEC.md.
# Uso: smoke.sh [BASE_URL]   (default http://localhost:8099). Sale !=0 si algún caso falla.
set -uo pipefail

BASE_URL="${1:-${BASE_URL:-http://localhost:8099}}"
API="$BASE_URL/api/v1/onboarding"
FAILS=0
ROWS=()

record() { # caso, esperado, obtenido
  local verdict=PASS
  [[ "$2" == "$3" ]] || { verdict=FAIL; FAILS=$((FAILS + 1)); }
  ROWS+=("$(printf '| %-36s | %-24s | %-24s | %s |' "$1" "$2" "$3" "$verdict")")
}

start() { # document_id product -> body JSON en stdout, http code en $HTTP
  local out
  out=$(curl -s -w '\n%{http_code}' -X POST "$API/start" -H 'Content-Type: application/json' \
    -d "{\"prospect_name\":\"Smoke Test\",\"document_id\":\"$1\",\"product\":\"$2\"}")
  HTTP="${out##*$'\n'}"
  BODY="${out%$'\n'*}"
}

field() { jq -r "$1 // empty" <<<"$BODY" 2>/dev/null; }

# Salud
record "GET /health" "200" "$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/health")"

# Escenarios por document_id (tabla de SPEC.md)
while read -r doc expected; do
  start "$doc" cuenta_ahorros
  record "start $doc" "$expected" "$(field .status)"
done <<'EOF'
1712345678 APPROVED
0900000001 REJECTED
0900000002 ESCALATED
0900000003 ESCALATED
0900000004 APPROVED_WITH_CONDITIONS
0900000005 ESCALATED
EOF

# 0900000001 debe traer propuesta (RF3: no solo rechazar)
start 0900000001 cuenta_ahorros
has_proposal=$(jq -r '[.proposals[]? | test("presencial"; "i")] | any' <<<"$BODY" 2>/dev/null)
record "0900000001 proposals: presencial" "true" "${has_proposal:-false}"
record "0900000001 conversation>0" "true" "$(jq -r '(.conversation | length) > 0' <<<"$BODY" 2>/dev/null)"

# 0900000004 debe exigir documentos de debida diligencia y traer propuesta (condiciones)
start 0900000004 cuenta_ahorros
record "0900000004 required_documents>0" "true" "$(jq -r '(.required_documents | length) > 0' <<<"$BODY" 2>/dev/null)"
record "0900000004 proposals>0" "true" "$(jq -r '(.proposals | length) > 0' <<<"$BODY" 2>/dev/null)"

# Validaciones de entrada
start 12345 cuenta_ahorros
record "document_id inválido -> 422" "422" "$HTTP"
start 1712345678 producto_inexistente
record "producto inexistente -> REJECTED" "REJECTED" "$(field .status)"

# Escalamiento + resolve approve reanuda el flujo
start 0900000002 cuenta_ahorros
OID=$(field .onboarding_id)
EID=$(jq -r '.escalations[0].id // empty' <<<"$BODY" 2>/dev/null)
record "GET estado escalado" "ESCALATED" "$(curl -s "$API/$OID" | jq -r '.status // empty' 2>/dev/null)"
BODY=$(curl -s -X POST "$API/$OID/resolve" -H 'Content-Type: application/json' \
  -d "{\"escalation_id\":\"$EID\",\"action\":\"approve\",\"notes\":\"smoke\"}")
record "resolve approve -> reanuda" "APPROVED" "$(field .status)"
start 0900000003 cuenta_ahorros
OID=$(field .onboarding_id); EID=$(jq -r '.escalations[0].id // empty' <<<"$BODY" 2>/dev/null)
BODY=$(curl -s -X POST "$API/$OID/resolve" -H 'Content-Type: application/json' \
  -d "{\"escalation_id\":\"$EID\",\"action\":\"reject\",\"notes\":\"smoke\"}")
record "resolve reject -> REJECTED" "REJECTED" "$(field .status)"

printf '| %-36s | %-24s | %-24s | %s |\n' "Caso" "Esperado" "Obtenido" "Resultado"
printf '|%s|%s|%s|%s|\n' "--------------------------------------" "--------------------------" "--------------------------" "-----------"
printf '%s\n' "${ROWS[@]}"
echo
if ((FAILS > 0)); then echo "SMOKE: FAIL ($FAILS casos)"; exit 1; fi
echo "SMOKE: PASS"
