"""Authentication helpers."""

import secrets
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException

from app.config import OperatorTokenIdentity, get_settings


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """Trusted identity resolved from server configuration, never request headers."""

    tenant_id: str
    user_id: str
    roles: frozenset[str]

    @classmethod
    def from_identity(cls, identity: OperatorTokenIdentity) -> "AuthenticatedPrincipal":
        return cls(
            tenant_id=identity.tenant_id,
            user_id=identity.user_id,
            roles=frozenset(identity.roles),
        )


_DEVELOPMENT_PRINCIPAL = AuthenticatedPrincipal(
    tenant_id="development",
    user_id="anonymous",
    roles=frozenset(),
)


async def verify_api_key(
    x_api_key: str | None = Header(None, description="API key for authentication"),
):
    """Verify API key if configured."""
    settings = get_settings()
    if settings.API_KEY:
        if not x_api_key:
            raise HTTPException(status_code=401, detail="Missing API key")
        if not secrets.compare_digest(x_api_key, settings.API_KEY):
            raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key


async def require_operator(
    authorization: str | None = Header(None, description="Bearer token for operator endpoints"),
) -> AuthenticatedPrincipal:
    """Resolve a configured operator token to a tenant-scoped principal.

    `OPERATOR_TOKEN_MAP` is the production identity source. The legacy
    `OPERATOR_BEARER_TOKEN` fallback remains only for a transition: configure the
    map with the old token's claims, migrate callers, then remove the fallback.
    Production accepts that fallback only with OPERATOR_ALLOW_LEGACY_TOKEN=true.
    """
    settings = get_settings()
    configured_tokens = settings.OPERATOR_TOKEN_MAP
    if not configured_tokens and not settings.legacy_operator_token_enabled:
        if settings.is_production:
            raise HTTPException(
                status_code=503,
                detail="Operator authentication is not configured",
            )
        return _DEVELOPMENT_PRINCIPAL

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    for configured_token, identity in configured_tokens.items():
        if secrets.compare_digest(token, configured_token):
            return AuthenticatedPrincipal.from_identity(identity)

    if (
        settings.legacy_operator_token_enabled
        and secrets.compare_digest(token, settings.OPERATOR_BEARER_TOKEN or "")
    ):
        return AuthenticatedPrincipal.from_identity(settings.OPERATOR_LEGACY_PRINCIPAL)

    raise HTTPException(status_code=401, detail="Invalid Bearer token")


async def require_document_reviewer(
    principal: AuthenticatedPrincipal = Depends(require_operator),
) -> AuthenticatedPrincipal:
    """Require a reviewer-capable role for document mutations in production."""
    if not get_settings().is_production:
        return principal
    if {"admin", "operator", "reviewer"} & principal.roles:
        return principal
    raise HTTPException(status_code=403, detail="Reviewer role required")
