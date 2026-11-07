"""Tests for the default configuration, which ends up in the public image."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from flask import Flask
from foca import Foca
from foca.models.config import Config, MongoConfig
import mongomock
import pytest
import yaml

from pubgrade.app import CONFIG_FILE, create_admin_user
from tests.mock_data import ENDPOINT_CONFIG, MONGO_CONFIG


@pytest.fixture(name="config")
def fixture_config() -> dict[str, Any]:
    """Load the default configuration.

    Returns:
        The content of `pubgrade/config.yaml`.
    """
    path = Path(__file__).parent.parent / "pubgrade" / "config.yaml"
    return yaml.safe_load(path.read_text())


def test_no_debug_mode(config: dict[str, Any]) -> None:
    """Debug and development settings are off."""
    assert config["server"]["debug"] is False
    assert config["server"]["testing"] is False


def test_request_bodies_limited(config: dict[str, Any]) -> None:
    """Request bodies are limited in size."""
    assert config["server"]["max_content_length"] == 1048576


def test_valid_for_foca() -> None:
    """FOCA accepts the configuration, with errors as problem details."""
    foca = Foca(config_file=CONFIG_FILE)
    assert foca.conf.exceptions.mapping == "pubgrade.errors.exceptions.exceptions"
    assert foca.conf.api.specs


def test_no_users(config: dict[str, Any]) -> None:
    """Deployments bring their own admin users and tokens."""
    assert config["endpoints"]["subscriptions"]["admin_users"] == []


def test_builds_off(config: dict[str, Any]) -> None:
    """Builds are off, without settings for particular deployments."""
    builds = config["endpoints"]["builds"]
    assert builds["enabled"] is False
    assert builds["gh_action_path"] == ""
    assert builds["intermediate_registery_format"] == ""


def test_admin_users_follow_configuration() -> None:
    """Tokens get replaced, and users missing in the configuration removed."""
    app = Flask(__name__)
    flask_config: Any = app.config
    settings: dict[str, Any] = {
        "db": MongoConfig(**MONGO_CONFIG),
        "endpoints": {
            **ENDPOINT_CONFIG,
            "subscriptions": {
                "admin_users": [
                    {"name": "A", "uid": "a", "user_access_token": "new"},
                    {"name": "C", "uid": "c", "user_access_token": "token"},
                ]
            },
        },
    }
    flask_config.foca = Config(**settings)
    collection: Any = mongomock.MongoClient().db.collection
    collection.insert_many(
        [
            {"name": "A", "uid": "a", "user_access_token": "old"},
            {"name": "B", "uid": "b", "user_access_token": "gone"},
        ]
    )
    flask_config.foca.db.dbs["pubgradeStore"].collections[
        "admin_users"
    ].client = collection
    create_admin_user(SimpleNamespace(app=app))
    users = {user["uid"]: user for user in collection.find()}
    assert set(users) == {"a", "c"}
    assert users["a"]["user_access_token"] == "new"
