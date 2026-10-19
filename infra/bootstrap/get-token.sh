#!/usr/bin/env bash
# Imprime SOLO el IdToken (trae cognito:groups y su audience = ClientId, lo que valida el JWT authorizer).
# Uso: export AUTH_TOKEN=$(infra/bootstrap/get-token.sh oficial|canal [--profile onboarding-deployer] [--stack onboarding-agent-dev])
set -euo pipefail

case "${1:-}" in
  canal) USER="canal-digital@test.onboarding" ;;
  oficial) USER="oficial-cumplimiento@test.onboarding" ;;
  *) echo "uso: $0 canal|oficial [--profile P] [--stack S]" >&2; exit 2 ;;
esac
shift
PROFILE=onboarding-deployer STACK=onboarding-agent-dev REGION=us-east-1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --stack) STACK="$2"; shift 2 ;;
    *) echo "argumento desconocido: $1" >&2; exit 2 ;;
  esac
done

aws_() { aws --profile "$PROFILE" --region "$REGION" "$@"; }
CLIENT="$(aws_ cloudformation describe-stacks --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='UserPoolClientId'].OutputValue" --output text)"

TMP="$(mktemp -d)"; chmod 700 "$TMP"; trap 'rm -rf "$TMP"' EXIT
aws_ secretsmanager get-secret-value --secret-id onboarding-agent/test-users --query SecretString --output text \
  >"$TMP/users.json"
python3 -c 'import json,sys; print(json.dumps({"ClientId": sys.argv[1], "AuthFlow": "USER_PASSWORD_AUTH",
  "AuthParameters": {"USERNAME": sys.argv[2], "PASSWORD": json.load(open(sys.argv[3]))[sys.argv[2]]}}))' \
  "$CLIENT" "$USER" "$TMP/users.json" >"$TMP/auth.json"
aws_ cognito-idp initiate-auth --cli-input-json "file://$TMP/auth.json" \
  --query AuthenticationResult.IdToken --output text
