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
    db_collection = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['users'].client
    )
    db_collection.insert_one({'uid': '9fe2c4e93f654fdbb24c02b15259716c',
                              'name': 'Akash',
                              'user_access_token': 'c42a6d44e3d0'})


def register_subscription(uid: str, user_access_token: str, data: Dict):
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
                response_data = []
                for subscription_id in data_from_db_user['subscription_list']:
                    response_data.append({'subscription_id': subscription_id})
                return response_data
            except SubscriptionNotFound:
                raise SubscriptionNotFound
        else:
            raise Unauthorized
    else:
        raise UserNotFound


def get_subscription_info(uid: str, user_access_token: str,
                          subscription_id: str):
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
                data = db_collection_subscriptions.find_one(
                    {'id': subscription_id})
                del data['_id']
                del data['access_token']
                del data['id']
                return data
            except SubscriptionNotFound:
                raise SubscriptionNotFound
        else:
            raise Unauthorized
    else:
        raise UserNotFound


def delete_subscription(uid: str, user_access_token: str,
                        subscription_id: str):
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
    db_collection_subscriptions = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['subscriptions'].client
    )
    db_collection_builds = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['builds'].client
    )
    try:
        data_build = db_collection_builds.find_one({'id': build_id})
        try:
            data = db_collection_subscriptions.find_one({'id':
                                                        subscription_id})
            subscription_type = data['type']
            value = data['value']
            if subscription_type in data_build['head_commit']:
                if data_build['head_commit'][subscription_type] == value:
                    data['state'] = 'Active'
                    data['build_id'] = build_id
                    data['updated_at'] = str(
                        datetime.datetime.now().isoformat())
                    del data['_id']
                    db_collection_subscriptions.update({"id": subscription_id},
                                                       {"$set": data})
                    url = data['callback_url']
                    payload = 'image={"image":"' + image + '"}&uuid=' + data[
                        'access_token']
                    headers = {'Content-Type': 'application/x-www-form'
                                               '-urlencoded'}
                    try:
                        requests.request("POST", url, headers=headers,
                                         data=payload)
                    except requests.exceptions.Timeout:
                        # retry
                        data['state'] = 'Inactive'
                        data['updated_at'] = str(
                            datetime.datetime.now().isoformat())
                        del data['_id']
                        db_collection_subscriptions.update(
                            {"id": subscription_id},
                            {"$set": data})
                        raise RequestException
                    except requests.exceptions.TooManyRedirects:
                        data['state'] = 'Inactive'
                        data['updated_at'] = str(
                            datetime.datetime.now().isoformat())
                        del data['_id']
                        db_collection_subscriptions.update(
                            {"id": subscription_id},
                            {"$set": data})
                        raise RequestException
                    except requests.exceptions.RequestException as e:
                        data['state'] = 'Inactive'
                        data['updated_at'] = str(
                            datetime.datetime.now().isoformat())
                        del data['_id']
                        db_collection_subscriptions.update(
                            {"id": subscription_id},
                            {"$set": data})
                        raise RequestException
                else:
                    print('Value not matched')
            else:
                print('Type not matched')
        except SubscriptionNotFound:
            raise SubscriptionNotFound
    except BuildNotFound:
        raise BuildNotFound
