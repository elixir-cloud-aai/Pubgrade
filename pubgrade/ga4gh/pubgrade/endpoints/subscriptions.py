import datetime
import logging

import requests
from pubgrade.errors.exceptions import (
    RepositoryNotFound, UserNotFound, SubscriptionNotFound, BuildNotFound,
    RequestNotSent, InternalServerError
)
from pubgrade.ga4gh.pubgrade.endpoints.repositories import generate_id
from flask import current_app
from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import Unauthorized

logger = logging.getLogger(__name__)


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
    """
    db_collection_subscriptions = (
        current_app.config['FOCA'].db.dbs['pubgradeStore'].
        collections['subscriptions'].client
    )
    db_collection_user = (
        current_app.config['FOCA'].db.dbs['pubgradeStore'].
        collections['users'].client
    )
    db_collection_repositories = (
        current_app.config['FOCA'].db.dbs['pubgradeStore'].
        collections['repositories'].client
    )
    retries = current_app.config['FOCA'].endpoints['repository']['retries']
    id_length: int = (
        current_app.config['FOCA'].endpoints['repository']['id_length']
    )
    id_charset: str = (
        current_app.config['FOCA'].endpoints['repository']['id_charset']
    )
    try:
        id_charset = eval(id_charset)
    except Exception:
        id_charset = ''.join(sorted(set(id_charset)))
    data_from_db_user = db_collection_user.find_one({'uid': uid})
    data_from_db_repository = db_collection_repositories.find_one(
        {'id': data['repository_id']})
    if data_from_db_user is None:
        raise UserNotFound
    if data_from_db_user['user_access_token'] != user_access_token:
        raise Unauthorized
    if data_from_db_repository is None:
        raise RepositoryNotFound
    for i in range(retries):
        logger.debug(f"Trying to insert/update object: try {i}" +
                     str(data))
        data['id'] = generate_id(
            charset=id_charset,
            length=id_length,
        )
        data['state'] = 'Inactive'
        try:
            db_collection_subscriptions.insert_one(data)
            # Updates subscription_list at both user and subscribed repository.
            db_collection_user.update_one({"uid": uid}, {"$push": {
                "subscription_list": data['id']}})
            db_collection_repositories.update_one(
                {"id": data['repository_id']},
                {"$push": {"subscription_list": data['id']}})
            break
        except DuplicateKeyError:
            logger.error(f"DuplicateKeyError ({data['id']}): Key "
                         f"generated is already present.")
            continue
    else:
        logger.error(
            f"Could not generate unique identifier."
            f" Tried {retries + 1} times."
        )
        raise InternalServerError
    return {"subscription_id": data['id']}


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
        current_app.config['FOCA'].db.dbs['pubgradeStore'].
        collections['users'].client
    )
    data_from_db_user = db_collection_user.find_one({'uid': uid})
    if data_from_db_user is None:
        raise UserNotFound
    if data_from_db_user['user_access_token'] != user_access_token:
        raise Unauthorized
    try:
        subscription_list = []
        for subscription_id in data_from_db_user['subscription_list']:
            subscription_list.append(
                {'subscription_id': subscription_id}
            )
        return subscription_list
    except KeyError:
        raise SubscriptionNotFound


def get_subscription_info(uid: str, user_access_token: str,
                          subscription_id: str):
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
        current_app.config['FOCA'].db.dbs['pubgradeStore'].
        collections['users'].client
    )
    db_collection_subscriptions = (
        current_app.config['FOCA'].db.dbs['pubgradeStore'].
        collections['subscriptions'].client
    )
    data_from_db_user = db_collection_user.find_one({'uid': uid})
    if data_from_db_user is None:
        raise UserNotFound
    if data_from_db_user['user_access_token'] != user_access_token:
        raise Unauthorized
    subscription_object = db_collection_subscriptions.find_one(
            {'id': subscription_id})
    if subscription_object is None:
        raise SubscriptionNotFound
    del subscription_object['_id']
    del subscription_object['access_token']
    return subscription_object


def delete_subscription(uid: str, user_access_token: str,
                        subscription_id: str):
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
        current_app.config['FOCA'].db.dbs['pubgradeStore'].
        collections['users'].client
    )
    db_collection_subscriptions = (
        current_app.config['FOCA'].db.dbs['pubgradeStore'].
        collections['subscriptions'].client
    )
    data_from_db_user = db_collection_user.find_one({'uid': uid})
    if data_from_db_user is None:
        raise UserNotFound
    if data_from_db_user['user_access_token'] != user_access_token:
        raise Unauthorized
    data = db_collection_subscriptions.delete_one(
            {'id': subscription_id})
    if data.deleted_count > 0:
        return data.deleted_count
    else:
        raise SubscriptionNotFound


def notify_subscriptions(subscription_id: str, image: str, build_id: str):
    """ Notifies subscriptions.

    Function sends request on callback URL set by user on registering
    build after build completion (called at
    `pubgrade.ga4gh.pubgrade.endpoints.builds`) if subscription type is equal
    to build type.

    Args:
        subscription_id (str): Identifier for subscription.
        image (str): Docker image to be updated at deployment.
        build_id (str): Build Identifier for build to be used for subscription.

    Raises:
        RequestException: Raised when something unexpected happen while
        requesting side-car service for deploying updates.
        SubscriptionNotFound: Raised when no subscription is available for
        the user.
        BuildNotFound: Raised when object with given build identifier was not
        found.
    """
    db_collection_subscriptions = (
        current_app.config['FOCA'].db.dbs['pubgradeStore'].
        collections['subscriptions'].client
    )
    db_collection_builds = (
        current_app.config['FOCA'].db.dbs['pubgradeStore'].
        collections['builds'].client
    )
    build_object = db_collection_builds.find_one({'id': build_id})
    if build_object is None:
        raise BuildNotFound
    try:
        subscription_object = db_collection_subscriptions.find_one(
            {'id': subscription_id})
        subscription_type = subscription_object['type']
        value = subscription_object['value']
        if subscription_type in build_object['head_commit']:
            # Check if subscription type is equal to build type.
            if build_object['head_commit'][subscription_type] == value:
                # Update subscription object
                subscription_object['state'] = 'Active'
                subscription_object['build_id'] = build_id
                subscription_object['updated_at'] = str(
                    datetime.datetime.now().isoformat())
                del subscription_object['_id']
                db_collection_subscriptions.update_one(
                    {"id": subscription_id},
                    {"$set": subscription_object})
                # Retrieve callback URL for the side-car service (at
                # deployment) from subscription collection, build payload
                # and send request.
                url = subscription_object['callback_url']
                payload = 'image={"image":"' + image + '"}&uuid='\
                          + subscription_object['access_token']
                headers = {'Content-Type': 'application/x-www-form'
                                           '-urlencoded'}
                try:
                    requests.request("POST", url, headers=headers,
                                     data=payload)
                except requests.exceptions.Timeout:
                    subscription_object['state'] = 'Inactive'
                    subscription_object['updated_at'] = str(
                        datetime.datetime.now().isoformat())
                    db_collection_subscriptions.update_one(
                        {"id": subscription_id},
                        {"$set": subscription_object})
                    raise RequestNotSent
                except requests.exceptions.TooManyRedirects:
                    subscription_object['state'] = 'Inactive'
                    subscription_object['updated_at'] = str(
                        datetime.datetime.now().isoformat())
                    db_collection_subscriptions.update_one(
                        {"id": subscription_id},
                        {"$set": subscription_object})
                    raise RequestNotSent
                except requests.exceptions.RequestException:
                    subscription_object['state'] = 'Inactive'
                    subscription_object['updated_at'] = str(
                        datetime.datetime.now().isoformat())
                    db_collection_subscriptions.update_one(
                        {"id": subscription_id},
                        {"$set": subscription_object})
                    raise RequestNotSent
            else:
                print('Value not matched')
        else:
            print('Type not matched')
    except TypeError:
        raise SubscriptionNotFound
