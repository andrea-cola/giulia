"""Tests for giulia.agents.auth.token_mint — JWT minting logic.

These tests use a lightweight HMAC-based stub to avoid a real KMS dependency.
The KMS provider is patched via the giulia provider registry.
"""

from __future__ import annotations

from unittest.mock import patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stub_token(payload: dict) -> str:
    """Produce a minimal dot-separated stub token (not a real JWT)."""
    import base64
    import json

    def b64(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    header = b64({"alg": "RS256", "typ": "JWT"})
    body = b64(payload)
    return f"{header}.{body}.fakesig"


# ---------------------------------------------------------------------------
# Tests for mint_token claim construction
# ---------------------------------------------------------------------------


class TestMintTokenClaims:
    """Verify the claim construction inside mint_token without a real KMS."""

    def _captured_payload(
        self,
        *,
        sub: str = "client-1",
        client_name: str = "test",
        scopes: list[str] | None = None,
        audience: str | None = None,
        ttl: int = 60,
        max_ttl: int = 300,
        delegation_chain: list[str] | None = None,
    ) -> dict:
        """Call mint_token with a sign_jwt stub that captures the payload."""
        captured: dict = {}

        def fake_sign(payload: dict, **_kwargs: object) -> str:
            captured.update(payload)
            return _make_stub_token(payload)

        with patch("giulia.agents.auth.token_mint.sign_jwt", side_effect=fake_sign):
            from giulia.agents.auth.token_mint import mint_token

            mint_token(
                sub=sub,
                client_name=client_name,
                scopes=scopes or ["agent:invoke"],
                audience=audience,
                ttl=ttl,
                max_ttl=max_ttl,
                delegation_chain=delegation_chain,
            )

        return captured

    def test_sub_claim(self) -> None:
        payload = self._captured_payload(sub="my-client")
        assert payload["sub"] == "my-client"

    def test_scope_joined(self) -> None:
        payload = self._captured_payload(scopes=["agent:invoke", "agent:read"])
        assert payload["scope"] == "agent:invoke agent:read"

    def test_audience_present_when_given(self) -> None:
        payload = self._captured_payload(audience="urn:agent:acme:public:sophia")
        assert payload["aud"] == "urn:agent:acme:public:sophia"

    def test_audience_absent_when_not_given(self) -> None:
        payload = self._captured_payload(audience=None)
        assert "aud" not in payload

    def test_ttl_capped_by_max(self) -> None:
        with patch("giulia.agents.auth.token_mint.sign_jwt", return_value="tok"):
            from giulia.agents.auth.token_mint import mint_token

            _token, expires_in = mint_token(
                sub="x",
                client_name="x",
                scopes=["agent:invoke"],
                ttl=9999,
                max_ttl=120,
            )
        assert expires_in == 120

    def test_ttl_respected_when_below_max(self) -> None:
        with patch("giulia.agents.auth.token_mint.sign_jwt", return_value="tok"):
            from giulia.agents.auth.token_mint import mint_token

            _token, expires_in = mint_token(
                sub="x",
                client_name="x",
                scopes=["agent:invoke"],
                ttl=30,
                max_ttl=300,
            )
        assert expires_in == 30

    def test_delegation_chain_included(self) -> None:
        payload = self._captured_payload(delegation_chain=["agent-a", "agent-b"])
        assert payload["delegation_chain"] == ["agent-a", "agent-b"]

    def test_no_delegation_chain_when_absent(self) -> None:
        payload = self._captured_payload(delegation_chain=None)
        assert "delegation_chain" not in payload

    def test_jti_present_and_unique(self) -> None:
        p1 = self._captured_payload()
        p2 = self._captured_payload()
        assert "jti" in p1
        assert p1["jti"] != p2["jti"]

    def test_exp_after_iat(self) -> None:
        payload = self._captured_payload(ttl=60)
        assert payload["exp"] > payload["iat"]
        assert payload["exp"] - payload["iat"] == 60


class TestMintExchangedToken:
    """Tests for the RFC 8693 token-exchange helper."""

    def _exchange(
        self,
        original: dict,
        new_audience: str = "urn:agent:acme:public:target",
        acting_as: str = "urn:agent:acme:internal:broker",
    ) -> dict:
        captured: dict = {}

        def fake_sign(payload: dict, **_kwargs: object) -> str:
            captured.update(payload)
            return _make_stub_token(payload)

        with patch("giulia.agents.auth.token_mint.sign_jwt", side_effect=fake_sign):
            from giulia.agents.auth.token_mint import mint_exchanged_token

            mint_exchanged_token(
                original_payload=original,
                new_audience=new_audience,
                acting_as=acting_as,
            )

        return captured

    def test_preserves_original_sub(self) -> None:
        payload = self._exchange({"sub": "original-client", "scope": "agent:invoke"})
        assert payload["sub"] == "original-client"

    def test_extends_empty_delegation_chain(self) -> None:
        payload = self._exchange({"sub": "root", "scope": "agent:invoke"})
        assert payload["delegation_chain"] == ["root", "urn:agent:acme:internal:broker"]

    def test_extends_existing_delegation_chain(self) -> None:
        payload = self._exchange(
            {
                "sub": "root",
                "scope": "agent:invoke",
                "delegation_chain": ["root", "hop-1"],
            }
        )
        assert payload["delegation_chain"] == [
            "root",
            "hop-1",
            "urn:agent:acme:internal:broker",
        ]

    def test_new_audience_set(self) -> None:
        payload = self._exchange(
            {"sub": "root", "scope": "agent:invoke"},
            new_audience="urn:agent:acme:public:target",
        )
        assert payload["aud"] == "urn:agent:acme:public:target"
