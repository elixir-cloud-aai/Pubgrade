"""Tests for the comparison of access tokens."""

import ast
from pathlib import Path
from unittest.mock import patch

import pytest

from pubgrade import tokens
from pubgrade.tokens import tokens_match

ENDPOINTS = Path(__file__).parents[1] / "pubgrade" / "modules" / "endpoints"


def test_tokens_match() -> None:
    """Equal tokens match."""
    assert tokens_match("abc.def-1", "abc.def-1")


@pytest.mark.parametrize(
    "supplied",
    ["abc.def-2", "abc.def-", "abc.def-12", "", "ABC.DEF-1"],
)
def test_tokens_differ(supplied: str) -> None:
    """Other tokens, also prefixes and longer ones, don't match.

    Args:
        supplied: Token of the request.
    """
    assert not tokens_match(supplied, "abc.def-1")


@pytest.mark.parametrize(
    ("supplied", "stored"),
    [(None, "abc"), ("abc", None), (None, None), ("", "")],
)
def test_missing_tokens_never_match(supplied: str | None, stored: str | None) -> None:
    """A missing or empty token matches nothing, not even another one.

    Args:
        supplied: Token of the request, if any.
        stored: Stored token, if any.
    """
    assert not tokens_match(supplied, stored)


@pytest.mark.parametrize("stored", [123456, 1.5, True, ["abc"]])
def test_tokens_that_are_not_strings_never_match(stored: object) -> None:
    """Stored values that aren't strings (e.g., unquoted in YAML) match none.

    Args:
        stored: Stored value.
    """
    assert not tokens_match(str(stored), stored)
    assert not tokens_match(stored, str(stored))


def test_non_ascii_tokens() -> None:
    """Tokens with characters outside ASCII are compared, not rejected."""
    assert tokens_match("tökén", "tökén")
    assert not tokens_match("tökén", "token")


def test_tokens_compared_with_compare_digest() -> None:
    """The comparison is delegated to `hmac.compare_digest`.

    This checks the delegation only, not the timing itself, which is
    `compare_digest`'s.
    """
    with patch.object(tokens.hmac, "compare_digest", return_value=True) as compare:
        assert tokens_match("a", "b")
    compare.assert_called_once_with(b"a", b"b")


def test_endpoints_compare_no_tokens_directly() -> None:
    """No endpoint compares a token with `==` or `!=`.

    A comparison counts as one of tokens if its source names a token, as
    the stored fields and the arguments of the endpoints do
    (`access_token`, `user_access_token`, ...).
    """
    for module in ENDPOINTS.glob("*.py"):
        for node in ast.walk(ast.parse(module.read_text())):
            if not isinstance(node, ast.Compare):
                continue
            if not any(isinstance(op, ast.Eq | ast.NotEq) for op in node.ops):
                continue
            source = ast.unparse(node)
            assert "token" not in source, f"{module.name}:{node.lineno}: {source}"
