"""Tests for the character sets of identifiers and access tokens."""

from pathlib import Path
import string
from typing import Any

import pytest
import yaml

from flask import Flask
from foca.models.config import Config

from pubgrade.charsets import (
    CharsetError,
    check_charsets,
    get_charset,
    resolve_charset,
)
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
        "[ '.' , '-', string.ascii_lowercase, string.digits]",
        "[string.ascii_lowercase,string.digits,'.-']",
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
        ("AB", "AB"),
        (["abc", "b"], "abc"),
        (["string.hexdigits"], "".join(sorted(set(string.hexdigits)))),
        (["string.ascii_letters"], "".join(sorted(string.ascii_letters))),
        ("'abcdef'", "abcdef"),
        ('"abc"', "abc"),
        ("~a", "a~"),
        ("['ab']", "ab"),
    ],
)
def test_resolve(value: Any, expected: str) -> None:
    """Each character once, sorted.

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
        ("string.digits + abc", "can't read"),
        ("string.digits abc", "can't read"),
        ("[string.ascii_lowercase + string.digits]", "can't read"),
        ("a+b", "characters '+' not allowed"),
        ("'.' + '+' + 'a'", "characters '+' not allowed"),
        ("a b", "characters ' ' not allowed"),
        (["string.digits", "a b"], "characters ' ' not allowed"),
        (["/?#a"], "characters '#/?' not allowed"),
        (["'\\N'"], "not allowed"),
        ("[]", "characters '[]' not allowed"),
        ("+", "characters '+' not allowed"),
        (12, "expected a string or a list of strings, got int"),
        (["a", 1], "expected a string or a list of strings, got list"),
        (None, "got NoneType"),
        ("", "needs at least two characters"),
        ([], "needs at least two characters"),
        ("a", "needs at least two characters"),
        (["a", "a"], "needs at least two characters"),
        ("string.digits", "needs at least one character"),
        ([".", "-", "0"], "needs at least one character"),
        ("a_b", "characters '_' not allowed"),
        ("'a' 'b'", "not allowed"),
        # Names in quotes, or misspelt
        ("'string.digits'", "unknown character set 'string.digits'"),
        ("['string.digits']", "unknown character set 'string.digits'"),
        (["'string.digits'"], "unknown character set 'string.digits'"),
        (["xstring.digits"], "unknown character set"),
        ("ascii_lowercase", "can't read"),
        (["ascii_lowercase"], "unknown character set"),
        ("String.digits", "can't read"),
        ("strings.digits", "can't read"),
        ("[string.digits, '.', '-', abc]", "listed in brackets"),
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
        (
            {**ENDPOINT_CONFIG, "repository": {"id_charset": "string.ascii_letters"}},
            "endpoints.repository.id_charset: characters 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'",
        ),
        (
            {**ENDPOINT_CONFIG, "repository": {"id_charset": "ab~"}},
            "endpoints.repository.id_charset: characters '~' not allowed",
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


def test_get_charset() -> None:
    """The app's settings are read from its configuration."""
    app = Flask(__name__)
    app.config.foca = Config(endpoints={"user": {"uid_charset": "string.digits+'x'"}})
    with app.app_context():
        assert get_charset("user", "uid_charset") == "0123456789x"


def test_get_charset_repository() -> None:
    """Repository identifiers take lowercase letters, digits, `.` and `-` only."""
    app = Flask(__name__)
    app.config.foca = Config(endpoints={"repository": {"id_charset": "AB"}})
    with app.app_context(), pytest.raises(CharsetError, match="'AB' not allowed"):
        get_charset("repository", "id_charset")
