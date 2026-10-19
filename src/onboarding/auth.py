"""Defensa en profundidad para /resolve: exige grupo Cognito `compliance` cuando AUTH_MODE=apigw.

El authorizer JWT de API Gateway ya valida el token; aquí se re-verifica la autorización con los
claims que Mangum expone en `request.scope["aws.event"]`. Fail-closed: AUTH_MODE ausente equivale a
`apigw`; `none` (local/tests) solo se acepta si además ALLOW_INSECURE_LOCAL=1 y nunca dentro de Lambda
(AWS_LAMBDA_FUNCTION_NAME), para que un cambio de variables de entorno no apague el check en AWS.
"""

import os
from dataclasses import dataclass

from fastapi import HTTPException, Request

REQUIRED_GROUP = "compliance"


@dataclass(frozen=True)
class Officer:
    sub: str
    groups: tuple[str, ...]


def _parse_groups(raw: object) -> tuple[str, ...]:
    # HTTP API entrega `cognito:groups` como lista o como string "[g1 g2]" / "g1,g2".
    if isinstance(raw, list | tuple):
        return tuple(str(g) for g in raw)
    if isinstance(raw, str):
        return tuple(g for g in raw.strip("[]").replace(",", " ").split() if g)
    return ()


def _claims(request: Request) -> dict:
    event = request.scope.get("aws.event") or {}
    return (event.get("requestContext") or {}).get("authorizer", {}).get("jwt", {}).get("claims") or {}


def require_compliance(request: Request) -> Officer | None:
    mode = os.getenv("AUTH_MODE", "apigw").strip().lower()
    if mode == "none":
        if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
            raise HTTPException(500, "AUTH_MODE=none no está permitido en Lambda")
        if os.getenv("ALLOW_INSECURE_LOCAL") == "1":
            return None
        raise HTTPException(403, "AUTH_MODE=none requiere ALLOW_INSECURE_LOCAL=1")
    if mode != "apigw":
        raise HTTPException(500, "invalid AUTH_MODE")
    claims = _claims(request)
    groups = _parse_groups(claims.get("cognito:groups"))
    sub = claims.get("sub")
    if not sub or REQUIRED_GROUP not in groups:
        raise HTTPException(403, "se requiere un oficial del grupo compliance")
    return Officer(sub=str(sub), groups=groups)
