# ADR-0007 — Usuario IAM `onboarding-deployer` acotado por permissions boundary

- **Estado:** Aceptado · 2026-10-19 · Cuenta 774305616818 (compartida con otros proyectos), us-east-1

## Contexto
Nunca se despliega con root. Una primera política del deployer permitía `iam:CreateRole`/`AttachRolePolicy`/
`PutRolePolicy`/`PassRole` sobre `role/onboarding-agent-*` sin condiciones junto con `lambda:*`. Eso es una escalada a
admin: crear un rol con `AdministratorAccess`, pasarlo a una Lambda e invocarla da control de toda la cuenta
(hallazgo HIGH de la revisión).

## Decisión
- **Bootstrap con root, solo una vez** (`infra/bootstrap/create-deployer.sh`). Crea la política administrada
  `onboarding-agent-boundary` y el usuario `onboarding-deployer` con política inline (`deployer-policy.json`).
  La access key va directo a `~/.aws/credentials` (perfil `onboarding-deployer`), nunca a stdout ni al repo.
- **Boundary** (`boundary-policy.json`), el techo de cualquier rol del proyecto:
  - logs solo de `/aws/lambda/onboarding-agent-*`;
  - DynamoDB solo a nivel de ítem en `table/onboarding-agent-*`;
  - `GetSecretValue` solo en `onboarding-agent/llm-keys-*` (la Lambda no puede leer `test-users`);
  - X-Ray.
- **Política del deployer:**
  - `CreateRole`, `PutRolePolicy`, `DeleteRolePolicy`, `Attach/DetachRolePolicy` exigen
    `iam:PermissionsBoundary = onboarding-agent-boundary`.
  - `AttachRolePolicy` solo admite `AWSLambdaBasicExecutionRole` y `AWSXRayDaemonWriteAccess`.
  - `PassRole` solo a `lambda.amazonaws.com` y solo sobre `role/onboarding-agent-*`.
  - Deny explícito de quitar o cambiar el boundary, de modificar o borrar la política boundary, y de
    `CreateUser`/`AttachUserPolicy`/`PutUserPolicy`/`CreateAccessKey`/`CreateLoginProfile`/`UpdateAssumeRolePolicy`.
  - El resto se acota por prefijo de nombre `onboarding-agent-*` (stacks, funciones, tablas, log groups, alarmas,
    dashboard, tópico SNS, secretos) y por el bucket gestionado de SAM.
- **Plantilla:** `Globals.Function.PermissionsBoundary` y nombres `${AWS::StackName}-*` (stack `onboarding-agent-<stage>`).
- Validación: `aws accessanalyzer validate-policy --policy-type IDENTITY_POLICY`: 0 hallazgos de seguridad (ver nota sobre `apigateway:TagResource`).

## Acotación por tag `project=onboarding-agent` (v2, revisión de skills)
- **Cognito:** `CreateUserPool` exige `aws:RequestTag/project`. Las acciones sobre `userpool/*` son una lista
  explícita: el pool y su MFA, client, group, tags y `AdminGetUser/AdminCreateUser/AdminSetUserPassword/
  AdminAdd|RemoveUserFromGroup`, y exigen `aws:ResourceTag/project`. La primera versión de este ADR afirmaba que
  Cognito no soporta tags; era **incorrecto**. La Service Authorization Reference los declara en `userpool`.
  Access Analyzer solo emitía una sugerencia y la condición funciona en tiempo de ejecución.
- **API Gateway (HTTP API):**
  - `POST /apis` exige `aws:RequestTag`. `GET`/`PUT /apis` (listar e `ImportApi`, que usa SAM) van sin condición:
    `PUT /apis` solo crea APIs nuevas.
  - Las operaciones sobre `/apis/*` y `/tags/*` exigen `aws:ResourceTag`.
  - `apigateway:TagResource` exige `aws:RequestTag`, porque el stage nace sin tag.
  - Access Analyzer marca `apigateway:TagResource` como `INVALID_ACTION`, pero CloudFormation (ApiGatewayV2) lo
    evalúa en tiempo de ejecución.
- **Lambda:** Deny de Function URLs y de `AddPermission` con `lambda:Principal` distinto de `apigateway.amazonaws.com`.
- **Políticas:** el límite de 6144 caracteres obliga a partir la política en `onboarding-agent-deployer` (recursos)
  y `onboarding-agent-deployer-iam` (roles con boundary, PassRole, denies). Ambas están protegidas por el Deny de
  versionado.
- **Política de roles:** SAM adjunta `AWSXrayWriteOnlyAccess` (no `AWSXRayDaemonWriteAccess`) cuando hay
  `Tracing: Active`.

## Riesgos residuales (aceptados)
- **Trust policy de `CreateRole`:** no se puede acotar por condición. Cualquier rol creado queda limitado por el
  boundary, pero su trust podría admitir principales externos. Se propone activar IAM Access Analyzer de acceso
  externo; **no se activó** porque es un cambio de la cuenta compartida y lo decide el usuario.
- **`logs:CreateLogDelivery`/`PutResourcePolicy`:** no tienen nivel de recurso; los requieren los access logs de la HTTP API.
- **Bucket gestionado de SAM:** `s3:*` sobre `aws-sam-cli-managed-default-*`, que incluye su bucket policy; es
  compartido con otros stacks SAM de la región.
- **Access key de larga duración** del deployer: **borrarla al terminar la evaluación**
  (`aws iam delete-access-key` con root) o rotarla.
- `DeletionPolicy: Retain` en la tabla: un create fallido deja la tabla huérfana y hay que borrarla antes de reintentar.
- Una Lambda del proyecto puede ejecutar código arbitrario, pero dentro del boundary; no puede escalar.

## Consecuencias
- ✅ El deployer no puede llegar a admin ni crear identidades nuevas; root se usa solo para el bootstrap.
- ⚠️ Añadir permisos a la Lambda exige ampliar primero el boundary (re-ejecutar el bootstrap con root).
