"""Tests for /projects endpoint """

import mongomock
import pytest
from flask import Flask
from foca.models.config import MongoConfig
from foca.models.config import Config
from werkzeug.exceptions import Unauthorized

from broker.errors.exceptions import URLNotFound, RepositoryNotFound
from tests.ga4gh.mock_data import MONGO_CONFIG, ENDPOINT_CONFIG, \
    MOCK_REPOSITORIES

from broker.ga4gh.broker.endpoints.repositories import (
    register_repository, get_repositories, generate_id, get_repository_info,
    modify_repository_info, delete_repository)


class TestRepository:
    app = Flask(__name__)

    def setup(self):
        self.app.config['FOCA'] = \
            Config(db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
        self.app.config['FOCA'].db.dbs['brokerStore']. \
            collections['repositories'].client = mongomock.MongoClient(
        ).db.collection
        for repository in MOCK_REPOSITORIES:
            self.app.config['FOCA'].db.dbs['brokerStore']. \
                collections['repositories'].client.insert_one(
                repository).inserted_id

    def test_register_repository(self):
        self.setup()
        data = {
            "url": "https://github.com/akash2237778/Broker-test"
        }
        with self.app.app_context():
            res = register_repository(data=data)
            assert 'id' in res
            assert 'access_token' in res
            assert isinstance(res, dict)

    def test_register_repository_url_not_found(self):
        self.setup()
        data = {
        }
        with self.app.app_context():
            with pytest.raises(URLNotFound):
                res = register_repository(data=data)
                assert 'id' in res
                assert 'access_token' in res
                assert isinstance(res, dict)

    # def test_register_repository_duplicate_key_error(self):
    #     self.app.config['FOCA'] = Config(
    #         db=MongoConfig(**MONGO_CONFIG),
    #         endpoints=MOCK_ENDPOINT,
    #     )
    #     data = {
    #         "url": "https://github.com/akash2237778/Broker-test"
    #     }
    #     self.app.config['FOCA'].db.dbs['brokerStore'].collections[
    #         'repositories'].client = mongomock.MongoClient().db.collection
    #     with self.app.app_context():
    #         res = register_repository(data=data)
    #         pprint(res)
    #     with self.app.app_context():
    #         with pytest.raises(DuplicateKeyError):
    #             register_repository(data=data)

    def test_get_repositories(self):
        self.app.config['FOCA'] = \
            Config(db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
        self.app.config['FOCA'].db.dbs['brokerStore']. \
            collections['repositories'].client = mongomock.MongoClient(
        ).db.collection
        with self.app.app_context():
            res = get_repositories()
            assert res == []
        self.setup()
        with self.app.app_context():
            res = get_repositories()
            assert isinstance(res, list)
            assert MOCK_REPOSITORIES[1]['id'] == res[1]['id']

    def test_generate_id(self):
        for i in range(100):
            charset = "string.ascii_lowercase + string.digits +  '.' +  '-'"
            charset = eval(charset)
            length = 6
            res = generate_id(charset, length)
            assert length == len(res)
            assert 1 in [c in res for c in charset]
            assert '_' not in res or res[0] != '.' or res[0] != '-'

    def test_get_repository_info(self):
        self.setup()
        with self.app.app_context():
            res = get_repository_info(MOCK_REPOSITORIES[1]['id'])
            assert 'subscription_list' not in res
            assert 'access_token' not in res
            assert 'build_list' in res and MOCK_REPOSITORIES[1]['build_list'] \
                   == res['build_list']
            assert 'id' in res and MOCK_REPOSITORIES[1]['id'] \
                   == res['id']
            assert 'url' in res and MOCK_REPOSITORIES[1]['url'] \
                   == res['url']

    def test_get_repository_info_repository_not_found(self):
        self.setup()
        with self.app.app_context():
            with pytest.raises(RepositoryNotFound):
                get_repository_info('abcd')

    def test_modify_repository_info(self):
        self.setup()
        data = {
            "url": "https://github.com/akash2237778/broker"
        }
        with self.app.app_context():
            res = modify_repository_info(MOCK_REPOSITORIES[1]['id'],
                                         MOCK_REPOSITORIES[1]['access_token'],
                                         data)
            assert 'access_token' in res and 'id' in res
            assert res['id'] == MOCK_REPOSITORIES[1]['id']

    def test_modify_repository_info_repository_not_found(self):
        self.setup()
        data = {
            "url": "https://github.com/akash2237778/broker"
        }
        with self.app.app_context():
            with pytest.raises(RepositoryNotFound):
                modify_repository_info('abcd',
                                       MOCK_REPOSITORIES[1]['access_token'],
                                       data)

    def test_modify_repository_info_unauthorized(self):
        self.setup()
        data = {
            "url": "https://github.com/akash2237778/broker"
        }
        with self.app.app_context():
            with pytest.raises(Unauthorized):
                modify_repository_info(MOCK_REPOSITORIES[1]['id'],
                                       'access_token',
                                       data)

    def test_delete_repository(self):
        self.setup()
        with self.app.app_context():
            res = delete_repository(MOCK_REPOSITORIES[1]['id'],
                                    MOCK_REPOSITORIES[1]['access_token'])
            assert res == 1

    def test_delete_repository_repository_not_found(self):
        self.setup()
        with self.app.app_context():
            with pytest.raises(RepositoryNotFound):
                delete_repository('abcd',
                                  MOCK_REPOSITORIES[1]['access_token'])

    def test_delete_repository_unauthorized(self):
        self.setup()
        with self.app.app_context():
            with pytest.raises(Unauthorized):
                delete_repository(MOCK_REPOSITORIES[1]['id'],
                                  'access_token')
