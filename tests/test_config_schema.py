"""Tests for giulia.agents.core.config_schema — AgentYAMLConfig."""

from __future__ import annotations

from giulia.agents.core.config_schema import AgentTier, AgentYAMLConfig


def _config(**overrides: object) -> AgentYAMLConfig:
    defaults: dict = {
        "name": "test-agent",
        "company": "acme",
        "domain": "agents.acme.com",
    }
    defaults.update(overrides)
    return AgentYAMLConfig(**defaults)


class TestUrn:
    def test_private_urn(self) -> None:
        cfg = _config(tier=AgentTier.PRIVATE)
        assert cfg.urn == "urn:agent:acme:private:test-agent"

    def test_public_urn(self) -> None:
        cfg = _config(tier=AgentTier.PUBLIC)
        assert cfg.urn == "urn:agent:acme:public:test-agent"

    def test_company_lowercased_in_urn(self) -> None:
        cfg = _config(company="ACME")
        assert "acme" in cfg.urn


class TestPublicUrl:
    def test_public_url_format(self) -> None:
        cfg = _config()
        assert cfg.public_url == "https://agents.acme.com/agents/test-agent"


class TestPathPrefix:
    def test_path_prefix(self) -> None:
        cfg = _config()
        assert cfg.path_prefix == "/agents/test-agent"


class TestRegistryHandle:
    def test_default_handle(self) -> None:
        cfg = _config(tier=AgentTier.PRIVATE)
        assert cfg.registry_handle == "@acme:private/test-agent"

    def test_explicit_handle_takes_precedence(self) -> None:
        cfg = _config(handle="@custom:handle")
        assert cfg.registry_handle == "@custom:handle"


class TestOwnerDid:
    def test_default_did(self) -> None:
        cfg = _config()
        assert cfg.owner_did == "did:org:acme"

    def test_explicit_owner(self) -> None:
        cfg = _config(owner="did:web:acme.com")
        assert cfg.owner_did == "did:web:acme.com"


class TestRegistrationPayload:
    def test_payload_keys(self) -> None:
        cfg = _config()
        payload = cfg.to_registration_payload()
        for key in (
            "urn",
            "name",
            "handle",
            "owner",
            "company",
            "capabilities",
            "tier",
            "domain",
            "public_url",
        ):
            assert key in payload

    def test_service_url_included_when_given(self) -> None:
        cfg = _config()
        payload = cfg.to_registration_payload(service_url="http://internal.svc:8080")
        assert payload["k8s_service_url"] == "http://internal.svc:8080"

    def test_service_url_absent_when_not_given(self) -> None:
        cfg = _config()
        payload = cfg.to_registration_payload()
        assert "k8s_service_url" not in payload
