"""Registration and management of repositories."""

import logging
import secrets
import string
from typing import Any
import uuid

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import Unauthorized

from pubgrade.charsets import EXCLUDED, NOT_AT_ENDS, get_charset, usable
from pubgrade.errors.exceptions import (
    InternalServerError,
    RegistrationDisabled,
    RepositoryNotFound,
    UndeclaredBuildType,
    URLNotFound,
)
from pubgrade.settings import collection, endpoints

logger = logging.getLogger(__name__)

# Matches repositories that take new builds and subscriptions: not those that
# are being deleted
ACCEPTING: dict[str, Any] = {"deleting": {"$exists": False}}
# Fields of repositories that responses leave out
HIDDEN: dict[str, Any] = {"access_token": False, "_id": False, "deleting": False}


def register_repository(data: dict[str, Any]) -> dict[str, Any]:
    """Register a new repository object.

    Args:
         data (dict): Request object containing URL of git repository and,
         optionally, the build types that its builds may have
         (`build_types`).

    Returns:
        repository_object (dict): Dictionary of repository contents (
        identifier and access_token).

    Raises:
        URLNotFound: Raised when request data does not have url string.
        InternalServerError: Raised when it's unable to create unique
        identifier for the repository_object.
        RegistrationDisabled: Raised when registration is closed by the
        setting `endpoints.repository.registration_enabled`.
    """
    if not endpoints()["repository"].get("registration_enabled", True):
        raise RegistrationDisabled
    repository_object: dict[str, Any] = {}
    try:
        repository_object["url"] = data["url"]
        # Needs to verify validity of repository url.
    except KeyError:
        raise URLNotFound from None
    if "build_types" in data:
        repository_object["build_types"] = data["build_types"]

    db_collection = collection("repositories")
    retries = endpoints()["repository"]["retries"]
    id_length: int = endpoints()["repository"]["id_length"]
    id_charset = get_charset("repository", "id_charset")
    access_token_length: int = endpoints()["access_token"]["length"]
    access_token_charset = get_charset("access_token", "charset")

    for i in range(retries):
        logger.debug("Trying to insert/update object: try %s", i)
        repository_object["id"] = generate_id(
            charset=id_charset,
            length=id_length,
        )
        repository_object["access_token"] = str(
            generate_id(charset=access_token_charset, length=access_token_length)
        )
        try:
            db_collection.insert_one(repository_object)
            break
        except DuplicateKeyError:
            logger.error(
                "DuplicateKeyError (%s):  Key generated is already present.",
                repository_object["id"],
            )
            continue
    else:
        logger.error(
            "Could not generate unique identifier. Tried %s times.", retries + 1
        )
        raise InternalServerError

    repository_object.pop("_id", None)
    del repository_object["url"]
    repository_object.pop("build_types", None)
    logger.info("Added repository %s.", repository_object["id"])
    return repository_object


def get_repositories() -> list[dict[str, Any]]:
    """Retrieve available repositories.

    Returns:
        List of repository objects.

    Raises:
        RepositoryNotFound: Raised when there is no registered repository in
        the pubgrade.
    """
    db_collection = collection("repositories")

    cursor = db_collection.find({}, HIDDEN)
    repos = list(cursor)

    for repo in repos:
        if "subscription_list" in repo:
            del repo["subscription_list"]
    return list(repos)


def generate_id(
    charset: str = "".join([string.ascii_lowercase, string.digits]),
    length: int = 6,
) -> str:
    """Generate a random string from a set of characters.

    Characters are drawn with `secrets.choice`. Values never contain `_`, and
    don't start or end with `.`, `-` or a digit.

    Args:
        charset: Characters to draw from (cf. `pubgrade.charsets`).
        length: Length of the string.

    Returns:
        Random string of the given length.

    Raises:
        ValueError: If the characters leave none for the start and end of
            values.
    """
    if not usable(charset):
        raise ValueError(f"No character for the start and end of values in {charset!r}")
    generated_string = ""
    while len(generated_string) < length:
        random_char = secrets.choice(charset)
        if random_char in EXCLUDED:
            continue
        at_end = len(generated_string) in (0, length - 1)
        if at_end and random_char in NOT_AT_ENDS:
            continue
        generated_string += random_char
    return generated_string


def get_repository(repo_id: str) -> dict[str, Any]:
    """Retrieve repository info.

    Args:
        repo_id (str): Identifier of repository to be retrieved.

    Returns:
        repository_object (dict): Information of the specified repository also
        containing list of available builds for the repository.

    Raises:
        RepositoryNotFound: Raised when repository is not found with given
        identifier.
    """
    db_collection = collection("repositories")
    try:
        repository_object = db_collection.find({"id": repo_id}, HIDDEN).limit(1).next()
        if "subscription_list" in repository_object:
            del repository_object["subscription_list"]
        return repository_object
    except StopIteration:
        logger.error("Could not find repository with given identifier: %s", repo_id)
        raise RepositoryNotFound from None


def modify_repository_info(
    repo_id: str, access_token: str, data: dict[str, Any]
) -> dict[str, Any]:
    """Modify registered repository.

    Only the URL changes, and the build types if the request gives them
    (`build_types`): the repository keeps its identifier, access token,
    builds and subscriptions, also those with build types that it no longer
    declares.

    Args:
        repo_id (str): Unique identifier for the repository.
        access_token (str): Secret used to verify source is authorized.
        data (dict): Request data containing modified url of the repository
        and, optionally, its build types.

    Returns:
        repository_object (dict): Identifier and access token of the
        repository.

    Raises:
        URLNotFound: Raised when request data does not have url string.
        Unauthorized: Raised when access_token is invalid or not specified
        in request.
        RepositoryNotFound: Raised when repository is not found with given
        identifier.
    """
    db_collection_repository = collection("repositories")
    data_from_db = db_collection_repository.find_one({"id": repo_id})
    if data_from_db is None:
        logger.error("Could not find repository with given identifier: %s", repo_id)
        raise RepositoryNotFound
    if data_from_db["access_token"] != access_token:
        raise Unauthorized
    try:
        url = data["url"]
    except KeyError:
        raise URLNotFound from None
    changes: dict[str, Any] = {"url": url}
    if "build_types" in data:
        changes["build_types"] = data["build_types"]
    result = db_collection_repository.update_one({"id": repo_id}, {"$set": changes})
    if result.matched_count == 0:
        raise RepositoryNotFound
    logger.info("Modified repository %s.", repo_id)
    return {"id": repo_id, "access_token": data_from_db["access_token"]}


def check_build_types(repository: dict[str, Any], build_types: list[str]) -> None:
    """Check that a repository declares build types.

    Args:
        repository: The repository, as stored.
        build_types: Build types of a build or a subscription.

    Raises:
        UndeclaredBuildType: Raised when the repository doesn't declare one of
        them.
    """
    declared = repository.get("build_types", [])
    if any(build_type not in declared for build_type in build_types):
        raise UndeclaredBuildType


def accepts_additions(repo_id: str) -> bool:
    """Check whether a repository takes new builds and subscriptions.

    Args:
        repo_id: Identifier of the repository.

    Returns:
        Whether the repository exists and isn't being deleted.
    """
    found = collection("repositories").find_one(
        {"id": repo_id, **ACCEPTING}, {"_id": True}
    )
    return found is not None


def delete_repository(repo_id: str, access_token: str) -> None:
    """Delete a repository with its builds and subscriptions.

    The repository is marked first, so that it takes no new builds or
    subscriptions; those registered meanwhile remove themselves again (see
    `accepts_additions()`). With builds switched on, the pods and files of
    the repository's builds are removed. Then its subscriptions (also from
    their users' lists), its builds and the repository itself are deleted,
    the repository last. If this fails (e.g., a pod can't be deleted), the
    mark is removed and the data left stays, so that the request can be
    repeated; pods and files removed before stay removed. Deployments that
    have been notified keep their images.

    Args:
        repo_id (str): Unique identifier for the repository.
        access_token (str): Secret used to verify source is authorized.

    Raises:
        Unauthorized: Raised when access_token is invalid or not specified
        in request.
        RepositoryNotFound: Raised when repository is not found with given
        identifier, also if another request deleted it meanwhile.
        DeletePodError: Raised when the pod of a build can't be deleted.
    """
    # Imported here, as the module of builds imports this one (`generate_id`)
    from pubgrade.modules.endpoints.builds import (  # noqa: PLC0415
        stop_builds,
    )

    db_collection = collection("repositories")
    data = db_collection.find_one({"id": repo_id})
    if data is None:
        logger.error("Not Found any repository with id: %s", repo_id)
        raise RepositoryNotFound
    if data["access_token"] != access_token:
        raise Unauthorized
    # The builds as of the mark: builds registered later remove themselves
    # Each deletion has its own mark, so that one that fails removes only
    # its own, not that of another one in progress
    mark = uuid.uuid4().hex
    data = db_collection.find_one_and_update(
        {"id": repo_id},
        {"$set": {"deleting": mark}},
        return_document=ReturnDocument.AFTER,
    )
    if data is None:
        raise RepositoryNotFound
    build_ids: list[str] = data.get("build_list", [])
    subscription_ids = list(data.get("subscription_list", []))
    try:
        stop_builds(build_ids)
        db_collection_subscriptions = collection("subscriptions")
        subscription_ids = list(
            {
                *subscription_ids,
                *(
                    subscription["id"]
                    for subscription in db_collection_subscriptions.find(
                        {"repository_id": repo_id}, {"id": True, "_id": False}
                    )
                ),
            }
        )
        if subscription_ids:
            collection("users").update_many(
                {"subscription_list": {"$in": subscription_ids}},
                {"$pull": {"subscription_list": {"$in": subscription_ids}}},
            )
            db_collection_subscriptions.delete_many({"id": {"$in": subscription_ids}})
        if build_ids:
            collection("builds").delete_many({"id": {"$in": build_ids}})
        deleted = db_collection.delete_one({"id": repo_id}).deleted_count
    except Exception:
        # The repository takes builds and subscriptions again until the
        # request is repeated
        db_collection.update_one(
            {"id": repo_id, "deleting": mark}, {"$unset": {"deleting": ""}}
        )
        raise
    if deleted == 0:
        raise RepositoryNotFound
    logger.info(
        "Deleted repository %s with %s builds and %s subscriptions.",
        repo_id,
        len(build_ids),
        len(subscription_ids),
    )
