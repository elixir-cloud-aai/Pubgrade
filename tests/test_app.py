"""Tests for the app factory and the entry point for development."""

from types import SimpleNamespace
from typing import Any, ClassVar

from flask import Flask
from foca.models.config import Config, MongoConfig
import mongomock
import pytest

import pubgrade.app
from pubgrade.app import CONFIG_FILE, DB, create_app, main
from pubgrade.charsets import CharsetError
from tests.mock_data import ENDPOINT_CONFIG, MONGO_CONFIG


class FakeFoca:
    """Stands in for FOCA: returns an app with in-memory collections."""

    config_files: ClassVar[list[Any]] = []
    app: ClassVar[Any] = None

    def __init__(self, config_file: Any) -> None:
        """Remember the configuration file.

        Args:
            config_file: Path to the configuration.
        """
        self.config_files.append(config_file)

    def create_app(self) -> Any:
        """Return the prepared app.

        Returns:
            The app, as FOCA would return it.
        """
        return self.app


@pytest.fixture(name="collections")
def fixture_collections(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Prepare a FOCA app with in-memory collections, and return them.

    Args:
        monkeypatch: Fixture to replace FOCA.

    Returns:
        Collections of the database, by name.
    """
    flask_app = Flask(__name__)
    flask_config: Any = flask_app.config
    settings: dict[str, Any] = {
        "db": MongoConfig(**MONGO_CONFIG),
        "endpoints": {
            **ENDPOINT_CONFIG,
            "subscriptions": {
                "admin_users": [{"name": "A", "uid": "a", "user_access_token": "token"}]
            },
        },
    }
    flask_config.foca = Config(**settings)
    database: Any = mongomock.MongoClient().db
    collections: dict[str, Any] = {}
    for name in ("admin_users", "builds", "subscriptions"):
        collections[name] = database[name]
        flask_config.foca.db.dbs[DB].collections[name].client = database[name]
    app = SimpleNamespace(app=flask_app, port=8080, run=lambda port: None)
    FakeFoca.config_files = []
    FakeFoca.app = app
    monkeypatch.setattr(pubgrade.app, "Foca", FakeFoca)
    return collections


def test_create_app(collections: dict[str, Any]) -> None:
    """The factory creates the admin users and repairs stored timestamps."""
    collections["builds"].insert_one(
        {"id": "b", "started_at": "2026-01-02T03:04:05", "finished_at": "NULL"}
    )
    app = create_app()
    assert app is FakeFoca.app
    assert FakeFoca.config_files == [CONFIG_FILE]
    assert [user["uid"] for user in collections["admin_users"].find()] == ["a"]
    build = collections["builds"].find_one({"id": "b"})
    assert build["started_at"] == "2026-01-02T03:04:05+00:00"
    assert build["finished_at"] is None


def test_create_app_removes_tokens_of_canceled_builds(
    collections: dict[str, Any],
) -> None:
    """Canceled builds (e.g., of earlier versions) lose their registry token.

    Other builds keep theirs: a running build needs it for its signing, and
    one that earlier versions recorded as `SUCCEEDED` may be reported again.

    Args:
        collections: Collections of the database, by name.
    """
    collections["builds"].insert_many(
        [
            {"id": status, "status": status, "dockerhub_token": "token"}
            for status in ("CANCELED", "QUEUED", "SUCCEEDED")
        ]
    )
    create_app()
    tokens = {
        build["id"]: "dockerhub_token" in build
        for build in collections["builds"].find()
    }
    assert tokens == {"CANCELED": False, "QUEUED": True, "SUCCEEDED": True}


def test_main_runs_on_configured_port(
    collections: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The development server runs the app on the configured port.

    Args:
        collections: Fixture with the collections of the database.
        monkeypatch: Fixture to replace the server.
    """
    ports: list[int] = []

    def run(port: int) -> None:
        """Record the port instead of serving.

        Args:
            port: Port to serve on.
        """
        ports.append(port)

    monkeypatch.setattr(FakeFoca.app, "run", run)
    main()
    assert ports == [8080]


def test_create_app_checks_charsets(
    collections: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A character set setting that can't be used stops the app at start.

    Nothing is written to the database then.

    Args:
        collections: Fixture with the collections of the database.
        monkeypatch: Fixture to change the configuration.
    """
    collections["builds"].insert_one({"id": "b", "finished_at": "NULL"})
    endpoints = FakeFoca.app.app.config.foca.endpoints
    monkeypatch.setitem(endpoints["user"], "uid_charset", "string.foo")
    with pytest.raises(CharsetError, match=r"endpoints\.user\.uid_charset"):
        create_app()
    assert collections["admin_users"].count_documents({}) == 0
    assert collections["builds"].find_one({"id": "b"})["finished_at"] == "NULL"
