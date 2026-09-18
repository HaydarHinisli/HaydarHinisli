"""FastAPI auth/RBAC dependencies.

get_current_user() verifies the bearer JWT and loads the User; require_role(...)
wraps it with a role check that system_admin always satisfies (cross-tenant
superuser). resolve_tenant_id() is the one place that decides which company_id an
endpoint acts on — it is the enforcement point that stops a normal user from ever
reading or writing another tenant's data by guessing/passing a different company_id.
"""
from __future__ import annotations
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from .security import decode_access_token

ROLES = ('seller', 'manager', 'tenant_admin', 'compliance_admin', 'system_admin')

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    user_id: int
    company_id: int | None
    role: str
    email: str


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> AuthContext:
    if credentials is None:
        raise HTTPException(401, 'Missing bearer token')
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, 'Token expired')
    except jwt.InvalidTokenError:
        raise HTTPException(401, 'Invalid token')
    user = db.get(User, int(payload['sub']))
    if user is None:
        raise HTTPException(401, 'User not found')
    if not user.is_active:
        raise HTTPException(403, 'Account is disabled')
    ctx = AuthContext(user_id=user.id, company_id=user.company_id, role=user.role, email=user.email)
    # Consumed by the structured-logging middleware in app/logging_config.py.
    # request.state persists for the lifetime of this Request regardless of where
    # it is set, so the access-log line written after the endpoint returns can
    # still read it even though it's set here, inside a dependency.
    request.state.user_id = ctx.user_id
    request.state.company_id = ctx.company_id
    request.state.role = ctx.role
    return ctx


def require_role(*roles: str):
    allowed = set(roles)

    def _dependency(current_user: AuthContext = Depends(get_current_user)) -> AuthContext:
        if current_user.role == 'system_admin':
            return current_user
        if current_user.role not in allowed:
            raise HTTPException(
                403,
                f'Role "{current_user.role}" is not permitted for this action (requires one of {sorted(allowed)}).',
            )
        return current_user

    return _dependency


def resolve_tenant_id(current_user: AuthContext, requested_company_id: int | None = None) -> int:
    if current_user.role == 'system_admin':
        if requested_company_id is None:
            raise HTTPException(400, 'system_admin must specify company_id explicitly for tenant-scoped actions.')
        return requested_company_id
    if requested_company_id is not None and requested_company_id != current_user.company_id:
        raise HTTPException(403, 'Cannot act on a different tenant.')
    if current_user.company_id is None:
        raise HTTPException(403, 'User has no tenant assigned.')
    return current_user.company_id
