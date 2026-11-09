"""Registration of subscriptions and notification of subscribers."""

from concurrent.futures import ThreadPoolExecutor, wait
import json
import logging
from typing import Any

from flask import current_app
from pymongo.errors import DuplicateKeyError
import requests
from werkzeug.exceptions import Unauthorized

from pubgrade.charsets import get_charset
from pubgrade.errors.exceptions import (
    BuildNotFound,
    InternalServerError,
    RegistrationDisabled,
    RepositoryNotFound,
    SubscriptionNotFound,
    TooManySubscriptions,
    UndeclaredBuildType,
    UserNotFound,
    UserNotVerified,
)
from pubgrade.modules.endpoints.repositories import (
    ACCEPTING,
    accepts_additions,
    check_build_types,
    declaring,
    generate_id,
)
from pubgrade.settings import collection, endpoints
from pubgrade.timestamps import now, repaired_subscription

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
# The fields of a request for a subscription (`Subscription` and
# `access_token` in the API); others aren't stored
SUBSCRIPTION_FIELDS = frozenset(
    {"repository_id", "callback_url", "type", "value", "build_types", "access_token"}
)


def register_subscription(
    uid: str, user_access_token: str, data: dict[str, Any]
) -> dict[str, str]:
    """Register new subscription for the user.

    Args:
        uid (str): Unique identifier for user.
        user_access_token (str): Secret to verify user.
        data (dict): Dictionary element of request received.

    Returns:
        subscription_id (str): Identifier generated for created subscription.

    Raises:
        RepositoryNotFound: Raised when there is no registered repository in
        the pubgrade, or it is being deleted; a subscription registered
        meanwhile is removed again.
        Unauthorized: Raised when access_token is invalid or not specified
        in request.
        UserNotFound: Raised when there is no user with specified uid.
        RegistrationDisabled: Raised when registration is closed by the
        setting `endpoints.subscriptions.registration_enabled`.
        TooManySubscriptions: Raised when the repository has reached the limit
        `endpoints.subscriptions.max_per_repository`.
        UndeclaredBuildType: Raised when the repository doesn't declare one of
        the subscription's `build_types`.
    """
    if not endpoints()["subscriptions"].get("registration_enabled", True):
        raise RegistrationDisabled
    data = {key: value for key, value in data.items() if key in SUBSCRIPTION_FIELDS}
    db_collection_subscriptions = collection("subscriptions")
    db_collection_user = collection("users")
    db_collection_repositories = collection("repositories")
    retries = endpoints()["repository"]["retries"]
    id_length: int = endpoints()["repository"]["id_length"]
    id_charset = get_charset("repository", "id_charset")
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
    if data_from_db_repository is None or "deleting" in data_from_db_repository:
        raise RepositoryNotFound
    check_build_types(data_from_db_repository, data.get("build_types", []))
    if (
        db_collection_subscriptions.count_documents(
            {"repository_id": data["repository_id"]}
        )
        >= _max_subscriptions()
    ):
        raise TooManySubscriptions
    for i in range(retries):
        logger.debug("Trying to insert/update object: try %s", i)
        data["id"] = generate_id(
            charset=id_charset,
            length=id_length,
        )
        data["state"] = "Inactive"
        try:
            db_collection_subscriptions.insert_one(data)
            break
        except DuplicateKeyError:
            logger.error(
                "DuplicateKeyError (%s): Key generated is already present.", data["id"]
            )
            continue
    else:
        logger.error(
            "Could not generate unique identifier. Tried %s times.", retries + 1
        )
        raise InternalServerError
    # Lists the subscription for the user first, then for the repository,
    # unless that is being deleted meanwhile: its deletion then misses the
    # subscription, which is removed again
    db_collection_user.update_one(
        {"uid": uid}, {"$push": {"subscription_list": data["id"]}}
    )
    pushed = db_collection_repositories.update_one(
        {
            "id": data["repository_id"],
            **ACCEPTING,
            # Types removed since the check aren't stored
            **declaring(data.get("build_types", [])),
        },
        {"$push": {"subscription_list": data["id"]}},
    )
    if pushed.matched_count == 0:
        db_collection_user.update_one(
            {"uid": uid}, {"$pull": {"subscription_list": data["id"]}}
        )
        db_collection_subscriptions.delete_one({"id": data["id"]})
        if data.get("build_types") and accepts_additions(data["repository_id"]):
            logger.info(
                "Removed subscription %s, whose build types the repository no "
                "longer declares.",
                data["id"],
            )
            raise UndeclaredBuildType
        logger.info(
            "Removed subscription %s, whose repository is being deleted.", data["id"]
        )
        raise RepositoryNotFound
    logger.info("Added subscription %s.", data["id"])
    return {"subscription_id": data["id"]}


def get_subscriptions(uid: str, user_access_token: str) -> list[dict[str, str]]:
    """Retrieve registered subscriptions for the user.

    Args:
        uid (str): Unique identifier for user.
        user_access_token (str): Secret to verify user.

    Returns:
        subscription_list (list): list of subscriptions registered by the
        user; empty if there are none.

    Raises:
        Unauthorized: Raised when access_token is invalid or not specified
        in request.
        UserNotFound: Raised when there is no user with specified uid.
    """
    db_collection_user = collection("users")
    data_from_db_user = db_collection_user.find_one({"uid": uid})
    if data_from_db_user is None:
        raise UserNotFound
    if not data_from_db_user["isVerified"]:
        raise UserNotVerified
    if data_from_db_user["user_access_token"] != user_access_token:
        raise Unauthorized
    return [
        {"subscription_id": subscription_id}
        for subscription_id in data_from_db_user.get("subscription_list", [])
    ]


def get_subscription_info(
    uid: str, user_access_token: str, subscription_id: str
) -> dict[str, Any]:
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
    db_collection_user = collection("users")
    db_collection_subscriptions = collection("subscriptions")
    data_from_db_user = db_collection_user.find_one({"uid": uid})
    if data_from_db_user is None:
        raise UserNotFound
    if not data_from_db_user["isVerified"]:
        raise UserNotVerified
    if data_from_db_user["user_access_token"] != user_access_token:
        raise Unauthorized
    if subscription_id not in data_from_db_user.get("subscription_list", []):
        raise SubscriptionNotFound
    subscription_object = db_collection_subscriptions.find_one({"id": subscription_id})
    if subscription_object is None:
        raise SubscriptionNotFound
    del subscription_object["_id"]
    del subscription_object["access_token"]
    return repaired_subscription(subscription_object)


def delete_subscription(uid: str, user_access_token: str, subscription_id: str) -> int:
    """Delete subscription.

    Args:
        uid (str): Unique identifier for user.
        user_access_token (str): Secret to verify user.
        subscription_id (str): Identifier for subscriptions.

    Returns:
        Delete count, 1. The subscription is no longer listed for the user
        or its repository.

    Raises:
        SubscriptionNotFound: Raised when no subscription is available for
        the user.
        Unauthorized: Raised when access_token is invalid or not specified
        in request.
        UserNotFound: Raised when there is no user with specified uid.
    """
    db_collection_user = collection("users")
    db_collection_subscriptions = collection("subscriptions")
    data_from_db_user = db_collection_user.find_one({"uid": uid})
    if data_from_db_user is None:
        raise UserNotFound
    if not data_from_db_user["isVerified"]:
        raise UserNotVerified
    if data_from_db_user["user_access_token"] != user_access_token:
        raise Unauthorized
    if subscription_id not in data_from_db_user.get("subscription_list", []):
        raise SubscriptionNotFound
    deleted = db_collection_subscriptions.find_one_and_delete({"id": subscription_id})
    # No longer listed for the user, nor for its repository
    db_collection_user.update_one(
        {"uid": uid}, {"$pull": {"subscription_list": subscription_id}}
    )
    if deleted is None:
        raise SubscriptionNotFound
    collection("repositories").update_one(
        {"id": deleted["repository_id"]},
        {"$pull": {"subscription_list": subscription_id}},
    )
    return 1


def notify_subscriptions(
    subscription_id: str, image: str, build_id: str
) -> dict[str, Any]:
    """Notify one subscription of an image, if it matches the build.

    Sends a request to the callback URL of the subscription, if its type and
    value match the build's `head_commit`; the value `*` matches any value of
    the type. A subscription with `build_types` (not empty) matches only
    builds whose `build_type` is one of them, not builds without a type. The
    result doesn't contain the
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
    db_collection_subscriptions = collection("subscriptions")
    db_collection_builds = collection("builds")
    build_object = db_collection_builds.find_one({"id": build_id})
    if build_object is None:
        raise BuildNotFound
    subscription_object = db_collection_subscriptions.find_one({"id": subscription_id})
    if subscription_object is None:
        raise SubscriptionNotFound
    if not matches(subscription_object, build_object):
        logger.info("Subscription %s doesn't match the build.", subscription_id)
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
            "Notifying subscription %s failed: %s",
            subscription_id,
            type(error).__name__,
        )
        result = "failed"
    subscription_object["state"] = "Active" if result == "delivered" else "Inactive"
    subscription_object["updated_at"] = now()
    db_collection_subscriptions.update_one(
        {"id": subscription_id}, {"$set": subscription_object}
    )
    return _notification_result(subscription_id, result, http_status)


def matches(subscription: dict[str, Any], build: dict[str, Any]) -> bool:
    """Tell whether a subscription matches a build.

    Args:
        subscription: The subscription, as stored.
        build: The build, as stored.

    Returns:
        Whether the subscription's `type` is in the build's `head_commit`,
        with the subscription's `value` (or any value for `*`), and, if the
        subscription has `build_types` (a list that isn't empty), whether
        the build's `build_type` is one of them; builds without a type then
        don't match.
    """
    head_commit = build["head_commit"]
    subscription_type = subscription["type"]
    if subscription_type not in head_commit or subscription["value"] not in (
        "*",
        head_commit[subscription_type],
    ):
        return False
    build_types = subscription.get("build_types")
    if isinstance(build_types, list) and build_types:
        return build.get("build_type") in build_types
    return True


def notify_all_subscriptions(
    subscription_ids: list[str], image: str, build_id: str
) -> list[dict[str, Any]]:
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
    # The app itself, not its proxy, which needs this thread's app context
    app = current_app._get_current_object()  # type: ignore[attr-defined]

    def notify(subscription_id: str) -> dict[str, Any]:
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
                logger.exception("Notifying subscription %s failed.", subscription_id)
                return _notification_result(subscription_id, "failed")

    results: list[dict[str, Any]] = []
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
    app.config.foca.db.dbs["pubgradeStore"].collections["builds"].client.update_one(
        {"id": build_id}, {"$set": {"notifications": results}}
    )
    return results


def _max_subscriptions() -> int:
    """Get the limit of subscriptions per repository.

    Returns:
        The setting `endpoints.subscriptions.max_per_repository`.
    """
    value: Any = endpoints()["subscriptions"].get(
        "max_per_repository", DEFAULT_MAX_SUBSCRIPTIONS
    )
    return value


def _notification_timeout() -> float:
    """Get the timeout for calls to subscribers.

    Returns:
        The setting `endpoints.subscriptions.notification_timeout`, in seconds.
    """
    value: Any = endpoints()["subscriptions"].get(
        "notification_timeout", DEFAULT_NOTIFICATION_TIMEOUT
    )
    return value


def _notification_result(
    subscription_id: str, result: str, http_status: int | None = None
) -> dict[str, Any]:
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
