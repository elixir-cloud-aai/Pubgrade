import logging
import string
from random import choice
from typing import (Dict)

from flask import (current_app)
from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import Unauthorized

from broker.errors.exceptions import (
    InternalServerError,
    NotFound,
    RepositoryNotFound
)

logger = logging.getLogger(__name__)


def register_repository(data: Dict):
    retries = 3
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

        data['id'] = generate_id(
            charset=id_charset,
            length=id_length,
        )
        try:
            data['access_token'] = str(generate_id(id_charset, 32))
            db_collection.insert_one(data)
            break
        except DuplicateKeyError:
            continue
    else:
        logger.error(
            f"Could not generate unique identifier. Tried {retries + 1} times."
        )
        raise InternalServerError
    del data['_id']
    del data['url']
    logger.info(f"Added object with '{data}'.")
    return data


def get_repositories():
    db_collection = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['repositories'].client
    )
    try:
        cursor = db_collection.find(
            {}, {'access_token': False, '_id': False}
        )
        data = list(cursor)
        for repo in data:
            if 'subscription_list' in repo:
                del repo['subscription_list']
        return list(data)
    except StopIteration:
        raise NotFound


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


def get_repository_info(id: str):
    db_collection = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['repositories'].client
    )
    try:
        data = db_collection.find(
            {'id': id}, {'access_token': False, '_id': False}
        ).limit(1).next()
        if 'subscriptionList' in data:
            del data['subscriptionList']
        return data
    except RepositoryNotFound:
        raise NotFound


def modify_repository_info(id: str, access_token: str, data: Dict):
    db_collection = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['repositories'].client
    )
    data_from_db = db_collection.find_one({'id': id})
    if data_from_db is not None:
        if data_from_db['access_token'] == access_token:
            try:
                data['id'] = id
                data['access_token'] = str(access_token)
                db_collection.replace_one(
                    filter={'id': id},
                    replacement=data,
                )
                del data['url']
                return data
            except RepositoryNotFound:
                raise NotFound
        else:
            raise Unauthorized
    else:
        raise NotFound


def delete_repository(id: str, access_token: str):
    db_collection = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['repositories'].client
    )
    # try:
    data = db_collection.find_one({'id': id})
    if data is not None:
        if data['access_token'] == access_token:
            try:
                is_deleted = db_collection.delete_one({'id': id})
                return is_deleted.deleted_count
            except RepositoryNotFound:
                logger.error('Not Found any repository with id:' + id)
                raise NotFound
        else:
            raise Unauthorized
    else:
        raise NotFound
