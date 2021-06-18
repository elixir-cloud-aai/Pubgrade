from math import exp
from broker.ga4gh.broker.endpoints.repositories import generate_id
from typing import Dict
from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import Unauthorized
from broker.errors.exceptions import (InternalServerError, NotFound, RepositoryNotFound)
import logging
from flask import (current_app)

logger = logging.getLogger(__name__)

def test_create_user():
    db_collection = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['users'].client
    )
    db_collection.insert_one({'uid':'9fe2c4e93f654fdbb24c02b15259716c',
    'name': 'Akash',
    'user_access_token': 'c42a6d44e3d0'})
    

def register_subscription(uid: str, user_access_token: str, data: Dict):
    retries=3
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
    data_from_DB_user = db_collection_user.find_one({'uid':uid})
    data_from_DB_repository = db_collection_repositories.find_one({'id':data['repository_id']})
    if data_from_DB_user != None:
        if data_from_DB_user['user_access_token'] == user_access_token:
            if data_from_DB_repository != None:
                for i in range(retries + 1):
                    logger.debug(f"Trying to insert/update object: try {i}" + str(data))
                    data['id'] = generate_id(
                        charset=id_charset, 
                        length=id_length, 
                    )
                    try:
                        db_collection_subscriptions.insert_one(data)
                        db_collection_user.update({"uid": uid}, {"$push":{"subscriptionList": data['id']}} )
                        db_collection_repositories.update({"id": data['repository_id']}, {"$push":{"subscriptionList": data['id']}} )
                        break
                    except DuplicateKeyError:
                        continue
                return {"subscription_id": data['id']}
            else:
                raise RepositoryNotFound
        else:
            raise Unauthorized
    else:
        raise NotFound


def get_subscriptions(uid: str, user_access_token: str):
    db_collection_user = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['users'].client
    )
    data_from_DB_user = db_collection_user.find_one({'uid':uid})
    if data_from_DB_user != None:
        if data_from_DB_user['user_access_token'] == user_access_token:
            try:
                data= db_collection_user.find( {'uid':uid}, {'access_token': False,'_id': False}).limit(1).next()
                response_data=[]
                for subscription_id in data['subscriptionList']:
                    response_data.append({'subscription_id': subscription_id})
                return response_data
            except KeyError:
                raise KeyError
        else:
            raise Unauthorized
    else:
        raise NotFound


def get_subscription_info(uid: str, user_access_token: str, subscription_id: str):
    db_collection_user = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['users'].client
    )
    db_collection_subscriptions = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['subscriptions'].client
    )
    data_from_DB_user = db_collection_user.find_one({'uid':uid})
    if data_from_DB_user != None:
        if data_from_DB_user['user_access_token'] == user_access_token:
            data = db_collection_subscriptions.find_one({'id':subscription_id})
            data['state'] = 'Active'
            data['build_type'] = 'production' # to be removed
            data['build_id'] = 'gfdnjk'
            data['updated_at'] = '2021-06-11T17:32:28+00:00'
            del data['_id']
            del data['access_token']
            del data['id']
            return data
        else:
            raise Unauthorized
    else:
        raise NotFound


def delete_subscription(uid: str, user_access_token: str, subscription_id: str):
    db_collection_user = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['users'].client
    )
    db_collection_subscriptions = (
        current_app.config['FOCA'].db.dbs['brokerStore'].
        collections['subscriptions'].client
    )
    data_from_DB_user = db_collection_user.find_one({'uid':uid})
    if data_from_DB_user != None:
        if data_from_DB_user['user_access_token'] == user_access_token:
            try:
                data = db_collection_subscriptions.delete_one({'id':subscription_id})
            except NotFound:
                raise NotFound
            return data.deleted_count
        else:
            raise Unauthorized
    else:
        raise NotFound