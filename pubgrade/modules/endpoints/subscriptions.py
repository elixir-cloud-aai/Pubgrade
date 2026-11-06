from concurrent.futures import ThreadPoolExecutor, wait
import logging
from typing import Any, Dict, List, Optional

import requests
from pubgrade.timestamps import now, repaired_subscription
from pubgrade.errors.exceptions import (
    RegistrationDisabled,
    RepositoryNotFound,
    UserNotFound,
    SubscriptionNotFound,
    TooManySubscriptions,
    BuildNotFound,
    InternalServerError,
    UserNotVerified,
)
from pubgrade.modules.endpoints.repositories import generate_id
from flask import current_app
from foca import get_config
import json
from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import Unauthorized

logger = logging.getLogger(__name__)

# Seconds, if `endpoints.subscriptions.notification_timeout` isn't set
DEFAULT_NOTIFICATION_TIMEOUT = 10
# Subscriptions per repository, if
# `endpoints.subscriptions.max_per_repository` isn't set. This also limits the
# threads per notification, as each subscriber gets its own
DEFAULT_MAX_SUBSCRIPTIONS = 100
# Seconds that all calls of a notification may take beyond connecting and
# waiting for the response
NOTIFICATION_MARGIN = 5


def register_subscription(uid: str, user_access_token: str, data: dict):
    """Register new subscription for the user.

    Args:
        uid (str): Unique identifier for user.
        user_access_token (str): Secret to verify user.
        data (dict): Dictionary element of request received.

    Returns:
        subscription_id (str): Identifier generated for created subscription.

    Raises:
        RepositoryNotFound: Raised when there is no registered repository in
        the pubgrade.
        Unauthorized: Raised when access_token is invalid or not specified
        in request.
        UserNotFound: Raised when there is no user with specified uid.
        RegistrationDisabled: Raised when registration is closed by the
        setting `endpoints.subscriptions.registration_enabled`.
        TooManySubscriptions: Raised when the repository has reached the limit
        `endpoints.subscriptions.max_per_repository`.
    """
    if not get_config().endpoints["subscriptions"].get(
        "registration_enabled", True
    ):
        raise RegistrationDisabled
    db_collection_subscriptions = (
        get_config()
        .db.dbs["pubgradeStore"]
        .collections["subscriptions"]
        .client
    )
    db_collection_user = (
        get_config()
        .db.dbs["pubgradeStore"]
        .collections["users"]
        .client
    )
    db_collection_repositories = (
        get_config()
        .db.dbs["pubgradeStore"]
        .collections["repositories"]
        .client
    )
    retries = get_config().endpoints["repository"]["retries"]
    id_length: int = get_config().endpoints["repository"][
        "id_length"
    ]
    id_charset: str = get_config().endpoints["repository"][
        "id_charset"
    ]
    try:
        id_charset = eval(id_charset)
    except Exception:
        id_charset = "".join(sorted(set(id_charset)))
    data_from_db_user = db_collection_user.find_one({"uid": uid})
    data_from_db_repository = db_collection_repositories.find_one(
        {"id": data["repository_id"]}
    )
    if data_from_db_user is None:
        raise UserNotFound
    if not data_from_db_user["isVerified"]:
        raise UserNotVerified
    if data_from_db_user["user_access_token"] != user_access_token:
        raise Unauthorized
    if data_from_db_repository is None:
        raise RepositoryNotFound
    if db_collection_subscriptions.count_documents(
        {"repository_id": data["repository_id"]}
    ) >= _max_subscriptions():
        raise TooManySubscriptions
    for i in range(retries):
        logger.debug(f"Trying to insert/update object: try {i}" + str(data))
        data["id"] = generate_id(
            charset=id_charset,
            length=id_length,
        )
        data["state"] = "Inactive"
        try:
            db_collection_subscriptions.insert_one(data)
            # Updates subscription_list at both user and subscribed repository.
            db_collection_user.update_one(
                {"uid": uid}, {"$push": {"subscription_list": data["id"]}}
            )
            db_collection_repositories.update_one(
                {"id": data["repository_id"]},
                {"$push": {"subscription_list": data["id"]}},
            )
            break
        except DuplicateKeyError:
            logger.error(
                f"DuplicateKeyError ({data['id']}): Key "
                f"generated is already present."
            )
            continue
    else:
        logger.error(
            f"Could not generate unique identifier."
            f" Tried {retries + 1} times."
        )
        raise InternalServerError
    return {"subscription_id": data["id"]}


def get_subscriptions(uid: str, user_access_token: str):
    """Retrieve registered subscriptions for the user.

    Args:
        uid (str): Unique identifier for user.
        user_access_token (str): Secret to verify user.

    Returns:
        subscription_list (list): list of subscriptions registered by the user.

    Raises:
        SubscriptionNotFound: Raised when no subscription is available for
        the user.
        Unauthorized: Raised when access_token is invalid or not specified
        in request.
        UserNotFound: Raised when there is no user with specified uid.
    """
    db_collection_user = (
        get_config()
        .db.dbs["pubgradeStore"]
        .collections["users"]
        .client
    )
    data_from_db_user = db_collection_user.find_one({"uid": uid})
    if data_from_db_user is None:
        raise UserNotFound
    if not data_from_db_user["isVerified"]:
        raise UserNotVerified
    if data_from_db_user["user_access_token"] != user_access_token:
        raise Unauthorized
    try:
        subscription_list = []
        for subscription_id in data_from_db_user["subscription_list"]:
            subscription_list.append({"subscription_id": subscription_id})
        return subscription_list
    except KeyError:
        raise SubscriptionNotFound


def get_subscription_info(
    uid: str, user_access_token: str, subscription_id: str
):
    """Retrieve subscription information.

    Args:
        uid (str): Unique identifier for user.
        user_access_token (str): Secret to verify user.
        subscription_id (str): Identifier for subscriptions.

    Returns:
        subscription_object (dict): Dictionary element of subscription.

    Raises:
        SubscriptionNotFound: Raised when no subscription is available for
        the user.
        Unauthorized: Raised when access_token is invalid or not specified
        in request.
        UserNotFound: Raised when there is no user with specified uid.
    """
    db_collection_user = (
        get_config()
        .db.dbs["pubgradeStore"]
        .collections["users"]
        .client
    )
    db_collection_subscriptions = (
        get_config()
        .db.dbs["pubgradeStore"]
        .collections["subscriptions"]
        .client
    )
    data_from_db_user = db_collection_user.find_one({"uid": uid})
    if data_from_db_user is None:
        raise UserNotFound
    if not data_from_db_user["isVerified"]:
        raise UserNotVerified
    if data_from_db_user["user_access_token"] != user_access_token:
        raise Unauthorized
    if subscription_id not in data_from_db_user.get("subscription_list", []):
        raise SubscriptionNotFound
    subscription_object = db_collection_subscriptions.find_one(
        {"id": subscription_id}
    )
    if subscription_object is None:
        raise SubscriptionNotFound
    del subscription_object["_id"]
    del subscription_object["access_token"]
    return repaired_subscription(subscription_object)


def delete_subscription(
    uid: str, user_access_token: str, subscription_id: str
):
    """Delete subscription.

    Args:
        uid (str): Unique identifier for user.
        user_access_token (str): Secret to verify user.
        subscription_id (str): Identifier for subscriptions.

    Returns:
        Delete count. (1 if subscription is deleted, 0 if not
        deleted.)

    Raises:
        SubscriptionNotFound: Raised when no subscription is available for
        the user.
        Unauthorized: Raised when access_token is invalid or not specified
        in request.
        UserNotFound: Raised when there is no user with specified uid.
    """
    db_collection_user = (
        get_config()
        .db.dbs["pubgradeStore"]
        .collections["users"]
        .client
    )
    db_collection_subscriptions = (
        get_config()
        .db.dbs["pubgradeStore"]
        .collections["subscriptions"]
        .client
    )
    data_from_db_user = db_collection_user.find_one({"uid": uid})
    if data_from_db_user is None:
        raise UserNotFound
    if not data_from_db_user["isVerified"]:
        raise UserNotVerified
    if data_from_db_user["user_access_token"] != user_access_token:
        raise Unauthorized
    if subscription_id not in data_from_db_user.get("subscription_list", []):
        raise SubscriptionNotFound
    data = db_collection_subscriptions.delete_one({"id": subscription_id})
    if data.deleted_count > 0:
        return data.deleted_count
    else:
        raise SubscriptionNotFound


def notify_subscriptions(
    subscription_id: str, image: str, build_id: str
) -> Dict[str, Any]:
    """Notify one subscription of an image, if it matches the build.

    Sends a request to the callback URL of the subscription, if its type and
    value match the build's `head_commit`; the value `*` matches any value of
    the type. The result doesn't contain the
    callback URL or the subscription's token, as builds are public.

    Args:
        subscription_id: Identifier for subscription.
        image: Docker image to be updated at deployment.
        build_id: Build Identifier for build to be used for subscription.

    Returns:
        Result of the notification: `subscription_id`, `result` (`delivered`,
        `failed` or `skipped`), `http_status` (or None without a response) and
        `finished_at`.

    Raises:
        SubscriptionNotFound: Raised when the subscription doesn't exist.
        BuildNotFound: Raised when object with given build identifier was not
        found.
    """
    db_collection_subscriptions = (
        get_config()
        .db.dbs["pubgradeStore"]
        .collections["subscriptions"]
        .client
    )
    db_collection_builds = (
        get_config()
        .db.dbs["pubgradeStore"]
        .collections["builds"]
        .client
    )
    build_object = db_collection_builds.find_one({"id": build_id})
    if build_object is None:
        raise BuildNotFound
    subscription_object = db_collection_subscriptions.find_one(
        {"id": subscription_id}
    )
    if subscription_object is None:
        raise SubscriptionNotFound
    head_commit = build_object["head_commit"]
    subscription_type = subscription_object["type"]
    value = subscription_object["value"]
    if subscription_type not in head_commit or value not in (
        "*",
        head_commit[subscription_type],
    ):
        logger.info(f"Subscription {subscription_id} doesn't match the build.")
        return _notification_result(subscription_id, "skipped")

    del subscription_object["_id"]
    subscription_object["build_id"] = build_id
    name, _, tag = image.rpartition(":")
    http_status = None
    try:
        # No redirects, as they would forward the token to another host. Only
        # the status counts: the body isn't read
        response = requests.request(
            "PUT",
            subscription_object["callback_url"],
            headers={
                "X-Access-Token": subscription_object["access_token"],
                "Content-Type": "application/json",
            },
            data=json.dumps({"image_name": name, "tag": tag}),
            timeout=_notification_timeout(),
            allow_redirects=False,
            stream=True,
        )
        response.close()
        http_status = response.status_code
        result = "delivered" if 200 <= http_status < 300 else "failed"
    except requests.exceptions.RequestException as error:
        logger.error(
            f"Notifying subscription {subscription_id} failed: "
            f"{type(error).__name__}"
        )
        result = "failed"
    subscription_object["state"] = (
        "Active" if result == "delivered" else "Inactive"
    )
    subscription_object["updated_at"] = now()
    db_collection_subscriptions.update_one(
        {"id": subscription_id}, {"$set": subscription_object}
    )
    return _notification_result(subscription_id, result, http_status)


def notify_all_subscriptions(
    subscription_ids: List[str], image: str, build_id: str
) -> List[Dict[str, Any]]:
    """Notify subscriptions concurrently and store the results on the build.

    One subscription that fails or hangs affects none of the others: up to the
    limit of subscriptions per repository, each one has its own thread, so none
    waits behind another, and each call has a timeout
    (`endpoints.subscriptions.notification_timeout`), for connecting and for
    each wait for data. Calls that go on for longer than the overall wait count
    as failed; their threads end with the call.

    Args:
        subscription_ids: Identifiers of the subscriptions.
        image: Docker image to be updated at deployments.
        build_id: Identifier of the build.

    Returns:
        One result per subscription, see `notify_subscriptions()`.
    """
    app = current_app._get_current_object()

    def notify(subscription_id: str) -> Dict[str, Any]:
        """Notify one subscription, turning all errors into its result.

        Args:
            subscription_id: Identifier of the subscription.

        Returns:
            Result of the notification.
        """
        with app.app_context():
            try:
                return notify_subscriptions(subscription_id, image, build_id)
            except SubscriptionNotFound:
                # Deleting a subscription leaves its ID at the repository
                return _notification_result(subscription_id, "skipped")
            except Exception:
                logger.exception(
                    f"Notifying subscription {subscription_id} failed."
                )
                return _notification_result(subscription_id, "failed")

    results: List[Dict[str, Any]] = []
    if subscription_ids:
        executor = ThreadPoolExecutor(
            max_workers=min(len(subscription_ids), _max_subscriptions())
        )
        futures = {
            executor.submit(notify, subscription_id): subscription_id
            for subscription_id in subscription_ids
        }
        done, _ = wait(
            futures, timeout=2 * _notification_timeout() + NOTIFICATION_MARGIN
        )
        # Calls that are still running end with their timeouts
        executor.shutdown(wait=False)
        results = [
            future.result()
            if future in done
            else _notification_result(subscription_id, "failed")
            for future, subscription_id in futures.items()
        ]
    app.config.foca.db.dbs["pubgradeStore"].collections[
        "builds"
    ].client.update_one({"id": build_id}, {"$set": {"notifications": results}})
    return results


def _max_subscriptions() -> int:
    """Get the limit of subscriptions per repository.

    Returns:
        The setting `endpoints.subscriptions.max_per_repository`.
    """
    return get_config().endpoints["subscriptions"].get(
        "max_per_repository", DEFAULT_MAX_SUBSCRIPTIONS
    )


def _notification_timeout() -> float:
    """Get the timeout for calls to subscribers.

    Returns:
        The setting `endpoints.subscriptions.notification_timeout`, in seconds.
    """
    return get_config().endpoints["subscriptions"].get(
        "notification_timeout", DEFAULT_NOTIFICATION_TIMEOUT
    )


def _notification_result(
    subscription_id: str, result: str, http_status: Optional[int] = None
) -> Dict[str, Any]:
    """Create the result of a notification.

    Args:
        subscription_id: Identifier of the subscription.
        result: `delivered`, `failed` or `skipped`.
        http_status: Status of the subscriber's response, if any.

    Returns:
        The result, as stored on the build.
    """
    return {
        "subscription_id": subscription_id,
        "result": result,
        "http_status": http_status,
        "finished_at": now(),
    }
