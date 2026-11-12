"""Comparison of access tokens.

Every check of a supplied access token against a stored one goes through
`tokens_match()`, which compares them with `hmac.compare_digest`: the time
that a comparison takes doesn't depend on how much of the supplied value
matches.
"""

import hmac


def tokens_match(supplied: object, stored: object) -> bool:
    """Check whether a supplied access token is the stored one.

    Args:
        supplied: Token of the request, e.g., from a header; `None` if the
            request has none.
        stored: Stored token; `None` if there is none.

    Returns:
        Whether both are strings, not empty, and equal; the comparison
        takes constant time for tokens of the same length. Values that
        aren't strings (e.g., an unquoted number in the configuration)
        match nothing.
    """
    if not isinstance(supplied, str) or not isinstance(stored, str):
        return False
    if not supplied or not stored:
        return False
    return hmac.compare_digest(supplied.encode("utf-8"), stored.encode("utf-8"))
