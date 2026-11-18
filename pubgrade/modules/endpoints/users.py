"""Registration and management of users."""

import logging
from typing import Any

from foca.errors import Unauthorized
from pymongo.errors import DuplicateKeyError

from pubgrade.charsets import get_charset
from pubgrade.errors.exceptions import (
    InternalServerError,
    NameNotFound,
    UserNotFound,
    VerificationNotAllowed,
)
from pubgrade.modules.endpoints.repositories import generate_id
from pubgrade.registration import check_registration
from pubgrade.settings import collection, endpoints
from pubgrade.tokens import tokens_match

logger = logging.getLogger(__name__)


def register_user(
    data: dict[str, Any],
    admin_user_id: str | None = None,
    admin_user_access_token: str | None = None,
) -> dict[str, Any]:
    """Register a new user object.

    Args:
         data (dict): Contains Name of the user and, optionally, whether it
         is verified at once (`verified`, admins only).
         admin_user_id: Identifier of an admin user, who may register also
         while registration is closed, and register verified users; `None`
         if not given.
         admin_user_access_token: Access token of the admin user; `None` if
         not given.

    Returns:
        user_object (dict): Dictionary of user contents (
        identifier and access_token).

    Raises:
        NameNotFound: Raised when request data does not have name string.
        InternalServerError: Raised when it's unable to create unique
        identifier for the user_object.
        RegistrationDisabled: Raised when registration is closed by the
        setting `endpoints.user.registration_enabled` and the request has no
        admin credentials.
        Unauthorized: Raised when admin credentials are given but invalid.
        VerificationNotAllowed: Raised when a request without admin
        credentials asks for a verified user.
    """
    admin = check_registration("user", admin_user_id, admin_user_access_token)
    verified = data.get("verified") is True
    if verified and not admin:
        raise VerificationNotAllowed
    user_object: dict[str, Any] = {}

    try:
        user_object["name"] = sanitise_text(data["name"])
    except KeyError:
        raise NameNotFound from None

    db_collection = collection("users")
    retries = endpoints()["user"]["retries"]
    id_length: int = endpoints()["user"]["uid_length"]
    id_charset = get_charset("user", "uid_charset")
    access_token_length: int = endpoints()["access_token"]["length"]
    access_token_charset = get_charset("access_token", "charset")

    for i in range(retries):
        logger.debug("Trying to insert/update object: try %s", i)
        user_object["uid"] = generate_id(
            charset=id_charset,
            length=id_length,
        )
        user_object["user_access_token"] = str(
            generate_id(charset=access_token_charset, length=access_token_length)
        )
        user_object["isVerified"] = verified
        try:
            db_collection.insert_one(user_object)
            break
        except DuplicateKeyError:
            logger.error(
                "DuplicateKeyError (%s):  Key generated is already present.",
                user_object["uid"],
            )
            continue
    else:
        logger.error(
            "Could not generate unique identifier. Tried %s times.", retries + 1
        )
        raise InternalServerError

    user_object.pop("_id", None)
    # del user_object['isVerified']
    logger.info(
        "Added user %s%s.",
        user_object["uid"],
        " (verified by an admin)" if verified else "",
    )
    return user_object


def delete_user(uid: str, user_access_token: str) -> str:
    """Delete User object.

    Args:
        uid (str): Unique identifier for user.
        user_access_token (str): Secret to verify user.

    Returns:
        "User deleted successfully."

    Raises:
        RepositoryNotFound: Raised when there is no registered repository in
        the pubgrade.
        Unauthorized: Raised when access_token is invalid or not specified
        in request.
        UserNotFound: Raised when there is no user with specified uid.
    """
    db_collection_subscriptions = collection("subscriptions")
    db_collection_user = collection("users")
    data_from_db_user = db_collection_user.find_one({"uid": uid})
    if data_from_db_user is None:
        raise UserNotFound
    if not tokens_match(user_access_token, data_from_db_user["user_access_token"]):
        raise Unauthorized

    try:
        for subscription_id in data_from_db_user["subscription_list"]:
            db_collection_subscriptions.delete_one({"id": subscription_id})
    except KeyError:
        logger.info("No subcriptions found for user: %s", uid)
    db_collection_user.delete_one({"uid": uid})
    return "User deleted successfully."


def get_users(admin_user_id: str, admin_user_access_token: str) -> list[dict[str, Any]]:
    """Get available users.

    Args:
        admin_user_id (str): Unique identifier for admin user
        admin_user_access_token (str): Secret to verify admin user.

    Returns:
        List of available users.

    Raises:
        UserNotFound: Raised when there is no admin user with specified uid.
        Unauthorized: Raised when access_token is invalid or not specified
        in request.
    """
    db_collection_admin_users = collection("admin_users")
    data_from_db = db_collection_admin_users.find_one({"uid": admin_user_id})
    if data_from_db is None:
        raise UserNotFound
    if not tokens_match(admin_user_access_token, data_from_db["user_access_token"]):
        raise Unauthorized

    db_collection = collection("users")
    # Get all user objects from database with `user_access_token`, `_id` and
    # `subscription_list` omitted.
    users = db_collection.find(
        {},
        {"user_access_token": False, "_id": False, "subscription_list": False},
    )
    return list(users)


def toggle_user_status(
    admin_user_id: str, admin_user_access_token: str, uid: str, is_verify: bool
) -> str:
    """Verify/Unverify user status.

    Args:
        admin_user_id (str): Unique identifier for admin user
        admin_user_access_token (str): Secret to verify admin user.
        uid (str): Unique identifier for user.
        is_verify (bool): Verification status of user.

    Returns:
        User active status.

    Raises:
        UserNotFound: Raised when there is no user with specified uid.
        Unauthorized: Raised when access_token is invalid or not specified
        in request.
    """
    db_collection_admin_users = collection("admin_users")
    data_from_db = db_collection_admin_users.find_one({"uid": admin_user_id})
    if data_from_db is None:
        raise UserNotFound
    if not tokens_match(admin_user_access_token, data_from_db["user_access_token"]):
        raise Unauthorized

    db_collection_user = collection("users")
    # Sets only the flag, so that concurrent changes of the user's
    # subscriptions are kept
    updated = db_collection_user.update_one(
        {"uid": uid}, {"$set": {"isVerified": is_verify}}
    )
    if updated.matched_count == 0:
        logger.error("Could not find user with given identifier: %s", uid)
        raise UserNotFound
    if is_verify:
        return "User verified successfully."
    else:
        return "User unverified successfully."


def sanitise_text(text: str) -> str:
    """Sanitise input text.

    Args:
        text: input text.

    Returns:
        Sanitised text

    """
    return "".join(e for e in text if e.isalnum() or e.isspace())
