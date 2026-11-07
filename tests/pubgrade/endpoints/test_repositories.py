"""Tests for the /repositories endpoint."""

import logging
from pathlib import Path
import string
from typing import Any
from unittest.mock import MagicMock

from flask import Flask
from foca.models.config import MongoConfig
import mongomock
from pymongo.errors import DuplicateKeyError
import pytest
from werkzeug.exceptions import InternalServerError, Unauthorized

from pubgrade.errors.exceptions import (
    DeletePodError,
    RegistrationDisabled,
    RepositoryNotFound,
    URLNotFound,
)
from pubgrade.modules.endpoints import builds, repositories
from pubgrade.modules.endpoints.repositories import (
    delete_repository,
    generate_id,
    get_repositories,
    get_repository,
    modify_repository_info,
    register_repository,
)
from tests.helpers import foca_config, set_foca
from tests.mock_data import (
    ENDPOINT_CONFIG,
    MOCK_BUILD_INFO,
    MOCK_BUILD_INFO_2,
    MOCK_REPOSITORIES,
    MOCK_REPOSITORY_2,
    MOCK_SUBSCRIPTION_INFO,
    MOCK_USER_DB,
    MONGO_CONFIG,
)


def collection_of(app: Flask, name: str) -> Any:
    """Get a collection of the mock database.

    Args:
        app: Flask app.
        name: Name of the collection.

    Returns:
        The collection's client.
    """
    return foca_config(app).db.dbs["pubgradeStore"].collections[name].client


class TestRepository:
    """Tests for the repository controllers."""

    app = Flask(__name__)

    repository_url = "https://github.com/elixir-cloud-aai/drs-filer"

    def setup(self) -> None:
        """Prepare the configuration with a user and an admin user."""
        set_foca(self.app, db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
        foca_config(self.app).db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client = mongomock.MongoClient().db.collection
        for repository in MOCK_REPOSITORIES:
            foca_config(self.app).db.dbs["pubgradeStore"].collections[
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
        foca_config(self.app).endpoints["repository"]["registration_enabled"] = False
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
        set_foca(
            app,
            db=MongoConfig(**MONGO_CONFIG),
            endpoints=ENDPOINT_CONFIG,
        )
        mock_resp = MagicMock(side_effect=DuplicateKeyError(""))
        foca_config(app).db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client = MagicMock()
        foca_config(app).db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client.insert_one = mock_resp
        request_data = {"url": self.repository_url}
        with app.app_context(), pytest.raises(InternalServerError):
            register_repository(data=request_data)

    def test_get_repositories(self) -> None:
        """All repositories are listed."""
        set_foca(self.app, db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
        foca_config(self.app).db.dbs["pubgradeStore"].collections[
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
            foca_config(self.app).endpoints["access_token"],
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

    def test_modify_repository_info_keeps_builds_and_subscriptions(self) -> None:
        """Modifying a repository changes its URL only.

        Regression test: the repository's builds and subscriptions were lost.
        """
        self.setup()
        data = {"url": self.repository_url, "build_list": [], "id": "other"}
        with self.app.app_context():
            modify_repository_info(
                MOCK_REPOSITORY_2["id"], MOCK_REPOSITORY_2["access_token"], data
            )
            stored = collection_of(self.app, "repositories").find_one(
                {"id": MOCK_REPOSITORY_2["id"]}, {"_id": False}
            )
        expected = dict(MOCK_REPOSITORY_2)
        expected.pop("_id", None)
        assert stored == {**expected, "url": self.repository_url}

    def test_modify_repository_info_url_not_found(self) -> None:
        """Modifying a repository without a URL fails."""
        self.setup()
        with self.app.app_context(), pytest.raises(URLNotFound):
            modify_repository_info(
                MOCK_REPOSITORY_2["id"], MOCK_REPOSITORY_2["access_token"], {}
            )

    def test_modify_repository_info_deleted_meanwhile(self) -> None:
        """A repository that another request deleted meanwhile isn't found."""
        self.setup()
        wrapper = MagicMock(wraps=collection_of(self.app, "repositories"))
        wrapper.update_one.return_value = MagicMock(matched_count=0)
        foca_config(self.app).db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client = wrapper
        with self.app.app_context(), pytest.raises(RepositoryNotFound):
            modify_repository_info(
                MOCK_REPOSITORY_2["id"],
                MOCK_REPOSITORY_2["access_token"],
                {"url": self.repository_url},
            )

    def setup_cascade(self, builds_enabled: bool) -> None:
        """Prepare a repository with builds, a subscription and its user.

        Args:
            builds_enabled: Whether Pubgrade builds images itself.
        """
        self.setup()
        for name in ("builds", "subscriptions", "users"):
            foca_config(self.app).db.dbs["pubgradeStore"].collections[
                name
            ].client = mongomock.MongoClient().db[name]
        foca_config(self.app).endpoints["builds"]["enabled"] = builds_enabled
        finished = {**MOCK_BUILD_INFO_2, "status": "SUCCEEDED"}
        other_build = {**MOCK_BUILD_INFO, "id": "repo12abcdef"}
        other_subscription = {
            **MOCK_SUBSCRIPTION_INFO,
            "id": "other1",
            "repository_id": "repo12",
        }
        user = {**MOCK_USER_DB, "subscription_list": ["tnglot", "other1"]}
        for name, documents in (
            ("builds", [MOCK_BUILD_INFO, finished, other_build]),
            ("subscriptions", [MOCK_SUBSCRIPTION_INFO, other_subscription]),
            ("users", [user]),
        ):
            for document in documents:
                collection_of(self.app, name).insert_one(dict(document))

    def remaining(self, name: str, key: str = "id") -> list[str]:
        """Get the identifiers of the documents left in a collection.

        Args:
            name: Name of the collection.
            key: Field that identifies the documents.

        Returns:
            The identifiers.
        """
        return [doc[key] for doc in collection_of(self.app, name).find()]

    def test_delete_repository(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Deleting a repository removes its builds and subscriptions.

        Other repositories keep theirs. With builds switched off, no pods are
        touched.

        Args:
            monkeypatch: Fixture to fail on calls to Kubernetes.
        """
        self.setup_cascade(builds_enabled=False)
        delete_pod = MagicMock()
        monkeypatch.setattr(builds, "delete_pod", delete_pod)
        with self.app.app_context():
            delete_repository(
                MOCK_REPOSITORY_2["id"], MOCK_REPOSITORY_2["access_token"]
            )
            assert self.remaining("repositories") == ["repo12"]
            assert self.remaining("builds") == ["repo12abcdef"]
            assert self.remaining("subscriptions") == ["other1"]
            user = collection_of(self.app, "users").find_one({})
        assert user is not None
        assert user["subscription_list"] == ["other1"]
        delete_pod.assert_not_called()

    def test_delete_repository_stops_unfinished_builds(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """With builds switched on, unfinished builds lose their pods and files.

        Args:
            monkeypatch: Fixture to replace the calls to Kubernetes.
            tmp_path: Temporary directory for the builds' files.
        """
        self.setup_cascade(builds_enabled=True)
        for build_id in (MOCK_BUILD_INFO["id"], MOCK_BUILD_INFO_2["id"]):
            (tmp_path / build_id).mkdir()
        monkeypatch.setattr(builds, "BASE_DIR", str(tmp_path))
        monkeypatch.setattr(builds, "load_cluster_config", MagicMock())
        delete_pod = MagicMock()
        monkeypatch.setattr(builds, "delete_pod", delete_pod)
        monkeypatch.delenv("NAMESPACE", raising=False)
        with self.app.app_context():
            delete_repository(
                MOCK_REPOSITORY_2["id"], MOCK_REPOSITORY_2["access_token"]
            )
            assert self.remaining("builds") == ["repo12abcdef"]
        delete_pod.assert_called_once_with(
            MOCK_BUILD_INFO["id"], "default", missing_ok=True
        )
        # The finished build's files are left to its own cleanup
        assert [path.name for path in tmp_path.iterdir()] == [MOCK_BUILD_INFO_2["id"]]

    def test_delete_repository_keeps_all_if_pod_deletion_fails(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """If a build's pod can't be deleted, nothing is, so a retry can finish.

        Args:
            monkeypatch: Fixture to replace the calls to Kubernetes.
            tmp_path: Temporary directory for the builds' files.
        """
        self.setup_cascade(builds_enabled=True)
        monkeypatch.setattr(builds, "BASE_DIR", str(tmp_path))
        monkeypatch.setattr(builds, "load_cluster_config", MagicMock())
        monkeypatch.setattr(builds, "delete_pod", MagicMock(side_effect=DeletePodError))
        with self.app.app_context(), pytest.raises(DeletePodError):
            delete_repository(
                MOCK_REPOSITORY_2["id"], MOCK_REPOSITORY_2["access_token"]
            )
        with self.app.app_context():
            assert MOCK_REPOSITORY_2["id"] in self.remaining("repositories")
            assert len(self.remaining("builds")) == 3
            assert len(self.remaining("subscriptions")) == 2

    def test_delete_repository_deleted_meanwhile(self) -> None:
        """A repository that another request deleted meanwhile isn't found."""
        self.setup_cascade(builds_enabled=False)
        repositories_collection = collection_of(self.app, "repositories")
        wrapper = MagicMock(wraps=repositories_collection)
        wrapper.delete_one.return_value = MagicMock(deleted_count=0)
        foca_config(self.app).db.dbs["pubgradeStore"].collections[
            "repositories"
        ].client = wrapper
        with self.app.app_context(), pytest.raises(RepositoryNotFound):
            delete_repository(
                MOCK_REPOSITORY_2["id"], MOCK_REPOSITORY_2["access_token"]
            )

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
