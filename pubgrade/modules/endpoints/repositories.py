import logging
import string
from random import choice

from flask import current_app
from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import Unauthorized

from pubgrade.errors.exceptions import (
    RepositoryNotFound,
    URLNotFound,
    InternalServerError,
)

logger = logging.getLogger(__name__)


def register_repository(data: dict):
    """Register a new repository object.

    Args:
         data (dict): Request object containing URL of git repository.

    Returns:
        repository_object (dict): Dictionary of repository contents (
        identifier and access_token).

    Raises:
        URLNotFound: Raised when request data does not have url string.
        InternalServerError: Raised when it's unable to create unique
        identifier for the repository_object.
    """
    repository_object = {}
    try:
        repository_object["url"] = data["url"]
        # Needs to verify validity of repository url.
    except KeyError:
        raise URLNotFound

    db_collection = (
        current_app.config["FOCA"]
        .db.dbs["pubgradeStore"]
        .collections["repositories"]
        .client
    )
    retries = current_app.config["FOCA"].endpoints["repository"]["retries"]
    id_length: int = current_app.config["FOCA"].endpoints["repository"][
        "id_length"
    ]
    id_charset: str = current_app.config["FOCA"].endpoints["repository"][
        "id_charset"
    ]
    access_token_length: int = current_app.config["FOCA"].endpoints[
        "access_token"
    ]["length"]
    access_token_charset: str = current_app.config["FOCA"].endpoints[
        "access_token"
    ]["charset"]
    try:
        id_charset = eval(id_charset)
    except Exception:
        id_charset = "".join(sorted(set(id_charset)))
    try:
        access_token_charset = eval(access_token_charset)
    except Exception:
        access_token_charset = "".join(sorted(set(id_charset)))

    for i in range(retries):
        logger.debug(f"Trying to insert/update object: try {i}")
        repository_object["id"] = generate_id(
            charset=id_charset,
            length=id_length,
        )
        repository_object["access_token"] = str(
            generate_id(
                charset=access_token_charset, length=access_token_length
            )
        )
        try:
            db_collection.insert_one(repository_object)
            break
        except DuplicateKeyError:
            logger.error(
                f"DuplicateKeyError ({repository_object['id']}):  "
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

    if "_id" in repository_object:
        del repository_object["_id"]
    del repository_object["url"]
    logger.info(f"Added object with '{repository_object}'.")
    return repository_object


def get_repositories():
    """Retrieve available repositories.

    Returns:
        List of repository objects.

    Raises:
        RepositoryNotFound: Raised when there is no registered repository in
        the pubgrade.
    """
    db_collection = (
        current_app.config["FOCA"]
        .db.dbs["pubgradeStore"]
        .collections["repositories"]
        .client
    )

    cursor = db_collection.find({}, {"access_token": False, "_id": False})
    repos = list(cursor)

    for repo in repos:
        if "subscription_list" in repo:
            del repo["subscription_list"]
    return list(repos)


def generate_id(
    charset: str = "".join([string.ascii_lowercase, string.digits]),
    length: int = 6,
) -> str:
    """Generate random string based on allowed set of characters.

    Args:
        charset (str): String of allowed characters.
        length (int): Length of returned string.

    Returns:
        Random string of specified length and composed of defined set of
        allowed characters except '_' and '.' or '-' at index 0 and length-1
    """
    generated_string = ""
    counter = 0
    while counter < length:
        random_char = choice(charset)
        if random_char in "_":
            continue
        if counter == 0 or counter == (length - 1):
            if random_char in ".-" or random_char in string.digits:
                continue
        counter = counter + 1
        generated_string = generated_string + "".join(random_char)
    return generated_string


def get_repository(repo_id: str):
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
    db_collection = (
        current_app.config["FOCA"]
        .db.dbs["pubgradeStore"]
        .collections["repositories"]
        .client
    )
    try:
        repository_object = (
            db_collection.find(
                {"id": repo_id}, {"access_token": False, "_id": False}
            )
            .limit(1)
            .next()
        )
        if "subscription_list" in repository_object:
            del repository_object["subscription_list"]
        return repository_object
    except StopIteration:
        logger.error(
            f"Could not find repository with given identifier:" f" {repo_id}"
        )
        raise RepositoryNotFound


def modify_repository_info(repo_id: str, access_token: str, data: dict):
    """Modify registered repository.

    Args:
        repo_id (str): Unique identifier for the repository.
        access_token (str): Secret used to verify source is authorized.
        data (dict): Request data containing modified url of the repository.

    Returns:
        repository_object (dict): Dictionary object of created repository
        containing it's identifier and access_token.

    Raises:
        MongoError: Raised when object is unable to replace existing
        repository_object in mongodb.
        Unauthorized: Raised when access_token is invalid or not specified
        in request.
        RepositoryNotFound: Raised when repository is not found with given
        identifier.
    """
    db_collection_repository = (
        current_app.config["FOCA"]
        .db.dbs["pubgradeStore"]
        .collections["repositories"]
        .client
    )
    data_from_db = db_collection_repository.find_one({"id": repo_id})
    if data_from_db is None:
        logger.error(
            f"Could not find repository with given identifier: {repo_id}"
        )
        raise RepositoryNotFound
    if data_from_db["access_token"] != access_token:
        raise Unauthorized
    data["id"] = repo_id
    data["access_token"] = str(access_token)
    db_collection_repository.replace_one(
        filter={"id": repo_id}, replacement=data
    )
    del data["url"]
    return data


def delete_repository(repo_id: str, access_token: str):
    """Delete repository.

    Args:
        repo_id (str): Unique identifier for the repository.
        access_token (str): Secret used to verify source is authorized.

    Returns:
        repository delete count. (1 if repository is deleted, 0 if not
        deleted.)

    Raises:
        MongoError: Raised when object is unable to replace existing
        repository object in mongodb.
        Unauthorized: Raised when access_token is invalid or not specified
        in request.
        RepositoryNotFound: Raised when repository is not found with given
        identifier.
    """
    db_collection = (
        current_app.config["FOCA"]
        .db.dbs["pubgradeStore"]
        .collections["repositories"]
        .client
    )
    data = db_collection.find_one({"id": repo_id})
    if data is None:
        logger.error("Not Found any repository with id:" + repo_id)
        raise RepositoryNotFound
    if data["access_token"] != access_token:
        raise Unauthorized
    is_deleted = db_collection.delete_one({"id": repo_id})
    return is_deleted.deleted_count
