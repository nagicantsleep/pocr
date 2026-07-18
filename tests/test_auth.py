"""Focused tests for configured operator identity resolution."""

import pytest
from fastapi import HTTPException

from app.auth import (
    AuthenticatedPrincipal,
    require_document_reviewer,
    require_operator,
)
from app.config import Settings


def _settings(**overrides) -> Settings:
    values = {
        "OPERATOR_ENVIRONMENT": "test",
        "OPERATOR_TOKEN_MAP": {
            "test-token": {
                "tenant_id": "tenant-test",
                "user_id": "operator-test",
                "roles": ["operator", "reviewer"],
            }
        },
        "OPERATOR_BEARER_TOKEN": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_settings_parses_operator_token_map_from_environment(monkeypatch):
    monkeypatch.setenv(
        "OPERATOR_TOKEN_MAP",
        (
            '{"configured-token":{"tenant_id":"tenant-configured",'
            '"user_id":"operator-configured","roles":["operator"]}}'
        ),
    )

    settings = Settings(_env_file=None)

    assert settings.OPERATOR_TOKEN_MAP["configured-token"].tenant_id == "tenant-configured"
    assert settings.OPERATOR_TOKEN_MAP["configured-token"].roles == ("operator",)


@pytest.mark.asyncio
async def test_require_operator_resolves_configured_tenant_principal(monkeypatch):
    monkeypatch.setattr("app.auth.get_settings", lambda: _settings())

    principal = await require_operator("Bearer test-token")

    assert principal == AuthenticatedPrincipal(
        tenant_id="tenant-test",
        user_id="operator-test",
        roles=frozenset({"operator", "reviewer"}),
    )


@pytest.mark.asyncio
async def test_require_operator_rejects_unknown_configured_token(monkeypatch):
    monkeypatch.setattr("app.auth.get_settings", lambda: _settings())

    with pytest.raises(HTTPException, match="Invalid Bearer token") as error:
        await require_operator("Bearer untrusted-token")

    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_production_without_identity_configuration_fails_closed(monkeypatch):
    monkeypatch.setattr(
        "app.auth.get_settings",
        lambda: _settings(OPERATOR_ENVIRONMENT="production", OPERATOR_TOKEN_MAP={}),
    )

    with pytest.raises(HTTPException, match="not configured") as error:
        await require_operator(None)

    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_production_map_requires_a_bearer_token(monkeypatch):
    monkeypatch.setattr(
        "app.auth.get_settings",
        lambda: _settings(OPERATOR_ENVIRONMENT="production"),
    )

    with pytest.raises(HTTPException, match="Missing Bearer token") as error:
        await require_operator(None)

    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_explicit_legacy_token_migration_resolves_configured_principal(monkeypatch):
    legacy_principal = {
        "tenant_id": "tenant-legacy",
        "user_id": "migration-operator",
        "roles": ["operator"],
    }
    monkeypatch.setattr(
        "app.auth.get_settings",
        lambda: _settings(
            OPERATOR_ENVIRONMENT="production",
            OPERATOR_TOKEN_MAP={},
            OPERATOR_BEARER_TOKEN="legacy-token",
            OPERATOR_ALLOW_LEGACY_TOKEN=True,
            OPERATOR_LEGACY_PRINCIPAL=legacy_principal,
        ),
    )

    principal = await require_operator("Bearer legacy-token")

    assert principal == AuthenticatedPrincipal(
        tenant_id="tenant-legacy",
        user_id="migration-operator",
        roles=frozenset({"operator"}),
    )


@pytest.mark.asyncio
async def test_production_does_not_enable_legacy_token_implicitly(monkeypatch):
    monkeypatch.setattr(
        "app.auth.get_settings",
        lambda: _settings(
            OPERATOR_ENVIRONMENT="production",
            OPERATOR_TOKEN_MAP={},
            OPERATOR_BEARER_TOKEN="legacy-token",
        ),
    )

    with pytest.raises(HTTPException, match="not configured") as error:
        await require_operator("Bearer legacy-token")

    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_production_reviewer_dependency_rejects_submitter_only_principal(monkeypatch):
    monkeypatch.setattr(
        "app.auth.get_settings",
        lambda: _settings(
            OPERATOR_ENVIRONMENT="production",
            OPERATOR_TOKEN_MAP={
                "submitter-token": {
                    "tenant_id": "tenant-test",
                    "user_id": "submitter-test",
                    "roles": ["submitter"],
                }
            },
        ),
    )

    principal = await require_operator("Bearer submitter-token")
    with pytest.raises(HTTPException, match="Reviewer role required") as error:
        await require_document_reviewer(principal)

    assert error.value.status_code == 403
