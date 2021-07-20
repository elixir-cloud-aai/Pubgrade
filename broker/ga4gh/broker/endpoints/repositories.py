import logging
import string
from random import choice
from typing import (Dict)

from flask import (current_app)
from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import Unauthorized

from broker.errors.exceptions import (
    InternalServerError,
    RepositoryNotFound, MongoError, URLNotFound
)

logger = logging.getLogger(__name__)


def register_repository(data: Dict):
    """Register a new repository.

    Args:
         data: Dictionary element of request received.

    Returns:
        repository_object: Dictionary element of Repository created along with
        identifier and access_token.

    Description:
        - Takes request data.
        - Creates a repository object using url in request data.
        - Generate a unique identifier for the object. (Retries 3 times for
        generating unique identifier.)
        - Generates access_token of 32 characters. (access_token will be
        used later for operations like creating a new build, updating build
        completion.)
        - Inserts object in mongodb.
        - Returns id and access_token for the repository_object created.

    Raises:
        URLNotFound: Raised when request data does not have url string.
        InternalServerError: Raised when it's unable to create unique
        identifier for the repository_object.


    """
    retries = 3
    repository_object = {}
    try:
        repository_object['url'] = data['url']
        # Needs to verify validity of repository url.
    except KeyError:
        raise URLNotFound
    db_collection = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['repositories'].client
    )
    id_length = (
        current_app.config['FOCA'].endpoints['repository']['id_length']
    )
    id_charset: str = (
        current_app.config['FOCA'].endpoints['repository']['id_charset']
    )
    try:
        id_charset = eval(id_charset)
    except Exception:
        id_charset = ''.join(sorted(set(id_charset)))

    for i in range(retries + 1):
        logger.debug(f"Trying to insert/update object: try {i}")

        repo_id = generate_id(
            charset=id_charset,
            length=id_length,
        )
        try:
            access_token = str(generate_id(id_charset, 32))
            repository_object['id'] = repo_id
            repository_object['access_token'] = access_token
            db_collection.insert_one(repository_object)
            break
        except DuplicateKeyError:
            continue
    else:
        logger.error(
            f"Could not generate unique identifier. Tried {retries + 1} times."
        )
        raise InternalServerError
    del repository_object['_id']
    del repository_object['url']
    logger.info(f"Added object with '{repository_object}'.")
    return repository_object


def get_repositories():
    """Get available Repositories.

    Returns:
        list of repository_objects

    Description:
        - Fetches all repositories from the mongodb.
        - Removes subscription_list if present.
        - Returns list of repository_objects.

    Raises:
        RepositoryNotFound: Raised when there is no registered repository in
        the broker.

    """
    db_collection = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['repositories'].client
    )
    try:
        cursor = db_collection.find(
            {}, {'access_token': False, '_id': False}
        )
        repository_object = list(cursor)
        for repo in repository_object:
            if 'subscription_list' in repo:
                del repo['subscription_list']
        return list(repository_object)
    except StopIteration:
        raise RepositoryNotFound


def generate_id(
        charset: str = ''.join([string.ascii_lowercase, string.digits]),
        length: int = 6
) -> str:
    """Generate random string based on allowed set of characters.

    Args:
        charset: String of allowed characters.
        length: Length of returned string.

    Returns:
        Random string of specified length and composed of defined set of
        allowed characters except '_' and '.' or '-' at index 0 and length-1
    """
    generated_string = ''
    counter = 0
    while counter < length:
        random_char = choice(charset)
        if random_char in '_':
            continue
        if counter == 0 or counter == (length - 1):
            if random_char in '.-' or random_char in string.digits:
                continue
        counter = counter + 1
        generated_string = generated_string + ''.join(random_char)
    return generated_string


def get_repository_info(repo_id: str):
    """Get repository info.

    Args:
        repo_id: Identifier of repository to be retrieved.

    Returns:
        repository_object: Information of required repository also containing
        list of available builds.

    Description:
        - Takes the repository identifier.
        - Fetches repository object with specified id from mongodb without
        access_token.
        - Removes subscription_list if present.
        - Returns repository object.

    Raises:
        RepositoryNotFound: Raised when repository is not found with given
        identifier.
    """
    db_collection = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['repositories'].client
    )
    try:
        repository_object = db_collection.find(
            {'id': repo_id}, {'access_token': False, '_id': False}
        ).limit(1).next()
        if 'subscription_list' in repository_object:
            del repository_object['subscription_list']
        return repository_object
    except StopIteration:
        raise RepositoryNotFound


def modify_repository_info(repo_id: str, access_token: str, data: Dict):
    """Modify already registered repository.

    Args:
        repo_id: Unique identifier for the repository.
        access_token: Secret used to verify source is authorized.
        data: Request data containing modified url of the repository.

    Returns:
        repository_object: Dictionary element of Repository created along with
        identifier and access_token.

    Raises:
        MongoError: Raised when object is unable to replace existing
        repository_object in mongodb.
        Unauthorized: Raised when access_token is invalid or not specified
        in request.
        RepositoryNotFound: Raised when repository is not found with given
        identifier.

    Description:
        - Takes repository_id, access_token and request data.
        - Check if repository with specified identifier is available or not.
        - Verify access_token.
        - Modify the specified repository using repository collection.
        - Returns repository_object.

    """
    db_collection_repository = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['repositories'].client
    )
    data_from_db = db_collection_repository.find_one({'id': repo_id})
    if data_from_db is not None:
        if data_from_db['access_token'] == access_token:
            try:
                data['id'] = repo_id
                data['access_token'] = str(access_token)
                db_collection_repository.replace_one(
                    filter={'id': repo_id},
                    replacement=data,
                )
                del data['url']
                return data
            except Exception:
                raise MongoError
        else:
            raise Unauthorized
    else:
        raise RepositoryNotFound


def delete_repository(repo_id: str, access_token: str):
    """Delete repository.

    Args:
        repo_id: Unique identifier for the repository.
        access_token: Secret used to verify source is authorized.

    Returns:
        repository delete count. (1 if repository is deleted, 0 if not
        deleted.)

    Raises:
        MongoError: Raised when object is unable to replace existing
        repository_object in mongodb.
        Unauthorized: Raised when access_token is invalid or not specified
        in request.
        RepositoryNotFound: Raised when repository is not found with given
        identifier.

    Description:
        - Takes repository_id and access_token.
        - Check if repository with specified identifier is available or not.
        - Verify access_token.
        - Delete the specified repository using repository collection.
        - Returns delete count.

    """
    db_collection = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['repositories'].client
    )
    # try:
    data = db_collection.find_one({'id': repo_id})
    if data is not None:
        if data['access_token'] == access_token:
            try:
                is_deleted = db_collection.delete_one({'id': repo_id})
                return is_deleted.deleted_count
            except Exception:
                raise MongoError
        else:
            raise Unauthorized
    else:
        logger.error('Not Found any repository with id:' + repo_id)
        raise RepositoryNotFound
