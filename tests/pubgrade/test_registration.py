"""Tests for the checks of registrations (`pubgrade.registration`)."""

import copy
from typing import Any

from flask import Flask
from foca.errors import Unauthorized
from foca.models.config import MongoConfig
import mongomock
import pytest

from pubgrade.errors.exceptions import RegistrationDisabled
from pubgrade.registration import check_registration
from tests.helpers import foca_config, set_foca
from tests.mock_data import ENDPOINT_CONFIG, MOCK_ADMIN_USER_1, MONGO_CONFIG

ADMIN_ID = MOCK_ADMIN_USER_1["uid"]
ADMIN_TOKEN = MOCK_ADMIN_USER_1["user_access_token"]
SECTIONS = ["repository", "user", "subscriptions"]


@pytest.fixture
def app() -> Flask:
    """Create an app with one admin user and open registrations.

    Returns:
        The app.
    """
    app = Flask(__name__)
    set_foca(
        app,
        db=MongoConfig(**MONGO_CONFIG),
        endpoints=copy.deepcopy(ENDPOINT_CONFIG),
    )
    admin_users = foca_config(app).db.dbs["pubgradeStore"].collections["admin_users"]
    admin_users.client = mongomock.MongoClient().db.collection
    admin_users.client.insert_one(dict(MOCK_ADMIN_USER_1))
    return app


def close(app: Flask, section: str) -> None:
    """Close the registration of a section.

    Args:
        app: The app.
        section: Section of the settings, e.g., `repository`.
    """
    foca_config(app).endpoints[section]["registration_enabled"] = False


@pytest.mark.parametrize("section", SECTIONS)
def test_open_without_credentials(app: Flask, section: str) -> None:
    """Anyone may register while registration is open.

    Args:
        app: The app.
        section: Section of the settings.
    """
    with app.app_context():
        assert check_registration(section, None, None) is False


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("closed", [False, True])
def test_admin(app: Flask, section: str, closed: bool) -> None:
    """Admins may register, also while registration is closed.

    Args:
        app: The app.
        section: Section of the settings.
        closed: Whether registration is closed.
    """
    if closed:
        close(app, section)
    with app.app_context():
        assert check_registration(section, ADMIN_ID, ADMIN_TOKEN) is True


@pytest.mark.parametrize("section", SECTIONS)
def test_closed_without_credentials(app: Flask, section: str) -> None:
    """Others may not register while registration is closed.

    Args:
        app: The app.
        section: Section of the settings.
    """
    close(app, section)
    with app.app_context(), pytest.raises(RegistrationDisabled):
        check_registration(section, None, None)


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("closed", [False, True])
@pytest.mark.parametrize(
    ("admin_id", "token"),
    [
        (ADMIN_ID, "wrong"),
        (ADMIN_ID, ""),
        ("unknown", ADMIN_TOKEN),
        (ADMIN_ID, None),
        (None, ADMIN_TOKEN),
    ],
)
def test_invalid_credentials(
    app: Flask, section: str, closed: bool, admin_id: Any, token: Any
) -> None:
    """Admin credentials that are given must be valid, open or closed.

    Args:
        app: The app.
        section: Section of the settings.
        closed: Whether registration is closed.
        admin_id: Identifier of the admin user given.
        token: Access token given.
    """
    if closed:
        close(app, section)
    with app.app_context(), pytest.raises(Unauthorized):
        check_registration(section, admin_id, token)
