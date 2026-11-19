"""Checks of registrations, which admins may make also while they are closed.

`POST /repositories`, `POST /users/register` and `POST /subscriptions` take
the credentials of an admin user (`X-Super-User-Id` and
`X-Super-User-Access-Token`, as `PUT /users/{uid}/verify`): with them, the
request is allowed even while the registration is closed by
`registration_enabled` in its section of the settings.
"""

from typing import Any

from foca.errors import Unauthorized

from pubgrade.errors.exceptions import RegistrationDisabled
from pubgrade.settings import collection, endpoints
from pubgrade.tokens import tokens_match


def is_admin(admin_user_id: str | None, admin_user_access_token: str | None) -> bool:
    """Check the credentials of an admin user.

    Unknown admins and wrong tokens look the same to the caller (both
    `False`), so that registrations answer both with a 401 and don't tell
    which admin identifiers exist. (`GET /users` and the verification of
    users answer an unknown admin with a 404, as before.)

    Args:
        admin_user_id: Identifier of the admin user, or `None`.
        admin_user_access_token: Access token of the admin user, or `None`.

    Returns:
        Whether they are the identifier and access token of an admin user
        of the configuration (`subscriptions.admin_users`).
    """
    if not isinstance(admin_user_id, str) or not admin_user_id:
        return False
    admin: dict[str, Any] | None = collection("admin_users").find_one(
        {"uid": admin_user_id}
    )
    stored = None if admin is None else admin.get("user_access_token")
    return tokens_match(admin_user_access_token, stored)


def check_registration(
    section: str, admin_user_id: str | None, admin_user_access_token: str | None
) -> bool:
    """Check whether a registration is allowed, and whether an admin makes it.

    Admin credentials that are given, even one of the two, must be valid,
    whether registration is open or not, so that a mistyped token isn't
    mistaken for a request without one.

    Args:
        section: Section of the settings with `registration_enabled`
            (`repository`, `user` or `subscriptions`).
        admin_user_id: Identifier of an admin user (`X-Super-User-Id`), or
            `None` if the request has none.
        admin_user_access_token: Access token of the admin user
            (`X-Super-User-Access-Token`), or `None` if the request has none.

    Returns:
        Whether the request carries valid admin credentials.

    Raises:
        Unauthorized: Admin credentials are given, but aren't valid.
        RegistrationDisabled: Registration is closed, and the request has no
            admin credentials.
    """
    if admin_user_id is None and admin_user_access_token is None:
        if not endpoints()[section].get("registration_enabled", True):
            raise RegistrationDisabled
        return False
    if not is_admin(admin_user_id, admin_user_access_token):
        raise Unauthorized
    return True
