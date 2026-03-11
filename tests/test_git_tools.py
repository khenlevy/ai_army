"""Tests for agent git identity helpers."""

from ai_army.tools.git_tools import build_agent_identity


def test_build_agent_identity_uses_slug_and_domain():
    """Agent git identity should use a slugified name and configured domain."""
    git_name, git_email = build_agent_identity("Product Manager")

    assert git_name == "product-manager"
    assert git_email == "product-manager@khenlevy.com"


def test_build_agent_identity_handles_symbols():
    """Non-alphanumeric characters should collapse to dashes."""
    git_name, git_email = build_agent_identity("Front-end Developer")

    assert git_name == "front-end-developer"
    assert git_email == "front-end-developer@khenlevy.com"
