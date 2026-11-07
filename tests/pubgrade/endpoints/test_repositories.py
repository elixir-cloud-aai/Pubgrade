"""Tests for /repositories endpoint """
import logging
from unittest.mock import MagicMock

import mongomock
import pytest
from flask import Flask
from foca.models.config import Config
from foca.models.config import MongoConfig
import string

from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import Unauthorized, InternalServerError

from pubgrade.errors.exceptions import (
    RegistrationDisabled,
    RepositoryNotFound,
    URLNotFound,
)
from pubgrade.modules.endpoints import repositories
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
        self.app.config.foca = Config(
            db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
        )
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client = mongomock.MongoClient().db.collection
        for repository in MOCK_REPOSITORIES:
            self.app.config.foca.db.dbs["pubgradeStore"].collections[
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

    def test_register_repository_logs_no_token(self, caplog):
        """Log messages name the new repository, without its token."""
        self.setup()
        caplog.set_level(logging.DEBUG)
        with self.app.app_context():
            res = register_repository(data={"url": self.repository_url})
        assert res["id"] in caplog.text
        assert res["access_token"] not in caplog.text

    def test_register_repository_closed(self):
        """Registration can be closed by configuration."""
        self.setup()
        self.app.config.foca.endpoints["repository"][
            "registration_enabled"
        ] = False
        with self.app.app_context():
            with pytest.raises(RegistrationDisabled):
                register_repository(data={"url": self.repository_url})

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
        app.config.foca = Config(
            db=MongoConfig(**MONGO_CONFIG),
            endpoints=ENDPOINT_CONFIG,
        )
        mock_resp = MagicMock(side_effect=DuplicateKeyError(""))
        app.config.foca.db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client = MagicMock()
        app.config.foca.db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client.insert_one = mock_resp
        request_data = {"url": self.repository_url}
        with app.app_context():
            with pytest.raises(InternalServerError):
                register_repository(data=request_data)

    def test_get_repositories(self):
        self.app.config.foca = Config(
            db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG
        )
        self.app.config.foca.db.dbs["pubgradeStore"].collections[
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
        """Values have the length and the characters asked for."""
        charset = string.ascii_lowercase + string.digits + ".-"
        for _ in range(100):
            res = generate_id(charset, 6)
            assert len(res) == 6
            assert set(res) <= set(charset)
            assert res[0] not in ".-" + string.digits
            assert res[-1] not in ".-" + string.digits

    def test_generate_id_unusable_charset(self):
        """Characters that can't start or end a value are rejected."""
        with pytest.raises(ValueError, match="No character for the start"):
            generate_id("_.-0", 3)

    def test_generate_id_skips_underscores(self):
        """Values never contain `_`."""
        for _ in range(20):
            assert generate_id("a_", 4) == "aaaa"

    def test_generate_id_uses_secrets(self, monkeypatch):
        """Characters are drawn with `secrets.choice`, the standard for tokens."""
        calls = []

        def choice(charset):
            calls.append(charset)
            return "a"

        monkeypatch.setattr(repositories.secrets, "choice", choice)
        assert generate_id("ab", 3) == "aaa"
        assert calls == ["ab"] * 3

    def test_register_repository_charsets(self, monkeypatch):
        """Identifiers and tokens use the characters the settings name."""
        self.setup()
        charsets = []
        choice = repositories.secrets.choice

        def recording_choice(charset):
            charsets.append(charset)
            return choice(charset)

        monkeypatch.setattr(repositories.secrets, "choice", recording_choice)
        monkeypatch.setitem(
            self.app.config.foca.endpoints["access_token"],
            "charset",
            "string.ascii_uppercase",
        )
        with self.app.app_context():
            res = register_repository(data={"url": self.repository_url})
        expected = "".join(sorted(string.ascii_lowercase + string.digits + ".-"))
        assert set(charsets) == {expected, string.ascii_uppercase}
        assert set(res["id"]) <= set(expected)
        assert len(res["access_token"]) == 32
        assert set(res["access_token"]) <= set(string.ascii_uppercase)

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
