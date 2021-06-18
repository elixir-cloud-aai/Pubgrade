from typing import (Dict)
from random import choice

from flask import (current_app)
import string
import logging

from pymongo.errors import DuplicateKeyError
from broker.errors.exceptions import (InternalServerError, NotFound)

logger = logging.getLogger(__name__)

def register_repository(data: Dict):
    retries=3
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
            hash = generate_id(id_charset,32)
            data['access_token'] = str(hash)
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
        cursor= db_collection.find( 
        {}, {'access_token': False, '_id': False}
        )
        data=list(cursor)
        return list(data)
    except StopIteration:
        raise NotFound


def generate_id(
    charset: str = ''.join([string.ascii_letters, string.digits]),
    length: int = 6
) -> str:
    """Generate random string based on allowed set of characters.
    Args:
        charset: String of allowed characters.
        length: Length of returned string.
    Returns:
        Random string of specified length and composed of defined set of
        allowed characters.
    """
    return ''.join(choice(charset) for __ in range(length))