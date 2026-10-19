#!/usr/bin/env bash
# Usuarios de prueba del User Pool (idempotente). Passwords aleatorias guardadas SOLO en Secrets Manager
# `onboarding-agent/test-users` ({usuario: password}); nunca en stdout, argumentos de proceso ni repo.
#   canal-digital@test.onboarding         sin grupo  -> canal digital: start/get OK, resolve 403
#   oficial-cumplimiento@test.onboarding  compliance -> resuelve escalamientos
# Uso: infra/bootstrap/seed-test-users.sh [--profile onboarding-deployer] [--stack onboarding-agent-dev]
set -euo pipefail

PROFILE=onboarding-deployer STACK=onboarding-agent-dev REGION=us-east-1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --stack) STACK="$2"; shift 2 ;;
    *) echo "argumento desconocido: $1" >&2; exit 2 ;;
  esac
done
SECRET_ID="onboarding-agent/test-users"
CANAL="canal-digital@test.onboarding"
OFICIAL="oficial-cumplimiento@test.onboarding"

aws_() { aws --profile "$PROFILE" --region "$REGION" "$@"; }
output() { aws_ cloudformation describe-stacks --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }

POOL="$(output UserPoolId)"
[[ -n "$POOL" && "$POOL" != None ]] || { echo "sin UserPoolId en el stack $STACK" >&2; exit 1; }

TMP="$(mktemp -d)"; chmod 700 "$TMP"; trap 'rm -rf "$TMP"' EXIT

# Reutiliza las passwords si el secreto ya existe; si no, genera nuevas y crea el secreto.
if aws_ secretsmanager get-secret-value --secret-id "$SECRET_ID" --query SecretString --output text \
     >"$TMP/users.json" 2>/dev/null; then
  echo "secreto $SECRET_ID existente: se reutilizan passwords"
else
  python3 - "$CANAL" "$OFICIAL" >"$TMP/users.json" <<'PY'
import json, secrets, string, sys
def pwd():
    pools = [string.ascii_lowercase, string.ascii_uppercase, string.digits, "!@#%^*-_=+"]
    chars = [secrets.choice(p) for p in pools] + [secrets.choice("".join(pools)) for _ in range(20)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)
print(json.dumps({u: pwd() for u in sys.argv[1:]}))
PY
  python3 -c 'import json,sys; print(json.dumps({"Name": sys.argv[1], "SecretString": open(sys.argv[2]).read(),
    "Description": "Passwords de usuarios de prueba de Cognito (onboarding-agent)",
    "Tags": [{"Key": "project", "Value": "onboarding-agent"}]}))' "$SECRET_ID" "$TMP/users.json" >"$TMP/create.json"
  aws_ secretsmanager create-secret --cli-input-json "file://$TMP/create.json" >/dev/null
  echo "secreto $SECRET_ID creado"
fi

for user in "$CANAL" "$OFICIAL"; do
  if aws_ cognito-idp admin-get-user --user-pool-id "$POOL" --username "$user" >/dev/null 2>&1; then
    echo "usuario $user ya existe"
  else
    aws_ cognito-idp admin-create-user --user-pool-id "$POOL" --username "$user" --message-action SUPPRESS >/dev/null
    echo "usuario $user creado"
  fi
  python3 -c 'import json,sys; print(json.dumps({"UserPoolId": sys.argv[1], "Username": sys.argv[2],
    "Password": json.load(open(sys.argv[3]))[sys.argv[2]], "Permanent": True}))' \
    "$POOL" "$user" "$TMP/users.json" >"$TMP/pwd.json"
  aws_ cognito-idp admin-set-user-password --cli-input-json "file://$TMP/pwd.json"
done

aws_ cognito-idp admin-add-user-to-group --user-pool-id "$POOL" --username "$OFICIAL" --group-name compliance
aws_ cognito-idp admin-remove-user-from-group --user-pool-id "$POOL" --username "$CANAL" --group-name compliance
echo "listo: $OFICIAL en compliance; $CANAL sin grupo"
