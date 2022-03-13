import logging

from pubgrade.errors.exceptions import (
    UserNotFound,
    InternalServerError,
    NameNotFound,
)
from pubgrade.modules.endpoints.repositories import generate_id
from flask import current_app
from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import Unauthorized

logger = logging.getLogger(__name__)


def register_user(data: dict):
    """Register a new user object.

    Args:
         data (dict): Contains Name of the user.

    Returns:
        user_object (dict): Dictionary of user contents (
        identifier and access_token).

    Raises:
        NameNotFound: Raised when request data does not have name string.
        InternalServerError: Raised when it's unable to create unique
        identifier for the user_object.
    """
    user_object = {}

    try:
        user_object["name"] = data["name"]
    except KeyError:
        raise NameNotFound

    db_collection = (
        current_app.config["FOCA"]
            .db.dbs["pubgradeStore"]
            .collections["users"]
            .client
    )
    retries = current_app.config["FOCA"].endpoints["user"]["retries"]
    id_length: int = current_app.config["FOCA"].endpoints["user"][
        "uid_length"
    ]
    id_charset: str = current_app.config["FOCA"].endpoints["user"][
        "uid_charset"
    ]
    access_token_length: int = current_app.config["FOCA"].endpoints[
        "access_token"
    ]["length"]
    access_token_charset: str = current_app.config["FOCA"].endpoints[
        "access_token"
    ]["charset"]
    # Try to evaluate python expression and if any exception occurs, use `set` to create charset.
    try:
        id_charset = eval(id_charset)
    except Exception:
        id_charset = "".join(sorted(set(id_charset)))
    # Try to evaluate python expression and if any exception occurs, use `set` to create charset.
    try:
        access_token_charset = eval(access_token_charset)
    except Exception:
        access_token_charset = "".join(sorted(set(access_token_charset)))

    for i in range(retries):
        logger.debug(f"Trying to insert/update object: try {i}")
        user_object["uid"] = generate_id(
            charset=id_charset,
            length=id_length,
        )
        user_object["user_access_token"] = str(
            generate_id(
                charset=access_token_charset, length=access_token_length
            )
        )
        user_object["isVerified"] = False
        try:
            db_collection.insert_one(user_object)
            break
        except DuplicateKeyError:
            logger.error(
                f"DuplicateKeyError ({user_object['uid']}):  "
                f"Key generated"
                f" is already present."
            )
            continue
    else:
        logger.error(
            f"Could not generate unique identifier."
            f" Tried {retries + 1} times."
        )
        raise InternalServerError

    if "_id" in user_object:
        del user_object["_id"]
        # del user_object['isVerified']
    logger.info(f"Added object with '{user_object}'.")
    return user_object


def delete_user(uid: str, user_access_token: str):
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
    db_collection_subscriptions = (
        current_app.config["FOCA"]
            .db.dbs["pubgradeStore"]
            .collections["subscriptions"]
            .client
    )
    db_collection_user = (
        current_app.config["FOCA"]
            .db.dbs["pubgradeStore"]
            .collections["users"]
            .client
    )
    data_from_db_user = db_collection_user.find_one({"uid": uid})
    if data_from_db_user is None:
        raise UserNotFound
    if data_from_db_user["user_access_token"] != user_access_token:
        raise Unauthorized

    try:
        for subscription_id in data_from_db_user["subscription_list"]:
            db_collection_subscriptions.delete_one({"id": subscription_id})
    except KeyError:
        logger.info(f"No subcriptions found for user: {uid}")
    db_collection_user.delete_one({"uid": uid})
    return "User deleted successfully."


def get_users(admin_user_id: str, admin_user_access_token: str):
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
    db_collection_admin_users = (
        current_app.config["FOCA"]
            .db.dbs["pubgradeStore"]
            .collections["admin_users"]
            .client
    )
    data_from_db = db_collection_admin_users.find_one({"uid": admin_user_id})
    if data_from_db is None:
        raise UserNotFound
    if data_from_db["user_access_token"] != admin_user_access_token:
        raise Unauthorized

    db_collection = (
        current_app.config["FOCA"]
            .db.dbs["pubgradeStore"]
            .collections["users"]
            .client
    )
    # Get all user objects from database with `user_access_token`, `_id` and `subscription_list` omitted.
    users = db_collection.find(
        {},
        {"user_access_token": False, "_id": False, "subscription_list": False},
    )
    return list(users)


def toggle_user_status(
        admin_user_id: str, admin_user_access_token: str, uid: str,
        is_verify: bool
):
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
    db_collection_admin_users = (
        current_app.config["FOCA"]
            .db.dbs["pubgradeStore"]
            .collections["admin_users"]
            .client
    )
    data_from_db = db_collection_admin_users.find_one({"uid": admin_user_id})
    if data_from_db is None:
        raise UserNotFound
    if data_from_db["user_access_token"] != admin_user_access_token:
        raise Unauthorized

    db_collection_user = (
        current_app.config["FOCA"]
            .db.dbs["pubgradeStore"]
            .collections["users"]
            .client
    )
    data_from_db = db_collection_user.find_one({"uid": uid})
    if data_from_db is None:
        logger.error(f"Could not find repository with given identifier: {uid}")
        raise UserNotFound
    data_from_db["isVerified"] = is_verify
    db_collection_user.replace_one(
        filter={"uid": uid}, replacement=data_from_db
    )
    if is_verify:
        return "User verified successfully."
    else:
        return "User unverified successfully."