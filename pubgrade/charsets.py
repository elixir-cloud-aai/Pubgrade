"""Character sets of generated identifiers and access tokens.

The settings `endpoints.repository.id_charset`, `endpoints.user.uid_charset`
and `endpoints.access_token.charset` name the characters that generated
identifiers and access tokens consist of, as one of:

- a list, whose items are names of character sets (`NAMED`, e.g.,
  `string.digits`, without quotes) or literal characters, optionally in
  quotes (e.g., `'.'`, `-`, `abc`);
- a string with such items joined by `+`, literal characters in quotes (e.g.,
  `string.ascii_lowercase + string.digits + '.' + '-'`), or written as a list
  (e.g., `[string.digits, '.', '-']`);
- a single name (e.g., `string.digits`) or quoted string (e.g., `'abc'`);
- any other string, as literal characters (e.g., `abcdef`).

Literal characters are ASCII letters, digits, `.`, `-` and `~`, which URLs
take as they are; repository identifiers, which also name Kubernetes
resources of builds, only lowercase letters, digits, `.` and `-`. Each
setting needs at least two characters.
The app checks the settings at start (`check_charsets()`), so that a mistake
stops it with an error instead of failing requests.
"""

from __future__ import annotations

from collections.abc import Mapping
import re
import string
from typing import Any

from foca import get_config

# Character sets that the settings may name
NAMED: dict[str, str] = {
    "string.ascii_letters": string.ascii_letters,
    "string.ascii_lowercase": string.ascii_lowercase,
    "string.ascii_uppercase": string.ascii_uppercase,
    "string.digits": string.digits,
    "string.hexdigits": string.hexdigits,
}

# Characters that the settings may contain
ALLOWED = frozenset(string.ascii_letters + string.digits + ".-~")
# Characters of repository identifiers, which also name Kubernetes resources
# of builds (lowercase RFC 1123 names)
ALLOWED_REPOSITORY = frozenset(string.ascii_lowercase + string.digits + ".-")

# Characters that generated values never contain (`EXCLUDED`), or not at
# their start or end (`NOT_AT_ENDS`); cf. `generate_id()`
EXCLUDED = "_"
NOT_AT_ENDS = ".-" + string.digits

# The settings with character sets, as `(section, key)` under `endpoints`
SETTINGS: tuple[tuple[str, str], ...] = (
    ("repository", "id_charset"),
    ("user", "uid_charset"),
    ("access_token", "charset"),
)

# A string in quotes, without escapes
_QUOTED = r"'[^'\\]*'|\"[^\"\\]*\""
# Tokens of a setting written as an expression or list: names, quoted
# strings, the separators `+` and `,`, and brackets
_TOKEN = re.compile(
    rf"\s*(?:(?P<name>string\.\w+)|(?P<quoted>{_QUOTED})|(?P<sep>[+,\[\]]))\s*"
)
# Anything that looks like a name of a character set, also misspelt
_NAME_LIKE = re.compile(r"strings?\.|ascii_|^(?:digits|hexdigits)$", re.IGNORECASE)


class CharsetError(ValueError):
    """A character set setting can't be used."""


def usable(charset: str) -> bool:
    """Tell whether generated values can start and end with a character.

    Args:
        charset: Characters to draw from.

    Returns:
        Whether it has a character other than `_`, `.`, `-` and digits.
    """
    return bool(set(charset) - set(EXCLUDED + NOT_AT_ENDS))


def _split(value: str) -> list[str] | None:
    """Return the items of a setting written as an expression or list.

    Args:
        value: Value of the setting.

    Returns:
        The items (names and quoted strings), or `None` unless the value is a
        single name or quoted string, such items joined by `+`, or a list of
        them in brackets, separated by `,`.
    """
    tokens: list[re.Match[str]] = []
    position = 0
    while position < len(value):
        match = _TOKEN.match(value, position)
        if match is None:
            return None
        tokens.append(match)
        position = match.end()
    separator = "+"
    if len(tokens) >= 2 and tokens[0]["sep"] == "[" and tokens[-1]["sep"] == "]":
        tokens, separator = tokens[1:-1], ","
    items, separators = tokens[::2], tokens[1::2]
    if (
        len(tokens) % 2 == 0
        or any(token["sep"] is not None for token in items)
        or any(token["sep"] != separator for token in separators)
    ):
        return None
    return [token["name"] or token["quoted"] for token in items]


def _item(item: str, setting: str) -> str:
    """Return the characters of an item of a character set setting.

    Args:
        item: A name of a character set, a quoted string or literal characters.
        setting: Name of the setting, for error messages.

    Returns:
        The characters.

    Raises:
        CharsetError: If the item names an unknown character set.
    """
    item = item.strip()
    if item in NAMED:
        return NAMED[item]
    if re.fullmatch(_QUOTED, item):
        item = item[1:-1]
    if _NAME_LIKE.search(item):
        raise CharsetError(
            f"{setting}: unknown character set {item!r}; use one of "
            f"{', '.join(NAMED)} (without quotes) or literal characters"
        )
    return item


def _allowed(section: str) -> frozenset[str]:
    """Return the characters that a section's character set may contain.

    Args:
        section: Section under `endpoints`, e.g., `repository`.

    Returns:
        `ALLOWED_REPOSITORY` for repositories, otherwise `ALLOWED`.
    """
    return ALLOWED_REPOSITORY if section == "repository" else ALLOWED


def resolve_charset(
    value: Any, setting: str = "charset", allowed: frozenset[str] = ALLOWED
) -> str:
    """Return the characters that a character set setting names.

    Args:
        value: Value of the setting (see the module's docstring).
        setting: Name of the setting, for error messages.
        allowed: Characters that the setting may contain.

    Returns:
        The characters, each once, in sorted order.

    Raises:
        CharsetError: If the value has the wrong type, can't be read, names
            an unknown character set, has characters other than `allowed`,
            has fewer than two characters, or leaves no character for the
            start and end of generated values (anything but `.`, `-` and
            digits).
    """
    if isinstance(value, str):
        items = _split(value)
        if items is None:
            if _NAME_LIKE.search(value):
                raise CharsetError(
                    f"{setting}: can't read {value!r}; use names of character "
                    f"sets and quoted literal characters, joined by '+' or "
                    f"listed in brackets"
                )
            items = [value]
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        items = value
    else:
        raise CharsetError(
            f"{setting}: expected a string or a list of strings, "
            f"got {type(value).__name__}"
        )
    characters = set("".join(_item(item, setting) for item in items))
    if characters - allowed:
        raise CharsetError(
            f"{setting}: characters {''.join(sorted(characters - allowed))!r} "
            f"not allowed; use {''.join(sorted(allowed))!r}"
        )
    if len(characters) < 2:
        raise CharsetError(f"{setting}: needs at least two characters")
    if not usable("".join(characters)):
        raise CharsetError(
            f"{setting}: needs at least one character other than "
            f"'.', '-' and digits, for the start and end of values"
        )
    return "".join(sorted(characters))


def check_charsets(endpoints: Mapping[str, Any]) -> None:
    """Check the character set settings of the configuration.

    Args:
        endpoints: The section `endpoints` of the configuration.

    Raises:
        CharsetError: If a setting is missing or can't be used.
    """
    for section, key in SETTINGS:
        setting = f"endpoints.{section}.{key}"
        try:
            value = endpoints[section][key]
        except (KeyError, TypeError):
            raise CharsetError(f"{setting}: missing") from None
        resolve_charset(value, setting, _allowed(section))


def get_charset(section: str, key: str) -> str:
    """Return the characters of a character set setting of the app.

    Args:
        section: Section under `endpoints`, e.g., `repository`.
        key: Key of the setting in the section, e.g., `id_charset`.

    Returns:
        The characters (cf. `resolve_charset()`).
    """
    value = get_config().endpoints[section][key]
    return resolve_charset(value, f"endpoints.{section}.{key}", _allowed(section))
