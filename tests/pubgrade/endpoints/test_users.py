"""Tests for /users endpoint """
from unittest.mock import patch, MagicMock

import mongomock
import pytest
from flask import Flask
from foca.models.config import MongoConfig, Config

from pubgrade.errors.exceptions import URLNotFound
from pubgrade.modules.endpoints.users import register_user, get_users, \
    toggle_user_status
from tests.mock_data import MONGO_CONFIG, ENDPOINT_CONFIG, MOCK_USER_DB


class TestUsers:
    app = Flask(__name__)

    def setup(self):
        self.app.config['FOCA'] = \
            Config(db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
        self.app.config['FOCA'].db.dbs['pubgradeStore']. \
            collections['users'].client = mongomock.MongoClient(
        ).db.collection
        # for repository in MOCK_REPOSITORIES:
        self.app.config['FOCA'].db.dbs['pubgradeStore'].collections[
            'users'].client.insert_one(MOCK_USER_DB)

    def test_register_user(self):
        self.setup()
        with self.app.app_context():
            response = register_user({'name': 'Akash Saini'})
            assert 'uid' in response
            assert 'user_access_token' in response
            assert 'name' in response

    def test_register_user_keyerror(self):
        self.setup()
        with self.app.app_context():
            with pytest.raises(URLNotFound):
                response = register_user({'nam': 'Akash Saini'})

    # def test_register_user_duplicate(self):

    def test_get_users(self):
        self.setup()
        with self.app.app_context():
            uid = self.app.config['FOCA'].endpoints['subscriptions'][
                'admin_user']['uid']
            user_access_token = self.app.config['FOCA'].endpoints[
                'subscriptions']['admin_user'][
                'user_access_token']
            response = get_users(uid, user_access_token)
            assert response[0]['name'] == 'Akash'
            assert isinstance(response, list)

    def test_toggle_user_status(self):
        self.setup()
        with self.app.app_context():
            uid = self.app.config['FOCA'].endpoints['subscriptions'][
                'admin_user']['uid']
            user_access_token = self.app.config['FOCA'].endpoints[
                'subscriptions']['admin_user'][
                'user_access_token']
            response = toggle_user_status(uid, user_access_token,
                                          MOCK_USER_DB['uid'], False)
            assert response == "User unverified successfully."
