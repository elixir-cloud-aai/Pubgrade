"""Tests for the app factory and the entry point for development."""

from types import SimpleNamespace
from typing import Any, Dict, List

from flask import Flask
from foca.models.config import Config, MongoConfig
import mongomock
import pytest

import pubgrade.app
from pubgrade.charsets import CharsetError
from pubgrade.app import CONFIG_FILE, DB, create_app, main
from tests.mock_data import ENDPOINT_CONFIG, MONGO_CONFIG


class FakeFoca:
    """Stands in for FOCA: returns an app with in-memory collections."""

    config_files: List[Any] = []
    app: Any = None

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
def fixture_collections(monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    """Prepare a FOCA app with in-memory collections, and return them.

    Args:
        monkeypatch: Fixture to replace FOCA.

    Returns:
        Collections of the database, by name.
    """
    flask_app = Flask(__name__)
    flask_app.config.foca = Config(
        db=MongoConfig(**MONGO_CONFIG),
        endpoints={
            **ENDPOINT_CONFIG,
            "subscriptions": {
                "admin_users": [
                    {"name": "A", "uid": "a", "user_access_token": "token"}
                ]
            },
        },
    )
    database = mongomock.MongoClient().db
    collections = {}
    for name in ("admin_users", "builds", "subscriptions"):
        collections[name] = database[name]
        flask_app.config.foca.db.dbs[DB].collections[name].client = database[name]
    app = SimpleNamespace(app=flask_app, port=8080, run=lambda port: None)
    FakeFoca.config_files = []
    FakeFoca.app = app
    monkeypatch.setattr(pubgrade.app, "Foca", FakeFoca)
    return collections


def test_create_app(collections: Dict[str, Any]) -> None:
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


def test_main_runs_on_configured_port(
    collections: Dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The development server runs the app on the configured port."""
    ports: List[int] = []
    monkeypatch.setattr(FakeFoca.app, "run", lambda port: ports.append(port))
    main()
    assert ports == [8080]


def test_create_app_checks_charsets(collections: Dict[str, Any]) -> None:
    """A character set setting that can't be used stops the app at start."""
    FakeFoca.app.app.config.foca.endpoints["user"]["uid_charset"] = "string.foo"
    with pytest.raises(CharsetError, match="endpoints.user.uid_charset"):
        create_app()
    assert collections["admin_users"].count_documents({}) == 0
