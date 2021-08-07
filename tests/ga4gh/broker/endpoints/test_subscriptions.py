"""Tests for /subscriptions endpoint """
from pprint import pprint

import mongomock
import pytest
from flask import Flask
from foca.models.config import Config, MongoConfig
from werkzeug.exceptions import Unauthorized

from broker.errors.exceptions import RepositoryNotFound, UserNotFound, \
    SubscriptionNotFound
from broker.ga4gh.broker.endpoints.subscriptions import register_subscription, \
    get_subscriptions, get_subscription_info
from tests.ga4gh.mock_data import MONGO_CONFIG, ENDPOINT_CONFIG, \
    MOCK_REPOSITORIES, MOCK_BUILD_INFO, MOCK_BUILD_INFO_2, MOCK_USER, \
    MOCK_SUBSCRIPTION_INFO, SUBSCRIPTION_PAYLOAD, MOCK_USER_DB


class TestSubscriptions:
    app = Flask(__name__)

    def setup(self):
        self.app.config['FOCA'] = \
            Config(db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
        self.app.config['FOCA'].db.dbs['brokerStore']. \
            collections['repositories'].client = mongomock.MongoClient(
        ).db.collection
        self.app.config['FOCA'].db.dbs['brokerStore']. \
            collections['builds'].client = mongomock.MongoClient(
        ).db.collection
        self.app.config['FOCA'].db.dbs['brokerStore']. \
            collections['users'].client = mongomock.MongoClient(
        ).db.collection
        self.app.config['FOCA'].db.dbs['brokerStore']. \
            collections['subscriptions'].client = mongomock.MongoClient(
        ).db.collection
        for repository in MOCK_REPOSITORIES:
            self.app.config['FOCA'].db.dbs['brokerStore']. \
                collections['repositories'].client.insert_one(
                repository).inserted_id
        self.app.config['FOCA'].db.dbs['brokerStore']. \
            collections['builds'].client.insert_one(
            MOCK_BUILD_INFO).inserted_id
        self.app.config['FOCA'].db.dbs['brokerStore']. \
            collections['builds'].client.insert_one(
            MOCK_BUILD_INFO_2).inserted_id
        self.app.config['FOCA'].db.dbs['brokerStore']. \
            collections['users'].client.insert_one(
            MOCK_USER).inserted_id

    def insert_subscription(self):
        self.app.config['FOCA'].db.dbs['brokerStore']. \
            collections['users'].client.insert_one(
            MOCK_USER_DB).inserted_id
        self.app.config['FOCA'].db.dbs['brokerStore']. \
            collections['subscriptions'].client.insert_one(
            MOCK_SUBSCRIPTION_INFO).inserted_id

    def test_register_subscription(self):
        self.setup()
        with self.app.app_context():
            res = register_subscription(MOCK_USER['uid'], MOCK_USER[
                'user_access_token'], SUBSCRIPTION_PAYLOAD)
            data = self.app.config['FOCA'].db.dbs['brokerStore']. \
                collections['repositories'].client.find_one(
                {"id": SUBSCRIPTION_PAYLOAD['repository_id']})
            subscription = self.app.config['FOCA'].db.dbs['brokerStore']. \
                collections['subscriptions'].client.find_one(
                {"id": res['subscription_id']})
            assert isinstance(res, dict)
            assert res['subscription_id'] in data['subscription_list']
            assert subscription['state'] == 'Inactive'

    def test_register_subscription_repo_not_found(self):
        self.setup()
        with self.app.app_context():
            with pytest.raises(RepositoryNotFound):
                SUBSCRIPTION_PAYLOAD['repository_id'] = 'abcd'
                register_subscription(MOCK_USER['uid'], MOCK_USER[
                    'user_access_token'], SUBSCRIPTION_PAYLOAD)

    def test_register_subscription_unauthorized(self):
        self.setup()
        with self.app.app_context():
            with pytest.raises(Unauthorized):
                MOCK_USER['user_access_token'] = 'mock_access_token'
                register_subscription(MOCK_USER['uid'], MOCK_USER[
                    'user_access_token'], SUBSCRIPTION_PAYLOAD)

    def test_register_subscription_user_not_found(self):
        self.setup()
        with self.app.app_context():
            with pytest.raises(UserNotFound):
                MOCK_USER['uid'] = 'mock_uid'
                register_subscription(MOCK_USER['uid'], MOCK_USER[
                    'user_access_token'], SUBSCRIPTION_PAYLOAD)

    def test_get_subscriptions(self):
        self.app.config['FOCA'] = \
            Config(db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
        self.app.config['FOCA'].db.dbs['brokerStore']. \
            collections['repositories'].client = mongomock.MongoClient(
        ).db.collection
        self.app.config['FOCA'].db.dbs['brokerStore']. \
            collections['builds'].client = mongomock.MongoClient(
        ).db.collection
        self.app.config['FOCA'].db.dbs['brokerStore']. \
            collections['users'].client = mongomock.MongoClient(
        ).db.collection
        self.app.config['FOCA'].db.dbs['brokerStore']. \
            collections['subscriptions'].client = mongomock.MongoClient(
        ).db.collection
        for repository in MOCK_REPOSITORIES:
            self.app.config['FOCA'].db.dbs['brokerStore']. \
                collections['repositories'].client.insert_one(
                repository).inserted_id
        self.app.config['FOCA'].db.dbs['brokerStore']. \
            collections['builds'].client.insert_one(
            MOCK_BUILD_INFO).inserted_id
        self.app.config['FOCA'].db.dbs['brokerStore']. \
            collections['builds'].client.insert_one(
            MOCK_BUILD_INFO_2).inserted_id
        self.app.config['FOCA'].db.dbs['brokerStore']. \
            collections['users'].client.insert_one(
            MOCK_USER_DB).inserted_id
        with self.app.app_context():
            res = get_subscriptions(MOCK_USER['uid'], MOCK_USER[
                'user_access_token'])
            assert isinstance(res, list)
            assert res[0]['subscription_id'] == MOCK_USER_DB[
                'subscription_list'][0]

    def test_get_subscriptions_subscription_not_found(self):
        self.setup()
        self.app.config['FOCA'].db.dbs['brokerStore'].collections[
            'users'].client.insert_one(MOCK_USER_DB).inserted_id
        with self.app.app_context():
            with pytest.raises(SubscriptionNotFound):
                get_subscriptions(MOCK_USER['uid'], MOCK_USER[
                    'user_access_token'])

    def test_get_subscriptions_unauthorized(self):
        self.setup()
        self.insert_subscription()
        with self.app.app_context():
            with pytest.raises(Unauthorized):
                MOCK_USER['user_access_token'] = 'access_token'
                get_subscriptions(MOCK_USER['uid'], MOCK_USER[
                    'user_access_token'])

    def test_get_subscriptions_user_not_found(self):
        self.setup()
        self.insert_subscription()
        with self.app.app_context():
            with pytest.raises(UserNotFound):
                MOCK_USER['uid'] = 'uid'
                get_subscriptions(MOCK_USER['uid'], MOCK_USER[
                    'user_access_token'])
#####
    def test_get_subscription_info(self):
        self.setup()
        self.insert_subscription()
        with self.app.app_context():
            res = get_subscription_info(MOCK_USER['uid'], MOCK_USER[
                'user_access_token'], MOCK_SUBSCRIPTION_INFO['id'])
            assert isinstance(res, dict)
            assert 'access_token' not in res
            assert 'id' in res
            assert res['state'] == 'Inactive'

    def test_get_subscription_info_subscription_not_found(self):
        self.setup()
        with self.app.app_context():
            with pytest.raises(SubscriptionNotFound):
                get_subscription_info(MOCK_USER['uid'], MOCK_USER[
                    'user_access_token'], MOCK_SUBSCRIPTION_INFO['id'])

    def test_get_subscription_info_unauthorized(self):
        self.setup()
        self.insert_subscription()
        with self.app.app_context():
            with pytest.raises(Unauthorized):
                MOCK_USER['user_access_token'] = 'access_token'
                get_subscription_info(MOCK_USER['uid'], MOCK_USER[
                    'user_access_token'], MOCK_SUBSCRIPTION_INFO['id'])

    def test_get_subscription_info_user_not_found(self):
        self.setup()
        self.insert_subscription()
        with self.app.app_context():
            with pytest.raises(UserNotFound):
                MOCK_USER['uid'] = 'uid'
                get_subscription_info(MOCK_USER['uid'], MOCK_USER[
                    'user_access_token'], MOCK_SUBSCRIPTION_INFO['id'])