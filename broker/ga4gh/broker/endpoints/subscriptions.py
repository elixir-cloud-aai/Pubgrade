import datetime
import logging
from typing import Dict

import requests
from broker.errors.exceptions import (
    RequestException,
    RepositoryNotFound, UserNotFound, SubscriptionNotFound, BuildNotFound
)
from broker.ga4gh.broker.endpoints.repositories import generate_id
from flask import current_app
from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import Unauthorized

logger = logging.getLogger(__name__)


def test_create_user():
    """
    Right now this function is used to create user and will be deleted later.
    """
    db_collection = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['users'].client
    )
    db_collection.insert_one({'uid': '9fe2c4e93f654fdbb24c02b15259716c',
                              'name': 'Akash',
                              'user_access_token': 'c42a6d44e3d0'})


def register_subscription(uid: str, user_access_token: str, data: Dict):
    """Register new subscription.

    Args:
        uid: Unique identifier for user.
        user_access_token: Secret to verify user.
        data: Dictionary element of request received.

    Returns:
        subscription_id: Identifier generated for created subscription.

    Raises:
        RepositoryNotFound: Raised when there is no registered repository in
        the broker.
        Unauthorized: Raised when access_token is invalid or not specified
        in request.
        UserNotFound: Raised when there is no user with specified uid.

    Description:
        - Takes the uid, user_access_token, request_data.
        - Create client for collections (subscriptions, users, repositories)
        to read/write data.
        - Check if user with specified uid is available or not.
        - Verify if user access_token is valid.
        - Check if repository with specified identifier is available or not.
        - Generate a unique identifier for the subscription. (Retries 3
        times for generating unique identifier.)
        - Insert newly created subscription to the subscription collection.
        - Update subscription_list at subscribed user.
        - Update subscription_list at subscribed repository.
        - Returns subscription_id.

    """
    retries = 3
    db_collection_subscriptions = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['subscriptions'].client
    )
    db_collection_user = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['users'].client
    )
    db_collection_repositories = (
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
    data_from_db_user = db_collection_user.find_one({'uid': uid})
    data_from_db_repository = db_collection_repositories.find_one(
        {'id': data['repository_id']})
    if data_from_db_user is not None:
        if data_from_db_user['user_access_token'] == user_access_token:
            if data_from_db_repository is not None:
                for i in range(retries + 1):
                    logger.debug(f"Trying to insert/update object: try {i}" +
                                 str(data))
                    data['id'] = generate_id(
                        charset=id_charset,
                        length=id_length,
                    )
                    data['state'] = 'Inactive'
                    try:
                        db_collection_subscriptions.insert_one(data)
                        db_collection_user.update({"uid": uid}, {"$push": {
                            "subscription_list": data['id']}})
                        db_collection_repositories.update(
                            {"id": data['repository_id']},
                            {"$push": {"subscription_list": data['id']}})
                        break
                    except DuplicateKeyError:
                        continue
                return {"subscription_id": data['id']}
            else:
                raise RepositoryNotFound
        else:
            raise Unauthorized
    else:
        raise UserNotFound


def get_subscriptions(uid: str, user_access_token: str):
    """Get registered subscriptions for the user.

    Args:
        uid: Unique identifier for user.
        user_access_token: Secret to verify user.

    Returns:
        subscription_list: list of subscriptions registered by the user.

    Raises:
        SubscriptionNotFound: Raised when no subscription is available for
        the user.
        Unauthorized: Raised when access_token is invalid or not specified
        in request.
        UserNotFound: Raised when there is no user with specified uid.

    Description:
        - Takes the uid, user_access_token.
        - Create client for collections(users) to read/write data.
        - Check if user with specified uid is available or not.
        - Verify if user access_token is valid.
        - Fetch subscriptions from the database and append in list.
        - Returns the list.
    """
    db_collection_user = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['users'].client
    )
    data_from_db_user = db_collection_user.find_one({'uid': uid})
    if data_from_db_user is not None:
        if data_from_db_user['user_access_token'] == user_access_token:
            try:
                # data = db_collection_user.find(
                #     {'uid': uid},
                #     {'access_token': False, '_id': False}).limit(1).next()
                subscription_list = []
                for subscription_id in data_from_db_user['subscription_list']:
                    subscription_list.append(
                        {'subscription_id': subscription_id}
                    )
                return subscription_list
            except KeyError:
                raise SubscriptionNotFound
        else:
            raise Unauthorized
    else:
        raise UserNotFound


def get_subscription_info(uid: str, user_access_token: str,
                          subscription_id: str):
    """Get subscription information.

    Args:
        uid: Unique identifier for user.
        user_access_token: Secret to verify user.
        subscription_id: Identifier for subscriptions.

    Returns:
        subscription_object: Dictionary element of subscription.

    Raises:
        SubscriptionNotFound: Raised when no subscription is available for
        the user.
        Unauthorized: Raised when access_token is invalid or not specified
        in request.
        UserNotFound: Raised when there is no user with specified uid.

    Description:
        - Takes the uid, user_access_token and subscription_id.
        - Create client for collections(users, subscriptions) to read/write
        data.
        - Check if user with specified uid is available or not.
        - Verify if user access_token is valid.
        - Fetch subscriptions information from the subscriptions collection.
        - Remove _id, id and access_token.
        - Returns the subscription_object.
    """
    db_collection_user = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['users'].client
    )
    db_collection_subscriptions = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['subscriptions'].client
    )
    data_from_db_user = db_collection_user.find_one({'uid': uid})
    if data_from_db_user is not None:
        if data_from_db_user['user_access_token'] == user_access_token:
            try:
                subscription_object = db_collection_subscriptions.find_one(
                    {'id': subscription_id})
                del subscription_object['_id']
                del subscription_object['access_token']
                del subscription_object['id']
                return subscription_object
            except SubscriptionNotFound:
                raise SubscriptionNotFound
        else:
            raise Unauthorized
    else:
        raise UserNotFound


def delete_subscription(uid: str, user_access_token: str,
                        subscription_id: str):
    """Delete subscription.

    Args:
        uid: Unique identifier for user.
        user_access_token: Secret to verify user.
        subscription_id: Identifier for subscriptions.

    Returns:
        Delete count. (1 if subscription is deleted, 0 if not
        deleted.)

    Raises:
        SubscriptionNotFound: Raised when no subscription is available for
        the user.
        Unauthorized: Raised when access_token is invalid or not specified
        in request.
        UserNotFound: Raised when there is no user with specified uid.

    Description:
        - Takes the uid, user_access_token and subscription_id.
        - Create client for collections(users, subscriptions) to read/write
        data.
        - Check if user with specified uid is available or not.
        - Verify if user access_token is valid.
        - Delete subscriptions from the subscriptions collection.
        - Returns the delete count.
    """
    db_collection_user = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['users'].client
    )
    db_collection_subscriptions = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['subscriptions'].client
    )
    data_from_db_user = db_collection_user.find_one({'uid': uid})
    if data_from_db_user is not None:
        if data_from_db_user['user_access_token'] == user_access_token:
            try:
                data = db_collection_subscriptions.delete_one(
                    {'id': subscription_id})
            except SubscriptionNotFound:
                raise SubscriptionNotFound
            return data.deleted_count
        else:
            raise Unauthorized
    else:
        raise UserNotFound


def notify_subscriptions(subscription_id: str, image: str, build_id: str):
    """ Notifies subscriptions.

    Args:
        subscription_id: Identifier for subscription.
        image: Docker image to be updated at deployment.
        build_id: Build Identifier for build to be used for subscription.

    Raises:
        RequestException: Raised when something unexpected happen while
        requesting side-car service for deploying updates.
        SubscriptionNotFound: Raised when no subscription is available for
        the user.
        BuildNotFound: Raised when object with given build identifier was not
        found.

    Description:
        - Takes subscription identifier, image and build identifier.
        - Create client for collections(subscriptions, builds) to read/write
        data.
        - Retrieve build object using build identifier.
        - Retrieve subscription object using subscription identifier.
        - Check if subscription type is equal to build type.
        - Update subscription object for state, build_id and update timestamp.
        - Update on subscription collection too.
        - Create payload to request updates at deployment.
        - Send a request to deployment(side-car service).

    """
    db_collection_subscriptions = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['subscriptions'].client
    )
    db_collection_builds = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['builds'].client
    )
    try:
        build_object = db_collection_builds.find_one({'id': build_id})
        try:
            subscription_object = db_collection_subscriptions.find_one(
                {'id': subscription_id})
            subscription_type = subscription_object['type']
            value = subscription_object['value']
            if subscription_type in build_object['head_commit']:
                if build_object['head_commit'][subscription_type] == value:
                    subscription_object['state'] = 'Active'
                    subscription_object['build_id'] = build_id
                    subscription_object['updated_at'] = str(
                        datetime.datetime.now().isoformat())
                    del subscription_object['_id']
                    db_collection_subscriptions.update(
                        {"id": subscription_id},
                        {"$set": subscription_object})
                    url = subscription_object['callback_url']
                    payload = 'image={"image":"' + image + '"}&uuid='\
                              + subscription_object['access_token']
                    headers = {'Content-Type': 'application/x-www-form'
                                               '-urlencoded'}
                    try:
                        requests.request("POST", url, headers=headers,
                                         data=payload)
                    except requests.exceptions.Timeout:
                        # retry
                        subscription_object['state'] = 'Inactive'
                        subscription_object['updated_at'] = str(
                            datetime.datetime.now().isoformat())
                        del subscription_object['_id']
                        db_collection_subscriptions.update(
                            {"id": subscription_id},
                            {"$set": subscription_object})
                        raise RequestException
                    except requests.exceptions.TooManyRedirects:
                        subscription_object['state'] = 'Inactive'
                        subscription_object['updated_at'] = str(
                            datetime.datetime.now().isoformat())
                        del subscription_object['_id']
                        db_collection_subscriptions.update(
                            {"id": subscription_id},
                            {"$set": subscription_object})
                        raise RequestException
                    except requests.exceptions.RequestException:
                        subscription_object['state'] = 'Inactive'
                        subscription_object['updated_at'] = str(
                            datetime.datetime.now().isoformat())
                        del subscription_object['_id']
                        db_collection_subscriptions.update(
                            {"id": subscription_id},
                            {"$set": subscription_object})
                        raise RequestException
                else:
                    print('Value not matched')
            else:
                print('Type not matched')
        except SubscriptionNotFound:
            raise SubscriptionNotFound
    except BuildNotFound:
        raise BuildNotFound
