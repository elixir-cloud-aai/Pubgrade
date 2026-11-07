"""Tests for the /repositories endpoint."""

import logging
import string
from typing import Any
from unittest.mock import MagicMock

from flask import Flask
from foca.models.config import Config, MongoConfig
import mongomock
from pymongo.errors import DuplicateKeyError
import pytest
from werkzeug.exceptions import InternalServerError, Unauthorized

from pubgrade.errors.exceptions import (
    RegistrationDisabled,
    RepositoryNotFound,
    URLNotFound,
)
from pubgrade.modules.endpoints import repositories
from pubgrade.modules.endpoints.repositories import (
    delete_repository,
    generate_id,
    get_repositories,
    get_repository,
    modify_repository_info,
    register_repository,
)
from tests.mock_data import ENDPOINT_CONFIG, MOCK_REPOSITORIES, MONGO_CONFIG


def _set_foca(app: Flask, **settings: Any) -> None:
    """Set the FOCA configuration of an app.

    Args:
        app: Flask app.
        **settings: Settings of the configuration.
    """
    flask_config: Any = app.config
    flask_config.foca = Config(**settings)


def _foca(app: Flask) -> Any:
    """Get the FOCA configuration of an app.

    Args:
        app: Flask app.

    Returns:
        The configuration, with the collections of the database.
    """
    flask_config: Any = app.config
    return flask_config.foca


class TestRepository:
    """Tests for the repository controllers."""

    app = Flask(__name__)

    repository_url = "https://github.com/elixir-cloud-aai/drs-filer"

    def setup(self) -> None:
        """Prepare the configuration with a user and an admin user."""
        _set_foca(self.app, db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
        _foca(self.app).db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client = mongomock.MongoClient().db.collection
        for repository in MOCK_REPOSITORIES:
            _foca(self.app).db.dbs["pubgradeStore"].collections[
                "repositories"
            ].client.insert_one(repository)

    def test_register_repository(self) -> None:
        """A registered repository gets an identifier and a token."""
        self.setup()
        data = {"url": self.repository_url}
        with self.app.app_context():
            res = register_repository(data=data)
            assert "id" in res
            assert "access_token" in res
            assert isinstance(res, dict)

    def test_register_repository_logs_no_token(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Log messages name the new repository, without its token.

        Args:
            caplog: Fixture to capture log messages.
        """
        self.setup()
        caplog.set_level(logging.DEBUG)
        with self.app.app_context():
            res = register_repository(data={"url": self.repository_url})
        assert res["id"] in caplog.text
        assert res["access_token"] not in caplog.text

    def test_register_repository_closed(self) -> None:
        """Registration can be closed by configuration."""
        self.setup()
        _foca(self.app).endpoints["repository"]["registration_enabled"] = False
        with self.app.app_context(), pytest.raises(RegistrationDisabled):
            register_repository(data={"url": self.repository_url})

    def test_register_repository_url_not_found(self) -> None:
        """Registration without a URL fails."""
        self.setup()
        data: dict[str, Any] = {}
        with self.app.app_context(), pytest.raises(URLNotFound):
            res = register_repository(data=data)
            assert "id" in res
            assert "access_token" in res
            assert isinstance(res, dict)

    def test_register_repository_duplicate_key_error(self) -> None:
        """A duplicate key on insertion is an internal error."""
        app = Flask(__name__)
        _set_foca(
            app,
            db=MongoConfig(**MONGO_CONFIG),
            endpoints=ENDPOINT_CONFIG,
        )
        mock_resp = MagicMock(side_effect=DuplicateKeyError(""))
        _foca(app).db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client = MagicMock()
        _foca(app).db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client.insert_one = mock_resp
        request_data = {"url": self.repository_url}
        with app.app_context(), pytest.raises(InternalServerError):
            register_repository(data=request_data)

    def test_get_repositories(self) -> None:
        """All repositories are listed."""
        _set_foca(self.app, db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
        _foca(self.app).db.dbs["pubgradeStore"].collections[
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

    def test_generate_id(self) -> None:
        """Values have the length and the characters asked for."""
        charset = string.ascii_lowercase + string.digits + ".-"
        for _ in range(100):
            res = generate_id(charset, 6)
            assert len(res) == 6
            assert set(res) <= set(charset)
            assert res[0] not in ".-" + string.digits
            assert res[-1] not in ".-" + string.digits

    def test_generate_id_unusable_charset(self) -> None:
        """Characters that can't start or end a value are rejected."""
        with pytest.raises(ValueError, match="No character for the start"):
            generate_id("_.-0", 3)

    def test_generate_id_skips_underscores(self) -> None:
        """Values never contain `_`."""
        for _ in range(20):
            assert generate_id("a_", 4) == "aaaa"

    def test_generate_id_uses_secrets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Characters are drawn with `secrets.choice`, the standard for tokens.

        Args:
            monkeypatch: Fixture to replace `secrets.choice`.
        """
        calls: list[str] = []

        def choice(charset: str) -> str:
            """Record the character set and pick `a`.

            Args:
                charset: Characters to choose from.

            Returns:
                Always `a`.
            """
            calls.append(charset)
            return "a"

        monkeypatch.setattr(repositories.secrets, "choice", choice)
        assert generate_id("ab", 3) == "aaa"
        assert calls == ["ab"] * 3

    def test_register_repository_charsets(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Identifiers and tokens use the characters the settings name.

        Args:
            monkeypatch: Fixture to record the draws and change the settings.
        """
        self.setup()
        charsets: list[str] = []
        choice = repositories.secrets.choice

        def recording_choice(charset: str) -> str:
            """Record the character set and pick a character.

            Args:
                charset: Characters to choose from.

            Returns:
                A character of the set.
            """
            charsets.append(charset)
            return choice(charset)

        monkeypatch.setattr(repositories.secrets, "choice", recording_choice)
        monkeypatch.setitem(
            _foca(self.app).endpoints["access_token"],
            "charset",
            "string.ascii_uppercase",
        )
        with self.app.app_context():
            res = register_repository(data={"url": self.repository_url})
        expected = "".join(sorted(string.ascii_lowercase + string.digits + ".-"))
        assert set(charsets) == {expected, string.ascii_uppercase}
        assert len(res["id"]) == 6
        assert set(res["id"]) <= set(expected)
        assert len(res["access_token"]) == 32
        assert set(res["access_token"]) <= set(string.ascii_uppercase)

    def test_get_repository(self) -> None:
        """A repository is returned without its secrets."""
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

    def test_get_repository_repository_not_found(self) -> None:
        """Getting an unknown repository fails."""
        self.setup()
        with self.app.app_context(), pytest.raises(RepositoryNotFound):
            get_repository("abcd")

    def test_modify_repository_info(self) -> None:
        """A repository can be modified with its token."""
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

    def test_modify_repository_info_repository_not_found(self) -> None:
        """Modifying an unknown repository fails."""
        self.setup()
        data = {"url": self.repository_url}
        with self.app.app_context(), pytest.raises(RepositoryNotFound):
            modify_repository_info("abcd", MOCK_REPOSITORIES[1]["access_token"], data)

    def test_modify_repository_info_unauthorized(self) -> None:
        """Modifying a repository with a wrong token fails."""
        self.setup()
        data = {"url": self.repository_url}
        with self.app.app_context(), pytest.raises(Unauthorized):
            modify_repository_info(MOCK_REPOSITORIES[1]["id"], "access_token", data)

    def test_delete_repository(self) -> None:
        """A repository can be deleted with its token."""
        self.setup()
        with self.app.app_context():
            res = delete_repository(
                MOCK_REPOSITORIES[1]["id"],
                MOCK_REPOSITORIES[1]["access_token"],
            )
            assert res == 1

    def test_delete_repository_repository_not_found(self) -> None:
        """Deleting an unknown repository fails."""
        self.setup()
        with self.app.app_context(), pytest.raises(RepositoryNotFound):
            delete_repository("abcd", MOCK_REPOSITORIES[1]["access_token"])

    def test_delete_repository_unauthorized(self) -> None:
        """Deleting a repository with a wrong token fails."""
        self.setup()
        with self.app.app_context(), pytest.raises(Unauthorized):
            delete_repository(MOCK_REPOSITORIES[1]["id"], "access_token")
