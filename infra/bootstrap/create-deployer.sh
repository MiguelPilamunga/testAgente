#!/usr/bin/env bash
# Bootstrap IAM (una sola vez, con credenciales de administrador): crea el permissions boundary
# `onboarding-agent-boundary` y el usuario `onboarding-deployer` con la política acotada de deployer-policy.json y configura el perfil local `onboarding-deployer`.
# El secret de la access key va directo a ~/.aws/credentials: nunca se imprime ni se escribe en el repo.
# Uso: ADMIN_PROFILE=default [STAGE=dev] infra/bootstrap/create-deployer.sh   (re-ejecutable: actualiza políticas y rol)
set -euo pipefail

ADMIN_PROFILE="${ADMIN_PROFILE:-default}"
USER_NAME="onboarding-deployer"
DEPLOY_PROFILE="onboarding-deployer"
REGION="us-east-1"
ACCOUNT="774305616818"
STAGE="${STAGE:-dev}"
POLICY="$(cd "$(dirname "$0")" && pwd)/deployer-policy.json"
IAM_POLICY="$(cd "$(dirname "$0")" && pwd)/deployer-iam-policy.json"
BOUNDARY="$(cd "$(dirname "$0")" && pwd)/boundary-policy.json"

admin() { aws --profile "$ADMIN_PROFILE" --region "$REGION" "$@"; }

actual="$(admin sts get-caller-identity --query Account --output text)"
[[ "$actual" == "$ACCOUNT" ]] || { echo "cuenta $actual != $ACCOUNT, abortando" >&2; exit 1; }

if admin iam get-user --user-name "$USER_NAME" >/dev/null 2>&1; then
  echo "usuario $USER_NAME ya existe"
else
  admin iam create-user --user-name "$USER_NAME" --tags Key=project,Value=onboarding-agent >/dev/null
  echo "usuario $USER_NAME creado"
fi

upsert_policy() { # nombre archivo descripción — crea la política administrada o publica una nueva versión default
  local arn="arn:aws:iam::$ACCOUNT:policy/$1"
  if admin iam get-policy --policy-arn "$arn" >/dev/null 2>&1; then
    # Máximo 5 versiones: borra la más antigua no default antes de publicar la nueva.
    local versions
    versions="$(admin iam list-policy-versions --policy-arn "$arn" \
      --query 'Versions[?IsDefaultVersion==`false`].VersionId' --output text)"
    if [[ $(wc -w <<<"$versions") -ge 4 ]]; then
      admin iam delete-policy-version --policy-arn "$arn" --version-id "$(tr '\t' '\n' <<<"$versions" | sort -V | head -1)"
    fi
    admin iam create-policy-version --policy-arn "$arn" --set-as-default --policy-document "file://$2" >/dev/null
    echo "política $1 actualizada"
  else
    admin iam create-policy --policy-name "$1" --policy-document "file://$2" --description "$3" >/dev/null
    echo "política $1 creada"
  fi
}

# Permissions boundary obligatorio para todo rol que cree el deployer (ver docs/adr/0007-iam-deployer-boundary.md).
upsert_policy onboarding-agent-boundary "$BOUNDARY" "Permissions boundary de los roles de onboarding-agent-*"
# Rol de ejecución de la Lambda, pre-creado aquí (el deployer NO puede crear ni modificar roles: ADR-0007).
# Trust solo lambda.amazonaws.com de esta cuenta; boundary + permisos mínimos del stage.
ROLE_NAME="onboarding-agent-$STAGE-function-role"
DIR="$(cd "$(dirname "$0")" && pwd)"
if admin iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  admin iam update-assume-role-policy --role-name "$ROLE_NAME" --policy-document "file://$DIR/function-role-trust.json"
  echo "rol $ROLE_NAME ya existe (trust actualizado)"
else
  admin iam create-role --role-name "$ROLE_NAME" --assume-role-policy-document "file://$DIR/function-role-trust.json" \
    --permissions-boundary "arn:aws:iam::$ACCOUNT:policy/onboarding-agent-boundary" \
    --tags Key=project,Value=onboarding-agent --description "Ejecución de la Lambda onboarding-agent-$STAGE" >/dev/null
  echo "rol $ROLE_NAME creado"
fi
admin iam put-role-permissions-boundary --role-name "$ROLE_NAME" \
  --permissions-boundary "arn:aws:iam::$ACCOUNT:policy/onboarding-agent-boundary"
sed "s/STAGE/$STAGE/g" "$DIR/function-role-policy.json" >"$DIR/.function-role-policy.$STAGE.json"
admin iam put-role-policy --role-name "$ROLE_NAME" --policy-name function \
  --policy-document "file://$DIR/.function-role-policy.$STAGE.json"
rm -f "$DIR/.function-role-policy.$STAGE.json"
echo "rol $ROLE_NAME: arn:aws:iam::$ACCOUNT:role/$ROLE_NAME (parámetro FunctionRoleArn)"

# Administradas (no inline: las inline de usuario están limitadas a 2048 bytes), partidas por el límite de 6144:
# recursos del stack | controles IAM (boundary obligatorio, PassRole, denies).
upsert_policy onboarding-agent-deployer "$POLICY" "Despliegue SAM de onboarding-agent-* (recursos)"
upsert_policy onboarding-agent-deployer-iam "$IAM_POLICY" "Despliegue SAM de onboarding-agent-* (IAM con boundary y denies)"
for pol in onboarding-agent-deployer onboarding-agent-deployer-iam; do
  admin iam attach-user-policy --user-name "$USER_NAME" --policy-arn "arn:aws:iam::$ACCOUNT:policy/$pol"
done
echo "políticas onboarding-agent-deployer{,-iam} adjuntas a $USER_NAME"

if aws configure get aws_access_key_id --profile "$DEPLOY_PROFILE" >/dev/null 2>&1; then
  echo "perfil $DEPLOY_PROFILE ya configurado; no se crea otra access key"
else
  # La key se lee de stdout del CLI directo a `aws configure set` (no pasa por la terminal ni por el repo).
  key_json="$(admin iam create-access-key --user-name "$USER_NAME" --output json)"
  aws configure set aws_access_key_id "$(jq -r .AccessKey.AccessKeyId <<<"$key_json")" --profile "$DEPLOY_PROFILE"
  aws configure set aws_secret_access_key "$(jq -r .AccessKey.SecretAccessKey <<<"$key_json")" --profile "$DEPLOY_PROFILE"
  unset key_json
  echo "access key creada y guardada en el perfil $DEPLOY_PROFILE"
fi
aws configure set region "$REGION" --profile "$DEPLOY_PROFILE"

# Propagación de IAM: reintenta hasta que el nuevo perfil responda.
for _ in 1 2 3 4 5 6; do
  aws --profile "$DEPLOY_PROFILE" sts get-caller-identity --query Arn --output text 2>/dev/null && exit 0
  sleep 5
done
echo "el perfil $DEPLOY_PROFILE aún no responde (propagación IAM); reintentar en unos segundos" >&2
exit 1
