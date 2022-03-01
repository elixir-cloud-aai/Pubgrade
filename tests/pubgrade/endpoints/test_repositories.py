"""Tests for /repositories endpoint """
from unittest.mock import MagicMock

import mongomock
import pytest
from flask import Flask
from foca.models.config import Config
from foca.models.config import MongoConfig
import string

from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import Unauthorized, InternalServerError

from pubgrade.errors.exceptions import URLNotFound, RepositoryNotFound
from pubgrade.modules.endpoints.repositories import (
    register_repository,
    get_repositories,
    generate_id,
    get_repository,
    modify_repository_info,
    delete_repository,
)
from tests.mock_data import MONGO_CONFIG, ENDPOINT_CONFIG, MOCK_REPOSITORIES


class TestRepository:
    app = Flask(__name__)

    repository_url = "https://github.com/elixir-cloud-aai/drs-filer"

    def setup(self):
        self.app.config["FOCA"] = Config(
            db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
        )
        self.app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client = mongomock.MongoClient().db.collection
        for repository in MOCK_REPOSITORIES:
            self.app.config["FOCA"].db.dbs["pubgradeStore"].collections[
                "repositories"
            ].client.insert_one(repository)

    def test_register_repository(self):
        self.setup()
        data = {"url": self.repository_url}
        with self.app.app_context():
            res = register_repository(data=data)
            assert "id" in res
            assert "access_token" in res
            assert isinstance(res, dict)

    def test_register_repository_url_not_found(self):
        self.setup()
        data = {}
        with self.app.app_context():
            with pytest.raises(URLNotFound):
                res = register_repository(data=data)
                assert "id" in res
                assert "access_token" in res
                assert isinstance(res, dict)

    def test_register_repository_duplicate_key_error(self):
        app = Flask(__name__)
        app.config["FOCA"] = Config(
            db=MongoConfig(**MONGO_CONFIG),
            endpoints=ENDPOINT_CONFIG,
        )
        mock_resp = MagicMock(side_effect=DuplicateKeyError(""))
        app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client = MagicMock()
        app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client.insert_one = mock_resp
        request_data = {"url": self.repository_url}
        with app.app_context():
            with pytest.raises(InternalServerError):
                register_repository(data=request_data)

    def test_get_repositories(self):
        self.app.config["FOCA"] = Config(
            db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
        )
        self.app.config["FOCA"].db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client = mongomock.MongoClient().db.collection
        with self.app.app_context():
            res = get_repositories()
            assert res == []
        self.setup()
        with self.app.app_context():
            res = get_repositories()
            assert isinstance(res, list)
            assert MOCK_REPOSITORIES[1]["id"] == res[1]["id"]

    def test_generate_id(self):
        string.digits  # to avoid lint error
        for i in range(100):
            charset = "string.ascii_lowercase + string.digits +  '.' +  '-'"
            charset = eval(charset)
            length = 6
            res = generate_id(charset, length)
            assert length == len(res)
            assert 1 in [c in res for c in charset]
            assert "_" not in res or res[0] != "." or res[0] != "-"

    def test_get_repository(self):
        self.setup()
        with self.app.app_context():
            res = get_repository(MOCK_REPOSITORIES[1]["id"])
            assert "subscription_list" not in res
            assert "access_token" not in res
            assert (
                "build_list" in res
                and MOCK_REPOSITORIES[1]["build_list"] == res["build_list"]
            )
            assert "id" in res and MOCK_REPOSITORIES[1]["id"] == res["id"]
            assert "url" in res and MOCK_REPOSITORIES[1]["url"] == res["url"]

    def test_get_repository_repository_not_found(self):
        self.setup()
        with self.app.app_context():
            with pytest.raises(RepositoryNotFound):
                get_repository("abcd")

    def test_modify_repository_info(self):
        self.setup()
        data = {"url": self.repository_url}
        with self.app.app_context():
            res = modify_repository_info(
                MOCK_REPOSITORIES[1]["id"],
                MOCK_REPOSITORIES[1]["access_token"],
                data,
            )
            assert "access_token" in res and "id" in res
            assert res["id"] == MOCK_REPOSITORIES[1]["id"]

    def test_modify_repository_info_repository_not_found(self):
        self.setup()
        data = {"url": self.repository_url}
        with self.app.app_context():
            with pytest.raises(RepositoryNotFound):
                modify_repository_info(
                    "abcd", MOCK_REPOSITORIES[1]["access_token"], data
                )

    def test_modify_repository_info_unauthorized(self):
        self.setup()
        data = {"url": self.repository_url}
        with self.app.app_context():
            with pytest.raises(Unauthorized):
                modify_repository_info(
                    MOCK_REPOSITORIES[1]["id"], "access_token", data
                )

    def test_delete_repository(self):
        self.setup()
        with self.app.app_context():
            res = delete_repository(
                MOCK_REPOSITORIES[1]["id"],
                MOCK_REPOSITORIES[1]["access_token"],
            )
            assert res == 1

    def test_delete_repository_repository_not_found(self):
        self.setup()
        with self.app.app_context():
            with pytest.raises(RepositoryNotFound):
                delete_repository("abcd", MOCK_REPOSITORIES[1]["access_token"])

    def test_delete_repository_unauthorized(self):
        self.setup()
        with self.app.app_context():
            with pytest.raises(Unauthorized):
                delete_repository(MOCK_REPOSITORIES[1]["id"], "access_token")
