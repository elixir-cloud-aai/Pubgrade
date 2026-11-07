"""Character sets of generated identifiers and access tokens.

The settings `endpoints.repository.id_charset`, `endpoints.user.uid_charset`
and `endpoints.access_token.charset` name the characters that generated
identifiers and access tokens consist of, as one of:

- a list, whose items are names of character sets (`NAMED`, e.g.,
  `string.digits`) or literal characters (e.g., `'.'`, `'-'`, `abc`);
- a string with such items joined by `+`, literal characters in quotes (e.g.,
  `string.ascii_lowercase + string.digits + '.' + '-'`);
- a single name (e.g., `string.digits`);
- any other string, as literal characters (e.g., `abcdef`).

The app checks them at start (`check_charsets()`), so that a mistake stops it
with an error instead of failing requests.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
import string
from typing import Any

# Character sets that the settings may name
NAMED: dict[str, str] = {
    "string.ascii_letters": string.ascii_letters,
    "string.ascii_lowercase": string.ascii_lowercase,
    "string.ascii_uppercase": string.ascii_uppercase,
    "string.digits": string.digits,
    "string.hexdigits": string.hexdigits,
}

# Characters that generated values never contain (`_`), or not at their
# start or end (`.`, `-` and digits); cf. `generate_id()`
EXCLUDED = "_"
NOT_AT_ENDS = ".-" + string.digits

# The settings with character sets, as paths under `endpoints`
SETTINGS: tuple[tuple[str, str], ...] = (
    ("repository", "id_charset"),
    ("user", "uid_charset"),
    ("access_token", "charset"),
)


class CharsetError(ValueError):
    """A character set setting can't be used."""


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
    if item.startswith("string."):
        raise CharsetError(
            f"{setting}: unknown character set {item!r}; "
            f"use one of {', '.join(NAMED)} or literal characters"
        )
    if len(item) >= 2 and item[0] == item[-1] and item[0] in "'\"":
        try:
            value = ast.literal_eval(item)
        except (SyntaxError, ValueError):
            return item
        if isinstance(value, str):
            return value
    return item


def resolve_charset(value: Any, setting: str = "charset") -> str:
    """Return the characters that a character set setting names.

    Args:
        value: Value of the setting (see the module's docstring).
        setting: Name of the setting, for error messages.

    Returns:
        The characters, each once, in sorted order, without `_`.

    Raises:
        CharsetError: If the value has the wrong type, names an unknown
            character set, or leaves no character for the start and end of
            generated values (anything but `_`, `.`, `-` and digits).
    """
    if isinstance(value, str):
        parts = value.split("+")
        if len(parts) > 1 and all(
            part.strip() in NAMED
            or (
                len(part.strip()) >= 2
                and part.strip()[0] == part.strip()[-1]
                and part.strip()[0] in "'\""
            )
            for part in parts
        ):
            items = parts
        elif value.strip().startswith("string."):
            items = [value]
        else:
            items = list(value)
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        items = value
    else:
        raise CharsetError(
            f"{setting}: expected a string or a list of strings, "
            f"got {type(value).__name__}"
        )
    characters = set("".join(_item(item, setting) for item in items))
    characters.discard(EXCLUDED)
    if not characters - set(NOT_AT_ENDS):
        raise CharsetError(
            f"{setting}: needs at least one character other than "
            f"'_', '.', '-' and digits, for the start and end of values"
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
        resolve_charset(value, setting)
