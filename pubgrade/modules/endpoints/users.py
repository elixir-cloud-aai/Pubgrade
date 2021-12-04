import logging

from pubgrade.errors.exceptions import (
    UserNotFound,
    InternalServerError,
    URLNotFound
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
        user_object['name'] = data['name']
        # Needs to verify validity of user url.
    except KeyError:
        raise URLNotFound

    db_collection = (
        current_app.config['FOCA'].db.dbs['pubgradeStore'].
        collections['users'].client
    )
    retries = current_app.config['FOCA'].endpoints['repository']['retries']
    id_length: int = (
        current_app.config['FOCA'].endpoints['repository']['id_length']
    )
    id_charset: str = (
        current_app.config['FOCA'].endpoints['repository']['id_charset']
    )
    access_token_length: int = (
        current_app.config['FOCA'].endpoints['access_token']['length']
    )
    access_token_charset: str = (
        current_app.config['FOCA'].endpoints['access_token']['charset']
    )
    try:
        id_charset = eval(id_charset)
    except Exception:
        id_charset = ''.join(sorted(set(id_charset)))
    try:
        access_token_charset = eval(access_token_charset)
    except Exception:
        access_token_charset = ''.join(sorted(set(id_charset)))

    for i in range(retries):
        logger.debug(f"Trying to insert/update object: try {i}")
        user_object['uid'] = generate_id(
            charset=id_charset,
            length=id_length,
        )
        user_object['user_access_token'] = str(
            generate_id(charset=access_token_charset,
                        length=access_token_length))
        user_object['isVerified'] = False
        try:
            db_collection.insert_one(user_object)
            break
        except DuplicateKeyError:
            logger.error(f"DuplicateKeyError ({user_object['uid']}):  "
                         f"Key generated"
                         f" is already present.")
            continue
    else:
        logger.error(
                    f"Could not generate unique identifier."
                    f" Tried {retries + 1} times."
                )
        raise InternalServerError

    if '_id' in user_object:
        del user_object['_id']
        del user_object['isVerified']
    # del user_object['name']
    logger.info(f"Added object with '{user_object}'.")
    return user_object


def get_users(super_user_id: str, super_user_access_token: str):
    """Retrieve available repositories.

    Returns:
        List of repository objects.

    Raises:
        RepositoryNotFound: Raised when there is no registered repository in
        the pubgrade.
    """
    # if 'X-Super-User-Id' not in data or 'X-Super-User-Access-Token' not in
    # data:
    #     raise BadRequest

    if super_user_id != current_app.config['FOCA'].endpoints[
         'subscriptions']['admin_user']['uid']:
        raise UserNotFound

    if super_user_access_token != current_app.config['FOCA'].endpoints[
         'subscriptions']['admin_user']['user_access_token']:
        raise Unauthorized

    db_collection = (
        current_app.config['FOCA'].db.dbs['pubgradeStore'].
        collections['users'].client
    )

    cursor = db_collection.find(
        {}, {'access_token': False, '_id': False}
    )
    repos = list(cursor)

    # for repo in repos:
    #     if 'subscription_list' in repo:
    #         del repo['subscription_list']
    return list(repos)


def toggle_user_status(super_user_id: str, super_user_access_token: str,
                       uid: str, status: bool):
    if super_user_id != \
            current_app.config['FOCA'].endpoints['subscriptions'][
                'admin_user']['uid']:
        raise UserNotFound

    if super_user_access_token != current_app.config['FOCA'].endpoints[
         'subscriptions']['admin_user']['user_access_token']:
        raise Unauthorized

    db_collection_user = (
        current_app.config['FOCA'].db.dbs['pubgradeStore'].
        collections['users'].client
    )
    data_from_db = db_collection_user.find_one({'uid': uid})
    if data_from_db is None:
        logger.error(
                f"Could not find repository with given identifier: {uid}"
                )
        raise UserNotFound
    data_from_db['isVerified'] = status
    db_collection_user.replace_one(
        filter={'uid': uid},
        replacement=data_from_db)
    if status:
        return "User verified successfully."
    else:
        return "User unverified successfully."
