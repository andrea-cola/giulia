"""Tests for giulia.agents.utils.urn — URN/slug helpers."""

from __future__ import annotations

from giulia.agents.utils.urn import urn_to_python_identifier, urn_to_slug
from hypothesis import given
from hypothesis import strategies as st


class TestUrnToSlug:
    def test_standard_urn(self) -> None:
        assert urn_to_slug("urn:agent:giulia:public:sophia") == "sophia"

    def test_internal_with_hyphen(self) -> None:
        assert urn_to_slug("urn:agent:giulia:internal:crm-connector") == "crm-connector"

    def test_plain_id_no_colon(self) -> None:
        assert urn_to_slug("my-agent") == "my-agent"

    def test_slash_in_plain_id(self) -> None:
        assert urn_to_slug("acme/tool") == "acme-tool"

    def test_strips_whitespace(self) -> None:
        assert urn_to_slug("  urn:agent:x:y:z  ") == "z"

    def test_returns_lowercase(self) -> None:
        assert urn_to_slug("urn:agent:acme:public:MyAgent") == "myagent"

    @given(st.text(min_size=1, alphabet=st.characters(blacklist_categories=("Cs",))))
    def test_never_raises(self, agent_id: str) -> None:
        result = urn_to_slug(agent_id)
        assert isinstance(result, str)


class TestUrnToPythonIdentifier:
    def test_hyphen_replaced(self) -> None:
        assert (
            urn_to_python_identifier("urn:agent:giulia:public:supplier-scouting")
            == "supplier_scouting"
        )

    def test_no_hyphen(self) -> None:
        assert urn_to_python_identifier("urn:agent:giulia:public:sophia") == "sophia"

    def test_plain_id(self) -> None:
        assert urn_to_python_identifier("myplugin") == "myplugin"

    @given(st.text(min_size=1, alphabet=st.characters(blacklist_categories=("Cs",))))
    def test_never_raises(self, agent_id: str) -> None:
        result = urn_to_python_identifier(agent_id)
        assert isinstance(result, str)
