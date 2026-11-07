"""Tests for the /users endpoint."""

import logging
import string
from unittest.mock import MagicMock

from flask import Flask
from foca.models.config import MongoConfig
import mongomock
from pymongo.errors import DuplicateKeyError
import pytest
from werkzeug.exceptions import InternalServerError, Unauthorized

from pubgrade.errors.exceptions import (
    NameNotFound,
    RegistrationDisabled,
    UserNotFound,
)
from pubgrade.modules.endpoints.users import (
    delete_user,
    get_users,
    register_user,
    sanitise_text,
    toggle_user_status,
)
from tests.helpers import foca_config, set_foca
from tests.mock_data import (
    ENDPOINT_CONFIG,
    MOCK_ADMIN_USER_1,
    MOCK_SUBSCRIPTION_INFO,
    MOCK_USER,
    MOCK_USER_DB,
    MONGO_CONFIG,
)


class TestUsers:
    """Tests for the user controllers."""

    app = Flask(__name__)

    def setup(self) -> None:
        """Prepare the configuration with a user and an admin user."""
        set_foca(self.app, db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
        foca_config(self.app).db.dbs["pubgradeStore"].collections[
            "users"
        ].client = mongomock.MongoClient().db.collection
        foca_config(self.app).db.dbs["pubgradeStore"].collections[
            "users"
        ].client.insert_one(MOCK_USER_DB)
        foca_config(self.app).db.dbs["pubgradeStore"].collections[
            "admin_users"
        ].client = mongomock.MongoClient().db.collection
        foca_config(self.app).db.dbs["pubgradeStore"].collections[
            "admin_users"
        ].client.insert_one(MOCK_ADMIN_USER_1)

    def test_register_user(self) -> None:
        """A registered user gets an identifier, a token and its name."""
        self.setup()
        with self.app.app_context():
            name = "Akash Saini"
            response = register_user({"name": name})
            assert "uid" in response
            assert "user_access_token" in response
            assert "name" in response
            assert sanitise_text(name) == response["name"]

    def test_register_user_charsets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Identifiers and tokens use the characters the settings name.

        Args:
            monkeypatch: Fixture to change the settings.
        """
        self.setup()
        endpoints = foca_config(self.app).endpoints
        monkeypatch.setitem(endpoints["user"], "uid_charset", "string.ascii_uppercase")
        monkeypatch.setitem(endpoints["access_token"], "charset", ["x", "y"])
        with self.app.app_context():
            response = register_user({"name": "Name"})
        assert len(response["uid"]) == 6
        assert set(response["uid"]) <= set(string.ascii_uppercase)
        assert len(response["user_access_token"]) == 32
        assert set(response["user_access_token"]) <= {"x", "y"}

    def test_register_user_logs_no_token(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Log messages name the new user, without its token.

        Args:
            caplog: Fixture to capture log messages.
        """
        self.setup()
        caplog.set_level(logging.DEBUG)
        with self.app.app_context():
            response = register_user({"name": "Name"})
        assert response["uid"] in caplog.text
        assert response["user_access_token"] not in caplog.text

    def test_register_user_closed(self) -> None:
        """Registration can be closed by configuration."""
        self.setup()
        foca_config(self.app).endpoints["user"]["registration_enabled"] = False
        with self.app.app_context(), pytest.raises(RegistrationDisabled):
            register_user({"name": "Name"})

    def test_register_user_keyerror(self) -> None:
        """Registration without a name fails."""
        self.setup()
        with self.app.app_context(), pytest.raises(NameNotFound):
            register_user({"wrong_name_key": "Akash Saini"})

    def test_register_user_duplicate_key_error(self) -> None:
        """A duplicate key on insertion is an internal error."""
        app = Flask(__name__)
        set_foca(
            app,
            db=MongoConfig(**MONGO_CONFIG),
            endpoints=ENDPOINT_CONFIG,
        )
        mock_resp = MagicMock(side_effect=DuplicateKeyError(""))
        foca_config(app).db.dbs["pubgradeStore"].collections[
            "users"
        ].client = MagicMock()
        foca_config(app).db.dbs["pubgradeStore"].collections[
            "users"
        ].client.insert_one = mock_resp
        with app.app_context(), pytest.raises(InternalServerError):
            register_user({"name": "Akash Saini"})

    def test_delete_user(self) -> None:
        """A user can delete itself."""
        self.setup()
        foca_config(self.app).db.dbs["pubgradeStore"].collections[
            "subscriptions"
        ].client = mongomock.MongoClient().db.collection
        foca_config(self.app).db.dbs["pubgradeStore"].collections[
            "subscriptions"
        ].client.insert_one(MOCK_SUBSCRIPTION_INFO)
        with self.app.app_context():
            response = delete_user(
                uid=MOCK_USER["uid"],
                user_access_token=MOCK_USER["user_access_token"],
            )
            assert response == "User deleted successfully."

    def test_delete_user_user_not_found(self) -> None:
        """Deleting an unknown user fails."""
        self.setup()
        foca_config(self.app).db.dbs["pubgradeStore"].collections[
            "subscriptions"
        ].client = mongomock.MongoClient().db.collection
        foca_config(self.app).db.dbs["pubgradeStore"].collections[
            "subscriptions"
        ].client.insert_one(MOCK_SUBSCRIPTION_INFO)
        with self.app.app_context(), pytest.raises(UserNotFound):
            delete_user(
                uid="wrong_uid",
                user_access_token=MOCK_USER["user_access_token"],
            )

    def test_delete_user_unauthorized(self) -> None:
        """Deleting a user with a wrong token fails."""
        self.setup()
        foca_config(self.app).db.dbs["pubgradeStore"].collections[
            "subscriptions"
        ].client = mongomock.MongoClient().db.collection
        foca_config(self.app).db.dbs["pubgradeStore"].collections[
            "subscriptions"
        ].client.insert_one(MOCK_SUBSCRIPTION_INFO)
        with self.app.app_context(), pytest.raises(Unauthorized):
            delete_user(
                uid=MOCK_USER["uid"],
                user_access_token="wrong_access_token",
            )

    def test_delete_key_error(self) -> None:
        """A user without subscriptions can be deleted."""
        set_foca(self.app, db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
        foca_config(self.app).db.dbs["pubgradeStore"].collections[
            "users"
        ].client = mongomock.MongoClient().db.collection
        foca_config(self.app).db.dbs["pubgradeStore"].collections[
            "users"
        ].client.insert_one(MOCK_USER)
        foca_config(self.app).db.dbs["pubgradeStore"].collections[
            "subscriptions"
        ].client = mongomock.MongoClient().db.subscriptions
        with self.app.app_context():
            response = delete_user(
                uid=MOCK_USER["uid"],
                user_access_token=MOCK_USER["user_access_token"],
            )
            assert response == "User deleted successfully."

    def test_get_users(self) -> None:
        """Admin users can list the users."""
        self.setup()
        with self.app.app_context():
            admin_uid = MOCK_ADMIN_USER_1["uid"]
            user_access_token = MOCK_ADMIN_USER_1["user_access_token"]
            response = get_users(admin_uid, user_access_token)
            assert response[0]["name"] == "Akash Saini"
            assert isinstance(response, list)

    def test_get_users_user_not_found(self) -> None:
        """Listing users as an unknown admin user fails."""
        self.setup()
        with self.app.app_context(), pytest.raises(UserNotFound):
            get_users("wrong_uid", "wrong_user_access_token")

    def test_get_users_unauthorized(self) -> None:
        """Listing users with a wrong token fails."""
        self.setup()
        with self.app.app_context():
            admin_uid = MOCK_ADMIN_USER_1["uid"]
            with pytest.raises(Unauthorized):
                get_users(admin_uid, "wrong_user_access_token")

    def test_toggle_user_status_false(self) -> None:
        """Admin users can unverify a user."""
        self.setup()
        with self.app.app_context():
            admin_uid = MOCK_ADMIN_USER_1["uid"]
            user_access_token = MOCK_ADMIN_USER_1["user_access_token"]
            response = toggle_user_status(
                admin_uid, user_access_token, MOCK_USER_DB["uid"], False
            )
            assert response == "User unverified successfully."

    def test_toggle_user_status_true(self) -> None:
        """Admin users can verify a user."""
        self.setup()
        with self.app.app_context():
            admin_uid = MOCK_ADMIN_USER_1["uid"]
            user_access_token = MOCK_ADMIN_USER_1["user_access_token"]
            response = toggle_user_status(
                admin_uid, user_access_token, MOCK_USER_DB["uid"], True
            )
            assert response == "User verified successfully."

    def test_toggle_user_status_superuser_not_found(self) -> None:
        """Changing a status as an unknown admin user fails."""
        self.setup()
        with self.app.app_context(), pytest.raises(UserNotFound):
            toggle_user_status(
                "wrong_uid",
                "wrong_user_access_token",
                MOCK_USER_DB["uid"],
                False,
            )

    def test_toggle_user_status_unauthorized(self) -> None:
        """Changing a status with a wrong token fails."""
        self.setup()
        with self.app.app_context():
            admin_uid = MOCK_ADMIN_USER_1["uid"]
            with pytest.raises(Unauthorized):
                toggle_user_status(
                    admin_uid,
                    "wrong_user_access_token",
                    MOCK_USER_DB["uid"],
                    False,
                )

    def test_toggle_user_status_user_not_found(self) -> None:
        """Changing the status of an unknown user fails."""
        self.setup()
        with self.app.app_context():
            admin_uid = MOCK_ADMIN_USER_1["uid"]
            user_access_token = MOCK_ADMIN_USER_1["user_access_token"]
            with pytest.raises(UserNotFound):
                toggle_user_status(admin_uid, user_access_token, "wrong_uid", False)
