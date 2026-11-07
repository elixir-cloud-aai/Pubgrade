"""Tests for the character sets of identifiers and access tokens."""

from pathlib import Path
import string
from typing import Any

import pytest
import yaml

from pubgrade.charsets import CharsetError, check_charsets, resolve_charset
from tests.mock_data import ENDPOINT_CONFIG

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = "".join(sorted(string.ascii_lowercase + string.digits + ".-"))


@pytest.mark.parametrize(
    "value",
    [
        # As in the image's configuration (`pubgrade/config.yaml`)
        ["string.ascii_lowercase", "string.digits", ".", "-"],
        [" string.ascii_lowercase", "string.digits ", "'.'", '"-"'],
        "string.ascii_lowercase + string.digits + '.' + '-'",
        "string.ascii_lowercase+string.digits+'.-'",
    ],
)
def test_resolve_named_and_literal(value: Any) -> None:
    """Names of character sets and literal characters combine.

    Args:
        value: Value of the setting.
    """
    assert resolve_charset(value) == DEFAULT


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("string.digits + 'a'", "0123456789a"),
        ("string.ascii_uppercase", string.ascii_uppercase),
        ("abca", "abc"),
        ("A", "A"),
        ("a_b", "ab"),
        (["abc", "b"], "abc"),
        (["string.hexdigits"], "".join(sorted(set(string.hexdigits)))),
        (["string.ascii_letters"], "".join(sorted(string.ascii_letters))),
        ("a+b", "+ab"),
    ],
)
def test_resolve(value: Any, expected: str) -> None:
    """Each character once, sorted, without `_`.

    Args:
        value: Value of the setting.
        expected: Characters it names.
    """
    assert resolve_charset(value) == expected


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("string.punctuation", "unknown character set 'string.punctuation'"),
        (["string.letters"], "unknown character set 'string.letters'"),
        ("string.digits + string.foo", "unknown character set"),
        (12, "expected a string or a list of strings, got int"),
        (["a", 1], "expected a string or a list of strings, got list"),
        (None, "got NoneType"),
        ("", "needs at least one character"),
        ([], "needs at least one character"),
        ("string.digits", "needs at least one character"),
        (["_", ".", "-", "0"], "needs at least one character"),
    ],
)
def test_resolve_errors(value: Any, message: str) -> None:
    """Values that can't be used fail with an error naming the setting.

    Args:
        value: Value of the setting.
        message: Part of the error message.
    """
    with pytest.raises(CharsetError, match="^endpoints.user.uid_charset: ") as error:
        resolve_charset(value, "endpoints.user.uid_charset")
    assert message in str(error.value)


def test_quoted_literal_with_bad_escape() -> None:
    """A quoted item that isn't a valid string literal counts as characters."""
    assert resolve_charset(["'\\N'"]) == "'N\\"


def test_check_charsets_default_config() -> None:
    """The image's configuration passes, with the intended characters."""
    config = yaml.safe_load((ROOT / "pubgrade" / "config.yaml").read_text())
    endpoints = config["endpoints"]
    check_charsets(endpoints)
    assert resolve_charset(endpoints["access_token"]["charset"]) == DEFAULT
    assert resolve_charset(endpoints["repository"]["id_charset"]) == DEFAULT
    assert resolve_charset(endpoints["user"]["uid_charset"]) == DEFAULT


def test_check_charsets_mock_config() -> None:
    """The tests' configuration passes."""
    check_charsets(ENDPOINT_CONFIG)


@pytest.mark.parametrize(
    ("endpoints", "message"),
    [
        ({}, "endpoints.repository.id_charset: missing"),
        (
            {**ENDPOINT_CONFIG, "user": {"uid_charset": "string.unknown"}},
            "endpoints.user.uid_charset: unknown",
        ),
        (
            {**ENDPOINT_CONFIG, "access_token": None},
            "endpoints.access_token.charset: missing",
        ),
    ],
)
def test_check_charsets_errors(endpoints: dict[str, Any], message: str) -> None:
    """Missing and unusable settings fail.

    Args:
        endpoints: Section `endpoints` of the configuration.
        message: Start of the error message.
    """
    with pytest.raises(CharsetError, match=f"^{message}"):
        check_charsets(endpoints)
